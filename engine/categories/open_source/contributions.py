"""Collect good-first-issue opportunities from curated GitHub repositories.

Unauthenticated GitHub access provides roughly 60 requests/hour, enough for
about 45 repositories; set GITHUB_TOKEN to scale collection to 100+ repos.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib import request
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit

from core.paths import OPPORTUNITIES_PATH


STALE_DAYS = 60
DESCRIPTION_CHARS = 250
DISCOVERY_UPDATED_WITHIN_DAYS = 120
MAX_COMMENTS = 15
RECENT_ACTIVITY_DAYS = 3
NEW_WINDOW_DAYS = 30
RECONFIRM_WINDOW_DAYS = 7
REVERIFY_BATCH_SIZE = 4
DISCOVERY_MIN_STARS = 500
DISCOVERY_MIN_GOOD_FIRST_ISSUES = 3
DISCOVERY_PUSHED_WITHIN_DAYS = 60
DISCOVERY_REPOS_PER_LANGUAGE = 10
DISCOVERY_MAX_REPOS = 200
# Extra star bands searched after the >=500 pass; floor 100 keeps out low-quality repos.
DISCOVERY_EXTRA_STAR_BANDS = ("100..499",)
DISCOVERY_LANGUAGES = [
    "Python", "JavaScript", "TypeScript", "Java", "Go", "Rust",
    "C++", "C", "Ruby", "PHP", "C#", "Kotlin",
]
DISCOVERY_REQUEST_DELAY = 2
GOOD_FIRST_ISSUE_LABELS = {"good first issue", "good-first-issue"}
IN_PROGRESS_LABEL_MARKERS = (
    "in pr", "in-pr", "has pr", "has-pr", "in progress", "in-progress",
    "wip", "being worked", "claimed",
)
_INTERNAL_GATE_CLOSURE = "_reverification_gate_closed"
_INTERNAL_REVERIFY_UNTOUCHED = "_reverification_untouched"
_INTERNAL_REVERIFY_VERIFIED = "_reverification_verified"


@dataclass(frozen=True)
class _IssueFetchResult:
    issue: object = None
    rate_limited: bool = False
    retry_after: object = None
    rate_limit_reset: object = None


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
    # India-origin popular projects
    ("frappe/erpnext", "Python"),
    ("frappe/frappe", "Python"),
    ("appsmithorg/appsmith", "TypeScript"),
    ("hoppscotch/hoppscotch", "TypeScript"),
    ("ToolJet/ToolJet", "JavaScript"),
    ("juspay/hyperswitch", "Rust"),
    ("keploy/keploy", "Go"),
    ("hasura/graphql-engine", "TypeScript"),
    ("openobserve/openobserve", "Rust"),
    ("ohcnetwork/care_fe", "TypeScript"),
    # Rust / Go / Java diversity
    ("astral-sh/ruff", "Rust"),
    ("bevyengine/bevy", "Rust"),
    ("gin-gonic/gin", "Go"),
    ("traefik/traefik", "Go"),
    ("apache/dubbo", "Java"),
    ("apache/kafka", "Java"),
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


def _github_token():
    """Prefer a personal access token (GH_PAT) over the workflow's GITHUB_TOKEN."""
    return os.environ.get("GH_PAT") or os.environ.get("GITHUB_TOKEN")


def _describe_search_error(error):
    """One-line reason for a failed GitHub search call (HTTP status, API message, rate-limit headers)."""
    if isinstance(error, HTTPError):
        message = ""
        try:
            message = json.loads(error.read().decode("utf-8", "replace")).get("message", "")
        except Exception:
            pass
        headers = getattr(error, "headers", None)
        remaining = headers.get("X-RateLimit-Remaining") if headers else None
        resource = headers.get("X-RateLimit-Resource") if headers else None
        return "HTTP {} {} message={!r} ratelimit_remaining={} resource={}".format(
            error.code, getattr(error, "reason", ""), message, remaining, resource)
    return "{}: {}".format(type(error).__name__, str(error)[:200])


