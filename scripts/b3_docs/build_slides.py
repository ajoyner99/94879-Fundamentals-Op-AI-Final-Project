import sys
from pathlib import Path
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN

REPO = str(Path(__file__).resolve().parents[2])  # repository root
FIG = f"{REPO}/data/b3_runs/figures"
OUT = f"{REPO}/B3_slides.pptx"

TEMPLATE = sys.argv[1] if len(sys.argv) > 1 else f"{REPO}/OP AI B2 Challenge.pptx"
if not Path(TEMPLATE).exists():
    sys.exit(f"Team template not found: {TEMPLATE}. Pass the team .pptx path as the first argument.")
prs = Presentation(TEMPLATE)
# Start from the team template: drop its slides, keep masters/layouts/theme.
sldIdLst = prs.slides._sldIdLst
for sldId in list(sldIdLst):
    prs.part.drop_rel(sldId.rId)
    sldIdLst.remove(sldId)
LAYOUT = [l for l in prs.slide_layouts if l.name == "Title Slide"][0]

INK = RGBColor(0x1B, 0x1B, 0x1B)
MUTED = RGBColor(0x55, 0x55, 0x55)
BLUE = RGBColor(0x2A, 0x78, 0xD6)
RED = RGBColor(0xC0, 0x39, 0x2B)
PANEL = RGBColor(0xEE, 0xF3, 0xFA)
SEV = {"OK": RGBColor(0x9A, 0x9A, 0x96), "LOW": RGBColor(0xF8, 0xB2, 0x1D),
       "HIGH": RGBColor(0xD0, 0x3B, 0x3B)}


def new_slide(title, notes=None):
    s = prs.slides.add_slide(LAYOUT)
    for ph in list(s.placeholders):
        ph._element.getparent().remove(ph._element)
    tb = s.shapes.add_textbox(Inches(0.5), Inches(0.35), Inches(12.3), Inches(0.65))
    r = tb.text_frame.paragraphs[0].add_run()
    r.text = title
    r.font.name, r.font.size, r.font.bold, r.font.color.rgb = "Open Sans", Pt(24), True, INK
    if notes:
        s.notes_slide.notes_text_frame.text = notes
    return s


def text(s, x, y, w, h, paras, size=16, font="Calibri"):
    """paras: list of str or list of (text, bold, color) runs; prefix '• ' adds a bullet."""
    tb = s.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = True
    for i, para in enumerate(paras):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.space_after = Pt(6)
        runs = [(para, False, INK)] if isinstance(para, str) else para
        for t, b, col in runs:
            r = p.add_run()
            r.text = t
            r.font.name, r.font.size, r.font.bold, r.font.color.rgb = font, Pt(size), b, col
    return tb


def panel(s, x, y, w, h, fill=PANEL):
    sh = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
    sh.adjustments[0] = 0.05
    sh.fill.solid()
    sh.fill.fore_color.rgb = fill
    sh.line.fill.background()
    return sh


def picture(s, path, x, y, w):
    return s.shapes.add_picture(path, Inches(x), Inches(y), width=Inches(w))


def table(s, x, y, w, rows, colw, size=12, sev_col=None):
    t = s.shapes.add_table(len(rows), len(rows[0]), Inches(x), Inches(y), Inches(w), Inches(0.3 * len(rows))).table
    for j, cw in enumerate(colw):
        t.columns[j].width = Inches(cw)
    for rr in t.rows:
        rr.height = Inches(0.25)
    for i, row in enumerate(rows):
        for j, val in enumerate(row):
            c = t.cell(i, j)
            c.text = val
            c.margin_left = c.margin_right = Inches(0.06)
            c.margin_top = c.margin_bottom = Inches(0.02)
            c.fill.solid()
            c.fill.fore_color.rgb = PANEL if i == 0 else RGBColor(0xFF, 0xFF, 0xFF)
            for p in c.text_frame.paragraphs:
                for r in p.runs:
                    r.font.name, r.font.size, r.font.color.rgb = "Calibri", Pt(size), INK
                    r.font.bold = i == 0 or (j == sev_col and val in SEV)
                    if i > 0 and j == sev_col and val in SEV:
                        r.font.color.rgb = SEV[val]
    return t


B = "• "

