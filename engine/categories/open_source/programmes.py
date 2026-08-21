from __future__ import annotations

import os
from datetime import datetime
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
    parse_dates, run_module_cli, validate_verification,
)

SOURCE_REGISTRY = (
    {"source_id": "mlh-open-source", "programme_id": "mlh-fellowship-open-source", "programme_name": "MLH Fellowship Open Source Track", "organizer": "Major League Hacking", "official_url": "https://fellowship.mlh.io/programs/open-source", "allowed_path_hints": ["programs/open-source"], "check_cadence": "daily"},
    {"source_id": "google-summer-of-code", "programme_id": "google-summer-of-code", "programme_name": "Google Summer of Code", "organizer": "Google", "official_url": "https://summerofcode.withgoogle.com/", "allowed_path_hints": [], "check_cadence": "daily"},
    {"source_id": "outreachy", "programme_id": "outreachy", "programme_name": "Outreachy", "organizer": "Outreachy", "official_url": "https://www.outreachy.org/", "allowed_path_hints": [], "check_cadence": "daily"},
    {"source_id": "lfx-mentorship", "programme_id": "lfx-mentorship", "programme_name": "LFX Mentorship", "organizer": "The Linux Foundation", "official_url": "https://lfx.linuxfoundation.org/tools/mentorship", "allowed_path_hints": ["tools/mentorship"], "check_cadence": "daily"},
    {"source_id": "riscv-international-mentorship", "programme_id": "riscv-international-mentorship", "programme_name": "RISC-V International Mentorship", "organizer": "RISC-V International", "official_url": "https://riscv.org/community/mentorship/", "allowed_path_hints": ["community/mentorship"], "check_cadence": "daily"},
    {"source_id": "kde-season-of-kde", "programme_id": "kde-season-of-kde", "programme_name": "KDE Season of KDE", "organizer": "KDE", "official_url": "https://season.kde.org/", "allowed_path_hints": [], "check_cadence": "daily"},
    {"source_id": "summer-of-bitcoin", "programme_id": "summer-of-bitcoin", "programme_name": "Summer of Bitcoin", "organizer": "Summer of Bitcoin", "official_url": "https://www.summerofbitcoin.org/", "allowed_path_hints": [], "check_cadence": "daily"},
    {"source_id": "julia-summer-of-code", "programme_id": "julia-summer-of-code", "programme_name": "Julia Summer of Code", "organizer": "Julia Language", "official_url": "https://julialang.org/jsoc/", "allowed_path_hints": [], "check_cadence": "daily"},
    {"source_id": "ospp", "programme_id": "ospp", "programme_name": "Open Source Promotion Plan", "organizer": "ISCAS", "official_url": "https://summer-ospp.ac.cn/", "allowed_path_hints": [], "check_cadence": "daily"},
    {"source_id": "linux-kernel-mentorship", "programme_id": "linux-kernel-mentorship", "programme_name": "Linux Kernel Mentorship Program", "organizer": "Linux Foundation", "official_url": "https://wiki.linuxfoundation.org/lkmp", "allowed_path_hints": [], "check_cadence": "daily"},
    {"source_id": "hyperledger-mentorship", "programme_id": "hyperledger-mentorship", "programme_name": "Hyperledger Mentorship", "organizer": "Linux Foundation", "official_url": "https://wiki.hyperledger.org/display/INTERN/", "allowed_path_hints": [], "check_cadence": "daily"},
    {"source_id": "open-mainframe-mentorship", "programme_id": "open-mainframe-mentorship", "programme_name": "Open Mainframe Project Mentorship", "organizer": "Open Mainframe Project", "official_url": "https://www.openmainframeproject.org/projects/mentorship-program", "allowed_path_hints": [], "check_cadence": "daily"},
    {"source_id": "hacktoberfest", "programme_id": "hacktoberfest", "programme_name": "Hacktoberfest", "organizer": "DigitalOcean", "official_url": "https://hacktoberfest.com/", "allowed_path_hints": [], "check_cadence": "daily"},
    {"source_id": "24-pull-requests", "programme_id": "24-pull-requests", "programme_name": "24 Pull Requests", "organizer": "24 Pull Requests", "official_url": "https://24pullrequests.com/", "allowed_path_hints": [], "check_cadence": "daily"},
    {"source_id": "igalia-coding-experience", "programme_id": "igalia-coding-experience", "programme_name": "Igalia Coding Experience", "organizer": "Igalia", "official_url": "https://www.igalia.com/coding-experience/", "allowed_path_hints": [], "check_cadence": "daily"},
    {"source_id": "xorg-evoc", "programme_id": "xorg-evoc", "programme_name": "X.Org Endless Vacation of Code", "organizer": "X.Org Foundation", "official_url": "https://www.x.org/wiki/XorgEVoC/", "allowed_path_hints": [], "check_cadence": "daily"},
    {"source_id": "processing-foundation-fellowship", "programme_id": "processing-foundation-fellowship", "programme_name": "Processing Foundation Fellowship", "organizer": "Processing Foundation", "official_url": "https://processingfoundation.org/fellowships/", "allowed_path_hints": [], "check_cadence": "daily"},
    {"source_id": "fossasia-codeheat", "programme_id": "fossasia-codeheat", "programme_name": "FOSSASIA Codeheat", "organizer": "FOSSASIA", "official_url": "https://codeheat.org/", "allowed_path_hints": [], "check_cadence": "daily"},
    {"source_id": "c4gt", "programme_id": "c4gt", "programme_name": "Code for GovTech (C4GT)", "organizer": "Code for GovTech", "official_url": "https://www.codeforgovtech.in/", "allowed_path_hints": [], "check_cadence": "daily"},
    {"source_id": "gssoc", "programme_id": "gssoc", "programme_name": "GirlScript Summer of Code", "organizer": "GirlScript Foundation", "official_url": "https://gssoc.girlscript.org/", "allowed_path_hints": [], "check_cadence": "daily"},
    {"source_id": "social-summer-of-code", "programme_id": "social-summer-of-code", "programme_name": "Social Summer of Code", "organizer": "Social", "official_url": "https://socialsummerofcode.com/", "allowed_path_hints": [], "check_cadence": "daily"},
    {"source_id": "social-winter-of-code", "programme_id": "social-winter-of-code", "programme_name": "Social Winter of Code", "organizer": "Social", "official_url": "https://swoc.in/", "allowed_path_hints": [], "check_cadence": "daily"},
    {"source_id": "fossee-summer-fellowship", "programme_id": "fossee-summer-fellowship", "programme_name": "FOSSEE Summer Fellowship", "organizer": "FOSSEE, IIT Bombay", "official_url": "https://fossee.in/", "allowed_path_hints": [], "check_cadence": "daily"},
    {"source_id": "kwoc", "programme_id": "kwoc", "programme_name": "Kharagpur Winter of Code", "organizer": "KOSS, IIT Kharagpur", "official_url": "https://kwoc.kossiitkgp.org/", "allowed_path_hints": [], "check_cadence": "daily"},
    {"source_id": "devscript-woc", "programme_id": "devscript-woc", "programme_name": "DevScript Winter of Code", "organizer": "DevScript", "official_url": "https://devscript.tech/woc/", "allowed_path_hints": [], "check_cadence": "daily"},
    {"source_id": "dwoc", "programme_id": "dwoc", "programme_name": "Delta Winter of Code", "organizer": "Delta, NIT Trichy", "official_url": "https://dwoc.io/", "allowed_path_hints": [], "check_cadence": "daily"},
    {"source_id": "foss-overflow", "programme_id": "foss-overflow", "programme_name": "FOSS Overflow", "organizer": "OpenLake, IIT Bhilai", "official_url": "https://fossoverflow.dev/", "allowed_path_hints": [], "check_cadence": "daily"},
    {"source_id": "jgec-woc", "programme_id": "jgec-woc", "programme_name": "JGEC Winter of Code", "organizer": "JGEC", "official_url": "https://jwoc.tech/", "allowed_path_hints": [], "check_cadence": "daily"},
    {"source_id": "njack-woc", "programme_id": "njack-woc", "programme_name": "NJACK Winter of Code", "organizer": "NJACK, IIT Patna", "official_url": "https://njackwinterofcode.github.io/", "allowed_path_hints": [], "check_cadence": "daily"},
    {"source_id": "opencode-iiita", "programme_id": "opencode-iiita", "programme_name": "OpenCode IIITA", "organizer": "IIIT Allahabad", "official_url": "https://opencodeiiita.github.io/", "allowed_path_hints": [], "check_cadence": "daily"},
    {"source_id": "cross-woc", "programme_id": "cross-woc", "programme_name": "Cross Winter of Code", "organizer": "IEEE DTU", "official_url": "https://crosswoc.ieeedtu.in/", "allowed_path_hints": [], "check_cadence": "daily"},
    {"source_id": "summer-of-nix", "programme_id": "summer-of-nix", "programme_name": "Summer of Nix", "organizer": "NixOS Foundation", "official_url": "https://summer.nixos.org/", "allowed_path_hints": [], "check_cadence": "daily"},
    {"source_id": "ethereum-protocol-fellowship", "programme_id": "ethereum-protocol-fellowship", "programme_name": "Ethereum Protocol Fellowship", "organizer": "Ethereum Foundation", "official_url": "https://ps.ethereum.foundation/fellowship", "allowed_path_hints": ["fellowship"], "check_cadence": "daily"},
    {"source_id": "sovereign-tech-fellowship", "programme_id": "sovereign-tech-fellowship", "programme_name": "Sovereign Tech Fellowship", "organizer": "Sovereign Tech Agency", "official_url": "https://www.sovereign.tech/programs/fellowship", "allowed_path_hints": ["programs/fellowship"], "check_cadence": "daily"},
    {"source_id": "sequoia-oss-fellowship", "programme_id": "sequoia-oss-fellowship", "programme_name": "Sequoia Open Source Fellowship", "organizer": "Sequoia Capital", "official_url": "https://www.sequoiacap.com/oss", "allowed_path_hints": ["oss"], "check_cadence": "daily"},
    {"source_id": "djangonaut-space", "programme_id": "djangonaut-space", "programme_name": "Djangonaut Space", "organizer": "Djangonaut Space", "official_url": "https://djangonaut.space/", "allowed_path_hints": [], "check_cadence": "daily"},
    {"source_id": "swift-mentorship", "programme_id": "swift-mentorship", "programme_name": "Swift Mentorship Program", "organizer": "Swift.org", "official_url": "https://www.swift.org/mentorship/", "allowed_path_hints": ["mentorship"], "check_cadence": "daily"},
    {"source_id": "kubernetes-release-shadow", "programme_id": "kubernetes-release-shadow", "programme_name": "Kubernetes Release Shadow Program", "organizer": "Kubernetes (CNCF)", "official_url": "https://github.com/kubernetes/sig-release/blob/master/release-team/shadows.md", "allowed_path_hints": ["kubernetes/sig-release"], "check_cadence": "daily"},
    {"source_id": "open-source-research-experience", "programme_id": "open-source-research-experience", "programme_name": "Open Source Research Experience", "organizer": "UC Santa Cruz Open Source Program Office", "official_url": "https://ucsc-ospo.github.io/osre/", "allowed_path_hints": ["osre"], "check_cadence": "daily"},
    {"source_id": "sktime-mentorship", "programme_id": "sktime-mentorship", "programme_name": "sktime Mentorship Program", "organizer": "sktime", "official_url": "https://www.sktime.net/docs/get-involved/mentoring/", "allowed_path_hints": ["get-involved/mentoring"], "check_cadence": "daily"},
    {"source_id": "european-summer-of-code", "programme_id": "european-summer-of-code", "programme_name": "European Summer of Code", "organizer": "European Summer of Code", "official_url": "https://www.esoc.dev/", "allowed_path_hints": [], "check_cadence": "daily"},
)
SEEDS = SOURCE_REGISTRY
SEED_BY_URL = {seed["official_url"]: seed for seed in SOURCE_REGISTRY}
SOURCE_BY_ID = {seed["programme_id"]: seed for seed in SOURCE_REGISTRY}
OBSERVATIONS_PATH = os.path.join(OPERATIONS_DIR, "programmes_observations.json")
VERIFICATIONS_PATH = os.path.join(OPERATIONS_DIR, "programme_verifications.json")

