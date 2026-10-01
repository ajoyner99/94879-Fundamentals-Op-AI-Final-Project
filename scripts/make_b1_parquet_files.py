import pandas as pd
from pathlib import Path

SOURCE = Path("data/processed/b1_rate4000_trial3.parquet")
OUT = Path("data/processed")
OUT.mkdir(parents=True, exist_ok=True)

df = pd.read_parquet(SOURCE)

sizes = {
    "small": 1_000,
    "medium": 10_000,
    "large": 50_000,
}

for name, n in sizes.items():
    repeats = (n // len(df)) + 1
    expanded = pd.concat([df] * repeats, ignore_index=True).iloc[:n]

    path = OUT / f"b1_size_{name}.parquet"
    expanded.to_parquet(path, engine="pyarrow", index=False)

    print(f"{name}: {len(expanded)} rows -> {path}")