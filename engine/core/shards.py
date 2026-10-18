"""Per-category lake shards.

Jobs/internships stay in the main lake (``lake/opportunities.json``). Every
other category lives in its own shard (``lake/shards/<name>.json``) so a run
only restores, mutates, syncs and publishes that one category.

A row belongs to a shard by ``(record_type, category)``; anything that matches
no shard (jobs, internships, unknown programme categories) stays in main, so a
split never loses a row.
"""
from __future__ import annotations

import json
import os
from typing import Dict, Iterable, List, Optional, Tuple

from core.paths import LAKE_DIR

SHARDS_DIR = os.path.join(LAKE_DIR, "shards")
S3_SHARD_PREFIX = "lake/shards"
MAIN = "main"

# shard -> [(record_type, category or None for any)]
SHARD_SCOPES: Dict[str, List[Tuple[str, Optional[str]]]] = {
    "hackathons": [("hackathon", None)],
    "fellowships": [("programme", "fellowship")],
    "scholarships": [("programme", "scholarship")],
    "grants": [("programme", "grant")],
    "research": [("programme", "research")],
    "open_source": [("programme", "open-source-programmes"), ("contribution", None)],
    "startup": [("programme", "startup-founder")],
    "community": [("programme", "community")],
}

# Jobs/internships shard by ATS platform (the row's own `platform`, which is
# stable even when is_internship flips). `jobs-other` is the catch-all, so a
# job row always has a shard and a split never loses one.
JOB_SHARD_PLATFORMS: Dict[str, Tuple[str, ...]] = {
    "jobs-greenhouse": ("greenhouse",),
    "jobs-lever": ("lever",),
    "jobs-ashby": ("ashby",),
    "jobs-workable": ("workable",),
    "jobs-workday": ("workday",),
    "jobs-keka": ("keka",),
    "jobs-internships": ("unstop", "zshah101-list"),
}
JOB_OTHER = "jobs-other"
JOB_SHARDS = list(JOB_SHARD_PLATFORMS) + [JOB_OTHER]
CATEGORY_SHARDS = list(SHARD_SCOPES)
ALL_SHARDS = CATEGORY_SHARDS + JOB_SHARDS


def is_job_shard(name: str) -> bool:
    return name in JOB_SHARDS


def job_shard_of_platform(platform: Optional[str]) -> str:
    for name, plats in JOB_SHARD_PLATFORMS.items():
        if platform in plats:
            return name
    return JOB_OTHER


# Drop guard: ignore tiny shards (a 3 -> 1 change is noise, not data loss).
DROP_GUARD_MIN_ROWS = 10
DROP_GUARD_RATIO = 0.5


def shard_of(row: dict) -> str:
    """Return the shard name for a row, or MAIN."""
    if not isinstance(row, dict):
        return MAIN
    rtype, cat = row.get("record_type"), row.get("category")
    if not rtype:  # job / internship row
        return job_shard_of_platform(row.get("platform"))
    for name, scopes in SHARD_SCOPES.items():
        for t, c in scopes:
            if rtype == t and (c is None or cat == c):
                return name
    return MAIN


def split_rows(rows: Iterable[dict]) -> Dict[str, List[dict]]:
    out: Dict[str, List[dict]] = {MAIN: [], **{n: [] for n in ALL_SHARDS}}
    for r in rows:
        out[shard_of(r)].append(r)
    return out


def combine(main_rows: Iterable[dict], shards: Dict[str, List[dict]]) -> List[dict]:
    """Whole lake = main rows + shard rows. A present shard is authoritative:
    main rows of that shard's categories (stale pre-migration copies) are
    dropped so nothing is duplicated."""
    present = set(shards)
    out = [r for r in main_rows if shard_of(r) not in present]
    for name in sorted(shards):
        out.extend(shards[name])
    return out


def hidden_path(name: str, shards_dir: str = SHARDS_DIR) -> str:
    """Companion hidden store of a job shard (not published)."""
    if not is_job_shard(name):
        raise ValueError("only job shards have a hidden store: %r" % name)
    return os.path.join(shards_dir, name + ".hidden.json")


def shard_path(name: str, shards_dir: str = SHARDS_DIR) -> str:
    if name not in ALL_SHARDS:
        raise ValueError("unknown shard %r (valid: %s)" % (name, ", ".join(ALL_SHARDS)))
    return os.path.join(shards_dir, name + ".json")


def _read(path: str):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def save_shard_hidden(name: str, rows: List[dict], shards_dir: str = SHARDS_DIR) -> str:
    p = hidden_path(name, shards_dir)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(rows, fh, ensure_ascii=False)
    os.replace(tmp, p)
    return p


def load_shard(name: str, shards_dir: str = SHARDS_DIR) -> Optional[List[dict]]:
    p = shard_path(name, shards_dir)
    return _read(p) if os.path.exists(p) else None


def save_shard(name: str, rows: List[dict], shards_dir: str = SHARDS_DIR) -> str:
    p = shard_path(name, shards_dir)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(rows, fh, ensure_ascii=False)
    os.replace(tmp, p)
    return p


def load_all_shards(shards_dir: str = SHARDS_DIR) -> Dict[str, List[dict]]:
    out = {}
    for name in ALL_SHARDS:
        rows = load_shard(name, shards_dir)
        if rows is not None:
            out[name] = rows
    return out


def load_whole_lake(main_path: str, shards_dir: str = SHARDS_DIR) -> List[dict]:
    """Main lake combined with any shards present locally."""
    main = _read(main_path) if os.path.exists(main_path) else []
    return combine(main, load_all_shards(shards_dir))


def drop_guard(previous: int, new: int, forced: bool = False) -> Optional[str]:
    """Return an error message if the shard shrank by more than 50%."""
    if forced or previous < DROP_GUARD_MIN_ROWS:
        return None
    if new < previous * DROP_GUARD_RATIO:
        return ("row count dropped %d -> %d (>%d%%); refusing. Re-run with "
                "retire_force including this category if intended."
                % (previous, new, int((1 - DROP_GUARD_RATIO) * 100)))
    return None
