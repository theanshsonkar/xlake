from __future__ import annotations

import json
import os
import sys
from copy import deepcopy
from datetime import datetime, timezone
from typing import Callable, Dict, Iterable, List, Optional, Tuple

from core.paths import OPPORTUNITIES_PATH, OPERATIONS_DIR
from categories import programme_core as _core
from categories.programme_core import (
    APPLICANT_ACTION_TOKENS, APPLICANT_DEADLINE_TOKENS, APPLY_LINK_TOKENS,
    FORMAL_PROGRAMME_TOKENS, MONTHS, MONTH_PATTERN, ORGANIZER_WINDOW_TOKENS,
    ROLLING_TOKENS, ProgrammeConfig, _VisibleText, _application_url,
    _atomic_json, _default_fetch, _evidence, _later_timestamp, _load_json,
    _month_number, _observation, _quote_with, _sentences, _text, _timestamp,
    _year_near, classify_status, detect_applicant_windows, load_generated_seeds,
    parse_date, parse_dates, validate_verification,
)

def _load_static_seed_registry() -> tuple:
    path = os.path.join(os.path.dirname(__file__), "community_seeds.json")
    with open(path, encoding="utf-8") as handle:
        seeds = json.load(handle)
    if not isinstance(seeds, list):
        raise ValueError("community seed registry must be a JSON array")
    return tuple(seeds)


STATIC_SOURCE_REGISTRY = _load_static_seed_registry()


def _combined_source_registry() -> tuple:
    result = list(STATIC_SOURCE_REGISTRY)
    seen_urls = {seed["official_url"] for seed in result}
    seen_ids = {seed["source_id"] for seed in result} | {seed["programme_id"] for seed in result}
    for seed in load_generated_seeds("community"):
        if (seed["official_url"] in seen_urls
                or seed["source_id"] in seen_ids
                or seed["programme_id"] in seen_ids):
            continue
        result.append(seed)
        seen_urls.add(seed["official_url"])
        seen_ids.update((seed["source_id"], seed["programme_id"]))
    return tuple(result)


SOURCE_REGISTRY = _combined_source_registry()
SEEDS = SOURCE_REGISTRY
SEED_BY_URL = {seed["official_url"]: seed for seed in SOURCE_REGISTRY}
SOURCE_BY_ID = {seed["programme_id"]: seed for seed in SOURCE_REGISTRY}
OBSERVATIONS_PATH = os.path.join(OPERATIONS_DIR, "community_programmes_observations.json")
VERIFICATIONS_PATH = os.path.join(OPERATIONS_DIR, "community_programme_verifications.json")
COMMUNITY_CONFIG = ProgrammeConfig(
    category="community",
    opportunity_type="programme",
    source_registry=SOURCE_REGISTRY,
    observations_path=OBSERVATIONS_PATH,
    verifications_path=VERIFICATIONS_PATH,
    needs_confirmation_floor=True,
)


def _base(seed, checked, evidence):
    return _core._base(seed, checked, evidence, COMMUNITY_CONFIG)


def parse_programme(seed: Dict, html: str, checked_at: Optional[datetime] = None, final_url: Optional[str] = None) -> Tuple[Optional[Dict], Dict]:
    return _core.parse_programme(seed, html, checked_at, final_url, config=COMMUNITY_CONFIG)


_FACT_EVIDENCE_KEYS = {
    "programme_status": ("status", "programme_status"),
    "opening_date": ("opening_date", "status"),
    "deadline": ("deadline",),
    "eligibility": ("eligibility",),
    "funding": ("funding",),
    "international_eligibility": ("international_eligibility",),
}


def _verified_by_id(verifications: Iterable[Dict]) -> Dict[str, Dict]:
    verified = {}
    for verification in verifications:
        programme_id = verification.get("programme_id")
        if programme_id in SOURCE_BY_ID and validate_verification(verification)[0]:
            verified[programme_id] = verification
    return verified


def _fact_is_backed(verification: Dict, field: str) -> bool:
    value = verification.get(field)
    if value in (None, ""):
        return False
    evidence = verification.get("official_evidence")
    if not isinstance(evidence, dict):
        return False
    return any(
        isinstance(evidence.get(key), dict)
        and str(evidence[key].get("quote", "")).strip()
        and str(evidence[key].get("url", "")).strip()
        for key in _FACT_EVIDENCE_KEYS[field]
    )


