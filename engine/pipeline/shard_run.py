"""Stage / finalize one category shard around a collector run (used by CI).

    python3 -m pipeline.shard_run stage    --category hackathons [--from-full]
    python3 -m pipeline.shard_run finalize --category hackathons [--force]

stage: puts the shard's rows at data/lake/opportunities.json, the file every
collector already reads/writes, so collectors need no changes. If the shard
file is missing (first run), it is derived once from the full lake
(--from-full, expects data/lake/opportunities.json to be the full lake).

finalize: keeps only this shard's rows from opportunities.json, applies the
>50% drop guard against the staged row count, writes data/lake/shards/<cat>.json
and a markdown quality summary to stdout (and $GITHUB_STEP_SUMMARY).
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from core import shards
from core.paths import HIDDEN_PATH, LAKE_DIR, OPPORTUNITIES_PATH

PREV_COUNT = os.path.join(LAKE_DIR, "shards", ".prev_count")


def _pct(rows, pred):
    return "%d%%" % round(100.0 * sum(1 for r in rows if pred(r)) / len(rows)) if rows else "n/a"


def summary(cat, rows, prev):
    live = [r for r in rows if r.get("is_live") is True]
    ended = [r for r in rows if r.get("is_live") is False]
    has = lambda *ks: (lambda r: any(r.get(k) not in (None, "", [], "not_stated", "needs_confirmation") for k in ks))
    if shards.is_job_shard(cat):
        jobs = [r for r in live if not r.get("is_duplicate")]
        lines = [
            "### %s shard" % cat,
            "| metric | value |", "|---|---|",
            "| rows (prev -> now) | %s -> %d |" % (prev if prev is not None else "new", len(rows)),
            "| live | %d |" % len(live),
            "| live duplicates (not served) | %d |" % (len(live) - len(jobs)),
            "| ended | %d |" % len(ended),
        ]
        for label, keys in (("description", ("description",)), ("employment_type", ("employment_type",)),
                            ("workplace", ("workplace",)), ("salary", ("salary_min", "salary_text")),
                            ("posted_at", ("posted_at",)), ("deadline", ("deadline",)),
                            ("company_domain", ("company_domain",)), ("level", ("level",))):
            lines.append("| with %s (of live, non-dup) | %s |" % (label, _pct(jobs, has(*keys))))
        return "\n".join(lines)
    lines = [
        "### %s shard" % cat,
        "| metric | value |", "|---|---|",
        "| rows (prev -> now) | %s -> %d |" % (prev if prev is not None else "new", len(rows)),
        "| live | %d |" % len(live),
        "| ended | %d |" % len(ended),
        "| with deadline (of live) | %s |" % _pct(live, has("deadline", "registration_deadline")),
        "| with logo (of live) | %s |" % _pct(live, has("logo_url")),
        "| with description (of live) | %s |" % _pct(live, has("description")),
        "| with funding (of live) | %s |" % _pct(live, has("funding", "prize")),
    ]
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["stage", "finalize"])
    ap.add_argument("--category", required=True, choices=list(shards.ALL_SHARDS))
    ap.add_argument("--from-full", action="store_true")
    ap.add_argument("--force", action="store_true", help="bypass drop guard")
    args = ap.parse_args(argv)
    cat = args.category

    if args.action == "stage":
        rows = shards.load_shard(cat)
        if rows is None:
            if not args.from_full or not os.path.exists(OPPORTUNITIES_PATH):
                print("ERROR: shard %s missing; restore it or pass --from-full "
                      "with the full lake at %s" % (cat, OPPORTUNITIES_PATH), file=sys.stderr)
                return 2
            full = json.load(open(OPPORTUNITIES_PATH, encoding="utf-8"))
            rows = shards.split_rows(full)[cat]
            print("derived shard %s from full lake: %d rows" % (cat, len(rows)))
            if shards.is_job_shard(cat) and os.path.exists(HIDDEN_PATH):
                hid = [r for r in json.load(open(HIDDEN_PATH, encoding="utf-8"))
                       if shards.shard_of(r) == cat]
                shards.save_shard_hidden(cat, hid)
                print("derived hidden companion: %d rows" % len(hid))
        os.makedirs(LAKE_DIR, exist_ok=True)
        with open(OPPORTUNITIES_PATH, "w", encoding="utf-8") as fh:
            json.dump(rows, fh, ensure_ascii=False)
        with open(PREV_COUNT, "w") as fh:
            fh.write(str(len(rows)))
        if shards.is_job_shard(cat):
            # The sweep keeps rejected rows in hidden.json; stage this shard's.
            hp = shards.hidden_path(cat)
            hid = json.load(open(hp, encoding="utf-8")) if os.path.exists(hp) else []
            with open(HIDDEN_PATH, "w", encoding="utf-8") as fh:
                json.dump(hid, fh, ensure_ascii=False)
        print("staged %s: %d rows" % (cat, len(rows)))
        return 0

    rows = json.load(open(OPPORTUNITIES_PATH, encoding="utf-8"))
    mine = [r for r in rows if shards.shard_of(r) == cat]
    foreign = len(rows) - len(mine)
    if foreign:
        print("note: dropped %d non-%s rows from working file" % (foreign, cat))
    prev = int(open(PREV_COUNT).read()) if os.path.exists(PREV_COUNT) else None
    err = shards.drop_guard(prev if prev is not None else 0, len(mine), args.force)
    text = summary(cat, mine, prev)
    print(text)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as fh:
            fh.write(text + "\n")
    if err:
        print("ERROR: " + err, file=sys.stderr)
        return 3
    shards.save_shard(cat, mine)
    if shards.is_job_shard(cat) and os.path.exists(HIDDEN_PATH):
        hid = [r for r in json.load(open(HIDDEN_PATH, encoding="utf-8"))
               if shards.shard_of(r) == cat]
        shards.save_shard_hidden(cat, hid)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
