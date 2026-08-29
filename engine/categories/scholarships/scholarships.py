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
    {"source_id": "scholarship-fulbright", "programme_id": "scholarship-fulbright-foreign-student-program", "programme_name": "Fulbright Foreign Student Program", "organizer": "U.S. Department of State / Institute of International Education", "official_url": "https://foreign.fulbrightonline.org/about/foreign-student-program", "allowed_path_hints": ["about/foreign-student-program"], "check_cadence": "monthly"},
    {"source_id": "scholarship-rhodes", "programme_id": "scholarship-rhodes", "programme_name": "Rhodes Scholarship", "organizer": "Rhodes Trust", "official_url": "https://www.rhodeshouse.ox.ac.uk/scholarships/the-rhodes-scholarship/", "allowed_path_hints": ["scholarships/the-rhodes-scholarship"], "check_cadence": "monthly"},
    {"source_id": "scholarship-gates-cambridge", "programme_id": "scholarship-gates-cambridge", "programme_name": "Gates Cambridge Scholarships", "organizer": "Gates Cambridge Trust", "official_url": "https://www.gatescambridge.org/apply/eligibility/", "allowed_path_hints": ["apply/eligibility"], "check_cadence": "monthly"},
    {"source_id": "scholarship-knight-hennessy", "programme_id": "scholarship-knight-hennessy", "programme_name": "Knight-Hennessy Scholars", "organizer": "Stanford University", "official_url": "https://knight-hennessy.stanford.edu/admission", "allowed_path_hints": ["admission"], "check_cadence": "monthly"},
    {"source_id": "scholarship-daad", "programme_id": "scholarship-daad", "programme_name": "DAAD Scholarships & Funding", "organizer": "DAAD", "official_url": "https://www.daad.de/en/studying-in-germany/scholarships/", "allowed_path_hints": ["en/studying-in-germany/scholarships"], "check_cadence": "monthly"},
    {"source_id": "scholarship-schwarzman", "programme_id": "scholarship-schwarzman", "programme_name": "Schwarzman Scholars", "organizer": "Schwarzman Scholars", "official_url": "https://www.schwarzmanscholars.org/admissions/", "allowed_path_hints": ["admissions"], "check_cadence": "monthly"},
    {"source_id": "scholarship-commonwealth-masters", "programme_id": "scholarship-commonwealth-masters", "programme_name": "Commonwealth Master's Scholarships", "organizer": "Commonwealth Scholarship Commission in the UK", "official_url": "https://cscuk.fcdo.gov.uk/scholarships/commonwealth-masters-scholarships/", "allowed_path_hints": ["scholarships/commonwealth-masters-scholarships"], "check_cadence": "monthly"},
    {"source_id": "scholarship-erasmus-mundus", "programme_id": "scholarship-erasmus-mundus-joint-masters", "programme_name": "Erasmus Mundus Joint Masters", "organizer": "European Commission", "official_url": "https://erasmus-plus.ec.europa.eu/opportunities/opportunities-for-individuals/students/erasmus-mundus-joint-masters", "allowed_path_hints": ["opportunities/opportunities-for-individuals/students/erasmus-mundus-joint-masters"], "check_cadence": "monthly"},
    {"source_id": "scholarship-stipendium-hungaricum", "programme_id": "scholarship-stipendium-hungaricum", "programme_name": "Stipendium Hungaricum", "organizer": "Tempus Public Foundation", "official_url": "https://stipendiumhungaricum.hu/", "allowed_path_hints": [""], "check_cadence": "monthly"},
    {"source_id": "scholarship-turkiye", "programme_id": "scholarship-turkiye", "programme_name": "Türkiye Scholarships", "organizer": "Presidency for Turks Abroad and Related Communities (YTB)", "official_url": "https://www.turkiyeburslari.gov.tr/", "allowed_path_hints": [""], "check_cadence": "monthly"},
)
SEEDS = SOURCE_REGISTRY
SEED_BY_URL = {seed["official_url"]: seed for seed in SOURCE_REGISTRY}
SOURCE_BY_ID = {seed["programme_id"]: seed for seed in SOURCE_REGISTRY}
OBSERVATIONS_PATH = os.path.join(OPERATIONS_DIR, "scholarship_programmes_observations.json")
VERIFICATIONS_PATH = os.path.join(OPERATIONS_DIR, "scholarship_programme_verifications.json")

SCHOLARSHIP_CONFIG = ProgrammeConfig(
    category="scholarship",
    opportunity_type="scholarship",
    source_registry=SOURCE_REGISTRY,
    observations_path=OBSERVATIONS_PATH,
    verifications_path=VERIFICATIONS_PATH,
)


def _base(seed, checked, evidence):
    return _core._base(seed, checked, evidence, SCHOLARSHIP_CONFIG)


def parse_programme(seed: Dict, html: str, checked_at: Optional[datetime] = None, final_url: Optional[str] = None) -> Tuple[Optional[Dict], Dict]:
    return _core.parse_programme(seed, html, checked_at, final_url, config=SCHOLARSHIP_CONFIG)


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
    """Keep only quote-backed Scholarship facts from manual verification."""
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
    applied = _core.apply_verifications(rows, verifications, now, config=SCHOLARSHIP_CONFIG)
    return _postprocess(applied, verifications)


def load_verifications(path: str = VERIFICATIONS_PATH) -> List[Dict]:
    return _core.load_verifications(path)


def merge_programmes(records: Iterable[Dict], observations: Iterable[Dict], lake_path: str = OPPORTUNITIES_PATH, observations_path: str = OBSERVATIONS_PATH, now: Optional[str] = None) -> List[Dict]:
    return _core.merge_programmes(records, observations, lake_path, observations_path, now)


def collect(fetch: Callable[[str], str] = _core._default_fetch, checked_at: Optional[datetime] = None, lake_path: str = OPPORTUNITIES_PATH, observations_path: str = OBSERVATIONS_PATH) -> Dict:
    result = _core.collect(
        SCHOLARSHIP_CONFIG,
        fetch=fetch,
        checked_at=checked_at,
        lake_path=lake_path,
        observations_path=observations_path,
    )
    verifications = load_verifications(SCHOLARSHIP_CONFIG.verifications_path)
    merged = apply_verifications(
        _load_json(lake_path, []), verifications,
        datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
    _atomic_json(lake_path, merged)
    result["merged"] = merged
    return result


def _apply_verifications_cli(config: ProgrammeConfig = SCHOLARSHIP_CONFIG) -> None:
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


def run_module_cli(config: ProgrammeConfig = SCHOLARSHIP_CONFIG, argv=None) -> None:
    args = sys.argv[1:] if argv is None else argv
    if "--apply-verifications" in args:
        _apply_verifications_cli(config)
    else:
        result = collect()
        print(json.dumps({"records": len(result["records"]), "observations": len(result["observations"])}, indent=2))


if __name__ == "__main__":
    run_module_cli(SCHOLARSHIP_CONFIG)
