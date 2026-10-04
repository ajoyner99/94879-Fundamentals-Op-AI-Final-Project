"""
monitoring/b3_monitor.py

B3 tiered monitor. Answers "is the system up?" separately from "is the AI
still working?" and turns the evidence into one severity + action per
scenario. Every number it reports is computed from the feature files, the
saved model and the running services; nothing is typed in.

  Tier 1  system health   container state/health from `docker compose ps`
                          (recorded once per run), /health, and the current
                          window sent row by row through the real /score API
                          (latency, error rate, and the largest difference
                          between the API's score and model.pkl's score)
  Tier 2  drift           per-feature PSI, model-score PSI, alert-rate shift.
                          The "before" view is a KS test per feature with the
                          same defaults the supplied Evidently report uses
                          (p < 0.05 flags a feature; dataset drift when >= 50%
                          of features are flagged). monitoring/b3_diagnosis.py
                          runs Evidently itself on the same scenarios so the
                          two can be compared.
  Tier 3  performance     retrospective model-fitness diagnostic once labels
                          exist: PR-AUC, prevalence baseline, lift (PR-AUC minus
                          prevalence) with a 95% exploratory row-bootstrap
                          interval, and an exploratory change in labeled
                          performance vs reference. Tier 3 does not set severity.

Severity rules (the thresholds are the constants below; see their comments
for where each value comes from):
  PAGE    the scoring service cannot provide predictions: /health fails, the model
          is not loaded, or the /score API returns no predictions at all
  HIGH    alert rate doubles or halves, or shifts >= 20 pp
  MEDIUM  score PSI >= 0.1 or alert-rate shift > 5 pp
  LOW     any feature PSI >= 0.1 (feature drift only)
  OK      none of the above
Tier 1 system status (separate from the drift severity ladder):
  HEALTHY      /health succeeds, model loaded, and every attempted /score request
               produced a prediction
  DEGRADED     /health succeeds and at least one prediction was produced, but one or
               more /score requests failed: reported as a serving/reliability issue,
               with no drift severity and no paging cutoff
  UNAVAILABLE  /health fails, model not loaded, or no /score request produced a
               prediction: this is the PAGE condition
OK / LOW / MEDIUM / HIGH describe model/data-behavior changes; PAGE represents
complete serving failure.

Severity uses Tier 1 and Tier 2 only. API error rate and latency are recorded
as Tier 1 telemetry but have no paging cutoff: no production SLO or validated
API error-rate paging threshold was supplied for this project, so error rate
is monitored without inventing an operational cutoff.

Model fitness (Tier 3) is reported separately and compares observed PR-AUC
with the prevalence baseline on the available data:
  "ABOVE-BASELINE PERFORMANCE NOT ESTABLISHED ON AVAILABLE DATA" when the lower
  end of the 95% exploratory row-bootstrap interval for lift is <= 0. On the
  available short, effectively in-sample dataset, above-baseline PR-AUC
  performance is not established. This does not prove the model is useless or
  incapable of performing better on unseen data.
  "ABOVE-BASELINE PERFORMANCE OBSERVED ON AVAILABLE DATA (EXPLORATORY)"
  otherwise. Because the uncertainty calculation is an exploratory row
  bootstrap on sequential observations and the data are effectively in-sample,
  this is not formal evidence of generalizable model performance.

Scenarios (reference window vs current window):
  S0  odd rows vs even rows of the reference features   (interleaved split)
  S1  reference features vs drifted features             (sample_ticks_drifted.jsonl)
  S2  first half vs second half of the reference features (split at the middle row)
  S3  reference features vs message-loss features         (sample_ticks_msgloss.jsonl,
                                                            built by scripts/b3_inject_faults.py)
"""
import argparse
import csv
import json
import os
import pickle
import subprocess
import time
import urllib.request

import numpy as np
import pandas as pd
from scipy.stats import ks_2samp
from sklearn.metrics import average_precision_score, precision_score, recall_score

FEATURE_COLUMNS = ["midprice_returns", "spread_normalized", "order_book_imbalance", "trade_intensity"]

# --- Settings (not results). Where each value comes from: ---
# Supplied project/code settings.
ALERT_THRESHOLD = 0.5      # supplied: the scorer's rule, spike = probability >= 0.5 (scoring/score_service.py)

