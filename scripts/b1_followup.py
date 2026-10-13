"""
scripts/b1_followup.py

B1 follow-up experiments requested in the presentation feedback, run back to back
on one machine in one session so the results are comparable with each other.

Runs (each: same workload, same ~11,750-row starting history, lag reset to 0,
rate 4000, 11,750 rows processed) using scripts/b1_before_after.run_one:
    1. single, 25-row flush   (starter-kit behavior: "before")
    2. parts,  25-row flush   (the intervention: "after")
    3. parts, 100-row flush   (flush-size follow-up)
    4. parts, 500-row flush   (flush-size follow-up)

Then, on the outputs of those runs:
    - Lag, saves, commits, files: peak lag, lag samples, number of files, number of
      saves and offset commits, total save and commit time (feedback: "report lag,
      file count and commits").
    - Identity: every output must hold exactly the same rows and values as run 1
      (feedback: "show that output rows are identical before and after").
    - Reader cost: time pd.read_parquet(output), the call training and the drift report
      make, for every output; compact the 25-row part folder into one file and time
      the compaction and the read of the compacted file; optionally time the full
      drift report on parts vs compacted (feedback: "the slowdown from many small
      files is asserted, not measured ... show compaction restoring it").

Usage (from the project folder, Docker stack running, nothing else running):
    python scripts/b1_followup.py --tag ana1 --seed data/processed/inst_rate4000_t1_ana.parquet
    python scripts/b1_followup.py --tag ana2 --seed data/processed/inst_rate4000_t1_ana.parquet --reverse

--reverse runs the same four configurations in the opposite order, so run order
(laptop warm-up) cannot explain the result. Each pass takes about 8-10 minutes.

Output: data/b1_runs/followup_<tag>/ with summary.csv, reader_cost.csv,
results.md (tables to paste into the memo) and lag_over_time.png.
"""
import argparse
import csv
import glob
import os
import statistics
import subprocess
import sys
import time

from pathlib import Path

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import b1_before_after as bba  # noqa: E402
from b1_check_identity import compare, load  # noqa: E402
from features.compact_parts import compact  # noqa: E402

CONFIGS = [("single", 25), ("parts", 25), ("parts", 100), ("parts", 500)]


# ---------- per-run metrics ----------

def read_text(path):
    raw = open(path, "rb").read()
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16")
    return raw.decode("utf-8", errors="replace")


def log_metrics(log_path):
    text = read_text(log_path)
    timing = [l for l in text.splitlines() if l.startswith("[timing]")]
    if not timing:
        return {}
    fields = dict(p.split("=", 1) for p in timing[-1].split()[1:] if "=" in p)
    sec = lambda k: float(fields[k].rstrip("s"))
    stages = {k: sec(k) for k in ("parse", "features", "window", "produce", "parquet_total", "commit_total")}
    total = sum(stages.values())
    flush_saves = len(timing)
    final_commit = "reached max_messages" in text
    return {
        "saves_with_timing": flush_saves,
        "offset_commits": flush_saves + (1 if final_commit else 0),
        "save_total_s": round(stages["parquet_total"], 3),
        "commit_total_s": round(stages["commit_total"], 3),
        "save_ms_per_flush": round(1000 * stages["parquet_total"] / flush_saves, 2),
        "save_share": round(stages["parquet_total"] / total, 3) if total else None,
        "commit_share": round(stages["commit_total"] / total, 3) if total else None,
        "other_share": round(1 - (stages["parquet_total"] + stages["commit_total"]) / total, 3) if total else None,
        "measured_total_s": round(total, 3),
    }


def lag_metrics(label):
    files = sorted(glob.glob(os.path.join("data", "b1_runs", f"lag_{label}_[0-9]*.csv")))
    if not files:
        return {"lag_csv": None}
    with open(files[-1], newline="") as f:
        rows = [r for r in csv.DictReader(f) if r["lag"]]
    lags = [int(r["lag"]) for r in rows]
    arrivals = [float(r["arrival_rate_per_s"]) for r in rows if r["arrival_rate_per_s"] not in ("", "0.0")]
    loaded = [l for l in lags if l > 0]
    return {
        "lag_csv": files[-1],
        "peak_lag": max(lags) if lags else None,
        "lag_samples_nonzero": " ".join(str(l) for l in loaded),
        "final_lag": lags[-1] if lags else None,
        "arrival_peak_per_s": round(max(arrivals)) if arrivals else None,
        "arrival_mean_per_s": round(statistics.mean(arrivals)) if arrivals else None,
    }


