"""Turn category hub discoveries into deterministic programme seed records."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import time
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib import parse as urlparse

# Existing category modules use ``categories``/``core`` as top-level imports.
# Make that package layout available both from the repository root and from
# the engine directory, without changing those established modules.
ENGINE_ROOT = Path(__file__).resolve().parents[1]
if str(ENGINE_ROOT) not in sys.path:
    sys.path.insert(0, str(ENGINE_ROOT))
from categories.research import harvest as research_harvest
from categories.open_source import harvest as open_source_harvest
from categories.startup_founder import harvest as startup_harvest

try:
    from categories.fellowships import fellowships as fellowships_category
    from categories.scholarships import scholarships as scholarships_category
    from categories.grants import grants as grants_category
    from categories.research import research as research_category
    from categories.open_source import programmes as open_source_category
    from categories.community import programmes as community_category
    from categories.startup_founder import programmes as startup_founder_category
except ImportError:  # pragma: no cover - supports package-root imports
    from engine.categories.fellowships import fellowships as fellowships_category
    from engine.categories.scholarships import scholarships as scholarships_category
    from engine.categories.grants import grants as grants_category
    from engine.categories.research import research as research_category
    from engine.categories.open_source import programmes as open_source_category
    from engine.categories.community import programmes as community_category
    from engine.categories.startup_founder import programmes as startup_founder_category

DIRECTORY_CATEGORIES = frozenset(("fellowships", "scholarships", "grants"))
DIRECTORY_TERMS = re.compile(
    r"(?:research|reu|fellowship|internship|undergraduate[\\s_-]*research|"
    r"scholarship|grant|award|program(?:me)?s?)",
    re.IGNORECASE,
)
try:
    from categories.programme_core import COMMUNITY_SPECIFIC_NOUN_PATTERN
except ImportError:  # pragma: no cover - supports package-root imports
    from engine.categories.programme_core import COMMUNITY_SPECIFIC_NOUN_PATTERN

COMMUNITY_TERMS = re.compile(COMMUNITY_SPECIFIC_NOUN_PATTERN, re.IGNORECASE)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_DIR = REPO_ROOT / "engine" / "data" / "operations" / "generated_seeds"
GENERIC_NAMES = frozenset({
    "apply", "apply now", "learn more", "read more", "more", "website",
    "click here", "here", "link", "home", "visit", "visit site", "details",
    "info", "register", "sign up",
})
from core import pagetext
try:
    from categories.programme_core import programme_title_ok, should_route_research_seed
except ImportError:  # pragma: no cover - supports package-root imports
    from engine.categories.programme_core import programme_title_ok, should_route_research_seed


_ADMISSION_PATH_SEGMENTS = frozenset({
    "blog", "blogs", "news", "newsroom", "newsfeed", "press", "article",
    "articles", "post", "posts", "story", "stories", "jobs", "job",
    "careers", "career", "alumni", "alums", "alumnus", "past-interns",
    "archive", "tag", "tags", "category", "author", "wp-content", "wiki",
    "podcast", "video", "videos", "events-archive",
})
_ADMISSION_HOSTS = frozenset({
    "medium.com", "substack.com", "freecodecamp.org", "dev.to", "wikipedia.org",
    "news.ycombinator.com", "paulgraham.com", "greenhouse.io", "lever.co",
    "workday.com", "myworkdayjobs.com", "ashbyhq.com", "smartrecruiters.com",
    "bamboohr.com",
})
# Keep this list in one place: it is the allow signal for the page-level
# relevance gate, rather than a category-specific collection policy.
TECH_RELEVANCE_KEYWORDS = (
    "computer science", "software", "engineering", "engineer", "artificial intelligence",
    "ai", "machine learning", "deep learning", "data", "research", "stem",
    "cybersecurity", "cyber security", "open source", "developer", "development",
    "coding", "programming", "technology", "tech", "computing", "robotics",
    "cloud", "quantum", "mathematics", "statistics", "informatics", "digital",
    "algorithm", "blockchain", "bioinformatics", "techmakers",
)
_ADMISSION_FORM_HOSTS = frozenset({
    "tally.so", "forms.gle", "typeform.com", "airtable.com", "jotform.com",
    "surveymonkey.com", "linktr.ee",
})
_ADMISSION_CURRENT_YEAR = 2026
_ADMISSION_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")
_ADMISSION_STALE_MARKER = re.compile(r"\b(?:previous|outdated|archived|archive)\b", re.IGNORECASE)
_ADMISSION_PROGRAMME_WORDS = (
    "fellowship", "scholarship", "program", "programme", "grant", "internship",
    "residency", "award", "prize", "mentorship", "scheme", "accelerator",
    "challenge", "bursary", "stipend", "studentship",
)
_ADMISSION_DIRECTORY_TERMS = re.compile(
    r"\b(?:finder|directory|database|list\s+of|top\s+(?:10|20)|best|compare)\b",
    re.IGNORECASE,
)
# WorldQuant BRAIN is the programme's branded name, while its page prose
# identifies it as a programme. Keep this exception tied to both the exact
# brand and page-text evidence instead of broadening the title vocabulary.
_ADMISSION_PAGE_EVIDENCE_NAMES = frozenset({"worldquant brain"})
_ADMISSION_AMBASSADOR = re.compile(
    r"\b(?:ambassadors?|representatives?|campus[\s_-]*(?:reps?|representatives?|leaders?))\b",
    re.IGNORECASE,
)
_ADMISSION_US_STATES = frozenset({
    "alabama", "alaska", "arizona", "arkansas", "california", "colorado",
    "connecticut", "delaware", "florida", "georgia", "hawaii", "idaho",
    "illinois", "indiana", "iowa", "kansas", "kentucky", "louisiana",
    "maine", "maryland", "massachusetts", "michigan", "minnesota",
    "mississippi", "missouri", "montana", "nebraska", "nevada", "new hampshire",
    "new jersey", "new mexico", "new york", "north carolina", "north dakota",
    "ohio", "oklahoma", "oregon", "pennsylvania", "rhode island",
    "south carolina", "south dakota", "tennessee", "texas", "utah", "vermont",
    "virginia", "washington", "west virginia", "wisconsin", "wyoming",
    "district of columbia",
})
_ADMISSION_GENERIC_NAMES = frozenset({
    "home", "research", "blog", "news", "about", "about us", "programs",
    "programmes", "apply", "learn more", "read more", "details and link to apply",
    "past interns", "overview", "welcome", "details", "more", "website",
    "click here", "here", "link", "visit", "visit site", "info", "register",
    "sign up", "apply now", "acerca de", "sobre", "contact", "contact us",
    "faq", "faqs", "home page", "homepage", "login", "log in", "menu", "search",
    "skip to content",
})
_ADMISSION_PROGRAMME_NOUNS = _ADMISSION_PROGRAMME_WORDS
_ADMISSION_APPLICATION_SIGNALS = (
    "apply", "application", "eligib", "deadline", "admission", "nominat", "enrol",
    "cohort", "join us",
)
_ADMISSION_DATE_PATH = re.compile(r"/(?:20\d{2}/\d{2}/|20\d{2}-\d{2}-\d{2}(?:/|$))", re.I)
_ADMISSION_SUFFIX = re.compile(r"\s+(?:\||-|–|—|::)\s+.*$")


class _AdmissionHTMLParser(HTMLParser):
    """Small, forgiving extractor for the fields needed before parsing a seed."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.h1 = ""
        self.title = ""
        self.og_type = ""
        self.og_site_name = ""
        self.og_title = ""
        self.json_ld: List[str] = []
        self._capture: Optional[str] = None
        self._buffer: List[str] = []
        self._h1_seen = False

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        lowered = tag.lower()
        values = {str(key).lower(): value or "" for key, value in attrs}
        if lowered == "meta":
            prop = (values.get("property") or values.get("name") or "").casefold()
            if prop == "og:type" and not self.og_type:
                self.og_type = values.get("content", "")
            elif prop == "og:site_name" and not self.og_site_name:
                self.og_site_name = values.get("content", "")
            elif prop == "og:title" and not self.og_title:
                self.og_title = values.get("content", "")
        elif lowered == "h1" and not self._h1_seen:
            self._h1_seen = True
            self._capture = "h1"
            self._buffer = []
        elif lowered == "title" and not self.title and self._capture is None:
            self._capture = "title"
            self._buffer = []
        elif lowered == "script" and values.get("type", "").casefold() == "application/ld+json":
            self._capture = "jsonld"
            self._buffer = []

    def handle_endtag(self, tag: str) -> None:
        expected = "script" if self._capture == "jsonld" else self._capture
        if self._capture is None or tag.casefold() != expected:
            return
        value = _collapsed(" ".join(self._buffer))
        if self._capture == "h1":
            self.h1 = value
        elif self._capture == "title":
            self.title = value
        else:
            self.json_ld.append(value)
        self._capture = None
        self._buffer = []

    def handle_data(self, data: str) -> None:
        if self._capture is not None:
            self._buffer.append(data)

    def finish(self) -> None:
        if self._capture is not None:
            self.handle_endtag("script" if self._capture == "jsonld" else self._capture)


