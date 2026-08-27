"""The sweep. Company-scoped, board-scoped liveness.

Reads `data/operations/registry.json` — boards the resolver has already
confirmed for a named company — fetches each one, filters on title and
location, runs the hygiene layer, and writes the canonical lake stores under
`data/lake/` plus an operational report under `data/operations/`.

This does not sweep the raw Common Crawl discovery universe. Every row traces
back to a company someone or the resolver actually looked up.

The board-scoped liveness behavior supersedes the historical implementation
preserved in `archive/opportunity-lake-oldengine-2026-08-16/`; uncertain reads
never establish closure.

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
from typing import Dict, List, Set, Tuple

from core import filters, quality, tiering
from core.paths import (
    DATA_ROOT, HIDDEN_PATH, OPPORTUNITIES_PATH, REGISTRY_PATH, RUNS_PATH,
)
from adapters.boards import list_board

DATA = DATA_ROOT
REGISTRY = os.environ.get("LAKE_REGISTRY", REGISTRY_PATH)
OUT_JOBS = OPPORTUNITIES_PATH
OUT_HIDDEN = HIDDEN_PATH
OUT_RUNS = RUNS_PATH

WORKERS = int(os.environ.get("LAKE_WORKERS", "4"))
# Sweep only the first N registry entries. Local testing should never need the
# whole registry — verify the logic on a handful, run the real thing on CI.
LIMIT = int(os.environ.get("LAKE_LIMIT", "0"))  # 0 = no limit

# Maximum rows one company may surface. Same measured reason as the old
# engine: a single high-volume poster can dominate the lake. Kept even though
# the new registry is small — a company-scoped registry can still resolve to
# a board (e.g. a big-tech Workday tenant) that posts hundreds of roles.
COMPANY_CAP = int(os.environ.get("LAKE_COMPANY_CAP", "10"))
INDIA_SOURCE_PLATFORMS = {"unstop", "keka"}


def load_registry(segment: str = None) -> List[Dict]:
    if not os.path.exists(REGISTRY):
        return []
    rows = json.load(open(REGISTRY))
    if segment:
        rows = [r for r in rows if r.get("segment") == segment]
    return rows


def _key(r: Dict) -> str:
    """Identity of an opportunity: its official URL, normalised."""
    record_type = r.get("record_type")
    u = (r.get("url") or "").strip().rstrip("/").lower()
    if record_type:
        identifier = (r.get("programme_id") or r.get("issue_id") or u
                      or "{}|{}|{}".format(r.get("platform"), r.get("token"),
                                           r.get("title")))
        return "{}|{}".format(record_type, identifier)
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
    passthrough: List[Dict] = []
    if os.path.exists(path):
        try:
            for r in json.load(open(path)):
                if r.get("record_type"):
                    passthrough.append(r)
                else:
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
            if "is_internship" not in existing:
                existing["is_internship"] = r.get("is_internship")
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

    job_rows = list(lake.values())

    # Set-level hygiene runs over the WHOLE job lake, not just this run's rows,
    # because "is this company over its cap" and "is this a duplicate" are
    # questions about the set. Non-job records are pass-through rows and must
    # never receive job annotations or participate in job liveness.
    quality.annotate(job_rows, cap=COMPANY_CAP)
    out = job_rows + passthrough

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
                # A failed or partial read does NOT enter boards_read — this is
                # the whole point of board-scoped liveness. Observed postings
                # can still be retained and classified; only absence/closure
                # requires a complete successful read.
                if not r.postings:
                    continue

            if r.truncated:
                s["truncated"] += 1
            elif not r.error:
                # The trust contract excludes truncated and failed reads from
                # liveness.
                boards_read.add(board)
            if r.count == 0:
                s["empty"] += 1
                tiering.record_sweep(tier_state, entry["platform"], entry["token"],
                                      qualifying_count=0)
                continue
            if not r.error:
                s["ok"] += 1
            s["postings"] += r.count

            kept_this_board = 0
            india_source = entry["platform"] in INDIA_SOURCE_PLATFORMS
            for p in r.postings:
                v = filters.classify(p.title, p.location, india_source=india_source)
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
                        "company_name": (p.company or entry.get("company")),
                        "segment": entry.get("segment"),
                        "stage": v.stage,
                        "stage_title": v.stage,
                        "stage_resolved": resolution.stage_resolved,
                        "technical": v.technical,
                        "discipline": v.discipline,
                        "is_internship": v.is_internship,
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
                    resolution.experience_min, v.discipline, v.is_internship)
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
                    "is_internship": v.is_internship,
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

    job_rows = [r for r in unique if r.get("record_type") is None]
    report = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "seconds": round(time.time() - started, 1),
        "entries_swept": len(entries),
        "boards_read_ok": len(boards_read),
        "totals": stats["_total"],
        "failure_modes": dict(fails.most_common(10)),
        "kept_total": len(job_rows),
        "store_reconciled": store_reconciled,
        "by_stage": dict(collections.Counter(r.get("stage", "unknown") for r in job_rows)),
        "by_bucket": dict(collections.Counter(r.get("location_bucket", "unknown") for r in job_rows)),
        "technical": sum(1 for r in job_rows if r.get("technical") is True),
        "non_technical": sum(1 for r in job_rows if r.get("technical") is False),
        "unclassified": sum(1 for r in job_rows if r.get("technical") is None),
        "filtered_out": {
            "total": sum(filtered_out.values()),
            "by_reason": dict(filtered_out),
        },
        "hidden": {
            "total": sum(1 for r in job_rows if r.get("hidden_reason") is not None),
            "by_reason": dict(collections.Counter(
                r.get("hidden_reason", None) for r in job_rows
                if r.get("hidden_reason") is not None)),
        },
        "visible_total": sum(1 for r in job_rows
                              if r.get("hidden_reason") is None),
        "by_stage_resolved": dict(collections.Counter(
            r.get("stage_resolved", "unknown") for r in job_rows)),
        "stage_resolved_changed": sum(
            1 for r in job_rows if r.get("stage_resolved") != r.get("stage")),
        "experience_stated": sum(
            1 for r in job_rows if r.get("experience_min") is not None),
        "experience_conflicts": sum(
            1 for r in job_rows if r.get("experience_conflict") is True),
        "by_eligibility_status": dict(collections.Counter(
            r.get("eligibility_status", "unknown") for r in job_rows)),
        "worth_checking_total": sum(
            1 for r in job_rows
            if r.get("eligibility_status") == filters.ELIG_RULES_UNCLEAR),
    }

    india = [r for r in job_rows
             if r.get("location_bucket") in (filters.INDIA_LOCATED, filters.INDIA_REMOTE)]
    report["india_early_career"] = len(india)
    report["india_early_career_technical"] = sum(
        1 for r in india if r.get("technical") is True)
    report["quality"] = quality.report(unique)

    os.makedirs(DATA, exist_ok=True)
    with open(OUT_RUNS, "a") as fh:
        fh.write(json.dumps(report) + "\n")
    return report


def main() -> None:
    args = sys.argv[1:]
    segment = None
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
    if LIMIT:
        entries = entries[:LIMIT]

    if not entries:
        print("data/operations/registry.json has no entries{} — nothing to sweep. "
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
