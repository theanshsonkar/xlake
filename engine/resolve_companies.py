"""Run the resolver over the known-company list and report the mechanism split.

This produces the one number that sets the AI budget: how many of the ~150
companies a student asks about by name can be read for free from a board API,
and how many need a model to read their careers page.

    python3 resolve_companies.py                 # all of them
    python3 resolve_companies.py --segment quant # one segment
    python3 resolve_companies.py --limit 20      # a cheap smoke test

Writes data/registry.json (mechanism 1 boards, ready for the sweep) and
data/pagereader_targets.json (mechanism 2 queue). Both are rewritten in full,
because a resolution is a current fact about a company, not history.

No AI in this file.
"""

from __future__ import annotations

import collections
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import resolve

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
COMPANIES = os.path.join(DATA, "companies.txt")
OUT_REGISTRY = os.path.join(DATA, "registry.json")
OUT_PAGEREADER = os.path.join(DATA, "pagereader_targets.json")

WORKERS = int(os.environ.get("LAKE_WORKERS", "8"))


def load_companies(path: str = COMPANIES) -> List[Tuple[str, str, str]]:
    out: List[Tuple[str, str, str]] = []
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 2 or not parts[1]:
                continue
            name, domain = parts[0], parts[1]
            segment = parts[2] if len(parts) > 2 else "unsorted"
            out.append((name, domain, segment))
    return out


def classify_mechanism(r: resolve.Resolution) -> Tuple[str, str]:
    """(mechanism, reason) for one resolution.

    Four outcomes, and the distinction between the last two is the point:

      board        a readable platform with a token that actually answered
      page         no readable board — the page reader has to do it
      re_resolve   we found a token and it does NOT answer. NOT the same as a
                   company that is not hiring. `ashby:vercel` returned 200 with
                   an empty list forever while Vercel's real board was on
                   Greenhouse, so a dead token must be re-read from the careers
                   page rather than swept forever.
      unreachable  the careers page itself could not be fetched
    """
    if r.platform in resolve.READABLE and r.token:
        if r.state == "verified":
            return "board", "verified_{}_jobs".format(r.verify_jobs)
        if r.state == "empty":
            # 200-with-zero is a real state, not a failure. Kept on mechanism 1;
            # the sweep counts consecutive empties and re-resolves after N.
            return "board", "empty_but_live"
        return "re_resolve", "token_did_not_answer_{}".format(r.verify_error or "")
    # These are all "no board", but they are NOT the same problem and must not be
    # reported as one. A wrong domain in our own list, a site that blocks us, and
    # a company with a JS-only careers page need three different fixes.
    if r.error == "domain_does_not_resolve":
        return "unreachable", "domain_does_not_resolve_FIX_COMPANIES_TXT"
    if r.error == "bot_blocked":
        return "page", "bot_blocked_403"
    if r.error == "careers_path_redirects_to_homepage":
        return "page", "careers_path_redirects_to_homepage"
    if r.error == "no_careers_page_found":
        return "unreachable", "no_careers_page_found"
    if r.platform in resolve.UNREADABLE:
        return "page", "on_{}_not_machine_readable".format(r.platform)
    return "page", "no_ats_detected"


def main() -> None:
    args = sys.argv[1:]
    segment: Optional[str] = None
    limit = 0
    if "--segment" in args:
        segment = args[args.index("--segment") + 1]
    if "--limit" in args:
        limit = int(args[args.index("--limit") + 1])

    companies = load_companies()
    if segment:
        companies = [c for c in companies if c[2] == segment]
    if limit:
        companies = companies[:limit]

    print("resolving {} companies with {} workers...".format(len(companies), WORKERS))
    started = time.time()

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        results = list(
            pool.map(lambda c: resolve.resolve_and_verify(c[0], c[1]), companies)
        )

    rows: List[Dict] = []
    for (name, domain, seg), r in zip(companies, results):
        mech, reason = classify_mechanism(r)
        rows.append({
            "company": name,
            "domain": domain,
            "segment": seg,
            "mechanism": mech,
            "reason": reason,
            "platform": r.platform,
            "token": r.token,
            "state": r.state,
            "verify_jobs": r.verify_jobs,
            "verify_status": r.verify_status,
            "verify_error": r.verify_error,
            "careers_url": r.careers_url,
            "evidence": r.evidence,
            "resolved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        })

    # --- per-company detail ------------------------------------------------ #
    print()
    print("{:<26} {:<10} {:<16} {:<26} {:>6}".format(
        "company", "mechanism", "platform", "token", "jobs"))
    print("-" * 92)
    for row in sorted(rows, key=lambda x: (x["mechanism"], x["segment"], x["company"])):
        print("{:<26} {:<10} {:<16} {:<26} {:>6}".format(
            row["company"][:26],
            row["mechanism"],
            (row["platform"] or "-")[:16],
            (row["token"] or "-")[:26],
            row["verify_jobs"] if row["verify_jobs"] is not None else "-",
        ))

    # --- the split --------------------------------------------------------- #
    mech = collections.Counter(r["mechanism"] for r in rows)
    total = len(rows)
    board_rows = [r for r in rows if r["mechanism"] == "board"]
    postings = sum(r["verify_jobs"] or 0 for r in board_rows)

    print()
    print("=" * 72)
    print("MECHANISM SPLIT over {} known companies   ({:.0f}s)".format(
        total, time.time() - started))
    print("=" * 72)
    for k in ("board", "page", "re_resolve", "unreachable"):
        n = mech.get(k, 0)
        print("  {:<12} {:>4}  ({:>5.1f}%)".format(
            k, n, 100.0 * n / total if total else 0.0))
    print()
    print("  postings reachable for free right now : {}".format(postings))
    print("  companies needing a model to read     : {}".format(
        mech.get("page", 0) + mech.get("unreachable", 0)))

    print()
    print("  by segment:")
    print("  {:<16} {:>6} {:>6} {:>6} {:>6} {:>10}".format(
        "segment", "board", "page", "requ", "unrch", "postings"))
    by_seg: Dict[str, collections.Counter] = collections.defaultdict(
        collections.Counter)
    seg_postings: Dict[str, int] = collections.defaultdict(int)
    for r in rows:
        by_seg[r["segment"]][r["mechanism"]] += 1
        seg_postings[r["segment"]] += r["verify_jobs"] or 0
    for seg in sorted(by_seg):
        c = by_seg[seg]
        print("  {:<16} {:>6} {:>6} {:>6} {:>6} {:>10}".format(
            seg, c["board"], c["page"], c["re_resolve"], c["unreachable"],
            seg_postings[seg]))

    print()
    print("  platforms found:")
    for p, n in collections.Counter(
            r["platform"] or "none" for r in rows).most_common():
        print("    {:<18} {}".format(p, n))

    # --- write ------------------------------------------------------------- #
    os.makedirs(DATA, exist_ok=True)
    registry = [
        {"platform": r["platform"], "token": r["token"], "company": r["company"],
         "segment": r["segment"], "source": "resolver", "evidence": r["evidence"]}
        for r in board_rows
    ]
    with open(OUT_REGISTRY, "w") as fh:
        json.dump(registry, fh, indent=1)
    targets = [r for r in rows if r["mechanism"] in ("page", "unreachable", "re_resolve")]
    with open(OUT_PAGEREADER, "w") as fh:
        json.dump(targets, fh, indent=1)

    print()
    print("wrote {} boards      -> {}".format(len(registry), OUT_REGISTRY))
    print("wrote {} page targets -> {}".format(len(targets), OUT_PAGEREADER))


if __name__ == "__main__":
    main()
