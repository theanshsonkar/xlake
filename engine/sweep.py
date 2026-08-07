"""The sweep. Company-scoped, board-scoped liveness.

Reads data/registry.json — the boards the resolver has already confirmed
answer for a NAMED company (mechanism 1) — fetches each one, filters on title
+ location, runs the hygiene layer, and writes data/jobs.json plus a run
report to data/runs.jsonl.

This deliberately does NOT sweep enumerate_boards.py's raw Common Crawl
universe of thousands of tokens. REGISTRY-PLAN.md section 1 retired that
approach: a board swept with no company context produces roles nobody can
research or trust the identity of. Every row this sweep produces traces back
to a company someone (or resolve_companies.py) actually looked up.

FIXES THE OLD ENGINE'S REAL BUG (oldengine/sweep.py line 133):
    swept = set(swept_platforms)
`swept_platforms` was never defined in that scope — a NameError that meant
this line, and therefore all of _write_jobs()'s liveness logic, never actually
executed in production. The bug was invisible because the function never got
called with real data at scale in that state.

The fix here is not a smaller patch on the same idea — liveness is
BOARD-scoped ((platform, token) pair), not platform-scoped, from the start.
The oldengine's own comment already explains why platform-scoping is wrong:
a LAKE_LIMIT=12 test run against a 311-board platform marked 264 untouched
rows dead, because "platform X was in this run" doesn't mean "board (X, this
particular token) was fetched this run". `boards_read` here is a set of
(platform, token) tuples that were fetched WITHOUT ERROR this run; only rows
whose own board is in that set are eligible to be marked dead if missing.

No AI in this file.

Usage:
    LAKE_LIMIT=20 LAKE_WORKERS=2 python3 sweep.py          # cheap local test
    python3 sweep.py                                       # full sweep, CI
    python3 sweep.py --segment quant                        # one segment
"""

from __future__ import annotations

import collections
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set, Tuple

import filters
import quality
import tiering
from fetch import list_board

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
REGISTRY = os.environ.get("LAKE_REGISTRY", os.path.join(DATA, "registry.json"))
OUT_JOBS = os.path.join(DATA, "jobs.json")
OUT_HIDDEN = os.path.join(DATA, "hidden.json")
OUT_RUNS = os.path.join(DATA, "runs.jsonl")

WORKERS = int(os.environ.get("LAKE_WORKERS", "4"))
# Sweep only the first N registry entries. Local testing should never need the
# whole registry — verify the logic on a handful, run the real thing on CI.
LIMIT = int(os.environ.get("LAKE_LIMIT", "0"))  # 0 = no limit
IGNORE_TIERS = os.environ.get("LAKE_IGNORE_TIERS", "") == "1"
TIER_STATE_PATH = os.environ.get("LAKE_TIER_STATE", "") or None

# Maximum rows one company may surface. Same measured reason as the old
# engine: a single high-volume poster can dominate the lake. Kept even though
# the new registry is small — a company-scoped registry can still resolve to
# a board (e.g. a big-tech Workday tenant) that posts hundreds of roles.
COMPANY_CAP = int(os.environ.get("LAKE_COMPANY_CAP", "10"))


def is_sweepable(entry: Dict) -> bool:
    """False only for boards that can never work; absent key means sweepable."""
    return bool(entry.get("reachable", True))


def is_due(entry: Dict, state: Dict, now=None, ignore: Optional[bool] = None) -> bool:
    """Freshness gate. Unmeasured boards are always due, so an empty tier
    state sweeps everything. Separate from is_sweepable, which permanently
    excludes boards that can never work."""
    if IGNORE_TIERS if ignore is None else ignore:
        return True
    history = state.get("{}|{}".format(entry["platform"], entry["token"]))
    if history is None:
        return True
    return tiering.sweep_due(history, now)


def load_registry(segment: str = None) -> List[Dict]:
    if not os.path.exists(REGISTRY):
        return []
    rows = json.load(open(REGISTRY))
    if segment:
        rows = [r for r in rows if r.get("segment") == segment]
    excluded = len(rows)
    rows = [r for r in rows if is_sweepable(r)]
    excluded -= len(rows)
    if excluded:
        print("skipped {} unreachable registry entries".format(excluded))
    return rows


