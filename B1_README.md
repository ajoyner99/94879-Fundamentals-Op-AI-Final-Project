## B1: Falling Behind — intervention and experiments

### Background

Under sustained load at replay rate 4000, the featurizer kept up when its Parquet output file
started empty but fell behind (lag grew at every sample) when the file already held ~11,750
rows. Timing showed that Parquet writes were 74–87% of the featurizer's measured time.

**Hypothesis:** the pipeline falls behind because every flush (every 25 rows) calls
`_append_parquet`, which reads the entire existing file, adds 25 rows, and rewrites the whole
file. Each save therefore gets slower as history accumulates.

**What would falsify it:** if saving only the new rows (never touching history) still got slower
as starting history grew, or the pipeline still fell behind with large history, the cost is not
coming from rereading and rewriting history.

**Intervention:** write each flush to its own small "part" file inside a folder, instead of
rewriting one growing file. Each save writes only the new rows, so its cost should no longer
depend on how much history exists.

### Files added or changed (not in the starter kit)

| File                               | Status | Purpose                                                                                                                                                                                                                                       |
|------------------------------------|--------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `features/parquet_parts.py`        | new | `PartWriter`: writes each flush as `part-000001.parquet`, `part-000002.parquet`, … in a folder. Writes to a temporary `_inprogress-` name first, then renames, so readers never see a half-written file.                                      |
| `features/featurizer.py`           | changed | New `--parquet_mode` flag: `single` (default, original starter-kit behavior) or `parts` (intervention). Every intervention line is marked `# B1 INTERVENTION`. Lines marked `# CHANGE` are the timing instrumentation added during diagnosis. |
| `scripts/make_b1_parquet_files.py` | new | Creates the controlled starting files with 1,000, 10,000, and 50,000 rows.                                                                                                                                                                    |
| `scripts/b1_size_comparison.py`    | new | **Main experiment.** Starting-size experiment run for both saving methods.                                                                                                                                                                    |
| `scripts/b1_before_after.py`       | new | **Supporting experiment.** Full live runs at rate 4000, measuring lag over time, before vs after.                                                                                                                                             |
| `scripts/b1_lag_recorder.py`       | new | Records current offset, log-end offset, lag, and arrival rate every 3 s. Started automatically by `b1_before_after.py`.                                                                                                                       |
| `scripts/b1_make_figures.py`       | new | Builds figures used in presentation and memo.                                                                                                                                                                                                 |
| `scripts/b1_timing_breakdown.py`   | new | reads the featurizer timing logs and reports the share of time spent on Parquet saves, commits, and everything else.                                                                                                                          |

The default `--parquet_mode single` keeps the original behavior, so "before" and "after" runs
use the same code and differ by a single flag.

### Prerequisites (both experiments)

1. Docker stack running (Kafka container named `broker`).
2. No featurizer, lag recorder, or replay already running.
3. Laptop plugged in, other programs closed (laptop speed varies between sessions).
4. Run all commands from the project folder (the one containing `features/` and `scripts/`).

---

### Experiment 1 (main evidence): starting-size comparison

**Question:** does save cost grow with history under the original method, and stay flat with
part files?

**Design:** for starting histories of 0, 1,000, 10,000, and 50,000 rows, the featurizer
processes the same 1,000 messages (= 40 flushes of 25 rows) using each saving method. Parquet
save time is read from the featurizer's `[timing]` log lines.

**Step 1: create the starting files** (only needed once)

```powershell
python scripts/make_b1_parquet_files.py
```

This creates `data/processed/b1_size_small.parquet` (1,000 rows), `b1_size_medium.parquet`
(10,000 rows), and `b1_size_large.parquet` (50,000 rows), built by repeating rows from
`data/processed/b1_rate4000_trial3.parquet`. Size 0 means no starting history.

**Step 2: run the comparison**

```powershell
python scripts/b1_size_comparison.py --tag t1 --repeats 3
```

- `--tag`: a short name for this set of runs. Use a new tag every time.
- `--repeats`: how many times each size × method combination runs (default 2).
  `--repeats 3` = 4 sizes × 2 methods × 3 = 24 runs, about 6–8 minutes.

**How the script keeps runs comparable**

- **Same 1,000 messages every run:** the workload is loaded into Kafka once at the start, and
  before every run the featurizer's offset is reset to the same starting position.
- **Both methods measured in the same session:** the original method is rerun rather than
  compared with numbers from an earlier day.
- **Run order alternates** between repeats, so laptop warm-up cannot favor one method.
- **Checks:** the script stops if a starting file has the wrong row count, if a run does not
  add exactly 1,000 rows and 40 flushes, or if the log does not show the intended
  `--parquet_mode`.

**Output**

- A printed summary table (median of the repeats) of total save time and average time per
  flush for each starting size and method.
- Every individual run: `data/b1_runs/sizes_<tag>.csv`
- Feature data and featurizer logs for every run: `data/processed/b1_sizes_<tag>/`

**How to read the table**

| Starting rows | Original method (`single`) | Intervention (`parts`) |
|---------------|----------------------------|------------------------|
| 0 | baseline | parts with no history |
| 1,000 / 10,000 / 50,000 | before | after |