def _admission_page_fields(html: str) -> _AdmissionHTMLParser:
    parser = _AdmissionHTMLParser()
    try:
        parser.feed(html or "")
        parser.close()
    except (TypeError, ValueError):
        pass
    parser.finish()
    return parser


def _admission_blocked_form_host(url: str) -> bool:
    try:
        parsed = urlparse.urlsplit(url)
        host = (parsed.hostname or "").casefold().rstrip(".")
        path = (parsed.path or "/").casefold()
    except (TypeError, ValueError):
        return False
    if host == "docs.google.com":
        return path == "/forms" or path.startswith("/forms/")
    if host in _ADMISSION_FORM_HOSTS or any(
            host.endswith("." + blocked) for blocked in _ADMISSION_FORM_HOSTS):
        return True
    return False


def _admission_contains_keyword(value: str) -> bool:
    lowered = (value or "").casefold()
    for keyword in TECH_RELEVANCE_KEYWORDS:
        escaped = re.escape(keyword.casefold()).replace(r"\ ", r"\s+")
        if re.search(r"(?<![a-z0-9]){}(?![a-z0-9])".format(escaped), lowered):
            return True
    return False


def _admission_geography_locked(value: str) -> bool:
    lowered = (value or "").casefold()
    state_pattern = r"(?:{})".format("|".join(
        re.escape(state) for state in sorted(_ADMISSION_US_STATES, key=len, reverse=True)
    ))
    if not re.search(r"\b{}\b".format(state_pattern), lowered):
        return False
    # State names in a university or organizer name are not by themselves a
    # lock. These terms identify state-resident/student-only aid pages.
    if re.search(r"\b(?:resident|residents|student|students|aid|tuition|scholarship|award)\b", lowered):
        return True
    return bool(re.search(r"\b(?:only|exclusive|eligib)\w*\b", lowered))