def file_count(path):
    return len(glob.glob(os.path.join(path, "part-*.parquet"))) if os.path.isdir(path) else 1


# ---------- reader cost ----------

def time_call(fn, repeats):
    fn()  # warm-up, not timed
    times = []
    for _ in range(repeats):
        t0 = time.perf_counter()
        fn()
        times.append(time.perf_counter() - t0)
    return statistics.median(times), min(times), max(times)


def drift_report_seconds(features, out_html, repeats):
    cmd = [sys.executable, "monitoring/drift_report.py", "--features", features, "--out", out_html]
    times = []
    for _ in range(repeats):
        t0 = time.perf_counter()
        r = subprocess.run(cmd, capture_output=True, text=True)
        times.append(time.perf_counter() - t0)
        if r.returncode != 0:
            print(f"  [WARNING] drift report failed on {features}:\n{r.stderr[-600:]}")
            return None
    return statistics.median(times)


def md_table(df):
    """Markdown table without needing the optional 'tabulate' package."""
    cells = [[("" if pd.isna(v) else str(v)) for v in row] for row in df.itertuples(index=False)]
    lines = ["| " + " | ".join(map(str, df.columns)) + " |", "|" + "---|" * len(df.columns)]
    return "\n".join(lines + ["| " + " | ".join(c) + " |" for c in cells])


