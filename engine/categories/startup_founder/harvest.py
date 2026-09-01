"""Startup & Founder programme external directory harvester.

This module is intentionally category-local: it reads a small startup-founder
hub directory, discovers links, and writes only the requested output records.
It never writes the lake, S3, Supabase, operations data, or any shared
collector state. The category is sourced from each hub entry rather than
hard-coded into record construction.

The CLI is a dry-run by design. Its default output is
/tmp/startup_founder_dryrun.json; repository, lake, and S3 destinations are
rejected. It uses only Python's standard library and does not call shared
collector or programme merge code.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import html
import json
import os
import re
import sys
import tempfile
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request


REPO_ROOT = Path(__file__).resolve().parents[3]
HUBS_PATH = Path(__file__).with_name("startup_founder_hubs.json")
DEFAULT_OUTPUT = Path("/tmp/startup_founder_dryrun.json")
USER_AGENT = (
    "OpportunityRadarStartupFounderHarvester/1.0 "
    "(+https://github.com/theanshsonkar/xlake; "
    "contact: anshsonkar@users.noreply.github.com)"
)
ROBOTS_AGENT_TOKEN = "opportunityradarstartupfounderharvester"
REQUEST_CAP = 150
HOST_DELAY_SECONDS = 2.0
REQUEST_TIMEOUT_SECONDS = 20
MAX_BODY_BYTES = 5 * 1024 * 1024
MAX_REDIRECTS = 5

# These are intentionally conservative domain proxies, not claims about the
# ownership of a domain. They prevent common navigational and social links from
# becoming opportunity records.
EXCLUDED_REGISTERED_DOMAINS = {
    "api.github.com",
    "crunchbase.com",
    "bing.com",
    "duckduckgo.com",
    "facebook.com",
    "glassdoor.com",
    "github.com",
    "google.com",
    "indeed.com",
    "instagram.com",
    "jooble.org",
    "linkedin.com",
    "medium.com",
    "naukri.com",
    "raw.githubusercontent.com",
    "reddit.com",
    "simplyhired.com",
    "tiktok.com",
    "twitter.com",
    "unstop.com",
    "wikipedia.org",
    "x.com",
    "youtube.com",
    "ziprecruiter.com",
}

# A small explicit public-suffix approximation. This is not a PSL and is only
# used for dedupe/exclusion metrics, which are labelled as proxies in output.
COMMON_MULTI_PART_SUFFIXES = {
    "ac.uk",
    "co.in",
    "co.jp",
    "co.nz",
    "co.uk",
    "com.au",
    "com.br",
    "com.cn",
    "com.sg",
    "edu.au",
    "edu.cn",
    "gov.au",
    "gov.in",
    "gov.uk",
    "net.au",
    "org.au",
    "org.cn",
    "org.in",
    "org.uk",
}

CANDIDATE_TERMS = re.compile(
    r"(?:startup|founder|accelerator|incubator|pre[\s_-]*accelerator|"
    r"venture|entrepreneur|founders[\s_-]*program|startup[\s_-]*program)",
    re.IGNORECASE,
)
TRACKING_PARAMETER = re.compile(r"^(?:utm_.+|mc_.+|fbclid|gclid)$", re.IGNORECASE)
VALID_SCHEMES = {"http", "https"}


@dataclass
class FetchResult:
    """A fetch outcome with enough state to keep blocked separate from failed."""

    state: str
    status: Optional[int] = None
    url: str = ""
    final_url: str = ""
    body: str = ""
    reason: str = ""
    response_headers: Dict[str, str] = field(default_factory=dict)


@dataclass
class RobotsRules:
    allow: List[str] = field(default_factory=list)
    disallow: List[str] = field(default_factory=list)

    def allows(self, path: str) -> bool:
        if not path.startswith("/"):
            path = "/" + path
        allow_length = max(
            (self._match_length(rule, path) for rule in self.allow), default=-1
        )
        deny_length = max(
            (self._match_length(rule, path) for rule in self.disallow), default=-1
        )
        return deny_length < 0 or allow_length >= deny_length

    @staticmethod
    def _match_length(pattern: str, path: str) -> int:
        if not pattern:
            return -1
        end_anchored = pattern.endswith("$")
        body = pattern[:-1] if end_anchored else pattern
        expression = "".join(".*" if char == "*" else re.escape(char) for char in body)
        expression = "^" + expression + ("$" if end_anchored else "")
        try:
            return len(pattern) if re.match(expression, path) else -1
        except re.error:
            return -1


@dataclass
class Candidate:
    url: str
    memberships: Dict[str, Tuple[str, str]] = field(default_factory=dict)


@dataclass
class HubFetch:
    """A hub read plus operational acquisition observations."""

    state: str
    links: List[Tuple[str, str]]
    reason: str
    base_url: str
    method: str
    raw_link_count: int = 0


class AnchorParser(HTMLParser):
    """Collect HTML anchors while preserving their first-seen order."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: List[Tuple[str, str]] = []
        self._active_href: Optional[str] = None
        self._active_text: List[str] = []
        self._depth = 0

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        if tag.lower() != "a":
            if self._active_href is not None:
                self._depth += 1
            return
        if self._active_href is not None:
            self._finish_anchor()
        href = dict(attrs).get("href")
        self._active_href = href
        self._active_text = []
        self._depth = 0

    def handle_endtag(self, tag: str) -> None:
        if self._active_href is None:
            return
        if tag.lower() == "a" and self._depth == 0:
            self._finish_anchor()
        elif self._depth:
            self._depth -= 1

    def handle_data(self, data: str) -> None:
        if self._active_href is not None:
            self._active_text.append(data)

    def close(self) -> None:
        super().close()
        if self._active_href is not None:
            self._finish_anchor()

    def _finish_anchor(self) -> None:
        if self._active_href is not None:
            self.links.append((self._active_href, clean_text(" ".join(self._active_text))))
        self._active_href = None
        self._active_text = []
        self._depth = 0


