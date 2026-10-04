from pathlib import Path
import csv
import json

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.lib.utils import ImageReader
from reportlab.platypus import (Image, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle)

REPO = str(Path(__file__).resolve().parents[2])  # repository root
RUNS = f"{REPO}/data/b3_runs"
FIG = f"{RUNS}/figures"
OUT = f"{REPO}/B3_Explainer.pdf"

# ---------- every number below is read from the saved outputs ----------
SC = json.load(open(f"{RUNS}/scenarios.json"))
DG = json.load(open(f"{RUNS}/diagnosis.json"))
SE = json.load(open(f"{RUNS}/sensitivity_summary.json"))
EX = json.load(open(f"{RUNS}/exploration.json"))
S = {s["scenario"]: s for s in SC["scenarios"]}
R, TE, DF, EV = DG["reference_window"], DG["training_eval"], DG["data_files"], DG["evidently"]
W = DG["model"]["weights_on_standardized_features"]
TH = SC["thresholds"]


def pct(x, d=1): return f"{100 * x:.{d}f}%"
def f3(x): return f"{x:.3f}"
def alerts(n): return f"{pct(S[n]['tier2']['alert_rate_ref'])} to {pct(S[n]['tier2']['alert_rate_cur'])}"
def lift_iv(n):
    lo, hi = S[n]["tier3"]["lift_row_bootstrap_interval_95_current"]
    return f"[{lo:+.3f}, {hi:+.3f}]"


p95 = [S[n]["tier1"]["latency_ms_p95"] for n in S]
p50 = [S[n]["tier1"]["latency_ms_p50"] for n in S]
errors = sum(S[n]["tier1"]["errors"] for n in S)
maxdiff = max(S[n]["tier1"]["max_abs_score_diff"] for n in S)
containers = ", ".join(f"{k} {v['state']}/{v['health']}" for k, v in SC["containers"].items())
s2_spike = (S["S2"]["tier3"]["reference"]["positive_rate"], S["S2"]["tier3"]["current"]["positive_rate"])
ref_perf = S["S1"]["tier3"]["reference"]
sens_n = SE["valid_combinations"]
sens_rows = {}
for row in csv.DictReader(open(f"{RUNS}/sensitivity.csv")):
    k, v = row["scenario"], float(row["max_feature_psi"])
    sens_rows[k] = (min(v, sens_rows[k][0]), max(v, sens_rows[k][1])) if k in sens_rows else (v, v)
s0_max_feat = sens_rows["S0"][1]
e3 = EX["E3_feature_edits"]["all_labeled_rows"]
# ----------------------------------------------------------------------

ss = getSampleStyleSheet()
INK, ACCENT = colors.HexColor("#1b1b1b"), colors.HexColor("#2a78d6")
LIGHT, GRIDC = colors.HexColor("#eef3fa"), colors.HexColor("#c9c9c4")
H1 = ParagraphStyle("H1", parent=ss["Heading1"], fontSize=17, leading=21, textColor=INK, spaceBefore=6, spaceAfter=8)
H2 = ParagraphStyle("H2", parent=ss["Heading2"], fontSize=13, leading=16, textColor=ACCENT, spaceBefore=10, spaceAfter=4)
H3 = ParagraphStyle("H3", parent=ss["Heading3"], fontSize=11, leading=14, textColor=INK, spaceBefore=6, spaceAfter=2)
P = ParagraphStyle("P", parent=ss["BodyText"], fontSize=10, leading=14, textColor=INK, spaceAfter=5)
B = ParagraphStyle("B", parent=P, leftIndent=14, bulletIndent=4, spaceAfter=2)
CELL = ParagraphStyle("CELL", parent=P, fontSize=8.5, leading=11, spaceAfter=0)
CELLB = ParagraphStyle("CELLB", parent=CELL, fontName="Helvetica-Bold")
NOTE = ParagraphStyle("NOTE", parent=P, fontSize=9, leading=12, textColor=colors.HexColor("#333333"),
                      backColor=LIGHT, borderPadding=6, spaceBefore=4, spaceAfter=8)
CAP = ParagraphStyle("CAP", parent=P, fontSize=8.5, leading=11, textColor=colors.HexColor("#555555"))
TITLE = ParagraphStyle("TITLE", parent=ss["Title"], fontSize=24, leading=29, textColor=INK, alignment=TA_LEFT)
CODE = ParagraphStyle("code", parent=CELL, fontName="Courier", fontSize=8, leftIndent=10, spaceAfter=3)
story = []


def h1(t): story.append(Paragraph(t, H1))
def h2(t): story.append(Paragraph(t, H2))
def h3(t): story.append(Paragraph(t, H3))
def p(t): story.append(Paragraph(t, P))
def note(t): story.append(Paragraph(t, NOTE))
def c(t): return f"<font face='Courier'>{t}</font>"
def bullets(items):
    for it in items:
        story.append(Paragraph(it, B, bulletText="•"))
    story.append(Spacer(1, 4))


def table(rows, widths, header=True):
    data = [[Paragraph(str(x), CELLB if (header and i == 0) else CELL) for x in r] for i, r in enumerate(rows)]
    t = Table(data, colWidths=[w * inch for w in widths], repeatRows=1 if header else 0)
    st = [("GRID", (0, 0), (-1, -1), 0.4, GRIDC), ("VALIGN", (0, 0), (-1, -1), "TOP"),
          ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
          ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]
    if header:
        st.append(("BACKGROUND", (0, 0), (-1, 0), LIGHT))
    t.setStyle(TableStyle(st))
    story.append(t)
    story.append(Spacer(1, 8))


def figure(path, w, caption):
    iw, ih = ImageReader(path).getSize()
    story.append(KeepTogether([Image(path, width=w * inch, height=w * inch * ih / iw), Paragraph(caption, CAP), Spacer(1, 8)]))


LIMITATION = (
    "<b>Independent validation limitation.</b> All supplied market-data artifacts ultimately derive from one "
    "approximately five-minute recording, including the repeated training data and transformed scenario files. The "
    "monitoring design was also informed by exploratory analysis of this recording. Therefore, S0-S3 should be "
    "interpreted as controlled development/evaluation scenarios rather than a held-out test set. The sensitivity "
    "analysis shows that their ordering is robust to the tested monitoring settings, but it does not establish "
    "generalization to unseen data or failure modes. A future evaluation should freeze the monitor and test it once on "
    "an independently recorded replay window.")
SENS_SENTENCE = (
    f"Across {sens_n:,} tested monitoring-setting combinations, the S0-S3 ordering remained unchanged. This suggests "
    "that the observed scenario separation is not dependent on the exact threshold and PSI settings tested. Because "
    "all scenarios ultimately derive from the same underlying recording and informed monitor development, this is an "
    "internal robustness analysis, not independent validation.")
TIER3_MEANING = (
    "On the available short, effectively in-sample dataset, PR-AUC does not establish performance above the "
    "prevalence baseline. This does not prove the model is useless or incapable of performing better on unseen data.")
BOOT_NOTE = (
    "The evaluation rows are sequentially dependent while the bootstrap resamples individual rows independently, so "
    "these intervals are used descriptively rather than as formally calibrated confidence intervals or hypothesis tests.")

