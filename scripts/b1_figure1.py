"""
scripts/b1_figure1.py

Redraws memo Figure 1 (B1 baseline and diagnosis) from the lag recorder CSVs,
with the ACHIEVED arrival rate in each panel title next to the requested rate
(feedback: the replay delivers ~1,600 msg/s whether 2,500 or 4,000 is requested).

Achieved rate = mean arrival rate over full recorder windows (the partial first
and last windows of the replay are excluded), the definition used in
docs/run_log_9-24-2026.md.

Usage (from the project folder):
    python scripts/b1_figure1.py
Output: data/b1_runs/figure1_baseline_diagnosis.png
"""
import glob
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

RUNS = [(1500, "lag_inst_rate1500_t2_ana_*.csv"),
        (2500, "lag_inst_rate2500_t2_ana_*.csv"),
        (4000, "lag_inst_rate4000_t1_ana_*.csv")]
ARRIVAL, PROCESSING, LAG = "#5b5f97", "#2a9d8f", "#d1495b"
OUT = os.path.join("data", "b1_runs", "figure1_baseline_diagnosis.png")


def load(pattern):
    path = sorted(glob.glob(os.path.join("data", "b1_runs", "**", pattern), recursive=True))[0]
    d = pd.read_csv(path)
    d["arrival_rate_per_s"] = pd.to_numeric(d["arrival_rate_per_s"], errors="coerce").fillna(0)
    d["processing_rate_per_s"] = pd.to_numeric(d["processing_rate_per_s"], errors="coerce").fillna(0)
    active = d.index[d["arrival_rate_per_s"] > 0]
    t0 = d.loc[active[0] - 1, "elapsed_s"]          # last sample before arrivals started
    d["t"] = d["elapsed_s"] - t0
    full = d.loc[active[1:-1], "arrival_rate_per_s"]  # full windows only
    return d[(d["t"] >= -3) & (d["t"] <= 22)], full.mean(), os.path.basename(path)


def main():
    fig, axes = plt.subplots(2, 3, figsize=(13, 6.2), sharex=True, sharey="row")
    sources = []
    for col, (rate, pattern) in enumerate(RUNS):
        d, achieved, name = load(pattern)
        sources.append(name)
        top, bottom = axes[0, col], axes[1, col]
        t, a, p = d["t"], d["arrival_rate_per_s"], d["processing_rate_per_s"]
        top.fill_between(t, a, p, where=a > p, interpolate=True, color=LAG, alpha=0.18, lw=0)
        top.fill_between(t, a, p, where=p > a, interpolate=True, color=PROCESSING, alpha=0.18, lw=0)
        top.plot(t, a, color=ARRIVAL, lw=1.6, marker="o", ms=3, label="Arrival rate")
        top.plot(t, p, color=PROCESSING, lw=1.6, marker="o", ms=3, label="Processing rate")
        top.set_title(f"Requested {rate:,}/s  ·  achieved ~{achieved:,.0f}/s", fontsize=10, loc="left")
        bottom.fill_between(d["t"], d["lag"], color=LAG, alpha=0.15, lw=0)
        bottom.plot(d["t"], d["lag"], color=LAG, lw=1.6, marker="o", ms=3)
        bottom.set_xlabel("Seconds since replay started", fontsize=9)
        for ax in (top, bottom):
            ax.grid(color="#e6e6e6", lw=0.6)
            ax.spines[["top", "right"]].set_visible(False)
            ax.tick_params(labelsize=8)
    axes[0, 0].set_ylabel("Messages per second", fontsize=9)
    axes[1, 0].set_ylabel("Lag (messages waiting)", fontsize=9)
    axes[0, 0].set_ylim(bottom=0)
    axes[1, 0].set_ylim(bottom=0)
    handles = [plt.Line2D([], [], color=ARRIVAL, marker="o", ms=3, lw=1.6, label="Arrival rate"),
               plt.Line2D([], [], color=PROCESSING, marker="o", ms=3, lw=1.6, label="Processing rate"),
               plt.Rectangle((0, 0), 1, 1, color=LAG, alpha=0.18, label="Falling behind (arrivals > processing)"),
               plt.Rectangle((0, 0), 1, 1, color=PROCESSING, alpha=0.18, label="Catching up (processing > arrivals)")]
    fig.legend(handles=handles, loc="lower center", ncol=4, frameon=False, fontsize=8.5)
    fig.suptitle("Lag grows when arrivals outpace processing; requesting 4,000/s delivers no more than 2,500/s",
                 x=0.06, y=0.985, ha="left", fontsize=11)
    fig.text(0.06, 0.94, "Second laptop; each run starts from an empty output file. "
             "Achieved = mean arrival over full 3-second windows.", fontsize=8.5, color="#555555")
    fig.tight_layout(rect=(0, 0.05, 1, 0.95))
    fig.savefig(OUT, dpi=200)
    print(f"saved {OUT}\nsources: {', '.join(sources)}")


if __name__ == "__main__":
    main()
