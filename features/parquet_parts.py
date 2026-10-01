"""
features/parquet_parts.py   (NEW FILE - not in the starter kit)

B1 intervention 1: write each flush to its own small Parquet "part" file in a
folder, instead of reading + rewriting one ever-growing file.

Why: the starter kit's _append_parquet reads the WHOLE file, adds 25 rows, and
rewrites the WHOLE file, so each save gets slower as history grows. PartWriter
only ever writes the new rows, so each save costs about the same no matter how
much history already exists.

Folder layout produced:
    data/processed/features_<label>_parts/
        part-000000.parquet   (optional: a seed / earlier history)
        part-000001.parquet   (flush 1: ~25 rows)
        part-000002.parquet   (flush 2: ~25 rows)
        ...

Reading it back: pd.read_parquet("data/processed/features_<label>_parts")
returns all parts combined as one DataFrame.
"""
import os
import re

import pandas as pd

_PART_RE = re.compile(r"^part-(\d{6})\.parquet$")


class PartWriter:
    def __init__(self, folder):
        self.folder = folder
        os.makedirs(folder, exist_ok=True)
        # Look at the folder ONCE, at startup, to find where numbering should
        # continue (so a restart never overwrites an existing part).
        # We do not re-list the folder on every flush: listing thousands of
        # files each time would slowly reintroduce a cost that grows with history.
        nums = [int(m.group(1)) for name in os.listdir(folder)
                if (m := _PART_RE.match(name))]
        self.next_num = max(nums, default=0) + 1

    def write(self, rows):
        """Write only this batch of rows (a list of dicts) as one new part file."""
        if not rows:
            return
        name = f"part-{self.next_num:06d}.parquet"
        final_path = os.path.join(self.folder, name)
        # Write under a temporary name starting with "_", then rename.
        # Parquet readers skip files starting with "_" or ".", so nobody can
        # read a half-written part, and a crash mid-write leaves no broken part.
        tmp_path = os.path.join(self.folder, "_inprogress-" + name)
        pd.DataFrame(rows).to_parquet(tmp_path, index=False)
        os.replace(tmp_path, final_path)
        self.next_num += 1