def _admission_is_stale_year(title: str, h1: str, *urls: str) -> bool:
    # H1 years are source evidence too; only a current/future title year can
    # establish that an otherwise stale page is the current cycle.
    title_text = title or ""
    title_years = [int(item) for item in _ADMISSION_YEAR.findall(title_text)]
    source_years = title_years + [
        int(item) for item in _ADMISSION_YEAR.findall(h1 or "")
    ]
    for url in urls:
        try:
            source_years.extend(
                int(item) for item in _ADMISSION_YEAR.findall(urlparse.urlsplit(url).path or "")
            )
        except (TypeError, ValueError):
            continue
    has_past_source_year = any(year <= _ADMISSION_CURRENT_YEAR - 1 for year in source_years)
    has_current_title_year = any(
        int(item) >= _ADMISSION_CURRENT_YEAR
        for item in _ADMISSION_YEAR.findall(title_text)
    )
    return (has_past_source_year and not has_current_title_year) or bool(
        _ADMISSION_STALE_MARKER.search(title_text)
    )


def _admission_is_ambassador(title: str, h1: str, name: str, *urls: str) -> bool:
    value = " ".join((title or "", h1 or "", name or "", *urls))
    return bool(_ADMISSION_AMBASSADOR.search(value))


def _admission_url_pattern(url: str) -> bool:
    try:
        parsed = urlparse.urlsplit(url)
        host = (parsed.hostname or "").casefold().rstrip(".")
    except (TypeError, ValueError):
        return True
    if parsed.scheme.casefold() not in {"http", "https"} or not host:
        return True
    segments = {part.casefold() for part in (parsed.path or "/").split("/") if part}
    if segments & _ADMISSION_PATH_SEGMENTS or _ADMISSION_DATE_PATH.search(parsed.path or ""):
        return True
    if (host in _ADMISSION_HOSTS or
            any(host.endswith("." + blocked) for blocked in _ADMISSION_HOSTS) or
            host.startswith(("blog.", "careers.", "jobs.", "news.")) or
            host.endswith(".jobs")):
        return True
    return False


def _admission_types(value: Any) -> Iterable[str]:
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "@type":
                if isinstance(child, str):
                    yield child
                elif isinstance(child, list):
                    yield from (item for item in child if isinstance(item, str))
            else:
                yield from _admission_types(child)
    elif isinstance(value, list):
        for child in value:
            yield from _admission_types(child)


def _has_admission_programme_signal(value: str) -> bool:
    for noun in _ADMISSION_PROGRAMME_NOUNS:
        if re.search(r"(?<![A-Za-z0-9]){}(?![A-Za-z0-9])".format(re.escape(noun)), value, re.I):
            return True
    return False


def _has_admission_programme_signal_for_category(value: str, category: str) -> bool:
    if category == "community":
        return COMMUNITY_TERMS.search(value or "") is not None
    return _has_admission_programme_signal(value)


def _admission_is_directory_page(*values: str) -> bool:
    return bool(_ADMISSION_DIRECTORY_TERMS.search(" ".join(value or "" for value in values)))


def _admission_has_page_programme_evidence(name: str, visible: str) -> bool:
    return (
        name.casefold() in _ADMISSION_PAGE_EVIDENCE_NAMES
        and _has_admission_programme_signal(visible)
    )


_ADMISSION_TITLE_SPLITTER = re.compile(r" \| | - | – | — | :: | : | · ")
_ADMISSION_EDGE_CHARS = " \t\r\n\"'“”‘’‹›«»"
_ADMISSION_SLOGAN_PREFIX = re.compile(
    r"^(?:we|our|learn|join|welcome|discover|build|get|become|two|one|your)(?:\b|$)"
    r"|^the best(?:\b|$)|^why(?:\b|$)",
    re.I,
)


def _admission_name(value: str) -> str:
    """Normalise page text without composing a name from separate fields."""
    name = _collapsed(value)
    name = name.strip(_ADMISSION_EDGE_CHARS)
    name = re.sub(r"[^\w\s]+$", "", name).strip()
    return name


def _admission_name_candidates(page: _AdmissionHTMLParser, anchor: str) -> List[Tuple[str, str]]:
    raw_values: List[str] = []
    raw_values.extend(_ADMISSION_TITLE_SPLITTER.split(page.title) if page.title else [])
    if page.og_site_name:
        raw_values.append(page.og_site_name)
    raw_values.extend(_ADMISSION_TITLE_SPLITTER.split(page.og_title) if page.og_title else [])
    if page.h1:
        raw_values.append(page.h1)
    if anchor:
        raw_values.append(anchor)
    return [(raw, _admission_name(raw)) for raw in raw_values if _admission_name(raw)]


def _admission_name_passes(raw: str, name: str, require_noun: bool = True) -> bool:
    raw_end = _collapsed(raw).rstrip(_ADMISSION_EDGE_CHARS)
    if raw_end.endswith((".", "!", "?")):
        return False
    if not (4 <= len(name) <= 80):
        return False
    words = re.findall(r"\b[\w]+(?:['’][\w]+)?\b", name, re.UNICODE)
    if not (1 <= len(words) <= 8):
        return False
    lowered = name.casefold()
    if lowered in _ADMISSION_GENERIC_NAMES or any(char in raw or char in name for char in "€$£%"):
        return False
    if _ADMISSION_SLOGAN_PREFIX.search(name):
        return False
    return not require_noun or _has_admission_programme_signal(name)


def _admission_host_label(url: str) -> str:
    try:
        host = (urlparse.urlsplit(url).hostname or "").casefold().rstrip(".")
    except (TypeError, ValueError):
        return ""
    registered = research_harvest.registered_domain(host)
    return registered.split(".", 1)[0]


def _admission_host_overlap(name: str, url: str) -> bool:
    label = re.sub(r"[^a-z0-9]", "", _admission_host_label(url))
    if not label:
        return False
    words = re.findall(r"[a-z0-9]+", name.casefold())
    compact = "".join(words)
    return compact == label or any(len(word) >= 3 and (word in label or label in word)
                                   for word in words)


