"""
scripts/b1_timing_breakdown.py

Reads the last [timing] line of each featurizer log and prints where the time went.
Handles logs saved by PowerShell's Tee-Object (UTF-16) as well as normal UTF-8 files.

Usage (from the project folder):
    python scripts/b1_timing_breakdown.py                      # all data/b1_runs/featurizer_*.log
    python scripts/b1_timing_breakdown.py path/to/some.log     # specific files
    python scripts/b1_timing_breakdown.py (Get-ChildItem data/b1_runs/3_drain_tests/featurizer_*.log) # data from specific dir
"""
import glob
import sys

STAGES = ["parquet_total", "commit_total", "parse", "features", "window", "produce"]


def read_text(path):
    raw = open(path, "rb").read()
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16")
    return raw.decode("utf-8", errors="replace")


def breakdown(path):
    lines = [l for l in read_text(path).splitlines() if l.startswith("[timing]")]
    if not lines:
        return None
    fields = dict(p.split("=") for p in lines[-1].split()[1:] if "=" in p)
    secs = {s: float(fields[s].rstrip("s")) for s in STAGES}
    total = sum(secs.values())
    other = total - secs["parquet_total"] - secs["commit_total"]
    return fields["rows"], total, secs["parquet_total"] / total, secs["commit_total"] / total, other / total


paths = sys.argv[1:] or sorted(glob.glob("data/b1_runs/featurizer_*.log"))
print(f"{'log file':55} {'rows':>6} {'total s':>8} {'parquet':>8} {'commit':>7} {'other':>6}")
for path in paths:
    result = breakdown(path)
    if result is None:
        print(f"{path:55} (no [timing] lines found)")
        continue
    rows, total, pq, cm, ot = result
    print(f"{path:55} {rows:>6} {total:>8.2f} {pq:>8.0%} {cm:>7.0%} {ot:>6.0%}")