# ================= Title =================
story.append(Spacer(1, 1.1 * inch))
story.append(Paragraph("B3: It Is Running, but Is It Still Working?", TITLE))
story.append(Spacer(1, 6))
story.append(Paragraph("Monitoring and drift: explainer for presentation and Q&amp;A preparation", H2))
story.append(Spacer(1, 10))
p("94-879 Fundamentals of Operationalizing AI, Track B &middot; Owner: Vidhi Kothari &middot; Team: Lauren Johnson, "
  f"Anastasiya Joyner, Vidhi Kothari, Stephen Mai &middot; Branch: {c('B3---Vidhi')}")
story.append(Spacer(1, 12))
h2("How to use this document")
bullets([
    "Section 1 is the one-page summary. Section 2 states what kind of evidence this project has, and what it does not have.",
    "Sections 3 to 9 follow the assignment's process: diagnose, hypothesize, intervene, test, evaluate.",
    "Section 10 covers the recommendation and limitations. Sections 11 and 12 give the decision log with provenance and the AI-supervision notes.",
    "Section 13 has likely questions; Section 15 is a glossary; Section 16 lists external references.",
])
note("All empirical results in this document are read directly from the committed outputs in "
     f"{c('data/b3_runs/')} ({c('scenarios.json')}, {c('diagnosis.json')}, {c('sensitivity_summary.json')}, "
     f"{c('exploration.json')}) when the PDF is built. Design parameters, thresholds, tool defaults and implementation "
     "choices are identified separately by their provenance (Section 6.5).")
story.append(PageBreak())

# ================= 1. Summary =================
h1("1. Summary")
p("<b>The assignment's question:</b> requests succeed and the API is available. Is the AI still behaving appropriately? "
  "The task was to design and test monitoring that separates \"is the system up?\" from \"is the AI performing "
  "appropriately?\", decide which changes matter, and say what should follow an alert.")
p("<b>Where the hypothesis came from.</b> The core hypothesis was submitted at the interim checkpoint: infrastructure "
  "health and raw feature-drift tests alone are not enough to tell whether the AI is still working appropriately, and "
  "feature drift should trigger investigation rather than automatic retraining. That hypothesis survived. What changed "
  "was our understanding of the data: the interim treated the split-half drift as a false alarm; later diagnosis showed it "
  "was a real model-behavior change caused by the rolling 60 s trade-intensity window refilling after a gap in the "
  "recording. We revised the experiment rather than forcing the original explanation to fit (Sections 4.3 and 5).")
p("<b>Diagnosis.</b>")
bullets([
    f"Serving health is good: containers {containers}; /health reports the model loaded; {errors} API errors across all "
    f"scenarios; p95 latency {min(p95):.1f}-{max(p95):.1f} ms in the saved run.",
    f"Model performance: on the reference window, PR-AUC is {f3(ref_perf['pr_auc'])} against a prevalence baseline of "
    f"{f3(ref_perf['positive_rate'])}. Above-baseline performance is not established on the available data.",
    f"The model's score correlates {R['corr_score_vs_trade_intensity']:.2f} with <b>trade intensity</b> (messages in the "
    f"last 60 s) and {R['corr_score_vs_label']:.3f} with the spike label. Trade intensity has the model's largest weight "
    f"({W['trade_intensity']:+.3f}) but correlates {R['corr_trade_intensity_vs_label']:.3f} with the label.",
    "The supplied drift tool (Evidently, KS test) reports the harmless spread change and the alert-volume change with the "
    "same kind of verdict (p close to 0) and no indication of which matters.",
])
p(f"<b>Intervention.</b> A tiered monitor in one script ({c('monitoring/b3_monitor.py')}): Tier 1 serving status; "
  "Tier 2 drift graded by its effect on the model's output and alert volume; a drift severity (OK / LOW / MEDIUM / HIGH, "
  "with PAGE for complete serving failure); and Tier 3, a separate retrospective model-performance diagnostic.")
p("<b>Testing.</b> Four <b>controlled development/evaluation scenarios</b>, S0-S3, plus an internal threshold-robustness "
  "analysis.")
table([
    ["Scenario", "How it is built", "Before (Evidently-style KS)", "After (monitor)", "Matched intended operational interpretation?"],
    ["S0", "Interleaved odd vs even rows (no change)", f"{S['S0']['tier2']['before_ks_features_flagged']}/4 flagged", S["S0"]["severity"], "Yes"],
    ["S1", "Drifted file (spread wider)", f"{S['S1']['tier2']['before_ks_features_flagged']}/4 flagged", S["S1"]["severity"], "Yes"],
    ["S2", "Split-half of reference", f"{S['S2']['tier2']['before_ks_features_flagged']}/4 flagged", f"{S['S2']['severity']} (alerts {alerts('S2')})", "Yes"],
    ["S3", "Message loss, replayed through Kafka", f"{S['S3']['tier2']['before_ks_features_flagged']}/4 flagged", f"{S['S3']['severity']} (alerts {alerts('S3')})", "Yes"],
], [0.75, 1.65, 1.3, 1.5, 1.4])
p("<b>Conclusion (bounded to this experiment).</b> Infrastructure health alone does not establish appropriate model "
  "behavior. In these controlled scenarios, feature drift by itself could be operationally harmless, while large changes "
  "in model outputs and alert volume identified consequential behavior changes. The monitor therefore separates serving "
  "health, input/output drift, operational alert impact and retrospective model-performance evidence rather than "
  "treating all statistical drift as equivalent. " + SENS_SENTENCE)
story.append(PageBreak())

# ================= 2. Methodological status =================
h1("2. Methodological status: what kind of evidence this is")
p("The evidence hierarchy for B3:")
table([
    ["Level", "What it is", "What it can show"],
    ["1. S0-S3", "Controlled development/evaluation scenarios", "How the frozen monitor behaves under four known conditions"],
    ["2. Sensitivity analysis", "Internal threshold-robustness analysis", "Whether the S0-S3 conclusions depend on the exact threshold and PSI settings tested"],
    ["3. Held-out evaluation", "Not available", "Independent generalization remains untested: no genuinely new market recording exists in the supplied repository"],
    ["4. Remaining uncertainty", "", "Whether the frozen monitor behaves appropriately on unseen market windows and different failure modes"],
], [1.4, 2.2, 3.0])
note(LIMITATION)
p("The final monitor configuration was frozen before the final robustness analysis, but some design choices were informed "
  "by earlier exploratory analysis. We therefore do not describe the experiment as preregistered.")
story.append(PageBreak())

# ================= 3. Background =================
h1("3. Background: the system and the data")
h2("3.1 The pipeline")
p("Recorded market messages are replayed into <b>Kafka</b>. The <b>featurizer</b> computes four features per message and "
  "saves them to a <b>parquet</b> file. A Flask <b>API</b> (the scorer) serves model scores at POST /score, with a health "
  "check at GET /health. MLflow stores training runs.")