def admit_candidate(
    html: str,
    url: str,
    category: str,
    anchor: str = "",
    effective_url: str = "",
) -> Tuple[bool, str, str]:
    """Pure page-level gate for turning a discovered link into a programme seed."""
    category_is_directory = category in DIRECTORY_CATEGORIES
    checked_urls = tuple(item for item in (url, effective_url) if item)
    if any(_admission_blocked_form_host(item) for item in checked_urls):
        return False, "blocked_form_host", ""
    if _admission_url_pattern(url):
        return False, "url_pattern", ""
    page = _admission_page_fields(html)
    stale_title = " ".join(filter(None, (page.title, anchor)))
    if _admission_is_stale_year(stale_title, page.h1, *checked_urls):
        return False, "stale_year", ""
    if category != "community" and _admission_is_ambassador(page.title, page.h1, anchor, *checked_urls):
        return False, "ambassador", ""
    for script in page.json_ld:
        try:
            payload = json.loads(script)
        except (TypeError, ValueError):
            continue
        if any(item.casefold() in {"article", "newsarticle", "blogposting", "jobposting"}
               for item in _admission_types(payload)):
            return False, "article_or_job", ""
    if page.og_type.strip().casefold() == "article":
        return False, "article_or_job", ""
    if _admission_is_directory_page(
        page.title, page.h1, page.og_title, page.og_site_name, anchor, url,
    ):
        return False, "directory_page", ""

    candidates = _admission_name_candidates(page, anchor)
    # A host-labelled first segment is a useful brand name even when a later
    # title segment is marketing copy containing a programme noun.
    for raw, name in candidates:
        if (not category_is_directory and
                _admission_name_passes(raw, name, require_noun=False) and
                not _has_admission_programme_signal_for_category(name, category) and
                _admission_host_overlap(name, url)):
            return_name = name
            break
    else:
        return_name = ""
    if not return_name:
        for raw, name in candidates:
            if (_admission_name_passes(raw, name)
                    or (category == "community"
                        and _admission_name_passes(raw, name, require_noun=False)
                        and _has_admission_programme_signal_for_category(name, category))):
                return_name = name
                break
    if not return_name:
        for raw, name in candidates:
            if (_admission_name_passes(raw, name, require_noun=False) and
                    (_has_admission_programme_signal_for_category(name, category) or
                     name.casefold() in _ADMISSION_PAGE_EVIDENCE_NAMES) and
                    ((not category_is_directory and _admission_host_overlap(name, url)) or
                     name.casefold() in _ADMISSION_PAGE_EVIDENCE_NAMES)):
                return_name = name
                break
    if not return_name:
        return False, "no_name", ""

    visible = pagetext.to_text(html or "")
    header_text = " ".join((page.title, page.h1))
    page_evidence = _admission_has_page_programme_evidence(return_name, visible)
    if (not _has_admission_programme_signal_for_category(header_text, category)
            and not page_evidence):
        return False, "no_programme_signal", ""
    page_text = " ".join(filter(None, (page.title, page.og_title, page.h1, visible)))
    if (category != "community"
            and _admission_is_ambassador(page.title, page.h1, " ".join((return_name, anchor)), *checked_urls)):
        return False, "ambassador", ""
    if _admission_is_stale_year(stale_title, page.h1, *checked_urls):
        return False, "stale_year", ""
    # Body prose remains a useful technical signal; stale-year is deliberately
    # checked above without it so navigation/footer years cannot rescue a page.
    relevance_text = page_text
    if (not _admission_contains_keyword(relevance_text)
            and not (category == "community" and COMMUNITY_TERMS.search(relevance_text))):
        return False, "no_tech_signal", ""
    if not any(signal in visible.casefold() for signal in _ADMISSION_APPLICATION_SIGNALS):
        return False, "no_application_signal", ""
    return True, "admitted", return_name


def _fetch_parts(result: Any) -> Tuple[Optional[int], str, str, str]:
    """Normalize resolver tuples and research FetchResult objects."""
    if isinstance(result, tuple):
        if len(result) >= 4:
            return result[0], str(result[1] or ""), str(result[2] or ""), str(result[3] or "")
        if len(result) == 2:
            return 200, str(result[1] or ""), str(result[0] or ""), ""
    status = getattr(result, "status", None)
    state = str(getattr(result, "state", ""))
    body = str(getattr(result, "body", "") or "")
    final_url = str(getattr(result, "final_url", "") or getattr(result, "url", "") or "")
    reason = str(getattr(result, "reason", "") or "")
    if status is None and state == "live":
        status = 200
    return status, final_url, body, reason