# ---------- Slide 1 ----------
s = new_slide("B3: It's running. Is it still working?",
              "\"This hypothesis was in our interim. The final monitor puts it into practice.\"\n\n(~30 seconds)")
text(s, 0.5, 1.15, 12.3, 0.6, [[("A healthy service does not mean the AI is behaving appropriately.", True, BLUE)]], size=22)
text(s, 0.5, 1.95, 12.3, 1.6, [
    B + "Every scenario: 0 API errors, Tier 1 HEALTHY, model loaded.",
    B + "But the model alerts on 45.9% of rows while 7.3% are spikes; precision at the 0.5 alert threshold is 6.4%.",
], size=20)
panel(s, 0.5, 3.75, 12.3, 1.55)
text(s, 0.75, 3.88, 11.8, 1.35, [
    [("Core interim hypothesis, which survived: ", True, INK),
     ("health checks and raw feature-drift tests alone can't tell you whether the AI still works. Monitor serving "
      "health, data/prediction drift and labeled performance separately. Feature drift means investigate, not retrain.",
      False, INK)]], size=19)
text(s, 0.5, 5.55, 12.3, 0.7, [[("What changed: ", True, RED),
                                 ("our interpretation of the split-half evidence, not the hypothesis.", False, INK)]], size=20)

# ---------- Slide 2 ----------
s = new_slide("Diagnosis: Alerts follow trade intensity, not spikes",
              "\"We revised the experiment rather than forcing the original explanation to fit.\"\n\n(~45-50 seconds)")
picture(s, f"{FIG}/fig_a_diagnosis.png", 0.35, 1.05, 8.5)          # 8.5 x 4.6 in
text(s, 0.35, 5.7, 8.5, 0.45, [[("Model alerts rise with trade intensity; actual spikes do not.", True, MUTED)]], size=15)
text(s, 9.05, 1.15, 4.0, 5.9, [
    B + "PR-AUC 0.070 vs prevalence 0.073 on the reference window: above-baseline performance is not established on the available data.",
    B + "Score vs trade intensity r = 0.80; score vs the actual spike label r = 0.006.",
    B + "The recording has a 171 s gap. Trade intensity is a rolling 60 s count, so it refills afterwards (167 in the first 60 s after the gap, 305 later). The message rate is about the same: 4.92 vs 4.74 msg/s.",
    [("Interim correction: ", True, RED),
     ("we had used the split-half comparison as a no-change control and called its flags a false alarm. It is a real "
      "change: alerts 13.5% to 78.3% while spikes are 6.1% vs 8.5%. It became S2; the new control is the interleaved split (S0).",
      False, INK)],
], size=13.5)

# ---------- Slide 3 ----------
s = new_slide("Intervention and evidence",
              "Don't walk through each cutoff. Shorthand:\n"
              "- Feature-only drift -> LOW\n"
              "- Score/output drift or moderate alert movement -> MEDIUM\n"
              "- Major alert-volume disruption -> HIGH\n\n"
              "Then go straight to S1 versus S2/S3. Exact cutoffs are for Q&A.\n\n"
              "\"Both S1 and S2 show statistical drift, but in S1 the model's output and alert workload barely move, while "
              "in S2 alerts jump from 13.5% to 78.3%. That is why raw drift alone is not enough for an operational decision.\"\n\n"
              "S3: \"The service remains HEALTHY while alerts collapse from 45.9% to 1.8%.\"\n\n(~60-70 seconds)")
