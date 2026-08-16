#!/usr/bin/env python3
"""Verify the dated old-engine archive and its omitted-cache mappings.

This verifier is intentionally stdlib-only and does not require the legacy
source tree to exist. Use ``--compare-source`` before deletion when the source
is still available; the normal invocation verifies the durable archive after
migration.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Dict, Iterable, List

ARCHIVE_NAME = "opportunity-lake-oldengine-2026-08-16"
SCHEMA_VERSION = "1.0"


def _root() -> Path:
    return Path(__file__).resolve().parents[2]


def _archive() -> Path:
    return _root() / "archive" / ARCHIVE_NAME


def _safe_relative(value: str) -> Path:
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("unsafe archive path: {}".format(value))
    return path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_sums(path: Path) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        digest, sep, name = raw.partition("  ")
        if not sep or len(digest) != 64 or name in out:
            raise ValueError("invalid SHA256SUMS line: {}".format(raw))
        _safe_relative(name)
        out[name] = digest
    return out


def _verify_included(archive: Path, entries: Iterable[dict], sums: Dict[str, str]) -> List[str]:
    expected = {}
    errors: List[str] = []
    for entry in entries:
        rel = str(entry["path"])
        if rel in expected:
            errors.append("duplicate manifest path: {}".format(rel))
            continue
        expected[rel] = entry
        try:
            safe = _safe_relative(rel)
        except ValueError as exc:
            errors.append(str(exc))
            continue
        path = archive / safe
        if not path.is_file():
            errors.append("missing archived file: {}".format(rel))
            continue
        actual_size = path.stat().st_size
        actual_hash = _sha256(path)
        if actual_size != entry["size"]:
            errors.append("size mismatch: {}".format(rel))
        if actual_hash != entry["sha256"]:
            errors.append("manifest hash mismatch: {}".format(rel))
        if sums.get(rel) != actual_hash:
            errors.append("SHA256SUMS mismatch: {}".format(rel))
    if set(sums) != set(expected):
        errors.append("SHA256SUMS paths do not exactly match included_files")
    return errors


def _verify_excluded(root: Path, entries: Iterable[dict]) -> List[str]:
    errors: List[str] = []
    for entry in entries:
        try:
            active = root / _safe_relative(entry["active_path"])
        except ValueError as exc:
            errors.append(str(exc))
            continue
        if not active.is_file():
            errors.append("missing active duplicate mapping: {}".format(entry["active_path"]))
            continue
        actual_size = active.stat().st_size
        actual_hash = _sha256(active)
        if actual_size != entry["size"] or actual_hash != entry["sha256"]:
            errors.append("active duplicate mismatch: {}".format(entry["active_path"]))
    return errors


def _compare_source(root: Path, manifest: dict) -> List[str]:
    source = root / "oldengine"
    errors: List[str] = []
    if not source.is_dir():
        return ["--compare-source requested but oldengine is absent"]
    for entry in manifest["included_files"]:
        legacy = root / _safe_relative(entry["legacy_path"])
        if not legacy.is_file():
            errors.append("missing source file: {}".format(entry["legacy_path"]))
            continue
        if legacy.stat().st_size != entry["size"] or _sha256(legacy) != entry["sha256"]:
            errors.append("source mismatch: {}".format(entry["legacy_path"]))
    for entry in manifest["excluded_duplicate_caches"]:
        legacy = root / _safe_relative(entry["legacy_path"])
        if not legacy.is_file():
            errors.append("missing excluded source cache: {}".format(entry["legacy_path"]))
            continue
        if legacy.stat().st_size != entry["size"] or _sha256(legacy) != entry["sha256"]:
            errors.append("excluded source cache mismatch: {}".format(entry["legacy_path"]))
    return errors


def verify(compare_source: bool = False) -> None:
    root = _root()
    archive = _archive()
    manifest_path = archive / "manifest.json"
    sums_path = archive / "SHA256SUMS"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    errors: List[str] = []
    if manifest.get("schema_version") != SCHEMA_VERSION:
        errors.append("unsupported manifest schema")
    if manifest.get("source") != "oldengine":
        errors.append("manifest source is not oldengine")
    sums = _read_sums(sums_path)
    errors.extend(_verify_included(archive, manifest.get("included_files", []), sums))
    errors.extend(_verify_excluded(root, manifest.get("excluded_duplicate_caches", [])))
    if compare_source:
        errors.extend(_compare_source(root, manifest))
    if errors:
        raise SystemExit("archive verification failed:\n- " + "\n- ".join(errors))
    print("verified {} included files, {} excluded duplicate caches{}".format(
        len(manifest.get("included_files", [])),
        len(manifest.get("excluded_duplicate_caches", [])),
        " and source comparison" if compare_source else ""))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compare-source", action="store_true",
                        help="also compare included legacy files while oldengine exists")
    args = parser.parse_args()
    verify(compare_source=args.compare_source)


if __name__ == "__main__":
    main()