def admit_seeds(
    category: str,
    seeds: Iterable[Dict],
    fetch: Callable,
    robots_allowed: Callable,
    max_fetch: int = 120,
) -> Tuple[List[Dict], List[Dict[str, str]]]:
    """Fetch candidate pages politely and return only page-admitted seed records."""
    global LAST_ADMISSION_STATS
    admitted: List[Dict] = []
    rejected: List[Dict[str, str]] = []
    host_last: Dict[str, float] = {}
    rate_limited_hosts = set()
    page_fetches = 0
    fetched_results: Dict[str, Tuple[Optional[int], str, str, str]] = {}
    fetch_call = fetch.fetch if hasattr(fetch, "fetch") else fetch
    for seed in seeds:
        if not isinstance(seed, dict):
            rejected.append({"url": "", "reason": "invalid_seed"})
            continue
        url = str(seed.get("official_url") or "")
        if _admission_blocked_form_host(url):
            rejected.append({"url": url, "reason": "blocked_form_host"})
            continue
        if _admission_url_pattern(url):
            rejected.append({"url": url, "reason": "url_pattern"})
            continue
        parsed = urlparse.urlsplit(url)
        host = (parsed.hostname or "").casefold()
        if host in rate_limited_hosts:
            rejected.append({"url": url, "reason": "rate_limited"})
            continue
        try:
            allowed_result = robots_allowed(url)
            allowed = allowed_result[0] if isinstance(allowed_result, tuple) else allowed_result
        except Exception:
            rejected.append({"url": url, "reason": "robots_error"})
            continue
        if not allowed:
            rejected.append({"url": url, "reason": "robots_disallowed"})
            continue
        if url in fetched_results:
            status, final_url, html, error = fetched_results[url]
        else:
            if page_fetches >= max_fetch:
                rejected.append({"url": url, "reason": "fetch_cap"})
                continue
            previous = host_last.get(host)
            if previous is not None:
                wait_for = 1.0 - (time.monotonic() - previous)
                if wait_for > 0:
                    time.sleep(wait_for)
            host_last[host] = time.monotonic()
            page_fetches += 1
            try:
                fetched_results[url] = _fetch_parts(fetch_call(url))
            except Exception:
                fetched_results[url] = (None, "", "", "fetch_exception")
            status, final_url, html, error = fetched_results[url]
        if status == 429:
            rate_limited_hosts.add(host)
            rejected.append({"url": url, "reason": "rate_limited"})
            continue
        if error or status is None or status >= 400 or not html:
            rejected.append({"url": url, "reason": "fetch_error"})
            continue
        evidence = seed.get("official_evidence")
        anchor = evidence.get("anchor_text", "") if isinstance(evidence, dict) else ""
        ok, reason, name = admit_candidate(
            html, url, category, str(anchor or ""), effective_url=final_url,
        )
        if not ok:
            rejected.append({"url": url, "reason": reason})
            continue
        admitted_seed = dict(seed)
        admitted_seed["programme_name"] = name
        admitted.append(admitted_seed)
    LAST_ADMISSION_STATS = {
        key: sum(1 for item in rejected if item.get("reason") == reason)
        for reason, key in _FILTER_COUNTERS.items()
    }
    return admitted, rejected

EXTRA_EXCLUDED_DOMAINS = frozenset({
    "twitter.com", "x.com", "linkedin.com", "facebook.com", "instagram.com",
    "youtube.com", "reddit.com", "t.me", "discord.gg", "medium.com", "github.com",
})
REQUIRED_SEED_FIELDS = (
    "source_id", "programme_id", "programme_name", "organizer", "official_url",
    "allowed_path_hints", "check_cadence",
)
LAST_GENERATE_STATS: Dict[str, object] = {}
LAST_ADMISSION_STATS: Dict[str, int] = {}
LAST_SEED_GATE_REJECTIONS: Dict[str, int] = {}
LAST_ROUTED_RESEARCH_SEEDS: List[Dict] = []


_FILTER_COUNTERS = {
    "blocked_form_host": "rejected_form_host",
    "no_tech_signal": "rejected_tech",
    "stale_year": "rejected_stale_year",
    "ambassador": "rejected_ambassador",
    "directory_page": "rejected_directory",
    "no_programme_signal": "rejected_programme_signal",
    "no_name": "rejected_no_name",
    "url_pattern": "rejected_url_pattern",
    "article_or_job": "rejected_article_or_job",
    "fetch_error": "rejected_fetch_error",
    "no_application_signal": "rejected_application_signal",
    "robots_disallowed": "rejected_robots",
    "robots_error": "rejected_robots_error",
    "rate_limited": "rejected_rate_limited",
    "fetch_cap": "rejected_fetch_cap",
    "invalid_seed": "rejected_invalid_seed",
}


def _collapsed(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _normalise_url(value: object) -> Optional[str]:
    if not isinstance(value, str):
        return None
    parsed = research_harvest.parse_http_url(value.strip())
    if parsed is None:
        return None
    host = (parsed.hostname or "").lower().rstrip(".")
    try:
        host = host.encode("idna").decode("ascii")
        port = parsed.port
    except (UnicodeError, ValueError):
        return None
    default_port = 443 if parsed.scheme.lower() == "https" else 80
    netloc = host if port in {None, default_port} else "{}:{}".format(host, port)
    path = parsed.path or "/"
    if path != "/":
        path = path.rstrip("/") or "/"
    tracking = re.compile(r"^(?:utm_.+|fbclid|gclid)$", re.IGNORECASE)
    pairs = [pair for pair in urlparse.parse_qsl(parsed.query, keep_blank_values=True)
             if not tracking.match(pair[0])]
    pairs.sort()
    query = urlparse.urlencode(pairs, doseq=True)
    return urlparse.urlunsplit((parsed.scheme.lower(), netloc, path, query, ""))


def _host_path(value: object) -> Optional[Tuple[str, str]]:
    normalized = _normalise_url(value)
    if normalized is None:
        return None
    parsed = urlparse.urlsplit(normalized)
    return (parsed.netloc.lower(), parsed.path or "/")


def _excluded_host(host: str) -> bool:
    lowered = host.lower().rstrip(".")
    excluded = set(getattr(research_harvest, "EXCLUDED_REGISTERED_DOMAINS", ()))
    excluded.update(EXTRA_EXCLUDED_DOMAINS)
    if lowered in excluded or any(lowered.endswith("." + domain) for domain in excluded):
        return True
    return research_harvest.registered_domain(lowered) in excluded


def _slug_prefix(normalized_url: str) -> str:
    parsed = urlparse.urlsplit(normalized_url)
    pieces = [parsed.hostname or ""]
    pieces.extend([part for part in parsed.path.split("/") if part][:2])
    value = re.sub(r"[^a-z0-9]+", "-", "-".join(pieces).lower()).strip("-")
    return value[:60].rstrip("-") or "site"


def _source_count(candidate: Dict) -> int:
    evidence = candidate.get("official_evidence")
    if not isinstance(evidence, dict):
        return 0
    value = evidence.get("source_count", 0)
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        corroborating = evidence.get("corroborating_hubs")
        return len(corroborating) if isinstance(corroborating, list) else 0


def _candidate_name(candidate: Dict) -> str:
    evidence = candidate.get("official_evidence")
    anchor = evidence.get("anchor_text") if isinstance(evidence, dict) else None
    return _collapsed(anchor or candidate.get("programme_name"))


def _seed_record(category: str, normalized: str, candidate: Dict) -> Dict:
    parsed = urlparse.urlsplit(normalized)
    host = (parsed.hostname or "").lower()
    name = _candidate_name(candidate)[:120]
    prefix = _slug_prefix(normalized)
    digest = hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:6]
    slug = prefix + "-" + digest
    path = (parsed.path or "/").strip("/")
    record = {
        "source_id": "hub-{}-{}".format(category, slug),
        "programme_id": "{}-hub-{}".format(category, slug),
        "programme_name": name,
        "organizer": host[4:] if host.startswith("www.") else host,
        "official_url": normalized,
        "allowed_path_hints": [path] if path else [""],
        "check_cadence": "monthly",
    }
    if candidate.get("_needs_page_noun"):
        record["needs_page_noun"] = True
    return record


