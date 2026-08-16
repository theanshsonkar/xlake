"""Canonical absolute paths for the operational engine tree.

The engine is run from ``engine/`` in normal operation, but paths are derived
from this package so commands and tests do not depend on the caller's cwd.
``LAKE_RAW_DIR`` remains an explicit override for private HTTP recordings.
"""
from __future__ import annotations

import os
from pathlib import Path

ENGINE_ROOT = str(Path(__file__).resolve().parents[1])
DATA_ROOT = os.path.join(ENGINE_ROOT, "data")
LAKE_DIR = os.path.join(DATA_ROOT, "lake")
OPERATIONS_DIR = os.path.join(DATA_ROOT, "operations")
_raw_override = os.environ.get("LAKE_RAW_DIR")
if _raw_override:
    _raw_path = Path(_raw_override).expanduser()
    if not _raw_path.is_absolute():
        _raw_path = Path(ENGINE_ROOT) / _raw_path
    RAW_DIR = str(_raw_path.resolve())
else:
    RAW_DIR = os.path.join(DATA_ROOT, "raw")
DISCOVERY_CACHE_DIR = os.path.join(DATA_ROOT, "raw", "discovery-cache")
FIXTURES_DIR = os.path.join(ENGINE_ROOT, "fixtures")

OPPORTUNITIES_PATH = os.path.join(LAKE_DIR, "opportunities.json")
HIDDEN_PATH = os.path.join(LAKE_DIR, "hidden.json")
OPPORTUNITIES_HISTORY_PATH = os.path.join(LAKE_DIR, "opportunities_history.json")
REGISTRY_PATH = os.path.join(OPERATIONS_DIR, "registry.json")
RUNS_PATH = os.path.join(OPERATIONS_DIR, "runs.jsonl")
TIER_STATE_PATH = os.path.join(OPERATIONS_DIR, "tier_state.json")
PAGEREADER_STATE_PATH = os.path.join(OPERATIONS_DIR, "pagereader_state.json")
PAGEREADER_TARGETS_PATH = os.path.join(OPERATIONS_DIR, "pagereader_targets.json")
PAGEREADER_ROWS_PATH = os.path.join(OPERATIONS_DIR, "pagereader_rows.json")
COMPANIES_PATH = os.path.join(OPERATIONS_DIR, "companies.txt")


def ensure_parent(path: str) -> None:
    """Create the parent directory for an active output path."""
    os.makedirs(os.path.dirname(path), exist_ok=True)


def ensure_data_dirs() -> None:
    """Create canonical writable roots without touching existing artifacts."""
    for directory in (LAKE_DIR, OPERATIONS_DIR, RAW_DIR, DISCOVERY_CACHE_DIR):
        os.makedirs(directory, exist_ok=True)
