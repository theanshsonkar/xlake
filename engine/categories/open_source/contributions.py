"""Collect good-first-issue opportunities from curated GitHub repositories.

Unauthenticated GitHub access provides roughly 60 requests/hour, enough for
about 45 repositories; set GITHUB_TOKEN to scale collection to 100+ repos.
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
import time
from datetime import datetime, timedelta, timezone
from urllib import request
from urllib.parse import urlencode

from core.paths import OPPORTUNITIES_PATH


STALE_DAYS = 120
MAX_COMMENTS = 30
RECENT_ACTIVITY_DAYS = 3
NEW_WINDOW_DAYS = 30
RECONFIRM_WINDOW_DAYS = 7
DISCOVERY_MIN_STARS = 500
DISCOVERY_MIN_GOOD_FIRST_ISSUES = 3
DISCOVERY_PUSHED_WITHIN_DAYS = 60
DISCOVERY_REPOS_PER_LANGUAGE = 10
DISCOVERY_MAX_REPOS = 120
DISCOVERY_LANGUAGES = [
    "Python", "JavaScript", "TypeScript", "Java", "Go", "Rust",
    "C++", "C", "Ruby", "PHP", "C#", "Kotlin",
]
DISCOVERY_REQUEST_DELAY = 2


CURATED_REPOS = (
    ("django/django", "Python"),
    ("pandas-dev/pandas", "Python"),
    ("scikit-learn/scikit-learn", "Python"),
    ("numpy/numpy", "Python"),
    ("matplotlib/matplotlib", "Python"),
    ("scipy/scipy", "Python"),
    ("pallets/flask", "Python"),
    ("psf/requests", "Python"),
    ("fastapi/fastapi", "Python"),
    ("ansible/ansible", "Python"),
    ("scrapy/scrapy", "Python"),
    ("python-pillow/Pillow", "Python"),
    ("facebook/react", "JavaScript"),
    ("vercel/next.js", "TypeScript"),
    ("nodejs/node", "C++"),
    ("vuejs/core", "TypeScript"),
    ("sveltejs/svelte", "TypeScript"),
    ("angular/angular", "TypeScript"),
    ("vitejs/vite", "TypeScript"),
    ("storybookjs/storybook", "TypeScript"),
    ("chartjs/Chart.js", "JavaScript"),
    ("expressjs/express", "JavaScript"),
    ("kubernetes/kubernetes", "Go"),
    ("prometheus/prometheus", "Go"),
    ("grafana/grafana", "Go"),
    ("hashicorp/terraform", "Go"),
    ("gohugoio/hugo", "Go"),
    ("etcd-io/etcd", "Go"),
    ("rust-lang/rust", "Rust"),
    ("tokio-rs/tokio", "Rust"),
    ("godotengine/godot", "C++"),
    ("opencv/opencv", "C++"),
    ("microsoft/terminal", "C++"),
    ("elastic/elasticsearch", "Java"),
    ("spring-projects/spring-boot", "Java"),
    ("home-assistant/core", "Python"),
    ("electron/electron", "C++"),
    ("freeCodeCamp/freeCodeCamp", "TypeScript"),
    ("denoland/deno", "Rust"),
    ("pytorch/pytorch", "Python"),
    ("huggingface/transformers", "Python"),
    ("mui/material-ui", "TypeScript"),
    ("tauri-apps/tauri", "Rust"),
    ("supabase/supabase", "TypeScript"),
    ("pola-rs/polars", "Rust"),
)
REPO_LANGUAGES = dict(CURATED_REPOS)


DIFFICULTY_BY_LABEL = {
    "good first issue": "beginner",
    "good-first-issue": "beginner",
    "beginner": "beginner",
    "beginner friendly": "beginner",
    "easy": "beginner",
    "starter": "beginner",
    "first-timers-only": "beginner",
    "up-for-grabs": "beginner",
    "low-hanging-fruit": "beginner",
    "help wanted": "intermediate",
    "intermediate": "intermediate",
    "medium": "intermediate",
}


def _default_fetch(repo):
    params = urlencode({
        "state": "open",
        "labels": "good first issue",
        "per_page": 15,
        "sort": "updated",
        "direction": "desc",
    })
    url = "https://api.github.com/repos/{}/issues?{}".format(repo, params)
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "opportunity-radar",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = "Bearer " + token
    req = request.Request(url, headers=headers)
    with request.urlopen(req) as response:
        issues = json.load(response)
    if not isinstance(issues, list):
        raise ValueError("GitHub issues response was not a list")
    return issues


def _default_search_fetch(query, token):
    params = urlencode({
        "q": query,
        "sort": "updated",
        "order": "desc",
        "per_page": DISCOVERY_REPOS_PER_LANGUAGE,
    })
    url = "https://api.github.com/search/repositories?{}".format(params)
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "opportunity-radar",
        "X-GitHub-Api-Version": "2022-11-28",
        "Authorization": "Bearer " + token,
    }
    req = request.Request(url, headers=headers)
    with request.urlopen(req) as response:
        result = json.load(response)
    if not isinstance(result, dict):
        raise ValueError("GitHub repository search response was not an object")
    return result


def _discovery_sleep(seconds):
    time.sleep(seconds)


def discover_repos(token, now, search_fetch=_default_search_fetch):
    if not token:
        return []
    if isinstance(now, str):
        now = _parse_timestamp(now)
    if now is None:
        return []
    pushed_since = (now - timedelta(days=DISCOVERY_PUSHED_WITHIN_DAYS)).date().isoformat()
    updated_since = (now - timedelta(days=STALE_DAYS)).date().isoformat()
    curated = {repo.casefold() for repo, _language in CURATED_REPOS}
    discovered = []
    seen = set(curated)
    for index, language in enumerate(DISCOVERY_LANGUAGES):
        if index:
            _discovery_sleep(DISCOVERY_REQUEST_DELAY)
        query = (
            "language:{lang} good-first-issues:>{minimum} stars:>={stars} "
            "pushed:>={date} updated:>={updated} archived:false is:public"
        ).format(
            lang=language,
            minimum=DISCOVERY_MIN_GOOD_FIRST_ISSUES - 1,
            stars=DISCOVERY_MIN_STARS,
            date=pushed_since,
            updated=updated_since,
        )
        try:
            result = search_fetch(query, token)
            items = result.get("items", [])
            if not isinstance(items, list):
                raise ValueError("GitHub repository search items was not a list")
        except Exception:
            return discovered
        for item in items:
            if not isinstance(item, dict):
                continue
            full_name = item.get("full_name")
            if not full_name or full_name.casefold() in seen:
                continue
            seen.add(full_name.casefold())
            stars = item.get("stargazers_count")
            try:
                stars = int(stars) if stars is not None else None
            except (TypeError, ValueError):
                stars = None
            discovered.append({
                "full_name": full_name,
                "language": item.get("language") or language,
                "stars": stars,
            })
            if len(discovered) >= DISCOVERY_MAX_REPOS:
                return discovered
    return discovered


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


def _updated_sort_key(row):
    parsed = _parse_timestamp(row.get("updated_at"))
    return parsed if parsed is not None else datetime.min.replace(tzinfo=timezone.utc)


def _last_seen_age_days(value, checked_at):
    if not isinstance(value, str):
        return None
    try:
        last_seen_date = datetime.fromisoformat(value[:10]).date()
    except ValueError:
        return None
    checked = _parse_timestamp(checked_at)
    if checked is None:
        return None
    return (checked.date() - last_seen_date).days


def _derive_difficulty(labels):
    normalized = [(label, DIFFICULTY_BY_LABEL.get(label.strip().lower())) for label in labels]
    for label, difficulty in normalized:
        if difficulty == "beginner":
            return "beginner", label
    for label, difficulty in normalized:
        if difficulty == "intermediate":
            return "intermediate", label
    return "beginner", "default"


def build_row(repo, issue, checked_at, language=None, discovery_source="curated", repo_stars=None):
    issue_url = issue["html_url"]
    created_at = issue.get("created_at")
    updated_at = issue.get("updated_at")
    labels = [label["name"] for label in issue.get("labels", [])]
    created_age_days = _age_days(created_at, checked_at)
    activity_age_days = _age_days(updated_at, checked_at)
    difficulty, difficulty_signal = _derive_difficulty(labels)
    return {
        "record_type": "contribution",
        "category": "open-source-contributions",
        "opportunity_type": "open_source_contribution",
        "contribution_id": issue_url,
        "title": issue["title"],
        "repo": repo,
        "organizer": repo,
        "official_url": issue_url,
        "application_url": issue_url,
        "labels": labels,
        "language": language if language is not None else REPO_LANGUAGES.get(repo),
        "difficulty": difficulty,
        "difficulty_signal": difficulty_signal,
        "discovery_source": discovery_source,
        "repo_stars": repo_stars,
        "issue_number": issue["number"],
        "created_at": created_at,
        "posted_on": created_at,
        "created_age_days": created_age_days,
        "activity_age_days": activity_age_days,
        "is_new_this_month": (
            created_age_days is not None
            and 0 <= created_age_days <= NEW_WINDOW_DAYS
        ),
        "is_recently_active": (
            activity_age_days is not None
            and 0 <= activity_age_days <= RECENT_ACTIVITY_DAYS
        ),
        "updated_at": updated_at,
        "status": "open",
        "official_evidence": {
            "title": {"quote": issue["title"], "url": issue_url},
            "label": {"quote": "good first issue", "url": issue_url},
        },
        "source_confirmation": "official_source",
        "source_mechanism": "github_api",
        "last_checked_at": checked_at,
    }


def parse_repo(repo, issues, checked_at, language=None, discovery_source="curated", repo_stars=None):
    rows = []
    for issue in issues:
        if "pull_request" in issue:
            continue
        if issue.get("state") != "open":
            continue
        if issue.get("assignee") or issue.get("assignees"):
            continue
        labels = issue.get("labels", [])
        if not any(
            isinstance(label, dict)
            and str(label.get("name", "")).strip().casefold()
            in {"good first issue", "good-first-issue"}
            for label in labels
        ):
            continue
        activity_age_days = _age_days(issue.get("updated_at"), checked_at)
        if activity_age_days is not None and activity_age_days > STALE_DAYS:
            continue
        try:
            comment_count = int(issue.get("comments", 0) or 0)
        except (TypeError, ValueError):
            continue
        if comment_count > MAX_COMMENTS:
            continue
        rows.append(build_row(
            repo,
            issue,
            checked_at,
            language=language,
            discovery_source=discovery_source,
            repo_stars=repo_stars,
        ))
    return sorted(rows, key=_updated_sort_key, reverse=True)


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
    fd, tmp = tempfile.mkstemp(prefix=".contributions-", dir=directory)
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(value, handle, indent=1)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def merge_contributions(rows_by_repo, successful_repos, lake_path=OPPORTUNITIES_PATH, now=None):
    now = now or datetime.now(timezone.utc).isoformat(timespec="seconds")
    lake = _load_json(lake_path, [])
    preserved = [row for row in lake if row.get("record_type") != "contribution"]
    contribution_rows = {
        row.get("contribution_id"): row
        for row in lake
        if row.get("record_type") == "contribution" and row.get("contribution_id")
    }
    unkeyed = [
        row for row in lake
        if row.get("record_type") == "contribution" and not row.get("contribution_id")
    ]

    new_rows = sorted(
        (row for rows in rows_by_repo.values() for row in rows),
        key=_updated_sort_key,
        reverse=True,
    )
    current_ids = {row["contribution_id"] for row in new_rows}
    for row in new_rows:
        contribution_id = row["contribution_id"]
        old = contribution_rows.get(contribution_id)
        if old:
            first_seen = old.get("first_seen", now)
            old.update(row)
            old.update({
                "first_seen": first_seen,
                "last_seen": now,
                "is_live": True,
                "needs_confirmation": False,
            })
            old.pop("liveness_reason", None)
        else:
            row = dict(row)
            row.update({
                "first_seen": now,
                "last_seen": now,
                "is_live": True,
                "needs_confirmation": False,
            })
            row.pop("liveness_reason", None)
            contribution_rows[contribution_id] = row

    successful_repos = set(successful_repos)
    for row in contribution_rows.values():
        if row.get("contribution_id") in current_ids:
            continue
        if row.get("repo") in successful_repos:
            row["is_live"], row["went_dead_at"] = False, now
            row["needs_confirmation"] = False
            row.pop("liveness_reason", None)
            continue
        age_days = _last_seen_age_days(row.get("last_seen"), now)
        if age_days is not None and age_days > RECONFIRM_WINDOW_DAYS:
            row["is_live"] = False
            row["needs_confirmation"] = True
            row["liveness_reason"] = "not_reconfirmed"

    merged_contributions = sorted(
        unkeyed + list(contribution_rows.values()),
        key=_updated_sort_key,
        reverse=True,
    )
    _atomic_json(lake_path, preserved + merged_contributions)
    return merged_contributions


def collect(
    fetch=_default_fetch,
    checked_at=None,
    lake_path=OPPORTUNITIES_PATH,
    search_fetch=_default_search_fetch,
):
    checked_datetime = checked_at or datetime.now(timezone.utc)
    if isinstance(checked_datetime, str):
        checked_datetime = _parse_timestamp(checked_datetime)
    checked_at = checked_datetime
    if isinstance(checked_at, datetime):
        checked_at = checked_at.isoformat(timespec="seconds")

    repo_specs = [
        {
            "repo": repo,
            "language": language,
            "discovery_source": "curated",
            "repo_stars": None,
        }
        for repo, language in CURATED_REPOS
    ]
    token = os.environ.get("GITHUB_TOKEN")
    discovered = discover_repos(token, checked_datetime, search_fetch=search_fetch) if token else []
    seen_repos = {spec["repo"].casefold() for spec in repo_specs}
    for item in discovered:
        repo = item["full_name"]
        if repo.casefold() in seen_repos:
            continue
        seen_repos.add(repo.casefold())
        repo_specs.append({
            "repo": repo,
            "language": item.get("language"),
            "discovery_source": "search",
            "repo_stars": item.get("stars"),
        })

    rows_by_repo = {}
    successful_repos = set()
    failed_repos = set()
    for spec in repo_specs:
        repo = spec["repo"]
        try:
            rows_by_repo[repo] = parse_repo(
                repo,
                fetch(repo),
                checked_at,
                language=spec["language"],
                discovery_source=spec["discovery_source"],
                repo_stars=spec["repo_stars"],
            )
            successful_repos.add(repo)
        except Exception:
            failed_repos.add(repo)
    rows = merge_contributions(rows_by_repo, successful_repos, lake_path, now=checked_at)
    total_issues_collected = sum(len(repo_rows) for repo_rows in rows_by_repo.values())
    return {
        "repos_ok": len(successful_repos),
        "repos_failed": len(failed_repos),
        "repos_curated": len(CURATED_REPOS),
        "repos_discovered": len(discovered),
        "total_issues_collected": total_issues_collected,
        "contributions": len(rows),
        "recently_active": sum(1 for row in rows if row.get("is_recently_active")),
        "new_this_month": sum(1 for row in rows if row.get("is_new_this_month")),
    }


def list_contributions(language=None, difficulty=None, recently_active=None, new_this_month=None):
    rows = [
        row for row in _load_json(OPPORTUNITIES_PATH, [])
        if row.get("record_type") == "contribution"
    ]
    if language is not None:
        language = str(language).casefold()
        rows = [
            row for row in rows
            if str(row.get("language", "")).casefold() == language
        ]
    if difficulty is not None:
        rows = [row for row in rows if row.get("difficulty") == difficulty]
    if recently_active is not None:
        rows = [row for row in rows if row.get("is_recently_active") == recently_active]
    if new_this_month is not None:
        rows = [row for row in rows if row.get("is_new_this_month") == new_this_month]
    return rows


def _list_cli():
    parser = argparse.ArgumentParser(description="List collected contributions without collecting")
    parser.add_argument("--list", action="store_true", help="list contribution rows from the canonical lake")
    parser.add_argument("--language")
    parser.add_argument("--difficulty")
    parser.add_argument("--recently-active", dest="recently_active", action="store_true", default=None)
    parser.add_argument("--new-this-month", dest="new_this_month", action="store_true", default=None)
    args = parser.parse_args()
    if not args.list:
        print(json.dumps(collect()))
        return
    rows = list_contributions(
        language=args.language,
        difficulty=args.difficulty,
        recently_active=args.recently_active,
        new_this_month=args.new_this_month,
    )
    print("{} contribution(s)".format(len(rows)))
    for row in rows[:5]:
        print("- {} — {}".format(row.get("title", ""), row.get("official_url", "")))


if __name__ == "__main__":
    _list_cli()
