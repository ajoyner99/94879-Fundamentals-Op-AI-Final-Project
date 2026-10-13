"""
b1_make_figures.py - presentation figures for Challenge B1 (Falling Behind).

Run from the repo root, e.g.:
    python scripts/b1_make_figures.py --logs experiment2_lj_t1.txt experiment2_lj_t2_reverse.txt \
        --sizes-log Experiment1_postIntervention.txt

What it reads
  * Console logs you saved from b1_before_after.py (one or more files).
    From each run block it takes: mode, parquet total, first/last-20 flush time,
    max lag, the lag samples, and the path of that run's lag CSV.
  * The lag CSVs in data/b1_runs/ (found via the path printed in the log).
    If a CSV has a time column, figure 2 uses real seconds on the x-axis;
    if the CSV is missing, it falls back to the lag samples printed in the log.
  * data/b1_runs/sizes_<tag>.csv from b1_size_comparison.py (figure 1).
    If that CSV can't be read, it falls back to parsing --sizes-log.

What it writes (to --out, default figures/b1/)
  fig1_flush_cost_vs_file_size.png   diagnosis: cost per flush grows with file size (single only)
  fig2_lag_over_time_<tag>.png       lag over time, before vs after, one per tag
  fig3_max_lag.png                   max lag per run, both run orders
  fig4_parquet_total_time.png        total time spent writing parquet per run
  fig5_flush_time_first_vs_last.png  per-flush time at start vs end of each run
  fig6_mechanism.png                 diagram: rewrite-whole-file vs write-new-part
  b1_summary.csv                     the numbers behind figures 3-5

Requires: pandas, matplotlib.
"""

import argparse
import re
from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # write files, no window needed
import matplotlib.pyplot as plt
import pandas as pd

BEFORE_COLOR = "#c0392b"   # red  = single (before)
AFTER_COLOR = "#2471a3"    # blue = parts (after)
plt.rcParams.update({"font.size": 12, "axes.spines.top": False, "axes.spines.right": False})


# ----------------------------------------------------------------------------
# 1. Parse the console logs from b1_before_after.py
# ----------------------------------------------------------------------------
HEADER_RE = re.compile(r"^=== (\S+)\s+\(--parquet_mode (\w+)\) ===")


def read_text(path):
    raw = Path(path).read_bytes()
    for enc in ("utf-8", "utf-16", "cp1252"):  # PowerShell '>' redirects often save UTF-16
        try:
            text = raw.decode(enc)
            if "===" in text or "rows" in text:
                return text
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="ignore")


def parse_run_logs(log_paths):
    """Return one dict per run block found in the logs."""
    runs = []
    for log_path in log_paths:
        current = None
        order = 0
        for line in read_text(log_path).splitlines():
            line = line.strip()
            m = HEADER_RE.match(line)
            if m:
                order += 1
                name, mode = m.group(1), m.group(2)
                # name looks like before_rate4000_lj_t1 -> phase=before, tag=lj_t1
                parts = name.split("_", 2)
                current = {
                    "run": name,
                    "phase": parts[0],
                    "tag": parts[2] if len(parts) > 2 else name,
                    "mode": mode,
                    "order_in_log": order,
                    "log_file": Path(log_path).name,
                }
                runs.append(current)
                continue
            if current is None:
                continue
            if m := re.search(r"parquet total: ([\d.]+) s", line):
                current["parquet_total_s"] = float(m.group(1))
            if m := re.search(r"first 20 = ([\d.]+) s, last 20 = ([\d.]+) s", line):
                current["first20_s_per_flush"] = float(m.group(1))
                current["last20_s_per_flush"] = float(m.group(2))
            if m := re.search(r"max lag during run: (\d+)", line):
                current["max_lag"] = int(m.group(1))
            if m := re.search(r"lag samples: (.+)$", line):
                current["lag_samples"] = [int(x) for x in re.findall(r"\d+", m.group(1))]
            if m := re.search(r"lag CSV: (.+\.csv)", line):
                current["lag_csv"] = m.group(1).strip().replace("\\", "/")
            if m := re.search(r"ending data: (\d+) rows \(added (\d+)\)", line):
                current["rows_added"] = int(m.group(2))
    if not runs:
        raise SystemExit("No run blocks found in the logs. Check the --logs paths.")
    return runs


# ----------------------------------------------------------------------------
# 2. Read a lag CSV, guessing column names (prints what it picked)
# ----------------------------------------------------------------------------
def find_col(columns, must_contain, avoid=()):
    for c in columns:
        low = c.lower()
        if any(k in low for k in must_contain) and not any(a in low for a in avoid):
            return c
    return None


