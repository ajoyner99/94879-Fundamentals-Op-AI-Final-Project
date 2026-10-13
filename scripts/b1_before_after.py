"""
scripts/b1_before_after.py

Script for testing Lauren's baseline experimentation - preseeding parquet with 11750 rows.

Runs the B1 before/after comparison back to back, under the same conditions:
  BEFORE: featurizer starts with ~11,750 rows of history, --parquet_mode single
          (starter-kit behavior: every flush rereads + rewrites one growing file)
  AFTER:  featurizer starts with the SAME ~11,750 rows of history, --parquet_mode parts
          (intervention: every flush writes only its new rows to a new part file)

The only thing that differs between the two runs is --parquet_mode.
Same seed rows, same workload, same rate, same 11,750 rows to process.

For each run it: checks the featurizer is stopped, resets offsets (lag 0), prepares
the starting data and checks its row count, starts the lag recorder, starts the
featurizer, waits until it is connected + 10 s, runs the replay, waits for the
featurizer to finish, stops the recorder, checks the final row count, and prints
a summary (lag + per-flush parquet time early vs late in the run).

Usage (from the project folder, Docker stack running, nothing else running):
    python scripts/b1_before_after.py --tag t1              # BEFORE first, then AFTER
    python scripts/b1_before_after.py --tag t2 --reverse    # AFTER first, then BEFORE
Running it twice with opposite order checks that "which run went first" (laptop
warming up, caches, etc.) is not what explains the difference.
"""
import argparse
import csv
import glob
import os
import re
import shutil
import statistics
import subprocess
import sys
import time

CONTAINER = "broker"
TOOL = "/opt/kafka/bin/kafka-consumer-groups.sh"
BOOTSTRAP = "localhost:9092"
GROUP = "featurizer_group"
TOPIC = "ticks.raw"
SEED = "data/processed/features_drain_test_t1.parquet"
WORKLOAD = "data/sample/sample_ticks_long.jsonl"
RATE = "4000"
ROWS_PER_RUN = 11750


def kafka(args):
    cmd = ["docker", "exec", CONTAINER, TOOL, "--bootstrap-server", BOOTSTRAP] + args
    return subprocess.run(cmd, capture_output=True, text=True, timeout=60).stdout


def group_state():
    """Returns (current_offset, log_end_offset, lag, consumer_active) for our group/topic."""
    for line in kafka(["--describe", "--group", GROUP]).splitlines():
        p = line.split()
        if len(p) >= 6 and p[0] == GROUP and p[1] == TOPIC:
            to_int = lambda s: int(s) if s.isdigit() else None
            return to_int(p[3]), to_int(p[4]), to_int(p[5]), len(p) >= 7 and p[6] != "-"
    return None


def count_rows(path):
    """Works for a single .parquet file AND for a folder of part files."""
    import pandas as pd
    return len(pd.read_parquet(path)) if os.path.exists(path) else 0


def stop(msg):
    print(f"\n[STOPPED] {msg}")
    sys.exit(1)


def reset_offsets():
    state = group_state()
    if state and state[3]:
        stop("The featurizer is still connected. Stop it (Ctrl+C in its terminal) and rerun.")
    kafka(["--group", GROUP, "--topic", TOPIC, "--reset-offsets", "--to-latest", "--execute"])
    state = group_state()
    if not state or state[2] != 0:
        stop(f"Reset did not bring lag to 0 (got {state}).")
    print(f"  reset done: offset {state[1]}, lag 0")


def prepare_start(mode, path):
    """Put exactly the seed rows in place, in the form this mode expects."""
    if os.path.exists(path):
        stop(f"{path} already exists. Use a new --tag (or move it) so no rows get mixed in.")
    if mode == "single":
        shutil.copyfile(SEED, path)                       # one file
    else:
        os.makedirs(path)                                 # folder with seed as part 0
        shutil.copyfile(SEED, os.path.join(path, "part-000000.parquet"))
    rows = count_rows(path)
    if not 11000 <= rows <= 12500:
        stop(f"{path} starts with {rows} rows, expected ~11,750. Check the seed.")
    return rows


def summarize_lag(label):
    files = sorted(glob.glob(os.path.join("data", "b1_runs", f"lag_{label}_*.csv")))
    if not files:
        return "  (recorder CSV not found)"
    with open(files[-1], newline="") as f:
        rows = [r for r in csv.DictReader(f) if r["lag"]]
    lags = [int(r["lag"]) for r in rows]
    arrivals = [float(r["arrival_rate_per_s"]) for r in rows
                if r["arrival_rate_per_s"] not in ("", "0.0")]
    return (f"  lag CSV: {files[-1]}\n"
            f"  lag samples: {', '.join(str(x) for x in lags) or 'n/a'}\n"
            f"  max lag during run: {max(lags) if lags else 'n/a'}\n"
            f"  arrival rate samples: {', '.join(f'{a:.0f}' for a in arrivals) or 'n/a'}")


