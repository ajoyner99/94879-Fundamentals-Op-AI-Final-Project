"""
scripts/b1_size_comparison.py

Script to compare before and after for Ana's baseline experiment - testing time at incremental pre-seeded parquet files.

Reruns the starting-file-size experiment for BOTH saving methods:
  - single: starter-kit behavior (every flush rereads + rewrites one growing file)
  - parts:  B1 intervention (every flush writes only its new rows to a new part file)

For each starting history size (0, 1,000, 10,000, 50,000 rows) and each mode, the
featurizer processes the SAME 1,000 messages (= 40 flushes of 25 rows), and we
record the parquet save time from its [timing] lines.

How "the same 1,000 messages" is guaranteed:
  1. The script replays the workload into Kafka ONCE at the start, noting the
     offset where those messages begin (START).
  2. Before every run it resets the featurizer's bookmark (offset) to START.
  So every run reads exactly the same messages from the same position.

Prediction if the hypothesis is right:
  - single: save time per flush grows with starting history (as measured before)
  - parts:  save time per flush stays roughly flat across starting history
If parts still grows clearly with starting history, the hypothesis is not supported.

Starting files: made beforehand with the size-file script
(data/processed/b1_size_small|medium|large.parquet). Size 0 = no history.

Usage (from the project folder, Docker stack running, nothing else running):
    python scripts/b1_size_comparison.py --tag t1
    python scripts/b1_size_comparison.py --tag t1 --repeats 3
Results: printed table + data/b1_runs/sizes_<tag>.csv
"""
import argparse
import csv
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
WORKLOAD = "data/sample/sample_ticks_long.jsonl"
MESSAGES = 1000          # rows to process per run (1000 / 25 = 40 flushes)
SIZES = {                # starting history: rows -> seed file (None = empty)
    0: None,
    1_000: "data/processed/b1_size_small.parquet",
    10_000: "data/processed/b1_size_medium.parquet",
    50_000: "data/processed/b1_size_large.parquet",
}


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


def check_featurizer_stopped():
    state = group_state()
    if state and state[3]:
        stop("A featurizer is still connected. Stop it (Ctrl+C in its terminal) and rerun.")


def reset_to(offset):
    check_featurizer_stopped()
    kafka(["--group", GROUP, "--topic", TOPIC, "--reset-offsets",
           "--to-offset", str(offset), "--execute"])
    state = group_state()
    if not state or state[0] != offset:
        stop(f"Offset reset to {offset} failed (got {state}).")


def load_workload_once():
    """Replay the workload once and return the offset where it starts."""
    check_featurizer_stopped()
    state = group_state()
    if not state or state[1] is None:
        stop("Could not read the topic's log-end offset. Is the Docker stack running?")
    start = state[1]
    print(f"  loading workload into Kafka once (starts at offset {start})...")
    subprocess.run([sys.executable, "scripts/replay.py", "--file", WORKLOAD, "--rate", "4000"])
    end = group_state()[1]
    print(f"  workload loaded: offsets {start} to {end} ({end - start} messages)")
    if end - start < MESSAGES * 1.2:
        stop("Not enough messages were loaded to cover 1,000 feature rows.")
    return start


def prepare_start(mode, size, path):
    seed = SIZES[size]
    if mode == "single":
        if seed:
            shutil.copyfile(seed, path)
    else:
        os.makedirs(path)
        if seed:
            shutil.copyfile(seed, os.path.join(path, "part-000000.parquet"))
    rows = count_rows(path)
    if rows != size:
        stop(f"{path} starts with {rows} rows, expected {size}.")


def parse_log(log_path, mode):
    """Per-flush save times from the featurizer's [timing] lines."""
    with open(log_path, encoding="utf-8", errors="replace") as f:
        text = f.read()
    if f"parquet_mode={mode}" not in text:
        stop(f"{log_path} does not show parquet_mode={mode}. Is the updated featurizer.py in place?")
    return [float(x) for x in re.findall(r"parquet_last=([\d.]+)s", text)]


