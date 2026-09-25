# B3: It Is Running, but Is It Still Working? Monitoring and Drift
**Branch:** `B3---Vidhi`

We are testing a monitoring approach that separates **system availability** from **model behavior and usefulness**. The main question is when a change in the data should trigger investigation, and when there is enough evidence to consider a model-level intervention.

## Baseline system confirmed

We successfully ran the supplied stack end to end. Kafka, MLflow, and the scorer containers report healthy, and `/health` returns `model_loaded: true`. We replayed all three supplied datasets through Kafka and the featurizer: training/long file (**11,754 rows**), reference (**653 rows**), and drifted (**653 rows**). We trained the baseline and logistic regression models, logged them to MLflow, and generated Evidently drift reports.

## Operational symptom

The main issue we observed is that **the system can look healthy even when the model is not useful**. Logistic regression PR-AUC is **0.105** on the training test split versus a prevalence baseline of **0.097**, and **0.070** on the reference window versus **0.073**. This gives little evidence that the model is meaningfully separating spike events from non-spike events. The model also predicts a spike on about **45% of observations**, while only about **7%** are actually positive, creating many noisy alerts.

We also found that **input drift does not necessarily mean the model has degraded**. In the drifted dataset (data drift, or covariate shift), the bid/ask spread increases by roughly **3x**, and Evidently strongly flags `spread_normalized` as drifted. However, the model alert rate changes by only **0.003**, and PR-AUC changes by only **0.001**. This suggests that a large statistical shift in one feature may have very little effect on the model's actual behavior.

A negative-control experiment showed another limitation of raw drift detection. When we split the unchanged reference file in half, Evidently flagged **3 of 4 features** as drifted. Initial inspection suggests that part of this comes from the featurizer itself: the 60-second trade-intensity window starts empty and fills over time, creating large differences in feature means even when the underlying data source has not meaningfully changed. This means a drift alert should not automatically be treated as a model failure or a reason to retrain.

## Initial hypothesis

A monitoring approach that separates **(1) system health, (2) data and prediction drift, and (3) labeled model performance** will do a better job of identifying meaningful AI failures than infrastructure checks and per-feature drift tests alone. System health tells us whether the service is functioning technically, data and prediction drift tells us whether inputs or alert rates have changed enough to investigate, and labeled performance tells us whether predictive usefulness has actually worsened once labels are available.

Feature-level drift should trigger **investigation**, not automatic retraining. A stronger intervention should only be considered when the change also affects model outputs or labeled performance, or when we confirm a data or pipeline problem. The monitor should also catch the opposite case: a model that is fully available but already performs close to the prevalence baseline.

### What would disprove this hypothesis?

The hypothesis would be weakened if the proposed monitor raises **drift alerts** on the unchanged split-reference control at rates similar to genuinely changed data, or if the injected spread change materially changes model outputs or labeled performance despite being treated as non-actionable.

## Before/after measures

- **Monitor false-alert rate:** number of **drift alerts** (data drift or prediction drift) raised on the split-reference negative control. Target: **0**. The **performance alert** is expected because PR-AUC remains at or below the prevalence baseline across windows.
- **Input drift:** number of features flagged and the size/significance of their distribution changes.
- **Prediction drift:** alert rate and mean score by window.
- **Labeled model performance:** PR-AUC relative to the prevalence baseline, plus precision and recall at the current decision threshold.
- **Detection of meaningful conditions:** whether the monitor flags weak model performance and material prediction drift.
- **Operational decision:** whether each condition leads to no action, investigation, or escalation for possible model intervention.

The technical intervention supplements the supplied Evidently feature-drift analysis in `monitoring/drift_report.py` with model-behavior and performance checks in `monitoring/b3_monitor.py`. Experimental evidence and outputs are stored in `data/b3_runs/`.