picture(s, f"{FIG}/fig_b_validation.png", 0.3, 0.95, 8.75)          # 8.75 x 4.04 in
text(s, 0.3, 4.95, 8.75, 0.4, [[("Raw drift flags do not show consequence; model-output impact separates S1 from S2/S3.", True, MUTED)]], size=14)
panel(s, 9.6, 1.05, 3.45, 4.0)
text(s, 9.75, 1.12, 3.2, 3.9, [
    [("Tiered monitor", True, BLUE)],
    [("Tier 1, serving status: ", True, INK), ("HEALTHY / DEGRADED / UNAVAILABLE. PAGE only for serving unavailability.", False, INK)],
    [("Tier 2, drift graded by impact: ", True, INK), ("LOW = feature drift only; MEDIUM = score PSI >= 0.10 or alert shift > 5 pp; "
                                                       "HIGH = alert rate x2 or /2, or shift >= 20 pp.", False, INK)],
    [("Tier 3, separate and retrospective: ", True, INK), ("PR-AUC vs prevalence. Never sets severity.", False, INK)],
], size=12)
text(s, 9.6, 5.1, 3.45, 0.4, [[("5 pp / 20 pp / 2x are project-specific operating thresholds.", False, MUTED)]], size=10.5)
text(s, 9.6, 5.6, 3.45, 0.6, [[("S0 (odd vs even rows): KS 0/4, monitor OK. No change; stays quiet.", False, MUTED)]], size=10.5)
table(s, 0.3, 5.22, 9.1, [
    ["", "KS before view", "Monitor", "Why"],
    ["S1", "1/4 (p≈0)", "LOW", "Spread PSI 8.2, but score PSI 0.005 and alerts 45.9% to 46.2%"],
    ["S2", "3/4", "HIGH", "Alerts 13.5% to 78.3%"],
    ["S3", "2/4", "HIGH", "Alerts 45.9% to 1.8%, with the service HEALTHY"],
], [0.45, 1.3, 0.9, 6.45], size=11, sev_col=2)

# ---------- Slide 4 ----------
s = new_slide("How far to trust it, and what to do", "(~35-40 seconds)")
cols = [
    ("What we know", BLUE, None),
    ("What we don't know", RED, None),
    ("What we recommend", INK, None),
]
x0, w, gap = 0.5, 3.95, 0.22
for i, (head, col, _) in enumerate(cols):
    x = x0 + i * (w + gap)
    panel(s, x, 1.15, w, 5.0)
    text(s, x + 0.2, 1.25, w - 0.4, 0.5, [[(head, True, col)]], size=20)
text(s, 0.7, 1.9, 3.55, 2.0, ["Across 1,485 tested monitoring-setting combinations, the S0–S3 ordering remained unchanged."], size=16)
hl = panel(s, 0.65, 3.55, 3.65, 1.25, RGBColor(0xFF, 0xF4, 0xD6))
text(s, 0.8, 3.65, 3.4, 1.1, [[("Internal threshold robustness, not independent validation.", True, INK)]], size=18)
text(s, 0.5 + w + gap + 0.2, 1.9, 3.55, 4.6, [
    B + "All scenarios derive from one ~5-minute recording that also informed the design; there is no independent held-out evaluation.",
    B + "Whether the monitor and the model behave appropriately on unseen data.",
], size=16)
text(s, 0.5 + 2 * (w + gap) + 0.2, 1.9, 3.55, 4.6, [
    B + "Provisional, limited use of the monitor until it is tested once on an independently recorded replay window.",
    B + "Do not automatically retrain on feature drift (S1): route it to a data-quality check.",
    B + "Re-evaluate the model on genuinely out-of-sample labeled data before changing thresholds, retraining or replacing it.",
], size=16)

# ---------- Backups ----------
s = new_slide("B3 Backup B1: Severity ladder and Tier 1 status")
table(s, 0.5, 1.1, 12.3, [
    ["Level", "Triggered when (first matching rule wins)", "Action"],
    ["PAGE", "Tier 1 UNAVAILABLE", "Page on-call; restore the service. Model checks are not trustworthy until it is healthy."],
    ["HIGH", "Alert rate doubles or halves (ratio 2x), or shifts by 20 percentage points or more",
     "Escalate now to model owner and pipeline on-call; consider pausing alerts. Labeled evidence is needed to establish a performance problem; root-cause analysis determines whether retraining is appropriate"],
    ["MEDIUM", "Score PSI 0.10 or more, or alert-rate shift above 5 percentage points",
     "Investigate same day; notify model owner; no retraining unless labeled evidence establishes a performance problem and root-cause analysis supports retraining"],
    ["LOW", "Any feature PSI 0.10 or more, with no MEDIUM/HIGH condition", "Data-quality ticket: real change or feed bug? No model action"],
    ["OK", "None of the above", "No action"],
], [1.1, 4.6, 6.6], size=12)
table(s, 0.5, 4.45, 12.3, [
    ["Tier 1 status", "Meaning", "Operational behavior"],
    ["HEALTHY", "/health ok, model loaded, every attempted /score request produced a prediction", "Proceed"],
    ["DEGRADED", "/health ok and at least one prediction produced, but one or more /score requests failed", "Reported as a serving/reliability issue; not a drift severity; no paging cutoff"],
    ["UNAVAILABLE", "/health fails, the model is not loaded, or no /score request produced a prediction", "PAGE"],
    ["NOT_CHECKED", "Tier 1 skipped (--no_api)", "Tier 1 was not evaluated; this does not mean healthy"],
], [1.6, 6.0, 4.7], size=12)

