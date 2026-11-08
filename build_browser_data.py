#!/usr/bin/env python3
"""Pack the scorer's CSV into small, random-access browser downloads."""

import argparse
import csv
import gzip
from contextlib import ExitStack
from pathlib import Path
from struct import Struct

BUCKETS = 128
RECORD = Struct("<IIdd")


def build(scores, destination):
    destination.mkdir(parents=True, exist_ok=True)
    with gzip.open(scores, "rt", encoding="utf-8", newline="") as source, ExitStack() as stack:
        files = []
        for bucket in range(BUCKETS):
            path = destination / f"scores-{bucket:03}.bin.gz"
            raw = stack.enter_context(path.open("wb"))
            files.append(stack.enter_context(gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0)))
        previous = 0
        count = 0
        for row in csv.DictReader(source):
            record_id = int(row["inspirehep_id"])
            if record_id <= previous:
                raise ValueError("Score rows must be ordered by unique INSPIRE ID")
            files[record_id % BUCKETS].write(RECORD.pack(
                record_id, int(row["direct_citations"]),
                float(row["effective_0.5pct"]), float(row["effective_1pct"]),
            ))
            previous = record_id
            count += 1
    print(f"Packed {count:,} scores into {BUCKETS} browser downloads")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scores", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    build(args.scores, args.destination)
