# 94-879 Challenge B3 README: Healthy but Wrong?

Question: the API is up and healthy, but is the model still behaving
appropriately? B3 separates "is the system up?" from "is the AI still working?"
and maps the evidence to one action per situation.

## Methodological status (read first)

Evidence hierarchy:

1. **S0-S3: controlled development/evaluation scenarios** showing how the frozen
   monitor behaves under four known conditions. They are not a held-out or
   independent test set.
2. **Sensitivity analysis: internal threshold-robustness analysis** testing
   whether the S0-S3 conclusions depend on the exact project-specific threshold
   and PSI settings. It is not validation of the monitor or of the thresholds.
3. **No held-out evaluation.** Independent generalization remains untested
   because no genuinely new market recording exists in the supplied repository.
4. **Remaining uncertainty:** whether the frozen monitor behaves appropriately on
   unseen market windows and different failure modes.

**Independent validation limitation.** All supplied market-data artifacts
ultimately derive from one approximately five-minute recording, including the
repeated training data and transformed scenario files. The monitoring design
was also informed by exploratory analysis of this recording. Therefore, S0-S3
should be interpreted as controlled development/evaluation scenarios rather than
a held-out test set. The sensitivity analysis shows that their ordering is
robust to the tested monitoring settings, but it does not establish
generalization to unseen data or failure modes. A future evaluation should
freeze the monitor and test it once on an independently recorded replay window.

## Data used

| File | What it is | Used for |
|---|---|---|
| `data/sample/sample_ticks.jsonl` | The only genuine recording: BTC-USD, 2025-11-12 17:07:45-17:12:53 UTC (782 messages, 653 ticker rows) | Reference side of S0-S3, diagnosis, exploration, sensitivity |
| `data/sample/sample_ticks_drifted.jsonl` | Same messages and timestamps; only `best_bid` / `best_ask` changed (spread about 3x wider) | S1 |
| `data/sample/sample_ticks_long.jsonl` | The reference repeated 18 times with rewritten timestamps | Model training; spike threshold tau |
| `data/sample/sample_ticks_msgloss.jsonl` | Created by `scripts/b3_inject_faults.py`: the reference with every other ticker message removed | S3 |

`data/processed/features.parquet` (starter-kit smoke test) is the first 10 s of
the same recording and is not used by B3. The identity checks (long file = 18
repeats; drifted file changes only bid/ask) are saved in
`data/b3_runs/diagnosis.json` (`data_files`).

## Scripts

| Script | Role | Output |
|---|---|---|
| `monitoring/b3_monitor.py` | The tiered monitor; runs S0-S3 (controlled evaluation) | `scenarios.json`, `scenarios.csv` |
| `monitoring/b3_diagnosis.py` | Diagnosis numbers quoted in the docs (data identity, model weights, training PR-AUC, recording gap, Evidently runs) | `diagnosis.json`, `minute_table.csv` |
| `monitoring/b3_sensitivity.py` | Internal threshold-robustness analysis over 1,485 setting combinations | `sensitivity.csv`, `sensitivity_summary.json` |
| `monitoring/b3_exploration.py` | **Provenance only**: reproduces exploratory checks first run by the AI assistant before parts of the design were proposed. Not evaluation evidence. | `exploration.json` |
| `monitoring/b3_figures.py` | Slide figures drawn from the saved monitor output | `figures/fig_a/b/c` |
| `scripts/b3_inject_faults.py` | Builds the S3 message-loss recording | `sample_ticks_msgloss.jsonl` |

All outputs go to `data/b3_runs/`.

## Reproduce

Prerequisite: the Docker stack running and healthy (README.md Quickstart /
Smoke test). Run each command on its own line from the repository root.

Clean start. The featurizer appends to an existing parquet, so delete old outputs:

```bash
source venv/bin/activate
rm -f data/processed/b3_train.parquet data/processed/b3_reference.parquet data/processed/b3_current.parquet data/processed/b3_msgloss.parquet
```

