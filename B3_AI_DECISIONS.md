# B3 Decision Log and AI Supervision Notes

Owner: Vidhi Kothari · Branch: `B3---Vidhi`

This file records the B3 design decisions after the interim: the options
considered, what was chosen, why, and where each choice came from. Provenance
categories used below:

- **Supplied**: from the course starter code or its defaults
- **External convention**: from a cited outside source
- **AI-proposed, owner-accepted**: proposed by the AI coding assistant (Claude); the owner accepted it
- **AI-proposed, owner-modified**: proposed by the AI assistant; the owner changed it
- **Owner-directed**: specified by the owner
- **Exploratory provenance**: analysis that informed the design; not evaluation evidence (`monitoring/b3_exploration.py`)

The methodology is now frozen (`b3_monitor.py`, `b3_sensitivity.py`, S0-S3,
all thresholds). See `B3_README.md` for the evidence hierarchy and the
independent validation limitation.

## Decision log

| # | Decision | Options considered | Chosen | Rationale | Provenance |
|---|---|---|---|---|---|
| D1 | Which scenarios | S0-S2 only (AI recommendation); S0-S2 + S3 replayed through Kafka; S0-S2 + S3 edited in the parquet | S0-S3, with S3 replayed through Kafka | A second consequential case, injected at the raw-message level so it passes through the real pipeline | Options AI-proposed; **owner chose against the AI recommendation** |
| D2 | No-change control | Interleaved odd/even rows; reference vs itself; split-half | Interleaved split (S0) | Both halves cover the same minutes; the split-half turned out to be a real change | AI-proposed, owner-accepted |
| D3 | Where to split S2 | Middle row; at the 171 s gap | Middle row | Matches the interim; the gap split leaves 67 rows (20 positives) on one side | AI-proposed, owner-accepted |
| D4 | How to measure Tier 1 | `/health` + real `/score` API; `/health` only; skip | `/health` + real API | Records errors and latency, and shows the API returns the same scores as `model.pkl` | AI-proposed, owner-accepted |
| D5 | Drift metric | PSI with KS kept as "before"; Wasserstein; KS only | PSI, KS kept as "before" | PSI measures the size of a shift; KS reproduces the supplied Evidently baseline | AI-proposed, owner-accepted. PSI cut-off source found later by the owner (D13) |
| D6 | How thresholds were set | Fixed values in code; calibrate on no-change data | Fixed values in code | Calibrating on one control sample would be circular | AI-proposed, owner-accepted. **Not pre-registered**: values were proposed after the AI assistant's exploratory analysis of the same recording (D14) and then frozen |
| D7 | What decides severity | Prediction drift alone (AI proposal); coefficient-weighted feature PSI; graded by downstream impact | Graded: feature drift only = LOW; output or moderate alert movement = MEDIUM; large alert/workflow disruption = HIGH | Severity follows how far the impact reaches | Structure **owner-modified** (owner wrote the graded version in place of the AI proposal) |
| D7a | HIGH thresholds | 2x / 20 pp / PSI 0.25; PSI only; alert rate only | Alert rate doubles or halves, or shifts >= 20 pp; score PSI alone never HIGH | Alert volume is the operator's workload | Numbers 2x and 20 pp AI-proposed; "PSI alone stays MEDIUM" owner-added |
| D7b | Where "model weakness" goes | Separate fitness flag; fold into HIGH | Separate fitness diagnostic | The weakness is present in every window, so folding it in would make the control HIGH | AI-proposed, owner-accepted |
| D8 | Tier 3 rule | Lower interval end <= 0; upper end <= 0 | Lower end <= 0, as a non-severity label with an advisory follow-up action | See D15 | AI-proposed, owner-accepted; later demoted to a non-severity diagnostic (D15) |
| D9 | MEDIUM threshold | (part of D6) | Alert shift > 5 pp or score PSI >= 0.10 | | 5 pp AI-proposed, owner-accepted |
| D10 | Correcting the interim | Visible correction; silent fix | Visible correction | Graders saw the interim's "false alarm" claim | AI-proposed, owner-accepted |
| D11 | Figures and colors | A+B+C or A+B; B1 red/blue or severity colors only | A+B+C; red = before, blue = after; status colors for severity | One figure per slide; consistent with the team deck | AI-proposed, owner-accepted |
| D12 | Slides | 4, 5 or 6 B3 slides | 4 + backup | The team shares one 8-minute slot | AI-proposed, owner-accepted |
| D13 | PSI cut-off provenance | AI's unsourced "rule of thumb" | 0.10 / 0.25 described as conventional heuristic bands from credit-scorecard practice (Lewis 1994, via Potgieter et al. 2026); 0.10 operational, 0.25 reference line only | The AI's claim had no source | Owner-directed; source supplied by the owner; external convention |
| D14 | Exploratory analysis | Leave it unrecorded; reproduce it in code | `monitoring/b3_exploration.py`, provenance only | The thresholds were proposed after exploration the owner had not run | Owner-directed |
| D15 | Tier 3 statistics | Block bootstrap; keep row bootstrap as exploratory | Row bootstrap kept, labeled a 95% exploratory row-bootstrap interval; Tier 3 removed from severity | Rows are sequentially dependent; the data are limited and effectively in-sample | Owner-directed |
| D16 | PAGE rule | Keep the 1% API-error rule; remove it | Removed. PAGE only when the service cannot produce predictions; Tier 1 status HEALTHY / DEGRADED / UNAVAILABLE / NOT_CHECKED | No production SLO was supplied; the 1% value had been set by the AI without asking the owner | Owner-directed |
| D17 | Sensitivity analysis | None; grid over thresholds and PSI settings | 1,485-combination internal threshold-robustness analysis | Tests whether the S0-S3 conclusion depends on the exact AI-proposed values | Grid owner-specified; script written by the AI assistant; run by the owner |
| D18 | Held-out evaluation | Split the reference again; treat the long file as unseen; state the limitation | State the limitation; methodology frozen | No independent recording exists in the repository | Owner-directed |