# PSI bands: conventional PSI heuristic bands originating in credit-scorecard practice (the "Lewis
# constants", Lewis 1994, as traced by Potgieter et al. 2026, Annals of Operations Research
# 361:413-435, pp. 414 and 419); not universal statistically calibrated thresholds.
PSI_MODERATE = 0.1         # the operational PSI threshold used by the severity ladder (LOW / MEDIUM)
PSI_SIGNIFICANT = 0.25     # conventional descriptive reference band and visualization line only;
                           # it does not independently trigger any severity level in this monitor

# AI-proposed, project-specific operating thresholds; accepted by the owner; not externally
# established standards.
ALERT_SHIFT_MEDIUM = 0.05  # MEDIUM: alert-rate change above 5 percentage points
ALERT_SHIFT_HIGH = 0.20    # HIGH (workflow disruption): alert-rate change of 20+ percentage points,
ALERT_RATIO_HIGH = 2.0     # or the alert rate doubling or halving

# Evidently defaults, used only for the baseline/"before" KS comparison.
KS_ALPHA = 0.05            # a feature is flagged when its KS p-value < 0.05
DATASET_DRIFT_SHARE = 0.5  # dataset drift when >= 50% of features are flagged

# AI-selected implementation choice, retained only for the exploratory Tier 3 diagnostic
# (the seed, 0, is the --seed default below); not a statistical standard.
N_BOOT = 1000              # row-bootstrap resamples for the exploratory lift intervals

ACTIONS = {
    "OK": "No action.",
    "LOW": "Open a data-quality ticket: confirm whether the input change is real or a feed/pipeline bug. No model action.",
    "MEDIUM": "Investigate same day: check upstream feed and feature pipeline, notify model owner. No retrain without labeled evidence.",
    "HIGH": "Escalate now: notify model owner and pipeline on-call; consider pausing alerts. "
            "Retrain only after labeled evidence confirms the cause.",
    "PAGE": "Page on-call: restore the service (restart/rollback). Model checks are not trustworthy until the service is healthy.",
}
FITNESS_ACTION = ("Escalate to model owner: above-baseline performance not established on available data; "
                  "review threshold, features and training data.")


def future_vol(df, horizon=20):
    """Forward rolling std of returns (same definition as models/train_baseline.py).
    horizon=20 is the supplied 20-row future-label horizon (label_spikes default there)."""
    return df["midprice_returns"].rolling(horizon).std().shift(-horizon)


def load_window(path, bundle, tau):
    """Load a features file, score every row with model.pkl, and attach the spike label.

    The label for a row looks at the next 20 rows, so it is computed on the full,
    unbroken file *before* any split (S0 and S2 split this frame afterwards).
    The last 20 rows have no label (NaN) and are left out of Tier 3."""
    df = pd.read_parquet(path).dropna(subset=FEATURE_COLUMNS).reset_index(drop=True)
    df["score"] = bundle["model"].predict_proba(bundle["scaler"].transform(df[bundle["features"]]))[:, 1]
    fv = future_vol(df)
    df["label"] = np.where(fv.isna(), np.nan, (fv >= tau).astype(float))
    return df


def psi(ref, cur, bins=10, floor=1e-4):
    """Population Stability Index: sum over bins of (cur% - ref%) * ln(cur% / ref%).

    Defaults: bins=10 matches Feature-engine's current default (DropHighPSIFeatures).
    floor=1e-4 uses the same numeric constant as Feature-engine's current
    min_pct_empty_bins default, but the method differs: Feature-engine adds 0.0001 to
    empty bins, while this function floors every bin proportion at a minimum of 0.0001.

    Bin edges are the reference's deciles. Duplicate edges are dropped because some
    features (e.g. spread_normalized) have many identical values, and the outer edges
    are opened to +/- infinity so every current value lands in a bin. Bin shares are
    floored at 0.0001 so an empty bin does not produce log(0)."""
    edges = np.unique(np.quantile(ref, np.linspace(0, 1, bins + 1)))
    edges[0], edges[-1] = -np.inf, np.inf
    p_ref = np.clip(np.histogram(ref, edges)[0] / len(ref), floor, None)
    p_cur = np.clip(np.histogram(cur, edges)[0] / len(cur), floor, None)
    return float(np.sum((p_cur - p_ref) * np.log(p_cur / p_ref)))


