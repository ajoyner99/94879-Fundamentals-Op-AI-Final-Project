# B1 follow-up: ana2 (seed: data/processed/inst_rate4000_t1_ana.parquet, order: reversed)

## Lag, files, saves and commits

| mode | flush_every | peak_lag | lag_samples_nonzero | final_lag | files | saves_with_timing | offset_commits | save_ms_per_flush | save_total_s | commit_total_s | rows_added | identical_to_single_25 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| single | 25 | 6077 | 2218 4248 6077 3835 4 4 4 4 | 4 | 1 | 470 | 471 | 25.05 | 11.775 | 1.018 | 11750 | True |
| parts | 25 | 494 | 494 77 53 4 4 4 | 4 | 471 | 470 | 471 | 10.68 | 5.017 | 0.992 | 11750 | True |
| parts | 100 | 121 | 113 63 121 4 4 4 | 4 | 119 | 117 | 118 | 15.35 | 1.796 | 0.24 | 11750 | True |
| parts | 500 | 246 | 121 246 232 4 4 4 | 4 | 25 | 23 | 24 | 31.26 | 0.719 | 0.058 | 11750 | True |

## Where the featurizer's time went

| mode | flush_every | save_share | commit_share | other_share | measured_total_s |
|---|---|---|---|---|---|
| single | 25 | 0.892 | 0.077 | 0.031 | 13.199 |
| parts | 25 | 0.747 | 0.148 | 0.105 | 6.713 |
| parts | 100 | 0.647 | 0.087 | 0.266 | 2.775 |
| parts | 500 | 0.499 | 0.04 | 0.461 | 1.441 |

## Reader cost (warm cache, median)

| what | files | median_s | min_s | max_s |
|---|---|---|---|---|
| read single 25-row output | 1 | 0.0051 | 0.0049 | 0.0069 |
| read parts 25-row output | 471 | 0.0982 | 0.0918 | 0.1082 |
| read parts 100-row output | 119 | 0.0312 | 0.0305 | 0.0321 |
| read parts 500-row output | 25 | 0.0094 | 0.0086 | 0.01 |
| compact 25-row parts -> 1 file | 471 | 0.9467 | 0.9337 | 1.0067 |
| read compacted file | 1 | 0.0064 | 0.006 | 0.0072 |
| drift report on 25-row parts | 471 | 4.944 |  |  |
| drift report on compacted file | 1 | 5.147 |  |  |

Compacted file identical to the part folder: True
