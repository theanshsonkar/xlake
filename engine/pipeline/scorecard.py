"""Per-category quality scorecard for non-job lake records."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from statistics import median
from typing import Dict, Iterable, List, Mapping, Optional
from urllib.parse import urlparse

from core.paths import DATA_ROOT, OPPORTUNITIES_PATH


METRIC_NAMES = (
    "total",
    "surfaced",
    "live",
    "needs_confirmation",
    "with_deadline",
    "with_status",
    "with_eligibility",
    "with_evidence",
    "distinct_official_hosts",
    "duplicate_official_urls",
    "stale_30d",
    "median_age_days",
)


def _nonempty(value: object) -> bool:
    if value is None or value is False:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return True


def _is_job_or_internship(record: Mapping[str, object]) -> bool:
    record_type = str(record.get("record_type") or "").strip().lower()
    category = str(record.get("category") or "").strip().lower()
    segment = str(record.get("segment") or "").strip().lower()
    if record_type in {"job", "jobs", "internship", "internships"}:
        return True
    if record.get("is_internship") is True:
        return True
    if segment in {"internship", "internships"}:
        return True
    if category in {"job", "jobs", "internship", "internships"}:
        return True
    # The legacy job store has no record_type; non-job records in this lake do.
    return not record_type


def _parse_timestamp(value: object) -> Optional[datetime]:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        try:
            parsed = datetime.combine(date.fromisoformat(text), datetime.min.time())
        except ValueError:
            return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _category(record: Mapping[str, object]) -> str:
    value = record.get("category")
    return str(value).strip() if value is not None and str(value).strip() else "uncategorized"


def score(records: Iterable[Mapping[str, object]], now: datetime) -> Dict[str, Dict]:
    """Return quality metrics grouped by category.

    ``now`` is supplied by the caller so this function is deterministic and
    straightforward to test. Missing or invalid last-checked timestamps count
    as stale, while valid timestamps older than 30 days also count as stale.
    """
    current = _as_utc(now)
    grouped: Dict[str, List[Mapping[str, object]]] = defaultdict(list)
    for record in records:
        if not _is_job_or_internship(record):
            grouped[_category(record)].append(record)

    result: Dict[str, Dict] = {}
    for category in sorted(grouped):
        rows = grouped[category]
        urls = [
            str(row.get("official_url")).strip()
            for row in rows
            if _nonempty(row.get("official_url"))
        ]
        url_counts = Counter(urls)
        hosts = set()
        for url in urls:
            try:
                host = urlparse(url).hostname
            except ValueError:
                host = None
            if host:
                hosts.add(host.lower())

        ages: List[float] = []
        stale = 0
        for row in rows:
            checked = _parse_timestamp(
                row.get("last_checked_at") or row.get("checked_at")
            )
            if checked is None:
                stale += 1
            else:
                age = max(0.0, (current - _as_utc(checked)).total_seconds() / 86400)
                ages.append(age)
                if age > 30:
                    stale += 1

        result[category] = {
            "total": len(rows),
            "surfaced": sum(bool(row.get("surfaced")) for row in rows),
            "live": sum(bool(row.get("is_live")) for row in rows),
            "needs_confirmation": sum(
                bool(row.get("needs_confirmation")) for row in rows
            ),
            "with_deadline": sum(
                row.get("deadline") is not None
                or row.get("registration_deadline") is not None
                for row in rows
            ),
            "with_status": sum(
                _nonempty(row.get("programme_status"))
                or _nonempty(row.get("status"))
                for row in rows
            ),
            "with_eligibility": sum(
                _nonempty(row.get("eligibility")) for row in rows
            ),
            "with_evidence": sum(
                _nonempty(row.get("official_evidence")) for row in rows
            ),
            "distinct_official_hosts": len(hosts),
            "duplicate_official_urls": sum(
                count > 1 for count in url_counts.values()
            ),
            "stale_30d": stale / len(rows) if rows else 0.0,
            "median_age_days": median(ages) if ages else None,
        }
    return result


def _load(path: str) -> List[Mapping[str, object]]:
    if not os.path.isfile(path):
        raise FileNotFoundError("scorecard input file not found: {}".format(path))
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, list):
        raise ValueError("scorecard input must contain a JSON list: {}".format(path))
    return data


def _flatten_paths(values: Optional[List[List[str]]]) -> List[str]:
    if not values:
        return [OPPORTUNITIES_PATH]
    return [path for group in values for path in group]


def _print_table(results: Dict[str, Dict]) -> None:
    headers = ("category",) + METRIC_NAMES
    print(" ".join(headers))
    for category, metrics in results.items():
        values = [category]
        for name in METRIC_NAMES:
            value = metrics[name]
            if name == "stale_30d":
                values.append("{:.3f}".format(value))
            elif name == "median_age_days" and isinstance(value, float):
                values.append("{:.1f}".format(value))
            else:
                values.append(str(value))
        print(" ".join(values))


def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--path", action="append", nargs="+", dest="paths", metavar="PATH"
    )
    parser.add_argument("--json", dest="json_path", metavar="OUT.json")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = _parse_args(argv)
    paths = _flatten_paths(args.paths)
    try:
        records: List[Mapping[str, object]] = []
        for path in paths:
            records.extend(_load(path))
        results = score(records, datetime.now(timezone.utc))
        if args.json_path:
            output = os.path.abspath(os.path.expanduser(args.json_path))
            data_root = os.path.abspath(DATA_ROOT)
            if output == data_root or output.startswith(data_root + os.sep):
                raise ValueError("scorecard will not write inside engine/data: {}".format(output))
            with open(output, "w", encoding="utf-8") as handle:
                json.dump(results, handle, indent=2, sort_keys=True)
                handle.write("\n")
        _print_table(results)
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print("error: {}".format(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