def _postprocess(rows: Iterable[Dict], verifications: Iterable[Dict]) -> List[Dict]:
    """Keep only quote-backed facts from manual verification."""
    result = deepcopy(list(rows))
    verified_by_id = _verified_by_id(verifications)
    fact_fields = ("programme_status", "opening_date", "deadline", "eligibility", "funding")

    for row in result:
        if row.get("record_type") != "programme" or row.get("programme_id") not in SOURCE_BY_ID:
            continue
        verification = verified_by_id.get(row["programme_id"], {})
        evidence = row.get("official_evidence")
        if not isinstance(evidence, dict):
            evidence = {}
            row["official_evidence"] = evidence
        for keys in _FACT_EVIDENCE_KEYS.values():
            for key in keys:
                evidence.pop(key, None)
        for field in fact_fields + ("international_eligibility",):
            if _fact_is_backed(verification, field):
                row[field] = verification[field]
                for key in _FACT_EVIDENCE_KEYS[field]:
                    if key in verification.get("official_evidence", {}):
                        evidence[key] = deepcopy(verification["official_evidence"][key])
            elif field == "eligibility":
                row[field] = "needs_confirmation"
            elif field == "funding":
                row[field] = "not_stated"
            elif field == "international_eligibility":
                row[field] = "needs_confirmation"
            else:
                row.pop(field, None)

        status = row.get("programme_status")
        if status in ("open", "opening_soon", "rolling"):
            row["is_live"] = True
            row.pop("needs_confirmation", None)
            row.pop("went_dead_at", None)
        elif status in ("closed", "ended"):
            row["is_live"] = False
            row.pop("needs_confirmation", None)
        else:
            row["needs_confirmation"] = True
            row["is_live"] = False
            row.pop("went_dead_at", None)
    return result


def apply_verifications(rows: Iterable[Dict], verifications: Iterable[Dict], now) -> List[Dict]:
    verifications = list(verifications)
    return _postprocess(
        _core.apply_verifications(rows, verifications, now, config=COMMUNITY_CONFIG),
        verifications,
    )


def load_verifications(path: str = VERIFICATIONS_PATH) -> List[Dict]:
    return _core.load_verifications(path)


def merge_programmes(records: Iterable[Dict], observations: Iterable[Dict], lake_path: str = OPPORTUNITIES_PATH, observations_path: str = OBSERVATIONS_PATH, now: Optional[str] = None) -> List[Dict]:
    return _core.merge_programmes(records, observations, lake_path, observations_path, now)


def collect(fetch: Callable[[str], str] = _core._default_fetch, checked_at: Optional[datetime] = None, lake_path: str = OPPORTUNITIES_PATH, observations_path: str = OBSERVATIONS_PATH) -> Dict:
    result = _core.collect(
        COMMUNITY_CONFIG,
        fetch=fetch,
        checked_at=checked_at,
        lake_path=lake_path,
        observations_path=observations_path,
    )
    verifications = load_verifications(COMMUNITY_CONFIG.verifications_path)
    merged = apply_verifications(
        _load_json(lake_path, []), verifications,
        datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
    _atomic_json(lake_path, merged)
    result["merged"] = merged
    return result


def _apply_verifications_cli(config: ProgrammeConfig = COMMUNITY_CONFIG) -> None:
    rows = _load_json(OPPORTUNITIES_PATH, [])
    verifications = load_verifications(config.verifications_path)
    valid_count = sum(1 for verification in verifications if validate_verification(verification)[0])
    updated = apply_verifications(
        rows, verifications,
        datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
    _atomic_json(OPPORTUNITIES_PATH, updated)
    print(json.dumps({
        "verification_records": len(verifications),
        "valid_records": valid_count,
        "programme_rows": sum(1 for row in updated if row.get("record_type") == "programme"),
    }, indent=2))


def run_module_cli(config: ProgrammeConfig = COMMUNITY_CONFIG, argv=None) -> None:
    args = sys.argv[1:] if argv is None else argv
    if "--apply-verifications" in args:
        _apply_verifications_cli(config)
    else:
        result = collect()
        print(json.dumps({"records": len(result["records"]), "observations": len(result["observations"])}, indent=2))


if __name__ == "__main__":
    run_module_cli(COMMUNITY_CONFIG)