h2("3.2 The model and the label")
bullets([
    f"A <b>logistic regression</b> ({c('models/train_baseline.py')}, class_weight = {DG['model']['class_weight']}) outputs a "
    "probability that a volatility spike is coming.",
    f"The scorer raises a spike alert when that probability is {TH['alert_threshold']} or more (supplied, {c('score_service.py')}).",
    f"The <b>label</b> is known only afterwards: the standard deviation of returns over the next 20 messages, called a spike "
    f"if it is at or above the training file's 90th percentile (<b>tau</b> = {SC['tau']:.3e}). Supplied: {c('label_spikes')} "
    "defaults. Because the label needs the next 20 messages, labels always arrive late.",
])
p("Model weights on standardized features:")
table([["Feature", "Plain meaning", "Weight"]] + [
    [f, m, f"{W[f]:+.3f}"] for f, m in [
        ("trade_intensity", "Messages in the last 60 seconds; low until that 60 s window has filled"),
        ("order_book_imbalance", "Whether more quantity waits at the best buy or best sell price (-1 to +1)"),
        ("midprice_returns", "Percent change in the middle price since the previous message"),
        ("spread_normalized", "Gap between best buy and best sell price, divided by price")]],
    [1.6, 4.0, 1.0])
h2("3.3 The data: one recording")
table([
    ["File", "What it is", "Used for"],
    ["sample_ticks.jsonl", f"The only genuine recording: about five minutes, {DF['reference_messages']} messages, {R['rows']} ticker rows", "Reference side of S0-S3; diagnosis; exploration; sensitivity"],
    ["sample_ticks_drifted.jsonl", f"Same messages; only {', '.join(DF['drifted_fields_changed'])} changed (median spread ratio {DF['spread_median_ratio_drifted_over_reference']:.2f})", "S1"],
    ["sample_ticks_long.jsonl", f"The reference repeated {DF['long_over_reference']:.0f} times with rewritten timestamps (identical apart from timestamps: {DF['long_is_reference_repeated_ignoring_timestamps']})", "Training; tau"],
    ["sample_ticks_msgloss.jsonl", f"Built by {c('scripts/b3_inject_faults.py')}: every other ticker message removed", "S3"],
], [1.7, 3.3, 1.6])
note("Because the training file repeats the reference recording, every model number on the reference window is effectively "
     "in-sample.")
story.append(PageBreak())

# ================= 4. Diagnosis =================
h1("4. Diagnosis: symptom and cause")
h2("4.1 Symptom: healthy service; above-baseline performance not established")
table([
    ["Check", "Result (saved run)", "Meaning"],
    ["Containers", containers, "Infrastructure is up"],
    ["Tier 1 status", ", ".join(f"{n} {S[n]['tier1']['system_status']}" for n in S), "Every /score request produced a prediction"],
    ["Latency", f"p50 {min(p50):.1f}-{max(p50):.1f} ms, p95 {min(p95):.1f}-{max(p95):.1f} ms", "Varies between runs; quoted from the saved run"],
    ["API vs model.pkl", f"largest score difference {maxdiff:.1e}", "The monitor checks the deployed model"],
    ["Training test split", f"PR-AUC {TE['pr_auc_logistic_regression']:.4f}; z-score rule {TE['pr_auc_zscore_baseline']:.4f}; prevalence {TE['test_prevalence']:.4f}", f"PR-AUC {TE['pr_auc_logistic_regression']:.4f} vs prevalence {TE['test_prevalence']:.4f} on the saved training-code split; absolute lift {TE['pr_auc_logistic_regression'] - TE['test_prevalence']:+.4f}"],
    ["Reference window", f"PR-AUC {f3(ref_perf['pr_auc'])} vs prevalence {f3(ref_perf['positive_rate'])}; {R['positives']} positives in {R['labeled_rows']} labeled rows", "Above-baseline performance not established"],
    ["Alert rate vs spike rate", f"{pct(R['alert_rate'])} of rows alerted; {pct(R['positive_rate'])} are spikes", f"Precision at 0.5: {pct(ref_perf['precision_at_threshold'])} of alerts are spikes"],
], [1.5, 3.0, 2.1])
h2("4.2 Cause: alerts follow trade intensity")
mt = R["minute_table"]
table([["Minute", "Rows", "Mean trade intensity", "Model alert rate", "Actual spike rate"]] +
      [[str(r["minute"]), str(r["rows"]), f"{r['mean_trade_intensity']:.0f}", pct(r["alert_rate"], 0),
        pct(r["spike_rate"], 0)] for r in mt], [1.0, 0.8, 1.6, 1.5, 1.5])
bullets([
    f"The recording has {R['rows_before_gap']} rows ({R['seconds_before_gap']:.1f} s), then {R['gap_seconds']:.0f} s with no "
    f"rows, then {R['rows'] - R['rows_before_gap']} rows.",
    f"Trade intensity counts messages in the last 60 s, so it stays low until the window fills. It never exceeds "
    f"{R['max_trade_intensity_before_gap']} before the gap; after the gap it averages {R['mean_trade_intensity_first_60s_after_gap']:.0f} "
    f"in the first 60 s and {R['mean_trade_intensity_after_first_60s_after_gap']:.0f} afterwards.",
    f"The message rate itself is about the same on both sides of the gap: {R['messages_per_second_before_gap']:.2f} vs "
    f"{R['messages_per_second_after_gap']:.2f} messages per second.",
    f"Score vs trade intensity r = {R['corr_score_vs_trade_intensity']:.2f}; score vs label r = {R['corr_score_vs_label']:.3f}.",
    f"Sources: {c('diagnosis.json')} ({c('reference_window')}), {c('minute_table.csv')}.",
])
figure(f"{FIG}/fig_a_diagnosis.png", 6.6, "Figure A. Top: mean trade intensity per 30 s; the shaded band is the period with no "
       "rows. Bottom: model alert rate (blue) vs actual spike rate (orange).")
h2("4.3 Correction to the interim: the split-half comparison")
p("<b>What the interim said.</b> The interim used the split-half comparison of the reference file (first half vs second "
  "half) as an \"unchanged\" negative control. Evidently flagged 3 of 4 features, and the interim treated those flags as a "
  "false alarm, attributing them in part to the featurizer's 60 s trade-intensity window filling over time.")
p("<b>What later diagnosis showed.</b> The two halves genuinely differ. The recording has a "
  f"{R['gap_seconds']:.0f} s gap, and trade intensity is a rolling 60 s count that refills after it. Splitting at the "
  f"middle row puts the {R['first_half_rows_before_gap']} pre-gap rows and {R['first_half_rows_in_refill']} refill rows "
  f"into the first half, so mean trade intensity is {R['first_half_mean_trade_intensity']:.0f} vs "
  f"{R['second_half_mean_trade_intensity']:.0f}, and the model's alert rate goes from {alerts('S2')} while the actual "
  f"spike rate is {pct(s2_spike[0])} and {pct(s2_spike[1])}. The message rate is about the same on both sides of the gap, "
  "so the cause is the rolling-window refill mechanism, not a change in message rate.")
p("<b>How the experiment was revised.</b> The refill mechanism suggested at the interim was right; \"false alarm\" was "
  "not. The split-half comparison became S2, a real consequential change, and the no-change control was replaced with the "
  "interleaved odd/even split (S0), whose two halves cover the same minutes.")
