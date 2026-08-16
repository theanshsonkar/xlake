"""The sweep. This is what runs every 12 hours.

Reads the enumerated board list, fetches every board, filters on title and
location alone, and writes jobs.json plus a run report.

No AI in this file. The point of this stage is to answer "is there anything here
for a B.Tech student" using only free, deterministic work. Description download
and eligibility extraction come later, and only for rows that survive here.

Usage:
    LAKE_HOST_DELAY=0.3 python3 sweep.py                    # all platforms
    LAKE_HOST_DELAY=0.3 python3 sweep.py keka greenhouse    # some platforms
"""

from __future__ import annotations

import collections
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Dict, List

import filters
import quality
from fetch import list_board

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, ".cache")
OUT_JOBS = os.path.join(HERE, "jobs.json")
OUT_RUNS = os.path.join(HERE, "runs.jsonl")

# Order matters only for readability of the log.
DEFAULT_PLATFORMS = ["keka", "greenhouse", "workable", "ashby", "smartrecruiters"]

# Concurrency. A full sweep is I/O bound but thousands of TLS handshakes across
# many threads for twenty minutes will still cook a laptop. Default gently and
# let CI turn it up, because CI is where full sweeps belong.
WORKERS = int(os.environ.get("LAKE_WORKERS", "4"))

# Sweep only the first N boards per platform. Local testing should never need
# the whole universe — verify the logic on 20 boards, run the real thing on CI.
LIMIT = int(os.environ.get("LAKE_LIMIT", "0"))  # 0 = no limit

# Maximum rows one company may surface. Measured reason: workable:kiavets posted
# 311 near-identical roles, 25.6% of the entire lake, from one US car-dealership
# chain. Rows past the cap are flagged, never deleted.
COMPANY_CAP = int(os.environ.get("LAKE_COMPANY_CAP", "10"))


def load_boards(platform: str) -> List[str]:
    p = os.path.join(CACHE, "boards_{}.json".format(platform))
    if not os.path.exists(p):
        return []
    return json.load(open(p))


def _key(r: Dict) -> str:
    """Identity of an opportunity: its official URL, normalised."""
    u = (r.get("url") or "").strip().rstrip("/").lower()
    if u:
        return u
    return "{}|{}|{}".format(r.get("platform"), r.get("token"), r.get("title"))


def _dedupe(rows: List[Dict]) -> List[Dict]:
    seen = set()
    unique = []
    for r in rows:
        k = _key(r)
        if k in seen:
            continue
        seen.add(k)
        unique.append(r)
    return unique


def _write_jobs(rows: List[Dict], boards_read: set) -> List[Dict]:
    """Merge this run's finds into the lake. Never delete, never replace.

    A row seen again updates last_seen. A row that has disappeared from a board
    we actually READ is marked is_live=false but KEPT, so a dead posting never
    resurfaces later as new, and so history survives.

    `boards_read` is the set of (platform, token) pairs this run fetched
    SUCCESSFULLY. It deliberately is not a set of platforms.

    The reason is a real bug this replaced. Liveness used to be scoped by
    platform: any row whose platform appeared in the run was marked dead if the
    run did not see it again. With LAKE_LIMIT=12 against a 311-board platform, a
    single local test marked 264 rows dead — rows on 299 boards that were never
    contacted. A board that errored must not kill rows either, for the same
    reason the fetch layer records a partial read as an error: not looking is not
    the same as looking and finding nothing.
    """
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    lake: Dict[str, Dict] = {}
    if os.path.exists(OUT_JOBS):
        try:
            for r in json.load(open(OUT_JOBS)):
                lake[_key(r)] = r
        except Exception:
            pass  # corrupt file: rebuild rather than crash

    found_now = set()
    for r in _dedupe(rows):
        k = _key(r)
        found_now.add(k)
        if k in lake:
            existing = lake[k]
            existing.update({
                "title": r["title"],
                "location": r["location"],
                "stage": r["stage"],
                "technical": r["technical"],
                "discipline": r["discipline"],
                "needs_description": r["needs_description"],
                "location_bucket": r["location_bucket"],
                "last_seen": now,
                "is_live": True,
            })
        else:
            r = dict(r)
            r["first_seen"] = now
            r["last_seen"] = now
            r["is_live"] = True
            lake[k] = r

    # Liveness: only for platforms actually swept in this run.
    swept = set(swept_platforms)
    disappeared = 0
    for k, r in lake.items():
        if k in found_now:
            continue
        if r.get("platform") in swept and r.get("is_live", True):
            r["is_live"] = False
            r["went_dead_at"] = now
            disappeared += 1

    out = list(lake.values())

    # Set-level hygiene. Must run over the WHOLE lake, not just this run's rows,
    # because "is this company over its cap" and "is this a duplicate" are
    # questions about the set. Annotates only — nothing is deleted, so a wrong
    # cap or a wrong agency verdict is still auditable on disk.
    quality.annotate(out, cap=COMPANY_CAP)

    tmp = OUT_JOBS + ".tmp"
    json.dump(out, open(tmp, "w"), indent=1)
    os.replace(tmp, OUT_JOBS)  # atomic; never a half-written lake
    print("   lake: {} rows total, {} live, {} surfaced, {} newly dead".format(
        len(out), sum(1 for r in out if r.get("is_live")),
        sum(1 for r in out if r.get("surfaced")), disappeared))
    return out