s = new_slide("B3 Backup B2: Tier 3 exploratory lift intervals")
picture(s, f"{FIG}/fig_c_fitness.png", 1.65, 1.0, 10.0)            # 11 x 5.0 in
text(s, 1.65, 5.6, 10.0, 0.5, [[("Above-baseline performance is not established on the available data.", True, MUTED)]], size=16)

s = new_slide("B3 Backup B3: Where each setting comes from")
table(s, 0.5, 1.1, 12.3, [
    ["Setting", "Value", "Provenance"],
    ["Alert threshold", "0.5", "Supplied code (score_service.py)"],
    ["Spike label", "90th percentile, 20-row horizon", "Supplied code (label_spikes defaults)"],
    ["Operational PSI threshold", "0.10", "Externally sourced heuristic: conventional PSI band originating in credit-scorecard practice (Lewis 1994, as traced by Potgieter et al. 2026); not a universal statistically calibrated threshold"],
    ["PSI reference band", "0.25", "Same source; descriptive/figure line only; does not independently determine severity"],
    ["PSI bins", "10", "Matches Feature-engine's current default"],
    ["PSI empty-bin handling", "0.0001", "Our monitor uses the same numeric constant, 0.0001, but a different implementation: Feature-engine replaces/adds the constant for empty or zero bins, whereas our psi() floors bin proportions at that minimum."],
    ["MEDIUM alert shift", "5 pp", "AI-proposed project-specific threshold, accepted by owner"],
    ["HIGH alert shift / ratio", "20 pp / 2x", "AI-proposed project-specific thresholds, accepted by owner"],
    ["KS p-value; dataset-drift share", "0.05; 50%", "Evidently defaults, used for the baseline comparison"],
    ["Bootstrap resamples; seed", "1000; 0", "AI-selected exploratory implementation choices"],
], [2.6, 2.2, 7.5], size=12)

s = new_slide("B3 Backup B4: AI supervision")
text(s, 0.5, 1.1, 12.3, 5.9, [
    [("1. Split-half explanation: wrong twice, caught by measurement. ", True, INK),
     ("(a) AI assistance contributed the causal interpretation that the split-half flags came in part from the 60-second "
      "rolling feature window (the interim states that \"part of this comes from the featurizer itself\" and treated the "
      "split-half as an unchanged control). Subsequent diagnosis showed the rolling-window mechanism was real, but the "
      "conclusion that the comparison was a false alarm was wrong; (b) \"the message rate roughly triples after a 171 s "
      "gap\" was wrong: b3_diagnosis.py measured 4.92 vs 4.74 messages per second. Outcome: (b) removed everywhere; S2 kept "
      "as a real change with the corrected cause.", False, INK)],
    [("2. Operational thresholds: accepted provisionally, then stress-tested. ", True, INK),
     ("Proposed: candidate alert-rate thresholds (5 pp for MEDIUM; 2x or 20 pp for HIGH) and prediction drift alone deciding "
      "HIGH. Response: the owner replaced \"prediction drift decides\" with the graded structure and kept score PSI alone at "
      "MEDIUM; the numbers were accepted as project-specific settings, not standards. Checked: the frozen monitor was rerun "
      "across 1,485 setting combinations and the S0-S3 ordering remained unchanged. This tests dependence on parameter "
      "choices; it does not independently validate monitor generalization.", False, INK)],
    [("Scope: ", True, MUTED),
     ("the interim already established the high-level hypothesis; the AI assistant did not originate the B3 research "
      "question or hypothesis.", False, MUTED)],
], size=15)

prs.save(OUT)
print("wrote", OUT, len(prs.slides), "slides")