def _github_headers(token=None):
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "opportunity-radar",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = _github_token() if token is None else token
    if token:
        headers["Authorization"] = "Bearer " + token
    return headers


def _issue_admission_reason(issue, checked_at):
    """Return a stable rejection reason, or None when an issue is admitted."""
    if not isinstance(issue, dict):
        return "needs-confirmation"
    if "pull_request" in issue:
        return "pull-request"

    state = issue.get("state")
    if not isinstance(state, str):
        return "needs-confirmation"
    if state != "open":
        return "closed"

    labels = issue.get("labels")
    if not isinstance(labels, list):
        return "needs-confirmation"
    label_names = []
    for label in labels:
        if not isinstance(label, dict) or not isinstance(label.get("name"), str):
            return "needs-confirmation"
        label_names.append(label["name"])
    normalized_labels = [label.strip().casefold() for label in label_names]
    if not any(label in GOOD_FIRST_ISSUE_LABELS for label in normalized_labels):
        return "missing-good-first-issue-label"

    assignee = issue.get("assignee")
    assignees = issue.get("assignees", [])
    if assignees is None:
        return "needs-confirmation"
    if not isinstance(assignees, list):
        return "needs-confirmation"
    if assignee is not None or assignees:
        return "assigned"

    if any(
        marker in label.casefold()
        for label in label_names
        for marker in IN_PROGRESS_LABEL_MARKERS
    ):
        return "in-progress-label"

    comments = issue.get("comments", 0)
    if isinstance(comments, bool):
        return "needs-confirmation"
    try:
        comments = int(comments)
    except (TypeError, ValueError):
        return "needs-confirmation"
    if comments < 0:
        return "needs-confirmation"
    if comments > MAX_COMMENTS:
        return "too-many-comments"

    updated_at = issue.get("updated_at")
    if _parse_timestamp(updated_at) is None or _parse_timestamp(checked_at) is None:
        return "needs-confirmation"
    activity_age_days = _age_days(updated_at, checked_at)
    if activity_age_days is None:
        return "needs-confirmation"
    if activity_age_days > STALE_DAYS:
        return "stale"
    return None


def _response_header(headers, name):
    if headers is None:
        return None
    try:
        return headers.get(name)
    except (AttributeError, TypeError):
        return None


def _rate_limited_result(headers):
    remaining = _response_header(headers, "X-RateLimit-Remaining")
    return _IssueFetchResult(
        rate_limited=True,
        retry_after=_response_header(headers, "Retry-After"),
        rate_limit_reset=_response_header(headers, "X-RateLimit-Reset"),
    ) if remaining is not None and str(remaining).strip() == "0" else None