def _key(r: Dict) -> str:
    """Identity of an opportunity: its official URL, normalised."""
    u = (r.get("url") or "").strip().rstrip("/").lower()
    if u:
        return u
    return "{}|{}|{}".format(r.get("platform"), r.get("token"), r.get("title"))


def _store_identity(r: Dict) -> Tuple[str, str, str]:
    """Stable board identity used to reconcile the two canonical stores."""
    return (r.get("platform"), r.get("token"), r.get("job_id"))


def _reconcile_jobs_with_hidden(hidden_rows: List[Dict],
                                jobs_path: str = OUT_JOBS,
                                jobs_rows: List[Dict] = None) -> int:
    """Mark kept rows rejected by this run as hidden, without deleting them."""
    rejected = {
        _store_identity(r): r for r in hidden_rows
        if all(_store_identity(r))
    }
    if not rejected:
        return 0

    if jobs_rows is None:
        if not os.path.exists(jobs_path):
            return 0
        try:
            jobs_rows = json.load(open(jobs_path))
        except Exception:
            return 0

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    reconciled = 0
    for row in jobs_rows:
        hidden = rejected.get(_store_identity(row))
        if hidden is None:
            continue
        # Classification rules change over time: an identity can move from
        # kept to rejected, so the kept store must record that disagreement.
        row["hidden_reason"] = hidden["hidden_reason"]
        row["eligibility_status"] = filters.ELIG_HIDDEN
        row["reconciled_at"] = now
        reconciled += 1

    if reconciled:
        os.makedirs(os.path.dirname(jobs_path) or ".", exist_ok=True)
        tmp = jobs_path + ".tmp"
        json.dump(jobs_rows, open(tmp, "w"), indent=1)
        os.replace(tmp, jobs_path)
    return reconciled


def _dedupe(rows: List[Dict]) -> List[Dict]:
    seen: Set[str] = set()
    unique = []
    for r in rows:
        k = _key(r)
        if k in seen:
            continue
        seen.add(k)
        unique.append(r)
    return unique


