"""B1 follow-up: compact a folder of Parquet part files into one file.

The part-file intervention (features/parquet_parts.py) keeps every save cheap,
but leaves hundreds of small files. This is the periodic compaction step the
memo recommends: read every part, write one file, and only then (optionally)
remove the parts.

Usage (from the repo root):
    python features/compact_parts.py --parts data/processed/features_parts --out data/processed/features_compacted.parquet
    python features/compact_parts.py --parts ... --out ... --delete-parts   # remove parts after a verified write

Safety:
- The new file is written to a temporary name and renamed into place, so a crash
  never leaves a half-written output.
- Parts are deleted only after the compacted file is re-read and its row count
  matches the parts.
- --out must be outside the parts folder; otherwise a reader of the folder would
  see every row twice.
"""
import argparse
import os
import sys
from pathlib import Path

import pandas as pd


def list_parts(parts_dir: Path) -> list[Path]:
    files = sorted(p for p in parts_dir.glob("*.parquet")
                   if p.is_file() and not p.name.startswith(("_", ".")))  # skip in-progress temp files
    if not files:
        sys.exit(f"No .parquet files found in {parts_dir}")
    return files


def read_parts(parts_dir: Path) -> pd.DataFrame:
    """Read every part file in name order (part numbers preserve write order)."""
    return pd.concat((pd.read_parquet(f) for f in list_parts(parts_dir)), ignore_index=True)


def compact(parts_dir: Path, out_file: Path) -> pd.DataFrame:
    parts_dir = parts_dir.resolve()
    out_file = out_file.resolve()
    if parts_dir in out_file.parents:
        sys.exit("--out must be outside the parts folder, or readers of the folder would see duplicate rows")
    df = read_parts(parts_dir)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_file.with_name(out_file.name + ".tmp")
    df.to_parquet(tmp, index=False)
    os.replace(tmp, out_file)  # atomic rename on the same drive
    return df


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--parts", required=True, type=Path, help="folder of part files")
    ap.add_argument("--out", required=True, type=Path, help="compacted output file (outside the parts folder)")
    ap.add_argument("--delete-parts", action="store_true", help="delete the parts after a verified write")
    args = ap.parse_args()

    parts = list_parts(args.parts)
    df = compact(args.parts, args.out)
    check = pd.read_parquet(args.out)
    if len(check) != len(df):
        sys.exit(f"Row count mismatch after write: parts {len(df)}, compacted {len(check)}. Parts kept.")
    print(f"Compacted {len(parts)} part files, {len(df):,} rows -> {args.out}")

    if args.delete_parts:
        for f in parts:
            f.unlink()
        print(f"Deleted {len(parts)} part files")


if __name__ == "__main__":
    main()
