"""Generic, data-driven collection of official open-source programmes."""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import unicodedata
from collections import Counter
from copy import deepcopy
from dataclasses import dataclass
from datetime import date, datetime, timezone
from html.parser import HTMLParser
from typing import Callable, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

from core import pagetext, robots
from core.paths import OPPORTUNITIES_PATH, OPERATIONS_DIR

@dataclass(frozen=True)
class ProgrammeConfig:
    category: str
    opportunity_type: str
    source_registry: tuple
    observations_path: str
    verifications_path: str
    needs_confirmation_floor: bool = False


# Shared title/host quality data for generated programme seeds.  Keep this
# category-neutral so hub discovery and collection enforce the same policy.
PROGRAMME_NOUNS = (
    "fellowship", "fellowships", "scholar", "scholars", "scholarship",
    "scholarships", "program", "programs", "programme", "programmes",
    "award", "awards", "grant", "grants", "residency", "residencies",
    "prize", "prizes", "summer school", "summer schools", "bootcamp",
    "bootcamps", "research experience", "research experiences",
    "internship programme", "internship program", "mentorship", "mentorships",
    "initiative", "initiatives", "foundation", "academy", "academies",
)
JOB_BOARD_HOSTS = (
    "lever", "greenhouse", "workable", "linkedin", "naukri", "indeed", "hanzilla",
)
_PROGRAMME_ADVICE_TITLE = re.compile(
    r"^(?:how|preparing|finding|writing|tips|guide|applying|why|what)\b", re.I,
)
_PROGRAMME_ADVICE_PATH_SEGMENTS = frozenset(("blog", "blogs", "advice", "tips", "guide"))


def _programme_host_is_job_board(url: str) -> bool:
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").casefold().rstrip(".")
    except (TypeError, ValueError):
        return False
    if not host or host.startswith(("jobs.", "careers.")):
        return bool(host)
    labels = set(host.split("."))
    return any(board in labels for board in JOB_BOARD_HOSTS)


def _programme_has_noun(title: str, category: str = "") -> bool:
    lowered = str(title or "").casefold()
    has_scholarship_or_fellowship = bool(
        re.search(r"\b(?:fellowships?|scholarships?)\b", lowered)
    )
    for noun in PROGRAMME_NOUNS:
        if noun == "foundation" and not (
                category.casefold() in {"scholarship", "scholarships"}
                or has_scholarship_or_fellowship):
            continue
        pattern = r"(?<![a-z0-9]){}(?![a-z0-9])".format(re.escape(noun))
        if re.search(pattern, lowered):
            return True
    return False


def programme_title_ok(title: str, url: str, category: str = "") -> Tuple[bool, str]:
    """Apply one data-driven quality gate to a generated programme title."""
    title_text = str(title or "").strip()
    lowered = title_text.casefold()
    if (_PROGRAMME_ADVICE_TITLE.search(title_text)
            or "how to" in lowered
            or "tips for" in lowered
            or "guide to" in lowered):
        return False, "advice_page"
    try:
        path = urlparse(url).path or "/"
        path_segments = {segment.casefold() for segment in path.split("/") if segment}
    except (TypeError, ValueError):
        path_segments = set()
    if path_segments & _PROGRAMME_ADVICE_PATH_SEGMENTS:
        return False, "advice_page"
    if _programme_host_is_job_board(url):
        return False, "job_board_host"
    if category.casefold() in {"fellowship", "fellowships"} and re.match(r"^internship\b", title_text, re.I):
        return False, "internship_title"
    if not _programme_has_noun(title_text, category):
        return False, "missing_programme_noun"
    return True, "ok"


MONTHS = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)
MONTH_PATTERN = "|".join(MONTHS)
APPLICANT_ACTION_TOKENS = (
    "applications open", "apply now", "apply by", "application deadline",
    "applications close", "applications are accepted", "applications accepted",
    "intern applications", "contributor applications", "application period",
    "rolling basis", "applications are rolling", "processed on a rolling basis",
)
# These are deliberately data, not source adapters.  Each cue is checked
# against a nearby date before it can create an applicant window.
APPLICANT_DEADLINE_TOKENS = (
    "deadline for the contributors applications",
    "application deadline", "applicant deadline", "applicant deadlines",
    "applications are due", "applications due", "application is due",
    "nominations due", "nomination deadline", "hard deadline",
    "cutoff date", "cut-off date", "application close on",
    "applications close on", "application closes on", "applications closes on",
    "application close at", "applications close at", "application closes at",
    "applications closes at", "application closed at", "applications closed at",
    "submission deadline", "deadline to apply", "apply by",
)
_DEADLINE_EXCLUSION_TOKENS = (
    "recommend", "reference", "referee", "letter", "mentor", "mentoring",
    "sign-up", "sign up", "host organi", "organisation sign", "organization sign",
)
ORGANIZER_WINDOW_TOKENS = (
    "mentor sign up", "mentors sign up", "mentoring organization",
    "mentoring organisation", "accepting proposals", "project submission",
    "mentor applications", "organization registration", "organisation registration",
    "call for mentors", "call for projects",
)
FORMAL_PROGRAMME_TOKENS = (
    "mentorship", "mentoring", "fellowship", "internship", "cohort",
    "stipend", "program", "programme",
)
ROLLING_TOKENS = ("rolling basis", "applications are rolling", "rolling application", "processed on a rolling basis")
APPLY_LINK_TOKENS = ("apply", "application", "applications", "contributor application")
_LEXICAL_RELEVANCE_TOKENS = ("application", "apply", "admission", "enrollment", "enrolment", "registration", "deadline", "eligibility", "cohort", "fellowship", "fellows", "programme", "program")
_CLOSED_PATTERNS = (
    re.compile(r"\bapplications?\s+(?:are\s+)?now\s+closed\b", re.I),
    re.compile(r"\bapplications?\s+(?:are\s+)?closed\b", re.I),
    re.compile(r"\bno\s+longer\s+accepting\s+applications?\b", re.I),
    re.compile(r"\bclosed\s+for\s+(?:20\d{2}(?:\s*/\s*20\d{2})?|the\s+20\d{2}\s+(?:cohort|cycle))\b", re.I),
)
_GENERIC_CLOSED_PATTERN = re.compile(r"\bnow\s+closed\b", re.I)
_CLOSED_CONTEXT_PATTERN = re.compile(r"\b(?:applications?|admissions?|enro(?:l|ll)ments?|registrations?)\b", re.I)
_OPENING_PATTERNS = (
    re.compile(r"\bapplications?\s+open\s+in\s+(?:20\d{2}|(?:January|February|March|April|May|June|July|August|September|October|November|December)\b)", re.I),
    re.compile(r"\bopens?\s+(?:on\s+)?(?:20\d{2}|(?:January|February|March|April|May|June|July|August|September|October|November|December)\b)", re.I),
    re.compile(r"\bcheck\s+back\b", re.I),
    re.compile(r"\bwill\s+open\b", re.I),
)