## AI supervision (for the brief's required section)

Scope: the interim checkpoint (`B3_interim_checkpoint_v3.md`) already
established the high-level hypothesis that infrastructure health and raw drift
alone were insufficient; the AI assistant did not originate the B3 research
question or hypothesis. AI assistance contributed specific causal explanations
and monitor-design choices. One consequential AI explanation about the
split-half drift was revised and then rejected after measurement (#1).

| # | What the AI proposed | Decision | Why | How it was verified |
|---|---|---|---|---|
| 1 | In order: (a) the causal interpretation that the split-half flags came in part from the 60-second rolling feature window (the interim says "part of this comes from the featurizer itself" and used the split-half as an unchanged control); (b) after a check that removed only the first 60 s of the recording, the AI replaced this with "the message rate roughly triples after a 171 s gap" (went into the README, PDF and code descriptions). | **(b) rejected; (a) partly right** | (b) was wrong: the message rate is about the same on both sides of the gap. Subsequent diagnosis showed the rolling-window mechanism in (a) was real, but the conclusion that the comparison was a false alarm was wrong because the model's alert rate really changes from 13.5% to 78.3%. | `monitoring/b3_diagnosis.py` measured 4.92 vs 4.74 messages/s before and after the gap, and trade_intensity of 167 in the first 60 s after the gap vs 305 afterwards (the rolling window refilling). Explanation (b) removed everywhere; S2 kept as a real change with the corrected cause. |
| 2 | The severity ladder with candidate thresholds: 5 pp for MEDIUM; 2x or 20 pp for HIGH; prediction drift alone deciding HIGH. | **Accepted provisionally, modified, then stress-tested** | The owner replaced "prediction drift decides" with the graded structure (D7) and kept score PSI alone at MEDIUM. The numbers were treated as project-specific, not as standards. | `monitoring/b3_sensitivity.py`: across 1,485 setting combinations the S0-S3 ordering remained unchanged. This is an internal robustness analysis on scenarios derived from the same recording, not independent validation. |
| 3 | Fix the spike threshold tau from the training data rather than per window. | Accepted | Recomputing per window forces about 10% positives everywhere. | Positive rate 7.27% on both reference and drifted windows. |
| 4 | Nonstandard labels "change alerts" and "weak-model alert". | Rejected | Not standard terms. | Replaced with data drift / prediction drift / performance terms. |
| 5 | PSI 0.10 / 0.25 described as a "widely used rule of thumb" / "standard industry cut-offs", with no source. | Rejected as worded; replaced | No source had been checked. | The owner located Potgieter et al. (2026), which traces the values to Lewis (1994) and calls them arbitrary; Feature-engine's source was fetched and quoted. |
| 6 | "Thresholds pre-registered before any scenario was run." | Rejected | The AI assistant had already explored these scenarios before proposing thresholds. | Exploration reproduced in `monitoring/b3_exploration.py`; wording changed to "frozen before the final run". |
| 7 | PAGE when more than 1% of API calls fail. | Rejected | Set by the AI without asking; no SLO supplied. | Replaced by the Tier 1 status design (D16). HEALTHY occurred in the saved S0-S3 runs. DEGRADED and UNAVAILABLE/PAGE were exercised only through constructed status-logic inputs during development; those checks were not saved as a separate test artifact. |
| 8 | Bootstrap intervals presented as formal 95% confidence intervals, and a "confirmed degradation" HIGH rule. | Modified | Independent row resampling on sequential data. | Relabeled as exploratory; Tier 3 removed from severity; numbers unchanged and S0-S3 severities unchanged. |
| 9 | Recommend falling back to the z-score baseline rule. | Rejected | The z-score baseline also scored below prevalence (PR-AUC 0.0949 vs 0.0966, `diagnosis.json`). | Removed from the HIGH action. |
| 10 | Report model fitness separately from change severity. | Accepted | Keeps the control quiet while still reporting the weak model. | S0 is OK while its fitness label is "above-baseline performance not established". |

Suggested pair for the brief: #1 (AI explanation wrong twice, caught by
measurement) and #2 (AI-proposed thresholds accepted provisionally, modified
by the owner, then tested for sensitivity).
