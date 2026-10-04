"""
monitoring/b3_sensitivity.py

Sensitivity analysis of the final drift-severity settings. It asks: given an
alternative reasonable parameter combination, what would the existing monitor
classify for S0-S3? It does not validate or optimize any threshold, and it
does not change the monitor.

Reused unchanged from monitoring/b3_monitor.py: build_scenarios(), psi(),
classify(), the same scenario windows, model.pkl scores and labels.

Grid (fixed before the results were seen; not changed afterwards):
  operational PSI threshold      0.05, 0.10, 0.15, 0.25, 0.50
      used wherever the monitor uses PSI_MODERATE: feature PSI for LOW and
      score PSI for MEDIUM. The 0.25 reference line is not a severity rule.
  MEDIUM absolute alert shift    2, 5, 10 percentage points
  HIGH absolute alert shift      10, 20, 30, 40 percentage points
  HIGH alert-rate ratio          1.5, 2, 3
  PSI bins                       5, 10, 20
  PSI proportion floor           1e-6, 1e-4, 1e-3
Combinations where the MEDIUM shift >= the HIGH shift are skipped.

For every (bins, floor) pair, each feature PSI and the score PSI are recomputed.
Alert rates do not depend on PSI settings, so they are computed once.

Not varied: Tier 1 (all evaluation scenarios were HEALTHY; Tier 1 is passed as
not checked, so PAGE cannot occur here) and Tier 3 (not part of severity).

Reference scenario ordering (the intended operational ordering, not ground
truth): S0 = OK, S1 = LOW, S2 = HIGH, S3 = HIGH.

Outputs: data/b3_runs/sensitivity.csv (one row per combination x scenario)
and data/b3_runs/sensitivity_summary.json.
"""
import argparse
import itertools
import json
import os
import pickle
import sys
from collections import Counter, defaultdict

import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
import b3_monitor as monitor  # noqa: E402

GRID = {
    "psi_threshold": [0.05, 0.10, 0.15, 0.25, 0.50],
    "alert_shift_medium": [0.02, 0.05, 0.10],
    "alert_shift_high": [0.10, 0.20, 0.30, 0.40],
    "alert_ratio_high": [1.5, 2.0, 3.0],
    "psi_bins": [5, 10, 20],
    "psi_floor": [1e-6, 1e-4, 1e-3],
}
REFERENCE_ORDERING = {"S0": "OK", "S1": "LOW", "S2": "HIGH", "S3": "HIGH"}


def tier2_for(ref, cur, bins, floor):
    """Tier 2 inputs to classify(), with PSI recomputed for this bins/floor setting."""
    features = {f: {"psi": monitor.psi(ref[f].to_numpy(), cur[f].to_numpy(), bins=bins, floor=floor)}
                for f in monitor.FEATURE_COLUMNS}
    alert_ref = float((ref["score"] >= monitor.ALERT_THRESHOLD).mean())
    alert_cur = float((cur["score"] >= monitor.ALERT_THRESHOLD).mean())
    return {
        "features": features,
        "max_feature_psi": max(v["psi"] for v in features.values()),
        "score_psi": monitor.psi(ref["score"].to_numpy(), cur["score"].to_numpy(), bins=bins, floor=floor),
        "alert_rate_ref": alert_ref,
        "alert_rate_cur": alert_cur,
        "alert_rate_shift": alert_cur - alert_ref,
        "alert_rate_ratio": (alert_cur / alert_ref) if alert_ref > 0 else float("inf"),
    }


def rule_that_fired(severity, t2, th):
    """Name the condition(s) of classify() that produced this severity (for reporting only)."""
    if severity == "HIGH":
        r = t2["alert_rate_ratio"]
        parts = []
        if r >= th["alert_ratio_high"] or r <= 1 / th["alert_ratio_high"]:
            parts.append("HIGH: alert-rate ratio")
        if abs(t2["alert_rate_shift"]) >= th["alert_shift_high"]:
            parts.append("HIGH: absolute alert shift")
        return " + ".join(parts)
    if severity == "MEDIUM":
        parts = []
        if t2["score_psi"] >= th["psi_moderate"]:
            parts.append("MEDIUM: score PSI")
        if abs(t2["alert_rate_shift"]) > th["alert_shift_medium"]:
            parts.append("MEDIUM: absolute alert shift")
        return " + ".join(parts)
    if severity == "LOW":
        return "LOW: feature PSI"
    return "none"


