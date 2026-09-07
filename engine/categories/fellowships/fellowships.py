from __future__ import annotations

import json
import os
import sys
import time
from copy import deepcopy
from datetime import datetime, timezone
from typing import Callable, Dict, Iterable, List, Optional, Tuple

from core import robots
from pipeline.resolve import _fetch_page

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

SEED_PATH = os.path.join(os.path.dirname(__file__), "fellowships_hubs.json")
REQUIRED_SEED_FIELDS = ("source_id", "programme_id", "programme_name", "organizer", "official_url", "allowed_path_hints", "check_cadence")


def _load_seed_registry(path: str = SEED_PATH) -> tuple:
    """Load and validate data-only fellowship seeds from the checked-in registry."""
    with open(path, encoding="utf-8") as handle:
        seeds = json.load(handle)
    if not isinstance(seeds, list):
        raise ValueError("fellowship seed registry must be a JSON array")
    seen_sources, seen_programmes = set(), set()
    validated = []
    for index, seed in enumerate(seeds):
        if not isinstance(seed, dict) or any(not seed.get(field) for field in REQUIRED_SEED_FIELDS):
            raise ValueError("seed {} is missing a required non-empty field".format(index))
        if set(seed) != set(REQUIRED_SEED_FIELDS):
            raise ValueError("seed {} contains fields outside the canonical schema".format(index))
        if seed["source_id"] in seen_sources or seed["programme_id"] in seen_programmes:
            raise ValueError("duplicate source_id or programme_id in seed {}".format(index))
        if not seed["official_url"].startswith(("https://", "http://")):
            raise ValueError("seed {} official_url must be an HTTP(S) URL".format(index))
        if not isinstance(seed["allowed_path_hints"], list) or not all(isinstance(item, str) for item in seed["allowed_path_hints"]):
            raise ValueError("seed {} allowed_path_hints must be a string list".format(index))
        seen_sources.add(seed["source_id"])
        seen_programmes.add(seed["programme_id"])
        validated.append(seed)
    return tuple(validated)


SOURCE_REGISTRY = _load_seed_registry()
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
    needs_confirmation_floor=True,
)


_RETRYABLE_HTTP = frozenset((403, 429))
FELLOWSHIP_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Version/18.6 Safari/605.1.15"
)


def _fellowship_fetch(url: str) -> Tuple[str, str]:
    """Fetch with initial-URL robots checks and one polite transient retry.

    Redirect destinations are returned by the shared resolver, but robots is
    intentionally checked only for the requested URL, matching the existing
    engine policy rather than claiming cross-host coverage.
    """
    allowed, why = robots.allowed(url)
    if not allowed:
        raise RuntimeError("robots_disallowed:{}".format(why))
    for attempt in range(2):
        status, final_url, html, error = _fetch_page(url, user_agent=FELLOWSHIP_BROWSER_UA)
        transient = status is None or status in _RETRYABLE_HTTP or (status is not None and status >= 500)
        if not error and status is not None and status < 400:
            return html, final_url
        if attempt == 0 and transient:
            time.sleep(1.0)
            allowed, why = robots.allowed(url)
            if not allowed:
                raise RuntimeError("robots_disallowed:{}".format(why))
            continue
        raise RuntimeError(error or "http_{}".format(status))
    raise RuntimeError("fellowship_fetch_exhausted")


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


def collect(fetch: Callable[[str], str] = _fellowship_fetch, checked_at: Optional[datetime] = None, lake_path: str = OPPORTUNITIES_PATH, observations_path: str = OBSERVATIONS_PATH) -> Dict:
    global SOURCE_REGISTRY, SEEDS, SEED_BY_URL, SOURCE_BY_ID, FELLOWSHIP_CONFIG
    SOURCE_REGISTRY = _load_seed_registry()
    SEEDS = SOURCE_REGISTRY
    SEED_BY_URL = {seed["official_url"]: seed for seed in SOURCE_REGISTRY}
    SOURCE_BY_ID = {seed["programme_id"]: seed for seed in SOURCE_REGISTRY}
    FELLOWSHIP_CONFIG = ProgrammeConfig(
        category="fellowship",
        opportunity_type="fellowship",
        source_registry=SOURCE_REGISTRY,
        observations_path=OBSERVATIONS_PATH,
        verifications_path=VERIFICATIONS_PATH,
        needs_confirmation_floor=True,
    )
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
