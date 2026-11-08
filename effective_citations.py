#!/usr/bin/env python3
"""Score all papers in the Netzschleuder INSPIRE-HEP citation snapshot."""

import argparse
import gzip
import math
import tempfile
from pathlib import Path
from zipfile import ZipFile

import numpy as np
import pandas as pd
from scipy.sparse import csr_matrix

from snapshot import download_snapshot


def date_bounds(dates):
    """Return inclusive YYYYMMDD bounds. Missing or unknown dates become 0."""
    dates = dates.fillna("")
    formats = ((r"[0-9]{4}", 10000, 101, 1231),
               (r"[0-9]{4}-[0-9]{2}", 100, 1, 31),
               (r"[0-9]{4}-[0-9]{2}-[0-9]{2}", 1, 0, 0))
    earliest = np.zeros(len(dates), dtype=np.int32)
    latest = np.zeros(len(dates), dtype=np.int32)
    for pattern, multiplier, start, end in formats:
        matching = dates.str.fullmatch(pattern).to_numpy()
        prefix = dates[matching].str.replace("-", "", regex=False).to_numpy(dtype=np.int32)
        earliest[matching] = prefix * multiplier + start
        latest[matching] = prefix * multiplier + end
    return earliest, latest


def load_graph(snapshot):
    """Return deduplicated citation links in chronological node order."""
    with ZipFile(snapshot) as archive:
        with archive.open("nodes.csv") as stream:
            nodes = pd.read_csv(
                stream,
                usecols=["# index", " name", " title", " date"],
                dtype={" name": np.int64, " date": str},
                escapechar="\\",
                keep_default_na=False,
            )
        if not np.array_equal(nodes["# index"].to_numpy(), np.arange(len(nodes))):
            raise ValueError("Expected consecutive vertex indices in nodes.csv")
        if not nodes[" name"].is_unique:
            raise ValueError("Expected a unique INSPIRE record ID for each vertex")

        earliest, latest = date_bounds(nodes[" date"])
        order = np.argsort(earliest).astype(np.int32)
        rank = np.empty(len(nodes), dtype=np.int32)
        rank[order] = np.arange(len(nodes), dtype=np.int32)
        cited_rows, citing_columns = [], []
        input_links = 0

        with archive.open("edges.csv") as stream:
            chunks = pd.read_csv(
                stream, header=0, names=["citing", "cited"],
                dtype=np.int32, chunksize=2_000_000,
            )
            for chunk in chunks:
                if chunk.empty:
                    continue
                citing = chunk["citing"].to_numpy()
                cited = chunk["cited"].to_numpy()
                input_links += len(chunk)
                if citing.min() < 0 or cited.min() < 0 or max(citing.max(), cited.max()) >= len(nodes):
                    raise ValueError("edges.csv contains an invalid vertex index")
                dated = (latest[cited] > 0) & (earliest[citing] > latest[cited])
                cited_rows.append(rank[cited[dated]])
                citing_columns.append(rank[citing[dated]])

    rows = np.concatenate(cited_rows) if cited_rows else np.empty(0, dtype=np.int32)
    columns = np.concatenate(citing_columns) if citing_columns else np.empty(0, dtype=np.int32)
    # Boolean sparse storage merges repeated references to the same record.
    graph = csr_matrix((np.ones(len(rows), dtype=bool), (rows, columns)),
                       shape=(len(nodes), len(nodes)))
    ordered_nodes = nodes.iloc[order].reset_index(drop=True)
    return ordered_nodes, earliest[order], graph, input_links


def calculate_scores(graph, earliest, rates):
    """For each rate p, calculate E(A) = direct(A) + p * sum(E(B))."""
    direct = np.diff(graph.indptr)
    scores = np.tile(direct, (len(rates), 1)).astype(np.float64)
    boundaries = np.r_[0, np.flatnonzero(earliest[1:] != earliest[:-1]) + 1, len(earliest)]

    # All papers cited by a group are strictly older. In descending date order,
    # every citing paper's effective score is already available.
    for group in range(len(boundaries) - 2, -1, -1):
        start, stop = boundaries[group:group + 2]
        first_edge, last_edge = graph.indptr[[start, stop]]
        if first_edge == last_edge:
            continue
        active_rows = start + np.flatnonzero(direct[start:stop])
        segment_starts = graph.indptr[active_rows] - first_edge
        citing_papers = graph.indices[first_edge:last_edge]
        for rate, result in zip(rates, scores):
            inherited = np.add.reduceat(result[citing_papers], segment_starts)
            result[active_rows] += rate * inherited

    if not np.isfinite(scores).all():
        raise ValueError("Scores overflowed. Try a smaller pass-back rate.")
    return direct, scores


def write_scores(path, table):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as temporary:
        partial = Path(temporary.name)
    try:
        if path.name.endswith(".gz"):
            stream = gzip.open(partial, "wt", encoding="utf-8", newline="", compresslevel=5)
        else:
            stream = partial.open("w", encoding="utf-8", newline="")
        with stream:
            table.to_csv(stream, index=False, float_format="%.8f")
        partial.replace(path)
    finally:
        partial.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, default=Path("citations.csv.zip"),
                        help="Netzschleuder CSV ZIP; downloaded here if absent")
    parser.add_argument("--rates", type=float, nargs="+", default=[0.5, 1.0],
                        help="pass-back percentages, e.g. 0.5 1 for 0.5%% and 1%%")
    parser.add_argument("--output", type=Path, default=Path("inspire_scores.csv.gz"),
                        help="output CSV; use a .gz suffix for compression")
    parser.add_argument("--lookup", nargs="+", default=[],
                        help="also print papers by INSPIRE ID or title substring")
    parser.add_argument("--include-titles", action="store_true",
                        help="include titles in the full CSV export")
    args = parser.parse_args()
    if any(not math.isfinite(rate) or not 0 <= rate <= 100 for rate in args.rates):
        parser.error("each rate must be a finite percentage from 0 to 100")
    if len(set(args.rates)) != len(args.rates):
        parser.error("rates must be distinct")
    if args.output.resolve() == args.snapshot.resolve():
        parser.error("output and snapshot must be different paths")

    if not args.snapshot.exists():
        download_snapshot(args.snapshot)
    nodes, earliest, graph, input_links = load_graph(args.snapshot)
    print(f"{len(nodes):,} records, {input_links:,} source edge rows, "
          f"{graph.nnz:,} distinct date-ordered links", flush=True)
    direct, scores = calculate_scores(graph, earliest, [rate / 100 for rate in args.rates])

    table = pd.DataFrame({
        "inspirehep_id": nodes[" name"],
        "first_date": nodes[" date"],
        "direct_citations": direct,
    })
    for rate, values in zip(args.rates, scores):
        percentage = str(rate).removesuffix(".0")
        table[f"effective_{percentage}pct"] = values

    if args.lookup:
        for term in args.lookup:
            if term.isdecimal():
                matches = table["inspirehep_id"].eq(int(term))
            else:
                matches = nodes[" title"].str.contains(term, case=False, regex=False, na=False)
            selected = table[matches].copy()
            if selected.empty:
                print(f"No papers matched {term!r}")
                continue
            selected.insert(1, "title", nodes.loc[matches, " title"])
            print(selected.to_string(index=False, float_format=lambda value: f"{value:.4f}"))

    if args.include_titles:
        table.insert(1, "title", nodes[" title"])
    write_scores(args.output, table.sort_values("inspirehep_id"))
    print(f"Wrote {len(table):,} scores to {args.output}")


if __name__ == "__main__":
    main()