def _month_number(name: str) -> int:
    return MONTHS.index(name.capitalize()) + 1


HOP_LINK_TOKENS = (
    "apply", "application", "deadline", "dates", "timeline", "eligib",
    "faq", "admission", "schedule", "calendar", "cycle", "next-round",
)
HOP_LINK_EXTENSIONS = (".pdf", ".doc", ".docx", ".zip", ".png", ".jpg")
HOP_LINK_LIMIT = 2
MAX_HOP_FETCHES = 150


class _HopLinkParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links: List[Tuple[str, str]] = []
        self._href: Optional[str] = None
        self._text: List[str] = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "a" and self._href is None:
            self._href = dict(attrs).get("href")
            self._text = []

    def handle_data(self, data):
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag.lower() == "a" and self._href is not None:
            self.links.append((self._href, " ".join(self._text)))
            self._href, self._text = None, []


_HOP_NAME_STOPWORDS = {
    "fellowship", "fellowships", "programme", "program", "scholarship",
    "scholarships", "scholars", "grant", "grants", "award", "awards",
    "the", "and", "for", "of", "in", "at", "to", "international",
    "foundation", "global", "summer", "student", "students", "research",
}


def _hop_page_matches_seed(seed: Dict, hop_url: str, hop_text: str) -> bool:
    """Return whether a same-origin hop is plausibly about the seed programme."""
    words = re.findall(r"[a-z0-9]{3,}", str(seed.get("programme_name", "")).casefold())
    distinctive = [word for word in words if word not in _HOP_NAME_STOPWORDS]
    if not distinctive:
        distinctive = words
    if not distinctive:
        return False

    page_text = pagetext.to_text(hop_text or "")
    matched = sum(
        bool(re.search(r"(?<![a-z0-9]){}(?![a-z0-9])".format(re.escape(token)), page_text, re.I))
        for token in set(distinctive)
    )
    if matched / len(set(distinctive)) >= 0.6:
        return True

    seed_parts, hop_parts = urlparse(seed.get("official_url", "")), urlparse(hop_url or "")
    if not seed_parts.hostname or not hop_parts.hostname:
        return False
    seed_path = (seed_parts.path or "/").rstrip("/")
    hop_path = hop_parts.path or "/"
    return (
        seed_parts.hostname.casefold() == hop_parts.hostname.casefold()
        and bool(seed_path)
        and seed_path != "/"
        and (hop_path == seed_path or hop_path.startswith(seed_path + "/"))
    )


def _hop_links(html: str, base_url: str, limit: int = HOP_LINK_LIMIT) -> List[str]:
    """Return a small, same-origin set of likely programme-information links."""
    parser = _HopLinkParser()
    parser.feed(html or "")
    base = urlparse(base_url)
    if base.scheme.lower() not in ("http", "https") or not base.hostname:
        return []

    def origin(parts):
        try:
            port = parts.port
        except ValueError:
            return None
        default_port = 443 if parts.scheme.lower() == "https" else 80
        return (parts.scheme.lower(), parts.hostname.lower(), port or default_port)

    base_origin = origin(base)
    base_without_fragment = base._replace(fragment="").geturl()
    candidates: List[Tuple[int, int, str]] = []
    seen = set()
    for index, (href, anchor) in enumerate(parser.links):
        href = (href or "").strip()
        if not href or href.startswith("#"):
            continue
        resolved = urljoin(base_url, href)
        target = urlparse(resolved)
        if target.scheme.lower() not in ("http", "https") or origin(target) != base_origin:
            continue
        target_url = target._replace(fragment="").geturl()
        if target_url == base_without_fragment or target_url in seen:
            continue
        if target.path.casefold().endswith(HOP_LINK_EXTENSIONS):
            continue
        haystack = "{} {}".format(href, anchor).casefold()
        if not any(token in haystack for token in HOP_LINK_TOKENS):
            continue
        seen.add(target_url)
        candidates.append((len(target.path or "/"), index, target_url))
    candidates.sort(key=lambda item: (item[0], item[1]))
    return [url for _, _, url in candidates[:max(0, limit)]]


def parse_dates(text: str, nearby_year: Optional[int] = None) -> List[Dict]:
    """Parse supported dates/ranges into ``start``, ``end`` and exactness."""
    results: List[Dict] = []
    range_re = re.compile(
        rf"\b(?P<sm>{MONTH_PATTERN})\s+(?P<sd>\d{{1,2}})\s*(?:[–—-]|\bto\b)\s*"
        rf"(?P<em>{MONTH_PATTERN})?\s*(?P<ed>\d{{1,2}})(?:,?\s*(?P<year>20\d{{2}}))?\b", re.I)
    consumed: List[Tuple[int, int]] = []

    def make(month: str, day: str, year: Optional[str]) -> Optional[date]:
        actual_year = int(year) if year else nearby_year
        if actual_year is None:
            return None
        try:
            return date(actual_year, _month_number(month), int(day))
        except ValueError:
            return None

    for match in range_re.finditer(text):
        start = make(match.group("sm"), match.group("sd"), match.group("year"))
        end = make(match.group("em") or match.group("sm"), match.group("ed"), match.group("year"))
        if start and end:
            results.append({"start": start, "end": end, "quote": match.group(0), "exact": True, "span": match.span()})
            consumed.append(match.span())
    iso_re = re.compile(r"\b(?P<year>20\d{2})-(?P<month>\d{2})-(?P<day>\d{2})\b")
    for match in iso_re.finditer(text):
        try:
            value = date(int(match.group("year")), int(match.group("month")), int(match.group("day")))
        except ValueError:
            continue
        results.append({"start": value, "end": value, "quote": match.group(0), "exact": True, "span": match.span()})
        consumed.append(match.span())
    day_first_re = re.compile(
        rf"\b(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)?\s*"
        rf"(?P<day>\d{{1,2}})\s+(?P<month>{MONTH_PATTERN})\s+(?P<year>20\d{{2}})\b", re.I)
    for match in day_first_re.finditer(text):
        if any(a <= match.start() < b for a, b in consumed):
            continue
        value = make(match.group("month"), match.group("day"), match.group("year"))
        if value:
            results.append({"start": value, "end": value, "quote": match.group(0), "exact": True, "span": match.span()})
            consumed.append(match.span())
    full_re = re.compile(rf"\b(?P<month>{MONTH_PATTERN})\s+(?P<day>\d{{1,2}}),?\s+(?P<year>20\d{{2}})\b", re.I)
    for match in full_re.finditer(text):
        if any(a <= match.start() < b for a, b in consumed):
            continue
        value = make(match.group("month"), match.group("day"), match.group("year"))
        if value:
            results.append({"start": value, "end": value, "quote": match.group(0), "exact": True, "span": match.span()})
            consumed.append(match.span())
    short_re = re.compile(rf"\b(?P<month>{MONTH_PATTERN})\s+(?P<day>\d{{1,2}})\b", re.I)
    for match in short_re.finditer(text):
        if any(a <= match.start() < b for a, b in consumed):
            continue
        value = make(match.group("month"), match.group("day"), None)
        if value:
            results.append({"start": value, "end": value, "quote": match.group(0), "exact": False, "span": match.span()})
    return sorted(results, key=lambda item: item["span"][0])


