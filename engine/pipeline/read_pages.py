"""Mechanism 2: the page reader. Runs daily, costs a model call only when a
page's content actually changed.

    python3 read_pages.py                    # every company in
                                              # data/operations/pagereader_targets.json
    python3 read_pages.py --limit 10         # cheap smoke test
    python3 read_pages.py --company Zerodha  # one company

Pipeline per company:
  1. fetch the careers page (free, robots-checked, cached in core/cache.py)
  2. hash stable text and compare to the last hash recorded for this URL
  3. unchanged -> skip extraction; changed -> run the configured extractor
  4. enforce quotes and shared filters/quality

Writes `data/operations/pagereader_state.json` and
`data/operations/pagereader_rows.json`. The rows file is operational
processing/compatibility output, not a second final lake; canonical board lake
writes remain in `data/lake/`.

No AI runs in this file directly; it calls into adapters.extractors.
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional

from core import cache, filters, pagetext, quality, robots
from adapters import extractors
from core.paths import (
    DATA_ROOT, PAGEREADER_ROWS_PATH, PAGEREADER_STATE_PATH,
    PAGEREADER_TARGETS_PATH,
)
from pipeline.resolve import _fetch_page

DATA = DATA_ROOT
TARGETS = PAGEREADER_TARGETS_PATH
STATE = PAGEREADER_STATE_PATH
# Operational processing/compatibility output, not a second final lake.
OUT_ROWS = PAGEREADER_ROWS_PATH


def load_state() -> Dict[str, Dict]:
    if os.path.exists(STATE):
        try:
            return json.load(open(STATE))
        except Exception:  # noqa: BLE001
            pass
    return {}


def save_state(state: Dict[str, Dict]) -> None:
    os.makedirs(DATA, exist_ok=True)
    tmp = STATE + ".tmp"
    json.dump(state, open(tmp, "w"), indent=1)
    os.replace(tmp, STATE)


def read_one(company_row: Dict, state: Dict[str, Dict], extractor,
            force: bool = False) -> Dict:
    """Fetch, hash-gate, maybe extract. Returns a per-company report dict.

    Every branch is named so a run report can distinguish "skipped because
    unchanged" (good — the system working as designed) from "skipped because
    blocked" (bad — needs attention) from "extracted" (cost money).
    """
    company = company_row.get("company") or company_row.get("domain")
    url = company_row.get("careers_url") or ""
    if not url:
        # No careers URL was ever found for this company by the resolver.
        # Nothing to fetch — the resolver's own reason is the honest answer.
        return {"company": company, "url": "", "outcome": "no_careers_url",
                "detail": company_row.get("reason", ""), "roles": 0}

    allowed, why = robots.allowed(url)
    if not allowed:
        return {"company": company, "url": url, "outcome": "robots_blocked",
                "detail": why, "roles": 0}
    if robots.is_rate_limited(url):
        return {"company": company, "url": url, "outcome": "rate_limited",
                "detail": "", "roles": 0}

    status, final_url, html, err = _fetch_page(url)
    if not html:
        return {"company": company, "url": url, "outcome": "fetch_failed",
                "detail": "{}".format(err or status), "roles": 0}

    cache.put(final_url, status, html)

    new_hash = pagetext.content_hash(html)
    prev = state.get(url) or {}
    old_hash = prev.get("content_hash")
    unchanged = (old_hash == new_hash) and not force

    rec = {
        "company": company, "url": url, "final_url": final_url,
        "content_hash": new_hash,
        "last_fetched": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }

    if unchanged:
        rec["last_extracted"] = prev.get("last_extracted")
        rec["last_role_count"] = prev.get("last_role_count", 0)
        state[url] = rec
        return {"company": company, "url": url, "outcome": "unchanged_skipped",
                "detail": "", "roles": prev.get("last_role_count", 0)}

    # Hash changed (or first sight): this is the one case that costs a model
    # call. Everything above this line is free.
    result = extractor.extract(html, final_url)
    text = pagetext.to_text(html)
    extractors.enforce_quotes(result, text)  # second gate, belt and braces

    rec["last_extracted"] = rec["last_fetched"]
    rec["last_role_count"] = len(result.roles)
    state[url] = rec

    if not result.ok:
        return {"company": company, "url": url, "outcome": "extraction_failed",
                "detail": result.error, "roles": 0}

    return {
        "company": company, "url": url, "outcome": "extracted",
        "detail": "", "roles": len(result.roles),
        "discarded_unquoted": result.discarded_unquoted,
        "discarded_titles": result.discarded_titles,
        "prompt_tokens": result.prompt_tokens,
        "completion_tokens": result.completion_tokens,
        "extracted_roles": [r.as_row() for r in result.roles],
        "company_row": company_row,
    }


def _to_lake_row(company: str, role: Dict, source_url: str) -> Dict:
    """Shape a page-reader role like a board posting, so both merge as one lake."""
    verdict = filters.classify(role.get("title") or "", role.get("location") or "")
    return {
        "platform": "page_reader",
        "token": company,
        "job_id": extractors.fixture_key(role.get("apply_url") or
                                         (source_url + role.get("title", ""))),
        "title": role.get("title") or "",
        "location": role.get("location") or "",
        "url": role.get("apply_url") or source_url,
        "posted_on": "",  # a page reader never invents a posting date
        "stage": verdict.stage,
        "technical": verdict.technical,
        "discipline": verdict.discipline,
        "needs_description": verdict.needs_description,
        "location_bucket": verdict.bucket,
        "source_mechanism": "page",
        "company": company,
        "quote": role.get("quote") or "",
        "evidence_lines": role.get("evidence") or {},
        "experience_min_years": role.get("experience_min_years"),
        "experience_max_years": role.get("experience_max_years"),
        "grad_years_accepted": role.get("grad_years_accepted") or [],
        "grad_window_from": role.get("grad_window_from") or "",
        "grad_window_to": role.get("grad_window_to") or "",
        "study_year_min": role.get("study_year_min"),
        "study_year_max": role.get("study_year_max"),
        "degree_ceiling": role.get("degree_ceiling") or "",
        "prerequisite_gate": role.get("prerequisite_gate") or "",
        "remote_tier": role.get("remote_tier") or "",
        "access_channel": role.get("access_channel") or "unknown",
        "stipend_text": role.get("stipend_text") or "",
        "salary_text": role.get("salary_text") or "",
    }


def main() -> None:
    args = sys.argv[1:]
    limit = 0
    only_company: Optional[str] = None
    force = "--force" in args
    if "--limit" in args:
        limit = int(args[args.index("--limit") + 1])
    if "--company" in args:
        only_company = args[args.index("--company") + 1].lower()

    if not os.path.exists(TARGETS):
        print("no {} — run resolve_companies.py first".format(TARGETS))
        raise SystemExit(1)
    targets: List[Dict] = json.load(open(TARGETS))
    targets = [t for t in targets if t.get("mechanism") in ("page", "re_resolve")
              and t.get("careers_url")]
    if only_company:
        targets = [t for t in targets if only_company in (t.get("company") or "").lower()]
    if limit:
        targets = targets[:limit]

    extractor = extractors.get_extractor()
    print("using extractor: {}  ({})".format(
        extractor.name,
        "configured" if getattr(extractor, "available", lambda: True)() else "fallback"))
    print("targets: {}".format(len(targets)))

    state = load_state()
    started = time.time()
    reports = []
    lake_rows: List[Dict] = []

    for i, t in enumerate(targets, 1):
        rep = read_one(t, state, extractor, force=force)
        reports.append(rep)
        for role in rep.get("extracted_roles") or []:
            lake_rows.append(_to_lake_row(rep["company"], role, rep["url"]))
        print("[{}/{}] {:<26} {:<20} roles={} {}".format(
            i, len(targets), (rep["company"] or "")[:26], rep["outcome"],
            rep["roles"], rep.get("detail", "")[:40]))

    save_state(state)

    # Merge into the page-reader lake. Never delete — same rule as sweep.py.
    existing: Dict[str, Dict] = {}
    if os.path.exists(OUT_ROWS):
        try:
            for r in json.load(open(OUT_ROWS)):
                existing[r.get("url") or r.get("job_id")] = r
        except Exception:  # noqa: BLE001
            pass
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for r in lake_rows:
        k = r.get("url") or r.get("job_id")
        if k in existing:
            existing[k].update(r)
            existing[k]["last_seen"] = now
        else:
            r["first_seen"] = now
            r["last_seen"] = now
            r["is_live"] = True
            existing[k] = r
    all_rows = list(existing.values())
    quality.annotate(all_rows, cap=int(os.environ.get("LAKE_COMPANY_CAP", "10")))
    os.makedirs(DATA, exist_ok=True)
    json.dump(all_rows, open(OUT_ROWS, "w"), indent=1)

    outcomes: Dict[str, int] = {}
    for r in reports:
        outcomes[r["outcome"]] = outcomes.get(r["outcome"], 0) + 1
    total_prompt = sum(r.get("prompt_tokens", 0) for r in reports)
    total_completion = sum(r.get("completion_tokens", 0) for r in reports)
    total_discarded = sum(r.get("discarded_unquoted", 0) for r in reports)

    print()
    print("=" * 72)
    print("PAGE READER RUN   ({:.0f}s)".format(time.time() - started))
    print("=" * 72)
    for k, n in sorted(outcomes.items(), key=lambda kv: -kv[1]):
        print("  {:<20} {}".format(k, n))
    print()
    print("  model calls made (outcome=extracted) : {}".format(
        outcomes.get("extracted", 0)))
    print("  roles discarded for missing quote    : {}".format(total_discarded))
    print("  prompt / completion tokens           : {} / {}".format(
        total_prompt, total_completion))
    print("  rows in pagereader lake now           : {}".format(len(all_rows)))
    print()
    print("wrote {} -> {}".format(len(all_rows), OUT_ROWS))
    print("wrote state -> {}".format(STATE))


if __name__ == "__main__":
    main()