story.append(PageBreak())

# ================= 5. Hypothesis =================
h1("5. Hypothesis and test setup")
h2("5.1 The interim hypothesis")
p(f"Submitted in the interim checkpoint ({c('B3_interim_checkpoint_v3.md')}): a monitoring approach that separates (1) "
  "system health, (2) data and prediction drift, and (3) labeled model performance will do a better job of identifying "
  "meaningful AI failures than infrastructure checks and per-feature drift tests alone. Feature-level drift should "
  "trigger investigation rather than automatic retraining unless it also affects model outputs or performance.")
p("The final monitor is a refinement and operationalization of this hypothesis, not a replacement of it.")
h2("5.2 What stayed the same from interim to final")
bullets([
    "Healthy infrastructure does not imply appropriate AI behavior.",
    "Raw feature drift alone is not enough to decide operational severity.",
    "Model-output behavior and labeled model performance are separate monitoring layers.",
    "Feature drift should trigger investigation, not automatic retraining, unless downstream model behavior or "
    "performance is affected.",
])
h2("5.3 What changed after the interim")
table([
    ["Interim", "Final", "Why"],
    ["Split-half comparison used as the \"unchanged\" control; its 3/4 feature flags treated as a false alarm",
     "Split-half is S2, a real consequential change; the no-change control is the interleaved odd/even split (S0)",
     "Diagnosis showed the halves differ because of the gap and the rolling-window refill (Section 4.3)"],
    ["Wording such as \"the model is not useful\"",
     "\"Above-baseline performance is not established on the available data\"",
     "The data are short and effectively in-sample, so they cannot show the model is useless"],
    ["A weak-model performance alert was expected because PR-AUC was near prevalence",
     "Tier 3 is a separate retrospective diagnostic with an advisory follow-up action; it never sets drift severity or PAGE status",
     "The weakness is present in every window, including the control; see D7b, D15"],
    ["General drift alerts and an operational decision of no action / investigate / escalate",
     "Tier 1 serving status; feature drift; score/output drift; alert-volume impact; retrospective labeled performance; "
     "severity OK / LOW / MEDIUM / HIGH, with PAGE for serving unavailability",
     "Makes each layer and its action explicit"],
], [2.1, 2.5, 2.0])
h2("5.4 The hypothesis as tested in the final run")
p("Infrastructure health checks and per-feature drift tests alone do not tell an operator whether the "
  "AI is still behaving appropriately or whether a change matters. A monitor that (1) reports serving status, (2) grades "
  "drift by its effect on the model's output and alert volume, and (3) reports retrospective model performance separately "
  "will separate no change, harmless change and consequential change in the controlled scenarios.")
h2("What would count against it")
bullets([
    "The monitor raises a drift severity (LOW or higher) on the no-change control S0.",
    "Its ordering does not match the intended operational interpretation, for example S1 HIGH or S3 OK.",
    "The spread change in S1 materially changes model outputs.",
])
h2("How the test is set up")
bullets([
    "<b>Intended operational interpretations:</b> S0 and S3 were built for this project (an interleaved split and an "
    "injected message-loss fault); S1 uses the supplied drifted file; S2's interpretation was revised after diagnosis "
    "(Section 4.3). Together they give a reference ordering S0=OK, S1=LOW, S2=HIGH, S3=HIGH, set before the final run "
    "and sensitivity analysis. This is the intended operational ordering, not ground truth, and it was not defined "
    "independently of the exploratory analysis.",
    "<b>Same conditions:</b> the same model file, label definition (fixed tau), reference window and pipeline for every scenario.",
    "<b>Before and after on identical inputs:</b> the Evidently-style KS view and the monitor are computed in the same run on the same rows.",
    "<b>Frozen configuration:</b> the final monitor configuration was frozen before the final robustness analysis, but some "
    "design choices were informed by earlier exploratory analysis, so the experiment is not described as preregistered.",
])
story.append(PageBreak())

# ================= 6. Monitor design =================
h1("6. The intervention: tiered monitor")
p(f"All logic is in {c('monitoring/b3_monitor.py')}. {c('scripts/b3_inject_faults.py')} builds S3; "
  f"{c('monitoring/b3_figures.py')} draws the figures.")
h2("6.1 Tier 1: system status (separate from drift severity)")
table([
    ["Status", "Meaning", "Operational behavior"],
    ["HEALTHY", "/health ok, model loaded, every attempted /score request produced a prediction", "Proceed"],
    ["DEGRADED", "/health ok and at least one prediction produced, but one or more /score requests failed", "Reported as a serving/reliability issue; not a drift severity; no paging cutoff"],
    ["UNAVAILABLE", "/health fails, the model is not loaded, or no /score request produced a prediction", "PAGE"],
    ["NOT_CHECKED", "Tier 1 skipped (--no_api)", "Tier 1 was not evaluated; this does not mean healthy"],
], [1.1, 3.2, 2.3])
p("API error count, error rate, p50/p95 latency, container status and API-vs-model.pkl score agreement are recorded every "
  "run. No partial-error paging threshold is imposed because no production SLO or validated cutoff was supplied.")
h2("6.2 Tier 2: drift, graded by effect on the model")
bullets([
    "<b>Feature PSI</b>: how far each input's distribution moved (reference deciles as bins).",
    "<b>Score PSI</b>: the same measure on the model's output. Because the score is produced by the fitted model from all "
    "features together, this captures whether input changes propagate into model behavior.",
    "<b>Alert-rate shift and ratio</b>: change in the share of rows the model alerts on (operator workload).",
    "<b>KS view (\"before\")</b>: per-feature KS p-value flagged below 0.05, dataset drift when 50% or more features are "
    "flagged (Evidently defaults). Evidently itself, run on the same pairs, gives the same counts "
    f"({', '.join(f'{k} {int(v[chr(100) + chr(114) + chr(105) + chr(102) + chr(116) + chr(101) + chr(100) + chr(95) + chr(99) + chr(111) + chr(117) + chr(110) + chr(116)])}/4' for k, v in EV.items())}).",
])
p("<b>Why not the KS p-value alone?</b> The KS p-value indicates evidence of a distributional difference under its "
  "assumptions but does not measure operational importance. SciPy's two-sample KS test assumes independent samples. Our "
  "streaming rows are serially dependent, so that assumption is not fully satisfied; we therefore do not treat the nominal "
  "p-values as calibrated measures of operational consequence. We retain KS as the baseline/before comparison and use effect size and downstream model "
  "behavior to assess consequence.")
