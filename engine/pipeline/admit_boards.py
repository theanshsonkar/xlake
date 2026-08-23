#!/usr/bin/env python3
"""admit_boards.py

Platform-generic admission bridge: turn cached ATS board leads
(engine/data/raw/discovery-cache/boards_<platform>.json) into verified,
screened, ready-to-admit registry entries.

Standalone (own cadence) - NOT wired into the daily sweep.
Dry-run by DEFAULT: reports everything, writes nothing. Pass --write to persist.

Reuses adapters.boards.list_board for verification; no new collection logic.
Add a platform in ONE line: add it to PLATFORM_POLICY (and optionally EVIDENCE_URL).
"""
import argparse
import json
import os
import sys

_ENGINE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ENGINE_ROOT not in sys.path:
    sys.path.insert(0, _ENGINE_ROOT)

from adapters.boards import list_board  # noqa: E402

PLATFORM_POLICY = {
    "keka": "admit",
    "greenhouse": "admit",
    "workable": "enrich",
    "zohorecruit": "page_reader",
    "darwinbox": "page_reader",
}

EVIDENCE_URL = {
    "greenhouse": "job-boards.greenhouse.io/{token}",
    "keka": "{token}.keka.com",
}

OUTLIER_COUNT = 200
AGENCY_PATTERNS = (
    "agency", "staffing", "recruit", "manpower",
    "consultanc", "hr-services", "outsourc",
)
DISCOVERY_SEGMENT = "unclassified"
DISCOVERY_SOURCE = "discovery"

_OPS_DIR = os.path.join(_ENGINE_ROOT, "data", "operations")
_CACHE_DIR = os.path.join(_ENGINE_ROOT, "data", "raw", "discovery-cache")
REGISTRY_PATH = os.path.join(_OPS_DIR, "registry.json")
REVIEW_PATH = os.path.join(_OPS_DIR, "discovery_review.json")
PENDING_PATH = os.path.join(_OPS_DIR, "discovery_pending_enrichment.json")


def _load_json(path, default):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    return default


def _key(entry):
    return (entry.get("platform"), entry.get("token"))


def is_agency(token, company):
    hay = "{} {}".format(token or "", company or "").lower()
    return any(p in hay for p in AGENCY_PATTERNS)


def build_entry(platform, token, company, count):
    tmpl = EVIDENCE_URL.get(platform)
    url = tmpl.format(token=token) if tmpl else ""
    prefix = (url + " ") if url else ""
    evidence = "{}(discovery-cache boards_{}.json, verified {} live jobs)".format(
        prefix, platform, count
    )
    return {
        "platform": platform,
        "token": token,
        "company": company,
        "segment": DISCOVERY_SEGMENT,
        "source": DISCOVERY_SOURCE,
        "evidence": evidence,
    }


def run_admission(caches, registry, list_board_fn=list_board,
                  policy=PLATFORM_POLICY, outlier=OUTLIER_COUNT):
    existing = {_key(e) for e in registry}
    report = {}
    admit_entries = []
    admit_rows = []
    review_rows = []
    pending_rows = []

    for platform, tokens in caches.items():
        pol = policy.get(platform)
        if pol is None:
            continue
        seen = set()
        uniq = []
        for t in tokens:
            if t not in seen:
                seen.add(t)
                uniq.append(t)
        new_tokens = [t for t in uniq if (platform, t) not in existing]
        r = {
            "policy": pol,
            "read": len(uniq),
            "deduped": len(uniq) - len(new_tokens),
            "verified": 0, "empty": 0, "dead": 0,
            "admit": 0, "flagged": 0, "pending": 0,
        }

        if pol == "page_reader":
            report[platform] = r
            continue

        if pol == "enrich":
            r["pending"] = len(new_tokens)
            if new_tokens:
                pending_rows.append({
                    "platform": platform,
                    "cache_file": "boards_{}.json".format(platform),
                    "new_tokens": len(new_tokens),
                    "total_in_cache": len(uniq),
                    "already_in_registry": r["deduped"],
                    "note": ("list API blind on location/employer; requires a "
                             "job-detail read (location + employer) before admission"),
                })
            report[platform] = r
            continue

        if pol == "admit":
            for t in new_tokens:
                res = list_board_fn(platform, t)
                if getattr(res, "error", None):
                    r["dead"] += 1
                    continue
                count = getattr(res, "count", 0)
                if not count:
                    r["empty"] += 1
                    continue
                r["verified"] += 1
                company = getattr(res, "token", None) or t
                postings = getattr(res, "postings", None) or []
                location = getattr(postings[0], "location", "") if postings else ""
                reasons = []
                if count >= outlier:
                    reasons.append("outlier_count>={}".format(outlier))
                if is_agency(t, company):
                    reasons.append("agency_pattern")
                if reasons:
                    r["flagged"] += 1
                    review_rows.append({
                        "platform": platform,
                        "token": t,
                        "company": company,
                        "count": count,
                        "reason": ", ".join(reasons),
                    })
                    continue
                r["admit"] += 1
                admit_entries.append(build_entry(platform, t, company, count))
                admit_rows.append({
                    "platform": platform, "token": t, "company": company,
                    "count": count, "location": location,
                })
            report[platform] = r
            continue

        report[platform] = r

    return {
        "report": report,
        "admit_entries": admit_entries,
        "admit_rows": admit_rows,
        "review_rows": review_rows,
        "pending_rows": pending_rows,
    }


