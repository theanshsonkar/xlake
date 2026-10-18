"""Split the main lake into per-category shards, or combine them back.

    python3 -m pipeline.split_lake                 # DRY-RUN: print counts
    python3 -m pipeline.split_lake --execute       # write data/lake/shards/*.json
    python3 -m pipeline.split_lake --execute --strip-main   # also remove sharded rows from main
    python3 -m pipeline.split_lake --combine --out whole.json

Run from engine/ against a local copy of s3://$BUCKET/lake/opportunities.json.
Never writes to S3; the migrate-shards workflow does the uploads.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from core import shards
from core.paths import HIDDEN_PATH, OPPORTUNITIES_PATH


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lake", default=OPPORTUNITIES_PATH)
    ap.add_argument("--hidden", default=HIDDEN_PATH,
                    help="main hidden.json; its job rows are split into <shard>.hidden.json")
    ap.add_argument("--shards-dir", default=shards.SHARDS_DIR)
    ap.add_argument("--execute", action="store_true", help="write files (default dry-run)")
    ap.add_argument("--strip-main", action="store_true",
                    help="with --execute: rewrite main lake without sharded rows")
    ap.add_argument("--combine", action="store_true", help="emit whole lake (main + shards)")
    ap.add_argument("--out", help="output path for --combine")
    args = ap.parse_args(argv)

    if args.combine:
        rows = shards.load_whole_lake(args.lake, args.shards_dir)
        out = args.out or "-"
        if out == "-":
            json.dump(rows, sys.stdout)
        else:
            with open(out, "w", encoding="utf-8") as fh:
                json.dump(rows, fh, ensure_ascii=False)
        print("combined rows: %d" % len(rows), file=sys.stderr)
        return 0

    if not os.path.exists(args.lake):
        print("ERROR: lake not found at %s" % args.lake, file=sys.stderr)
        return 2
    rows = json.load(open(args.lake, encoding="utf-8"))
    parts = shards.split_rows(rows)
    print("MODE: %s" % ("EXECUTE" if args.execute else "DRY-RUN (nothing written)"))
    print("total rows: %d" % len(rows))
    for name in [shards.MAIN] + list(shards.ALL_SHARDS):
        live = sum(1 for r in parts[name] if r.get("is_live") is True)
        print("  %-12s rows=%-7d live=%d" % (name, len(parts[name]), live))
    assert sum(len(v) for v in parts.values()) == len(rows)
    if not args.execute:
        print("DRY-RUN complete.")
        return 0
    for name in shards.ALL_SHARDS:
        path = shards.save_shard(name, parts[name], args.shards_dir)
        print("wrote %s (%d rows)" % (path, len(parts[name])))
    if os.path.exists(args.hidden):
        hid = shards.split_rows(json.load(open(args.hidden, encoding="utf-8")))
        for name in shards.JOB_SHARDS:
            path = shards.save_shard_hidden(name, hid[name], args.shards_dir)
            print("wrote %s (%d hidden rows)" % (path, len(hid[name])))
    if args.strip_main:
        tmp = args.lake + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(parts[shards.MAIN], fh, ensure_ascii=False)
        os.replace(tmp, args.lake)
        print("main lake rewritten: %d rows" % len(parts[shards.MAIN]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
