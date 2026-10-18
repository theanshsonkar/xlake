"""Duplicate marking for job rows. Never changes ids and never deletes rows.

Two postings are the same opportunity when they share a canonical URL, or the
same employer (company_domain, else the board-derived company key), normalised
title and normalised location. The freshest row keeps serving; the others get
``is_duplicate=True`` and ``duplicate_of=<winner url>`` and are not published.
Marking is recomputed from scratch every run, so a duplicate whose twin
disappears is un-marked automatically.
"""
from __future__ import annotations

import re
from typing import Dict, Iterable, List

from core import jobmeta, quality


def _loc_key(r: Dict) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(r.get("location") or "").lower()).strip()


def _company_key(r: Dict) -> str:
    dom = (r.get("company_domain") or "").lower()
    if dom:
        return "d:" + dom
    return "c:" + str(r.get("company") or quality.company_key(
        r.get("platform", ""), r.get("token", "")))


def _freshness(r: Dict):
    return (r.get("last_seen") or "", r.get("posted_at") or r.get("posted_on") or "",
            r.get("first_seen") or "")


def _eligible(r: Dict) -> bool:
    return not r.get("record_type") and r.get("is_live") is not False


def mark_duplicates(rows: Iterable[Dict]) -> Dict[str, int]:
    rows = [r for r in rows if not r.get("record_type")]
    for r in rows:
        r["is_duplicate"] = False
        r["duplicate_of"] = None
    live = [r for r in rows if _eligible(r)]

    def collapse(keyfn) -> int:
        groups: Dict[object, List[Dict]] = {}
        for r in live:
            if r["is_duplicate"]:
                continue
            k = keyfn(r)
            if k is not None:
                groups.setdefault(k, []).append(r)
        n = 0
        for g in groups.values():
            if len(g) < 2:
                continue
            g.sort(key=_freshness, reverse=True)
            win = g[0]
            for loser in g[1:]:
                loser["is_duplicate"] = True
                loser["duplicate_of"] = win.get("url") or win.get("job_id")
                n += 1
        return n

    by_url = collapse(lambda r: jobmeta.canonical_url(r.get("url")) or None)
    by_text = collapse(lambda r: (
        _company_key(r),
        r.get("title_norm") or quality.normalise_title(r.get("title", "")),
        _loc_key(r)) if (r.get("title") or "").strip() else None)
    return {"by_url": by_url, "by_company_title_location": by_text,
            "total": by_url + by_text}
