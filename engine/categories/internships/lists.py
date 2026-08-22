from __future__ import annotations

import argparse
import json
import os
import tempfile
from datetime import datetime, timezone
from urllib import request
from urllib.parse import urlsplit

from core import filters
from core.paths import OPPORTUNITIES_PATH


SOURCE_URL = (
    "https://raw.githubusercontent.com/zshah101/"
    "Automated-List-Of-Summer-2027-and-Fall-2026-Tech-Internships/"
    "main/docs/api/jobs.json"
)
PAGES_FALLBACK = (
    "https://zshah101.github.io/Automated-List-Of-Summer-2027-and-Fall-2026-Tech-Internships/"
    "api/jobs.json"
)
PLATFORM = "zshah101-list"
SOURCE_LIST = "zshah101/Automated-List-Of-Summer-2027-and-Fall-2026-Tech-Internships"
SOURCE_ATTRIBUTION = "MIT © Shah Zain"
RECONFIRM_WINDOW_DAYS = 7
USER_AGENT = "Mozilla/5.0 (compatible; OpportunityRadarBot/1.0)"
BLOCKED_URL_HOSTS = ("github.com", "github.io", "dreamworkhq.com")


def _normalize_url(u):
    """Use the same job URL normalization as pipeline.sweep._key."""
    return (u or "").strip().rstrip("/").lower()


def _load_json(path, default):
    if not os.path.exists(path):
        return default
    with open(path) as handle:
        value = json.load(handle)
    if not isinstance(value, type(default)):
        raise ValueError("invalid JSON shape in {}".format(path))
    return value


def _atomic_json(path, value):
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".internship-lists-", dir=directory)
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(value, handle, indent=1)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _parse_timestamp(value):
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _age_days(value, checked_at):
    parsed = _parse_timestamp(value)
    checked = _parse_timestamp(checked_at)
    if parsed is None or checked is None:
        return None
    return (checked - parsed).days


def _usable_official_url(value):
    if not isinstance(value, str):
        return False
    try:
        parts = urlsplit(value)
        host = (parts.hostname or "").casefold()
    except ValueError:
        return False
    if parts.scheme.casefold() not in ("http", "https") or not host:
        return False
    return not any(blocked in host for blocked in BLOCKED_URL_HOSTS)


def _fetch_json(url):
    try:
        req = request.Request(
            url,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        )
        with request.urlopen(req, timeout=20) as response:
            value = json.loads(response.read().decode("utf-8"))
        if not isinstance(value, dict) or not isinstance(value.get("jobs"), list):
            return None
        return value
    except Exception:
        return None


def _default_fetch():
    for url in (SOURCE_URL, PAGES_FALLBACK):
        value = _fetch_json(url)
        if value is not None:
            return value
    return None


def _date_part(value):
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value[:10] if value else None


def build_row(entry, checked_at):
    if not isinstance(entry, dict):
        return None
    url = entry.get("url")
    if not _usable_official_url(url):
        return None
    if "id" not in entry or "title" not in entry:
        return None

    title = entry["title"]
    location = entry.get("location") or ""
    remote = bool(entry.get("remote"))
    classifier_location = "Remote" if remote else location
    verdict = filters.classify(
        title,
        classifier_location,
        india_source=False,
    )
    bucket = filters.location_bucket(classifier_location, india_source=False)

    return {
        "platform": PLATFORM,
        "token": "us-tech-internships",
        "job_id": entry["id"],
        "title": title,
        "company_name": entry.get("company"),
        "location": location,
        "url": url,
        "posted_on": _date_part(entry.get("posted_at")),
        "description": "",
        "segment": "internships",
        "stage": verdict.stage,
        "stage_title": verdict.stage,
        "stage_resolved": verdict.stage,
        "technical": verdict.technical,
        "discipline": verdict.discipline,
        "needs_description": verdict.needs_description,
        "is_internship": True,
        "location_bucket": bucket,
        "source_mechanism": "community-list",
        "source_list": SOURCE_LIST,
        "source_attribution": SOURCE_ATTRIBUTION,
        "source_confirmation": "community_list",
        "official_evidence": {
            "source": "zshah101-list",
            "list_repo": "https://github.com/" + SOURCE_LIST,
            "source_ats": entry.get("source"),
            "listing_id": entry["id"],
        },
        "season": entry.get("season"),
        "category": entry.get("category"),
        "program": entry.get("program"),
        "salary": entry.get("salary"),
        "skills": entry.get("skills") or [],
        "remote": remote,
        "sponsorship": entry.get("sponsorship"),
        "last_checked_at": checked_at,
    }