def _fetch_issue(repo, issue_number):
    """Fetch one issue without allowing any network/decoding failure to escape."""
    url = "https://api.github.com/repos/{}/issues/{}".format(repo, issue_number)
    req = request.Request(url, headers=_github_headers())
    try:
        with request.urlopen(req) as response:
            headers = getattr(response, "headers", None)
            rate_result = _rate_limited_result(headers)
            if rate_result is not None:
                return rate_result
            status = getattr(response, "status", None)
            if status is None:
                status = response.getcode()
            if status in (403, 429):
                return _IssueFetchResult(
                    rate_limited=True,
                    retry_after=_response_header(headers, "Retry-After"),
                    rate_limit_reset=_response_header(headers, "X-RateLimit-Reset"),
                )
            if status is not None and not 200 <= status < 300:
                return _IssueFetchResult()
            issue = json.load(response)
            if not isinstance(issue, dict):
                return _IssueFetchResult()
            return _IssueFetchResult(issue=issue)
    except HTTPError as error:
        headers = getattr(error, "headers", None)
        status = getattr(error, "code", None)
        if status in (403, 429) or (
            _response_header(headers, "X-RateLimit-Remaining") is not None
            and str(_response_header(headers, "X-RateLimit-Remaining")).strip() == "0"
        ):
            return _IssueFetchResult(
                rate_limited=True,
                retry_after=_response_header(headers, "Retry-After"),
                rate_limit_reset=_response_header(headers, "X-RateLimit-Reset"),
            )
        return _IssueFetchResult()
    except Exception:
        return _IssueFetchResult()


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
    token = _github_token()
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
    updated_since = (now - timedelta(days=DISCOVERY_UPDATED_WITHIN_DAYS)).date().isoformat()
    curated = {repo.casefold() for repo, _language in CURATED_REPOS}
    discovered = []
    seen = set(curated)
    star_bands = [">={}".format(DISCOVERY_MIN_STARS)] + list(DISCOVERY_EXTRA_STAR_BANDS)
    passes = [(language, band) for band in star_bands for language in DISCOVERY_LANGUAGES]
    for index, (language, band) in enumerate(passes):
        if index:
            _discovery_sleep(DISCOVERY_REQUEST_DELAY)
        query = (
            "language:{lang} good-first-issues:>{minimum} stars:{stars} "
            "pushed:>={date} updated:>={updated} archived:false is:public"
        ).format(
            lang=language,
            minimum=DISCOVERY_MIN_GOOD_FIRST_ISSUES - 1,
            stars=band,
            date=pushed_since,
            updated=updated_since,
        )
        try:
            result = search_fetch(query, token)
            items = result.get("items", [])
            if not isinstance(items, list):
                raise ValueError("GitHub repository search items was not a list")
        except Exception as error:
            print("oss_discovery: search failed for language={} stars={} after {} repos: {}".format(
                language, band, len(discovered), _describe_search_error(error)), flush=True)
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


_FENCE_RE = re.compile(r"(```|~~~).*?(\1|\Z)", re.S)
_COMMENT_RE = re.compile(r"<!--.*?(-->|\Z)", re.S)
_TAG_RE = re.compile(r"<[^>]+>")
_CHECKLIST_RE = re.compile(r"^\s*[-*+]\s*\[[ xX]\].*$", re.M)
_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s*(.*)$", re.M)
_TEMPLATE_HEAD_RE = re.compile(
    r"^\s*(?:#{1,6}\s*)?\**(?:describe the bug|steps to reproduce|expected behou?r|"
    r"actual behou?r|environment|additional context|checklist|is your feature request.*|"
    r"prerequisites|versions?)\**:?\s*$", re.I | re.M)


def clean_issue_body(body, limit=DESCRIPTION_CHARS):
    """First ~limit chars of an issue body without markdown/HTML/template noise."""
    if not isinstance(body, str) or not body.strip():
        return None
    text = _COMMENT_RE.sub(" ", body.replace("\r", ""))
    text = _FENCE_RE.sub(" ", text)
    text = _CHECKLIST_RE.sub(" ", text)
    text = _TEMPLATE_HEAD_RE.sub(" ", text)
    text = _HEADING_RE.sub(r"\1", text)
    text = _TAG_RE.sub(" ", text)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"`+|\*\*|__|^\s*>\s?|^\s*[-*+]\s+", " ", text, flags=re.M)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) < 20:
        return None
    if len(text) <= limit:
        return text
    cut = text[:limit]
    space = cut.rfind(" ")
    if space > limit * 0.6:
        cut = cut[:space]
    return cut.rstrip(" ,;:-") + "\u2026"


def _owner(repo):
    return repo.split("/", 1)[0] if isinstance(repo, str) and "/" in repo else None


def owner_logo_url(repo, avatar_url=None):
    if isinstance(avatar_url, str) and avatar_url.startswith("https://"):
        return avatar_url
    owner = _owner(repo)
    return "https://github.com/{}.png?size=96".format(owner) if owner else None


def _issue_description(issue, repo_info):
    description = clean_issue_body(issue.get("body"))
    if description:
        return description
    repo_description = (repo_info or {}).get("description")
    if isinstance(repo_description, str) and repo_description.strip():
        return clean_issue_body(repo_description, DESCRIPTION_CHARS) or repo_description.strip()[:DESCRIPTION_CHARS]
    return None


