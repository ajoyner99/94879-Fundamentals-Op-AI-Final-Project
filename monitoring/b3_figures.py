"""
monitoring/b3_figures.py

Slide figures for B3. Every value drawn, and every number in a title, is read
from the monitor's output (data/b3_runs/scenarios.json) or computed here from
the reference features with the monitor's own functions, so the figures
always match the latest run.

  fig_a_diagnosis.png   reference window over time: mean trade_intensity per
                        30 s, and the model's alert rate vs the actual spike rate
  fig_b_validation.png  per scenario: before (KS features flagged) vs after
                        (model-score PSI, colored by the monitor's severity)
  fig_c_fitness.png     per scenario: PR-AUC lift over the prevalence baseline
                        with its 95% exploratory row-bootstrap interval (a
                        descriptive diagnostic, not a formal confidence interval)

Run monitoring/b3_monitor.py first.
"""
import argparse
import json
import os
import pickle
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
from b3_monitor import ALERT_THRESHOLD, DATASET_DRIFT_SHARE, FEATURE_COLUMNS, PSI_MODERATE, PSI_SIGNIFICANT, load_window  # noqa: E402

# Before = red, after = blue (same convention as the B1 slides); severity uses status colors + text labels
BEFORE, AFTER, SPIKE = "#c0392b", "#2a78d6", "#eb6834"
SEVERITY_COLORS = {"OK": "#9a9a96", "LOW": "#fab219", "MEDIUM": "#ec835a", "HIGH": "#d03b3b", "PAGE": "#4a3aa7"}
INK, MUTED, GRID = "#0b0b0b", "#52514e", "#e6e5e1"
# Axis labels describe how each scenario is built, not what it found.
SHORT_NAMES = {"S0": "S0\ninterleaved", "S1": "S1\ndrifted file", "S2": "S2\nsplit-half", "S3": "S3\nmessage loss"}

plt.rcParams.update({
    "font.size": 13, "axes.titlesize": 15, "axes.labelsize": 13, "axes.edgecolor": MUTED,
    "axes.labelcolor": INK, "xtick.color": MUTED, "ytick.color": MUTED, "axes.spines.top": False,
    "axes.spines.right": False, "figure.facecolor": "white", "axes.facecolor": "white",
})


