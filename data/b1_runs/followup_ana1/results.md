# B1 follow-up: ana1 (seed: data/processed/inst_rate4000_t1_ana.parquet, order: normal)

## Lag, files, saves and commits

| mode | flush_every | peak_lag | lag_samples_nonzero | final_lag | files | saves_with_timing | offset_commits | save_ms_per_flush | save_total_s | commit_total_s | rows_added | identical_to_single_25 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| single | 25 | 3112 | 2420 3112 994 4 4 4 4 | 4 | 1 | 470 | 471 | 20.28 | 9.533 | 1.523 | 11750 | True |
| parts | 25 | 92 | 80 92 4 4 4 4 | 4 | 471 | 470 | 471 | 5.41 | 2.542 | 1.052 | 11750 | True |
| parts | 100 | 151 | 101 123 151 4 4 4 4 | 4 | 119 | 117 | 118 | 17.63 | 2.063 | 0.265 | 11750 | True |
| parts | 500 | 336 | 115 336 227 4 4 4 4 | 4 | 25 | 23 | 24 | 23.54 | 0.541 | 0.055 | 11750 | True |

## Where the featurizer's time went

| mode | flush_every | save_share | commit_share | other_share | measured_total_s |
|---|---|---|---|---|---|
| single | 25 | 0.841 | 0.134 | 0.024 | 11.331 |
| parts | 25 | 0.641 | 0.266 | 0.093 | 3.963 |
| parts | 100 | 0.659 | 0.085 | 0.257 | 3.132 |
| parts | 500 | 0.365 | 0.037 | 0.598 | 1.484 |

## Reader cost (warm cache, median)

| what | files | median_s | min_s | max_s |
|---|---|---|---|---|
| read single 25-row output | 1 | 0.0056 | 0.0047 | 0.0095 |
| read parts 25-row output | 471 | 0.1019 | 0.0913 | 0.1046 |
| read parts 100-row output | 119 | 0.0293 | 0.0273 | 0.0298 |
| read parts 500-row output | 25 | 0.0086 | 0.0084 | 0.0092 |
| compact 25-row parts -> 1 file | 471 | 0.831 | 0.7384 | 0.8588 |
| read compacted file | 1 | 0.0056 | 0.0054 | 0.0061 |
| drift report on 25-row parts | 471 | 6.606 |  |  |
| drift report on compacted file | 1 | 5.37 |  |  |

Compacted file identical to the part folder: True