def _default_repo_fetch(repo):
    req = request.Request("https://api.github.com/repos/{}".format(repo), headers=_github_headers())
    with request.urlopen(req) as response:
        info = json.load(response)
    if not isinstance(info, dict):
        raise ValueError("repo response was not an object")
    return {
        "description": info.get("description"),
        "stars": info.get("stargazers_count"),
        "language": info.get("language"),
        "avatar_url": (info.get("owner") or {}).get("avatar_url"),
    }


def _default_pr_check(repo, number):
    """True when the issue has an open linked/cross-referenced pull request."""
    url = "https://api.github.com/repos/{}/issues/{}/timeline?per_page=100".format(repo, number)
    req = request.Request(url, headers=_github_headers())
    with request.urlopen(req) as response:
        events = json.load(response)
    for event in events if isinstance(events, list) else []:
        if event.get("event") == "connected":
            return True
        if event.get("event") == "cross-referenced":
            source = (event.get("source") or {}).get("issue") or {}
            if "pull_request" in source and source.get("state") == "open":
                return True
    return False


def _derive_difficulty(labels):
    normalized = [(label, DIFFICULTY_BY_LABEL.get(label.strip().lower())) for label in labels]
    for label, difficulty in normalized:
        if difficulty == "beginner":
            return "beginner", label
    for label, difficulty in normalized:
        if difficulty == "intermediate":
            return "intermediate", label
    return "beginner", "default"


def build_row(repo, issue, checked_at, language=None, discovery_source="curated", repo_stars=None, repo_info=None):
    repo_info = repo_info or {}
    issue_url = issue["html_url"]
    created_at = issue.get("created_at")
    updated_at = issue.get("updated_at")
    labels = [label["name"] for label in issue.get("labels", [])]
    try:
        comments_count = int(issue.get("comments", 0) or 0)
    except (TypeError, ValueError):
        comments_count = 0
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
        "language": language if language is not None else (REPO_LANGUAGES.get(repo) or repo_info.get("language")),
        "description": _issue_description(issue, repo_info),
        "repo_description": repo_info.get("description") or None,
        "logo_url": owner_logo_url(repo, repo_info.get("avatar_url")),
        "region": "Global/Remote",
        "mode": "online",
        "difficulty": difficulty,
        "difficulty_signal": difficulty_signal,
        "discovery_source": discovery_source,
        "repo_stars": repo_stars if repo_stars is not None else repo_info.get("stars"),
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
        "comments_count": comments_count,
        "assignee": None,
        "status": "open",
        "official_evidence": {
            "title": {"quote": issue["title"], "url": issue_url},
            "label": {"quote": "good first issue", "url": issue_url},
        },
        "source_confirmation": "official_source",
        "source_mechanism": "github_api",
        "last_checked_at": checked_at,
    }


def parse_repo(repo, issues, checked_at, language=None, discovery_source="curated", repo_stars=None, repo_info=None, pr_check=None):
    rows = []
    if not isinstance(issues, list):
        return rows
    for issue in issues:
        if _issue_admission_reason(issue, checked_at) is not None:
            continue
        try:
            rows.append(build_row(
                repo,
                issue,
                checked_at,
                language=language,
                discovery_source=discovery_source,
                repo_stars=repo_stars,
                repo_info=repo_info,
            ))
        except (KeyError, TypeError, ValueError):
            continue
        if pr_check is not None:
            try:
                if pr_check(repo, issue.get("number")):
                    rows.pop()  # linked PR: someone is already on it
            except Exception:
                pass
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


def _valid_repo(value):
    if not isinstance(value, str) or any(char.isspace() for char in value):
        return False
    parts = value.split("/")
    return len(parts) == 2 and all(
        part and all(char.isalnum() or char in ".-_" for char in part)
        for part in parts
    )


def _issue_number(value):
    try:
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value if value > 0 else None
        if isinstance(value, str) and value and all("0" <= char <= "9" for char in value):
            number = int(value)
            return number if number > 0 else None
    except (TypeError, ValueError, OverflowError):
        return None
    return None