def fig_a(reference_path, model_path, tau, out, bin_s=30):
    with open(model_path, "rb") as f:
        bundle = pickle.load(f)
    df = load_window(reference_path, bundle, tau)  # same scoring and labels as the monitor
    ts = pd.to_datetime(df["timestamp"])
    df["t"] = (ts - ts.iloc[0]).dt.total_seconds()
    df["bin"] = (df["t"] // bin_s).astype(int)

    g = df.groupby("bin").agg(intensity=("trade_intensity", "mean"),
                              alert=("score", lambda s: (s >= ALERT_THRESHOLD).mean()),
                              spike=("label", "mean"))
    g = g.reindex(range(g.index.max() + 1))   # empty bins (the recording gap) stay empty
    x = g.index * bin_s + bin_s / 2

    gap_after = int(df["t"].diff().idxmax())  # first row after the largest jump in timestamps
    gap = (df["t"].iloc[gap_after - 1], df["t"].iloc[gap_after])
    r_int = np.corrcoef(df["score"], df["trade_intensity"])[0, 1]
    r_lab = df[["score", "label"]].dropna().corr().iloc[0, 1]

    fig, (top, bot) = plt.subplots(2, 1, figsize=(12, 6.5), sharex=True, gridspec_kw={"height_ratios": [1, 1.4]})
    top.bar(x, g["intensity"].fillna(0), width=bin_s - 2, color=MUTED, alpha=0.55, zorder=2)
    top.set_ylabel("Mean trade_intensity")
    top.set_title("trade_intensity (messages in the last 60 s), per 30 s", loc="left", color=INK)

    bot.plot(x, g["alert"] * 100, color=AFTER, lw=2, marker="o", ms=8, label="Model alert rate")
    bot.plot(x, g["spike"] * 100, color=SPIKE, lw=2, marker="o", ms=8, label="Actual spike rate")
    bot.set_ylabel("% of rows")
    bot.set_ylim(0, 105)
    bot.set_xlabel("Seconds since the first row of the reference recording")
    bot.legend(loc="upper left", frameon=False)
    bot.set_title(f"Correlation of model score with trade_intensity r = {r_int:.2f}; with actual spikes r = {r_lab:.3f}",
                  loc="left", color=INK)

    for ax in (top, bot):
        ax.axvspan(*gap, color=GRID, alpha=0.8, lw=0, zorder=0)
        ax.grid(axis="y", color=GRID, lw=0.8)
        ax.set_axisbelow(True)
    top.text(np.mean(gap), top.get_ylim()[1] * 0.85, f"{gap[1] - gap[0]:.0f} s with\nno rows",
             ha="center", va="top", color=MUTED, fontsize=11)

    fig.suptitle("Reference window: trade_intensity, model alerts and actual spikes over time",
                 x=0.01, ha="left", fontsize=17, fontweight="bold", color=INK)
    fig.tight_layout()
    fig.savefig(out, dpi=200)
    plt.close(fig)


def fig_b(scenarios, out):
    names = [s["scenario"] for s in scenarios]
    labels = [SHORT_NAMES.get(n, n) for n in names]
    x = np.arange(len(names))
    flagged = [s["tier2"]["before_ks_features_flagged"] for s in scenarios]
    # Log scale cannot show 0, so values below 0.001 are drawn at 0.001 (none occurred in our run).
    score_psi = [max(s["tier2"]["score_psi"], 1e-3) for s in scenarios]
    sev = [s["severity"] for s in scenarios]
    n_feat = len(FEATURE_COLUMNS)

    fig, (left, right) = plt.subplots(1, 2, figsize=(13, 6))

    left.bar(x, flagged, width=0.6, color=BEFORE)
    line = n_feat * DATASET_DRIFT_SHARE
    left.axhline(line, color=MUTED, ls="--", lw=1)
    left.text(-0.45, line + 0.05, f"dataset drift (>= {DATASET_DRIFT_SHARE:.0%})", ha="left", va="bottom", color=MUTED, fontsize=11)
    for xi, v in zip(x, flagged):
        left.text(xi, v + 0.06, f"{v}/{n_feat}", ha="center", va="bottom", color=INK)
    left.set_ylim(0, n_feat + 0.4)
    left.set_yticks(range(n_feat + 1))
    left.set_ylabel("Features flagged (KS p < 0.05)")
    left.set_title("Before: per-feature KS test (Evidently defaults)", loc="left", color=BEFORE, fontweight="bold")

    right.bar(x, score_psi, width=0.6, color=[SEVERITY_COLORS[s] for s in sev])
    right.set_yscale("log")
    right.set_ylim(1e-3, 30)
    for y, name in ((PSI_MODERATE, f"{PSI_MODERATE:.2f} operational threshold"),
                    (PSI_SIGNIFICANT, f"{PSI_SIGNIFICANT:.2f} reference band (not a severity rule)")):
        right.axhline(y, color=MUTED, ls="--", lw=1)
        right.text(-0.45, y * 1.08, name, ha="left", va="bottom", color=MUTED, fontsize=10)
    for xi, s, v in zip(x, scenarios, score_psi):
        t2 = s["tier2"]
        right.text(xi, v * 1.3, f"{s['severity']}\nalerts {t2['alert_rate_ref']:.0%}→{t2['alert_rate_cur']:.0%}",
                   ha="center", va="bottom", color=INK, fontsize=11)
    right.set_ylabel("Model score PSI (log scale)")
    right.set_title("After: tiered monitor severity", loc="left", color=AFTER, fontweight="bold")

    for ax in (left, right):
        ax.set_xticks(x, labels)
        ax.grid(axis="y", color=GRID, lw=0.8)
        ax.set_axisbelow(True)

    fig.suptitle("Before vs after on the same scenarios", x=0.01, ha="left", fontsize=17, fontweight="bold", color=INK)
    fig.tight_layout()
    fig.savefig(out, dpi=200)
    plt.close(fig)


def fig_c(scenarios, out):
    names = [s["scenario"] for s in scenarios][::-1]
    rows = scenarios[::-1]
    y = np.arange(len(rows))
    lift = [s["tier3"]["current"]["lift"] for s in rows]
    lo = [s["tier3"]["lift_row_bootstrap_interval_95_current"][0] for s in rows]
    hi = [s["tier3"]["lift_row_bootstrap_interval_95_current"][1] for s in rows]
    includes_zero = sum(l <= 0 <= h for l, h in zip(lo, hi))

    fig, ax = plt.subplots(figsize=(11, 5))
    ax.axvline(0, color=BEFORE, ls="--", lw=1.5)
    ax.text(0, len(rows) - 0.45, "  0 = prevalence baseline", color=BEFORE, va="top", fontsize=11)
    ax.hlines(y, lo, hi, color=AFTER, lw=2)
    ax.plot(lift, y, "o", color=AFTER, ms=9)
    for yi, l, h in zip(y, lo, hi):
        ax.text(h, yi + 0.15, f" [{l:+.3f}, {h:+.3f}]", va="bottom", color=MUTED, fontsize=10)
    ax.set_yticks(y, [SHORT_NAMES.get(n, n).replace("\n", " ") for n in names])
    ax.set_xlabel("PR-AUC lift over prevalence baseline (95% exploratory row-bootstrap interval, current window)")
    ax.grid(axis="x", color=GRID, lw=0.8)
    ax.set_axisbelow(True)
    ax.set_ylim(-0.6, len(rows) - 0.2)
    fig.suptitle(f"Exploratory lift interval includes 0 in {includes_zero} of {len(rows)} windows",
                 x=0.01, ha="left", fontsize=16, fontweight="bold", color=INK)
    fig.tight_layout()
    fig.savefig(out, dpi=200)
    plt.close(fig)


def main(args):
    os.makedirs(args.out_dir, exist_ok=True)
    with open(args.scenarios) as f:
        run = json.load(f)
    # Use the tau saved by the monitor run, so the labels here match that run exactly.
    fig_a(args.reference_features, args.model, run["tau"], os.path.join(args.out_dir, "fig_a_diagnosis.png"))
    fig_b(run["scenarios"], os.path.join(args.out_dir, "fig_b_validation.png"))
    fig_c(run["scenarios"], os.path.join(args.out_dir, "fig_c_fitness.png"))
    print(f"[b3_figures] saved 3 figures to {args.out_dir}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenarios", default="data/b3_runs/scenarios.json")
    parser.add_argument("--reference_features", default="data/processed/b3_reference.parquet")
    parser.add_argument("--model", default=os.environ.get("MODEL_PATH", "models/artifacts/model.pkl"))
    parser.add_argument("--out_dir", default="data/b3_runs/figures")
    main(parser.parse_args())