def _deadline_cue_matches(sentence: str) -> List[Tuple[int, int, str]]:
    lowered = sentence.casefold()
    matches = []
    for token in APPLICANT_DEADLINE_TOKENS:
        value = token.casefold()
        start = lowered.find(value)
        while start >= 0:
            matches.append((start, start + len(value), token))
            start = lowered.find(value, start + 1)
    return sorted(set(matches), key=lambda item: (item[0], -(item[1] - item[0])))


def _deadline_candidate(sentence: str, nearby_year: Optional[int] = None) -> Optional[Dict]:
    """Return the first non-excluded deadline cue with a nearby date."""
    for cue_start, cue_end, token in _deadline_cue_matches(sentence):
        tail = sentence[cue_end:min(len(sentence), cue_end + 100)]
        for parsed in parse_dates(tail, nearby_year):
            date_start = cue_end + parsed["span"][0]
            before_date = sentence[max(0, date_start - 60):date_start].casefold()
            if any(exclusion in before_date for exclusion in _DEADLINE_EXCLUSION_TOKENS):
                continue
            return {"token": token, "parsed": parsed, "cue_start": cue_start, "cue_end": cue_end}
    return None



def parse_date(text: str, nearby_year: Optional[int] = None) -> Optional[Dict]:
    """Return the first supported date or range, useful to offline callers."""
    values = parse_dates(text, nearby_year)
    return values[0] if values else None


def _year_near(text: str, position: int) -> Optional[int]:
    years = list(re.finditer(r"\b(20\d{2})\b", text[max(0, position - 320):position + 320]))
    if not years:
        return None
    before = [match for match in years if match.start() <= min(320, position)]
    return int((before or years)[-1].group(1))


def _sentences(text: str) -> Iterable[Tuple[int, int, str]]:
    for match in re.finditer(r"[^.!?\n]+(?:[.!?]|$)", text):
        yield match.start(), match.end(), match.group(0).strip()


def detect_applicant_windows(text: str) -> List[Dict]:
    """Find dated applicant windows while rejecting organizer/mentor dates."""
    candidates: List[Dict] = []
    normalized = text.replace("\xa0", " ")
    for start, end, sentence in _sentences(normalized):
        lowered = sentence.lower()
        # Deadline cues are stricter than the older action vocabulary: a date
        # must follow the cue in this sentence, and organizer language near it
        # must not turn a recommendation/mentor date into an applicant date.
        organizer_positions = [lowered.find(token) for token in ORGANIZER_WINDOW_TOKENS if token in lowered]
        candidate_sentence = sentence[:min(organizer_positions)] if organizer_positions else sentence
        deadline_cues = _deadline_cue_matches(candidate_sentence)
        if deadline_cues:
            nearby_year = _year_near(normalized, start)
            candidate = _deadline_candidate(candidate_sentence, nearby_year)
            if not candidate:
                continue
            parsed = candidate["parsed"]
            candidates.append({
                "start": parsed["start"], "end": parsed["end"],
                "quote": candidate_sentence.strip() if candidate_sentence else parsed["quote"],
                "date_quote": parsed["quote"], "exact": parsed["exact"] or nearby_year is not None,
                "token": candidate["token"], "deadline_cue": True,
            })
            continue
        positive = [token for token in APPLICANT_ACTION_TOKENS if token in lowered]
        if not positive:
            continue
        # A page may put an applicant event and an organizer event in one
        # rendered block. Only the text attached to the applicant token is a
        # candidate; an organizer-only block never reaches this point.
        dates = parse_dates(candidate_sentence, _year_near(normalized, start))
        if not dates:
            # Dates can sit on an adjacent line or heading, but remain close.
            left, right = max(0, start - 120), min(len(normalized), end + 120)
            context = normalized[left:right]
            if any(token in context.lower() for token in ORGANIZER_WINDOW_TOKENS):
                continue
            dates = parse_dates(context, _year_near(normalized, start))
        for parsed in dates:
            quote = candidate_sentence.strip() if candidate_sentence else parsed["quote"]
            candidates.append({"start": parsed["start"], "end": parsed["end"], "quote": quote, "date_quote": parsed["quote"], "exact": parsed["exact"], "token": positive[0]})
    # Preserve order and avoid a duplicated date discovered through adjacent context.
    unique = {}
    for candidate in candidates:
        unique[(candidate["start"], candidate["end"], candidate["quote"])] = candidate
    return list(unique.values())


def classify_status(text: str, windows: List[Dict], today: date, formal_programme: bool, application_url: Optional[str]) -> str:
    """Classify a page without making vague dates actionable."""
    lowered = text.lower()
    if formal_programme and application_url and any(token in lowered for token in ROLLING_TOKENS):
        return "rolling"
    for window in windows:
        opening, closing = window["start"], window["end"]
        if closing < today:
            return "closed"
        if opening <= today <= closing:
            return "open"
        if opening > today and window.get("exact"):
            return "opening_soon"
    return "non_actionable"


_NON_VISIBLE_TAGS = frozenset((
    "head", "style", "script", "noscript", "template", "svg", "canvas",
    "iframe", "object", "embed",
))
_HTML_VOID_TAGS = frozenset((
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
    "meta", "param", "source", "track", "wbr",
))


