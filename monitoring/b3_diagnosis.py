"""
monitoring/b3_diagnosis.py

Computes and saves every B3 diagnosis number that is quoted in the README,
the explainer PDF and the slides but is not produced by b3_monitor.py. Each
section below names the claim it backs up, so every quoted number can be
traced to code and to a saved output.

Outputs (in --out_dir, default data/b3_runs):
  diagnosis.json      all numbers below, grouped by section
  minute_table.csv    reference window per minute: rows, mean trade_intensity,
                      model alert rate, actual spike rate

Sections:
  1. data_files       the training file is the reference repeated; the drifted
                      file changes only bid/ask; how much wider the spread is
  2. model            the deployed model's settings and per-feature weights
  3. training_eval    PR-AUC of the model and the z-score baseline on the
                      training test split, and that split's prevalence
                      (re-computed with the same functions as train_baseline.py)
  4. reference_window positives, the recording gap, message rate before and
                      after the gap, how trade_intensity refills after the gap,
                      and correlations of the score with trade_intensity and label
  5. evidently        the supplied Evidently drift preset run on every scenario,
                      to compare with the KS "before" view inside b3_monitor.py
"""
import argparse
import json
import os
import pickle
import sys

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score

# Reuse the exact training-time functions so the training numbers are not re-derived by hand.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from models.train_baseline import FEATURE_COLUMNS, label_spikes, time_split  # noqa: E402
sys.path.insert(0, os.path.dirname(__file__))
from b3_monitor import ALERT_THRESHOLD, DATASET_DRIFT_SHARE, load_window  # noqa: E402

# trade_intensity counts messages in the last 60 s: WINDOW_SIZE_SECONDS in features/featurizer.py
from features.featurizer import WINDOW_SIZE_SECONDS as WINDOW_SECONDS  # noqa: E402


def read_jsonl(path):
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def strip_times(msg):
    """Drop the fields that legitimately differ between copies of the same message."""
    return json.dumps({k: v for k, v in msg.items() if k not in ("timestamp", "received_at", "sequence_num")},
                      sort_keys=True)


def data_files(sample_dir, ref_feat, cur_feat):
    ref = read_jsonl(os.path.join(sample_dir, "sample_ticks.jsonl"))
    long = read_jsonl(os.path.join(sample_dir, "sample_ticks_long.jsonl"))
    drifted = read_jsonl(os.path.join(sample_dir, "sample_ticks_drifted.jsonl"))

    # Is the training (long) file the reference file repeated, apart from timestamps?
    repeats = len(long) / len(ref)
    long_is_repeat = len(long) % len(ref) == 0 and all(
        strip_times(long[i]) == strip_times(ref[i % len(ref)]) for i in range(len(long)))

    # Which ticker fields differ between the reference and the drifted file?
    changed_fields = set()
    lines_changed = 0
    for a, b in zip(ref, drifted):
        if strip_times(a) == strip_times(b):
            continue
        lines_changed += 1
        for ea, eb in zip(a.get("events", []), b.get("events", [])):
            for ta, tb in zip(ea.get("tickers", []), eb.get("tickers", [])):
                changed_fields |= {k for k in ta if ta.get(k) != tb.get(k)}

    r = pd.read_parquet(ref_feat)
    c = pd.read_parquet(cur_feat)
    return {
        "reference_messages": len(ref),
        "long_messages": len(long),
        "long_over_reference": repeats,
        "long_is_reference_repeated_ignoring_timestamps": bool(long_is_repeat),
        "drifted_lines_changed": lines_changed,
        "drifted_fields_changed": sorted(changed_fields),
        "spread_normalized_median_reference": float(r["spread_normalized"].median()),
        "spread_normalized_median_drifted": float(c["spread_normalized"].median()),
        "spread_median_ratio_drifted_over_reference": float(c["spread_normalized"].median() / r["spread_normalized"].median()),
    }


def model_info(bundle):
    m = bundle["model"]
    return {
        "type": type(m).__name__,
        "class_weight": m.class_weight,
        "features": list(bundle["features"]),
        # Weights apply to standardized features (StandardScaler), so their sizes are comparable.
        "weights_on_standardized_features": dict(zip(bundle["features"], [float(w) for w in m.coef_[0]])),
        "intercept": float(m.intercept_[0]),
        "alert_threshold": ALERT_THRESHOLD,
    }