def candidates_to_seeds(
    category: str,
    candidates: Iterable[Dict],
    existing_seeds: Iterable[Dict],
    max_per_host: int = 5,
    max_total: int = 200,
) -> List[Dict]:
    """Convert harvester candidates, routing academic internships to research."""
    global LAST_SEED_GATE_REJECTIONS, LAST_ROUTED_RESEARCH_SEEDS
    LAST_SEED_GATE_REJECTIONS = {}
    LAST_ROUTED_RESEARCH_SEEDS = []
    if max_per_host <= 0 or max_total <= 0:
        return []
    existing = {_host_path(seed.get("official_url")) for seed in existing_seeds
                if isinstance(seed, dict)}
    existing.discard(None)
    chosen: Dict[str, Tuple[int, str, Dict]] = {}
    routed: Dict[str, Tuple[int, str, Dict]] = {}
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        name = _candidate_name(candidate)
        if not name or len(name) < 4 or name.casefold() in GENERIC_NAMES:
            continue
        normalized = _normalise_url(candidate.get("official_url"))
        if normalized is None:
            continue
        if category in DIRECTORY_CATEGORIES:
            title_ok, title_reason = programme_title_ok(name, normalized, category)
            if not title_ok:
                route_seed = {"programme_name": name, "official_url": normalized}
                if should_route_research_seed(route_seed, category, title_reason):
                    count = _source_count(candidate)
                    tie_key = (name.casefold(), normalized)
                    previous = routed.get(normalized)
                    if previous is None or (count, "", tie_key) > (previous[0], "", previous[1]):
                        routed[normalized] = (count, tie_key, candidate)
                    continue
                if (title_reason == "missing_programme_noun"
                        and category in {"fellowships", "fellowship"}):
                    candidate = dict(candidate)
                    candidate["_needs_page_noun"] = True
                else:
                    LAST_SEED_GATE_REJECTIONS[title_reason] = LAST_SEED_GATE_REJECTIONS.get(title_reason, 0) + 1
                    continue
        parsed = urlparse.urlsplit(normalized)
        host = (parsed.hostname or "").lower()
        if not host or _excluded_host(host) or (host, parsed.path or "/") in existing:
            continue
        count = _source_count(candidate)
        tie_key = (name.casefold(), normalized)
        previous = chosen.get(normalized)
        if previous is None or (count, "", tie_key) > (previous[0], "", previous[1]):
            chosen[normalized] = (count, tie_key, candidate)

    def build_seed_list(entries: Dict[str, Tuple[int, str, Dict]], category_name: str) -> List[Dict]:
        ordered = sorted(entries.items(), key=lambda item: (-item[1][0], item[0]))
        result: List[Dict] = []
        host_counts: Dict[str, int] = {}
        for normalized, (_, _, candidate) in ordered:
            parsed = urlparse.urlsplit(normalized)
            host = (parsed.hostname or "").lower()
            if host_counts.get(host, 0) >= max_per_host:
                continue
            result.append(_seed_record(category_name, normalized, candidate))
            host_counts[host] = host_counts.get(host, 0) + 1
            if len(result) >= max_total:
                break
        return result

    result = build_seed_list(chosen, category)
    LAST_ROUTED_RESEARCH_SEEDS = build_seed_list(routed, "research")
    if LAST_ROUTED_RESEARCH_SEEDS:
        LAST_SEED_GATE_REJECTIONS["routed_research"] = len(LAST_ROUTED_RESEARCH_SEEDS)
    return result


def _load_category_hubs(category: str, hubs_path: Path) -> List[Dict[str, object]]:
    if category == "startup_founder":
        return startup_harvest.load_hubs(hubs_path)
    if category == "open_source":
        return open_source_harvest.load_hubs(hubs_path)
    return research_harvest.load_hubs(
        hubs_path, category=category, exact_count=None, min_hubs=1,
        max_hubs=200, allow_authoritative=True,
    )


def _policy(category: str):
    if category == "open_source":
        return open_source_harvest.OPEN_SOURCE_TERMS, True
    if category == "startup_founder":
        return startup_harvest.CANDIDATE_TERMS, False
    if category == "community":
        return COMMUNITY_TERMS, False
    if category in DIRECTORY_CATEGORIES:
        return DIRECTORY_TERMS, False
    return research_harvest.CANDIDATE_TERMS, False


