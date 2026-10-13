"""
monitoring/b3_exploration.py

This script reproduces exploratory analyses originally performed by the AI
assistant before portions of the final monitoring design were proposed. These
analyses informed candidate design choices and are NOT part of the independent
final evaluation. They are committed for transparency and reproducibility only.

Do not use the output (data/b3_runs/exploration.json) as evaluation evidence or
as validation of any threshold. The evaluation is monitoring/b3_monitor.py.

What was originally run, and what each check reproduces:
  E1  split-half of the reference window: per-feature PSI, score PSI and alert
      rates, on all rows and with the first 60 s of the recording dropped
  E2  reference vs drifted features: the same measures. The original check was
      run only with the first 60 s dropped, so only that version is reproduced.
  E3  Feature-space sensitivity probe, not a pipeline experiment. Two edits
      made directly to the reference features (order_book_imbalance x -1;
      trade_intensity x 0.5):
        - on all labeled rows: alert rate, mean score, PR-AUC (original first check)
        - with the first 60 s dropped: per-feature PSI, score PSI, alert rates
          (original second check)
      The E3 feature edits were applied directly to already-computed features to
      understand how the fitted model responds to specific inputs. They did not
      pass through Kafka or the featurizer and are retained only to reproduce the
      exploratory analysis that informed later design choices. They are not used
      as evaluation evidence.
      The pipeline-faithful follow-up to the trade-intensity exploration is S3:
      message loss was injected at the raw-message level
      (scripts/b3_inject_faults.py), replayed through Kafka, processed by the real
      featurizer, and then evaluated by monitoring/b3_monitor.py.
  E4  interleaved split (odd vs even rows): per-feature PSI and KS p-value,
      score PSI, alert rates
  E5  row bootstrap on the labeled reference rows: 1,000 resamples, seed 0,
      95% percentile intervals of PR-AUC and of lift (PR-AUC minus positive rate)

PSI, scoring and labeling use the functions in monitoring/b3_monitor.py. The
original scratch PSI function was the same calculation (reference deciles,
outer edges opened, shares floored at 0.0001).
"""
import argparse
import json
import os
import pickle
import sys

import numpy as np
import pandas as pd
from scipy.stats import ks_2samp
from sklearn.metrics import average_precision_score

sys.path.insert(0, os.path.dirname(__file__))
from b3_monitor import ALERT_THRESHOLD, FEATURE_COLUMNS, future_vol, load_window, psi  # noqa: E402

DROP_SECONDS = 60  # the original check dropped the first 60 s of each recording


def drop_first_seconds(df, seconds=DROP_SECONDS):
    ts = pd.to_datetime(df["timestamp"])
    return df[ts >= ts.iloc[0] + pd.Timedelta(seconds=seconds)]


def alert_rate(df):
    return float((df["score"] >= ALERT_THRESHOLD).mean())


def drift_measures(ref, cur):
    """Per-feature PSI, score PSI and alert rates for a reference/current pair."""
    return {
        "rows_ref": int(len(ref)),
        "rows_cur": int(len(cur)),
        "feature_psi": {f: psi(ref[f].to_numpy(), cur[f].to_numpy()) for f in FEATURE_COLUMNS},
        "score_psi": psi(ref["score"].to_numpy(), cur["score"].to_numpy()),
        "alert_rate_ref": alert_rate(ref),
        "alert_rate_cur": alert_rate(cur),
    }


def rescore(df, bundle):
    out = df.copy()
    out["score"] = bundle["model"].predict_proba(bundle["scaler"].transform(out[bundle["features"]]))[:, 1]
    return out


def edited(ref, bundle, feature, factor):
    out = ref.copy()
    out[feature] = out[feature] * factor
    return rescore(out, bundle)


def labeled_summary(df):
    """Original first check: alert rate, mean score and PR-AUC on the labeled rows only."""
    d = df.dropna(subset=["label"])
    return {
        "rows": int(len(d)),
        "alert_rate": alert_rate(d),
        "mean_score": float(d["score"].mean()),
        "pr_auc": float(average_precision_score(d["label"].astype(int), d["score"])),
    }


