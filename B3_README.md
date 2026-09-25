# 94-879 Challenge B3 README: Healthy but Wrong?

Question: the API is up and healthy, but is the model still performing?
B3 separates "is the system up?" from "is the AI still working?" using the
supplied reference and drifted data.

## Data used

| File | What it is |
|---|---|
| `data/sample/sample_ticks.jsonl` | Reference window (782 messages -> 653 feature rows) |
| `data/sample/sample_ticks_drifted.jsonl` | Same ticks with bid/ask pushed apart (spread ~3x wider); nothing else changed |
| `data/sample/sample_ticks_long.jsonl` | Training data: `sample_ticks.jsonl` repeated 18x with new timestamps |

Note: because the long file is the reference file repeated, reference-window
model metrics are effectively in-sample.

## Reproduce

Prerequisites: stack running and healthy (see README.md Quickstart / Smoke test).

```bash
source venv/bin/activate

# 0. Clean start: the featurizer APPENDS to an existing parquet, so delete old outputs first
rm -f data/processed/b3_train.parquet data/processed/b3_reference.parquet data/processed/b3_current.parquet

# 1. Build features. Each window uses its own topics.
#    Always replay before running the featurizer; the consumer group is fixed
#    (featurizer_group) and keeps committed offsets, so a featurizer run with
#    nothing new to read waits forever.
python scripts/replay.py --file data/sample/sample_ticks_long.jsonl --topic b3.train.raw --rate 0
python features/featurizer.py --topic_in b3.train.raw --topic_out b3.train.features --max_messages 11754 --parquet_path data/processed/b3_train.parquet

python scripts/replay.py --file data/sample/sample_ticks.jsonl --topic b3.ref.raw --rate 0
python features/featurizer.py --topic_in b3.ref.raw --topic_out b3.ref.features --max_messages 653 --parquet_path data/processed/b3_reference.parquet

python scripts/replay.py --file data/sample/sample_ticks_drifted.jsonl --topic b3.cur.raw --rate 0
python features/featurizer.py --topic_in b3.cur.raw --topic_out b3.cur.features --max_messages 653 --parquet_path data/processed/b3_current.parquet

# 2. Train (logs to MLflow, writes models/artifacts/model.pkl), then reload the scorer
python models/train_baseline.py --features data/processed/b3_train.parquet
docker compose -f docker/compose.yaml up -d --build scorer
curl -s localhost:8000/health        # expect "model_loaded": true

# 3. Input-drift reports (Evidently)
# Control (no drift expected): first half vs second half of the reference data (default --split 0.5)
python monitoring/drift_report.py --features data/processed/b3_reference.parquet --out reports/b3_control.html
# Real comparison: reference vs drifted
python monitoring/drift_report.py --reference_features data/processed/b3_reference.parquet --current_features data/processed/b3_current.parquet --out reports/b3_ref_vs_drifted.html

# 4. Model-behavior check
python monitoring/b3_monitor.py
python monitoring/b3_monitor.py --current_features data/processed/b3_reference.parquet --out reports/b3_monitor_control.json
```

`reports/` and `data/processed/` are gitignored. Committed copies of the
results are in `data/b3_runs/`.

## Results (interim)

**System health:** broker, mlflow, and scorer all `healthy`; `/health` -> `model_loaded: true`.

**Training PR-AUC (test split):** random floor 0.097, z-score baseline 0.0949, logistic regression 0.1047.

**Input drift (Evidently, KS test)** - `data/b3_runs/drift_summary.csv`

| Comparison | Features flagged | Reading |
|---|---|---|
| Control: reference split in half | 3/4 | False alarm. `trade_intensity` half-means 110 vs 303 due to the 60s window warm-up |
| Reference vs drifted | 1/4 (`spread_normalized`) | Correctly finds the injected spread change |

**Model behavior (`b3_monitor.py`)** - `data/b3_runs/b3_monitor.json`

| Metric | Reference | Drifted | Delta |
|---|---|---|---|
| Alert rate (prob >= 0.5) | 0.4455 | 0.4487 | +0.003 |
| PR-AUC | 0.0699 | 0.0692 | -0.001 |
| Random floor (positive rate) | 0.0727 | 0.0727 | 0 |
| Precision / recall at 0.5 | 0.064 / 0.39 | 0.063 / 0.39 | ~0 |

Takeaways:
- The spread drift is statistically real but has little effect on the model:
  its weight on spread is 0.028, compared with about +/-0.5 on imbalance and intensity.
- The model is at or below the random floor on both windows, and alerts on
  about 45% of rows when about 7% are real spikes. The service looks healthy
  while the model adds no useful signal.
- Feature-drift p-values alone false-alarm on autocorrelated streaming windows,
  so they should trigger investigation, not retraining or paging.