def main(args):
    with open(args.model, "rb") as f:
        bundle = pickle.load(f)
    train = pd.read_parquet(args.train_features).dropna(subset=monitor.FEATURE_COLUMNS)
    tau = float(monitor.future_vol(train).quantile(args.percentile))
    scenarios = monitor.build_scenarios(args, bundle, tau)
    names = [n for n, _, _, _ in scenarios]

    # PSI depends only on (bins, floor): compute Tier 2 once per scenario per pair.
    tier2 = {(b, fl, n): tier2_for(r, c, b, fl)
             for b in GRID["psi_bins"] for fl in GRID["psi_floor"] for n, _, r, c in scenarios}

    t1 = {"skipped": True}  # Tier 1 not varied (all evaluation scenarios were HEALTHY)
    rows, combos, mismatches = [], [], []
    keys = list(GRID)
    for values in itertools.product(*(GRID[k] for k in keys)):
        p = dict(zip(keys, values))
        if p["alert_shift_medium"] >= p["alert_shift_high"]:
            continue
        th = {"psi_moderate": p["psi_threshold"], "alert_shift_medium": p["alert_shift_medium"],
              "alert_shift_high": p["alert_shift_high"], "alert_ratio_high": p["alert_ratio_high"]}
        result = {}
        for n in names:
            t2 = tier2[(p["psi_bins"], p["psi_floor"], n)]
            severity, reasons = monitor.classify(t1, t2, None, th)
            result[n] = severity
            rows.append({**p, "scenario": n,
                         "max_feature_psi": t2["max_feature_psi"], "score_psi": t2["score_psi"],
                         "alert_rate_ref": t2["alert_rate_ref"], "alert_rate_cur": t2["alert_rate_cur"],
                         "severity": severity, "reasons": "; ".join(reasons),
                         "rule": rule_that_fired(severity, t2, th),
                         "matches_reference": severity == REFERENCE_ORDERING.get(n)})
        full_match = all(result[n] == REFERENCE_ORDERING.get(n) for n in names)
        combos.append({**p, "full_match": full_match})
        if not full_match:
            changed = [{"scenario": n, "expected": REFERENCE_ORDERING.get(n), "got": result[n],
                        "rule": rule_that_fired(result[n], tier2[(p["psi_bins"], p["psi_floor"], n)], th)}
                       for n in names if result[n] != REFERENCE_ORDERING.get(n)]
            mismatches.append({"parameters": p, "changed": changed})

    os.makedirs(args.out_dir, exist_ok=True)
    pd.DataFrame(rows).to_csv(os.path.join(args.out_dir, "sensitivity.csv"), index=False)

    n_valid = len(combos)
    n_match = sum(c["full_match"] for c in combos)
    df = pd.DataFrame(rows)
    per_scenario = {n: {"matches": int(df[df.scenario == n].matches_reference.sum()),
                        "severity_counts": dict(Counter(df[df.scenario == n].severity))} for n in names}
    cdf = pd.DataFrame(combos)
    per_parameter = {k: [{"value": v, "combinations": int((cdf[k] == v).sum()),
                          "pct_full_match": round(100 * cdf[cdf[k] == v].full_match.mean(), 2)}
                         for v in GRID[k]] for k in keys}
    change_patterns = Counter((c["scenario"], c["expected"], c["got"], c["rule"])
                              for m in mismatches for c in m["changed"])
    summary = {
        "note": "Sensitivity analysis of the existing monitor's drift-severity settings. Not a validation "
                "or optimization of the thresholds. Reference ordering is the intended operational ordering, "
                "not ground truth.",
        "reference_ordering": REFERENCE_ORDERING,
        "grid": GRID,
        "excluded_rule": "alert_shift_medium >= alert_shift_high",
        "valid_combinations": n_valid,
        "full_match": {"count": n_match, "pct": round(100 * n_match / n_valid, 2)},
        "not_full_match": {"count": n_valid - n_match, "pct": round(100 * (n_valid - n_match) / n_valid, 2)},
        "per_scenario": per_scenario,
        "per_parameter": per_parameter,
        "change_patterns": [{"scenario": s, "expected": e, "got": g, "rule": r, "combinations": c}
                            for (s, e, g, r), c in change_patterns.most_common()],
        "non_matching_combinations": mismatches,
    }
    with open(os.path.join(args.out_dir, "sensitivity_summary.json"), "w") as f:
        json.dump(summary, f, indent=2)

    print(f"[b3_sensitivity] valid combinations: {n_valid}")
    print(f"[b3_sensitivity] full reference ordering: {n_match} ({summary['full_match']['pct']}%)")
    for n, v in per_scenario.items():
        print(f"  {n}: {v['matches']}/{n_valid} match; severities {v['severity_counts']}")
    for p in summary["change_patterns"]:
        print(f"  change: {p['scenario']} {p['expected']} -> {p['got']} via '{p['rule']}' in {p['combinations']} combinations")
    print(f"[b3_sensitivity] saved {args.out_dir}/sensitivity.csv and sensitivity_summary.json")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=os.environ.get("MODEL_PATH", "models/artifacts/model.pkl"))
    parser.add_argument("--train_features", default="data/processed/b3_train.parquet")
    parser.add_argument("--reference_features", default="data/processed/b3_reference.parquet")
    parser.add_argument("--current_features", default="data/processed/b3_current.parquet")
    parser.add_argument("--msgloss_features", default="data/processed/b3_msgloss.parquet")
    parser.add_argument("--out_dir", default="data/b3_runs")
    parser.add_argument("--percentile", type=float, default=0.90)
    main(parser.parse_args())