1. Original-method column: save time should **grow** with starting rows (the diagnosis).
2. Intervention column: save time should stay **roughly flat** (the validation).
3. 50,000-row row: the largest before/after difference.
4. Intervention at 50,000 vs original at 0: if similar, history no longer affects save cost.

If the intervention column still grows clearly with starting rows, the hypothesis is not
supported. Use the spread across repeats in the CSV to judge whether a difference is larger
than run-to-run noise.

---

### Experiment 2 (supporting evidence): live lag before vs after

**Question:** does the intervention change lag behavior under the real workload?
Experiment 1 measures save time; this experiment measures whether the pipeline keeps up.

**Design:** two live runs at replay rate 4000, each starting with the same ~11,750 rows of
history (`data/processed/features_drain_test_t1.parquet`) and processing 11,750 rows:

| Run | Starting data | Method |
|-----|---------------|--------|
| before | seed as one file | `--parquet_mode single` |
| after | seed copied into a folder as `part-000000.parquet` | `--parquet_mode parts` |

**Run**

```powershell
python scripts/b1_before_after.py --tag t1
python scripts/b1_before_after.py --tag t2 --reverse
```

`--reverse` runs "after" first. Running the pair in both orders checks that run order does not
explain the difference. Each pair takes about 4 minutes.

**For each run the script:** checks the featurizer is stopped, resets offsets so lag starts at
0, copies the seed into place and checks its row count, starts the lag recorder and the
featurizer, waits until the featurizer is connected plus 10 s, runs the replay at rate 4000,
waits for 11,750 rows to be processed, stops the recorder, and prints a summary.

**Output** (run names are built from the tag, e.g. `before_rate4000_t1`, `after_rate4000_t1`)

| What | Where |
|------|-------|
| Feature rows (before) | `data/processed/features_before_rate4000_<tag>.parquet` |
| Feature rows (after) | `data/processed/features_after_rate4000_<tag>_parts/` |
| Lag over time | `data/b1_runs/lag_<run name>_*.csv` |
| Featurizer log | `data/b1_runs/featurizer_<run name>.log` |
| Recorder log | `data/b1_runs/recorder_<run name>.log` |

**How to read it**

- **Lag samples:** look at the direction, not a single value. Growing lag (e.g. 200 → 700 →
  1,300) means falling behind; small, stable lag means keeping up. Expected: "before" grows,
  "after" stays stable.
- **Per-flush save time, first 20 vs last 20 flushes:** "before" should slow down during the
  run as the file grows; "after" should stay flat.
- **Rows added:** should be exactly 11,750, showing no data was lost.

Lag is only precise to about ±25 messages, because offsets are committed once per flush.
Lag under roughly 25 counts as caught up.

---

### Reading part-file output

Point pandas at the folder instead of a single file:

```python
import pandas as pd
df = pd.read_parquet("data/processed/features_after_rate4000_t1_parts")
```

pandas combines every `part-*.parquet` file in the folder into one table. Files starting with
`_` (temporary files) are skipped automatically.

### Running the featurizer by hand

```powershell
# original behavior: one file, reread and rewritten every flush
python -u features/featurizer.py --parquet_path data/processed/features_<run name>.parquet --max_messages 11750

# intervention: a folder of part files
python -u features/featurizer.py --parquet_mode parts --parquet_path data/processed/features_<run name>_parts --max_messages 11750
```

Replace `<run name>` (including the angle brackets) with a new name for every run. In
`parts` mode the path is a folder; if it already contains parts, numbering continues and rows
from different runs get mixed, so always use a new name. For an "after" run with history,
create the folder and copy the seed in as `part-000000.parquet` first.

Manually reset the bookmark before running the featurizer again:
```powershell
# 1. reset the bookmark so lag starts at 0 (featurizer must be stopped first)
docker exec broker /opt/kafka/bin/kafka-consumer-groups.sh --bootstrap-server localhost:9092 --group featurizer_group --topic ticks.raw --reset-offsets --to-latest --execute

# 2. use a brand-new --parquet_path (and copy the seed in first if the run needs history)```

### Tradeoffs and limitations

- **Many small files:** about 470 parts per 11,750 rows. Reading many small files is slower
  than one large file; a periodic compaction job (outside the streaming path) would merge them.
- **Readers must change:** anything that loads the features (training, the drift report) must
  read the folder instead of a single file.
- **Column types must match across parts:** a batch with an entirely empty column could be
  saved with a different type and break reading the folder.
- **Not faster than an empty file:** each save still has a fixed cost; the intervention stops
  save cost from growing with history rather than removing it.
- **Next bottleneck:** offset commits (10–22% of measured time) become a larger share once
  save cost is constant.
- **Measurement limits:** runs are short (the workload is 14,076 messages), and laptop
  conditions vary between sessions.

### If a script stops

Both experiment scripts stop with a `[STOPPED]` message rather than run a bad experiment:

- **featurizer still connected:** press Ctrl+C in that terminal, then rerun.
- **path or folder already exists:** use a new `--tag`.
- **wrong row count in a starting file:** recreate the size files or check the seed.
- **featurizer never connected / did not finish:** read the featurizer log named in the message.
- **log does not show `parquet_mode=...`:** the old `featurizer.py` is still in place.