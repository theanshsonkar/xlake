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
    _year_near, classify_status, detect_applicant_windows, parse_date,
    parse_dates, validate_verification,
)

SOURCE_REGISTRY = (
    {"source_id": "grant-otf-internet-freedom-fund", "programme_id": "grant-otf-internet-freedom-fund", "programme_name": "Open Technology Fund — Internet Freedom Fund", "organizer": "Open Technology Fund", "official_url": "https://www.opentech.fund/funds/internet-freedom-fund/", "allowed_path_hints": ["funds/internet-freedom-fund"], "check_cadence": "monthly"},
    {"source_id": "grant-ethereum-ecosystem-support-program", "programme_id": "grant-ethereum-ecosystem-support-program", "programme_name": "Ethereum Foundation — Ecosystem Support Program", "organizer": "Ethereum Foundation", "official_url": "https://esp.ethereum.foundation/", "allowed_path_hints": [""], "check_cadence": "monthly"},
    {"source_id": "grant-awesome-foundation-grant-application", "programme_id": "grant-awesome-foundation-grant-application", "programme_name": "Awesome Foundation — Grant Application", "organizer": "Awesome Foundation", "official_url": "https://www.awesomefoundation.org/en/submissions/new", "allowed_path_hints": ["en/submissions/new"], "check_cadence": "monthly"},
    {"source_id": "grant-pollination-daily-grants", "programme_id": "grant-pollination-daily-grants", "programme_name": "The Pollination Project — Daily Grants", "organizer": "The Pollination Project", "official_url": "https://thepollinationproject.org/apply/", "allowed_path_hints": ["apply"], "check_cadence": "monthly"},
    {"source_id": "grant-national-geographic-okavango-ecosystem-dynamics", "programme_id": "grant-national-geographic-okavango-ecosystem-dynamics", "programme_name": "National Geographic Society — Understanding Ecosystem Dynamics and the Ecology of the Okavango River Basin", "organizer": "National Geographic Society", "official_url": "https://funding.nationalgeographic.org/s/fundingopportunity/119Hr000000byRrIAI/understanding-ecosystem-dynamics-ecology-of-the-okavango-river-basin", "allowed_path_hints": ["s/fundingopportunity/119Hr000000byRrIAI"], "check_cadence": "monthly"},
)
SEEDS = SOURCE_REGISTRY
SEED_BY_URL = {seed["official_url"]: seed for seed in SOURCE_REGISTRY}
SOURCE_BY_ID = {seed["programme_id"]: seed for seed in SOURCE_REGISTRY}
OBSERVATIONS_PATH = os.path.join(OPERATIONS_DIR, "grant_programmes_observations.json")
VERIFICATIONS_PATH = os.path.join(OPERATIONS_DIR, "grant_programme_verifications.json")
GRANT_CONFIG = ProgrammeConfig(
    category="grant",
    opportunity_type="grant",
    source_registry=SOURCE_REGISTRY,
    observations_path=OBSERVATIONS_PATH,
    verifications_path=VERIFICATIONS_PATH,
)


def _base(seed, checked, evidence):
    return _core._base(seed, checked, evidence, GRANT_CONFIG)


def parse_programme(seed: Dict, html: str, checked_at: Optional[datetime] = None, final_url: Optional[str] = None) -> Tuple[Optional[Dict], Dict]:
    return _core.parse_programme(seed, html, checked_at, final_url, config=GRANT_CONFIG)


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
    """Keep only quote-backed Grant facts from manual verification."""
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

        # Remove parser evidence for fact fields first, then restore only the
        # evidence supplied by this programme's valid verification record.
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
        _core.apply_verifications(rows, verifications, now, config=GRANT_CONFIG),
        verifications,
    )


def load_verifications(path: str = VERIFICATIONS_PATH) -> List[Dict]:
    return _core.load_verifications(path)


def merge_programmes(records: Iterable[Dict], observations: Iterable[Dict], lake_path: str = OPPORTUNITIES_PATH, observations_path: str = OBSERVATIONS_PATH, now: Optional[str] = None) -> List[Dict]:
    return _core.merge_programmes(records, observations, lake_path, observations_path, now)


def collect(fetch: Callable[[str], str] = _core._default_fetch, checked_at: Optional[datetime] = None, lake_path: str = OPPORTUNITIES_PATH, observations_path: str = OBSERVATIONS_PATH) -> Dict:
    result = _core.collect(
        GRANT_CONFIG,
        fetch=fetch,
        checked_at=checked_at,
        lake_path=lake_path,
        observations_path=observations_path,
    )
    verifications = load_verifications(GRANT_CONFIG.verifications_path)
    merged = apply_verifications(
        _load_json(lake_path, []), verifications,
        datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
    _atomic_json(lake_path, merged)
    result["merged"] = merged
    return result


def _apply_verifications_cli(config: ProgrammeConfig = GRANT_CONFIG) -> None:
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


def run_module_cli(config: ProgrammeConfig = GRANT_CONFIG, argv=None) -> None:
    args = sys.argv[1:] if argv is None else argv
    if "--apply-verifications" in args:
        _apply_verifications_cli(config)
    else:
        result = collect()
        print(json.dumps({"records": len(result["records"]), "observations": len(result["observations"])}, indent=2))


if __name__ == "__main__":
    run_module_cli(GRANT_CONFIG)