OPEN_SOURCE_CONFIG = ProgrammeConfig(
    category="open-source-programmes",
    opportunity_type="open_source_programme",
    source_registry=SOURCE_REGISTRY,
    observations_path=OBSERVATIONS_PATH,
    verifications_path=VERIFICATIONS_PATH,
)


def _base(seed, checked, evidence):
    return _core._base(seed, checked, evidence, OPEN_SOURCE_CONFIG)


def parse_programme(seed: Dict, html: str, checked_at: Optional[datetime] = None, final_url: Optional[str] = None) -> Tuple[Optional[Dict], Dict]:
    return _core.parse_programme(seed, html, checked_at, final_url, config=OPEN_SOURCE_CONFIG)


def apply_verifications(rows: Iterable[Dict], verifications: Iterable[Dict], now) -> List[Dict]:
    return _core.apply_verifications(rows, verifications, now, config=OPEN_SOURCE_CONFIG)


def load_verifications(path: str = VERIFICATIONS_PATH) -> List[Dict]:
    return _core.load_verifications(path)


def merge_programmes(records: Iterable[Dict], observations: Iterable[Dict], lake_path: str = OPPORTUNITIES_PATH, observations_path: str = OBSERVATIONS_PATH, now: Optional[str] = None) -> List[Dict]:
    return _core.merge_programmes(records, observations, lake_path, observations_path, now)


def collect(fetch: Callable[[str], str] = _core._default_fetch, checked_at: Optional[datetime] = None, lake_path: str = OPPORTUNITIES_PATH, observations_path: str = OBSERVATIONS_PATH) -> Dict:
    return _core.collect(
        OPEN_SOURCE_CONFIG,
        fetch=fetch,
        checked_at=checked_at,
        lake_path=lake_path,
        observations_path=observations_path,
    )


if __name__ == "__main__":
    run_module_cli(OPEN_SOURCE_CONFIG)