class _VisibleText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts: List[str] = []
        self.links: List[Tuple[str, str]] = []
        self.href: Optional[str] = None
        self.anchor: List[str] = []
        self._hidden_depth = 0
        self._tag_stack: List[Tuple[str, bool]] = []

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in _HTML_VOID_TAGS:
            return
        if tag == "body":
            # HTML implicitly closes an omitted head end tag here.
            self.handle_endtag("head")
        attributes = dict(attrs)
        hidden = (
            tag in _NON_VISIBLE_TAGS
            or "hidden" in attributes
            or (attributes.get("aria-hidden") or "").lower() == "true"
            or "display:none" in attributes.get("style", "").replace(" ", "").lower()
            or "visibility:hidden" in attributes.get("style", "").replace(" ", "").lower()
        )
        self._tag_stack.append((tag, hidden))
        if hidden:
            self._hidden_depth += 1
        if tag == "a" and not self._hidden_depth:
            self.href = attributes.get("href")
            self.anchor = []

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_data(self, data):
        if self._hidden_depth or not data.strip():
            return
        self.parts.append(data.strip())
        if self.href is not None:
            self.anchor.append(data.strip())

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag == "a" and self.href is not None:
            self.links.append((" ".join(self.anchor), self.href))
            self.href, self.anchor = None, []
        for index in range(len(self._tag_stack) - 1, -1, -1):
            stacked_tag, hidden = self._tag_stack[index]
            if stacked_tag == tag:
                removed = self._tag_stack[index:]
                del self._tag_stack[index:]
                self._hidden_depth = max(0, self._hidden_depth - sum(item_hidden for _, item_hidden in removed))
                break

    def handle_comment(self, data):
        return


def _text(html: str) -> Tuple[str, List[Tuple[str, str]]]:
    parser = _VisibleText()
    parser.feed(html)
    return ". ".join(parser.parts), parser.links


def _clean_quote(quote: Optional[str]) -> str:
    if not quote:
        return ""
    normalized = unicodedata.normalize("NFKC", str(quote))
    return re.sub(r"\s+", " ", normalized).strip()


def is_quality_evidence(quote: Optional[str]) -> bool:
    """Return whether text is a meaningful programme-related human quote."""
    cleaned = _clean_quote(quote)
    if not cleaned or re.fullmatch(r"https?://\S+", cleaned, re.I):
        return False
    if re.search(r"[{};]|(?:^|\s)[.#][\w-]+|[\w-]+\s+h[1-6]\s*,?$", cleaned, re.I):
        return False
    words = re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ0-9]+", cleaned)
    if len(words) < 2 or len(cleaned) < 8:
        return False
    # Short punctuated headings/titles are not programme evidence.
    if len(words) <= 2 and cleaned.endswith((".", "!", "?")):
        return False
    lowered = cleaned.casefold()
    anchors = ("application", "apply", "deadline", "eligibility", "admission", "enrollment", "enrolment", "registration", "fellowship", "fellows", "programme", "program", "funding", "stipend")
    strong_anchors = ("application", "apply", "deadline", "eligibility", "admission", "enrollment", "enrolment", "registration", "funding", "stipend")
    if len(words) <= 4 and not any(anchor in lowered for anchor in strong_anchors):
        return False
    return any(anchor in lowered for anchor in anchors) or bool(re.search(r"[.!?]$", cleaned) and len(words) >= 8)


def _lexical_status(text: str, today: date) -> Tuple[Optional[str], Optional[str]]:
    """Return a high-confidence sentence-scoped lexical status, if present."""
    for _, _, sentence in _sentences(text):
        lowered = sentence.casefold()
        relevant = any(token in lowered for token in _LEXICAL_RELEVANCE_TOKENS)
        if not relevant or not is_quality_evidence(sentence):
            continue
        closed = any(pattern.search(sentence) for pattern in _CLOSED_PATTERNS)
        if not closed:
            generic_closed = _GENERIC_CLOSED_PATTERN.search(sentence)
            if generic_closed:
                nearby = sentence[max(0, generic_closed.start() - 96):generic_closed.start()]
                nearby += sentence[generic_closed.end():generic_closed.end() + 96]
                closed = bool(_CLOSED_CONTEXT_PATTERN.search(nearby))
        if closed:
            return "closed", _clean_quote(sentence)
        if not any(pattern.search(sentence) for pattern in _OPENING_PATTERNS):
            continue
        # Explicit month/year signals are only opening-soon evidence when they
        # are demonstrably in the future.  Do not invent a day or a date.
        year_match = re.search(r"\b(20\d{2})\b", sentence)
        month_match = re.search(rf"\b({MONTH_PATTERN})\b", sentence, re.I)
        if year_match and int(year_match.group(1)) < today.year:
            continue
        if year_match and int(year_match.group(1)) == today.year and month_match:
            if _month_number(month_match.group(1)) < today.month:
                continue
        if month_match and not year_match and _month_number(month_match.group(1)) < today.month:
            continue
        return "opening_soon", _clean_quote(sentence)
    return None, None


def _quote_with(text: str, tokens: Iterable[str], minimum_words: int = 1, prefer_relevant: bool = False, deadline_cues: bool = False) -> Optional[str]:
    candidates = []
    token_values = tuple(token.casefold() for token in tokens)
    for start, _, sentence in _sentences(text):
        lowered = sentence.casefold()
        if deadline_cues:
            if not _deadline_candidate(sentence, _year_near(text, start)):
                continue
        elif not any(token in lowered for token in token_values):
            continue
        if len(re.findall(r"\b\w+\b", sentence)) < minimum_words:
            continue
        cleaned = _clean_quote(sentence)
        if is_quality_evidence(cleaned):
            relevant = any(token in lowered for token in _LEXICAL_RELEVANCE_TOKENS)
            candidates.append((not (prefer_relevant and relevant), cleaned))
    if candidates:
        candidates.sort(key=lambda item: item[0])
        return candidates[0][1]
    return None


def _evidence(quote: Optional[str], url: str) -> Dict:
    cleaned = _clean_quote(quote)
    return {"quote": cleaned, "url": url} if is_quality_evidence(cleaned) else {}


def _application_url(seed_url: str, href: str, final_url: Optional[str]) -> Optional[str]:
    base_url = final_url or seed_url
    seed = urlparse(seed_url)
    base = urlparse(base_url)
    if base.scheme not in ("http", "https") or not base.netloc:
        base = seed
        base_url = seed_url
    resolved = urljoin(base_url, href or "")
    target = urlparse(resolved)
    trusted = {(seed.scheme, seed.netloc.lower()), (base.scheme, base.netloc.lower())}
    if target.scheme not in ("http", "https") or not target.netloc or (target.scheme, target.netloc.lower()) not in trusted:
        return None
    return resolved