def lift_samples(df, rng):
    """Row-bootstrap samples of (PR-AUC - positive rate) on the labeled rows.

    Rows in the evaluation stream are sequentially dependent, while this bootstrap
    resamples individual rows independently. The resulting intervals are therefore
    used as descriptive uncertainty diagnostics rather than formally calibrated
    confidence intervals or hypothesis tests. The evaluation data are also limited
    and effectively in-sample.

    A resample that happens to contain no positive rows has no defined PR-AUC,
    so it is skipped (the result can have slightly fewer than N_BOOT values)."""
    d = df.dropna(subset=["label"])
    y, s = d["label"].to_numpy(), d["score"].to_numpy()
    out = []
    for _ in range(N_BOOT):
        i = rng.integers(0, len(y), len(y))
        if y[i].sum() == 0:
            continue
        out.append(average_precision_score(y[i], s[i]) - y[i].mean())
    return np.array(out)


def performance(df):
    """Point estimates on the labeled rows: PR-AUC, positive rate (= prevalence baseline), lift,
    and precision/recall of the scorer's 0.5 alert rule."""
    d = df.dropna(subset=["label"])
    y, s = d["label"].astype(int), d["score"]
    alerts = (s >= ALERT_THRESHOLD).astype(int)
    pr_auc = float(average_precision_score(y, s)) if y.sum() else float("nan")
    return {
        "rows_labeled": int(len(d)),
        "positives": int(y.sum()),
        "positive_rate": float(y.mean()),
        "pr_auc": pr_auc,
        "lift": pr_auc - float(y.mean()),
        "precision_at_threshold": float(precision_score(y, alerts, zero_division=0)),
        "recall_at_threshold": float(recall_score(y, alerts, zero_division=0)),
    }


def container_status(compose_file):
    """Record each container's state and health exactly as `docker compose ps` reports them."""
    try:
        out = subprocess.run(["docker", "compose", "-f", compose_file, "ps", "--format", "json"],
                             capture_output=True, text=True, timeout=20, check=True).stdout
    except Exception as e:
        return {"error": str(e)}
    # Depending on the Docker Compose version the output is one JSON array or one JSON object per line.
    out = out.strip()
    rows = json.loads(out) if out.startswith("[") else [json.loads(line) for line in out.splitlines() if line.strip()]
    return {r["Service"]: {"state": r.get("State"), "health": r.get("Health"), "status": r.get("Status")} for r in rows}


def system_status(t1):
    """Tier 1 serving status: HEALTHY, DEGRADED or UNAVAILABLE (NOT_CHECKED with --no_api).
    No percentage cutoff: any failed request with at least one success is DEGRADED."""
    if t1.get("skipped"):
        return "NOT_CHECKED"
    if not t1["health_ok"] or not t1["model_loaded"]:
        return "UNAVAILABLE"
    if t1["requests"] > 0 and t1["errors"] == t1["requests"]:
        return "UNAVAILABLE"
    if (t1["errors"] or 0) > 0:
        return "DEGRADED"
    return "HEALTHY"


def tier1(api_url, cur):
    """/health, then send every row of the *current* window through the real /score API.

    Only the current window is sent: the reference window plays the role of past,
    already-scored traffic. For each row the API's score is compared with model.pkl's
    score computed locally; a difference of ~0 shows the monitor checks the deployed model."""
    result = {"health_ok": False, "model_loaded": False, "requests": 0, "errors": None, "error_rate": None,
              "latency_ms_p50": None, "latency_ms_p95": None, "max_abs_score_diff": None}
    try:
        with urllib.request.urlopen(f"{api_url}/health", timeout=3) as r:
            health = json.load(r)
        result["health_ok"] = health.get("status") == "ok"
        result["model_loaded"] = bool(health.get("model_loaded"))
    except Exception as e:
        result["health_error"] = str(e)
        return result

    latencies, errors, diffs = [], 0, []
    for _, row in cur.iterrows():
        body = json.dumps({c: float(row[c]) for c in FEATURE_COLUMNS}).encode()
        req = urllib.request.Request(f"{api_url}/score", data=body, headers={"Content-Type": "application/json"})
        t0 = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                api_score = json.load(r)["score"]
            diffs.append(abs(api_score - row["score"]))
        except Exception:
            errors += 1
        # Latency is measured by this script on the same machine, so it includes the local HTTP round trip.
        latencies.append((time.perf_counter() - t0) * 1000)

    result.update({
        "requests": len(cur),
        "errors": errors,
        "error_rate": errors / len(cur),
        "latency_ms_p50": float(np.percentile(latencies, 50)),
        "latency_ms_p95": float(np.percentile(latencies, 95)),
        "max_abs_score_diff": float(max(diffs)) if diffs else None,
    })
    return result


