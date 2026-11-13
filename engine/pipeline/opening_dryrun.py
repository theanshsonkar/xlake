"""Local dry run of the opening-date logic over shard JSON files (read-only).

Applies the current lifecycle to copies of the rows and prints, per category,
open->upcoming changes, dated opening quotes, opens_pattern rows and what the
API's opening_soon would list at 60/180 days. With --refetch it first re-reads
the official page of the in-scope rows (served programme rows with a future
opening_date, or upcoming rows with cycle history; at most --max) through the
project's polite fetcher and re-runs extraction. Writes only to --out.

  python3 -m pipeline.opening_dryrun shard.json [...] [--refetch] [--max 150] [--out report.json]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import cycles, lifecycle  # noqa: E402
from pipeline import publish_supabase as ps  # noqa: E402
from pipeline.rowshape import _dated_opens  # noqa: E402

KEYS = ("opening_date", "deadline", "opens_quote_dated", "opens_pattern")


def _configs():
    from categories.community.programmes import COMMUNITY_CONFIG
    from categories.fellowships.fellowships import FELLOWSHIP_CONFIG
    from categories.grants.grants import GRANT_CONFIG
    from categories.open_source.programmes import OPEN_SOURCE_CONFIG
    from categories.research.research import RESEARCH_CONFIG
    from categories.scholarships.scholarships import SCHOLARSHIP_CONFIG
    from categories.startup_founder.programmes import STARTUP_FOUNDER_CONFIG
    return {c.category: c for c in (COMMUNITY_CONFIG, FELLOWSHIP_CONFIG, GRANT_CONFIG, OPEN_SOURCE_CONFIG,
                                    RESEARCH_CONFIG, SCHOLARSHIP_CONFIG, STARTUP_FOUNDER_CONFIG)}


def _name(r):
    return r.get("programme_name") or r.get("title") or "?"


def _quote(r):
    return (((r.get("official_evidence") or {}).get("opening_date") or {}).get("quote")
            or (r.get("opens_pattern") or {}).get("quote") or "")


def in_scope(r, before, today):
    if r.get("record_type") != "programme" or not ps.is_serving(r):
        return False
    future = str(r.get("opening_date") or "")[:10] > today.isoformat()
    return future or (before == "upcoming" and bool(r.get("cycles")))


def refetch(row, configs):
    from categories import programme_core as pc
    config = configs.get(row.get("category"))
    if not config:
        return "no_config"
    seed = {k: row.get(k) for k in ("programme_id", "programme_name", "organizer", "official_url")}
    try:
        fetched = pc._default_fetch(row["official_url"])
        html, final = fetched if isinstance(fetched, tuple) else (fetched, None)
        rec, _ = pc.parse_programme(seed, html, None, final, config=config)
    except Exception as e:  # a failed read changes nothing
        return "fetch_failed: %s" % str(e)[:60]
    if not rec:
        return "no_record"
    for k in KEYS:
        row.pop(k, None)
        if k in rec:
            row[k] = rec[k]
    ev = dict(row.get("official_evidence") or {})
    ev["opening_date"] = (rec.get("official_evidence") or {}).get("opening_date") or {}
    row["official_evidence"] = ev
    return "ok"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("shards", nargs="+")
    ap.add_argument("--refetch", action="store_true")
    ap.add_argument("--max", type=int, default=150)
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    now = datetime.now(timezone.utc)
    today = now.date()
    stamp = now.isoformat(timespec="seconds")
    configs = _configs() if a.refetch else {}
    cat = defaultdict(lambda: defaultdict(list))
    fetched = defaultdict(int)
    for path in a.shards:
        rows = [r for r in json.load(open(path)) if isinstance(r, dict) and r.get("record_type") == "programme"]
        rows = [dict(r) for r in rows]
        before = {id(r): lifecycle.infer(r) if "lifecycle" not in r else r["lifecycle"] for r in rows}
        scoped = [r for r in rows if in_scope(r, before[id(r)], today)][:a.max]
        if a.refetch:
            for r in scoped:
                fetched[refetch(r, configs)] += 1
        lifecycle.reconcile(rows, today, stamp)
        cycles.finalize(rows, today)
        for r in rows:
            c = cat[r.get("category") or path]
            if before[id(r)] == "open" and r["lifecycle"] == "upcoming":
                c["open_to_upcoming"].append(r)
            if r in scoped:
                c["scope"].append(r)
                if _dated_opens(r):
                    c["dated_quote"].append(r)
                if r.get("opens_pattern"):
                    c["pattern"].append(r)
            if r["lifecycle"] == "upcoming" and ps.is_serving(r):
                d = r.get("expected_opens") or _dated_opens(r)
                for days in (60, 180):
                    if d and today < date.fromisoformat(d) <= today + timedelta(days=days):
                        c["soon%d" % days].append((d, r))
    report = {}
    for name, c in sorted(cat.items()):
        report[name] = {
            "open_to_upcoming": [_name(r) for r in c["open_to_upcoming"]],
            "in_scope": len(c["scope"]), "dated_opening_quote": len(c["dated_quote"]),
            "opens_pattern": len(c["pattern"]),
            "opening_soon_60": [(d, _name(r), _quote(r)) for d, r in sorted(c["soon60"], key=lambda t: t[0])],
            "opening_soon_180": [(d, _name(r), _quote(r)) for d, r in sorted(c["soon180"], key=lambda t: t[0])],
        }
        print("== %s: open->upcoming %d, in scope %d, dated opening quote %d, opens_pattern %d, soon60 %d, soon180 %d" % (
            name, len(c["open_to_upcoming"]), len(c["scope"]), len(c["dated_quote"]), len(c["pattern"]),
            len(c["soon60"]), len(c["soon180"])))
        for n in report[name]["open_to_upcoming"]:
            print("   open->upcoming: %s" % n)
        for days in (60, 180):
            for d, n, q in report[name]["opening_soon_%d" % days]:
                print("   soon%d: %s | %s | %s" % (days, d, n, q[:120]))
    if a.refetch:
        print("refetch:", dict(fetched))
    if a.out:
        with open(a.out, "w") as fh:
            json.dump(report, fh, indent=1, default=str)
    return 0


if __name__ == "__main__":
    sys.exit(main())
