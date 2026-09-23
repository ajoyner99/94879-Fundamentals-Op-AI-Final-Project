"""
monitoring/drift_report.py

Generates an Evidently HTML report comparing a "reference" window of
features against a "current" window.

Two modes:
  - Two-file mode: pass --reference_features and --current_features to
    compare two independently-produced parquet files directly.
  - Single-file mode (default): pass --features and this file is split
    into an early/late portion by --split.
"""
import argparse
import os

import pandas as pd
from evidently import Report
from evidently.presets import DataDriftPreset, DataSummaryPreset

FEATURE_COLUMNS = ["midprice_returns", "spread_normalized", "order_book_imbalance", "trade_intensity"]


def _load_reference_and_current(features_path, split, reference_features, current_features):
    if bool(reference_features) != bool(current_features):
        raise SystemExit(
            "--reference_features and --current_features must be given together. "
            f"Got reference_features={reference_features!r}, current_features={current_features!r}."
        )
    if reference_features and current_features:
        reference = pd.read_parquet(reference_features).dropna(subset=FEATURE_COLUMNS)
        current = pd.read_parquet(current_features).dropna(subset=FEATURE_COLUMNS)
        if len(reference) < 20 or len(current) < 20:
            raise SystemExit(
                f"Need at least 20 rows in each of reference/current, found "
                f"reference={len(reference)}, current={len(current)}"
            )
        return reference, current

    df = pd.read_parquet(features_path).dropna(subset=FEATURE_COLUMNS)
    if len(df) < 20:
        raise SystemExit(f"Need at least 20 rows to build a report, found {len(df)}")
    cut = int(len(df) * split)
    return df.iloc[:cut], df.iloc[cut:]


def main(features_path, out_path, split, reference_features=None, current_features=None):
    reference, current = _load_reference_and_current(
        features_path, split, reference_features, current_features
    )

    report = Report(metrics=[DataDriftPreset(), DataSummaryPreset()])
    result = report.run(reference_data=reference[FEATURE_COLUMNS], current_data=current[FEATURE_COLUMNS])

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    result.save_html(out_path)
    print(f"[drift_report] reference rows={len(reference)}, current rows={len(current)}")
    print(f"[drift_report] saved report to {out_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--features", default="data/processed/features.parquet",
                         help="Single-file mode: split this file by --split.")
    parser.add_argument("--out", default="reports/drift_report.html")
    parser.add_argument("--split", type=float, default=0.5,
                         help="Single-file mode only: fraction of rows used as the reference "
                              "window (rest = current)")
    parser.add_argument("--reference_features", default=None,
                         help="Two-file mode: path to the reference-window features parquet. "
                              "Must be given together with --current_features.")
    parser.add_argument("--current_features", default=None,
                         help="Two-file mode: path to the current-window features parquet. "
                              "Must be given together with --reference_features.")
    args = parser.parse_args()
    main(args.features, args.out, args.split, args.reference_features, args.current_features)
