# B3 slide and Q&A text (approved draft, final edits applied)

Source: frozen B3_Explainer.pdf and data/b3_runs/ outputs. 4 main slides + backups.
Figures: the final regenerated PNGs in data/b3_runs/figures/, used unmodified (no re-plotting; labels, thresholds, colors and data unchanged).

---

## Slide 1: It's running. Is it still working?

**Headline:** A healthy service does not mean the AI is behaving appropriately.

- Every scenario: 0 API errors, Tier 1 HEALTHY, model loaded.
- But the model alerts on 45.9% of rows while 7.3% are spikes; precision at the 0.5 alert threshold is 6.4%.
- **Core interim hypothesis, which survived:** health checks and raw feature-drift tests alone can't tell you whether the AI still works. Monitor serving health, data/prediction drift and labeled performance separately. Feature drift means investigate, not retrain.
- **What changed:** our interpretation of the split-half evidence, not the hypothesis.

*Speaker note:* "This hypothesis was in our interim. The final monitor puts it into practice."

---

## Slide 2: Diagnosis. Alerts follow trade intensity, not spikes

**Main visual (most of the slide):** `data/b3_runs/figures/fig_a_diagnosis.png`, used as-is (final regenerated image; no edits to labels, colors or data). Text below is kept short so the figure stays legible.

**On-slide caption:** "Model alerts rise with trade intensity; actual spikes do not."

- PR-AUC 0.070 vs prevalence 0.073 on the reference window: above-baseline performance is not established on the available data.
- Score vs trade intensity r = 0.80; score vs the actual spike label r = 0.006.
- The recording has a 171 s gap. Trade intensity is a rolling 60 s count, so it refills afterwards (167 in the first 60 s after the gap, 305 later). The message rate is about the same: 4.92 vs 4.74 msg/s.
- **Interim correction:** we had used the split-half comparison as a no-change control and called its flags a false alarm. It is a real change: alerts 13.5% to 78.3% while spikes are 6.1% vs 8.5%. It became **S2**; the new control is the interleaved split (**S0**).

*Speaker note:* "We revised the experiment rather than forcing the original explanation to fit."

---

## Slide 3: Intervention and evidence

**Main visual:** `data/b3_runs/figures/fig_b_validation.png`, used as-is (final regenerated image). Stays in the main deck. If the slide is crowded, simplify the scenario table below rather than shrinking Figure B; the slide should visually emphasize S1 vs S2/S3.

**On-slide caption:** "Raw drift flags do not show consequence; model-output impact separates S1 from S2/S3."

**Tiered monitor**
- **Tier 1, serving status:** HEALTHY / DEGRADED / UNAVAILABLE. PAGE only for serving unavailability.
- **Tier 2, drift graded by impact:** LOW = feature drift only; MEDIUM = score PSI >= 0.10 or alert shift > 5 pp; HIGH = alert rate x2 or /2, or shift >= 20 pp.
- **Tier 3, separate and retrospective:** PR-AUC vs prevalence. Never sets severity.

| | Built as | KS before view | Monitor | Why |
|---|---|---|---|---|
| S0 | Odd vs even rows | 0/4 | **OK** | No change; stays quiet |
| S1 | Supplied wider-spread file | 1/4 (p≈0) | **LOW** | Spread PSI 8.2, but score PSI 0.005 and alerts 45.9% to 46.2% |
| S2 | Split-half (gap + refill) | 3/4 | **HIGH** | Alerts 13.5% to 78.3% |
| S3 | Message loss, replayed via Kafka | 2/4 | **HIGH** | Alerts 45.9% to 1.8%, with the service HEALTHY |

**Takeaway:** S1 is a huge input shift the model barely notices, so it gets a data-quality ticket. S2 and S3 change the operator's alert workload, so they escalate. KS reports S1 with p≈0 and no sense of consequence.

*Small note on slide:* 5 pp / 20 pp / 2x are project-specific operating thresholds.

*Speaker note:* Don't walk through each cutoff. Shorthand:
- Feature-only drift → LOW
- Score/output drift or moderate alert movement → MEDIUM
- Major alert-volume disruption → HIGH

Then go straight to S1 versus S2/S3. Exact cutoffs are for Q&A.

---

## Slide 4: How far to trust it, and what to do

**What we know**
- Across 1,485 tested monitoring-setting combinations, the S0–S3 ordering remained unchanged.
- Internal threshold robustness, not independent validation.

