"""Read-only report: how complete is the standard row shape per shard?

Usage (from engine/)::

    python3 -m pipeline.shape_report <dir-or-file...> [--serving-only]

Converts every row with ``core.rowshape.to_standard`` and prints one markdown
table per shard: row count, % non-empty for each of the 26 fields, the share of
rows with every REQUIRED field, and how many rows fail each required field.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Iterable, List

from pipeline import rowshape
from pipeline import publish_supabase


def _files(paths: Iterable[str]) -> List[str]:
    out: List[str] = []
    for p in paths:
        if os.path.isdir(p):
            out += sorted(os.path.join(p, f) for f in os.listdir(p) if f.endswith(".json"))
        else:
            out.append(p)
    return out


def _filled(value) -> bool:
    return value not in (None, "", [], {}) and not (
        isinstance(value, dict) and not any(v not in (None, "", []) for v in value.values()))


def _complete(std: dict, field: str) -> bool:
    if field == "proof":
        return bool(std["proof"].get("quote")) and bool(std["proof"].get("url"))
    return _filled(std[field])


def report(path: str, serving_only: bool) -> str:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    rows = data if isinstance(data, list) else data.get("rows", [])
    if serving_only:
        rows = [r for r in rows if publish_supabase.is_serving(r)]
    n = len(rows)
    filled = {k: 0 for k in rowshape.FIELDS}
    failing = {k: 0 for k in rowshape.REQUIRED}
    complete = 0
    for r in rows:
        std = rowshape.to_standard(r)
        for k in rowshape.FIELDS:
            filled[k] += _filled(std[k])
        bad = [k for k in rowshape.REQUIRED if not _complete(std, k)]
        for k in bad:
            failing[k] += 1
        complete += not bad
    pct = lambda c: "{:.1f}".format(100.0 * c / n) if n else "-"
    name = os.path.splitext(os.path.basename(path))[0]
    lines = ["## {} ({} rows{})".format(name, n, ", serving only" if serving_only else ""), "",
             "required complete: **{}%**".format(pct(complete)), "",
             "| field | % non-empty |", "|---|---|"]
    lines += ["| {} | {} |".format(k, pct(filled[k])) for k in rowshape.FIELDS]
    lines += ["", "| required field | rows failing |", "|---|---|"]
    lines += ["| {} | {} |".format(k, failing[k]) for k in rowshape.REQUIRED]
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--serving-only", action="store_true")
    args = ap.parse_args(argv)
    for path in _files(args.paths):
        print(report(path, args.serving_only))
    return 0


if __name__ == "__main__":
    sys.exit(main())