def _observation(seed: Dict, checked: str, state: str, reason: str, evidence: Optional[Dict] = None) -> Dict:
    value = {"source_id": seed["source_id"], "programme_id": seed["programme_id"], "official_url": seed["official_url"], "checked_at": checked, "result": "failed" if state == "failed" else ("actionable" if state == "actionable" else "non_actionable"), "state": state, "reason": reason}
    if evidence:
        value["official_evidence"] = evidence
    return value


def _base(seed: Dict, checked: str, evidence: Dict, config: ProgrammeConfig) -> Dict:
    return {"record_type": "programme", "category": config.category, "opportunity_type": config.opportunity_type, "programme_id": seed["programme_id"], "programme_name": seed["programme_name"], "organizer": seed["organizer"], "official_url": seed["official_url"], "application_url": None, "programme_status": "non_actionable", "opening_date": None, "deadline": None, "location": "not_stated", "remote": None, "international_eligibility": "needs_confirmation", "funding": "not_stated", "eligibility": "needs_confirmation", "official_evidence": evidence, "last_checked_at": checked, "source_confirmation": "official_source", "source_mechanism": "official_html"}


def parse_programme(seed: Dict, html: str, checked_at: Optional[datetime] = None, final_url: Optional[str] = None, *, config: ProgrammeConfig) -> Tuple[Optional[Dict], Dict]:
    """Run the same extraction and actionability pipeline for every seed."""
    checked_at = checked_at or datetime.now(timezone.utc)
    checked = checked_at.isoformat(timespec="seconds")
    text, links = _text(html)
    if not text.strip():
        return None, _observation(seed, checked, "failed", "empty or unparsable official response")
    apply_link = next(((label, href) for label, href in links if any(token in (label or "").lower() for token in APPLY_LINK_TOKENS)), None)
    resolved_apply = _application_url(seed["official_url"], apply_link[1], final_url) if apply_link else None
    formal = any(token in text.lower() for token in FORMAL_PROGRAMME_TOKENS)
    windows = detect_applicant_windows(text)
    status = classify_status(text, windows, checked_at.date(), formal, resolved_apply)
    lexical_status, lexical_quote = _lexical_status(text, checked_at.date()) if status == "non_actionable" else (None, None)
    if lexical_status:
        status = lexical_status
    # Explicit dated deadlines are still useful closed observations even where
    # a site uses an unusual grammatical form around "applications".
    if status == "non_actionable":
        deadline_quote = _quote_with(text, APPLICANT_DEADLINE_TOKENS, deadline_cues=True)
        if deadline_quote:
            quote_position = text.casefold().find(deadline_quote.casefold())
            deadline = parse_dates(deadline_quote, _year_near(text, quote_position))
            if deadline and deadline[0]["end"] < checked_at.date():
                status, windows = "closed", [{"start": deadline[0]["start"], "end": deadline[0]["end"], "quote": deadline_quote, "date_quote": deadline[0]["quote"], "exact": True, "token": APPLICANT_DEADLINE_TOKENS[0]}]
    if status not in ("open", "rolling", "opening_soon"):
        evidence = {}
        if windows and status == "closed":
            window = windows[0]
            evidence = {"programme_status": _evidence(window["quote"], seed["official_url"]), "deadline": _evidence(window["quote"], seed["official_url"])}
            if window["start"] != window["end"]:
                evidence["application_window"] = _evidence(window["quote"], seed["official_url"])
        elif status == "closed" and lexical_quote:
            quote_evidence = _evidence(lexical_quote, seed["official_url"])
            if quote_evidence:
                evidence = {"programme_status": quote_evidence}
        # A successful formal programme page is useful even when its current
        # application state is not machine-readable. Keep it explicitly
        # uncertain: never invent a status/date and never treat it as live.
        if status == "non_actionable" and config.needs_confirmation_floor and formal and not windows:
            evidence = {
                "official_page": _evidence(
                    _quote_with(text, FORMAL_PROGRAMME_TOKENS, prefer_relevant=True),
                    seed["official_url"],
                ),
                "programme_name": {"quote": seed["programme_name"], "url": seed["official_url"]},
                "organizer": {"quote": seed["organizer"], "url": seed["official_url"]},
                "official_url": {"quote": seed["official_url"], "url": seed["official_url"]},
            }
            record = _base(seed, checked, evidence, config)
            record["programme_status"] = None
            record["opening_date"] = None
            record["deadline"] = None
            record["needs_confirmation"] = True
            record["is_live"] = False
            return record, _observation(seed, checked, "needs_confirmation", "official formal programme page; current status or deadline is not stated", evidence)
        return None, _observation(seed, checked, status, "no actionable applicant window" if status == "non_actionable" else "official applicant deadline passed", evidence)
    # Every surfaced state must retain the registry's official URL. Rolling
    # additionally needs a resolvable same-origin application URL; for open
    # and opening_soon, the exact official date window is sufficient evidence
    # and the official URL remains the action link (application_url may be null).
    if not formal or (status == "rolling" and not resolved_apply):
        return None, _observation(seed, checked, "non_actionable", "formal programme or resolvable application evidence is absent")

    window = windows[0] if windows else None
    status_quote = (_quote_with(text, ROLLING_TOKENS) if status == "rolling" else (window["quote"] if window else lexical_quote))
    evidence = {"programme_name": {}, "organizer": {}, "official_url": {}, "programme_status": _evidence(status_quote, seed["official_url"]), "application": _evidence(apply_link[0] if apply_link else None, resolved_apply or seed["official_url"]), "application_url": _evidence(apply_link[0] if apply_link else None, resolved_apply or seed["official_url"]), "opening_date": {}, "deadline": {}, "funding": {}, "location": {}, "remote": {}, "international_eligibility": {}, "eligibility": {}}
    record = _base(seed, checked, evidence, config)
    record["application_url"] = resolved_apply
    record["programme_status"] = status
    if window:
        record["opening_date"] = window["start"].isoformat()
        record["deadline"] = window["end"].isoformat() if window["end"] != window["start"] else None
        evidence["opening_date"] = _evidence(window["quote"], seed["official_url"])
        evidence["deadline"] = _evidence(window["quote"], seed["official_url"])
        if window.get("deadline_cue"):
            record["deadline"] = window["end"].isoformat()
            record["opening_date"] = None
        if record.get("deadline") is None and record.get("opening_date"):
            deadline_evidence = evidence.get("deadline", {})
            opening_evidence = evidence.get("opening_date", {})
            deadline_quote = str(deadline_evidence.get("quote", ""))
            opening_quote = str(opening_evidence.get("quote", ""))
            opening_signal = re.search(r"\b(?:open(?:ing)?|start(?:s|ed|ing)?|begin(?:s|ning)?)\b", opening_quote, re.I)
            if "deadline" in deadline_quote.lower():
                parsed_date = record["opening_date"]
                record["deadline"] = parsed_date
                if not opening_signal:
                    record["opening_date"] = None
    funding = _quote_with(text, ("stipend", "paid", "unpaid", "funded", "$"))
    remote = _quote_with(text, ("remote",), 3)
    international = _quote_with(text, ("worldwide", "international"), 3)
    eligibility = _quote_with(text, ("eligibility", "eligible", "who can apply"), 4)
    if funding:
        record["funding"], evidence["funding"] = funding, _evidence(funding, seed["official_url"])
    if remote:
        record["location"], record["remote"], evidence["location"], evidence["remote"] = remote, True, _evidence(remote, seed["official_url"]), _evidence(remote, seed["official_url"])
    if international:
        record["international_eligibility"], evidence["international_eligibility"] = "confirmed", _evidence(international, seed["official_url"])
    if eligibility:
        record["eligibility"], evidence["eligibility"] = eligibility, _evidence(eligibility, seed["official_url"])
    return record, _observation(seed, checked, "actionable", "generic evidence-based applicant window", evidence)