def training_eval(train_path, bundle):
    """Same steps as models/train_baseline.py main(): label on the whole file, 60/20/20 time split,
    evaluate on the last 20%. The z-score baseline uses train-split mean/std of midprice_returns."""
    df = pd.read_parquet(train_path).dropna(subset=FEATURE_COLUMNS)
    df["label"], tau = label_spikes(df)
    df = df.dropna(subset=["label"])
    train_df, _, test_df = time_split(df)
    y = test_df["label"]
    z = (test_df["midprice_returns"] - train_df["midprice_returns"].mean()) / train_df["midprice_returns"].std()
    probs = bundle["model"].predict_proba(bundle["scaler"].transform(test_df[FEATURE_COLUMNS]))[:, 1]
    return {
        "tau": float(tau),
        "test_rows": int(len(test_df)),
        "test_prevalence": float(y.mean()),
        "pr_auc_logistic_regression": float(average_precision_score(y, probs)),
        "pr_auc_zscore_baseline": float(average_precision_score(y, z.abs())),
    }


def reference_window(ref_path, bundle, tau, out_dir):
    df = load_window(ref_path, bundle, tau)  # same scoring and labels as b3_monitor.py
    ts = pd.to_datetime(df["timestamp"])
    df["t"] = (ts - ts.iloc[0]).dt.total_seconds()

    # The recording gap: the largest jump between consecutive timestamps.
    gaps = df["t"].diff()
    g = int(gaps.idxmax())          # first row after the gap
    pre, post = df.iloc[:g], df.iloc[g:].copy()
    post["since_gap"] = post["t"] - post["t"].iloc[0]
    refill = post[post["since_gap"] < WINDOW_SECONDS]
    full = post[post["since_gap"] >= WINDOW_SECONDS]
    half = len(df) // 2

    labeled = df.dropna(subset=["label"])
    out = {
        "rows": int(len(df)),
        "labeled_rows": int(len(labeled)),
        "positives": int(labeled["label"].sum()),
        "positive_rate": float(labeled["label"].mean()),
        "alert_rate": float((df["score"] >= ALERT_THRESHOLD).mean()),
        "gap_seconds": float(gaps.max()),
        "rows_before_gap": int(g),
        "positives_before_gap": int(pre["label"].sum()),
        "seconds_before_gap": float(pre["t"].iloc[-1] - pre["t"].iloc[0]),
        "messages_per_second_before_gap": float(len(pre) / (pre["t"].iloc[-1] - pre["t"].iloc[0])),
        "seconds_after_gap": float(post["t"].iloc[-1] - post["t"].iloc[0]),
        "messages_per_second_after_gap": float(len(post) / (post["t"].iloc[-1] - post["t"].iloc[0])),
        "max_trade_intensity_before_gap": int(pre["trade_intensity"].max()),
        # After the gap the 60 s window starts empty again and has to refill.
        "rows_first_60s_after_gap": int(len(refill)),
        "mean_trade_intensity_first_60s_after_gap": float(refill["trade_intensity"].mean()),
        "rows_after_first_60s_after_gap": int(len(full)),
        "mean_trade_intensity_after_first_60s_after_gap": float(full["trade_intensity"].mean()),
        # What the first half of the split-half comparison (S2 reference) is made of.
        "halfway_row": half,
        "first_half_rows_before_gap": int(min(g, half)),
        "first_half_rows_in_refill": int(((df.index >= g) & (df.index < half) & (df["t"] < post["t"].iloc[0] + WINDOW_SECONDS)).sum()),
        "first_half_mean_trade_intensity": float(df["trade_intensity"].iloc[:half].mean()),
        "second_half_mean_trade_intensity": float(df["trade_intensity"].iloc[half:].mean()),
        "corr_score_vs_trade_intensity": float(np.corrcoef(df["score"], df["trade_intensity"])[0, 1]),
        "corr_score_vs_label": float(labeled[["score", "label"]].corr().iloc[0, 1]),
        "corr_trade_intensity_vs_label": float(labeled[["trade_intensity", "label"]].corr().iloc[0, 1]),
    }

    df["minute"] = (df["t"] // 60).astype(int)
    table = df.groupby("minute").agg(
        rows=("t", "size"),
        mean_trade_intensity=("trade_intensity", "mean"),
        alert_rate=("score", lambda s: (s >= ALERT_THRESHOLD).mean()),
        spike_rate=("label", "mean"),
    ).round(3)
    table.to_csv(os.path.join(out_dir, "minute_table.csv"))
    out["minute_table"] = table.reset_index().to_dict(orient="records")
    return out


def evidently_check(ref_path, cur_path, msgloss_path):
    """Run the supplied Evidently DataDriftPreset on each scenario's reference/current pair."""
    from evidently import Report
    from evidently.presets import DataDriftPreset

    ref = pd.read_parquet(ref_path).dropna(subset=FEATURE_COLUMNS).reset_index(drop=True)[FEATURE_COLUMNS]
    half = len(ref) // 2
    pairs = {
        "S0": (ref.iloc[::2], ref.iloc[1::2]),
        "S1": (ref, pd.read_parquet(cur_path).dropna(subset=FEATURE_COLUMNS)[FEATURE_COLUMNS]),
        "S2": (ref.iloc[:half], ref.iloc[half:]),
    }
    if os.path.exists(msgloss_path):
        pairs["S3"] = (ref, pd.read_parquet(msgloss_path).dropna(subset=FEATURE_COLUMNS)[FEATURE_COLUMNS])

    out = {}
    for name, (a, b) in pairs.items():
        metrics = Report(metrics=[DataDriftPreset()]).run(reference_data=a, current_data=b).dict()["metrics"]
        result = {"per_feature": {}}
        for m in metrics:
            label = m["metric_name"]
            if label.startswith("DriftedColumnsCount"):
                result["drifted_count"] = float(m["value"]["count"])
                result["drifted_share"] = float(m["value"]["share"])
            elif label.startswith("ValueDrift"):
                column = label.split("column=")[1].split(",")[0]
                result["per_feature"][column] = {"method": label.split("method=")[1].split(",")[0],
                                                 "p_value": float(m["value"])}
        # Evidently declares dataset drift when the drifted share is >= its drift_share (0.5 by default).
        result["dataset_drift"] = result["drifted_share"] >= DATASET_DRIFT_SHARE
        out[name] = result
    return out


def main(args):
    os.makedirs(args.out_dir, exist_ok=True)
    with open(args.model, "rb") as f:
        bundle = pickle.load(f)

    train_eval = training_eval(args.train_features, bundle)
    result = {
        "data_files": data_files(args.sample_dir, args.reference_features, args.current_features),
        "model": model_info(bundle),
        "training_eval": train_eval,
        "reference_window": reference_window(args.reference_features, bundle, train_eval["tau"], args.out_dir),
        "evidently": evidently_check(args.reference_features, args.current_features, args.msgloss_features),
    }
    path = os.path.join(args.out_dir, "diagnosis.json")
    with open(path, "w") as f:
        json.dump(result, f, indent=2)
    print(json.dumps({k: v for k, v in result.items() if k != "reference_window"}, indent=2))
    print(json.dumps({k: v for k, v in result["reference_window"].items() if k != "minute_table"}, indent=2))
    print(pd.read_csv(os.path.join(args.out_dir, "minute_table.csv")).to_string(index=False))
    print(f"[b3_diagnosis] saved {path} and minute_table.csv")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=os.environ.get("MODEL_PATH", "models/artifacts/model.pkl"))
    parser.add_argument("--sample_dir", default="data/sample")
    parser.add_argument("--train_features", default="data/processed/b3_train.parquet")
    parser.add_argument("--reference_features", default="data/processed/b3_reference.parquet")
    parser.add_argument("--current_features", default="data/processed/b3_current.parquet")
    parser.add_argument("--msgloss_features", default="data/processed/b3_msgloss.parquet")
    parser.add_argument("--out_dir", default="data/b3_runs")
    main(parser.parse_args())
