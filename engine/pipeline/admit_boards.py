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
import re
import sys
import urllib.parse
from typing import Optional

_ENGINE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ENGINE_ROOT not in sys.path:
    sys.path.insert(0, _ENGINE_ROOT)

from adapters.boards import list_board  # noqa: E402

PLATFORM_POLICY = {
    "keka": "admit",
    "greenhouse": "admit",
    "workable": "admit",
    "zohorecruit": "page_reader",
    "darwinbox": "page_reader",
}

EVIDENCE_URL = {
    "greenhouse": "job-boards.greenhouse.io/{token}",
    "keka": "{token}.keka.com",
    "workable": "apply.workable.com/{token}",
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
REJECTED_PATH = os.path.join(_OPS_DIR, "discovery_rejected.json")
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


def build_entry(platform, token, company, count, note=None):
    tmpl = EVIDENCE_URL.get(platform)
    url = tmpl.format(token=token) if tmpl else ""
    prefix = (url + " ") if url else ""
    evidence = "{}(discovery-cache boards_{}.json, verified {} live jobs)".format(
        prefix, platform, count
    )
    if note:
        evidence += " ({})".format(note)
    return {
        "platform": platform,
        "token": token,
        "company": company,
        "segment": DISCOVERY_SEGMENT,
        "source": DISCOVERY_SOURCE,
        "evidence": evidence,
    }


def run_admission(caches, registry, list_board_fn=list_board,
                  policy=PLATFORM_POLICY, outlier=OUTLIER_COUNT,
                  rejected=None):
    rejected = set(rejected or ())
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
        new_tokens = [t for t in new_tokens if (platform, t) not in rejected]
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
                    "note": ("list API lacks fields required for admission; "
                             "parked pending enrichment"),
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


def clean_token(token: str) -> str:
    """Produce a readable fallback name from an ATS token."""
    words = re.sub(r"[-_.\s]+", " ", token).strip().split()
    return " ".join(word.capitalize() if word.islower() else word for word in words)


_TITLE_COMPANY_PATTERNS = (
    r"^Careers at (.+)$",
    r"^Jobs at (.+)$",
    r"^(.+?)\s*[-|–]\s*Careers$",
    r"^Careers\s*[-|–]\s*(.+)$",
    r"^(.+?)\s+Careers$",
)


def _company_from_title_text(text):
    text = (text or "").strip()
    if not text:
        return None
    for pattern in _TITLE_COMPANY_PATTERNS:
        matched = re.match(pattern, text, flags=re.IGNORECASE)
        if matched:
            return matched.group(1).strip()
    return None


def parse_keka_title(html: str) -> Optional[str]:
    """Extract a company name from common Keka careers page <title> text."""
    import html as html_module
    match = re.search(r"<title\b[^>]*>(.*?)</title\s*>", html,
                      flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return None
    return _company_from_title_text(html_module.unescape(match.group(1)))


def parse_keka_og_title(html: str) -> Optional[str]:
    """Extract a company name from the og:title meta tag of a Keka careers page."""
    import html as html_module
    m = re.search(r'<meta[^>]+property=["\']og:title["\'][^>]*content=["\']([^"\']*)["\']',
                  html, flags=re.IGNORECASE)
    if not m:
        m = re.search(r'<meta[^>]+content=["\']([^"\']*)["\'][^>]*property=["\']og:title["\']',
                      html, flags=re.IGNORECASE)
    if not m:
        return None
    return _company_from_title_text(html_module.unescape(m.group(1)))


def _fetch_greenhouse_name(token, request_fn):
    url = "https://boards-api.greenhouse.io/v1/boards/{}".format(
        urllib.parse.quote(token)
    )
    status, body, _error = request_fn(url)
    if status == 200 and isinstance(body, dict) and body.get("name"):
        return body["name"].strip(), "greenhouse-api"
    return None, "unresolved"


def _fetch_keka_name(token, request_fn):
    url = "https://{}.keka.com/careers/".format(urllib.parse.quote(token))
    status, body, _error = request_fn(url, want_json=False)
    if status == 200 and body:
        name = parse_keka_title(body)
        if name:
            return name, "keka-title"
        name = parse_keka_og_title(body)
        if name:
            return name, "keka-og-title"
        return clean_token(token), "fallback-token"
    return None, "unresolved"


def _fetch_workable_name(token, request_fn):
    url = "https://apply.workable.com/api/v1/widget/accounts/{}?details=true".format(
        urllib.parse.quote(token)
    )
    status, body, _error = request_fn(url)
    if status == 200 and isinstance(body, dict) and body.get("name"):
        return body["name"].strip(), "workable-widget"
    alt = "https://www.workable.com/api/accounts/{}".format(urllib.parse.quote(token))
    status2, body2, _error2 = request_fn(alt)
    if status2 == 200 and isinstance(body2, dict) and body2.get("name"):
        return body2["name"].strip(), "workable-accounts"
    return clean_token(token), "fallback-token"


def resolve_display_name(platform, token, request_fn=None):
    if request_fn is None:
        from adapters.boards import _request
        request_fn = _request
    if platform == "greenhouse":
        return _fetch_greenhouse_name(token, request_fn)
    if platform == "keka":
        return _fetch_keka_name(token, request_fn)
    if platform == "workable":
        return _fetch_workable_name(token, request_fn)
    return None, "unresolved"


def refresh_display_names(registry, resolve_fn=resolve_display_name):
    rows = []
    for entry in registry:
        if entry.get("source") != "discovery":
            continue
        platform = entry.get("platform")
        token = entry.get("token")
        old_company = entry.get("company")
        if platform not in ("greenhouse", "keka", "workable"):
            rows.append({
                "platform": platform,
                "token": token,
                "old_company": old_company,
                "new_company": old_company,
                "kind": "unresolved-unsupported",
            })
            continue
        name, kind = resolve_fn(platform, token)
        if name and kind != "unresolved":
            entry["company"] = name
            new_company = name
        else:
            kind = "unresolved"
            new_company = old_company
        rows.append({
            "platform": platform,
            "token": token,
            "old_company": old_company,
            "new_company": new_company,
            "kind": kind,
        })
    return rows


def _parse_keys(values):
    keys = []
    for chunk in values or []:
        for item in chunk.split(','):
            item = item.strip()
            if not item:
                continue
            platform, _, token = item.partition(':')
            platform = platform.strip(); token = token.strip()
            if platform and token:
                keys.append((platform, token))
    return keys


def process_review(admit_keys, reject_keys, review, registry, rejected,
                   list_board_fn=list_board, resolve_fn=resolve_display_name):
    admit_keys = list(admit_keys or ())
    reject_keys = list(reject_keys or ())
    admit_set = set(admit_keys)
    reject_set = set(reject_keys)
    existing_reg = {(e["platform"], e["token"]) for e in registry}
    review_by_key = {(r["platform"], r["token"]): r for r in review}
    result = {
        "admitted": [],
        "already_admitted": [],
        "admit_errors": [],
        "rejected_added": [],
        "already_rejected": [],
        "held": [],
    }
    new_entries = []

    for platform, token in admit_keys:
        key = (platform, token)
        if key in existing_reg:
            result["already_admitted"].append(key)
            continue
        try:
            board_result = list_board_fn(platform, token)
            count = getattr(board_result, "count", None)
            if count in (None, 0):
                error = getattr(board_result, "error", None) or "not live"
                result["admit_errors"].append({
                    "platform": platform, "token": token, "error": str(error),
                })
                continue
        except Exception as exc:
            result["admit_errors"].append({
                "platform": platform, "token": token, "error": str(exc),
            })
            continue
        name, _kind = resolve_fn(platform, token)
        if not name:
            name = token
        new_entries.append(build_entry(
            platform, token, name, count, note="approved from review"
        ))
        result["admitted"].append({
            "platform": platform, "token": token,
            "company": name, "count": count,
        })

    new_registry = merge_registry(list(registry), new_entries)
    existing_rej = {(r["platform"], r["token"]) for r in rejected}
    new_rejected = list(rejected)
    for platform, token in reject_keys:
        key = (platform, token)
        if key in existing_rej:
            result["already_rejected"].append(key)
            continue
        if key in review_by_key:
            record = dict(review_by_key[key])
        else:
            record = {
                "platform": platform,
                "token": token,
                "company": token,
                "count": None,
                "reason": "manual_reject",
            }
        new_rejected.append(record)
        existing_rej.add(key)
        result["rejected_added"].append(key)

    new_review = [
        row for row in review
        if (row["platform"], row["token"]) not in admit_set
        and (row["platform"], row["token"]) not in reject_set
    ]
    result["held"] = [
        (row["platform"], row["token"]) for row in new_review
    ]
    result["new_registry"] = new_registry
    result["new_review"] = new_review
    result["new_rejected"] = new_rejected
    return result


def main(argv=None):
    ap = argparse.ArgumentParser(description="Platform-generic board admission bridge")
    ap.add_argument("--dry-run", dest="dry_run", action="store_true", default=True,
                    help="report only, write nothing (DEFAULT)")
    ap.add_argument("--write", dest="dry_run", action="store_false",
                    help="persist registry/review/pending changes")
    ap.add_argument("--refresh-names", action="store_true",
                    help="refresh company names for discovery entries")
    ap.add_argument("--process-review", dest="process_review", action="store_true")
    ap.add_argument("--admit", action="append", default=[])
    ap.add_argument("--reject", action="append", default=[])
    args = ap.parse_args(argv)

    if args.refresh_names:
        registry = _load_json(REGISTRY_PATH, [])
        rows = refresh_display_names(registry)
        authoritative = sum(row["kind"] in ("greenhouse-api", "keka-title", "keka-og-title", "workable-widget", "workable-accounts")
                            for row in rows)
        fallback = sum(row["kind"] == "fallback-token" for row in rows)
        unresolved = sum(row["kind"] in ("unresolved", "unresolved-unsupported")
                         for row in rows)
        print("REFRESH_DISPLAY_NAMES (mode: {})".format(
            "DRY-RUN" if args.dry_run else "WRITE"))
        print("authoritative: {}".format(authoritative))
        print("fallback-cleaned: {}".format(fallback))
        print("unresolved: {}".format(unresolved))
        from collections import Counter
        by_platform = {}
        for row in rows:
            by_platform.setdefault(row['platform'], Counter())[row['kind']] += 1
        print('by-platform kind breakdown:')
        for _plat in sorted(by_platform):
            print('  {}: {}'.format(_plat, dict(by_platform[_plat])))
        for platform in ("greenhouse", "keka", "workable"):
            print("{} samples:".format(platform))
            for row in [r for r in rows if r["platform"] == platform][:10]:
                print("  {} -> {} [{}]".format(
                    row["token"], row["new_company"], row["kind"]))
        print("unresolved tokens:")
        for row in rows:
            if row["kind"] in ("unresolved", "unresolved-unsupported"):
                print("  {}".format(row["token"]))
        if args.dry_run:
            print("DRY-RUN: nothing written to registry.json.")
        else:
            _write_json(REGISTRY_PATH, registry)
            print("WROTE: registry.json")
        return 0

    if args.process_review:
        registry = _load_json(REGISTRY_PATH, [])
        review = _load_json(REVIEW_PATH, [])
        rejected = _load_json(REJECTED_PATH, [])
        admit_keys = _parse_keys(args.admit)
        reject_keys = _parse_keys(args.reject)
        res = process_review(admit_keys, reject_keys, review, registry, rejected)
        mode = "DRY-RUN" if args.dry_run else "WRITE"
        print("PROCESS_REVIEW (mode: {})".format(mode))
        print("ADMIT requested: {}  |  REJECT requested: {}".format(
            len(admit_keys), len(reject_keys)))
        print("-- ADMITTED (newly, {}):".format(len(res["admitted"])))
        for a in res["admitted"]:
            print("   {}/{} => {} | {} live".format(
                a["platform"], a["token"], a["company"], a["count"]))
        if res["already_admitted"]:
            print("-- already in registry (idempotent skip): {}".format(
                len(res["already_admitted"])))
            for platform, token in res["already_admitted"]:
                print("   {}/{}".format(platform, token))
        if res["admit_errors"]:
            print("-- ADMIT ERRORS / not live (NOT admitted): {}".format(
                len(res["admit_errors"])))
            for error in res["admit_errors"]:
                print("   {}/{} :: {}".format(
                    error["platform"], error["token"], error["error"]))
        print("-- REJECTED (newly, {}):".format(len(res["rejected_added"])))
        for platform, token in res["rejected_added"]:
            print("   {}/{}".format(platform, token))
        if res["already_rejected"]:
            print("-- already rejected (idempotent skip): {}".format(
                len(res["already_rejected"])))
        print("-- HELD in review ({}):".format(len(res["held"])))
        for platform, token in res["held"]:
            print("   {}/{}".format(platform, token))
        print("registry: {} -> {}".format(len(registry), len(res["new_registry"])))
        print("discovery_review: {} -> {}".format(
            len(review), len(res["new_review"])))
        print("discovery_rejected: {} -> {}".format(
            len(rejected), len(res["new_rejected"])))
        if args.dry_run:
            print("DRY-RUN: nothing written")
        else:
            _write_json(REGISTRY_PATH, res["new_registry"])
            _write_json(REVIEW_PATH, res["new_review"])
            _write_json(REJECTED_PATH, res["new_rejected"])
            print("WROTE: registry.json, discovery_review.json, discovery_rejected.json")
        return 0

    caches = _load_caches()
    registry = _load_json(REGISTRY_PATH, [])
    rejected_rows = _load_json(REJECTED_PATH, [])
    rejected_keys = {(r["platform"], r["token"]) for r in rejected_rows}
    result = run_admission(caches, registry, list_board_fn=list_board,
                           rejected=rejected_keys)

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