def _static_seeds(category: str) -> Tuple[Dict, ...]:
    modules = {
        "fellowships": fellowships_category,
        "scholarships": scholarships_category,
        "grants": grants_category,
        "research": research_category,
        "open_source": open_source_category,
        "community": community_category,
        "startup_founder": startup_founder_category,
    }
    module = modules.get(category)
    if module is None:
        return ()
    static = getattr(module, "STATIC_SOURCE_REGISTRY", None)
    if static is not None:
        return tuple(static)
    loader = getattr(module, "_load_seed_registry", None)
    if loader is None:
        return tuple(getattr(module, "SOURCE_REGISTRY", ()))
    previous = os.environ.pop(GENERATED_SEEDS_ENV, None)
    try:
        return tuple(loader())
    finally:
        if previous is not None:
            os.environ[GENERATED_SEEDS_ENV] = previous


def _capped_candidates(candidates, hubs, cap: int):
    if cap <= 0:
        return []
    hub_caps = {}
    for hub in hubs:
        try:
            host = (urlparse.urlsplit(str(hub["url"])).hostname or "").casefold().rstrip(".")
        except (TypeError, ValueError):
            host = ""
        hub_caps[str(hub["hub_id"])] = 150 if host == "github.com" else cap
    positions: Dict[str, Dict[str, int]] = {str(hub["hub_id"]): {} for hub in hubs}
    for candidate in candidates:
        for hub_id in candidate.memberships:
            positions.setdefault(str(hub_id), {})[candidate.url] = len(positions[str(hub_id)])
    allowed = set()
    for candidate in candidates:
        if any(positions.get(str(hub_id), {}).get(candidate.url, cap) <
               hub_caps.get(str(hub_id), cap) for hub_id in candidate.memberships):
            allowed.add(candidate.url)
    return [candidate for candidate in candidates if candidate.url in allowed]


def _candidate_dicts(candidates, hubs) -> List[Dict]:
    converted = []
    for candidate in candidates:
        memberships = dict(candidate.memberships)
        corroborating = research_harvest.build_corroborating_hubs(
            research_harvest.Candidate(candidate.url, memberships), hubs
        )
        if not corroborating:
            continue
        first = corroborating[0]
        converted.append({
            "programme_name": first.get("anchor_text", ""),
            "official_url": candidate.url,
            "official_evidence": {
                "source_hub": first.get("hub_url", ""),
                "anchor_text": first.get("anchor_text", ""),
                "corroborating_hubs": corroborating,
                "source_count": len(corroborating),
            },
        })
    return converted


def _run_timestamp(value: Optional[object] = None) -> str:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    if value is not None:
        return str(value)
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _seed_key(seed: Dict) -> Optional[str]:
    value = seed.get("official_url") or seed.get("url")
    normalized = _normalise_url(value)
    return normalized or (_collapsed(value) or None)


