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

Install the extra dependencies (not in the project `requirements.txt`):

```
pip install reportlab
```

Commands:

```
python scripts/b3_docs/build_explainer.py
python scripts/b3_docs/build_team_summary.py
```

Notes:

- Fonts: the PDFs use reportlab's built-in Helvetica and Courier.
- The PDFs' text is in their scripts, with all empirical numbers read from
  `data/b3_runs/` at build time.
