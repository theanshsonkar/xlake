#!/usr/bin/env python3
"""Backfill earliest first_seen values from remote history."""

from collections import Counter
from datetime import datetime
import json
import os
import sys


ENGINE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ENGINE_DIR)

from core.paths import OPPORTUNITIES_HISTORY_PATH, OPPORTUNITIES_PATH, OPERATIONS_DIR

DATA_DIR = OPERATIONS_DIR
HISTORY_PATH = OPPORTUNITIES_HISTORY_PATH
JOBS_PATH = OPPORTUNITIES_PATH
REPORT_PATH = os.path.join(DATA_DIR, "first_seen_backfill_report.json")

from pipeline.sweep import _key  # noqa: E402


def parse_timestamp(value):
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def load_jobs_container(path):
    with open(path) as fh:
        value = json.load(fh)
    if isinstance(value, list):
        return value, "list"
    if isinstance(value, dict):
        list_values = [(key, item) for key, item in value.items()
                       if isinstance(item, list)]
        if len(list_values) != 1:
            raise ValueError("jobs.json dict wrapper must contain one list")
        key, rows = list_values[0]
        return rows, "dict wrapper ({})".format(key)
    raise ValueError("jobs.json must be a list or dict wrapper")


def main():
    with open(HISTORY_PATH) as fh:
        history_rows = json.load(fh)
    if not isinstance(history_rows, list):
        raise ValueError("history must be a list")

    hist = {}
    hist_times = {}
    for row in history_rows:
        timestamp = parse_timestamp(row.get("first_seen"))
        if timestamp is None:
            continue
        key = _key(row)
        if key not in hist_times or timestamp < hist_times[key]:
            hist_times[key] = timestamp
            hist[key] = row["first_seen"]

    jobs, jobs_shape = load_jobs_container(JOBS_PATH)
    rows_total = len(jobs)
    matched = 0
    changed = 0
    unchanged = 0
    missing_or_unparseable = 0
    filled_missing = 0
    changed_dates = Counter()
    job_keys = set()

    for row in jobs:
        key = _key(row)
        job_keys.add(key)
        current = parse_timestamp(row.get("first_seen"))
        if key in hist:
            matched += 1
        if current is None:
            missing_or_unparseable += 1
            if key in hist:
                row["first_seen"] = hist[key]
                filled_missing += 1
            continue
        if key not in hist:
            continue
        historical_time = hist_times[key]
        if historical_time < current:
            row["first_seen"] = hist[key]
            changed += 1
            changed_dates[historical_time.date().isoformat()] += 1
        else:
            unchanged += 1

    unmatched_history_keys = len(set(hist) - job_keys)
    report = {
        "rows_total": rows_total,
        "history_rows": len(history_rows),
        "history_unique_keys": len(hist),
        "matched": matched,
        "changed": changed,
        "unchanged_because_not_earlier": unchanged,
        "unmatched_history_keys": unmatched_history_keys,
        "changed_first_seen_dates": dict(sorted(changed_dates.items())),
        "missing_or_unparseable_first_seen": missing_or_unparseable,
        "missing_or_unparseable_filled": filled_missing,
        "jobs_shape": jobs_shape,
    }

    tmp_path = JOBS_PATH + ".tmp"
    with open(tmp_path, "w") as fh:
        json.dump(jobs, fh, indent=1)
    os.replace(tmp_path, JOBS_PATH)

    with open(REPORT_PATH, "w") as fh:
        json.dump(report, fh, indent=1)

    for name, value in report.items():
        print("{}: {}".format(name, value))


if __name__ == "__main__":
    main()
