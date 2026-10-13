"""B1 check: did single mode and parts mode write identical rows?

Professor's feedback: "show that output rows are identical before and after",
not just that the counts match. This compares the full contents of the
single-file output (before) and the part-file folder (after) from the same
before/after workload.

Usage (from the repo root):
    python scripts/b1_check_identity.py --before <single .parquet> --after <parts folder>

    # If one side does not contain the 11,750 starting rows, compare only the
    # rows each run added (the last N rows in write order):
    python scripts/b1_check_identity.py --before ... --after ... --new-rows 11750

    # Leave out columns that legitimately differ between runs (e.g. a write timestamp):
    python scripts/b1_check_identity.py --before ... --after ... --ignore written_at

Either argument may be a single .parquet file or a folder of part files.
Rows are compared as a set: both sides are sorted on every column first, so a
different write order alone does not count as a difference.
"""
import argparse
import hashlib
import sys
from pathlib import Path

import pandas as pd


def load(path: Path) -> tuple[pd.DataFrame, int]:
    """Return (rows in write order, number of files)."""
    path = Path(path)
    if path.is_dir():
        files = sorted(p for p in path.glob("*.parquet")
                       if p.is_file() and not p.name.startswith(("_", ".")))  # skip in-progress temp files
        if not files:
            sys.exit(f"No .parquet files in {path}")
        return pd.concat((pd.read_parquet(f) for f in files), ignore_index=True), len(files)
    if not path.exists():
        sys.exit(f"Not found: {path}")
    return pd.read_parquet(path), 1


def canonical(df: pd.DataFrame) -> pd.DataFrame:
    """Same columns in the same order, rows sorted on every column."""
    df = df[sorted(df.columns)]
    return df.sort_values(list(df.columns), kind="mergesort").reset_index(drop=True)


def fingerprint(df: pd.DataFrame) -> str:
    row_hashes = pd.util.hash_pandas_object(df, index=False).to_numpy()
    return hashlib.sha256(row_hashes.tobytes()).hexdigest()[:16]


def compare(before: pd.DataFrame, after: pd.DataFrame) -> dict:
    result = {"rows_before": len(before), "rows_after": len(after)}
    cols_b, cols_a = set(before.columns), set(after.columns)
    result["only_in_before"] = sorted(cols_b - cols_a)
    result["only_in_after"] = sorted(cols_a - cols_b)
    common = sorted(cols_b & cols_a)
    result["dtype_differences"] = {
        c: (str(before[c].dtype), str(after[c].dtype)) for c in common if before[c].dtype != after[c].dtype
    }

    b = canonical(before[common])
    a = canonical(after[common].astype(before[common].dtypes.to_dict(), errors="ignore"))
    result["fingerprint_before"] = fingerprint(b)
    result["fingerprint_after"] = fingerprint(a)

    identical = len(b) == len(a) and not result["only_in_before"] and not result["only_in_after"] and b.equals(a)
    result["identical"] = identical
    if not identical and len(b) == len(a):
        diff_mask = ~((b == a) | (b.isna() & a.isna()))
        result["rows_that_differ"] = int(diff_mask.any(axis=1).sum())
        result["columns_that_differ"] = sorted(diff_mask.columns[diff_mask.any(axis=0)].tolist())
    return result


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--before", required=True, type=Path, help="single-mode output (file or folder)")
    ap.add_argument("--after", required=True, type=Path, help="parts-mode output (folder or file)")
    ap.add_argument("--new-rows", type=int, default=None, help="compare only the last N rows in write order")
    ap.add_argument("--ignore", nargs="*", default=[], help="columns to leave out of the comparison")
    args = ap.parse_args()

    before, files_before = load(args.before)
    after, files_after = load(args.after)
    if args.new_rows:
        before, after = before.tail(args.new_rows), after.tail(args.new_rows)
    before = before.drop(columns=[c for c in args.ignore if c in before.columns])
    after = after.drop(columns=[c for c in args.ignore if c in after.columns])

    r = compare(before, after)
    print(f"Files:        before {files_before:>6}   after {files_after:>6}")
    print(f"Rows:         before {r['rows_before']:>6,}   after {r['rows_after']:>6,}")
    if r["only_in_before"] or r["only_in_after"]:
        print(f"Columns only in before: {r['only_in_before']}   only in after: {r['only_in_after']}")
    if r["dtype_differences"]:
        print(f"Column type differences (before, after): {r['dtype_differences']}")
    print(f"Fingerprint:  before {r['fingerprint_before']}   after {r['fingerprint_after']}")
    if r["identical"]:
        print("RESULT: IDENTICAL - same rows and values after sorting")
    else:
        print("RESULT: DIFFERENT")
        if "rows_that_differ" in r:
            print(f"  {r['rows_that_differ']:,} rows differ, in columns: {r['columns_that_differ']}")
        sys.exit(1)


if __name__ == "__main__":
    main()