h2("6.3 Drift severity (Tier 1 and Tier 2 only)")
table([
    ["Level", "Triggered when (first matching rule wins)", "Action"],
    ["PAGE", "Tier 1 UNAVAILABLE", "Page on-call; restore the service. Model checks are not trustworthy until it is healthy."],
    ["HIGH", f"Alert rate doubles or halves (ratio {TH['alert_ratio_high']:.0f}x), or shifts by {100 * TH['alert_shift_high']:.0f} percentage points or more", "Escalate now to model owner and pipeline on-call; consider pausing alerts. Labeled evidence is needed to establish a performance problem; root-cause analysis determines whether retraining is appropriate"],
    ["MEDIUM", f"Score PSI {TH['psi_moderate']:.2f} or more, or alert-rate shift above {100 * TH['alert_shift_medium']:.0f} percentage points", "Investigate same day; notify model owner; no retraining unless labeled evidence establishes a performance problem and root-cause analysis supports retraining"],
    ["LOW", f"Any feature PSI {TH['psi_moderate']:.2f} or more, with no MEDIUM/HIGH condition", "Data-quality ticket: real change or feed bug? No model action"],
    ["OK", "None of the above", "No action"],
], [0.75, 2.9, 2.95])
p("Tier 3 does not independently make a scenario HIGH or affect any severity.")
h2("6.4 Tier 3: retrospective model-performance diagnostic")
p("Once labels exist, Tier 3 reports PR-AUC, the prevalence baseline, lift (PR-AUC minus prevalence) and a 95% exploratory "
  f"row-bootstrap interval for lift ({TH['n_boot']} resamples, seed {TH['seed']}). " + BOOT_NOTE + " Tier 3 is a "
  "separate retrospective diagnostic with an advisory follow-up action; it never sets drift severity or PAGE status. Display label when the interval's lower end is 0 or below: "
  "<b>ABOVE-BASELINE PERFORMANCE NOT ESTABLISHED ON AVAILABLE DATA</b>. " + TIER3_MEANING)
h2("6.5 Where each setting comes from")
table([
    ["Setting", "Value", "Provenance"],
    ["Alert threshold", f"{TH['alert_threshold']}", "Supplied code (score_service.py)"],
    ["Spike label", "90th percentile, 20-row horizon", "Supplied code (label_spikes defaults)"],
    ["Operational PSI threshold", f"{TH['psi_moderate']:.2f}", "Externally sourced heuristic: conventional PSI band originating in credit-scorecard practice (Lewis 1994, as traced by Potgieter et al. 2026); not a universal statistically calibrated threshold"],
    ["PSI reference band", f"{TH['psi_significant']:.2f}", "Same source; descriptive/figure line only; does not independently determine severity"],
    ["PSI bins", "10", "Matches Feature-engine's current default"],
    ["PSI empty-bin handling", "0.0001", "Our monitor uses the same numeric constant, 0.0001, but a different implementation: Feature-engine replaces/adds the constant for empty or zero bins, whereas our psi() floors bin proportions at that minimum."],
    ["MEDIUM alert shift", f"{100 * TH['alert_shift_medium']:.0f} percentage points (pp)", "AI-proposed project-specific threshold, accepted by owner"],
    ["HIGH alert shift / ratio", f"{100 * TH['alert_shift_high']:.0f} percentage points (pp) / {TH['alert_ratio_high']:.0f}x", "AI-proposed project-specific thresholds, accepted by owner"],
    ["KS p-value; dataset-drift share", f"{TH['ks_alpha']}; {pct(TH['dataset_drift_share'], 0)}", "Evidently defaults, used for the baseline comparison"],
    ["Bootstrap resamples; seed", f"{TH['n_boot']}; {TH['seed']}", "AI-selected exploratory implementation choices"],
], [1.6, 1.3, 3.7])
story.append(PageBreak())

# ================= 7. Scenarios =================
h1("7. Controlled development/evaluation scenarios")
table([
    ["#", "How it is built", "Why it is included", "Intended operational interpretation"],
    ["S0", "Odd vs even rows of the reference", "Negative control: both halves cover the same minutes", "OK"],
    ["S1", "Reference vs supplied drifted file", "Large input change in a feature with a small model weight", "LOW"],
    ["S2", "First vs second half of the reference", "Real change in trade intensity after the recording gap (Section 4.3)", "HIGH"],
    ["S3", "Reference vs message-loss file", "Constructed upstream fault, replayed through the real pipeline", "HIGH"],
], [0.4, 2.0, 3.0, 1.2])
p("<b>S3 is pipeline-faithful:</b> raw-message loss (every other ticker message removed), replayed through Kafka, features "
  "recomputed by the real featurizer, then evaluated by the monitor with the deployed model's scores. It is a constructed "
  "fault used to check whether the monitor reacts to a known change; it is not taken from a real incident.")
h2("Exploratory provenance (not evaluation evidence)")
p(f"{c('monitoring/b3_exploration.py')} reproduces exploratory checks originally run by the AI assistant before parts of "
  "the design were proposed. Its outputs are provenance only. E3 in that script is a <b>feature-space sensitivity probe, "
  "not a pipeline experiment</b>: feature values were edited directly (for example trade intensity x 0.5, alert rate "
  f"{pct(e3['reference']['alert_rate'])} to {pct(e3['trade_intensity_x_0.5']['alert_rate'])} on labeled rows) without "
  "Kafka or the featurizer. It suggested that the model is sensitive to trade intensity; S3 is the pipeline-faithful "
  "follow-up. E1-E5 values are not used as S0-S3 evidence.")
story.append(PageBreak())

# ================= 8. Results =================
h1("8. Results on the controlled scenarios")
p(f"Source: {c('scenarios.json')} (saved run).")
rows = [["", "S0", "S1", "S2", "S3"],
        ["Rows (reference / current)"] + [f"{S[n]['rows_ref']} / {S[n]['rows_cur']}" for n in S],
        ["Before: KS features flagged"] + [f"{S[n]['tier2']['before_ks_features_flagged']}/4" for n in S],
        ["Before: dataset drift (50% or more)"] + ["Yes" if S[n]["tier2"]["before_dataset_drift"] else "No" for n in S],
        ["Largest feature PSI"] + [f3(S[n]["tier2"]["max_feature_psi"]) for n in S],
        ["Score PSI"] + [f3(S[n]["tier2"]["score_psi"]) for n in S],
        ["Alert rate ref to cur"] + [alerts(n) for n in S],
        ["Tier 1 status"] + [S[n]["tier1"]["system_status"] for n in S],
        ["Severity"] + [S[n]["severity"] for n in S],
        ["Lift, 95% exploratory row-bootstrap interval"] + [lift_iv(n) for n in S],
        ["Tier 3 label"] + ["Above-baseline performance not established" if S[n]["model_fitness_code"] == "above_baseline_performance_not_established" else S[n]["model_fitness"] for n in S]]
table(rows, [1.9, 1.15, 1.15, 1.15, 1.25])
figure(f"{FIG}/fig_b_validation.png", 6.6, "Figure B. Left: features flagged by the KS view. Right: model score PSI (log "
       "scale) with the 0.10 operational threshold and 0.25 reference line; bars colored and labeled by severity.")