Build features through Kafka and the featurizer. Each window uses its own topics.
Always replay before running the featurizer: the consumer group
(`featurizer_group`) keeps committed offsets, so a featurizer run with nothing
new to read waits forever. `327` is the ticker count printed by
`b3_inject_faults.py`.

```bash
python scripts/replay.py --file data/sample/sample_ticks_long.jsonl --topic b3.train.raw --rate 0
python features/featurizer.py --topic_in b3.train.raw --topic_out b3.train.features --max_messages 11754 --parquet_path data/processed/b3_train.parquet
python scripts/replay.py --file data/sample/sample_ticks.jsonl --topic b3.ref.raw --rate 0
python features/featurizer.py --topic_in b3.ref.raw --topic_out b3.ref.features --max_messages 653 --parquet_path data/processed/b3_reference.parquet
python scripts/replay.py --file data/sample/sample_ticks_drifted.jsonl --topic b3.cur.raw --rate 0
python features/featurizer.py --topic_in b3.cur.raw --topic_out b3.cur.features --max_messages 653 --parquet_path data/processed/b3_current.parquet
python scripts/b3_inject_faults.py
python scripts/replay.py --file data/sample/sample_ticks_msgloss.jsonl --topic b3.loss.raw --rate 0
python features/featurizer.py --topic_in b3.loss.raw --topic_out b3.loss.features --max_messages 327 --parquet_path data/processed/b3_msgloss.parquet
```

Train (logs to MLflow, writes `models/artifacts/model.pkl`) and reload the scorer:

```bash
python models/train_baseline.py --features data/processed/b3_train.parquet
docker compose -f docker/compose.yaml up -d --build scorer
curl -s localhost:8000/health
```

Run the B3 analysis. `b3_monitor.py` needs the scorer for Tier 1 (`--no_api`
skips Tier 1 and reports it as NOT_CHECKED). The other scripts read only the
saved feature files and `model.pkl`; they do not need Docker or Kafka.

```bash
python monitoring/b3_monitor.py
python monitoring/b3_diagnosis.py
python monitoring/b3_sensitivity.py
python monitoring/b3_exploration.py
python monitoring/b3_figures.py
```

Interim Evidently HTML reports (supplied `drift_report.py`; `reports/` is gitignored):

```bash
python monitoring/drift_report.py --features data/processed/b3_reference.parquet --out reports/b3_control.html
python monitoring/drift_report.py --reference_features data/processed/b3_reference.parquet --current_features data/processed/b3_current.parquet --out reports/b3_ref_vs_drifted.html
```

## Diagnosis

Source: `diagnosis.json` (`reference_window`, `model`, `training_eval`) and `minute_table.csv`.

- Training test split: logistic regression PR-AUC 0.1047, z-score baseline
  0.0949, prevalence 0.0966.
- Reference window: 46 positives in 633 labeled rows. The model's score
  correlates 0.80 with `trade_intensity` and 0.006 with the spike label;
  `trade_intensity` itself correlates -0.033 with the label, although it has the
  model's largest weight (+0.507 on standardized features).
- The recording has 67 rows (13.6 s), then 171 s with no rows, then 586 rows.
  `trade_intensity` counts messages in the last 60 s, so it stays low until the
  window fills: it never exceeds 67 before the gap, averages 167 in the first
  60 s after the gap and 305 afterwards. The message rate itself is about the
  same on both sides (4.92 vs 4.74 messages/s).

## Interim hypothesis and what changed

The core hypothesis was submitted at the interim (`B3_interim_checkpoint_v3.md`):
infrastructure health and raw feature-drift tests alone are not enough to tell
whether the AI is still working appropriately; a monitor separating system
health, data/prediction drift and labeled performance should better identify
meaningful failures; feature drift should trigger investigation, not automatic
retraining, unless it also affects model outputs or performance. That hypothesis
survived; the final monitor operationalizes it.