def row_bootstrap(df, n_boot, seed):
    """Original row bootstrap: resample labeled rows with replacement; skip resamples with no positives."""
    d = df.dropna(subset=["label"])
    y, s = d["label"].to_numpy(), d["score"].to_numpy()
    rng = np.random.default_rng(seed)
    pr, base = [], []
    for _ in range(n_boot):
        i = rng.integers(0, len(y), len(y))
        if y[i].sum() == 0:
            continue
        pr.append(average_precision_score(y[i], s[i]))
        base.append(y[i].mean())
    pr, base = np.array(pr), np.array(base)
    return {
        "resamples_requested": n_boot,
        "resamples_used": int(len(pr)),
        "seed": seed,
        "positives": int(y.sum()),
        "pr_auc_95_interval": [float(np.percentile(pr, 2.5)), float(np.percentile(pr, 97.5))],
        "lift_95_interval": [float(np.percentile(pr - base, 2.5)), float(np.percentile(pr - base, 97.5))],
    }


def main(args):
    with open(args.model, "rb") as f:
        bundle = pickle.load(f)
    train = pd.read_parquet(args.train_features).dropna(subset=FEATURE_COLUMNS)
    tau = float(future_vol(train).quantile(0.90))  # same tau as b3_monitor.py

    ref = load_window(args.reference_features, bundle, tau)
    cur = load_window(args.current_features, bundle, tau)
    ref_dropped, cur_dropped = drop_first_seconds(ref), drop_first_seconds(cur)
    half, half_d = len(ref) // 2, len(ref_dropped) // 2

    result = {
        "note": "Provenance only: reproduces AI-assistant exploratory checks run before parts of the design were "
                "proposed. Not evaluation evidence and not validation of any threshold.",
        "tau": tau,
        "rows_dropped_as_first_60s": int(len(ref) - len(ref_dropped)),
        "E1_split_half": {
            "all_rows": drift_measures(ref.iloc[:half], ref.iloc[half:]),
            "first_60s_dropped": drift_measures(ref_dropped.iloc[:half_d], ref_dropped.iloc[half_d:]),
        },
        "E2_reference_vs_drifted": {
            "first_60s_dropped": drift_measures(ref_dropped, cur_dropped),
        },
        "E3_feature_edits": {
            "note": "Feature-space sensitivity probe, not a pipeline experiment: edits applied directly to "
                    "already-computed features; no Kafka or featurizer; not evaluation evidence. The "
                    "pipeline-faithful follow-up to the trade-intensity probe is scenario S3 in b3_monitor.py.",
            "all_labeled_rows": {
                "reference": labeled_summary(ref),
                "order_book_imbalance_x_-1": labeled_summary(edited(ref, bundle, "order_book_imbalance", -1)),
                "trade_intensity_x_0.5": labeled_summary(edited(ref, bundle, "trade_intensity", 0.5)),
            },
            "first_60s_dropped": {
                "order_book_imbalance_x_-1": drift_measures(
                    ref_dropped, edited(ref_dropped, bundle, "order_book_imbalance", -1)),
                "trade_intensity_x_0.5": drift_measures(
                    ref_dropped, edited(ref_dropped, bundle, "trade_intensity", 0.5)),
            },
        },
        "E4_interleaved": {
            **drift_measures(ref.iloc[::2], ref.iloc[1::2]),
            "feature_ks_pvalue": {f: float(ks_2samp(ref.iloc[::2][f], ref.iloc[1::2][f]).pvalue)
                                  for f in FEATURE_COLUMNS},
        },
        "E5_row_bootstrap_reference": row_bootstrap(ref, n_boot=1000, seed=0),
    }

    os.makedirs(args.out_dir, exist_ok=True)
    path = os.path.join(args.out_dir, "exploration.json")
    with open(path, "w") as f:
        json.dump(result, f, indent=2)
    print(json.dumps(result, indent=2))
    print(f"[b3_exploration] saved {path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=os.environ.get("MODEL_PATH", "models/artifacts/model.pkl"))
    parser.add_argument("--train_features", default="data/processed/b3_train.parquet")
    parser.add_argument("--reference_features", default="data/processed/b3_reference.parquet")
    parser.add_argument("--current_features", default="data/processed/b3_current.parquet")
    parser.add_argument("--out_dir", default="data/b3_runs")
    main(parser.parse_args())