h2("Reading each scenario")
bullets([
    f"<b>S0:</b> largest feature PSI {f3(S['S0']['tier2']['max_feature_psi'])}, alert rate {alerts('S0')}. OK; no drift severity on the control.",
    f"<b>S1:</b> spread PSI {f3(S['S1']['tier2']['features']['spread_normalized']['psi'])} but score PSI {f3(S['S1']['tier2']['score_psi'])} "
    f"and alert rate {alerts('S1')}. LOW: a data-quality ticket, no retrain. The KS view flags spread with no indication of consequence.",
    f"<b>S2:</b> score PSI {f3(S['S2']['tier2']['score_psi'])}, alert rate {alerts('S2')}, actual spike rate {pct(s2_spike[0])} and {pct(s2_spike[1])}. HIGH.",
    f"<b>S3:</b> alert rate {alerts('S3')} while Tier 1 is {S['S3']['tier1']['system_status']}. HIGH. The KS view flags "
    f"{S['S3']['tier2']['before_ks_features_flagged']} of 4 features, exactly at the 50% dataset-drift line, and says nothing about the alert change.",
    "<b>Tier 3:</b> every exploratory interval includes 0; above-baseline performance is not established on the available "
    "data in any window. S3's labels are computed from the reduced message stream.",
])
figure(f"{FIG}/fig_c_fitness.png", 6.2, "Figure C. PR-AUC lift over the prevalence baseline with the 95% exploratory "
       "row-bootstrap interval for each scenario's current window. Descriptive only.")
story.append(PageBreak())

# ================= 9. Sensitivity =================
h1("9. Internal threshold-robustness analysis")
p(f"Source: {c('monitoring/b3_sensitivity.py')}, {c('sensitivity_summary.json')}. The existing classify() rules were rerun "
  "with alternative settings: operational PSI threshold {0.05, 0.10, 0.15, 0.25, 0.50}; MEDIUM alert shift {2, 5, 10} pp; "
  "HIGH alert shift {10, 20, 30, 40} pp; HIGH ratio {1.5, 2, 3}; PSI bins {5, 10, 20}; PSI floor {1e-6, 1e-4, 1e-3}. "
  f"Combinations with MEDIUM shift at or above HIGH shift were excluded, leaving {sens_n:,}. PSI was recomputed for every "
  "bins/floor pair. Tier 1 and Tier 3 were not varied.")
table([["Scenario", "Matched reference ordering", "Severity counts", "Largest feature PSI range"]] +
      [[n, f"{SE['per_scenario'][n]['matches']}/{sens_n}", ", ".join(f"{k} {v}" for k, v in SE["per_scenario"][n]["severity_counts"].items()),
        f"{sens_rows[n][0]:.4f}-{sens_rows[n][1]:.4f}"] for n in SE["per_scenario"]], [0.9, 1.8, 1.8, 2.1])
note(SENS_SENTENCE)
p(f"<b>Boundary observation:</b> S0 was closest to a classification boundary. Its largest feature PSI reached approximately "
  f"{s0_max_feat:.3f} under the tested bin/floor settings, versus the lowest tested operational PSI threshold of 0.05. "
  "Lower PSI thresholds than those tested would not necessarily preserve S0 = OK.")
story.append(PageBreak())

# ================= 10. Evaluation =================
h1("10. Evaluation, recommendation and limitations")
h2("10.1 Against the hypothesis")
table([
    ["Check", "Result", "Outcome"],
    ["Drift severity on the control S0?", S["S0"]["severity"], "Matched intended interpretation"],
    ["Ordering matches intended interpretation?", " / ".join(S[n]["severity"] for n in S), "Matched in the saved run and in all tested settings"],
    ["Does the S1 spread change move the model?", f"score PSI {f3(S['S1']['tier2']['score_psi'])}, alert rate {alerts('S1')}", "No material output change"],
], [2.2, 2.3, 2.1])
p("Within these four controlled scenarios, the monitor matched the intended operational ordering: the no-change control "
  "stayed quiet, harmless input drift stayed low-severity, and large output/workload changes escalated. The KS view's "
  "dataset-level verdicts (No / No / Yes / Yes) point the same way but carry no severity or action, report the harmless "
  "spread change with p close to 0, catch S3 exactly at its 50% line, and say nothing about the model's outputs. Neither "
  "drift view nor serving health shows model performance; only Tier 3 does, retrospectively.")
h2("10.2 Tradeoffs")
p("These are expected tradeoffs reasoned from the design; they were not measured in this project.")
bullets([
    "<b>Fewer drift alarms vs slower detection:</b> grading by model impact may also quiet small real shifts; LOW tickets are intended to keep them visible.",
    "<b>Tier 3 lags:</b> labels need the next 20 messages, so Tier 2 would be the earlier signal.",
    "<b>Settings may need upkeep:</b> the alert-rate thresholds are project-specific and would likely need revisiting after any retrain.",
    "<b>Partial serving failures:</b> DEGRADED is reported but has no paging cutoff until a real SLO exists.",
    "<b>Operating cost:</b> Tier 1 sends real requests to the API; a busy production service would likely need to sample rows.",
])
h2("10.3 Recommendation")
bullets([
    "Adopt the tiered monitor (Tier 1 status, drift severity ladder, separate Tier 3 diagnostic) only as a provisional, limited deployment until it has been tested once on an independently recorded replay window.",
    "Do not retrain because of the spread drift (S1); route it to a data-quality check.",
    "<b>Escalate the model for re-evaluation.</b> Before changing the alert threshold, retraining, or replacing the model, "
    "evaluate candidate alternatives on genuinely out-of-sample labeled data.",
    "Treat breaks and losses in the message stream as an AI risk: in S2 and S3 trade intensity changed, and so did the alerts.",
])
h2("10.4 Limitations")
note(LIMITATION)
bullets([
    "PAGE (UNAVAILABLE) and DEGRADED never occurred in the saved runs. They were checked only by calling the status logic with constructed inputs during development (not saved as a test file), not by stopping or degrading the live scorer.",
    f"Training PR-AUC values come from re-evaluating the saved model with the training code's own split ({c('diagnosis.json')}).",
    "S3's labels are computed from the reduced message stream.",
])
h2("10.5 Remaining uncertainty")
p("Whether the frozen monitor behaves appropriately on unseen market windows and different failure modes, and whether the "
  "model performs above the prevalence baseline on independent data.")
h2("10.6 Team integration points")
p("These are integration points with teammates' challenges, as described in the team's materials; B3 did not independently "
  "verify B1 or B2 work. B2 concerns /health reporting model_loaded; B3 adds that a loaded model is not necessarily "
  "behaving appropriately. B1 concerns keeping up with the feed; in B3's scenarios, breaks or losses in the message stream "
  "changed trade intensity, which drives the model's predictions.")
story.append(PageBreak())