def _default_fetch(url: str) -> Tuple[str, str]:
    from pipeline.resolve import _fetch_page
    status, final_url, html, error = _fetch_page(url)
    if error or status is None or status >= 400:
        raise RuntimeError(error or "http_{}".format(status))
    return html, final_url


def _atomic_json(path: str, value) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".programmes-", dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(value, handle, indent=1)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _load_json(path: str, default):
    if not os.path.exists(path):
        return default
    with open(path) as handle:
        value = json.load(handle)
    if not isinstance(value, type(default)):
        raise ValueError("invalid JSON shape in {}".format(path))
    return value


def load_verifications(path: str) -> List[Dict]:
    """Load manually authored programme verification records."""
    return _load_json(path, [])


def validate_verification(rec: Dict) -> Tuple[bool, str]:
    """Require official quote and URL evidence for every asserted status/date."""
    if not isinstance(rec, dict):
        return False, "record must be an object"
    programme_id = rec.get("programme_id")
    if not programme_id:
        return False, "programme_id is required"
    evidence = rec.get("official_evidence")
    if not isinstance(evidence, dict):
        evidence = {}
    evidence_keys = {
        "programme_status": ("status",),
        "opening_date": ("opening_date", "status"),
        "deadline": ("deadline",),
    }
    for field, keys in evidence_keys.items():
        if field not in rec or rec[field] in (None, ""):
            continue
        entry = next((evidence.get(key) for key in keys if evidence.get(key) is not None), None)
        if not isinstance(entry, dict) or not str(entry.get("quote", "")).strip() or not str(entry.get("url", "")).strip():
            return False, "{} requires non-empty quote and url evidence ({})".format(field, ", ".join(keys))
    return True, ""


def _timestamp(value) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds")
    return str(value)


def _later_timestamp(existing, candidate: str) -> str:
    existing_value = _timestamp(existing)
    if not existing_value:
        return candidate
    try:
        left = datetime.fromisoformat(existing_value.replace("Z", "+00:00"))
        right = datetime.fromisoformat(candidate.replace("Z", "+00:00"))
        return existing_value if left >= right else candidate
    except (TypeError, ValueError):
        return candidate


def apply_verifications(rows: Iterable[Dict], verifications: Iterable[Dict], now, *, config: ProgrammeConfig) -> List[Dict]:
    """Overlay valid manual facts, retaining all unrelated lake rows."""
    now_value = _timestamp(now) or datetime.now(timezone.utc).isoformat(timespec="seconds")
    result = deepcopy(list(rows))
    source_by_id = {seed["programme_id"]: seed for seed in config.source_registry}
    overlay_fields = (
        "programme_status", "opening_date", "deadline", "eligibility", "funding",
        "remote", "international_eligibility", "official_url", "application_url",
        "opportunity_type", "verification_note",
    )
    for verification in verifications:
        valid, reason = validate_verification(verification)
        if not valid:
            identifier = verification.get("programme_id") if isinstance(verification, dict) else None
            print("Skipping invalid programme verification {}: {}".format(identifier or "<missing id>", reason), file=sys.stderr)
            continue
        programme_id = verification["programme_id"]
        row = next((item for item in result if item.get("record_type") == "programme" and item.get("programme_id") == programme_id), None)
        verified_at = _timestamp(verification.get("verified_at")) or now_value
        verified_by = verification.get("verified_by") or "manual-verification"
        seed = source_by_id.get(programme_id, {})
        if row is None:
            row = {
                "record_type": "programme",
                "category": config.category,
                "opportunity_type": config.opportunity_type,
                "programme_id": programme_id,
                "programme_name": seed.get("programme_name") or verification.get("programme_name") or verification.get("name") or programme_id,
                "organizer": seed.get("organizer") or verification.get("organizer") or "not_stated",
                "official_url": seed.get("official_url") or verification.get("official_url"),
                "application_url": None,
                "programme_status": "non_actionable",
                "opening_date": None,
                "deadline": None,
                "location": "not_stated",
                "remote": None,
                "international_eligibility": "needs_confirmation",
                "funding": "not_stated",
                "eligibility": "needs_confirmation",
                "official_evidence": {},
                "source_confirmation": "official_source",
                "source_mechanism": "manual-verification",
                "first_seen": now_value,
                "last_seen": now_value,
            }
            result.append(row)
        for field in overlay_fields:
            if field in verification:
                row[field] = verification[field]
        existing_evidence = row.get("official_evidence")
        merged_evidence = dict(existing_evidence) if isinstance(existing_evidence, dict) else {}
        verification_evidence = verification.get("official_evidence")
        if isinstance(verification_evidence, dict):
            merged_evidence.update(verification_evidence)
        row["official_evidence"] = merged_evidence
        row["manually_verified"] = True
        row["verified_at"] = verified_at
        row["verified_by"] = verified_by
        row["last_checked_at"] = _later_timestamp(row.get("last_checked_at"), verified_at)
        row["source_mechanism"] = "manual-verification"
        status = row.get("programme_status")
        if status in ("live", "open", "opening_soon"):
            row["is_live"] = True
        elif status in ("closed", "ended"):
            row["is_live"] = False
            if not row.get("went_dead_at"):
                row["went_dead_at"] = now_value
    return result


