"""List internship opportunities from the canonical lake without collecting."""

from __future__ import annotations

import argparse
import json
import os

from core import filters
from core.paths import OPPORTUNITIES_PATH


def _load_json(path, default):
    if not os.path.exists(path):
        return default
    with open(path) as handle:
        value = json.load(handle)
    if not isinstance(value, type(default)):
        raise ValueError("invalid JSON shape in {}".format(path))
    return value


def _company_value(row):
    return row.get("company") or row.get("company_name") or ""


def list_internships(india=None, surfaced=None, platform=None, company=None,
                     foreign=False):
    """Return internship job rows from the canonical opportunity lake."""
    rows = [
        row for row in _load_json(OPPORTUNITIES_PATH, [])
        if row.get("record_type") is None and row.get("is_internship") is True
    ]
    if india is True:
        rows = [
            row for row in rows
            if row.get("location_bucket") in
            (filters.INDIA_LOCATED, filters.INDIA_REMOTE)
        ]
    if surfaced is True:
        rows = [row for row in rows if row.get("hidden_reason") in (None,)]
    if foreign is True:
        rows = [
            row for row in rows
            if filters.accessibility(row.get("location_bucket")) ==
            filters.ACCESS_FOREIGN_ONSITE
        ]
    if platform is not None:
        platform = str(platform).casefold()
        rows = [
            row for row in rows
            if str(row.get("platform", "")).casefold() == platform
        ]
    if company is not None:
        company = str(company).casefold()
        rows = [
            row for row in rows
            if str(_company_value(row)).casefold() == company
        ]
    rows.sort(key=lambda row: filters.access_rank(row.get("location_bucket")))
    return rows


def _display_location(row):
    location = row.get("location") or row.get("location_bucket") or ""
    if isinstance(location, list):
        return ", ".join(str(value) for value in location)
    return str(location)


def _list_cli():
    parser = argparse.ArgumentParser(
        description="List collected internships without collecting"
    )
    parser.add_argument(
        "--list", action="store_true",
        help="list internship rows from the canonical lake",
    )
    parser.add_argument("--india", action="store_true", default=None)
    parser.add_argument("--surfaced", action="store_true", default=None)
    parser.add_argument("--foreign", action="store_true", default=False)
    parser.add_argument("--platform")
    parser.add_argument("--company")
    args = parser.parse_args()
    if not args.list:
        parser.print_help()
        return
    rows = list_internships(
        india=args.india,
        surfaced=args.surfaced,
        platform=args.platform,
        company=args.company,
        foreign=args.foreign,
    )
    print("{} internship(s)".format(len(rows)))
    for row in rows[:5]:
        url = row.get("official_url") or row.get("application_url") or row.get("url", "")
        print("- {} — {} — {} — {}".format(
            row.get("title", ""),
            _company_value(row),
            _display_location(row),
            url,
        ))


if __name__ == "__main__":
    _list_cli()