def load_lag_csv(path, repo_root):
    p = Path(path)
    if not p.is_absolute():
        p = repo_root / p
    if not p.exists():
        return None
    df = pd.read_csv(p)
    lag_col = find_col(df.columns, ["lag"], avoid=["max"])
    time_col = find_col(df.columns, ["elapsed", "seconds", "time", "ts", "t_s"])
    if lag_col is None:
        print(f"  ! {p.name}: no 'lag' column found (columns: {list(df.columns)}) - using log samples")
        return None
    if time_col is None:
        x = pd.Series(range(1, len(df) + 1))
        x_label = "Sample #"
    else:
        t = df[time_col]
        if not pd.api.types.is_numeric_dtype(t):
            t = pd.to_datetime(t, errors="coerce")
            t = (t - t.iloc[0]).dt.total_seconds()
        else:
            t = t - t.iloc[0]
            if t.max() > 10_000:  # looks like milliseconds
                t = t / 1000.0
        x = t
        x_label = "Seconds since monitoring started"
    print(f"  {p.name}: x='{time_col or 'row number'}', lag='{lag_col}'")
    return pd.DataFrame({"x": x.values, "lag": df[lag_col].values}), x_label


# ----------------------------------------------------------------------------
# 3. Experiment 1 data (flush cost vs starting file size)
# ----------------------------------------------------------------------------
def load_sizes(sizes_csv, sizes_log):
    """Return DataFrame with columns mode, start_rows, s_per_flush (all repeats)."""
    if sizes_csv and Path(sizes_csv).exists():
        df = pd.read_csv(sizes_csv)
        mode_c = find_col(df.columns, ["mode"])
        rows_c = find_col(df.columns, ["start", "rows"])
        avg_c = find_col(df.columns, ["per_flush", "avg", "s_flush"])
        if mode_c and rows_c and avg_c:
            print(f"  sizes CSV: mode='{mode_c}', rows='{rows_c}', s/flush='{avg_c}'")
            return df.rename(columns={mode_c: "mode", rows_c: "start_rows", avg_c: "s_per_flush"})[
                ["mode", "start_rows", "s_per_flush"]]
        print(f"  ! sizes CSV columns not recognised ({list(df.columns)}); trying the log instead")
    if sizes_log and Path(sizes_log).exists():
        pat = re.compile(r"^\s*(single|parts)\s+([\d,]+) rows\s+r\d+: total [\d.]+ s, avg ([\d.]+) s/flush")
        recs = []
        for line in read_text(sizes_log).splitlines():
            if m := pat.match(line):
                recs.append({"mode": m.group(1), "start_rows": int(m.group(2).replace(",", "")),
                             "s_per_flush": float(m.group(3))})
        if recs:
            print(f"  sizes: parsed {len(recs)} repeat lines from {Path(sizes_log).name}")
            return pd.DataFrame(recs)
    return None


# ----------------------------------------------------------------------------
# Figures
# ----------------------------------------------------------------------------
def fig1_sizes(sizes, out):
    med = sizes.groupby(["mode", "start_rows"])["s_per_flush"].median().unstack(0).sort_index()
    fig, ax = plt.subplots(figsize=(8, 5))
    # show every repeat as faint dots so the audience sees the spread, median as the line
    for mode, color, label in [("single", BEFORE_COLOR, "single: rewrite whole file (before)"),
                               ("parts", AFTER_COLOR, "parts: new file per flush (after)")]:
        if mode not in med:
            continue
        pts = sizes[sizes["mode"] == mode]
        ax.scatter(pts["start_rows"], pts["s_per_flush"] * 1000, color=color, alpha=0.3, s=25)
        ax.plot(med.index, med[mode] * 1000, marker="o", color=color, lw=2.5, label=label)
    ax.set_xscale("symlog", linthresh=1000)
    ax.set_xticks(list(med.index))
    ax.set_xticklabels([f"{int(v):,}" for v in med.index])
    ax.set_xlabel("Rows already in the parquet output before the run")
    ax.set_ylabel("Milliseconds per flush")
    ax.set_title("Flush cost grows with file size only when the whole file is rewritten")
    ax.set_ylim(bottom=0)
    ax.legend(frameon=False)
    ax.text(0.99, 0.02, "Line = median of repeats; dots = individual repeats\nSame 1,000 messages / 40 flushes each",
            transform=ax.transAxes, ha="right", va="bottom", fontsize=9, color="gray")
    fig.tight_layout()
    fig.savefig(out / "fig1_flush_cost_vs_file_size.png", dpi=200)
    plt.close(fig)