def _fallback_issue_identity(row):
    for value in (
        row.get("official_url"),
        row.get("application_url"),
        row.get("contribution_id"),
    ):
        if not isinstance(value, str):
            continue
        try:
            parsed = urlsplit(value)
            if (
                parsed.scheme.casefold() != "https"
                or parsed.netloc.casefold() != "github.com"
                or parsed.query
                or parsed.fragment
            ):
                continue
            parts = parsed.path.split("/")
            if len(parts) != 5 or parts[0] or parts[3].casefold() != "issues":
                continue
            owner, repo, number = parts[1], parts[2], parts[4]
            if not owner or not repo or _issue_number(number) is None:
                continue
            identity_repo = "{}/{}".format(owner, repo)
            if not _valid_repo(identity_repo):
                continue
            return identity_repo, int(number)
        except (TypeError, ValueError, OverflowError):
            continue
    return None


def _row_issue_identity(row):
    try:
        if not isinstance(row, dict):
            return None
        repo = row.get("repo")
        number = _issue_number(row.get("issue_number"))
        if _valid_repo(repo) and number is not None:
            return repo, number
        return _fallback_issue_identity(row)
    except Exception:
        return None


def _issue_refresh_fields(issue, checked_at):
    labels = issue.get("labels")
    if not isinstance(labels, list) or any(
        not isinstance(label, dict) or not isinstance(label.get("name"), str)
        for label in labels
    ):
        return None
    title = issue.get("title")
    issue_url = issue.get("html_url")
    if not isinstance(title, str) or not title:
        return None
    if not isinstance(issue_url, str) or not issue_url:
        return None
    try:
        comments_count = int(issue.get("comments", 0) or 0)
    except (TypeError, ValueError):
        return None
    if isinstance(issue.get("comments", 0), bool) or comments_count < 0:
        return None
    updated_at = issue.get("updated_at")
    if _parse_timestamp(updated_at) is None:
        return None
    refresh = {
        "title": title,
        "official_evidence": {
            "title": {"quote": title, "url": issue_url},
        },
        "updated_at": updated_at,
        "labels": [label["name"] for label in labels],
        "difficulty": _derive_difficulty([label["name"] for label in labels])[0],
        "difficulty_signal": _derive_difficulty([label["name"] for label in labels])[1],
        "comments_count": comments_count,
        "assignee": issue.get("assignee"),
        "activity_age_days": _age_days(updated_at, checked_at),
        "is_recently_active": (
            _age_days(updated_at, checked_at) is not None
            and 0 <= _age_days(updated_at, checked_at) <= RECENT_ACTIVITY_DAYS
        ),
        "last_checked_at": checked_at,
        "region": "Global/Remote",
        "mode": "online",
    }
    description = clean_issue_body(issue.get("body"))
    if description:
        refresh["description"] = description
    repo = _owner_repo_from_url(issue_url)
    logo = owner_logo_url(repo)
    if logo:
        refresh["logo_url"] = logo
    return refresh


def _owner_repo_from_url(url):
    parts = urlsplit(url).path.split("/")
    return "{}/{}".format(parts[1], parts[2]) if len(parts) > 2 and parts[1] and parts[2] else None