def run_one(mode, size, rep, start_offset, run_dir):
    name = f"{mode}_{size}_r{rep}"
    path = os.path.join(run_dir, name + (".parquet" if mode == "single" else "_parts"))
    log_path = os.path.join(run_dir, f"featurizer_{name}.log")

    reset_to(start_offset)
    prepare_start(mode, size, path)

    with open(log_path, "w") as log:
        proc = subprocess.Popen([sys.executable, "-u", "features/featurizer.py",
                                 "--parquet_mode", mode, "--parquet_path", path,
                                 "--max_messages", str(MESSAGES)],
                                stdout=log, stderr=subprocess.STDOUT)
        try:
            proc.wait(timeout=180)
        except subprocess.TimeoutExpired:
            proc.terminate()
            proc.wait()
            stop(f"Featurizer did not finish {MESSAGES} rows in 180 s. See {log_path}")

    times = parse_log(log_path, mode)
    added = count_rows(path) - size
    if added != MESSAGES or len(times) != MESSAGES // 25:
        stop(f"{name}: added {added} rows and {len(times)} flushes "
             f"(expected {MESSAGES} and {MESSAGES // 25}). See {log_path}")
    row = {"mode": mode, "start_rows": size, "repeat": rep, "flushes": len(times),
           "parquet_total_s": round(sum(times), 4),
           "avg_per_flush_s": round(statistics.mean(times), 5),
           "rows_added": added}
    print(f"  {mode:<7}{size:>8,} rows  r{rep}: total {row['parquet_total_s']:.3f} s, "
          f"avg {row['avg_per_flush_s']:.4f} s/flush")
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True, help="short name for this set of runs, e.g. t1")
    ap.add_argument("--repeats", type=int, default=2, help="runs per mode x size (default 2)")
    args = ap.parse_args()

    for f in ["features/featurizer.py", "features/parquet_parts.py", "scripts/replay.py", WORKLOAD]:
        if not os.path.exists(f):
            stop(f"{f} not found. Run from the project folder with all files in place.")
    for size, seed in SIZES.items():
        if seed and count_rows(seed) != size:
            stop(f"{seed} should have {size} rows. Recreate the size files first.")

    run_dir = os.path.join("data", "processed", f"b1_sizes_{args.tag}")
    if os.path.exists(run_dir):
        stop(f"{run_dir} already exists. Use a new --tag.")
    os.makedirs(run_dir)
    os.makedirs(os.path.join("data", "b1_runs"), exist_ok=True)

    start_offset = load_workload_once()

    rows = []
    for rep in range(1, args.repeats + 1):
        # alternate which mode goes first, so run order can't explain a difference
        modes = ["single", "parts"] if rep % 2 else ["parts", "single"]
        for size in SIZES:
            for mode in modes:
                rows.append(run_one(mode, size, rep, start_offset, run_dir))

    out_csv = os.path.join("data", "b1_runs", f"sizes_{args.tag}.csv")
    with open(out_csv, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    print(f"\nSummary (median of {args.repeats} repeats; same {MESSAGES} messages, "
          f"{MESSAGES // 25} flushes each)")
    print(f"{'start rows':>10} | {'single total':>12} {'s/flush':>8} | {'parts total':>11} {'s/flush':>8}")
    for size in SIZES:
        cells = []
        for mode in ("single", "parts"):
            r = [x for x in rows if x["mode"] == mode and x["start_rows"] == size]
            cells.append((statistics.median(x["parquet_total_s"] for x in r),
                          statistics.median(x["avg_per_flush_s"] for x in r)))
        print(f"{size:>10,} | {cells[0][0]:>11.3f}s {cells[0][1]:>8.4f} | "
              f"{cells[1][0]:>10.3f}s {cells[1][1]:>8.4f}")
    print(f"\nAll runs saved to {out_csv}; data and logs in {run_dir}")


if __name__ == "__main__":
    main()
