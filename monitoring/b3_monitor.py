"""
monitoring/b3_monitor.py

B3 model-behavior check. Input drift reports (drift_report.py) tell us
whether the *features* moved; this script checks whether the *model's
behavior* moved. It scores a reference window and a current window with
the deployed model artifact and compares:

  - spike-alert rate  (fraction of rows with prob >= threshold, same rule
                       as scoring/score_service.py)
  - mean score
  - PR-AUC against the volatility-spike label, next to the random floor
    (positive rate) for that window

The spike label uses a fixed tau computed on the training file, so both
windows are judged against the same definition of "spike" the model was
trained on (recomputing tau per window would force ~10% positives in each).
"""
import argparse
import json
import os
import pickle

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, precision_score, recall_score

FEATURE_COLUMNS = ["midprice_returns", "spread_normalized", "order_book_imbalance", "trade_intensity"]


def future_vol(df, horizon=20):
    """Forward rolling std of returns (same definition as models/train_baseline.py)."""
    return df["midprice_returns"].rolling(horizon).std().shift(-horizon)


def load_window(path):
    df = pd.read_parquet(path).dropna(subset=FEATURE_COLUMNS)
    if len(df) < 20:
        raise SystemExit(f"Need at least 20 rows in {path}, found {len(df)}")
    return df


def evaluate(df, bundle, tau, threshold):
    df = df.copy()
    df["fvol"] = future_vol(df)
    df = df.dropna(subset=["fvol"])
    y = (df["fvol"] >= tau).astype(int)

    X = bundle["scaler"].transform(df[bundle["features"]])
    probs = bundle["model"].predict_proba(X)[:, 1]
    alerts = (probs >= threshold).astype(int)

    has_pos = y.sum() > 0
    return {
        "rows_scored": int(len(df)),
        "positive_rate": float(y.mean()),
        "alert_rate": float(alerts.mean()),
        "mean_score": float(probs.mean()),
        "pr_auc": float(average_precision_score(y, probs)) if has_pos else float("nan"),
        "precision_at_threshold": float(precision_score(y, alerts, zero_division=0)),
        "recall_at_threshold": float(recall_score(y, alerts, zero_division=0)) if has_pos else float("nan"),
    }


def main(model_path, train_features, reference_features, current_features, out_path,
         threshold, alert_rate_tol, pr_auc_tol, percentile):
    with open(model_path, "rb") as f:
        bundle = pickle.load(f)

    train = load_window(train_features)
    tau = float(future_vol(train).quantile(percentile))

    ref = evaluate(load_window(reference_features), bundle, tau, threshold)
    cur = evaluate(load_window(current_features), bundle, tau, threshold)

    alert_delta = cur["alert_rate"] - ref["alert_rate"]
    pr_auc_delta = cur["pr_auc"] - ref["pr_auc"]
    checks = {
        "alert_rate_shift": bool(abs(alert_delta) > alert_rate_tol),
        "pr_auc_drop": bool(pr_auc_delta < -pr_auc_tol),
        "pr_auc_at_or_below_floor": bool(cur["pr_auc"] <= cur["positive_rate"]),
    }

    print(f"[b3_monitor] model={model_path}  tau={tau:.3e} (p{int(percentile * 100)} of train)  "
          f"alert threshold={threshold}")
    print(f"{'metric':<24}{'reference':>12}{'current':>12}{'delta':>12}")
    for k in ref:
        d = cur[k] - ref[k]
        fmt = "{:>12d}" if isinstance(ref[k], int) else "{:>12.4f}"
        print(f"{k:<24}" + fmt.format(ref[k]) + fmt.format(cur[k]) + fmt.format(d))
    print()
    for name, fired in checks.items():
        print(f"[b3_monitor] {name:<26} {'ALERT' if fired else 'ok'}")

    result = {
        "model_path": model_path,
        "tau": tau,
        "threshold": threshold,
        "tolerances": {"alert_rate": alert_rate_tol, "pr_auc": pr_auc_tol},
        "reference": {"path": reference_features, **ref},
        "current": {"path": current_features, **cur},
        "deltas": {"alert_rate": alert_delta, "pr_auc": pr_auc_delta},
        "checks": checks,
        "behavior_changed": any(checks.values()),
    }
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(result, f, indent=2, default=lambda o: None if isinstance(o, float) and np.isnan(o) else o)
    print(f"[b3_monitor] saved results to {out_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=os.environ.get("MODEL_PATH", "models/artifacts/model.pkl"))
    parser.add_argument("--train_features", default="data/processed/b3_train.parquet",
                        help="Used only to fix the spike-label threshold tau.")
    parser.add_argument("--reference_features", default="data/processed/b3_reference.parquet")
    parser.add_argument("--current_features", default="data/processed/b3_current.parquet")
    parser.add_argument("--out", default="reports/b3_monitor.json")
    parser.add_argument("--threshold", type=float, default=0.5,
                        help="Alert threshold on model probability (matches score_service.py).")
    parser.add_argument("--alert_rate_tol", type=float, default=0.05,
                        help="Flag if |alert-rate change| exceeds this (absolute).")
    parser.add_argument("--pr_auc_tol", type=float, default=0.02,
                        help="Flag if PR-AUC drops by more than this (absolute).")
    parser.add_argument("--percentile", type=float, default=0.90)
    args = parser.parse_args()
    main(args.model, args.train_features, args.reference_features, args.current_features, args.out,
         args.threshold, args.alert_rate_tol, args.pr_auc_tol, args.percentile)