# ================= 11. Decision log =================
h1("11. Decision log with provenance")
p(f"Full version: {c('B3_AI_DECISIONS.md')}.")
table([
    ["#", "Decision", "Chosen", "Provenance"],
    ["D1", "Scenarios", "S0-S3, S3 replayed through Kafka", "Options AI-proposed; owner chose against the AI recommendation (S0-S2 only)"],
    ["D2", "No-change control", "Interleaved split", "AI-proposed, owner-accepted"],
    ["D3", "Where to split S2", "Middle row", "AI-proposed, owner-accepted"],
    ["D4", "Tier 1 measurement", "/health + real /score API", "AI-proposed, owner-accepted"],
    ["D5", "Drift metric", "PSI, with KS as the before view", "AI-proposed, owner-accepted"],
    ["D6", "Threshold setting", "Fixed values in code; not preregistered", "AI-proposed, owner-accepted"],
    ["D7", "Severity structure", "Graded by downstream impact", "Owner-modified (owner wrote the graded version)"],
    ["D7a", "HIGH thresholds", "2x / 20 pp; score PSI alone never HIGH", "Numbers AI-proposed; PSI rule owner-added"],
    ["D7b", "Model weakness", "Separate Tier 3 diagnostic", "AI-proposed, owner-accepted"],
    ["D8", "Tier 3 label rule", "Interval lower end 0 or below", "AI-proposed, owner-accepted; later non-severity (D15)"],
    ["D9", "MEDIUM threshold", "5 pp or score PSI 0.10", "5 pp AI-proposed, owner-accepted"],
    ["D10-D12", "Interim correction; figures; slides", "Visible correction; A+B+C; 4 slides + backup", "AI-proposed, owner-accepted"],
    ["D13", "PSI provenance", "Lewis (1994) via Potgieter et al. (2026); 0.10 operational, 0.25 reference", "Owner-directed"],
    ["D14", "Exploration in code", "b3_exploration.py, provenance only", "Owner-directed"],
    ["D15", "Tier 3 statistics", "Exploratory row-bootstrap interval; no severity role", "Owner-directed"],
    ["D16", "PAGE / Tier 1 status", "No percentage cutoff; HEALTHY / DEGRADED / UNAVAILABLE / NOT_CHECKED", "Owner-directed"],
    ["D17", "Sensitivity analysis", f"{sens_n:,} combinations", "Grid owner-specified; script by AI; run by owner"],
    ["D18", "Held-out data", "None available; limitation stated; methodology frozen", "Owner-directed"],
], [0.6, 1.4, 2.5, 2.1])
story.append(PageBreak())

# ================= 12. AI supervision =================
h1("12. AI supervision")
p("<b>Scope of AI contributions.</b> The interim checkpoint already established the high-level hypothesis that infrastructure "
  "health and raw drift alone were insufficient (Section 5.1); the AI assistant did not originate the B3 research question "
  "or hypothesis. AI assistance contributed specific causal explanations and monitor-design choices (thresholds, PSI, the "
  "PAGE rule, bootstrap interpretation, the sensitivity-analysis script and other details), each accepted, modified or "
  "rejected below. One consequential AI explanation about the split-half drift was revised and then rejected after measurement.")
h3("1. Rejected after measurement: the AI's explanation of the split-half drift")
p("<b>Proposed, in order:</b> (a) AI assistance contributed the causal interpretation that the split-half flags came in part from the "
  "60-second rolling feature window (the interim states that \"part of this comes from the featurizer itself\" and treated the "
  "split-half as an unchanged control). Subsequent diagnosis showed the rolling-window mechanism was real, but the "
  "conclusion that the comparison was a false alarm was wrong; (b) after a check that removed only the first 60 s of the recording, \"the message rate roughly triples after "
  "a 171 s gap\" (in an earlier README, PDF and code descriptions). <b>Checked:</b> b3_diagnosis.py measured "
  f"{R['messages_per_second_before_gap']:.2f} vs {R['messages_per_second_after_gap']:.2f} messages per second on either side "
  f"of the gap, so (b) was wrong; trade intensity of {R['mean_trade_intensity_first_60s_after_gap']:.0f} in the first 60 s "
  f"after the gap vs {R['mean_trade_intensity_after_first_60s_after_gap']:.0f} afterwards shows the rolling window refilling, so the "
  f"mechanism in (a) was right but its conclusion was not: the alert rate really changes from {alerts('S2')}. "
  "<b>Outcome:</b> (b) removed everywhere; S2 kept as a real change with the corrected cause.")
h3("2. Accepted provisionally, then stress-tested: the operational thresholds")
p("<b>Proposed:</b> candidate alert-rate thresholds (5 pp for MEDIUM; 2x or 20 pp for HIGH) and prediction drift alone "
  "deciding HIGH. <b>Response:</b> the owner replaced \"prediction drift decides\" with the graded structure and kept score "
  "PSI alone at MEDIUM; the numbers were accepted as project-specific settings, not standards. <b>Checked:</b> the frozen "
  f"monitor was rerun across {sens_n:,} setting combinations and the S0-S3 ordering remained unchanged. This tests "
  "dependence on parameter choices; it does not independently validate monitor generalization.")
h3("Other AI recommendations")
bullets([
    "Fix tau from training data: accepted (positive rate equal across reference and drifted windows).",
    "Unsourced \"rule of thumb\" wording for PSI 0.10/0.25: rejected; replaced with a cited source.",
    "Calling the thresholds preregistered: rejected; exploration had preceded the thresholds.",
    "Paging on a fixed percentage of API errors (set without asking the owner): rejected; replaced by the Tier 1 status design.",
    "Bootstrap output presented as formal intervals with a degradation rule: modified; relabeled exploratory and removed from severity.",
    "Recommending a fallback to the z-score rule: rejected; that rule also scored below prevalence.",
    "Nonstandard labels (\"change alerts\"): rejected.",
])
story.append(PageBreak())

# ================= 13. Q&A =================
h1("13. Likely questions")
qa = [
    ("Why not retrain whenever drift is detected?",
     f"Not all drift matters. S1 has a large input shift (spread PSI {f3(S['S1']['tier2']['features']['spread_normalized']['psi'])}) "
     f"with score PSI {f3(S['S1']['tier2']['score_psi'])} and almost no alert change. Labeled evidence is needed to establish a performance problem, and root-cause analysis determines whether retraining is appropriate."),
    ("Your interim said the split-half was a false alarm. Was the interim wrong?",
     f"The core hypothesis survived; the interpretation of that comparison did not. The refill mechanism was right, but the model's alerts really changed ({alerts('S2')}), so it was not a false alarm. We made it S2 and replaced the control with the interleaved split."),
    ("Why PSI rather than the KS p-value?",
     "The KS p-value indicates evidence of a difference under its assumptions but not its operational importance; it depends on "
     "sample size, and our rows are serially dependent. PSI measures the size of a shift, and score PSI and alert rate show "
     "whether the shift reaches the model's behavior. KS is kept as the before view."),
    ("Where do 0.10 and 0.25 come from? Did you tune them?",
     "They are conventional PSI heuristic bands from credit-scorecard practice (Lewis 1994, as traced by Potgieter et al. 2026), "
     "not calibrated thresholds. Only 0.10 is used for severity. The alert-rate thresholds were AI-proposed project settings. "
     "Some design choices followed exploratory analysis, so we do not call the experiment preregistered; instead we tested "
     f"{sens_n:,} setting combinations and the ordering did not change."),
    ("Is S0-S3 a test on unseen data?",
     "No. All scenarios derive from one five-minute recording that also informed the design. They are controlled "
     "development/evaluation scenarios; generalization to unseen data is untested."),
    ("Isn't S3 synthetic?",
     "It is a constructed fault, built from the supplied recording and replayed through Kafka and the real featurizer. S2 comes "
     "from the supplied data directly."),
    ("Does the model work?",
     TIER3_MEANING),
    ("Why is the alert rate so high?",
     f"The model alerts on {pct(R['alert_rate'])} of reference rows, mostly when trade intensity is high. The supplied logistic "
     "regression uses class_weight='balanced', which assigns class weights inversely proportional to class frequency during "
     "fitting. We have not tested whether this setting caused the observed alert rate."),
    ("What happens if the scorer fails some requests?",
     "Tier 1 reports DEGRADED with the exact error count and rate; if no request produces a prediction, it is UNAVAILABLE and pages. "
     "No partial-error paging cutoff was set because no SLO was supplied."),
    ("What would you monitor after deploying?",
     "Tier 1 status and telemetry, score PSI and alert rate per window, Tier 3 once labels arrive, and breaks in the data, since "
     "trade intensity drives the score."),
    ("How does B3 relate to B1 and B2?",
     "As team integration points (not independently verified by B3): B2 concerns whether the model is loaded; B3 checks its behavior. B1 concerns keeping up with the feed; in B3's scenarios, breaks or losses in the message stream changed trade intensity and the model's predictions."),
]
for q, a in qa:
    story.append(KeepTogether([Paragraph(f"<b>Q: {q}</b>", P), Paragraph(a, B), Spacer(1, 3)]))
