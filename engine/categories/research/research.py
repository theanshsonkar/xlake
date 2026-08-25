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
    {"source_id": "mitacs-globalink-gri", "programme_id": "research-mitacs-globalink-research-internship", "programme_name": "Mitacs Globalink Research Internship", "organizer": "Mitacs", "official_url": "https://www.mitacs.ca/our-programs/globalink-research-internship-students/", "allowed_path_hints": ["our-programs/globalink-research-internship-students", "globalink"], "check_cadence": "monthly"},
    {"source_id": "daad-rise-germany", "programme_id": "research-daad-rise-germany", "programme_name": "DAAD RISE Germany (Research Internships in Science and Engineering)", "organizer": "DAAD (German Academic Exchange Service)", "official_url": "https://www.daad.de/rise/en/", "allowed_path_hints": ["rise"], "check_cadence": "monthly"},
    {"source_id": "cern-summer-student", "programme_id": "research-cern-summer-student", "programme_name": "CERN Summer Student Programme", "organizer": "CERN", "official_url": "https://home.cern/summer-student-programme/", "allowed_path_hints": ["summer-student-programme", "summer"], "check_cadence": "monthly"},
    {"source_id": "desy-summer-student", "programme_id": "research-desy-summer-student", "programme_name": "DESY Summer Student Programme", "organizer": "DESY (Deutsches Elektronen-Synchrotron)", "official_url": "https://summerstudents.desy.de/", "allowed_path_hints": ["application", ""], "check_cadence": "monthly"},
    {"source_id": "eth-zurich-ssrf", "programme_id": "research-eth-zurich-summer-research-fellowship", "programme_name": "ETH Zurich Student Summer Research Fellowship", "organizer": "ETH Zurich – Department of Computer Science", "official_url": "https://www.inf.ethz.ch/studies/summer-research-fellowship.html", "allowed_path_hints": ["studies/summer-research-fellowship", "summer-research-fellowship"], "check_cadence": "monthly"},
    {"source_id": "epfl-summer", "programme_id": "research-epfl-summer-research", "programme_name": "Summer@EPFL Research Fellowship", "organizer": "EPFL – School of Computer and Communication Sciences", "official_url": "https://summer.epfl.ch/", "allowed_path_hints": [""], "check_cadence": "monthly"},
    {"source_id": "amgen-scholars", "programme_id": "research-amgen-scholars", "programme_name": "Amgen Scholars Program", "organizer": "Amgen Foundation", "official_url": "https://amgenscholars.com/", "allowed_path_hints": [""], "check_cadence": "monthly"},
    {"source_id": "caltech-surf", "programme_id": "research-caltech-surf", "programme_name": "Caltech Summer Undergraduate Research Fellowships (SURF)", "organizer": "Caltech – Student-Faculty Programs", "official_url": "https://sfp.caltech.edu/undergraduate-research/programs/surf", "allowed_path_hints": ["undergraduate-research/programs/surf", "surf"], "check_cadence": "monthly"},
    {"source_id": "riken-ipa", "programme_id": "research-riken-ipa", "programme_name": "RIKEN International Program Associate (IPA)", "organizer": "RIKEN", "official_url": "https://www.riken.jp/en/careers/programs/ipa/index.html", "allowed_path_hints": ["careers/programs/ipa", "ipa"], "check_cadence": "monthly"},
    {"source_id": "nsf-reu", "programme_id": "research-nsf-reu", "programme_name": "NSF Research Experiences for Undergraduates (REU)", "organizer": "U.S. National Science Foundation (NSF)", "official_url": "https://www.nsf.gov/funding/initiatives/reu", "allowed_path_hints": ["funding/initiatives/reu", "reu"], "check_cadence": "monthly"},
)
SEEDS = SOURCE_REGISTRY
SEED_BY_URL = {seed["official_url"]: seed for seed in SOURCE_REGISTRY}
SOURCE_BY_ID = {seed["programme_id"]: seed for seed in SOURCE_REGISTRY}
OBSERVATIONS_PATH = os.path.join(OPERATIONS_DIR, "research_programmes_observations.json")
VERIFICATIONS_PATH = os.path.join(OPERATIONS_DIR, "research_programme_verifications.json")

RESEARCH_CONFIG = ProgrammeConfig(
    category="research",
    opportunity_type="research_programme",
    source_registry=SOURCE_REGISTRY,
    observations_path=OBSERVATIONS_PATH,
    verifications_path=VERIFICATIONS_PATH,
)


def _base(seed, checked, evidence):
    return _core._base(seed, checked, evidence, RESEARCH_CONFIG)


def parse_programme(seed: Dict, html: str, checked_at: Optional[datetime] = None, final_url: Optional[str] = None) -> Tuple[Optional[Dict], Dict]:
    return _core.parse_programme(seed, html, checked_at, final_url, config=RESEARCH_CONFIG)


def apply_verifications(rows: Iterable[Dict], verifications: Iterable[Dict], now) -> List[Dict]:
    return _core.apply_verifications(rows, verifications, now, config=RESEARCH_CONFIG)


def load_verifications(path: str = VERIFICATIONS_PATH) -> List[Dict]:
    return _core.load_verifications(path)


def merge_programmes(records: Iterable[Dict], observations: Iterable[Dict], lake_path: str = OPPORTUNITIES_PATH, observations_path: str = OBSERVATIONS_PATH, now: Optional[str] = None) -> List[Dict]:
    return _core.merge_programmes(records, observations, lake_path, observations_path, now)


def collect(fetch: Callable[[str], str] = _core._default_fetch, checked_at: Optional[datetime] = None, lake_path: str = OPPORTUNITIES_PATH, observations_path: str = OBSERVATIONS_PATH) -> Dict:
    return _core.collect(
        RESEARCH_CONFIG,
        fetch=fetch,
        checked_at=checked_at,
        lake_path=lake_path,
        observations_path=observations_path,
    )


if __name__ == "__main__":
    run_module_cli(RESEARCH_CONFIG)
