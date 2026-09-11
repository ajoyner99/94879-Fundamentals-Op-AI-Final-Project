"""
models/train_baseline.py

Trains two models:
  1. a z-score baseline (no fitting required)
  2. a small Logistic Regression model

Both get logged to MLflow (params + PR-AUC + artifact).
"""
import argparse
import os
import pickle

import mlflow
import mlflow.sklearn
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score
from sklearn.preprocessing import StandardScaler

FEATURE_COLUMNS = ["midprice_returns", "spread_normalized", "order_book_imbalance", "trade_intensity"]
ARTIFACTS_DIR = "models/artifacts"


def label_spikes(df, horizon=20, percentile=0.90):
    """Cheap volatility-spike label: forward rolling std of returns vs. a percentile threshold."""
    future_vol = df["midprice_returns"].rolling(horizon).std().shift(-horizon)
    tau = future_vol.quantile(percentile)
    label = (future_vol >= tau).astype(int)
    return label, tau


def time_split(df, train=0.6, val=0.2):
    n = len(df)
    i, j = int(n * train), int(n * (train + val))
    return df.iloc[:i], df.iloc[i:j], df.iloc[j:]


def main(features_path, tracking_uri, experiment_name):
    os.makedirs(ARTIFACTS_DIR, exist_ok=True)
    df = pd.read_parquet(features_path).dropna(subset=FEATURE_COLUMNS)
    df["label"], tau = label_spikes(df)
    df = df.dropna(subset=["label"])

    train_df, val_df, test_df = time_split(df)
    X_train, y_train = train_df[FEATURE_COLUMNS], train_df["label"]
    X_test, y_test = test_df[FEATURE_COLUMNS], test_df["label"]

    mlflow.set_tracking_uri(tracking_uri)
    mlflow.set_experiment(experiment_name)

    # --- Baseline: z-score rule, no fitting ---
    with mlflow.start_run(run_name="baseline_zscore"):
        z = (X_test["midprice_returns"] - X_train["midprice_returns"].mean()) / X_train["midprice_returns"].std()
        baseline_score = z.abs()
        pr_auc = average_precision_score(y_test, baseline_score) if y_test.sum() else float("nan")
        mlflow.log_param("threshold_tau", tau)
        mlflow.log_metric("pr_auc", pr_auc)
        print(f"[train] baseline PR-AUC: {pr_auc:.4f}")

    # --- Small ML model ---
    with mlflow.start_run(run_name="logistic_regression"):
        scaler = StandardScaler().fit(X_train)
        model = LogisticRegression(max_iter=500, class_weight="balanced")
        model.fit(scaler.transform(X_train), y_train)
        probs = model.predict_proba(scaler.transform(X_test))[:, 1]
        pr_auc = average_precision_score(y_test, probs) if y_test.sum() else float("nan")

        mlflow.log_param("threshold_tau", tau)
        mlflow.log_param("features", FEATURE_COLUMNS)
        mlflow.log_metric("pr_auc", pr_auc)
        mlflow.sklearn.log_model(model, "model")
        print(f"[train] logistic regression PR-AUC: {pr_auc:.4f}")

        artifact_path = os.path.join(ARTIFACTS_DIR, "model.pkl")
        with open(artifact_path, "wb") as f:
            pickle.dump({"model": model, "scaler": scaler, "features": FEATURE_COLUMNS}, f)
        print(f"[train] saved scoring artifact to {artifact_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--features", default="data/processed/features.parquet")
    parser.add_argument("--tracking_uri", default=os.environ.get("MLFLOW_TRACKING_URI", "http://localhost:5001"))
    parser.add_argument("--experiment", default="volatility_spike_detection")
    args = parser.parse_args()
    main(args.features, args.tracking_uri, args.experiment)