def _refresh_last_checked_at(row: Dict, checked_at) -> None:
    candidate = _timestamp(checked_at)
    if not candidate:
        return
    try:
        candidate_value = datetime.fromisoformat(candidate.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return
    existing = row.get("last_checked_at")
    if "last_checked_at" not in row:
        row["last_checked_at"] = candidate
        return
    try:
        existing_value = datetime.fromisoformat(str(existing).replace("Z", "+00:00"))
        if candidate_value > existing_value:
            row["last_checked_at"] = candidate
    except (TypeError, ValueError):
        return


def merge_programmes(records: Iterable[Dict], observations: Iterable[Dict], lake_path: str = OPPORTUNITIES_PATH, observations_path: str = None, now: Optional[str] = None) -> List[Dict]:
    now = now or datetime.now(timezone.utc).isoformat(timespec="seconds")
    lake = _load_json(lake_path, [])
    programme_rows = {r.get("programme_id"): r for r in lake if r.get("record_type") == "programme" and r.get("programme_id")}
    jobs = [r for r in lake if r.get("record_type") != "programme"]
    records, observed = list(records), list(observations)
    for record in records:
        old = programme_rows.get(record["programme_id"])
        # An uncertain parse is not evidence that an existing live row ended.
        # Keep the prior row untouched; new uncertain seeds are retained but
        # explicitly non-live until a status is confirmed.
        if record.get("needs_confirmation"):
            if old:
                continue
            record = dict(record)
            record.update({"first_seen": now, "last_seen": now, "is_live": False})
            programme_rows[record["programme_id"]] = record
            continue
        if old:
            had_last_checked_at = "last_checked_at" in old
            prior_last_checked_at = old.get("last_checked_at")
            first_seen = old.get("first_seen", now)
            old.update(record)
            if had_last_checked_at and "last_checked_at" in record:
                old["last_checked_at"] = prior_last_checked_at
            old.update({"first_seen": first_seen, "last_seen": now, "is_live": True})
        else:
            record = dict(record)
            record.update({"first_seen": now, "last_seen": now, "is_live": True})
            programme_rows[record["programme_id"]] = record
    successful_states = {"actionable", "non_actionable", "closed", "needs_confirmation"}
    for observation in observed:
        if observation.get("state") in successful_states:
            row = programme_rows.get(observation.get("programme_id"))
            if row is not None:
                _refresh_last_checked_at(row, observation.get("checked_at"))
    successful_sources = {
        o["official_url"]
        for o in observed
        if o.get("result") == "non_actionable"
        and o.get("state", "non_actionable") in ("non_actionable", "closed")
    }
    current_ids = {r.get("programme_id") for r in records}
    for row in programme_rows.values():
        if row.get("official_url") in successful_sources and row.get("programme_id") not in current_ids and row.get("is_live", True):
            row["is_live"], row["went_dead_at"] = False, now
    merged = jobs + list(programme_rows.values())
    _atomic_json(lake_path, merged)
    prior = _load_json(observations_path, [])
    _atomic_json(observations_path, prior + observed)
    return merged


def _fetch_failure_bucket(reason: str) -> str:
    """Reduce existing fetch/parse failure text to a stable log bucket."""
    lowered = str(reason or "").lower()
    if "robots_disallow" in lowered or "robots_block" in lowered:
        return "robots_blocked"
    status = re.search(r"\b(?:http[_ -]?)?(\d{3})\b", lowered)
    if status:
        code = int(status.group(1))
        if code == 403:
            return "http_403"
        if code == 429:
            return "http_429"
        if 400 <= code < 500:
            return "http_4xx"
        if 500 <= code < 600:
            return "http_5xx"
    if any(token in lowered for token in ("timeout", "timed out")):
        return "timeout"
    if any(token in lowered for token in ("dns", "name or service", "nodename", "getaddrinfo")):
        return "dns"
    if any(token in lowered for token in ("tls", "ssl", "certificate")):
        return "tls"
    return "exception"


def _log_fetch_outcome(seed: Dict, final_url: Optional[str], outcome: str, error: Optional[str] = None) -> None:
    line = "programme_fetch seed={} url={} outcome={}".format(
        seed["programme_name"], final_url or seed["official_url"], outcome,
    )
    if error:
        line += " err={}".format(error)
    print(line, flush=True)


def _is_generated_seed(seed: Dict) -> bool:
    """Generated hub overlays use the stable ``hub-`` source-id prefix."""
    return str(seed.get("source_id") or "").startswith("hub-")


def collect(config: ProgrammeConfig, fetch: Callable[[str], str] = _default_fetch, checked_at: Optional[datetime] = None, lake_path: str = OPPORTUNITIES_PATH, observations_path: Optional[str] = None) -> Dict:
    records, observations = [], []
    successes = 0
    failure_counts = Counter()
    exception_counts = Counter()
    hop_budget = [0]
    for seed in config.source_registry:
        final_url = None
        outcome = "exception"
        fetch_succeeded = False
        exception_detail = None
        if _is_generated_seed(seed):
            title_ok, title_reason = programme_title_ok(
                seed.get("programme_name", ""), seed.get("official_url", ""), config.category,
            )
            if not title_ok:
                checked = (checked_at or datetime.now(timezone.utc)).isoformat(timespec="seconds")
                observation = _observation(
                    seed, checked, "failed", "generated seed rejected: {}".format(title_reason),
                )
                observations.append(observation)
                outcome = "rejected_{}".format(title_reason)
                failure_counts[outcome] += 1
                _log_fetch_outcome(seed, seed.get("official_url"), outcome)
                continue
        try:
            fetched = fetch(seed["official_url"])
            html, final_url = fetched if isinstance(fetched, tuple) else (fetched, None)
            fetch_succeeded = bool(html)
            record, observation = parse_programme(seed, html, checked_at, final_url, config=config)
            if fetch_succeeded:
                record, observation = _follow_hops(
                    seed, html, final_url, record, observation, fetch, checked_at, config, hop_budget,
                )
            if observation.get("state") == "failed":
                outcome = "empty"
            else:
                outcome = "ok state={}".format(observation.get("state", "unknown"))
        except Exception as exc:
            checked = (checked_at or datetime.now(timezone.utc)).isoformat(timespec="seconds")
            exception_name = type(exc).__name__
            exception_message = str(exc)[:200].replace("\\r", " ").replace("\\n", " ")
            exception_detail = "{}: {}".format(exception_name, exception_message)
            observation = _observation(seed, checked, "failed", "{}: {}".format(exception_name, str(exc)[:160]))
            record = None
            outcome = _fetch_failure_bucket(observation["reason"])
            exception_counts[exception_name] += 1
        if record:
            records.append(record)
        observations.append(observation)
        if fetch_succeeded and outcome.startswith("ok"):
            successes += 1
        if not outcome.startswith("ok"):
            failure_counts[outcome.split()[0]] += 1
        _log_fetch_outcome(seed, final_url, outcome, exception_detail)
    failure_items = ["{}={}".format(kind, failure_counts[kind]) for kind in sorted(failure_counts)]
    failure_items.extend("exception[{}]={}".format(kind, exception_counts[kind]) for kind in sorted(exception_counts))
    failure_summary = ",".join(failure_items) or "none"
    print(
        "programme_fetch_summary total={} successes={} failures={}".format(
            len(config.source_registry), successes, failure_summary,
        ),
        flush=True,
    )
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    merged = merge_programmes(records, observations, lake_path, observations_path or config.observations_path, now)
    verification_now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    merged = apply_verifications(merged, load_verifications(config.verifications_path), verification_now, config=config)
    _atomic_json(lake_path, merged)
    return {"records": records, "observations": observations, "merged_count": len(merged)}


def _apply_verifications_cli(config: ProgrammeConfig) -> None:
    rows = _load_json(OPPORTUNITIES_PATH, [])
    verifications = load_verifications(config.verifications_path)
    valid_count = sum(1 for verification in verifications if validate_verification(verification)[0])
    updated = apply_verifications(rows, verifications, datetime.now(timezone.utc).isoformat(timespec="seconds"), config=config)
    _atomic_json(OPPORTUNITIES_PATH, updated)
    print(json.dumps({"verification_records": len(verifications), "valid_records": valid_count, "programme_rows": sum(1 for row in updated if row.get("record_type") == "programme")}, indent=2))


def run_module_cli(config: ProgrammeConfig, argv=None) -> None:
    args = sys.argv[1:] if argv is None else argv
    if "--apply-verifications" in args:
        _apply_verifications_cli(config)
    else:
        result = collect(config)
        print(json.dumps({"records": len(result["records"]), "observations": len(result["observations"])}, indent=2))


def _rewrite_hop_evidence(evidence: Dict, hop_url: str) -> Dict:
    rewritten = {}
    for key, value in (evidence or {}).items():
        if isinstance(value, dict):
            item = dict(value)
            if item.get("quote"):
                item["url"] = hop_url
            rewritten[key] = item
        else:
            rewritten[key] = value
    return rewritten


def _has_dated_evidence(record: Optional[Dict], observation: Dict) -> bool:
    if record and (record.get("opening_date") or record.get("deadline")):
        return True
    evidence = observation.get("official_evidence") or {}
    for key in ("opening_date", "deadline", "application_window", "programme_status"):
        quote = (evidence.get(key) or {}).get("quote")
        if quote and parse_dates(quote):
            return True
    return False


def _closed_hop_record(seed: Dict, observation: Dict, checked_at: datetime, hop_url: str, config: ProgrammeConfig) -> Optional[Dict]:
    evidence = observation.get("official_evidence") or {}
    deadline_evidence = evidence.get("deadline") or {}
    deadline_quote = deadline_evidence.get("quote")
    parsed_deadline = parse_dates(deadline_quote or "", checked_at.date())
    if not parsed_deadline:
        return None
    record = _base(seed, checked_at.isoformat(timespec="seconds"), _rewrite_hop_evidence(evidence, hop_url), config)
    record["programme_status"] = "closed"
    record["deadline"] = parsed_deadline[-1]["end"].isoformat()
    window_evidence = evidence.get("application_window") or {}
    parsed_window = parse_dates(window_evidence.get("quote", ""), checked_at.date())
    if parsed_window:
        record["opening_date"] = parsed_window[0]["start"].isoformat()
    record["needs_confirmation"] = False
    record["is_live"] = False
    return record


def _follow_hops(seed: Dict, html: str, final_url: Optional[str], record: Optional[Dict], observation: Dict,
                 fetch: Callable[[str], str], checked_at: Optional[datetime], config: ProgrammeConfig,
                 hop_budget: List[int]) -> Tuple[Optional[Dict], Dict]:
    """Try bounded information-page hops without changing failed first-page results."""
    first_page_needs_hop = (
        observation.get("state") == "non_actionable"
        or (
            record is not None
            and record.get("needs_confirmation")
            and record.get("deadline") is None
            and record.get("programme_status") is None
        )
    )
    if not html or observation.get("state") == "failed" or not first_page_needs_hop:
        return record, observation
    base_url = final_url or seed["official_url"]
    checked_value = checked_at or datetime.now(timezone.utc)
    for hop_url in _hop_links(html, base_url, HOP_LINK_LIMIT):
        if hop_budget[0] >= MAX_HOP_FETCHES:
            break
        try:
            allowed, _why = robots.allowed(hop_url)
        except Exception:
            continue
        if not allowed:
            continue
        hop_budget[0] += 1
        try:
            fetched = fetch(hop_url)
            hop_html, hop_final_url = fetched if isinstance(fetched, tuple) else (fetched, None)
            if not hop_html:
                continue
            hop_seed = dict(seed)
            hop_seed["official_url"] = hop_url
            hop_record, hop_observation = parse_programme(
                hop_seed, hop_html, checked_value, hop_final_url, config=config,
            )
        except Exception:
            continue
        if not _hop_page_matches_seed(seed, hop_url, hop_html):
            continue
        status = hop_record.get("programme_status") if hop_record else None
        dated = _has_dated_evidence(hop_record, hop_observation)
        if status in ("open", "rolling", "opening_soon"):
            promoted = deepcopy(hop_record)
            promoted.update({
                "programme_id": seed["programme_id"],
                "programme_name": seed["programme_name"],
                "organizer": seed["organizer"],
                "official_url": seed["official_url"],
                "official_evidence": _rewrite_hop_evidence(promoted.get("official_evidence", {}), hop_url),
                "needs_confirmation": not dated,
            })
            reason = "{}; second-hop evidence from {}".format(hop_observation.get("reason", "actionable"), hop_url)
            return promoted, _observation(seed, hop_observation["checked_at"], hop_observation["state"], reason, promoted["official_evidence"])
        if hop_observation.get("state") == "closed" and dated:
            promoted = _closed_hop_record(seed, hop_observation, checked_value, hop_url, config)
            if promoted:
                reason = "{}; second-hop evidence from {}".format(hop_observation.get("reason", "closed"), hop_url)
                return promoted, _observation(seed, hop_observation["checked_at"], "closed", reason, promoted["official_evidence"])
    return record, observation