def _parse_timestamp(value: object) -> Optional[datetime]:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def merge_generated_seeds(
    category: str,
    produced: Iterable[Dict],
    destination: Path,
    *,
    raw_links: int = 0,
    admitted: Optional[int] = None,
    successful_fetches: int = 1,
    now: Optional[object] = None,
) -> Tuple[List[Dict], Dict[str, int]]:
    """Merge this run's seeds into the category's durable generated registry."""
    run_at = _run_timestamp(now)
    destination = Path(destination)
    existing: List[Dict] = []
    if destination.exists():
        try:
            with destination.open("r", encoding="utf-8") as handle:
                loaded = json.load(handle)
            if not isinstance(loaded, list) or not all(isinstance(item, dict) for item in loaded):
                raise ValueError("generated seeds must be a list of objects")
            existing = loaded
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            backup = destination.with_name(destination.stem + ".bak" + destination.suffix)
            shutil.copyfile(destination, backup)
            existing = []

    existing_by_url: Dict[str, Dict] = {}
    for entry in existing:
        key = _seed_key(entry)
        if key is not None:
            existing_by_url[key] = dict(entry)
    produced_by_url: Dict[str, Dict] = {}
    for entry in produced:
        if not isinstance(entry, dict):
            continue
        key = _seed_key(entry)
        if key is not None:
            produced_by_url[key] = dict(entry)

    merged: Dict[str, Dict] = {}
    new_count = 0
    refreshed_count = 0
    for key, entry in produced_by_url.items():
        old = existing_by_url.get(key)
        if old is None:
            current = dict(entry)
            current["first_seen"] = run_at
            current["last_seen"] = run_at
            new_count += 1
        else:
            current = dict(entry)
            current["first_seen"] = old.get("first_seen") or old.get("added_at") or run_at
            current["last_seen"] = run_at
            for field in ("added_at", "generated_at"):
                if field in old:
                    current[field] = old[field]
            refreshed_count += 1
        merged[key] = current

    cutoff = datetime.fromisoformat(run_at.replace("Z", "+00:00")) - timedelta(days=56)
    kept_count = 0
    expired_count = 0
    for key, old in existing_by_url.items():
        if key in produced_by_url:
            continue
        current = dict(old)
        if not current.get("last_seen"):
            current["last_seen"] = current.get("generated_at") or current.get("added_at") or run_at
        last_seen = _parse_timestamp(current.get("last_seen"))
        if successful_fetches > 0 and last_seen is not None and last_seen < cutoff:
            expired_count += 1
            continue
        merged[key] = current
        kept_count += 1

    ordered = [merged[key] for key in sorted(merged)]
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8") as handle:
        json.dump(ordered, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    counters = {
        "raw_links": int(raw_links),
        "admitted": int(admitted if admitted is not None else len(produced_by_url)),
        "new": new_count,
        "refreshed": refreshed_count,
        "kept": kept_count,
        "expired": expired_count,
        "total": len(ordered),
    }
    print(
        "hub_seeds {}: raw_links={} admitted={} new={} refreshed={} kept={} expired={} total={}".format(
            category, counters["raw_links"], counters["admitted"], counters["new"],
            counters["refreshed"], counters["kept"], counters["expired"], counters["total"],
        )
    )
    return ordered, counters


def generate(
    category: str,
    hubs_path: Path,
    existing_seeds: Iterable[Dict],
    fetcher=None,
    out_path: Optional[Path] = None,
    per_hub_cap: int = 25,
) -> List[Dict]:
    """Discover category hub links and optionally persist generated seeds."""
    global LAST_GENERATE_STATS
    hubs_path = Path(hubs_path)
    try:
        hubs = _load_category_hubs(category, hubs_path)
    except (OSError, ValueError, TypeError) as exc:
        print("hub seed generation: skipping {}: {}".format(category, exc), file=sys.stderr)
        LAST_GENERATE_STATS = {"category": category, "hubs_loaded": 0, "candidates_found": 0, "seeds_generated": 0, "error": str(exc)}
        return []
    client = fetcher or research_harvest.Fetcher()
    terms, authoritative = _policy(category)
    discovered, states, reasons, counts, failures, blocks = research_harvest.discover_candidates(
        hubs, client, candidate_terms=terms, authoritative_same_origin=authoritative
    )
    capped = _capped_candidates(discovered, hubs, per_hub_cap)
    max_total = 300 if category in DIRECTORY_CATEGORIES else 200
    candidate_dicts = _candidate_dicts(capped, hubs)
    seeds = candidates_to_seeds(
        category, candidate_dicts, existing_seeds,
        max_total=max_total,
    )
    seed_urls = {seed.get("official_url") for seed in seeds}
    hub_seed_counts = {str(hub["hub_id"]): 0 for hub in hubs}
    for candidate in candidate_dicts:
        if candidate.get("official_url") not in seed_urls:
            continue
        evidence = candidate.get("official_evidence") or {}
        for corroborating in evidence.get("corroborating_hubs", ()):
            hub_id = str(corroborating.get("hub_id"))
            if hub_id in hub_seed_counts:
                hub_seed_counts[hub_id] += 1
    hub_stats = [
        {
            "hub_url": str(hub["url"]),
            "links_found": int(counts.get(str(hub["hub_id"]) or "", 0) or 0),
            "seeds_produced": hub_seed_counts.get(str(hub["hub_id"]), 0),
        }
        for hub in hubs
    ]
    routed_research = list(LAST_ROUTED_RESEARCH_SEEDS)
    LAST_GENERATE_STATS = {
        "category": category,
        "hubs_loaded": len(hubs),
        "raw_candidates_found": len(discovered),
        "candidates_found": len(capped),
        "seeds_generated": len(seeds),
        "hub_states": states,
        "hub_reasons": reasons,
        "hub_candidate_counts": counts,
        "hub_failures": failures,
        "hub_blocks": blocks,
        "http_requests": getattr(client, "total_requests", None),
        "rejections_by_reason": dict(LAST_SEED_GATE_REJECTIONS),
        "routed_research": len(routed_research),
        "hub_stats": hub_stats,
    }
    destination = Path(out_path) if out_path is not None else DEFAULT_OUTPUT_DIR / (category + ".json")
    resolved = destination.expanduser().resolve()
    lake = (REPO_ROOT / "engine" / "data" / "lake").resolve()
    try:
        resolved.relative_to(lake)
    except ValueError:
        pass
    else:
        raise ValueError("out_path must not be under engine/data/lake")
    destination.parent.mkdir(parents=True, exist_ok=True)
    successful_pages = sum(1 for state in states.values() if state == "processed")
    merged, merge_stats = merge_generated_seeds(
        category,
        seeds,
        destination,
        raw_links=len(discovered),
        admitted=len(seeds),
        successful_fetches=successful_pages,
    )
    LAST_GENERATE_STATS.update(merge_stats)
    if routed_research:
        merge_generated_seeds(
            "research", routed_research, destination.with_name("research.json"),
            raw_links=len(routed_research), admitted=len(routed_research), successful_fetches=0,
        )
    if category == "fellowships":
        print("HUB_STATS")
        for item in hub_stats:
            print("hub_url={} links_found={} seeds_produced={}".format(
                item["hub_url"], item["links_found"], item["seeds_produced"],
            ))
    print("hub_seeds {}: routed_research={}".format(category, len(routed_research)))
    LAST_GENERATE_STATS["successful_pages"] = successful_pages
    return merged


def _default_hubs_path(category: str) -> Path:
    filenames = {
        "fellowships": "fellowship_directories.json",
        "scholarships": "scholarship_directories.json",
        "grants": "grant_directories.json",
        "research": "research_directories.json",
        "open_source": "open_source_directories.json",
        "startup_founder": "startup_founder_hubs.json",
        "community": "community_hubs.json",
    }
    if category in filenames:
        return Path(__file__).parent / category / filenames[category]
    return Path(__file__).with_name(category + "_hubs.json")


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Generate programme seeds from category hubs")
    parser.add_argument(
        "--category", required=True,
        choices=("research", "startup_founder", "open_source", "community", "fellowships", "scholarships", "grants"),
    )
    parser.add_argument("--out", help="JSON output path")
    args = parser.parse_args(argv)
    seeds = generate(
        args.category,
        _default_hubs_path(args.category),
        _static_seeds(args.category),
        out_path=Path(args.out) if args.out else None,
    )
    print(json.dumps({
        "category": args.category,
        "seeds_generated": len(seeds),
        "rejections_by_reason": LAST_GENERATE_STATS.get("rejections_by_reason", {}),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