story.append(PageBreak())

# ================= 14. Reproduce =================
h1("14. Reproducing the results")
p(f"Full commands, including building the feature files through Kafka, are in {c('B3_README.md')}. With the feature files "
  "and model in place (Docker needed only for the monitor's Tier 1):")
for line in ["python monitoring/b3_monitor.py", "python monitoring/b3_diagnosis.py", "python monitoring/b3_sensitivity.py",
             "python monitoring/b3_exploration.py", "python monitoring/b3_figures.py"]:
    story.append(Paragraph(line, CODE))
story.append(PageBreak())

# ================= 15. Glossary =================
h1("15. Glossary")
gl = [
    ("Alert rate", "Share of rows where the score is 0.5 or more; stands in for operator workload."),
    ("Autocorrelation / serial dependence", "Each row resembles the rows just before it, as in streaming data."),
    ("Bid / ask / spread", "Highest buyer price, lowest seller price, and the gap between them."),
    ("Bootstrap (row)", "Resampling rows with replacement many times and recomputing a number, to see how much it varies."),
    ("Controlled development/evaluation scenario", "A constructed comparison with an intended interpretation, used to see how the monitor behaves; not a test on unseen data."),
    ("Correlation (r)", "How strongly two numbers move together, from -1 to +1."),
    ("Data drift", "A change in the distribution of a model's inputs."),
    ("DEGRADED / UNAVAILABLE / NOT_CHECKED", "Tier 1 statuses: partial /score failures; no predictions possible (PAGE); Tier 1 not evaluated."),
    ("Evidently", "The supplied drift-report tool; on this data it uses the KS test per feature."),
    ("Exploratory row-bootstrap interval", "The 2.5th-97.5th percentiles of bootstrap results; used descriptively, not as a formal interval estimate."),
    ("Fault injection", "Deliberately introducing a known failure to see whether monitoring responds."),
    ("In-sample", "Evaluated on data used to train the model. Here the reference recording is effectively in-sample because the training file repeats it. S1 and S3 are transformations of the same underlying recording, so none of the scenarios provides genuinely independent out-of-sample data."),
    ("Internal threshold-robustness analysis", "Rerunning the frozen rules with alternative settings on the same scenarios."),
    ("Kafka / topic / replay", "A message queue; a named stream; publishing recorded messages as if live."),
    ("KS test and p-value", "Tests whether two samples differ in distribution; the p-value is evidence of a difference under the test's assumptions, not its importance."),
    ("Label / spike / tau", "The true answer known afterwards; a spike if next-20-message variability is at or above tau."),
    ("Lift", "PR-AUC minus the prevalence baseline."),
    ("Prediction drift", "A change in the distribution of the model's outputs."),
    ("Prevalence baseline", "The PR-AUC a no-information ranking gets: the share of rows that are spikes."),
    ("PR-AUC", "Area under the precision-recall curve: how well scores rank spikes above non-spikes."),
    ("PSI", "Population Stability Index: how much a distribution moved across bins taken from the reference."),
    ("Score PSI", "PSI on the model's output scores."),
    ("Trade intensity", "Messages in the last 60 s; low until the window has filled, e.g. at the start or after a break."),
]
table([["Term", "Meaning"]] + [[t, d] for t, d in gl], [2.0, 4.6])

story.append(PageBreak())
h1("16. External references")
URL = ParagraphStyle("URL", parent=B, fontName="Courier", fontSize=7.5, leading=10)
refs = [
    ("Potgieter, C. J., Van Zyl, C., Schutte, W. D., et al. (2026). The population resemblance statistic: a chi-square "
     "measure of fit for banking. <i>Annals of Operations Research</i>, 361, 413-435. https://doi.org/10.1007/s10479-025-07024-6",
     "Used for: tracing PSI to Lewis (1994); the 0.10 and 0.25 \"Lewis constants\" (below 0.10 little or no action, "
     "0.10-0.25 investigate, above 0.25 consider reconstruction); and the point that these fixed constants do not account "
     "for shift magnitude or sampling variability and are not universal, statistically calibrated thresholds."),
    ("Lewis (1994), cited only via Potgieter et al. (2026); not consulted directly.", None),
    ("Feature-engine, DropHighPSIFeatures source: "
     "https://github.com/feature-engine/feature_engine/blob/main/feature_engine/selection/drop_psi_features.py",
     "Used for: defaults threshold=0.25, bins=10, strategy=\"equal_frequency\", min_pct_empty_bins=0.0001; documentation "
     "naming 0.25 and 0.10 as commonly used PSI thresholds; the small constant for empty/zero bins. Our psi() uses the same "
     "constant with a different implementation (Section 6.5)."),
    ("SciPy documentation, scipy.stats.ks_2samp: "
     "https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.ks_2samp.html",
     "Used for: the two-sample KS test compares the continuous distributions of two independent samples (Section 6.2)."),
    ("scikit-learn documentation, sklearn.linear_model.LogisticRegression: "
     "https://scikit-learn.org/stable/modules/generated/sklearn.linear_model.LogisticRegression.html",
     "Used for: class_weight='balanced' assigns class weights inversely proportional to class frequency."),
]
for i, (ref, use) in enumerate(refs, 1):
    story.append(Paragraph(ref, B, bulletText=f"{i}."))
    if use:
        story.append(Paragraph(use, ParagraphStyle("U", parent=B, leftIndent=26, textColor=colors.HexColor("#444444"))))
    story.append(Spacer(1, 4))

def footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#777777"))
    canvas.drawString(0.75 * inch, 0.5 * inch, "B3 Explainer: Monitoring and Drift")
    canvas.drawRightString(7.75 * inch, 0.5 * inch, f"Page {doc.page}")
    canvas.restoreState()


doc = SimpleDocTemplate(OUT, pagesize=letter, leftMargin=0.75 * inch, rightMargin=0.75 * inch,
                        topMargin=0.7 * inch, bottomMargin=0.8 * inch, title="B3 Explainer", author="Vidhi Kothari")
doc.build(story, onFirstPage=footer, onLaterPages=footer)
print("wrote", OUT)