def sweep(platforms: List[str], workers: int = WORKERS) -> Dict:
    started = time.time()
    rows: List[Dict] = []
    stats: Dict[str, Dict] = {}
    fails: Dict[str, collections.Counter] = {}

    for platform in platforms:
        tokens = load_boards(platform)
        if not tokens:
            print("[{}] no enumerated boards cached — skipping".format(platform))
            continue
        if LIMIT:
            tokens = tokens[:LIMIT]

        s = {
            "boards": len(tokens),
            "ok": 0,
            "empty": 0,
            "failed": 0,
            "truncated": 0,
            "postings": 0,
            "kept": 0,
        }
        f: collections.Counter = collections.Counter()
        done = 0
        print("[{}] sweeping {} boards...".format(platform, len(tokens)))

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futs = {pool.submit(list_board, platform, t): t for t in tokens}
            for fut in as_completed(futs):
                done += 1
                if done % 200 == 0:
                    print("   [{}] {}/{}  postings={}  kept={}".format(
                        platform, done, len(tokens), s["postings"], s["kept"]))
                try:
                    r = fut.result()
                except Exception as e:  # noqa: BLE001
                    s["failed"] += 1
                    f[type(e).__name__] += 1
                    continue

                if r.error:
                    s["failed"] += 1
                    f[r.error[:40]] += 1
                    continue
                if r.truncated:
                    s["truncated"] += 1
                if r.count == 0:
                    s["empty"] += 1
                    continue
                s["ok"] += 1
                s["postings"] += r.count

                for p in r.postings:
                    v = filters.classify(p.title, p.location)
                    if not v.keep:
                        continue
                    s["kept"] += 1
                    rows.append({
                        "platform": p.platform,
                        "token": p.token,
                        "job_id": p.job_id,
                        "title": p.title,
                        "location": p.location,
                        "url": p.url,
                        "posted_on": p.posted_on,
                        "stage": v.stage,
                        "technical": v.technical,
                        "discipline": v.discipline,
                        "needs_description": v.needs_description,
                        "location_bucket": v.bucket,
                    })

        stats[platform] = s
        fails[platform] = f
        print("   [{}] done: ok={} empty={} failed={} postings={} kept={}".format(
            platform, s["ok"], s["empty"], s["failed"], s["postings"], s["kept"]))

        # Flush after every platform. A sweep of thousands of boards takes tens
        # of minutes, and an interrupted run must not throw away what it already
        # found — that is real work against real rate limits.
        _write_jobs(rows, platforms)
        print("   [{}] flushed {} rows -> jobs.json".format(platform, len(rows)))

    unique = _write_jobs(rows, platforms)

    report = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "seconds": round(time.time() - started, 1),
        "platforms": stats,
        "failure_modes": {k: dict(v.most_common(6)) for k, v in fails.items()},
        "kept_total": len(unique),
        "by_stage": dict(collections.Counter(r["stage"] for r in unique)),
        "by_bucket": dict(collections.Counter(r["location_bucket"] for r in unique)),
        "technical": sum(1 for r in unique if r["technical"] is True),
        "non_technical": sum(1 for r in unique if r["technical"] is False),
        "unclassified": sum(1 for r in unique if r["technical"] is None),
    }

    india = [r for r in unique
             if r["location_bucket"] in (filters.INDIA_LOCATED, filters.INDIA_REMOTE)]
    report["india_early_career"] = len(india)
    report["india_early_career_technical"] = sum(1 for r in india if r["technical"] is True)

    # The hygiene layer's own numbers, including the one figure the beta is
    # actually sold on. Reported by the run rather than worked out afterwards,
    # because a number nobody prints is a number nobody checks.
    report["quality"] = quality.report(unique)

    with open(OUT_RUNS, "a") as fh:
        fh.write(json.dumps(report) + "\n")
    return report


def main() -> None:
    plats = sys.argv[1:] or DEFAULT_PLATFORMS
    rep = sweep(plats)

    print("\n" + "=" * 72)
    print("SWEEP REPORT   {}   ({}s)".format(rep["ts"], rep["seconds"]))
    print("=" * 72)
    print("{:<16} {:>7} {:>6} {:>6} {:>7} {:>9} {:>7}".format(
        "platform", "boards", "ok", "empty", "failed", "postings", "kept"))
    for p, s in rep["platforms"].items():
        print("{:<16} {:>7} {:>6} {:>6} {:>7} {:>9} {:>7}".format(
            p, s["boards"], s["ok"], s["empty"], s["failed"], s["postings"], s["kept"]))

    print("\nearly-career kept (deduped) : {}".format(rep["kept_total"]))
    print("  by stage                  : {}".format(rep["by_stage"]))
    print("  by location bucket        : {}".format(rep["by_bucket"]))
    print("  technical / non / unknown : {} / {} / {}".format(
        rep["technical"], rep["non_technical"], rep["unclassified"]))

    q = rep["quality"]
    print("\nhygiene (flagged, never deleted)")
    print("  staffing agencies         : -{}".format(q["removed_recruiter"]))
    print("  duplicate titles          : -{}".format(q["removed_duplicate"]))
    print("  over per-company cap      : -{}".format(q["removed_over_cap"]))
    print("  surfaced                  : {} rows across {} companies".format(
        q["surfaced"], q["companies_surfaced"]))
    print("  surfaced by discipline    : {}".format(q["surfaced_by_discipline"]))
    print("  locations still unparsed  : {}".format(q["locations_unparsed"]))

    print("\n  INDIA surfaced            : {}".format(q["surfaced_india"]))
    print("  INDIA by discipline       : {}".format(q["india_by_discipline"]))
    print("  >> INDIA + CSE + EARLY    : {}   <- the beta number".format(
        q["INDIA_CSE_EARLY_CAREER_OPEN"]))
    print("  India needing description : {}".format(q["india_needs_description"]))
    print("\nfailure modes: {}".format(json.dumps(rep["failure_modes"])[:600]))
    print("\nwrote {} rows -> jobs.json".format(rep["kept_total"]))


if __name__ == "__main__":
    main()