def _reverify_rows(existing_rows, checked_at):
    stats = {
        "eligible": 0,
        "attempted": 0,
        "reverified": 0,
        "admitted": 0,
        "closed": 0,
        "failed": 0,
        "rate_limited": 0,
        "rate_limit_detected": False,
        "skipped_rate_limited": 0,
        "untouched": 0,
    }
    working_rows = [dict(row) if isinstance(row, dict) else row for row in existing_rows]
    candidates = []
    for index, row in enumerate(working_rows):
        if not isinstance(row, dict):
            continue
        if row.get("record_type") != "contribution":
            continue
        if row.get("is_live") is not True and row.get("needs_confirmation") is not True:
            continue
        if not isinstance(row.get("last_seen"), str):
            continue
        stats["eligible"] += 1
        identity = _row_issue_identity(row)
        if identity is None:
            row[_INTERNAL_REVERIFY_UNTOUCHED] = True
            stats["untouched"] += 1
            continue
        candidates.append((index, identity[0], identity[1]))

    for offset in range(0, len(candidates), REVERIFY_BATCH_SIZE):
        batch = candidates[offset:offset + REVERIFY_BATCH_SIZE]
        results = {}
        with ThreadPoolExecutor(max_workers=REVERIFY_BATCH_SIZE) as executor:
            futures = {
                executor.submit(_fetch_issue, repo, number): index
                for index, repo, number in batch
            }
            stats["attempted"] += len(futures)
            for future in as_completed(futures):
                index = futures[future]
                try:
                    results[index] = future.result()
                except Exception:
                    results[index] = _IssueFetchResult()

        hit_rate_limit = False
        for index, _repo, _number in batch:
            result = results.get(index, _IssueFetchResult())
            row = working_rows[index]
            if not isinstance(result, _IssueFetchResult):
                row[_INTERNAL_REVERIFY_UNTOUCHED] = True
                stats["failed"] += 1
                stats["untouched"] += 1
                continue
            if result.rate_limited:
                row[_INTERNAL_REVERIFY_UNTOUCHED] = True
                stats["failed"] += 1
                stats["untouched"] += 1
                stats["rate_limited"] += 1
                stats["rate_limit_detected"] = True
                hit_rate_limit = True
                continue
            if not isinstance(result.issue, dict):
                row[_INTERNAL_REVERIFY_UNTOUCHED] = True
                stats["failed"] += 1
                stats["untouched"] += 1
                continue
            reason = _issue_admission_reason(result.issue, checked_at)
            refresh_fields = _issue_refresh_fields(result.issue, checked_at)
            if reason == "needs-confirmation" or refresh_fields is None:
                row[_INTERNAL_REVERIFY_UNTOUCHED] = True
                stats["failed"] += 1
                stats["untouched"] += 1
                continue
            refresh_evidence = refresh_fields.pop("official_evidence", None)
            row.update(refresh_fields)
            if isinstance(refresh_evidence, dict):
                evidence = row.get("official_evidence")
                if not isinstance(evidence, dict):
                    evidence = {}
                evidence.update(refresh_evidence)
                row["official_evidence"] = evidence
            created_age_days = _age_days(row.get("created_at"), checked_at)
            row.update({
                "created_age_days": created_age_days,
                "is_new_this_month": (
                    created_age_days is not None
                    and 0 <= created_age_days <= NEW_WINDOW_DAYS
                ),
            })
            stats["reverified"] += 1
            row[_INTERNAL_REVERIFY_VERIFIED] = True
            if reason is None:
                row["is_live"] = True
                row.pop("needs_confirmation", None)
                row.pop("liveness_reason", None)
                row.pop("went_dead_at", None)
                row.pop(_INTERNAL_GATE_CLOSURE, None)
                stats["admitted"] += 1
            else:
                row["is_live"] = False
                row.pop("needs_confirmation", None)
                row["went_dead_at"] = checked_at
                row["liveness_reason"] = reason
                row[_INTERNAL_GATE_CLOSURE] = True
                stats["closed"] += 1

        if hit_rate_limit:
            for row in working_rows:
                if (
                    isinstance(row, dict)
                    and row.get("record_type") == "contribution"
                    and not row.get(_INTERNAL_REVERIFY_VERIFIED)
                ):
                    row[_INTERNAL_REVERIFY_UNTOUCHED] = True
            remaining_candidates = candidates[offset + len(batch):]
            skipped = len(remaining_candidates)
            stats["skipped_rate_limited"] += skipped
            stats["untouched"] += skipped
            break
    return working_rows, stats