def merge_lists(rows, fetch_ok, lake_path=OPPORTUNITIES_PATH, now=None):
    now = now or datetime.now(timezone.utc).isoformat(timespec="seconds")
    if isinstance(now, datetime):
        now = now.isoformat(timespec="seconds")

    lake = _load_json(lake_path, [])
    ours_key = lambda row: (
        row.get("platform") == PLATFORM
        and row.get("source_mechanism") == "community-list"
    )
    preserved = [row for row in lake if not ours_key(row)]
    ours_existing = {
        _normalize_url(row["url"]): row
        for row in lake
        if ours_key(row) and row.get("url")
    }
    non_list_urls = {
        _normalize_url(row["url"])
        for row in preserved
        if row.get("url")
    }

    current = {}
    skipped_dup_within = 0
    skipped_dup_lake = 0
    for row in rows:
        nu = _normalize_url(row["url"])
        if nu in non_list_urls:
            skipped_dup_lake += 1
            continue
        if nu in current:
            skipped_dup_within += 1
            continue
        current[nu] = row

    merged = []
    for nu, row in current.items():
        if nu in ours_existing:
            old = ours_existing[nu]
            first_seen = old.get("first_seen") or now
            old.update(row)
            old["first_seen"] = first_seen
            old["last_seen"] = now
            old["is_live"] = True
            old.pop("went_dead_at", None)
            old.pop("needs_confirmation", None)
            old.pop("liveness_reason", None)
            merged.append(old)
        else:
            row = dict(row)
            row["first_seen"] = now
            row["last_seen"] = now
            row["is_live"] = True
            merged.append(row)

    closed = 0
    for nu, old in ours_existing.items():
        if nu in current:
            continue
        if fetch_ok:
            old["is_live"] = False
            old["went_dead_at"] = now
            old["liveness_reason"] = "delisted"
            closed += 1
        else:
            age_days = _age_days(old.get("last_seen"), now)
            if age_days is not None and age_days > RECONFIRM_WINDOW_DAYS:
                old["is_live"] = False
                old["needs_confirmation"] = True
                old["liveness_reason"] = "not_reconfirmed"
                closed += 1
            merged.append(old)
            continue
        merged.append(old)

    _atomic_json(lake_path, preserved + merged)
    return {
        "added_or_updated": len(current),
        "skipped_dup_within": skipped_dup_within,
        "skipped_dup_lake": skipped_dup_lake,
        "live_total": sum(1 for row in merged if row.get("is_live")),
        "closed": closed,
    }


def collect(fetch=_default_fetch, checked_at=None, lake_path=OPPORTUNITIES_PATH):
    if checked_at is None:
        checked_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    elif isinstance(checked_at, datetime):
        checked_at = checked_at.isoformat(timespec="seconds")
    else:
        checked_at = str(checked_at)

    try:
        data = fetch()
    except Exception:
        data = None
    fetch_ok = data is not None
    jobs = data.get("jobs", []) if isinstance(data, dict) else []
    if not isinstance(jobs, list):
        jobs = []
        fetch_ok = False
    rows = [build_row(entry, checked_at) for entry in jobs]
    rows = [row for row in rows if row is not None]
    merge_counts = merge_lists(rows, fetch_ok, lake_path=lake_path, now=checked_at)
    return {
        "raw": len(jobs),
        "built": len(rows),
        "added_or_updated": merge_counts["added_or_updated"],
        "skipped_dup_within": merge_counts["skipped_dup_within"],
        "skipped_dup_lake": merge_counts["skipped_dup_lake"],
        "live_total": merge_counts["live_total"],
        "closed": merge_counts["closed"],
        "fetch_ok": fetch_ok,
    }


def list_internship_lists(lake_path=OPPORTUNITIES_PATH):
    rows = [
        row for row in _load_json(lake_path, [])
        if row.get("platform") == PLATFORM
        and row.get("source_mechanism") == "community-list"
        and row.get("is_live") is True
    ]
    rows.sort(key=lambda row: row.get("posted_on") or "", reverse=True)
    rows.sort(key=lambda row: filters.access_rank(row.get("location_bucket")))
    return rows


def _list_cli():
    parser = argparse.ArgumentParser(
        description="Collect or list the zshah101 internship list"
    )
    parser.add_argument(
        "--list", action="store_true",
        help="list collected internship-list rows without collecting",
    )
    args = parser.parse_args()
    if not args.list:
        print(json.dumps(collect()))
        return
    rows = list_internship_lists()
    print("{} internship-list row(s)".format(len(rows)))
    for row in rows[:15]:
        print("{} | {} | {} | {}".format(
            row.get("company_name") or "",
            row.get("title") or "",
            row.get("location") or "",
            row.get("url") or "",
        ))


if __name__ == "__main__":
    _list_cli()
