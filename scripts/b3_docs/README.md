# B3 document build scripts

These scripts regenerate the B3 documents from the committed outputs in
`data/b3_runs/` (JSON/CSV and `figures/`). They read numbers from those files;
they do not run the monitor. Run them from the repository root after
`monitoring/b3_monitor.py`, `b3_diagnosis.py`, `b3_sensitivity.py`,
`b3_exploration.py` and `b3_figures.py` have produced the outputs.

| Script | Output | Extra dependency |
|---|---|---|
| `build_explainer.py` | `B3_Explainer.pdf` | `reportlab` |
| `build_team_summary.py` | `B3_Team_Summary.pdf` | `reportlab` |
| `build_slides.py` | `B3_slides.pptx` | `python-pptx`; the team deck as template |

Install the extra dependencies (not in the project `requirements.txt`):

```
pip install reportlab python-pptx
```

Commands:

```
python scripts/b3_docs/build_explainer.py
python scripts/b3_docs/build_team_summary.py
python scripts/b3_docs/build_slides.py "OP AI B2 Challenge.pptx"
```

Notes:

- `build_slides.py` uses the team deck (`OP AI B2 Challenge.pptx`) only for its
  slide masters, layouts and theme; its slides are dropped. The team deck is
  not committed on this branch, so pass its path as the first argument.
- Fonts: the PDFs use reportlab's built-in Helvetica and Courier. The deck asks
  for Open Sans (titles, as in the team deck) and Calibri (body); PowerPoint
  substitutes if they are not installed, which can change line breaks.
- The slide text is the frozen `B3_slides_draft.md`, written into
  `build_slides.py` by hand; the PDFs' text is in their scripts, with all
  empirical numbers read from `data/b3_runs/` at build time.