**What we don't know**
- All scenarios derive from one ~5-minute recording that also informed the design; there is no independent held-out evaluation.
- Whether the monitor and the model behave appropriately on unseen data.

**What we recommend**
- Provisional, limited use of the monitor until it is tested once on an independently recorded replay window.
- Do not automatically retrain on feature drift (S1): route it to a data-quality check.
- Re-evaluate the model on genuinely out-of-sample labeled data before changing thresholds, retraining or replacing it.

---

## Backup slides

- **B1:** Full severity ladder with actions, plus the Tier 1 status table.
- **B2:** `data/b3_runs/figures/fig_c_fitness.png`, used as-is (backup only): Tier 3 exploratory lift intervals; all four include 0. Caption: "Above-baseline performance is not established on the available data."
- **B3:** Settings provenance table (Lewis constants, Feature-engine, AI-proposed values).
- **B4:** AI supervision: #1 split-half explanation wrong twice, caught by measurement; #2 thresholds accepted provisionally, then stress-tested.

---

## Q&A defense

1. **The split-half reading changed; why does the hypothesis still hold?**
   The hypothesis was about how to monitor: separate health, drift and performance, and treat feature drift as a reason to investigate. What changed was one piece of evidence: a comparison we thought showed no change showed a real one. That correction supports the hypothesis: KS flagged both S1 and S2; only the model-impact view tells them apart.

2. **Why PSI alongside KS?**
   The KS p-value shows evidence of a difference, not its importance. SciPy's ks_2samp assumes independent samples; our streaming rows are serially dependent, so we don't read the p-values as calibrated. KS stays as the "before" baseline. PSI measures shift size; score PSI and alert rate show whether the shift reaches the model's behavior.

3. **Where do 0.10 and 0.25 come from?**
   0.10 and 0.25 are the Lewis constants, traced through Potgieter et al. (2026): conventional credit-scorecard heuristics, not calibrated thresholds. Feature-engine currently defaults to a PSI threshold of 0.25 and documents 0.10 and 0.25 as commonly used values. In our monitor only 0.10 affects severity; 0.25 is a reference line.

4. **Why are 5 pp / 20 pp / 2x project-specific?**
   The AI assistant proposed them and I accepted them; they are not external standards, and no production SLO or alert budget was supplied. That's why the sensitivity grid tested 2–10 pp, 10–40 pp and 1.5–3x.

5. **Why isn't 1,485 out of 1,485 independent validation?**
   It reran the same four scenarios from the same recording, which had also informed the design. It shows the ordering doesn't depend on the exact settings tested, not that the monitor works on new data. S0 was the closest call: its largest feature PSI reached 0.0445 against the lowest tested threshold of 0.05.

6. **Why no held-out test?**
   The repo has one genuine recording; the long training file is that recording repeated 18 times with rewritten timestamps. Re-splitting it would not give independent data. Next: freeze the monitor and test it once on a newly recorded replay window.

7. **Is S3 real?**
   S3 is pipeline-faithful: message loss was injected at the raw-message level, replayed through Kafka, and recomputed by the real featurizer. But pipeline fidelity is not the same as external validity: it is still a constructed fault on the same underlying recording, not a real incident.

8. **Why doesn't Tier 3 control severity?**
   The same Tier 3 outcome appears in every window, including S0, so using it as a change severity would make every scenario HIGH and destroy the monitor's ability to distinguish situations. Labels arrive late (they need the next 20 messages). The intervals come from a row bootstrap on serially dependent rows, so they are exploratory, not formal confidence intervals.

9. **DEGRADED vs PAGE?**
   DEGRADED: /health is fine and some predictions succeed, but some /score requests fail; reported with error counts, no paging, because no SLO was supplied. UNAVAILABLE leads to PAGE: health fails, the model isn't loaded, or no prediction is produced. Neither occurred in the saved runs; they were checked only with constructed inputs.

10. **What does "above-baseline performance not established" mean?**
    On the available data, we do not establish PR-AUC performance above the prevalence/no-information baseline. The exploratory lift interval includes 0, but because the rows are serially dependent and the data are not independent out-of-sample data, we do not treat that as a formal hypothesis test. This does not prove the model is useless or incapable of performing better on unseen data.

11. **What should be tested next?**
    First, test the frozen monitor once on an independently recorded replay window. Second, evaluate the model on genuinely out-of-sample labeled data. After that, test real DEGRADED/UNAVAILABLE serving faults and investigate whether the balanced class weighting contributes to the unusually high alert rate.