# ---------- main ----------

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tag", required=True, help="new short name for this pass, e.g. ana1")
    ap.add_argument("--seed", required=True, help="starting-history file with ~11,750 rows")
    ap.add_argument("--reverse", action="store_true", help="run the four configurations in reverse order")
    ap.add_argument("--read_repeats", type=int, default=5)
    ap.add_argument("--skip_drift_report", action="store_true", help="skip the end-to-end drift report timing")
    args = ap.parse_args()

    for f in ("features/featurizer.py", "features/parquet_parts.py", "features/compact_parts.py", args.seed):
        if not os.path.exists(f):
            bba.stop(f"{f} not found. Run from the project folder.")
    if "--flush_every" not in open("features/featurizer.py").read():
        bba.stop("features/featurizer.py has no --flush_every option. Copy in the updated featurizer.py.")
    bba.SEED = args.seed
    out_dir = os.path.join("data", "b1_runs", f"followup_{args.tag}")
    os.makedirs(out_dir, exist_ok=True)

    configs = list(reversed(CONFIGS)) if args.reverse else CONFIGS
    runs = []
    for i, (mode, flush) in enumerate(configs):
        print(f"\n##### run {i + 1} of {len(configs)}: {mode}, {flush}-row flush #####")
        runs.append(bba.run_one(mode, args.tag, flush))
        if i < len(configs) - 1:
            print("\n  pausing 15 s before the next run...")
            time.sleep(15)
    runs.sort(key=lambda r: CONFIGS.index((r["mode"], r["flush_every"])))

    # --- lag, saves, commits, files ---
    summary = []
    for r in runs:
        row = {"run": r["label"], "mode": r["mode"], "flush_every": r["flush_every"],
               "start_rows": r["start_rows"], "end_rows": r["end_rows"],
               "rows_added": r["end_rows"] - r["start_rows"], "files": file_count(r["path"])}
        row.update(lag_metrics(r["label"]))
        row.update(log_metrics(r["feat_log"]))
        summary.append(row)

    # --- identity against run 1 (single, 25) ---
    reference = next(r for r in runs if r["mode"] == "single" and r["flush_every"] == 25)
    ref_df, _ = load(reference["path"])
    for row, r in zip(summary, runs):
        other, _ = load(r["path"])
        row["identical_to_single_25"] = compare(ref_df, other)["identical"]
    pd.DataFrame(summary).to_csv(os.path.join(out_dir, "summary.csv"), index=False)

    # --- reader cost ---
    print("\n##### timing readers #####")
    reader = []
    for r in runs:
        med, lo, hi = time_call(lambda p=r["path"]: pd.read_parquet(p), args.read_repeats)
        reader.append({"what": f"read {r['mode']} {r['flush_every']}-row output", "files": file_count(r["path"]),
                       "median_s": round(med, 4), "min_s": round(lo, 4), "max_s": round(hi, 4)})
    parts25 = next(r for r in runs if r["mode"] == "parts" and r["flush_every"] == 25)
    compacted = os.path.join(out_dir, "parts25_compacted.parquet")
    med, lo, hi = time_call(lambda: compact(Path(parts25["path"]), Path(compacted)), args.read_repeats)
    reader.append({"what": "compact 25-row parts -> 1 file", "files": file_count(parts25["path"]),
                   "median_s": round(med, 4), "min_s": round(lo, 4), "max_s": round(hi, 4)})
    med, lo, hi = time_call(lambda: pd.read_parquet(compacted), args.read_repeats)
    reader.append({"what": "read compacted file", "files": 1,
                   "median_s": round(med, 4), "min_s": round(lo, 4), "max_s": round(hi, 4)})
    compacted_ok = compare(pd.read_parquet(parts25["path"]), pd.read_parquet(compacted))["identical"]

    if not args.skip_drift_report:
        print("  running the drift report on the part folder and on the compacted file (3 times each)...")
        tmp_html = os.path.join(out_dir, "drift_report_timing.html")
        for label, path in (("drift report on 25-row parts", parts25["path"]),
                            ("drift report on compacted file", compacted)):
            s = drift_report_seconds(path, tmp_html, 3)
            reader.append({"what": label, "files": file_count(path),
                           "median_s": round(s, 3) if s is not None else None, "min_s": None, "max_s": None})
    pd.DataFrame(reader).to_csv(os.path.join(out_dir, "reader_cost.csv"), index=False)

    # --- tables for the memo ---
    s = pd.DataFrame(summary)
    lag_table = s[["mode", "flush_every", "peak_lag", "lag_samples_nonzero", "final_lag", "files",
                   "saves_with_timing", "offset_commits", "save_ms_per_flush", "save_total_s",
                   "commit_total_s", "rows_added", "identical_to_single_25"]]
    share_table = s[["mode", "flush_every", "save_share", "commit_share", "other_share", "measured_total_s"]]
    with open(os.path.join(out_dir, "results.md"), "w", encoding="utf-8") as f:
        f.write(f"# B1 follow-up: {args.tag} (seed: {args.seed}, order: {'reversed' if args.reverse else 'normal'})\n\n")
        f.write("## Lag, files, saves and commits\n\n" + md_table(lag_table) + "\n\n")
        f.write("## Where the featurizer's time went\n\n" + md_table(share_table) + "\n\n")
        f.write("## Reader cost (warm cache, median)\n\n" + md_table(pd.DataFrame(reader)) + "\n\n")
        f.write(f"Compacted file identical to the part folder: {compacted_ok}\n")

    # --- lag-over-time figure ---
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(8, 4))
        for row in summary:
            if not row.get("lag_csv"):
                continue
            d = pd.read_csv(row["lag_csv"])
            start = d.index[d["lag"] > 0].min()
            t0 = d.loc[max(start - 1, 0), "elapsed_s"] if pd.notna(start) else 0
            name = "before: single file" if row["mode"] == "single" else f"after: parts, {row['flush_every']}-row flush"
            ax.plot(d["elapsed_s"] - t0, d["lag"], marker="o", ms=3,
                    label=f"{name} (peak {row['peak_lag']})")
        ax.set_xlim(left=-3)
        ax.set_xlabel("Seconds since lag first rose")
        ax.set_ylabel("Lag (messages waiting)")
        ax.set_title(f"Same workload, same 11,750-row start, one machine ({args.tag})")
        ax.legend(frameon=False, fontsize=8)
        ax.spines[["top", "right"]].set_visible(False)
        fig.tight_layout()
        fig.savefig(os.path.join(out_dir, "lag_over_time.png"), dpi=200)
    except Exception as e:  # the figure is a convenience; the CSVs are the evidence
        print(f"  (figure skipped: {e})")

    print("\n" + open(os.path.join(out_dir, "results.md"), encoding="utf-8").read())
    print(f"Everything saved in {out_dir}")


if __name__ == "__main__":
    main()
