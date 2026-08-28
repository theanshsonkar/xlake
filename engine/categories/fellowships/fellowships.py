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
    {"source_id": "fellowship-mlh", "programme_id": "fellowship-mlh-fellowship", "programme_name": "MLH Fellowship", "organizer": "Major League Hacking", "official_url": "https://fellowship.mlh.io/", "allowed_path_hints": [""], "check_cadence": "monthly"},
    {"source_id": "fellowship-thiel", "programme_id": "fellowship-thiel-fellowship", "programme_name": "Thiel Fellowship", "organizer": "Thiel Foundation", "official_url": "https://thielfellowship.org/", "allowed_path_hints": [""], "check_cadence": "monthly"},
    {"source_id": "fellowship-echoing-green", "programme_id": "fellowship-echoing-green", "programme_name": "Echoing Green Fellowship", "organizer": "Echoing Green", "official_url": "https://echoinggreen.org/fellowship/apply/", "allowed_path_hints": ["fellowship/apply", "fellowship"], "check_cadence": "monthly"},
    {"source_id": "fellowship-kleiner-perkins", "programme_id": "fellowship-kleiner-perkins-fellows", "programme_name": "Kleiner Perkins Fellows Program", "organizer": "Kleiner Perkins", "official_url": "https://www.kleinerperkins.com/fellows/", "allowed_path_hints": ["fellows"], "check_cadence": "monthly"},
    {"source_id": "fellowship-acumen", "programme_id": "fellowship-acumen", "programme_name": "Acumen Fellowship Program", "organizer": "Acumen Academy", "official_url": "https://acumenacademy.org/fellowship/", "allowed_path_hints": ["fellowship"], "check_cadence": "monthly"},
    {"source_id": "fellowship-mozilla", "programme_id": "fellowship-mozilla", "programme_name": "Mozilla Fellowship Program", "organizer": "Mozilla Foundation", "official_url": "https://www.mozillafoundation.org/en/what-we-do/grantmaking/fellowship/", "allowed_path_hints": ["en/what-we-do/grantmaking/fellowship"], "check_cadence": "monthly"},
    {"source_id": "fellowship-emergent-ventures", "programme_id": "fellowship-emergent-ventures", "programme_name": "Emergent Ventures", "organizer": "Mercatus Center", "official_url": "https://www.mercatus.org/emergent-ventures", "allowed_path_hints": ["emergent-ventures"], "check_cadence": "monthly"},
    {"source_id": "fellowship-eisenhower-global", "programme_id": "fellowship-eisenhower-global", "programme_name": "Eisenhower Fellowships Global Program", "organizer": "Eisenhower Fellowships", "official_url": "https://www.efworld.org/apply-now/", "allowed_path_hints": ["apply-now", "2027-globalprogram-eligibilty-criteria"], "check_cadence": "monthly"},
    {"source_id": "fellowship-schmidt-science", "programme_id": "fellowship-schmidt-science", "programme_name": "Schmidt Science Fellows", "organizer": "Schmidt Sciences", "official_url": "https://schmidtsciencefellows.org/selection/who-can-apply/", "allowed_path_hints": ["selection/who-can-apply"], "check_cadence": "monthly"},
    {"source_id": "fellowship-ashoka", "programme_id": "fellowship-ashoka", "programme_name": "Ashoka Fellowship", "organizer": "Ashoka", "official_url": "https://www.ashoka.org/en-us/program/ashoka-fellowship", "allowed_path_hints": ["en-us/program/ashoka-fellowship"], "check_cadence": "monthly"},
)
SEEDS = SOURCE_REGISTRY
SEED_BY_URL = {seed["official_url"]: seed for seed in SOURCE_REGISTRY}
SOURCE_BY_ID = {seed["programme_id"]: seed for seed in SOURCE_REGISTRY}
OBSERVATIONS_PATH = os.path.join(OPERATIONS_DIR, "fellowship_programmes_observations.json")
VERIFICATIONS_PATH = os.path.join(OPERATIONS_DIR, "fellowship_programme_verifications.json")

FELLOWSHIP_CONFIG = ProgrammeConfig(
    category="fellowship",
    opportunity_type="fellowship",
    source_registry=SOURCE_REGISTRY,
    observations_path=OBSERVATIONS_PATH,
    verifications_path=VERIFICATIONS_PATH,
)


def _base(seed, checked, evidence):
    return _core._base(seed, checked, evidence, FELLOWSHIP_CONFIG)


