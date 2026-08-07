"""Resolve harvested portfolio companies into verified, deduplicated registry boards.

Discovery remains lead-only: this module resolves company domains, writes an
observable resolution report, and appends mechanism-1 boards to the canonical
registry. Sweeping remains the sole producer of lake rows.
"""

from __future__ import annotations

import argparse
import collections
import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Dict, List

import resolve
import resolve_companies

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
LEADS = os.path.join(DATA, "portfolio_companies.json")
REGISTRY = os.path.join(DATA, "registry.json")
REPORT = os.path.join(DATA, "portfolio_resolutions.json")
WORKERS = int(os.environ.get("LAKE_PORTFOLIO_WORKERS", "4"))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def load_leads(path: str = LEADS) -> List[Dict]:
    with open(path, encoding="utf-8") as handle:
        rows = json.load(handle)
    return [row for row in rows if row.get("company") and row.get("domain")]


def resolve_lead(lead: Dict) -> Dict:
    resolution = resolve.resolve_and_verify(lead["company"], lead["domain"])
    mechanism, reason = resolve_companies.classify_mechanism(resolution)
    return {
        "company": lead["company"],
        "company_name_source": lead.get("company_name_source", "legacy_unknown"),
        "domain": lead["domain"],
        "website": lead.get("website", ""),
        "portfolio_slug": lead.get("portfolio_slug", ""),
        "portfolio_url": lead.get("portfolio_url", ""),
        "mechanism": mechanism,
        "reason": reason,
        "platform": resolution.platform,
        "token": resolution.token,
        "state": resolution.state,
        "verify_jobs": resolution.verify_jobs,
        "verify_status": resolution.verify_status,
        "verify_error": resolution.verify_error,
        "careers_url": resolution.careers_url,
        "evidence": resolution.evidence,
        "resolved_at": _now(),
    }


def append_verified_boards(rows: List[Dict], registry_path: str = REGISTRY) -> int:
    with open(registry_path, encoding="utf-8") as handle:
        registry = json.load(handle)
    known = {(entry.get("platform"), entry.get("token")) for entry in registry}
    additions = []
    for row in rows:
        key = (row.get("platform"), row.get("token"))
        if row.get("mechanism") != "board" or not all(key) or key in known:
            continue
        known.add(key)
        additions.append({
            "platform": row["platform"], "token": row["token"],
            "company": row["company"], "company_name": row["company"],
            "segment": "portfolio", "source": "portfolio_resolver",
            "portfolio_slug": row["portfolio_slug"], "evidence": row["evidence"],
        })
    if additions:
        registry.extend(additions)
        with open(registry_path, "w", encoding="utf-8") as handle:
            json.dump(registry, handle, indent=1)
            handle.write("\n")
    return len(additions)


def run(leads_path: str = LEADS, registry_path: str = REGISTRY,
        report_path: str = REPORT, limit: int = 0, write_registry: bool = True) -> Dict:
    leads = load_leads(leads_path)
    if limit:
        leads = leads[:limit]
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        rows = list(pool.map(resolve_lead, leads))
    report = {
        "generated_at": _now(), "leads": len(leads), "workers": WORKERS,
        "rows": rows,
        "mechanisms": dict(collections.Counter(row["mechanism"] for row in rows)),
        "platforms": dict(collections.Counter(row.get("platform") or "none" for row in rows)),
        "verified_postings": sum(row.get("verify_jobs") or 0 for row in rows if row["mechanism"] == "board"),
    }
    report["boards_added"] = append_verified_boards(rows, registry_path) if write_registry else 0
    with open(report_path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)
        handle.write("\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--leads", default=LEADS)
    parser.add_argument("--registry", default=REGISTRY)
    parser.add_argument("--report", default=REPORT)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--no-write-registry", action="store_true")
    args = parser.parse_args()
    result = run(args.leads, args.registry, args.report, args.limit, not args.no_write_registry)
    print("resolved {leads} leads; added {boards_added} verified boards; verified postings={verified_postings}".format(**result))
    print("mechanisms=" + json.dumps(result["mechanisms"], sort_keys=True))
    print("platforms=" + json.dumps(result["platforms"], sort_keys=True))


if __name__ == "__main__":
    main()