class NoRedirectHandler(urllib_request.HTTPRedirectHandler):
    """Expose redirect responses so each destination can pass robots checks."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        return None


class Fetcher:
    """One bounded, robots-aware urllib client shared by the whole run."""

    def __init__(self) -> None:
        self.total_requests = 0
        self._last_request_by_origin: Dict[str, float] = {}
        self._robots_cache: Dict[str, Tuple[bool, Optional[RobotsRules], str]] = {}
        self._opener = urllib_request.build_opener(NoRedirectHandler())

    def fetch(self, url: str, headers: Optional[Dict[str, str]] = None) -> FetchResult:
        """Fetch content, checking robots before every hop and every origin."""
        current = url
        seen: Set[str] = set()
        robots_reasons: List[str] = []
        request_headers = {"User-Agent": USER_AGENT, "Accept": "text/html, text/plain;q=0.9, */*;q=0.5"}
        if headers:
            request_headers.update(headers)

        for redirect_number in range(MAX_REDIRECTS + 1):
            parsed = parse_http_url(current)
            if parsed is None:
                return FetchResult("failed", url=url, final_url=current, reason="invalid redirect URL")
            allowed, robots_reason = self._robots_allows(current)
            robots_reasons.append(robots_reason)
            if not allowed:
                return FetchResult("blocked", url=url, final_url=current, reason=robots_reason)
            if current in seen:
                return FetchResult("failed", url=url, final_url=current, reason="redirect loop")
            seen.add(current)
            response = self._request_once(current, request_headers)
            if response.state == "failed":
                response.url = url
                response.final_url = current
                response.reason = self._with_robots_reason(response.reason, robots_reasons)
                return response
            status = response.status or 0
            if status in {301, 302, 303, 307, 308}:
                if redirect_number >= MAX_REDIRECTS:
                    return FetchResult("dead", status=status, url=url, final_url=current, reason=self._with_robots_reason("redirect limit", robots_reasons))
                location = response.reason
                if not location:
                    return FetchResult("failed", status=status, url=url, final_url=current, reason=self._with_robots_reason("redirect missing Location", robots_reasons))
                current = urllib_parse.urljoin(current, location)
                continue
            response.url = url
            response.final_url = current
            response.reason = self._with_robots_reason(response.reason or ("HTTP status" if status != 200 else ""), robots_reasons)
            if status == 200:
                return response
            return FetchResult("dead", status=status, url=url, final_url=current, body=response.body, reason=response.reason, response_headers=response.response_headers)
        return FetchResult("failed", url=url, final_url=current, reason="unreachable redirect loop")

    @staticmethod
    def _with_robots_reason(reason: str, robots_reasons: Sequence[str]) -> str:
        visible = ",".join(dict.fromkeys(robots_reasons))
        if reason and visible:
            return "{}; {}".format(reason, visible)
        return reason or visible

    def _robots_allows(self, url: str) -> Tuple[bool, str]:
        parsed = parse_http_url(url)
        if parsed is None:
            return False, "invalid URL"
        origin = origin_key_for(parsed)
        cached = self._robots_cache.get(origin)
        if cached is None:
            cached = self._fetch_robots(parsed)
            self._robots_cache[origin] = cached
        ok, rules, reason = cached
        if not ok or rules is None:
            return False, reason
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query
        if not rules.allows(path):
            return False, "robots_disallow"
        return True, reason

    def _fetch_robots(self, parsed: urllib_parse.SplitResult) -> Tuple[bool, Optional[RobotsRules], str]:
        source_origin = origin_key_for(parsed)
        current = urllib_parse.urlunsplit((parsed.scheme, parsed.netloc, "/robots.txt", "", ""))
        seen: Set[str] = set()
        for _ in range(MAX_REDIRECTS + 1):
            if current in seen:
                return False, None, "robots_redirect_loop"
            seen.add(current)
            response = self._request_once(
                current,
                {"User-Agent": USER_AGENT, "Accept": "text/plain,*/*;q=0.5"},
            )
            if response.state == "failed":
                return False, None, "robots_fetch_failed:{}".format(response.reason or "transport_error")
            status = response.status or 0
            if status in {301, 302, 303, 307, 308}:
                if not response.reason:
                    return False, None, "robots_redirect_missing_location"
                destination = urllib_parse.urljoin(current, response.reason)
                destination_parsed = parse_http_url(destination)
                if destination_parsed is None:
                    return False, None, "robots_redirect_invalid"
                # A robots redirect to another origin would require fetching
                # that origin's /robots.txt to authorize the destination. That
                # policy fetch can itself redirect back and recurse. Blocking
                # the cross-origin hop is conservative and, importantly, does
                # not cache the destination policy under source_origin.
                if origin_key_for(destination_parsed) != source_origin:
                    return False, None, "robots_cross_origin_redirect_blocked"
                current = destination
                continue
            if status == 404:
                return True, RobotsRules(), "robots_missing_allow"
            if status in {401, 403}:
                return False, None, "robots_blocked_http_{}".format(status)
            if status == 429 or 500 <= status <= 599:
                return False, None, "robots_unavailable_http_{}".format(status)
            if status != 200:
                return False, None, "robots_unavailable_http_{}".format(status)
            try:
                return True, parse_robots(response.body), "robots_allow"
            except ValueError as exc:
                return False, None, "robots_parse_failed:{}".format(exc)
        return False, None, "robots_redirect_limit"

    def _request_once(self, url: str, headers: Dict[str, str]) -> FetchResult:
        parsed = parse_http_url(url)
        if parsed is None:
            return FetchResult("failed", url=url, final_url=url, reason="invalid URL")
        if self.total_requests >= REQUEST_CAP:
            raise RequestCapExceeded("HTTP request cap of {} reached".format(REQUEST_CAP))
        origin = origin_key_for(parsed)
        previous = self._last_request_by_origin.get(origin)
        if previous is not None:
            wait = HOST_DELAY_SECONDS - (time.monotonic() - previous)
            if wait > 0:
                time.sleep(wait)
        self._last_request_by_origin[origin] = time.monotonic()
        self.total_requests += 1
        request = urllib_request.Request(url, headers=headers, method="GET")
        try:
            with self._opener.open(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
                body = response.read(MAX_BODY_BYTES + 1)
                response_headers = {key.lower(): value for key, value in response.headers.items()}
                if len(body) > MAX_BODY_BYTES:
                    return FetchResult("failed", status=response.getcode(), final_url=url, reason="response too large", response_headers=response_headers)
                return FetchResult(
                    "live",
                    status=response.getcode(),
                    final_url=response.geturl() or url,
                    body=body.decode("utf-8", errors="replace"),
                    response_headers=response_headers,
                )
        except urllib_error.HTTPError as exc:
            try:
                body = exc.read(MAX_BODY_BYTES + 1)
            except Exception:
                body = b""
            location = exc.headers.get("Location", "") if exc.headers else ""
            response_headers = {
                key.lower(): value for key, value in exc.headers.items()
            } if exc.headers else {}
            return FetchResult(
                "dead",
                status=exc.code,
                final_url=url,
                body=body[:MAX_BODY_BYTES].decode("utf-8", errors="replace"),
                reason=location,
                response_headers=response_headers,
            )
        except (urllib_error.URLError, TimeoutError, OSError, ValueError) as exc:
            return FetchResult("failed", final_url=url, reason=type(exc).__name__)


class RequestCapExceeded(RuntimeError):
    """Raised before a request could breach the global cap."""


def parse_robots(text: str) -> RobotsRules:
    """Parse the relevant robots group, failing on malformed directives."""
    groups: List[Tuple[List[str], RobotsRules]] = []
    agents: Optional[List[str]] = None
    rules: Optional[RobotsRules] = None
    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            agents = None
            rules = None
            continue
        field, separator, value = line.partition(":")
        if not separator:
            raise ValueError("directive without colon")
        field = field.strip().lower()
        value = value.strip()
        if field == "user-agent":
            if agents is None:
                agents = []
                rules = RobotsRules()
                groups.append((agents, rules))
            if not value:
                raise ValueError("empty user-agent")
            agents.append(value.lower())
        elif field in {"allow", "disallow"}:
            if agents is None or rules is None:
                raise ValueError("rule before user-agent")
            if value:
                getattr(rules, field).append(urllib_parse.unquote(value))
        elif field == "crawl-delay":
            # The harvester deliberately uses its own fixed politeness delay.
            # Validate malformed values rather than treating them as a blank read.
            if agents is None:
                raise ValueError("crawl-delay before user-agent")
            try:
                float(value)
            except ValueError as exc:
                raise ValueError("invalid crawl-delay") from exc
        else:
            # Unknown extensions are legal robots directives and do not affect
            # path permission, so they are ignored.
            continue
    selected = [
        rules
        for agents, rules in groups
        if any(agent in ROBOTS_AGENT_TOKEN for agent in agents)
    ]
    if not selected:
        selected = [rules for agents, rules in groups if "*" in agents]
    return selected[0] if selected else RobotsRules()


def parse_http_url(url: str) -> Optional[urllib_parse.SplitResult]:
    try:
        parsed = urllib_parse.urlsplit(url)
        if parsed.scheme.lower() not in VALID_SCHEMES or not parsed.hostname:
            return None
        if parsed.username or parsed.password:
            return None
        parsed.port  # Validate malformed ports.
        return parsed
    except (ValueError, UnicodeError):
        return None


def host_key_for(parsed: urllib_parse.SplitResult) -> str:
    host = (parsed.hostname or "").lower().rstrip(".")
    try:
        port = parsed.port
    except ValueError:
        port = None
    default = 443 if parsed.scheme.lower() == "https" else 80
    return host if port in {None, default} else "{}:{}".format(host, port)


def origin_key_for(parsed: urllib_parse.SplitResult) -> str:
    host = (parsed.hostname or "").lower().rstrip(".")
    try:
        port = parsed.port
    except ValueError:
        port = None
    default = 443 if parsed.scheme.lower() == "https" else 80
    effective_port = default if port is None else port
    return "{}://{}:{}".format(parsed.scheme.lower(), host, effective_port)


def registered_domain(host: str) -> str:
    """Return an approximate registered-domain proxy, never an entity claim."""
    value = host.lower().rstrip(".").split(":", 1)[0]
    labels = [part for part in value.split(".") if part]
    if len(labels) <= 2:
        return ".".join(labels)
    suffix = ".".join(labels[-2:])
    if suffix in COMMON_MULTI_PART_SUFFIXES and len(labels) >= 3:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(value or "")).strip()


def normalize_url(url: str) -> Optional[str]:
    parsed = parse_http_url(url)
    if parsed is None:
        return None
    host = (parsed.hostname or "").lower().rstrip(".")
    try:
        host = host.encode("idna").decode("ascii")
        port = parsed.port
    except (UnicodeError, ValueError):
        return None
    default = 443 if parsed.scheme.lower() == "https" else 80
    netloc = host if port in {None, default} else "{}:{}".format(host, port)
    path = parsed.path or "/"
    query_pairs = urllib_parse.parse_qsl(parsed.query, keep_blank_values=True)
    kept = [pair for pair in query_pairs if not TRACKING_PARAMETER.match(pair[0])]
    kept.sort()
    query = urllib_parse.urlencode(kept, doseq=True)
    return urllib_parse.urlunsplit((parsed.scheme.lower(), netloc, path, query, ""))


def github_repo_parts(url: str) -> Optional[Tuple[str, str]]:
    parsed = parse_http_url(url)
    if parsed is None or (parsed.hostname or "").lower() != "github.com":
        return None
    pieces = [urllib_parse.unquote(piece) for piece in parsed.path.split("/") if piece]
    if len(pieces) != 2 or not all(re.fullmatch(r"[A-Za-z0-9_.-]+", piece) for piece in pieces):
        return None
    return pieces[0], pieces[1].removesuffix(".git")


def is_github_repo(url: str) -> bool:
    return github_repo_parts(url) is not None


def github_readme_url(url: str) -> str:
    owner, repo = github_repo_parts(url) or ("", "")
    return "https://api.github.com/repos/{}/{}/readme".format(
        urllib_parse.quote(owner, safe=""), urllib_parse.quote(repo, safe="")
    )


def github_repo_api_url(url: str) -> str:
    owner, repo = github_repo_parts(url) or ("", "")
    return "https://api.github.com/repos/{}/{}".format(
        urllib_parse.quote(owner, safe=""), urllib_parse.quote(repo, safe="")
    )


def github_readme_metadata(text: str) -> Optional[Dict[str, object]]:
    try:
        value = json.loads(text)
    except (TypeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def github_decode_metadata(metadata: Dict[str, object]) -> Optional[str]:
    content = metadata.get("content")
    if not isinstance(content, str) or metadata.get("encoding") != "base64":
        return None
    compact = re.sub(r"\s+", "", content)
    try:
        decoded = base64.b64decode(compact, validate=True)
        return decoded.decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return None


def github_safe_path(path: object) -> Optional[str]:
    if not isinstance(path, str) or not path or path.startswith("/"):
        return None
    pieces = path.split("/")
    if any(piece in {"", ".", ".."} for piece in pieces):
        return None
    return "/".join(urllib_parse.quote(piece, safe="") for piece in pieces)


def github_raw_url(owner: str, repo: str, branch: str, path: str) -> Optional[str]:
    if not all(re.fullmatch(r"[A-Za-z0-9_.-]+", value) for value in (owner, repo)):
        return None
    if not isinstance(branch, str) or not branch or "\x00" in branch:
        return None
    safe_path = github_safe_path(path)
    if safe_path is None:
        return None
    return "https://raw.githubusercontent.com/{}/{}/{}/{}".format(
        urllib_parse.quote(owner, safe=""),
        urllib_parse.quote(repo, safe=""),
        urllib_parse.quote(branch, safe=""),
        safe_path,
    )


def github_readme_base(
    repo_url: str, metadata: Optional[Dict[str, object]], branch: str, path: str
) -> str:
    html_url = metadata.get("html_url") if metadata else None
    if isinstance(html_url, str) and parse_http_url(html_url):
        parsed = urllib_parse.urlsplit(html_url)
        if (parsed.hostname or "").lower() == "github.com":
            return html_url
    owner, repo = github_repo_parts(repo_url) or ("", "")
    safe_path = github_safe_path(path) or "README.md"
    return "https://github.com/{}/{}/blob/{}/{}".format(
        urllib_parse.quote(owner, safe=""), urllib_parse.quote(repo, safe=""),
        urllib_parse.quote(branch, safe=""), safe_path,
    )


def is_github_raw_response(result: FetchResult) -> bool:
    content_type = result.response_headers.get("content-type", "").lower()
    return "json" not in content_type and not result.body.lstrip().startswith("{")


def parse_html_links(text: str) -> List[Tuple[str, str]]:
    parser = AnchorParser()
    parser.feed(text)
    parser.close()
    return parser.links


def parse_markdown_links(text: str) -> List[Tuple[str, str]]:
    links: List[Tuple[str, str]] = []
    pattern = re.compile(
        r"(?<!!)(?:\[([^\]]+)\])\(\s*(?:<([^>]+)>|([^\s)]+))[^)]*\)",
        re.MULTILINE,
    )
    for match in pattern.finditer(text):
        target = match.group(2) or match.group(3) or ""
        links.append((target, clean_text(match.group(1))))
    return links


def candidate_flag(anchor: str, url: str) -> bool:
    return bool(CANDIDATE_TERMS.search(anchor) or CANDIDATE_TERMS.search(url))


def excluded_domain(host: str) -> bool:
    value = host.lower().rstrip(".").split(":", 1)[0]
    return any(
        value == domain or value.endswith("." + domain)
        for domain in EXCLUDED_REGISTERED_DOMAINS
    ) or registered_domain(value) in EXCLUDED_REGISTERED_DOMAINS


def candidate_from_link(
    hub_url: str,
    raw_href: str,
    anchor: str,
    require_candidate_terms: bool = False,
) -> Optional[str]:
    """Normalize one external link, with optional opt-in term filtering.

    The default deliberately keeps brand-name links such as Capital Factory;
    terms are only a configurable narrowing filter for exploratory runs.
    """
    if not raw_href:
        return None
    absolute = urllib_parse.urljoin(hub_url, html.unescape(raw_href.strip()))
    normalized = normalize_url(absolute)
    if normalized is None:
        return None
    parsed = urllib_parse.urlsplit(normalized)
    hub_normalized = normalize_url(hub_url)
    hub_parsed = urllib_parse.urlsplit(hub_normalized or hub_url)
    if parsed.scheme not in VALID_SCHEMES:
        return None
    if hub_normalized == normalized or host_key_for(parsed) == host_key_for(hub_parsed):
        return None
    if registered_domain(parsed.hostname or "") == registered_domain(hub_parsed.hostname or ""):
        return None
    if excluded_domain(parsed.hostname or ""):
        return None
    if require_candidate_terms and not candidate_flag(anchor, normalized):
        return None
    return normalized


def fallback_name(url: str) -> str:
    parsed = urllib_parse.urlsplit(url)
    label = (parsed.path.rstrip("/").split("/")[-1] or parsed.hostname or "").strip()
    label = urllib_parse.unquote(label).replace("_", " ").replace("-", " ")
    label = clean_text(label)
    return label or (parsed.hostname or url)


def load_hubs(path: Path = HUBS_PATH) -> List[Dict[str, object]]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("cannot load {}: {}".format(path, exc)) from exc
    if not isinstance(value, list) or not (1 <= len(value) <= 200):
        raise ValueError("{} must contain between one and 200 hub objects".format(path))
    required = {"hub_id", "url", "category", "type", "authoritative", "added_at"}
    hubs: List[Dict[str, object]] = []
    seen_ids: Set[str] = set()
    seen_urls: Set[str] = set()
    for index, item in enumerate(value, 1):
        if not isinstance(item, dict) or set(item) != required:
            raise ValueError("hub {} must have exactly hub_id, url, category, type, authoritative, added_at".format(index))
        if not all(isinstance(item[key], str) and item[key].strip() for key in required - {"authoritative"}):
            raise ValueError("hub {} string fields must be non-empty".format(index))
        if not isinstance(item["authoritative"], bool):
            raise ValueError("hub {} authoritative must be boolean".format(index))
        if item["category"] != "startup_founder" or item["type"] != "hub":
            raise ValueError("hub {} must have category=startup_founder and type=hub".format(index))
        if item["added_at"] != "2026-09-01T00:00:00Z":
            raise ValueError("hub {} must have added_at=2026-09-01T00:00:00Z".format(index))
        normalized = normalize_url(item["url"])
        if normalized is None:
            raise ValueError("hub {} has a malformed HTTP(S) URL: {}".format(index, item["url"]))
        if item["hub_id"] in seen_ids or normalized in seen_urls:
            raise ValueError("hub {} duplicates a hub id or URL".format(index))
        try:
            parsed_date = datetime.fromisoformat(item["added_at"].replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("hub {} has malformed added_at".format(index)) from exc
        if parsed_date.tzinfo is None or parsed_date.utcoffset() is None:
            raise ValueError("hub {} added_at must be timezone-aware ISO-8601".format(index))
        seen_ids.add(item["hub_id"])
        seen_urls.add(normalized)
        hubs.append(item)
    return hubs


def resolve_links(links: Iterable[Tuple[str, str]], base_url: str) -> List[Tuple[str, str]]:
    return [
        (urllib_parse.urljoin(base_url, html.unescape(href.strip())), anchor)
        for href, anchor in links
        if href
    ]


def _fetch_hub(fetcher: Fetcher, hub: Dict[str, str]) -> HubFetch:
    """Read one hub and retain acquisition details outside emitted records."""
    hub_url = hub["url"]
    if is_github_repo(hub_url):
        owner_repo = github_repo_parts(hub_url)
        assert owner_repo is not None
        owner, repo = owner_repo
        raw_results: List[Tuple[str, FetchResult]] = []
        for branch, method in (("master", "raw-master"), ("main", "raw-main")):
            raw_url = github_raw_url(owner, repo, branch, "README.md")
            if raw_url is None:
                continue
            result = fetcher.fetch(raw_url, {"Accept": "text/plain"})
            raw_results.append((method, result))
            if result.state == "live" and result.status == 200:
                links = parse_markdown_links(result.body)
                base = github_readme_base(hub_url, None, branch, "README.md")
                return HubFetch(
                    "processed",
                    resolve_links(links, base),
                    "{}; {}".format(method, result.reason or "robots_allow"),
                    base,
                    method,
                    len(links),
                )

        api_result = fetcher.fetch(
            github_readme_url(hub_url),
            {"Accept": "application/vnd.github.raw", "X-GitHub-Api-Version": "2022-11-28"},
        )
        api_metadata = github_readme_metadata(api_result.body) if api_result.state == "live" else None
        markdown: Optional[str] = None
        path = "README.md"
        if api_result.state == "live" and api_result.status == 200:
            if api_metadata is not None:
                markdown = github_decode_metadata(api_metadata)
                if isinstance(api_metadata.get("path"), str) and api_metadata["path"]:
                    path = api_metadata["path"]
            elif is_github_raw_response(api_result):
                markdown = api_result.body
        if markdown is not None:
            base = github_readme_base(hub_url, api_metadata, "HEAD", path)
            links = parse_markdown_links(markdown)
            return HubFetch(
                "processed",
                resolve_links(links, base),
                "api; {}".format(api_result.reason or "robots_allow"),
                base,
                "api",
                0,
            )

        fallback = fetcher.fetch(hub_url, {"Accept": "text/html, text/plain;q=0.9"})
        if fallback.state == "live" and fallback.status == 200:
            try:
                return HubFetch(
                    "processed",
                    parse_html_links(fallback.body),
                    "html; {}".format(fallback.reason or "robots_allow"),
                    fallback.final_url or hub_url,
                    "html",
                    0,
                )
            except (TypeError, ValueError) as exc:
                return HubFetch("failed", [], "HTML parse failed: {}".format(exc), hub_url, "failed")

        reasons = [
            "raw-master: {}".format(raw_results[0][1].reason or raw_results[0][1].state),
            "raw-main: {}".format(raw_results[1][1].reason or raw_results[1][1].state),
            "api: {}".format(api_result.reason or api_result.state),
            "html: {}".format(fallback.reason or fallback.state),
        ]
        blocked = any(
            result.state == "blocked"
            for result in [raw_results[0][1], raw_results[1][1], api_result, fallback]
        )
        return HubFetch(
            "blocked" if blocked else "failed",
            [],
            "; ".join(reasons),
            hub_url,
            "failed: " + ("; ".join(reasons)),
            0,
        )

    result = fetcher.fetch(hub_url, {"Accept": "text/html, text/plain;q=0.9"})
    if result.state == "blocked":
        return HubFetch("blocked", [], result.reason, hub_url, "failed: " + (result.reason or "blocked"))
    if result.state != "live" or result.status != 200:
        reason = result.reason or result.state
        return HubFetch("failed", [], reason, hub_url, "failed: " + reason)
    try:
        return HubFetch(
            "processed",
            parse_html_links(result.body),
            "HTML anchors; {}".format(result.reason or "robots_allow"),
            result.final_url or hub_url,
            "html",
            0,
        )
    except (TypeError, ValueError) as exc:
        reason = "HTML parse failed: {}".format(exc)
        return HubFetch("failed", [], reason, hub_url, "failed: " + reason)


def fetch_hub(
    fetcher: Fetcher, hub: Dict[str, str], include_stats: bool = False
):
    """Compatibility wrapper returning the historical four-value tuple."""
    outcome = _fetch_hub(fetcher, hub)
    values = (outcome.state, outcome.links, outcome.reason, outcome.base_url)
    if include_stats:
        return values + (outcome.method, outcome.raw_link_count)
    return values


def discover_candidates(
    hubs: Sequence[Dict[str, str]],
    fetcher: Fetcher,
    require_candidate_terms: bool = False,
    include_observations: bool = False,
):
    candidates: "OrderedDict[str, Candidate]" = OrderedDict()
    configured_hub_urls = {normalize_url(hub["url"]) for hub in hubs}
    hub_states: Dict[str, str] = {}
    hub_reasons: Dict[str, str] = {}
    hub_methods: Dict[str, str] = {}
    hub_raw_link_counts: Dict[str, int] = {}
    counts: Dict[str, Optional[int]] = {}
    failures = 0
    blocks = 0
    for hub in hubs:
        hub_id = hub["hub_id"]
        outcome = _fetch_hub(fetcher, hub)
        state, links, reason, html_base = (
            outcome.state,
            outcome.links,
            outcome.reason,
            outcome.base_url,
        )
        hub_states[hub_id] = state
        hub_reasons[hub_id] = reason
        hub_methods[hub_id] = outcome.method
        hub_raw_link_counts[hub_id] = outcome.raw_link_count
        if state == "failed":
            failures += 1
        elif state == "blocked":
            blocks += 1
        local: Set[str] = set()
        for raw_href, anchor in links:
            candidate_url = candidate_from_link(
                html_base, raw_href, anchor, require_candidate_terms
            )
            if candidate_url is None or candidate_url in configured_hub_urls:
                continue
            local.add(candidate_url)
            candidate = candidates.setdefault(candidate_url, Candidate(candidate_url))
            candidate.memberships.setdefault(hub_id, (hub["url"], clean_text(anchor)))
        counts[hub_id] = len(local) if state == "processed" else None
    result = list(candidates.values()), hub_states, hub_reasons, counts, failures, blocks
    if include_observations:
        return result + (hub_methods, hub_raw_link_counts)
    return result


def liveness_sample(candidates: Sequence[Candidate], hubs: Sequence[Dict[str, str]]) -> List[str]:
    queues: Dict[str, List[str]] = {hub["hub_id"]: [] for hub in hubs}
    for candidate in candidates:
        for hub_id in candidate.memberships:
            queues[hub_id].append(candidate.url)
    result: List[str] = []
    used: Set[str] = set()
    while len(result) < 20:
        added = False
        for hub in hubs:
            for url in queues[hub["hub_id"]]:
                if url not in used:
                    used.add(url)
                    result.append(url)
                    added = True
                    break
        if not added:
            break
    return result


def build_corroborating_hubs(
    candidate: Candidate, hubs: Sequence[Dict[str, str]]
) -> List[Dict[str, Optional[str]]]:
    """Return deterministic hub evidence for one candidate URL.

    Memberships are normally keyed by configured hub ID.  The URL fallback
    keeps this helper compatible with membership data that only retained a
    hub URL, while still resolving the configured ID when possible.
    """
    hub_order = {hub["hub_id"]: index for index, hub in enumerate(hubs)}
    hubs_by_id = {hub["hub_id"]: hub for hub in hubs}
    hubs_by_url = {hub["url"]: hub for hub in hubs}
    ordered_memberships = sorted(
        candidate.memberships,
        key=lambda value: (hub_order.get(value, len(hubs)), value),
    )
    corroborating: List[Dict[str, Optional[str]]] = []
    seen_hubs: Set[str] = set()
    for membership_id in ordered_memberships:
        source_hub, anchor = candidate.memberships[membership_id]
        configured = hubs_by_id.get(membership_id) or hubs_by_url.get(source_hub)
        hub_id = configured["hub_id"] if configured else membership_id
        hub_url = configured["url"] if configured else source_hub
        dedupe_key = configured["hub_id"] if configured else (source_hub or membership_id)
        if dedupe_key in seen_hubs:
            continue
        seen_hubs.add(dedupe_key)
        corroborating.append(
            {"hub_id": hub_id, "hub_url": hub_url, "anchor_text": anchor}
        )
    return corroborating


def build_records(candidates: Sequence[Candidate], hubs: Sequence[Dict[str, str]], checked_at: str) -> List[Dict[str, object]]:
    hub_order = {hub["hub_id"]: index for index, hub in enumerate(hubs)}
    records: List[Dict[str, object]] = []
    for candidate in sorted(candidates, key=lambda item: item.url):
        official_url = normalize_url(candidate.url)
        if official_url is None:
            continue
        winner_id = min(candidate.memberships, key=lambda value: (hub_order[value], value))
        source_hub, raw_anchor = candidate.memberships[winner_id]
        anchor = clean_text(raw_anchor)
        name = anchor or fallback_name(official_url)
        digest = hashlib.sha256(official_url.encode("utf-8")).hexdigest()[:20]
        corroborating_hubs = build_corroborating_hubs(candidate, hubs)
        corroborating_hubs = [
            {
                "hub_id": item["hub_id"],
                "hub_url": item["hub_url"],
                "anchor_text": clean_text(item["anchor_text"] or ""),
            }
            for item in corroborating_hubs
        ]
        records.append(
            {
                "record_type": "programme",
                "category": next(hub["category"] for hub in hubs if hub["hub_id"] == winner_id),
                "opportunity_type": "startup_programme",
                "programme_id": "startup-founder-programme-" + digest,
                "programme_name": clean_text(name),
                "official_url": official_url,
                "programme_status": "needs_confirmation",
                "deadline": None,
                "eligibility": "needs_confirmation",
                "funding": "not_stated",
                "official_evidence": {
                    "source_hub": source_hub,
                    "anchor_text": anchor,
                    "corroborating_hubs": corroborating_hubs,
                    "source_count": len(corroborating_hubs),
                },
                "last_checked_at": checked_at,
            }
        )
    return records


def liveness_counts(sample: Sequence[str], fetcher: Fetcher) -> Dict[str, int]:
    counts = {"live": 0, "blocked": 0, "dead": 0, "failed": 0}
    for url in sample:
        try:
            result = fetcher.fetch(url, {"Accept": "text/html, text/plain;q=0.9"})
        except RequestCapExceeded:
            counts["failed"] += 1
            continue
        if result.state == "live" and result.status == 200:
            counts["live"] += 1
        elif result.state in counts:
            counts[result.state] += 1
        else:
            counts["failed"] += 1
    return counts


def guarded_output_path(value: str) -> Path:
    """Allow writes only below the system temporary directory."""
    if "lake" in value.lower():
        raise ValueError("output path must not contain the substring lake")
    output = Path(value).expanduser()
    resolved = output.resolve()
    if "lake" in str(resolved).lower():
        raise ValueError("output path must not contain the substring lake")
    tmp_root = Path("/tmp").resolve()
    try:
        resolved.relative_to(tmp_root)
    except ValueError as exc:
        raise ValueError("output path must be inside /tmp") from exc
    return resolved


def write_records(path: Path, records: Sequence[Dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Optional[str] = None
    try:
        descriptor, temporary = tempfile.mkstemp(prefix="." + path.name + ".", dir=str(path.parent))
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(list(records), handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass


def print_stats(
    hubs: Sequence[Dict[str, str]],
    hub_states: Dict[str, str],
    hub_reasons: Dict[str, str],
    hub_counts: Dict[str, Optional[int]],
    failures: int,
    blocks: int,
    candidates: Sequence[Candidate],
    records: Sequence[Dict[str, object]],
    live: Dict[str, int],
    fetcher: Fetcher,
    hub_methods: Optional[Dict[str, str]] = None,
    hub_raw_link_counts: Optional[Dict[str, int]] = None,
) -> None:
    hub_methods = hub_methods or {hub["hub_id"]: "unknown" for hub in hubs}
    hub_raw_link_counts = hub_raw_link_counts or {hub["hub_id"]: 0 for hub in hubs}
    print("hubs processed: {} (failures={}, blocks={})".format(len(hubs), failures, blocks))
    reason_counts: Dict[str, int] = {}
    for hub in hubs:
        hub_id = hub["hub_id"]
        count = hub_counts[hub_id]
        count_text = str(count) if count is not None else "unavailable"
        reason = hub_reasons[hub_id]
        reason_counts[reason] = reason_counts.get(reason, 0) + 1
        print("hub {}: state={}, method={}, candidates={}, raw_link_count={}, reason={}".format(
            hub_id,
            hub_states[hub_id],
            hub_methods[hub_id],
            count_text,
            hub_raw_link_counts[hub_id],
            reason,
        ))
    print("reason summary: {}".format("; ".join(
        "{} x{}".format(reason, count) for reason, count in sorted(reason_counts.items())
    )))
    domains = {registered_domain(urllib_parse.urlsplit(candidate.url).hostname or "") for candidate in candidates}
    print("total unique startup-founder leads: {}".format(len(records)))
    print("registered-domain proxies: {}".format(len(domains)))
    print("liveness sample (live/blocked/dead/failed): {}/{}/{}/{}".format(
        live["live"], live["blocked"], live["dead"], live["failed"]
    ))
    print("total HTTP requests: {} (cap={})".format(fetcher.total_requests, REQUEST_CAP))
    print("samples:")
    for record in list(records)[:6]:
        print(json.dumps({"programme_name": record["programme_name"], "official_url": record["official_url"]}, ensure_ascii=False, sort_keys=True))


def run(output: Path, require_candidate_terms: bool = False) -> int:
    hubs = load_hubs()
    fetcher = Fetcher()
    try:
        (
            candidates,
            states,
            reasons,
            counts,
            failures,
            blocks,
            methods,
            raw_link_counts,
        ) = discover_candidates(
            hubs, fetcher, require_candidate_terms, include_observations=True
        )
        sample = liveness_sample(candidates, hubs)
        live = liveness_counts(sample, fetcher)
    except RequestCapExceeded as exc:
        raise RuntimeError(str(exc)) from exc
    checked_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    records = build_records(candidates, hubs, checked_at)
    write_records(output, records)
    print_stats(
        hubs,
        states,
        reasons,
        counts,
        failures,
        blocks,
        candidates,
        records,
        live,
        fetcher,
        methods,
        raw_link_counts,
    )
    print("output: {}".format(output))
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Dry-run startup-founder hub directory harvester")
    parser.add_argument(
        "--output", default=str(DEFAULT_OUTPUT),
        help="JSON output path below /tmp (default: /tmp/startup_founder_dryrun.json)",
    )
    parser.add_argument(
        "--require-candidate-terms", action="store_true",
        help="opt in to startup/founder term filtering for candidate links",
    )
    args = parser.parse_args(argv)
    try:
        output = guarded_output_path(args.output)
        return run(output, args.require_candidate_terms)
    except (ValueError, OSError, RuntimeError) as exc:
        print("harvest error: {}".format(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