def parse_programme(seed: Dict, html: str, checked_at: Optional[datetime] = None, final_url: Optional[str] = None) -> Tuple[Optional[Dict], Dict]:
    return _core.parse_programme(seed, html, checked_at, final_url, config=FELLOWSHIP_CONFIG)


def _needs_confirmation_ids(verifications: Iterable[Dict]) -> set:
    return {
        verification["programme_id"]
        for verification in verifications
        if verification.get("programme_id") in SOURCE_BY_ID
        and verification.get("programme_status") in (None, "")
    }


def _valid_open_ids(verifications: Iterable[Dict]) -> set:
    return {
        verification["programme_id"]
        for verification in verifications
        if verification.get("programme_id") in SOURCE_BY_ID
        and verification.get("programme_status") == "open"
        and validate_verification(verification)[0]
    }


def _postprocess(rows: Iterable[Dict], verifications: Iterable[Dict]) -> List[Dict]:
    """Keep verified facts while repairing Fellowship-local serving metadata."""
    result = deepcopy(list(rows))
    valid_open_ids = _valid_open_ids(verifications)
    needs_confirmation_ids = _needs_confirmation_ids(verifications) - valid_open_ids

    # The current registry ID wins over this one known pre-registry duplicate only.
    current_kleiner_id = "fellowship-kleiner-perkins-fellows"
    legacy_kleiner_id = "fellowship-kleiner-perkins"
    if any(
        row.get("record_type") == "programme"
        and row.get("category") == FELLOWSHIP_CONFIG.category
        and row.get("programme_id") == current_kleiner_id
        for row in result
    ):
        result = [
            row for row in result
            if not (
                row.get("record_type") == "programme"
                and row.get("category") == FELLOWSHIP_CONFIG.category
                and row.get("programme_id") == legacy_kleiner_id
            )
        ]

    for row in result:
        if row.get("record_type") != "programme":
            continue
        if row.get("programme_id") in valid_open_ids:
            row["is_live"] = True
            row.pop("needs_confirmation", None)
            row.pop("went_dead_at", None)
            continue
        if row.get("programme_id") not in needs_confirmation_ids:
            continue
        row.pop("programme_status", None)
        evidence = row.get("official_evidence")
        if isinstance(evidence, dict):
            evidence.pop("status", None)
            evidence.pop("programme_status", None)
        row["needs_confirmation"] = True
        row["is_live"] = False
        row.pop("went_dead_at", None)
    return result


def apply_verifications(rows: Iterable[Dict], verifications: Iterable[Dict], now) -> List[Dict]:
    verifications = list(verifications)
    applied = _core.apply_verifications(rows, verifications, now, config=FELLOWSHIP_CONFIG)
    return _postprocess(applied, verifications)


def load_verifications(path: str = VERIFICATIONS_PATH) -> List[Dict]:
    return _core.load_verifications(path)


def merge_programmes(records: Iterable[Dict], observations: Iterable[Dict], lake_path: str = OPPORTUNITIES_PATH, observations_path: str = OBSERVATIONS_PATH, now: Optional[str] = None) -> List[Dict]:
    return _core.merge_programmes(records, observations, lake_path, observations_path, now)


def collect(fetch: Callable[[str], str] = _core._default_fetch, checked_at: Optional[datetime] = None, lake_path: str = OPPORTUNITIES_PATH, observations_path: str = OBSERVATIONS_PATH) -> Dict:
    result = _core.collect(
        FELLOWSHIP_CONFIG,
        fetch=fetch,
        checked_at=checked_at,
        lake_path=lake_path,
        observations_path=observations_path,
    )
    verifications = load_verifications(FELLOWSHIP_CONFIG.verifications_path)
    merged = apply_verifications(
        _load_json(lake_path, []), verifications,
        datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
    _atomic_json(lake_path, merged)
    result["merged"] = merged
    return result


def _apply_verifications_cli(config: ProgrammeConfig = FELLOWSHIP_CONFIG) -> None:
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


def run_module_cli(config: ProgrammeConfig = FELLOWSHIP_CONFIG, argv=None) -> None:
    args = sys.argv[1:] if argv is None else argv
    if "--apply-verifications" in args:
        _apply_verifications_cli(config)
    else:
        result = collect()
        print(json.dumps({"records": len(result["records"]), "observations": len(result["observations"])}, indent=2))


if __name__ == "__main__":
    run_module_cli(FELLOWSHIP_CONFIG)