What changed:

- **Split-half comparison.** The interim used it as an "unchanged" control and
  treated its 3/4 feature flags as a false alarm. The halves genuinely differ:
  splitting at the middle row puts the 67 pre-gap rows and 259 refill rows into
  the first half (mean trade_intensity 110 vs 303), and the model's alert rate
  goes from 13.5% to 78.3% while the actual spike rate is 6.1% and 8.5%. The
  cause is the rolling 60 s trade_intensity window refilling after the 171 s
  gap, not a change in message rate. It became S2; the no-change control is now
  the interleaved split (S0).
- **Performance wording.** "The model is not useful" is replaced by
  "above-baseline performance is not established on the available data".
- **Weak-model alert.** Tier 3 is now a separate retrospective, descriptive
  diagnostic and does not set severity.
- **Drift alerts.** Now an explicit ladder: Tier 1 status; feature, score and
  alert-volume drift; severity OK / LOW / MEDIUM / HIGH, with PAGE for serving
  unavailability.

The AI assistant's role in the split-half explanation is recorded in
`B3_AI_DECISIONS.md`.

## Monitor design (frozen)

**Tier 1, system status** (separate from drift severity):

| Status | Meaning | Action |
|---|---|---|
| HEALTHY | `/health` ok, model loaded, every `/score` request produced a prediction | Proceed |
| DEGRADED | `/health` ok and at least one prediction, but one or more `/score` requests failed | Reported as a serving/reliability issue; no drift severity, no paging cutoff |
| UNAVAILABLE | `/health` fails, model not loaded, or no prediction produced | PAGE |
| NOT_CHECKED | Tier 1 skipped (`--no_api`) | Tier 1 was not evaluated; not "healthy" |

Error count, error rate, p50/p95 latency, container status and API-vs-`model.pkl`
score agreement are recorded every run. No production SLO or validated
error-rate paging threshold was supplied, so none is used.

**Drift severity** (Tier 1 and Tier 2 only; first matching rule wins):

| Level | Rule | Action |
|---|---|---|
| PAGE | Tier 1 UNAVAILABLE | Page on-call; restore the service |
| HIGH | Alert rate doubles or halves, or shifts by 20 percentage points or more | Escalate to model owner and pipeline on-call; consider pausing alerts; labeled evidence is needed to establish a performance problem, and root-cause analysis determines whether retraining is appropriate |
| MEDIUM | Score PSI >= 0.10, or alert-rate shift > 5 percentage points | Investigate same day; no retraining unless labeled evidence establishes a performance problem |
| LOW | Any feature PSI >= 0.10 (output did not move enough for MEDIUM) | Data-quality ticket; no model action |
| OK | None of the above | No action |

**Tier 3, retrospective model-fitness diagnostic** (does not set severity):
PR-AUC, prevalence baseline, lift (PR-AUC minus prevalence), and a 95%
exploratory row-bootstrap interval for lift. Rows in the evaluation stream are
sequentially dependent, while this bootstrap resamples individual rows
independently, so the interval is a descriptive uncertainty diagnostic, not a
formal confidence interval or hypothesis test. Label: "ABOVE-BASELINE
PERFORMANCE NOT ESTABLISHED ON AVAILABLE DATA" when the interval's lower end is
<= 0. This does not prove the model is useless or incapable of performing
better on unseen data.

**Settings and where they come from:**