def fig2_lag(runs, out, repo_root):
    for tag in sorted({r["tag"] for r in runs}):
        pair = [r for r in runs if r["tag"] == tag]
        fig, ax = plt.subplots(figsize=(9, 5))
        x_label = "Lag sample #"
        # load both CSVs first; if either is missing, use log samples for both so the x-axes match
        loaded_all = {r["run"]: (load_lag_csv(r["lag_csv"], repo_root) if r.get("lag_csv") else None) for r in pair}
        if any(v is None for v in loaded_all.values()):
            if any(v is not None for v in loaded_all.values()):
                print(f"  ! {tag}: a lag CSV is missing - plotting log samples for both runs")
            loaded_all = {k: None for k in loaded_all}
        for r in sorted(pair, key=lambda r: r["phase"] != "before"):
            color = BEFORE_COLOR if r["mode"] == "single" else AFTER_COLOR
            label = f"{r['phase']} ({r['mode']}), max {r.get('max_lag', '?')}"
            loaded = loaded_all[r["run"]]
            if loaded is not None:
                data, x_label = loaded
                ax.plot(data["x"], data["lag"], marker="o", ms=4, color=color, lw=2, label=label)
            elif r.get("lag_samples"):
                s = r["lag_samples"]
                ax.plot(range(1, len(s) + 1), s, marker="o", ms=4, color=color, lw=2, label=label)
        order = " (after ran first)" if any(r["phase"] == "after" and r["order_in_log"] == 1 for r in pair) else ""
        ax.set_title(f"Consumer lag during the same replay workload - {tag}{order}")
        ax.set_xlabel(x_label)
        ax.set_ylabel("Lag (messages behind log-end offset)")
        ax.set_ylim(bottom=0)
        ax.legend(frameon=False)
        fig.tight_layout()
        fig.savefig(out / f"fig2_lag_over_time_{tag}.png", dpi=200)
        plt.close(fig)


def grouped_bars(runs, value_key, ylabel, title, fname, out, fmt="{:.0f}"):
    tags = sorted({r["tag"] for r in runs})
    fig, ax = plt.subplots(figsize=(8, 5))
    width = 0.38
    for i, (phase, color) in enumerate([("before", BEFORE_COLOR), ("after", AFTER_COLOR)]):
        vals = []
        for t in tags:
            match = [r for r in runs if r["tag"] == t and r["phase"] == phase]
            vals.append(match[0].get(value_key, 0) if match else 0)
        xs = [j + (i - 0.5) * width for j in range(len(tags))]
        label = "before (single)" if phase == "before" else "after (parts)"
        bars = ax.bar(xs, vals, width, color=color, label=label)
        ax.bar_label(bars, labels=[fmt.format(v) for v in vals], padding=3, fontsize=10)
    labels = []
    for t in tags:
        rev = any(r["tag"] == t and r["phase"] == "after" and r["order_in_log"] == 1 for r in runs)
        labels.append(f"{t}\n({'after ran first' if rev else 'before ran first'})")
    ax.set_xticks(range(len(tags)))
    ax.set_xticklabels(labels)
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    ax.set_ylim(0, ax.get_ylim()[1] * 1.15)  # headroom so value labels don't hit the legend
    ax.legend(frameon=False, loc="upper center", ncol=2, bbox_to_anchor=(0.5, 1.0))
    fig.tight_layout()
    fig.savefig(out / fname, dpi=200)
    plt.close(fig)


def fig5_first_last(runs, out):
    fig, ax = plt.subplots(figsize=(9, 5))
    names, firsts, lasts, colors = [], [], [], []
    for r in sorted(runs, key=lambda r: (r["tag"], r["phase"] != "before")):
        if "first20_s_per_flush" not in r:
            continue
        names.append(f"{r['tag']}\n{r['phase']}")
        firsts.append(r["first20_s_per_flush"] * 1000)
        lasts.append(r["last20_s_per_flush"] * 1000)
        colors.append(BEFORE_COLOR if r["mode"] == "single" else AFTER_COLOR)
    xs = range(len(names))
    w = 0.38
    ax.bar([x - w / 2 for x in xs], firsts, w, color=colors, alpha=0.5, label="first 20 flushes")
    ax.bar([x + w / 2 for x in xs], lasts, w, color=colors, label="last 20 flushes")
    ax.set_xticks(list(xs))
    ax.set_xticklabels(names)
    ax.set_ylabel("Milliseconds per flush")
    ax.set_title("Per-flush write time at the start vs end of each run\n(red = single/before, blue = parts/after)")
    from matplotlib.patches import Patch
    ax.legend(handles=[Patch(color="gray", alpha=0.5, label="first 20 flushes (lighter)"),
                       Patch(color="gray", label="last 20 flushes (darker)")], frameon=False)
    fig.tight_layout()
    fig.savefig(out / "fig5_flush_time_first_vs_last.png", dpi=200)
    plt.close(fig)