def merge_contributions(rows_by_repo, successful_repos, lake_path=OPPORTUNITIES_PATH, now=None, existing_rows=None):
    now = now or datetime.now(timezone.utc).isoformat(timespec="seconds")
    lake = existing_rows if existing_rows is not None else _load_json(lake_path, [])
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
            if old.get(_INTERNAL_REVERIFY_UNTOUCHED):
                continue
            protected_gate_closure = bool(old.get(_INTERNAL_GATE_CLOSURE))
            protected_reason = old.get("liveness_reason")
            first_seen = old.get("first_seen", now)
            old.update(row)
            old.update({
                "first_seen": first_seen,
                "last_seen": now,
                "is_live": True,
                "needs_confirmation": False,
            })
            old.pop("liveness_reason", None)
            if protected_gate_closure:
                old["is_live"] = False
                old.pop("needs_confirmation", None)
                old["liveness_reason"] = protected_reason
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
        if row.get(_INTERNAL_REVERIFY_UNTOUCHED):
            continue
        if row.get("contribution_id") in current_ids:
            continue
        if row.get(_INTERNAL_REVERIFY_VERIFIED) and row.get("is_live") is True:
            continue
        if row.get(_INTERNAL_GATE_CLOSURE):
            continue
        if row.get("repo") in successful_repos:
            if row.get(_INTERNAL_GATE_CLOSURE):
                continue
            row["is_live"], row["went_dead_at"] = False, now
            row["needs_confirmation"] = False
            row.pop("liveness_reason", None)
            continue
        age_days = _last_seen_age_days(row.get("last_seen"), now)
        if age_days is not None and age_days > RECONFIRM_WINDOW_DAYS:
            row["is_live"] = False
            row["needs_confirmation"] = True
            row["liveness_reason"] = "not_reconfirmed"

    now_dt = _parse_timestamp(now)
    for row in unkeyed + list(contribution_rows.values()):
        if row.get(_INTERNAL_REVERIFY_UNTOUCHED):
            continue
        if row.get("record_type", "contribution") != "contribution" or not row.get("is_live"):
            continue
        age = _age_days(row.get("updated_at"), now_dt)
        if age is not None and age > STALE_DAYS:
            row["is_live"] = False
            row["needs_confirmation"] = True
            row["liveness_reason"] = "stale_activity"

    for row in unkeyed + list(contribution_rows.values()):
        if isinstance(row, dict):
            row.pop(_INTERNAL_GATE_CLOSURE, None)
            row.pop(_INTERNAL_REVERIFY_UNTOUCHED, None)
            row.pop(_INTERNAL_REVERIFY_VERIFIED, None)

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
    repo_fetch=_default_repo_fetch,
    pr_check=None,
):
    checked_datetime = checked_at or datetime.now(timezone.utc)
    if isinstance(checked_datetime, str):
        checked_datetime = _parse_timestamp(checked_datetime)
    if checked_datetime is None:
        checked_datetime = datetime.now(timezone.utc)
    if isinstance(checked_datetime, datetime):
        if checked_datetime.tzinfo is None:
            checked_datetime = checked_datetime.replace(tzinfo=timezone.utc)
        else:
            checked_datetime = checked_datetime.astimezone(timezone.utc)
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
    token = _github_token()
    if not token:
        print("oss_discovery: no GH_PAT/GITHUB_TOKEN set; repository search skipped", flush=True)
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

    if pr_check is None and token:
        pr_check = _default_pr_check
    existing_rows = _load_json(lake_path, [])
    existing_rows, reverification = _reverify_rows(existing_rows, checked_at)
    rows_by_repo = {}
    successful_repos = set()
    failed_repos = set()
    if not reverification["rate_limit_detected"]:
        for spec in repo_specs:
            repo = spec["repo"]
            try:
                issues = fetch(repo)
                try:
                    repo_info = repo_fetch(repo) if repo_fetch else {}
                except Exception:
                    repo_info = {}
                if not isinstance(repo_info, dict):
                    repo_info = {}
                rows_by_repo[repo] = parse_repo(
                    repo,
                    issues,
                    checked_at,
                    language=spec["language"],
                    discovery_source=spec["discovery_source"],
                    repo_stars=spec["repo_stars"],
                    repo_info=repo_info,
                    pr_check=pr_check,
                )
                successful_repos.add(repo)
            except Exception:
                failed_repos.add(repo)
    rows = merge_contributions(
        rows_by_repo,
        successful_repos,
        lake_path,
        now=checked_at,
        existing_rows=existing_rows,
    )
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
        "reverification": reverification,
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