| Setting | Value | Origin |
|---|---|---|
| Alert threshold | 0.5 | Supplied (`scoring/score_service.py`) |
| Spike label | 90th percentile, 20-row horizon | Supplied (`label_spikes` in `models/train_baseline.py`) |
| Operational PSI threshold | 0.10 | Conventional PSI heuristic band from credit-scorecard practice (Lewis 1994, as traced by Potgieter et al. 2026, *Annals of Operations Research* 361:413-435); not a statistically calibrated universal threshold |
| PSI reference band | 0.25 | Same source; descriptive/visualization line only, never triggers a severity |
| PSI bins | 10 | Matches Feature-engine's current default |
| PSI empty-bin handling | 0.0001 | Our monitor uses the same numeric constant, 0.0001, but a different implementation: Feature-engine replaces/adds the constant for empty or zero bins, whereas our psi() floors bin proportions at that minimum. |
| MEDIUM alert shift | 5 pp | AI-proposed, project-specific; accepted by the owner; not an external standard |
| HIGH alert shift / ratio | 20 pp / 2x | AI-proposed, project-specific; accepted by the owner; not external standards |
| KS p < 0.05; dataset drift at >= 50% of features | | Evidently defaults, used for the "before" comparison only |
| Bootstrap resamples / seed | 1,000 / 0 | AI-selected implementation choices for the exploratory Tier 3 diagnostic |

## Results: controlled development/evaluation scenarios S0-S3

Source: `data/b3_runs/scenarios.json` / `scenarios.csv` (saved run).

| Scenario | How it is built | Before: KS features flagged | Max feature PSI | Score PSI | Alert rate ref -> cur | Tier 1 | Severity |
|---|---|---|---|---|---|---|---|
| S0 | Interleaved odd vs even rows of the reference | 0/4 | 0.019 | 0.011 | 46.2% -> 45.7% | HEALTHY | OK |
| S1 | Reference vs drifted file | 1/4 | 8.245 | 0.005 | 45.9% -> 46.2% | HEALTHY | LOW |
| S2 | First vs second half of the reference | 3/4 | 7.894 | 4.433 | 13.5% -> 78.3% | HEALTHY | HIGH |
| S3 | Reference vs message-loss file (replayed through Kafka) | 2/4 | 4.885 | 2.989 | 45.9% -> 1.8% | HEALTHY | HIGH |

Evidently itself, run on the same pairs (`diagnosis.json`, `evidently`), gives
the same counts and dataset-drift verdicts (No / No / Yes / Yes; S3 is exactly
at the 50% line).

Tier 1 in the saved run: all containers running/healthy, 0 API errors in every
scenario, p95 latency 4.1-5.0 ms (latency varies between runs; quote the saved
run), and API scores match `model.pkl` (largest difference 1.1e-16).

Tier 3 (exploratory row-bootstrap interval for lift, current window): S0
[-0.012, +0.032], S1 [-0.012, +0.015], S2 [-0.025, +0.006], S3 [-0.059, +0.005].
All four include 0: above-baseline performance not established on available
data. S3's labels are computed from the reduced message stream.

## Internal threshold-robustness analysis

Source: `data/b3_runs/sensitivity_summary.json`.

Grid: operational PSI threshold {0.05, 0.10, 0.15, 0.25, 0.50}; MEDIUM shift {2,
5, 10} pp; HIGH shift {10, 20, 30, 40} pp; HIGH ratio {1.5, 2, 3}; PSI bins {5,
10, 20}; PSI floor {1e-6, 1e-4, 1e-3}; combinations with MEDIUM >= HIGH shift
excluded, leaving 1,485.

Across 1,485 tested monitoring-setting combinations, the S0-S3 ordering
remained unchanged. This suggests that the observed scenario separation is not
dependent on the exact threshold and PSI settings tested. However, because all
scenarios ultimately derive from the same underlying recording and informed
monitor development, this is an internal robustness analysis, not independent
validation.

Closest margin: at the 0.05 PSI threshold, S0's largest feature PSI reached
0.0445 under some bins/floor settings.

## Interim-only files

`data/b3_runs/b3_monitor.json` and `b3_monitor_control.json` were produced by
the first version of `b3_monitor.py`, which no longer exists, so they cannot be
reproduced. They are kept only as a record of the interim; their reference-vs-
drifted metrics are superseded by S1 in `scenarios.json`.