def fig6_mechanism(out):
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5))
    for ax in axes:
        ax.set_xlim(0, 10)
        ax.set_ylim(0, 6)
        ax.axis("off")

    ax = axes[0]
    ax.set_title("Before: single file (rewrite everything)", color=BEFORE_COLOR, fontweight="bold")
    for i, rows in enumerate([25, 50, 75, 100]):
        h = 0.6 + i * 0.9
        ax.add_patch(plt.Rectangle((0.5 + i * 2.3, 0.6), 1.6, h, color=BEFORE_COLOR, alpha=0.25 + i * 0.18))
        ax.text(1.3 + i * 2.3, 0.6 + h + 0.2, f"flush {i+1}\nread {rows - 25} + write {rows}", ha="center", fontsize=9)
    ax.text(5, 5.6, "Each flush reads the whole file and writes it all back:\nwork grows as the file grows",
            ha="center", fontsize=10)

    ax = axes[1]
    ax.set_title("After: parts (one new file per flush)", color=AFTER_COLOR, fontweight="bold")
    for i in range(4):
        ax.add_patch(plt.Rectangle((0.5 + i * 2.3, 0.6), 1.6, 0.6, color=AFTER_COLOR, alpha=0.7))
        ax.text(1.3 + i * 2.3, 1.4, f"flush {i+1}\nwrite 25 rows", ha="center", fontsize=9)
    ax.text(5, 5.6, "Each flush writes only its new rows:\nwork stays constant (but files pile up)",
            ha="center", fontsize=10)
    fig.tight_layout()
    fig.savefig(out / "fig6_mechanism.png", dpi=200)
    plt.close(fig)


# ----------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--logs", nargs="+", required=True, help="saved console output of b1_before_after.py")
    ap.add_argument("--sizes-csv", default=None, help="default: first data/b1_runs/sizes_*.csv found")
    ap.add_argument("--sizes-log", default=None, help="saved console output of b1_size_comparison.py (fallback)")
    ap.add_argument("--repo-root", default=".", help="folder the lag CSV paths in the logs are relative to")
    ap.add_argument("--out", default="figures/b1")
    args = ap.parse_args()

    repo_root = Path(args.repo_root)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    print("Reading run logs...")
    runs = parse_run_logs(args.logs)
    for r in runs:
        print(f"  {r['run']:<28} mode={r['mode']:<6} parquet={r.get('parquet_total_s')} s  max lag={r.get('max_lag')}")

    sizes_csv = args.sizes_csv
    if sizes_csv is None:
        found = sorted((repo_root / "data" / "b1_runs").glob("sizes_*.csv"))
        sizes_csv = str(found[0]) if found else None
    print("Reading size-comparison data...")
    sizes = load_sizes(sizes_csv, args.sizes_log)
    if sizes is not None:
        fig1_sizes(sizes, out)
    else:
        print("  ! no size data found - skipping figure 1 (pass --sizes-csv or --sizes-log)")

    print("Reading lag CSVs...")
    fig2_lag(runs, out, repo_root)
    grouped_bars(runs, "max_lag", "Max lag (messages)",
                 "Maximum consumer lag at --rate 4000, before vs after", "fig3_max_lag.png", out)
    grouped_bars(runs, "parquet_total_s", "Seconds spent writing parquet",
                 "Total parquet write time for the same 470 flushes", "fig4_parquet_total_time.png",
                 out, fmt="{:.2f} s")
    fig5_first_last(runs, out)
    fig6_mechanism(out)

    cols = ["run", "tag", "phase", "mode", "order_in_log", "rows_added", "parquet_total_s",
            "first20_s_per_flush", "last20_s_per_flush", "max_lag"]
    pd.DataFrame(runs).reindex(columns=cols).to_csv(out / "b1_summary.csv", index=False)
    print(f"\nDone. Figures and b1_summary.csv written to {out.resolve()}")


if __name__ == "__main__":
    main()
