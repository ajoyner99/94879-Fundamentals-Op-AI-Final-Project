"""
scripts/b1_log_analysis.py

Analysis only (no Kafka needed). Reads the outputs, featurizer logs and lag CSVs
from scripts/b1_followup.py runs and answers three review questions:

  1. Per-step timing in ms and %: parse, compute features, window, produce,
     save (Parquet), commit, for every run.
  2. Output fingerprints: a SHA-256 hash of each run's rows (sorted, all columns).
     Equal hashes = identical rows and values, not just equal counts.
  3. Save time while the replay was still sending vs after it stopped. The lag CSV
     shows when the replay ended (log-end offset stops rising) and how many
     messages the featurizer had committed by then; flushes before that point
     ran while the replay competed for the laptop.

Usage (from the project folder):
    python scripts/b1_log_analysis.py --tags ana1 ana2
Output: printed, and saved to data/b1_runs/followup_analysis.md
"""
import argparse
import csv
import glob
import os
import re
import statistics
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from b1_check_identity import canonical, fingerprint, load  # noqa: E402

STAGES = [("parse", "parse"), ("features", "compute features"), ("window", "window"),
          ("produce", "produce"), ("parquet_total", "save (Parquet)"), ("commit_total", "commit")]


def read_text(path):
    raw = open(path, "rb").read()
    return raw.decode("utf-16") if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else raw.decode("utf-8", errors="replace")


def timing_lines(log):
    return [l for l in read_text(log).splitlines() if l.startswith("[timing]")]


def fields(line):
    return dict(p.split("=", 1) for p in line.split()[1:] if "=" in p)


def md_table(rows, cols):
    out = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    out += ["| " + " | ".join(str(r.get(c, "")) for c in cols) + " |" for r in rows]
    return "\n".join(out)


def output_path(run, mode):
    return (f"data/processed/features_{run}.parquet" if mode == "single"
            else f"data/processed/features_{run}_parts")


def replay_end_rows(lag_csv, rows_per_message):
    """Rows the featurizer had committed when the replay stopped sending."""
    with open(lag_csv, newline="") as f:
        rows = [r for r in csv.DictReader(f) if r["current_offset"] and r["log_end_offset"]]
    if not rows:
        return None
    start = int(rows[0]["current_offset"])
    end_log = max(int(r["log_end_offset"]) for r in rows)
    first_full = next(r for r in rows if int(r["log_end_offset"]) == end_log)
    consumed = int(first_full["current_offset"]) - start
    return round(consumed * rows_per_message)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tags", nargs="+", required=True)
    ap.add_argument("--out", default="data/b1_runs/followup_analysis.md")
    args = ap.parse_args()

    stage_rows, hash_rows, contention_rows = [], [], []
    for tag in args.tags:
        summary_csv = f"data/b1_runs/followup_{tag}/summary.csv"
        if not os.path.exists(summary_csv):
            sys.exit(f"{summary_csv} not found. Run scripts/b1_followup.py --tag {tag} first.")
        summary = pd.read_csv(summary_csv)
        for _, s in summary.iterrows():
            run, mode, flush = s["run"], s["mode"], int(s["flush_every"])
            name = f"{tag} {mode} {flush}"
            log = f"data/b1_runs/featurizer_{run}.log"
            lines = timing_lines(log)
            last = fields(lines[-1])
            secs = {k: float(last[k].rstrip("s")) for k, _ in STAGES}
            total = sum(secs.values())
            row = {"run": name}
            for k, label in STAGES:
                row[label] = f"{1000 * secs[k]:,.0f} ms ({secs[k] / total:.1%})"
            row["total"] = f"{1000 * total:,.0f} ms"
            row["per row"] = f"{1000 * total / int(s['rows_added']):.3f} ms"
            stage_rows.append(row)

            df, n_files = load(output_path(run, mode))
            hash_rows.append({"run": name, "files": n_files, "rows": len(df),
                              "sha256 (first 16)": fingerprint(canonical(df))})

            per_flush = [float(fields(l)["parquet_last"].rstrip("s")) for l in lines]
            flush_rows = [int(fields(l)["rows"]) for l in lines]
            cut = replay_end_rows(s["lag_csv"], 11754 / 14076) if isinstance(s["lag_csv"], str) else None
            if cut:
                during = [t for t, r in zip(per_flush, flush_rows) if r <= cut]
                after = [t for t, r in zip(per_flush, flush_rows) if r > cut]
                contention_rows.append({
                    "run": name, "rows processed when replay ended": f"~{cut:,}",
                    "flushes during replay": len(during),
                    "median save during replay": f"{1000 * statistics.median(during):.1f} ms" if during else "",
                    "flushes after replay": len(after),
                    "median save after replay": f"{1000 * statistics.median(after):.1f} ms" if after else "",
                })

    stage_cols = ["run"] + [label for _, label in STAGES] + ["total", "per row"]
    text = "\n\n".join([
        "# B1 follow-up analysis",
        "## 1. Featurizer time by step (from the last [timing] line of each log)",
        md_table(stage_rows, stage_cols),
        "## 2. Output fingerprints (rows sorted on every column, then SHA-256)",
        md_table(hash_rows, ["run", "files", "rows", "sha256 (first 16)"]),
        "Equal fingerprints within a pass mean identical rows and values. Pass 1 and pass 2 "
        "process the same messages, so their fingerprints should also match each other.",
        "## 3. Save time while the replay was sending vs after it stopped",
        md_table(contention_rows, ["run", "rows processed when replay ended", "flushes during replay",
                                   "median save during replay", "flushes after replay",
                                   "median save after replay"]),
        "Rows at the cut are estimated from committed offsets (11,754 feature rows per 14,076 messages). "
        "In single mode the file keeps growing after the cut, so if saves are still FASTER after the replay "
        "stops, competition for the laptop during the replay outweighs file size.",
    ])
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(text + "\n")
    print(text)
    print(f"\nSaved to {args.out}")


if __name__ == "__main__":
    main()