# The thresholds used by classify(), taken from the constants above.
THRESHOLDS = {
    "psi_moderate": PSI_MODERATE,
    "alert_shift_medium": ALERT_SHIFT_MEDIUM,
    "alert_shift_high": ALERT_SHIFT_HIGH,
    "alert_ratio_high": ALERT_RATIO_HIGH,
}


def classify(t1, t2, t3, thresholds=THRESHOLDS):
    """Severity rules, checked from most to least severe; the first rule that matches wins.
    Returns (severity, reasons). Takes thresholds as an argument so the same rules can be
    rerun with other settings (monitoring/b3_sensitivity.py).

    Only Tier 1 (t1) and Tier 2 (t2) evidence is used. t3 is accepted for a stable
    signature but deliberately not used: Tier 3 is a retrospective diagnostic and does
    not set severity."""
    reasons = []
    # PAGE only when the service cannot provide predictions (Tier 1 status UNAVAILABLE).
    # DEGRADED (partial /score failures) is reported as Tier 1 status, not as a severity:
    # no production SLO was supplied, so no paging cutoff is invented.
    if system_status(t1) == "UNAVAILABLE":
        if not t1["health_ok"]:
            reasons.append("/health failed")
        elif not t1["model_loaded"]:
            reasons.append("model not loaded")
        else:
            reasons.append("/score API produced no predictions")
        return "PAGE", reasons
    ratio = t2["alert_rate_ratio"]
    material_alert = (ratio >= thresholds["alert_ratio_high"] or ratio <= 1 / thresholds["alert_ratio_high"]
                      or abs(t2["alert_rate_shift"]) >= thresholds["alert_shift_high"])
    if material_alert:
        reasons.append(f"alert rate {t2['alert_rate_ref']:.1%} -> {t2['alert_rate_cur']:.1%}")
        return "HIGH", reasons
    if t2["score_psi"] >= thresholds["psi_moderate"] or abs(t2["alert_rate_shift"]) > thresholds["alert_shift_medium"]:
        reasons.append(f"prediction drift: score PSI {t2['score_psi']:.2f}, alert shift {t2['alert_rate_shift']:+.1%}")
        return "MEDIUM", reasons
    if t2["max_feature_psi"] >= thresholds["psi_moderate"]:
        drifted = [f for f, v in t2["features"].items() if v["psi"] >= thresholds["psi_moderate"]]
        reasons.append(f"feature drift only: {', '.join(drifted)}")
        return "LOW", reasons
    return "OK", reasons


def evaluate(name, description, ref, cur, api_url, rng):
    # Tier 1
    t1 = tier1(api_url, cur) if api_url else {"skipped": True}
    t1["system_status"] = system_status(t1)

    # Tier 2
    features = {}
    for f in FEATURE_COLUMNS:
        p = ks_2samp(ref[f], cur[f]).pvalue
        features[f] = {"psi": psi(ref[f].to_numpy(), cur[f].to_numpy()), "ks_pvalue": float(p), "ks_flagged": bool(p < KS_ALPHA)}
    n_ks_flagged = sum(v["ks_flagged"] for v in features.values())
    alert_ref = float((ref["score"] >= ALERT_THRESHOLD).mean())
    alert_cur = float((cur["score"] >= ALERT_THRESHOLD).mean())
    t2 = {
        "features": features,
        "before_ks_features_flagged": n_ks_flagged,
        "before_dataset_drift": bool(n_ks_flagged / len(FEATURE_COLUMNS) >= DATASET_DRIFT_SHARE),
        "max_feature_psi": max(v["psi"] for v in features.values()),
        "score_psi": psi(ref["score"].to_numpy(), cur["score"].to_numpy()),
        "alert_rate_ref": alert_ref,
        "alert_rate_cur": alert_cur,
        "alert_rate_shift": alert_cur - alert_ref,
        # If the reference never alerts, any alerting in the current window counts as an unbounded increase.
        "alert_rate_ratio": (alert_cur / alert_ref) if alert_ref > 0 else float("inf"),
    }

    # Tier 3
    perf_ref, perf_cur = performance(ref), performance(cur)
    boot_ref, boot_cur = lift_samples(ref, rng), lift_samples(cur, rng)
    # The two windows are resampled independently; pairing the i-th resample of each gives
    # the bootstrap distribution of (current lift - reference lift).
    n = min(len(boot_ref), len(boot_cur))
    delta = boot_cur[:n] - boot_ref[:n]
    t3 = {
        "interval_method": ("95% exploratory row-bootstrap interval (2.5th-97.5th percentiles of "
                            f"{N_BOOT} independent row resamples). Descriptive only: rows are sequentially "
                            "dependent and the data are limited and effectively in-sample, so these are not "
                            "formal confidence intervals or hypothesis tests. Tier 3 does not set severity."),
        "reference": perf_ref,
        "current": perf_cur,
        "lift_row_bootstrap_interval_95_current": [float(np.percentile(boot_cur, 2.5)),
                                                   float(np.percentile(boot_cur, 97.5))],
        "exploratory_change_in_labeled_performance": {
            "lift_change": perf_cur["lift"] - perf_ref["lift"],
            "lift_change_row_bootstrap_interval_95": [float(np.percentile(delta, 2.5)),
                                                      float(np.percentile(delta, 97.5))],
        },
    }

    severity, reasons = classify(t1, t2, t3)

    no_skill = t3["lift_row_bootstrap_interval_95_current"][0] <= 0
    return {
        "scenario": name,
        "description": description,
        "rows_ref": int(len(ref)),
        "rows_cur": int(len(cur)),
        "tier1": t1,
        "tier2": t2,
        "tier3": t3,
        "severity": severity,
        "reasons": reasons,
        "action": ACTIONS[severity],
        "model_fitness_code": ("above_baseline_performance_not_established" if no_skill
                               else "above_baseline_performance_observed_exploratory"),
        "model_fitness": ("ABOVE-BASELINE PERFORMANCE NOT ESTABLISHED ON AVAILABLE DATA" if no_skill
                          else "ABOVE-BASELINE PERFORMANCE OBSERVED ON AVAILABLE DATA (EXPLORATORY)"),
        "fitness_action": FITNESS_ACTION if no_skill else "",
    }


