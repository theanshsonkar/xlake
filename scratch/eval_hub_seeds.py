"""Polite live measurement for hub-derived programme seeds.

This script is intentionally separate from the seed generator: it never merges
records or writes the lake. It writes only scratch/hub_eval.json.
"""

from __future__ import annotations

import importlib
import json
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Dict, Iterable, List, Optional
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "engine"
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

try:
    from categories import hub_seeds
    from categories import programme_core
    from core import robots
    from pipeline import resolve
except ImportError:
    from engine.categories import hub_seeds, programme_core
    from engine.core import robots
    from engine.pipeline import resolve

CATEGORIES = ("fellowships", "scholarships")
OUTPUT = ROOT / "scratch" / "dir_eval.json"
PAGE_LIMIT = 150


def _static_seeds(category: str) -> tuple:
    modules = {
        "fellowships": "categories.fellowships.fellowships",
        "scholarships": "categories.scholarships.scholarships",
    }
    module_name = modules.get(category)
    if not module_name:
        return ()
    try:
        module = importlib.import_module(module_name)
    except ImportError:
        module = importlib.import_module("engine." + module_name)
    return tuple(getattr(module, "SOURCE_REGISTRY", ()))


def _first_quote(value) -> str:
    if isinstance(value, dict):
        quote = value.get("quote")
        if isinstance(quote, str) and quote.strip():
            return quote.strip()
        for child in value.values():
            found = _first_quote(child)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _first_quote(child)
            if found:
                return found
    return ""


def _sample_indices(count: int, wanted: int = 40) -> List[int]:
    if count <= wanted:
        return list(range(count))
    return sorted({round(index * (count - 1) / (wanted - 1)) for index in range(wanted)})


def _sample_admitted_lines(category: str, admitted: List[Dict], records: List[Dict]) -> List[str]:
    statuses = {record.get("official_url"): record.get("programme_status")
                for record in records}
    lines = []
    for index in _sample_indices(len(admitted)):
        seed = admitted[index]
        lines.append("{} | {} | {} | {}".format(
            category,
            seed.get("programme_name", ""),
            seed.get("official_url", ""),
            statuses.get(seed.get("official_url")) or "needs_confirmation",
        ))
    return lines


def _category_result(category: str, static: Iterable[Dict], budget: Dict[str, int]) -> Dict:
    filenames = {
        "fellowships": "fellowship_directories.json",
        "scholarships": "scholarship_directories.json",
    }
    hubs_path = ENGINE / "categories" / category / filenames[category]
    seeds = hub_seeds.generate(
        category,
        hubs_path,
        tuple(static),
        per_hub_cap=25,
    )
    generation = dict(hub_seeds.LAST_GENERATE_STATS)
    candidates = seeds
    fetched_pages: Dict[str, tuple] = {}

    def fetch_page(url: str):
        if url not in fetched_pages:
            if budget["used"] >= PAGE_LIMIT:
                return (599, url, "", "global_page_fetch_cap")
            budget["used"] += 1
            fetched_pages[url] = resolve._fetch_page(url)
        return fetched_pages[url]

    admitted, rejected = hub_seeds.admit_seeds(
        category,
        candidates,
        fetch_page,
        robots.allowed,
        max_fetch=max(PAGE_LIMIT - budget["used"], 0),
    )
    config = programme_core.ProgrammeConfig(
        category=category,
        opportunity_type=category,
        source_registry=tuple(admitted),
        observations_path="",
        verifications_path="",
        needs_confirmation_floor=True,
    )
    records: List[Dict] = []
    statuses = Counter({key: 0 for key in ("open", "rolling", "opening_soon", "closed", "needs_confirmation")})
    no_record_reasons = Counter()
    for seed in admitted:
        fetched = fetched_pages.get(seed["official_url"])
        if not fetched:
            no_record_reasons["missing_cached_page"] += 1
            continue
        _, final_url, html, error = hub_seeds._fetch_parts(fetched)
        if error or not html:
            no_record_reasons["fetch_error"] += 1
            continue
        try:
            record, observation = programme_core.parse_programme(
                seed, html, final_url=final_url, config=config,
            )
        except Exception as exc:  # A malformed live page is a measured no-record.
            no_record_reasons["parse_{}".format(type(exc).__name__)] += 1
            continue
        if record is not None:
            records.append(record)
            state = record.get("programme_status") or "needs_confirmation"
            statuses[state if state in statuses else "needs_confirmation"] += 1
        else:
            no_record_reasons[observation.get("reason", "no_record")] += 1
    hub_states = generation.get("hub_states", {})
    hub_reasons = generation.get("hub_reasons", {})
    failed_ids = [hub_id for hub_id, state in hub_states.items() if state == "failed"]
    result = {
        "hubs_loaded": generation.get("hubs_loaded", 0),
        "hub_failed_fetches": len(failed_ids),
        "hub_failure_errors": {hub_id: hub_reasons.get(hub_id, "") for hub_id in failed_ids},
        "raw_candidates": generation.get("raw_candidates_found", 0),
        "candidates_after_cap": generation.get("candidates_found", 0),
        "seeds_after_dedupe": len(seeds),
        "admitted": len(admitted),
        "records_produced": len(records),
        "status_split": dict(statuses),
        "admission_rejection_reasons": dict(sorted(Counter(item["reason"] for item in rejected).items())),
        "rejected_tech": hub_seeds.LAST_ADMISSION_STATS.get("rejected_tech", 0),
        "rejected_form_host": hub_seeds.LAST_ADMISSION_STATS.get("rejected_form_host", 0),
        "rejected_stale_year": hub_seeds.LAST_ADMISSION_STATS.get("rejected_stale_year", 0),
        "rejected_ambassador": hub_seeds.LAST_ADMISSION_STATS.get("rejected_ambassador", 0),
        "no_record_reasons": dict(sorted(no_record_reasons.items())),
        "pages_fetched_total": budget["used"],
        "generator_http_requests": generation.get("http_requests"),
        "admitted_records": _sample_admitted_lines(category, admitted, records),
    }
    return result


def main() -> int:
    results = {}
    budget = {"used": 0}
    for category in CATEGORIES:
        results[category] = _category_result(category, _static_seeds(category), budget)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", encoding="utf-8") as handle:
        json.dump(results, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    for category, result in results.items():
        print("{}: {}".format(category, json.dumps(result, sort_keys=True)))
        for line in result.get("admitted_records", []):
            print(line)
    print("saved: {}".format(OUTPUT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
