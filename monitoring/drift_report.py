"""
monitoring/drift_report.py

Generates an Evidently HTML report comparing an early "reference" window of
features against a later "current" window. Run against
data/processed/features.parquet, produced by features/featurizer.py (or
scripts/replay.py followed by the featurizer).
"""
import argparse
import os

import pandas as pd
from evidently import Report
from evidently.presets import DataDriftPreset, DataSummaryPreset

FEATURE_COLUMNS = ["midprice_returns", "spread_normalized", "order_book_imbalance", "trade_intensity"]


def main(features_path, out_path, split):
    df = pd.read_parquet(features_path).dropna(subset=FEATURE_COLUMNS)
    if len(df) < 20:
        raise SystemExit(f"Need at least 20 rows to build a report, found {len(df)}")

    cut = int(len(df) * split)
    reference, current = df.iloc[:cut], df.iloc[cut:]

    report = Report(metrics=[DataDriftPreset(), DataSummaryPreset()])
    result = report.run(reference_data=reference[FEATURE_COLUMNS], current_data=current[FEATURE_COLUMNS])

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    result.save_html(out_path)
    print(f"[drift_report] reference rows={len(reference)}, current rows={len(current)}")
    print(f"[drift_report] saved report to {out_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--features", default="data/processed/features.parquet")
    parser.add_argument("--out", default="reports/drift_report.html")
    parser.add_argument("--split", type=float, default=0.5,
                         help="Fraction of rows used as the reference window (rest = current)")
    args = parser.parse_args()
    main(args.features, args.out, args.split)