def summarize_flush_times(log_path):
    """Per-flush parquet time early vs late in the run, from the [timing] lines.
    BEFORE should get slower as the file grows; AFTER should stay roughly flat."""
    times = []
    with open(log_path, encoding="utf-8", errors="replace") as f:
        for line in f:
            m = re.search(r"parquet_last=([\d.]+)s", line)
            if m:
                times.append(float(m.group(1)))
    if len(times) < 40:
        return f"  only {len(times)} flush timings found in {log_path}"
    first, last = statistics.mean(times[:20]), statistics.mean(times[-20:])
    return (f"  flushes: {len(times)}, parquet total: {sum(times):.2f} s\n"
            f"  avg parquet time per flush: first 20 = {first:.4f} s, last 20 = {last:.4f} s")


def check_mode_in_log(log_path, mode):
    with open(log_path, encoding="utf-8", errors="replace") as f:
        if f"parquet_mode={mode}" not in f.read():
            print(f"  [WARNING] featurizer log does not show parquet_mode={mode}. "
                  "Is the updated featurizer.py in place?")


def run_one(mode, tag):
    label = f"{'before' if mode == 'single' else 'after'}_rate{RATE}_{tag}"
    path = (f"data/processed/features_{label}.parquet" if mode == "single"
            else f"data/processed/features_{label}_parts")
    print(f"\n=== {label}  (--parquet_mode {mode}) ===")

    reset_offsets()
    start_rows = prepare_start(mode, path)
    print(f"  starting data: {start_rows} rows at {path}")

    feat_log_path = os.path.join("data", "b1_runs", f"featurizer_{label}.log")
    recorder = featurizer = None
    try:
        rec_log = open(os.path.join("data", "b1_runs", f"recorder_{label}.log"), "w")
        recorder = subprocess.Popen([sys.executable, "scripts/b1_lag_recorder.py",
                                     "--label", label, "--interval", "3"],
                                    stdout=rec_log, stderr=subprocess.STDOUT)
        time.sleep(5)
        feat_log = open(feat_log_path, "w")
        featurizer = subprocess.Popen([sys.executable, "-u", "features/featurizer.py",
                                       "--parquet_mode", mode,
                                       "--parquet_path", path,
                                       "--max_messages", str(ROWS_PER_RUN)],
                                      stdout=feat_log, stderr=subprocess.STDOUT)

        print("  waiting for featurizer to connect...")
        for _ in range(30):
            state = group_state()
            if state and state[3]:
                break
            time.sleep(2)
        else:
            stop(f"Featurizer never connected. Check {feat_log_path}")
        print("  featurizer connected; waiting 10 s")
        time.sleep(10)

        print(f"  replay running at --rate {RATE}...")
        subprocess.run([sys.executable, "scripts/replay.py", "--file", WORKLOAD, "--rate", RATE])

        try:
            featurizer.wait(timeout=180)
            print("  featurizer finished on its own")
        except subprocess.TimeoutExpired:
            print(f"  [WARNING] featurizer did not reach {ROWS_PER_RUN} rows in 180 s; stopping it")
            featurizer.terminate()

        time.sleep(10)  # let the recorder capture the settled state
    finally:
        for proc in (featurizer, recorder):
            if proc and proc.poll() is None:
                proc.terminate()
                proc.wait()

    end_rows = count_rows(path)
    added = end_rows - start_rows
    print(f"  ending data: {end_rows} rows (added {added}"
          f"{'' if added == ROWS_PER_RUN else f' <-- expected {ROWS_PER_RUN}, check this run'})")
    if mode == "parts":
        n_parts = len(glob.glob(os.path.join(path, "part-*.parquet")))
        print(f"  part files: {n_parts}")
    check_mode_in_log(feat_log_path, mode)
    print(summarize_flush_times(feat_log_path))
    print(summarize_lag(label))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True, help="short name for this pair of runs, e.g. t1")
    ap.add_argument("--reverse", action="store_true", help="run AFTER first, then BEFORE")
    args = ap.parse_args()

    if not os.path.exists("features/featurizer.py"):
        stop("Run this from the project folder (where the features/ and scripts/ folders are).")
    if not os.path.exists("features/parquet_parts.py"):
        stop("features/parquet_parts.py is missing. Add it before running.")
    if not os.path.exists(SEED):
        stop(f"Seed {SEED} not found.")
    os.makedirs(os.path.join("data", "b1_runs"), exist_ok=True)

    modes = ["parts", "single"] if args.reverse else ["single", "parts"]
    for i, mode in enumerate(modes):
        run_one(mode, args.tag)
        if i == 0:
            print("\n  pausing 15 s before the next run...")
            time.sleep(15)
    print("\nAll done. Summaries are printed above; lag CSVs and logs are in data/b1_runs/.")


if __name__ == "__main__":
    main()