def merge_registry(existing, new_entries):
    have = {_key(e) for e in existing}
    out = list(existing)
    for e in new_entries:
        if _key(e) not in have:
            out.append(e)
            have.add(_key(e))
    return out


def merge_review(existing, new_rows):
    have = {(e.get("platform"), e.get("token")) for e in existing}
    out = list(existing)
    for e in new_rows:
        k = (e.get("platform"), e.get("token"))
        if k not in have:
            out.append(e)
            have.add(k)
    return out


def merge_pending(existing, new_rows):
    by_platform = {e.get("platform"): e for e in existing}
    for e in new_rows:
        by_platform[e.get("platform")] = e
    return list(by_platform.values())


def _load_caches():
    caches = {}
    for platform in PLATFORM_POLICY:
        path = os.path.join(_CACHE_DIR, "boards_{}.json".format(platform))
        if os.path.exists(path):
            caches[platform] = _load_json(path, [])
    return caches


def _write_json(path, data):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=1, ensure_ascii=False)
        fh.write("\n")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Platform-generic board admission bridge")
    ap.add_argument("--dry-run", dest="dry_run", action="store_true", default=True,
                    help="report only, write nothing (DEFAULT)")
    ap.add_argument("--write", dest="dry_run", action="store_false",
                    help="persist registry/review/pending changes")
    args = ap.parse_args(argv)

    caches = _load_caches()
    registry = _load_json(REGISTRY_PATH, [])
    result = run_admission(caches, registry, list_board_fn=list_board)

    rep = result["report"]
    print("=" * 70)
    print("ADMIT_BOARDS  (mode: {})".format("DRY-RUN" if args.dry_run else "WRITE"))
    print("=" * 70)
    hdr = "{:<12} {:<11} {:>5} {:>5} {:>4} {:>5} {:>4} {:>5} {:>4} {:>4}"
    print(hdr.format("platform", "policy", "read", "dedup", "new", "verif",
                     "emp", "dead", "adm", "flag"))
    for p, r in rep.items():
        new = r["read"] - r["deduped"]
        print(hdr.format(p, r["policy"], r["read"], r["deduped"], new,
                         r["verified"], r["empty"], r["dead"],
                         r["admit"], r["flagged"]))
    print()

    print("FLAGGED FOR MANUAL REVIEW ({}):".format(len(result["review_rows"])))
    for row in result["review_rows"]:
        print("  {platform:<11} {token:<30} count={count:<5} company={company!r} reason={reason}".format(**row))
    print()

    print("ADMIT-SET SAMPLE (up to 10 of {}):".format(len(result["admit_rows"])))
    for row in result["admit_rows"][:10]:
        print("  {platform:<11} {token:<30} company={company!r} count={count:<5} loc={location!r}".format(**row))
    print()

    pend_total = sum(r["new_tokens"] for r in result["pending_rows"])
    print("PENDING ENRICHMENT: {} tokens across {} platform(s)".format(
        pend_total, len(result["pending_rows"])))
    for row in result["pending_rows"]:
        print("  {platform}: {new_tokens} new tokens ({note})".format(**row))
    print()

    if args.dry_run:
        print("DRY-RUN: nothing written to registry.json, discovery_review.json, "
              "or discovery_pending_enrichment.json.")
    else:
        new_registry = merge_registry(registry, result["admit_entries"])
        _write_json(REGISTRY_PATH, new_registry)
        review = merge_review(_load_json(REVIEW_PATH, []), result["review_rows"])
        _write_json(REVIEW_PATH, review)
        pending = merge_pending(_load_json(PENDING_PATH, []), result["pending_rows"])
        _write_json(PENDING_PATH, pending)
        print("WROTE: registry.json (+{} entries), discovery_review.json, "
              "discovery_pending_enrichment.json".format(len(result["admit_entries"])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