def build_scenarios(args, bundle, tau):
    """Return the scenarios as (name, description, reference frame, current frame)."""
    ref = load_window(args.reference_features, bundle, tau)
    half = len(ref) // 2
    scenarios = [
        ("S0", "Interleaved split: odd rows vs even rows of the reference features",
         ref.iloc[::2], ref.iloc[1::2]),
        ("S1", "Reference features vs features built from sample_ticks_drifted.jsonl",
         ref, load_window(args.current_features, bundle, tau)),
        ("S2", "Split-half: first half vs second half of the reference features (split at the middle row)",
         ref.iloc[:half], ref.iloc[half:]),
    ]
    if os.path.exists(args.msgloss_features):
        scenarios.append(("S3", "Reference features vs features built from sample_ticks_msgloss.jsonl "
                                "(scripts/b3_inject_faults.py; its labels are computed from the reduced message stream)",
                          ref, load_window(args.msgloss_features, bundle, tau)))
    else:
        print(f"[b3_monitor] {args.msgloss_features} not found, skipping S3")
    return scenarios


def main(args):
    with open(args.model, "rb") as f:
        bundle = pickle.load(f)
    # tau: the spike threshold, fixed from the training file (90th percentile of future volatility),
    # the same way models/train_baseline.py sets it, so every window uses one definition of "spike".
    train = pd.read_parquet(args.train_features).dropna(subset=FEATURE_COLUMNS)
    tau = float(future_vol(train).quantile(args.percentile))
    scenarios = build_scenarios(args, bundle, tau)

    rng = np.random.default_rng(args.seed)  # fixed seed so the bootstrap intervals repeat exactly
    api_url = None if args.no_api else args.api_url
    containers = {"skipped": True} if args.no_api else container_status(args.compose_file)
    results = [evaluate(n, d, r, c, api_url, rng) for n, d, r, c in scenarios]

    print(f"[b3_monitor] tau={tau:.3e} (p{int(args.percentile * 100)} of train)  alert threshold={ALERT_THRESHOLD}")
    print(f"[b3_monitor] containers: " + ", ".join(f"{k}={v.get('state')}/{v.get('health')}" for k, v in containers.items()
                                                   if isinstance(v, dict)) if "error" not in containers else
          f"[b3_monitor] containers: {containers}")
    header = f"{'':4}{'KS flagged':>11}{'max feat PSI':>13}{'score PSI':>10}{'alert ref->cur':>17}{'lift 95% row-boot':>18}{'p95 ms':>8}  tier1 / severity / fitness"
    print(header)
    for r in results:
        t1, t2, t3 = r["tier1"], r["tier2"], r["tier3"]
        p95 = f"{t1['latency_ms_p95']:.1f}" if t1.get("latency_ms_p95") is not None else "-"
        ci = t3["lift_row_bootstrap_interval_95_current"]
        print(f"{r['scenario']:4}{t2['before_ks_features_flagged']:>9}/4{t2['max_feature_psi']:>13.3f}{t2['score_psi']:>10.3f}"
              f"{t2['alert_rate_ref']:>8.1%} ->{t2['alert_rate_cur']:>6.1%}{f'[{ci[0]:+.3f}, {ci[1]:+.3f}]':>18}{p95:>8}"
              f"  {t1['system_status']} / {r['severity']} / {r['model_fitness']}")
        if t1["system_status"] == "DEGRADED":
            print(f"{'':6}! Tier 1 DEGRADED: {t1['errors']} of {t1['requests']} /score requests failed "
                  f"(error rate {t1['error_rate']:.1%}); serving issue, not a drift severity")
        for reason in r["reasons"]:
            print(f"{'':6}- {reason}")

    os.makedirs(args.out_dir, exist_ok=True)
    json_path = os.path.join(args.out_dir, "scenarios.json")
    with open(json_path, "w") as f:
        json.dump({"tau": tau, "containers": containers, "thresholds": {
            "alert_threshold": ALERT_THRESHOLD, "psi_moderate": PSI_MODERATE, "psi_significant": PSI_SIGNIFICANT,
            "alert_shift_medium": ALERT_SHIFT_MEDIUM, "alert_shift_high": ALERT_SHIFT_HIGH,
            "alert_ratio_high": ALERT_RATIO_HIGH, "ks_alpha": KS_ALPHA, "dataset_drift_share": DATASET_DRIFT_SHARE,
            "n_boot": N_BOOT, "seed": args.seed},
            "scenarios": results}, f, indent=2)

    csv_path = os.path.join(args.out_dir, "scenarios.csv")
    with open(csv_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["scenario", "before_ks_flagged", "before_dataset_drift", "max_feature_psi", "score_psi",
                    "alert_rate_ref", "alert_rate_cur", "pr_auc_cur", "prevalence_cur", "lift_row_boot95_low", "lift_row_boot95_high",
                    "latency_p50_ms", "latency_p95_ms", "api_errors", "api_error_rate", "tier1_status", "severity", "model_fitness", "action"])
        for r in results:
            t1, t2, t3 = r["tier1"], r["tier2"], r["tier3"]
            w.writerow([r["scenario"], t2["before_ks_features_flagged"], t2["before_dataset_drift"],
                        round(t2["max_feature_psi"], 4), round(t2["score_psi"], 4),
                        round(t2["alert_rate_ref"], 4), round(t2["alert_rate_cur"], 4),
                        round(t3["current"]["pr_auc"], 4), round(t3["current"]["positive_rate"], 4),
                        round(t3["lift_row_bootstrap_interval_95_current"][0], 4),
                        round(t3["lift_row_bootstrap_interval_95_current"][1], 4),
                        t1.get("latency_ms_p50"), t1.get("latency_ms_p95"), t1.get("errors"), t1.get("error_rate"),
                        t1["system_status"],
                        r["severity"], r["model_fitness"], r["action"]])
    print(f"[b3_monitor] saved {json_path} and {csv_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=os.environ.get("MODEL_PATH", "models/artifacts/model.pkl"))
    parser.add_argument("--train_features", default="data/processed/b3_train.parquet",
                        help="Used only to fix the spike-label threshold tau.")
    parser.add_argument("--reference_features", default="data/processed/b3_reference.parquet")
    parser.add_argument("--current_features", default="data/processed/b3_current.parquet")
    parser.add_argument("--msgloss_features", default="data/processed/b3_msgloss.parquet")
    parser.add_argument("--api_url", default="http://localhost:8000")
    parser.add_argument("--compose_file", default="docker/compose.yaml")
    parser.add_argument("--no_api", action="store_true",
                        help="Skip Tier 1 (no running scorer or Docker needed).")
    parser.add_argument("--out_dir", default="data/b3_runs")
    parser.add_argument("--percentile", type=float, default=0.90,
                        help="Spike label percentile; supplied setting (label_spikes default in models/train_baseline.py).")
    parser.add_argument("--seed", type=int, default=0,
                        help="Bootstrap seed; AI-selected implementation choice for the exploratory Tier 3 diagnostic.")
    main(parser.parse_args())
