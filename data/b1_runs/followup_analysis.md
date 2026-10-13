# B1 follow-up analysis

## 1. Featurizer time by step (from the last [timing] line of each log)

| run | parse | compute features | window | produce | save (Parquet) | commit | total | per row |
|---|---|---|---|---|---|---|---|---|
| ana1 single 25 | 121 ms (1.1%) | 10 ms (0.1%) | 26 ms (0.2%) | 119 ms (1.1%) | 9,533 ms (84.1%) | 1,523 ms (13.4%) | 11,331 ms | 0.964 ms |
| ana1 parts 25 | 163 ms (4.1%) | 14 ms (0.3%) | 36 ms (0.9%) | 156 ms (3.9%) | 2,542 ms (64.1%) | 1,052 ms (26.6%) | 3,963 ms | 0.337 ms |
| ana1 parts 100 | 315 ms (10.1%) | 29 ms (0.9%) | 70 ms (2.2%) | 390 ms (12.5%) | 2,063 ms (65.9%) | 265 ms (8.5%) | 3,132 ms | 0.267 ms |
| ana1 parts 500 | 317 ms (21.4%) | 30 ms (2.0%) | 72 ms (4.8%) | 468 ms (31.5%) | 541 ms (36.5%) | 55 ms (3.7%) | 1,484 ms | 0.126 ms |
| ana2 single 25 | 177 ms (1.3%) | 17 ms (0.1%) | 38 ms (0.3%) | 174 ms (1.3%) | 11,775 ms (89.2%) | 1,018 ms (7.7%) | 13,199 ms | 1.123 ms |
| ana2 parts 25 | 281 ms (4.2%) | 26 ms (0.4%) | 62 ms (0.9%) | 334 ms (5.0%) | 5,017 ms (74.7%) | 992 ms (14.8%) | 6,713 ms | 0.571 ms |
| ana2 parts 100 | 300 ms (10.8%) | 28 ms (1.0%) | 64 ms (2.3%) | 346 ms (12.5%) | 1,796 ms (64.7%) | 240 ms (8.7%) | 2,775 ms | 0.236 ms |
| ana2 parts 500 | 245 ms (17.0%) | 23 ms (1.6%) | 55 ms (3.8%) | 340 ms (23.6%) | 719 ms (49.9%) | 58 ms (4.0%) | 1,441 ms | 0.123 ms |

## 2. Output fingerprints (rows sorted on every column, then SHA-256)

| run | files | rows | sha256 (first 16) |
|---|---|---|---|
| ana1 single 25 | 1 | 23500 | 14f9211c573ba024 |
| ana1 parts 25 | 471 | 23500 | 14f9211c573ba024 |
| ana1 parts 100 | 119 | 23500 | 14f9211c573ba024 |
| ana1 parts 500 | 25 | 23500 | 14f9211c573ba024 |
| ana2 single 25 | 1 | 23500 | 14f9211c573ba024 |
| ana2 parts 25 | 471 | 23500 | 14f9211c573ba024 |
| ana2 parts 100 | 119 | 23500 | 14f9211c573ba024 |
| ana2 parts 500 | 25 | 23500 | 14f9211c573ba024 |

Equal fingerprints within a pass mean identical rows and values. Pass 1 and pass 2 process the same messages, so their fingerprints should also match each other.

## 3. Save time while the replay was sending vs after it stopped

| run | rows processed when replay ended | flushes during replay | median save during replay | flushes after replay | median save after replay |
|---|---|---|---|---|---|
| ana1 single 25 | ~10,924 | 436 | 16.2 ms | 34 | 41.0 ms |
| ana1 parts 25 | ~11,751 | 470 | 5.0 ms | 0 |  |
| ana1 parts 100 | ~11,751 | 117 | 11.7 ms | 0 |  |
| ana1 parts 500 | ~11,751 | 23 | 14.3 ms | 0 |  |
| ana2 single 25 | ~8,552 | 342 | 27.9 ms | 128 | 18.3 ms |
| ana2 parts 25 | ~11,751 | 470 | 10.5 ms | 0 |  |
| ana2 parts 100 | ~11,751 | 117 | 10.8 ms | 0 |  |
| ana2 parts 500 | ~11,751 | 23 | 10.3 ms | 0 |  |

Rows at the cut are estimated from committed offsets (11,754 feature rows per 14,076 messages). In single mode the file keeps growing after the cut, so if saves are still FASTER after the replay stops, competition for the laptop during the replay outweighs file size.