def _merge_store(path: str, rows: List[Dict],
                 boards_read: Set[Tuple[str, str]]) -> List[Dict]:
    """Merge one canonical store with board-scoped liveness.

    A row seen again updates last_seen. A row that has disappeared from a
    board we actually READ WITHOUT ERROR this run is marked is_live=false but
    KEPT, so a dead posting never resurfaces later as new, and history
    survives. The same merge is used for public rows and private rejects.
    """
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    lake: Dict[str, Dict] = {}
    if os.path.exists(path):
        try:
            for r in json.load(open(path)):
                lake[_key(r)] = r
        except Exception:
            pass  # corrupt file: rebuild rather than crash

    found_now: Set[str] = set()
    for r in _dedupe(rows):
        k = _key(r)
        found_now.add(k)
        if k in lake:
            existing = lake[k]
            existing.update({
                "title": r["title"],
                "location": r["location"],
                "posted_on": r.get("posted_on", existing.get("posted_on", "")),
                "description": r.get("description") or existing.get("description"),
                "stage": r["stage"],
                "stage_title": r.get("stage_title", existing.get("stage_title", r["stage"])),
                "technical": r["technical"],
                "discipline": r["discipline"],
                "needs_description": r.get("needs_description", existing.get("needs_description", False)),
                "stage_resolved": r["stage_resolved"],
                "experience_min": r["experience_min"],
                "experience_max": r["experience_max"],
                "experience_conflict": r.get("experience_conflict", existing.get("experience_conflict", False)),
                "batch_years": r.get("batch_years", existing.get("batch_years", [])),
                "degree_required": r.get("degree_required", existing.get("degree_required", [])),
                "enrolled_required": r.get("enrolled_required", existing.get("enrolled_required")),
                "eligibility_evidence": r["eligibility_evidence"],
                "gates_found": r.get("gates_found", existing.get("gates_found", [])),
                "gates_missing": r.get("gates_missing", existing.get("gates_missing", filters.ELIGIBILITY_GATES)),
                "eligibility_status": r.get("eligibility_status", existing.get("eligibility_status", filters.ELIG_RULES_UNCLEAR)),
                "hidden_reason": r["hidden_reason"],
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

    # Liveness: board-scoped, per the fix above. Only a row whose OWN
    # (platform, token) pair was actually read this run is eligible to be
    # marked dead if it did not reappear.
    disappeared = 0
    for k, r in lake.items():
        if k in found_now:
            continue
        board = (r.get("platform"), r.get("token"))
        if board in boards_read and r.get("is_live", True):
            r["is_live"] = False
            r["went_dead_at"] = now
            disappeared += 1

    out = list(lake.values())

    # Set-level hygiene runs over the WHOLE lake, not just this run's rows,
    # because "is this company over its cap" and "is this a duplicate" are
    # questions about the set.
    quality.annotate(out, cap=COMPANY_CAP)

    os.makedirs(DATA, exist_ok=True)
    tmp = path + ".tmp"
    json.dump(out, open(tmp, "w"), indent=1)
    os.replace(tmp, path)  # atomic; never a half-written lake
    print("   lake: {} rows total, {} live, {} surfaced, {} newly dead".format(
        len(out), sum(1 for r in out if r.get("is_live")),
        sum(1 for r in out if r.get("surfaced")), disappeared))
    return out


def _write_jobs(rows: List[Dict], boards_read: Set[Tuple[str, str]]) -> List[Dict]:
    """Merge this run's public finds into jobs.json."""
    return _merge_store(OUT_JOBS, rows, boards_read)


def sweep(entries: List[Dict], workers: int = WORKERS) -> Dict:
    started = time.time()
    rows: List[Dict] = []
    hidden_rows: List[Dict] = []
    boards_read: Set[Tuple[str, str]] = set()
    tier_state = tiering.load_tier_state()

    stats: Dict[str, Dict] = {"_total": {
        "boards": 0, "ok": 0, "empty": 0, "failed": 0, "truncated": 0,
        "postings": 0, "kept": 0,
    }}
    fails: collections.Counter = collections.Counter()
    filtered_out: collections.Counter = collections.Counter()
    board_qualifying: Dict[Tuple[str, str], int] = collections.defaultdict(int)

    print("sweeping {} registry entries...".format(len(entries)))

    def _fetch(entry: Dict):
        return entry, list_board(entry["platform"], entry["token"])

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = [pool.submit(_fetch, e) for e in entries]
        done = 0
        for fut in as_completed(futs):
            done += 1
            entry, r = fut.result()
            board = (entry["platform"], entry["token"])
            s = stats["_total"]
            s["boards"] += 1

            if r.error:
                s["failed"] += 1
                fails[r.error[:40]] += 1
                # A failed read does NOT enter boards_read — this is the whole
                # point of board-scoped liveness. A board we failed to reach
                # must not be treated as "read and found nothing".
                continue

            if r.truncated:
                s["truncated"] += 1
            else:
                # The trust contract excludes truncated reads from liveness.
                boards_read.add(board)
            if r.count == 0:
                s["empty"] += 1
                tiering.record_sweep(tier_state, entry["platform"], entry["token"],
                                      qualifying_count=0)
                continue
            s["ok"] += 1
            s["postings"] += r.count

            kept_this_board = 0
            for p in r.postings:
                v = filters.classify(p.title, p.location)
                resolution = filters.resolve_stage(v.stage, p.description, p.title)
                gates_found, gates_missing = filters.gates_of(
                    resolution, v.stage, p.title)
                if not v.keep:
                    reason = filters.canonical_reason(v.reason)
                    filtered_out[reason] += 1
                    hidden_rows.append({
                        "platform": p.platform,
                        "token": p.token,
                        "job_id": p.job_id,
                        "title": p.title,
                        "url": p.url,
                        "location": p.location,
                        "company_name": entry.get("company"),
                        "segment": entry.get("segment"),
                        "stage": v.stage,
                        "stage_title": v.stage,
                        "stage_resolved": resolution.stage_resolved,
                        "technical": v.technical,
                        "discipline": v.discipline,
                        "location_bucket": v.bucket,
                        "experience_min": resolution.experience_min,
                        "experience_max": resolution.experience_max,
                        "experience_conflict": resolution.experience_conflict,
                        "batch_years": resolution.batch_years,
                        "degree_required": resolution.degree_required,
                        "enrolled_required": resolution.enrolled_required,
                        "eligibility_evidence": resolution.evidence,
                        "gates_found": gates_found,
                        "gates_missing": gates_missing,
                        "eligibility_status": filters.ELIG_HIDDEN,
                        "hidden_reason": reason,
                        "source_mechanism": "board",
                    })
                    continue
                row_hidden_reason = filters.hidden_reason(
                    resolution.stage_resolved, v.bucket, v.technical,
                    resolution.experience_min, v.discipline)
                row_eligibility_status = filters.eligibility_status(
                    row_hidden_reason, gates_found)
                s["kept"] += 1
                kept_this_board += 1
                rows.append({
                    "platform": p.platform,
                    "token": p.token,
                    "job_id": p.job_id,
                    "title": p.title,
                    "location": p.location,
                    "url": p.url,
                    "posted_on": p.posted_on,
                    "description": p.description,
                    "company_name": entry.get("company"),
                    "segment": entry.get("segment"),
                    "stage": v.stage,
                    "stage_title": v.stage,
                    "stage_resolved": resolution.stage_resolved,
                    "experience_min": resolution.experience_min,
                    "experience_max": resolution.experience_max,
                    "experience_conflict": resolution.experience_conflict,
                    "batch_years": resolution.batch_years,
                    "degree_required": resolution.degree_required,
                    "enrolled_required": resolution.enrolled_required,
                    "eligibility_evidence": resolution.evidence,
                    "gates_found": gates_found,
                    "gates_missing": gates_missing,
                    "eligibility_status": row_eligibility_status,
                    "hidden_reason": row_hidden_reason,
                    "technical": v.technical,
                    "discipline": v.discipline,
                    "needs_description": v.needs_description,
                    "location_bucket": v.bucket,
                    "source_mechanism": "board",
                })
            board_qualifying[board] += kept_this_board
            tiering.record_sweep(tier_state, entry["platform"], entry["token"],
                                  qualifying_count=kept_this_board)
            if done % 5 == 0 or done == len(entries):
                print("   {}/{}  postings={}  kept={}".format(
                    done, len(entries), s["postings"], s["kept"]))

    unique = _write_jobs(rows, boards_read)
    unique_hidden = _merge_store(OUT_HIDDEN, hidden_rows, boards_read)
    store_reconciled = _reconcile_jobs_with_hidden(
        hidden_rows, jobs_path=OUT_JOBS, jobs_rows=unique)
    tiering.save_tier_state(tier_state)

    report = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "seconds": round(time.time() - started, 1),
        "entries_swept": len(entries),
        "boards_read_ok": len(boards_read),
        "totals": stats["_total"],
        "failure_modes": dict(fails.most_common(10)),
        "kept_total": len(unique),
        "store_reconciled": store_reconciled,
        "by_stage": dict(collections.Counter(r["stage"] for r in unique)),
        "by_bucket": dict(collections.Counter(r["location_bucket"] for r in unique)),
        "technical": sum(1 for r in unique if r["technical"] is True),
        "non_technical": sum(1 for r in unique if r["technical"] is False),
        "unclassified": sum(1 for r in unique if r["technical"] is None),
        "filtered_out": {
            "total": sum(filtered_out.values()),
            "by_reason": dict(filtered_out),
        },
        "hidden": {
            "total": sum(1 for r in unique if r.get("hidden_reason") is not None),
            "by_reason": dict(collections.Counter(
                r["hidden_reason"] for r in unique
                if r.get("hidden_reason") is not None)),
        },
        "visible_total": sum(1 for r in unique
                              if r.get("hidden_reason") is None),
        "by_stage_resolved": dict(collections.Counter(
            r["stage_resolved"] for r in unique)),
        "stage_resolved_changed": sum(
            1 for r in unique if r["stage_resolved"] != r["stage"]),
        "experience_stated": sum(
            1 for r in unique if r.get("experience_min") is not None),
        "experience_conflicts": sum(
            1 for r in unique if r.get("experience_conflict") is True),
        "by_eligibility_status": dict(collections.Counter(
            r["eligibility_status"] for r in unique)),
        "worth_checking_total": sum(
            1 for r in unique
            if r.get("eligibility_status") == filters.ELIG_RULES_UNCLEAR),
    }

    india = [r for r in unique
             if r["location_bucket"] in (filters.INDIA_LOCATED, filters.INDIA_REMOTE)]
    report["india_early_career"] = len(india)
    report["india_early_career_technical"] = sum(
        1 for r in india if r["technical"] is True)
    report["quality"] = quality.report(unique)

    os.makedirs(DATA, exist_ok=True)
    with open(OUT_RUNS, "a") as fh:
        fh.write(json.dumps(report) + "\n")
    return report


def main() -> None:
    args = sys.argv[1:]
    segment = None
    list_selection = "--list-selection" in args
    if "--segment" in args:
        segment = args[args.index("--segment") + 1]

    # Bare positional arguments are platform names; the segment value is not
    # itself a positional platform argument.
    positional = [
        arg for i, arg in enumerate(args)
        if not arg.startswith("--")
        and (i == 0 or args[i - 1] != "--segment")
    ]
    all_entries = load_registry()
    valid_platforms = sorted({r.get("platform") for r in all_entries
                               if r.get("platform")})
    if positional:
        invalid = sorted(set(positional) - set(valid_platforms))
        if invalid:
            print("unknown platform(s): {}\nvalid platforms: {}".format(
                ", ".join(invalid), ", ".join(valid_platforms) or "(none)"),
                file=sys.stderr)
            sys.exit(2)

    entries = load_registry(segment)
    if positional:
        entries = [r for r in entries if r.get("platform") in positional]
    tier_state = tiering.load_tier_state(TIER_STATE_PATH) if TIER_STATE_PATH else tiering.load_tier_state()
    before_due = len(entries)
    entries = [r for r in entries if is_due(r, tier_state)]
    if before_due - len(entries):
        print("skipped {} boards not due".format(before_due - len(entries)))
    if LIMIT:
        entries = entries[:LIMIT]

    if list_selection:
        for entry in entries:
            print("{}|{}".format(entry["platform"], entry["token"]))
        sys.exit(0)

    if not entries:
        print("data/registry.json has no entries{} — nothing to sweep. "
              "Run resolve_companies.py first.".format(
                  " for segment={}".format(segment) if segment else ""))
        sys.exit(1)

    rep = sweep(entries)

    print("\n" + "=" * 72)
    print("SWEEP REPORT   {}   ({}s)".format(rep["ts"], rep["seconds"]))
    print("=" * 72)
    t = rep["totals"]
    print("boards: {}  ok={} empty={} failed={} truncated={}".format(
        t["boards"], t["ok"], t["empty"], t["failed"], t["truncated"]))
    print("postings seen : {}".format(t["postings"]))
    print("kept (pre-dedupe) : {}".format(t["kept"]))
    print("boards read without error (liveness-eligible) : {}".format(
        rep["boards_read_ok"]))

    print("\nearly-career kept (deduped) : {}".format(rep["kept_total"]))
    print("  by stage                  : {}".format(rep["by_stage"]))
    print("  by location bucket        : {}".format(rep["by_bucket"]))
    print("  technical / non / unknown : {} / {} / {}".format(
        rep["technical"], rep["non_technical"], rep["unclassified"]))
    print("  india early-career         : {}  (technical: {})".format(
        rep["india_early_career"], rep["india_early_career_technical"]))

    if rep["failure_modes"]:
        print("\nfailure modes:")
        for k, n in rep["failure_modes"].items():
            print("  {:<40} {}".format(k, n))

    q = rep["quality"]
    print("\nhygiene (flagged, never deleted)")
    print("  staffing agencies         : -{}".format(q["removed_recruiter"]))
    print("  duplicate titles          : -{}".format(q["removed_duplicate"]))
    print("  over per-company cap      : -{}".format(q["removed_over_cap"]))
    print("  stale (>{} days)          : -{}".format(
        quality.STALE_DAYS, q.get("removed_stale", 0)))
    print("  pay-to-intern             : -{}".format(q.get("removed_pay_to_intern", 0)))
    print("  surfaced                  : {} rows across {} companies".format(
        q["surfaced"], q["companies_surfaced"]))


if __name__ == "__main__":
    main()
