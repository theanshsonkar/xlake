"""Durable name/URL filters for generated programme seeds (stdlib only).

Shared by categories/hub_seeds.py and categories/programme_core.py so neither imports the other.
Moved verbatim out of hub_seeds; hub_seeds re-exports every name."""
from __future__ import annotations

import re
from typing import List, Optional, Sequence
from urllib import parse as urlparse

_GRANT_GENERIC_NAME_PREFIXES = re.compile(
    r"^\s*(?:funding schemes|list of|opportunities for)\b", re.IGNORECASE,
)

_GRANT_LIST_NAME_TERMS = re.compile(r"\b(?:database\s+of|funding\s+schemes)\b", re.IGNORECASE)

_GRANT_NON_TECH_NEGATIVE_KEYWORDS = (
    "cancer", "autism", "biomedical", "clinical", "disease", "patient", "podcast", "podcasts",
)

_GRANT_NEWS_TITLE_KEYWORDS = ("announces", "recipients")

_ADMISSION_CURRENT_YEAR = 2026

_ADMISSION_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")

_ADMISSION_STALE_MARKER = re.compile(r"\b(?:previous|outdated|archived|archive)\b", re.IGNORECASE)

def _admission_contains_keywords(value: str, keywords: Sequence[str]) -> bool:
    lowered = (value or "").casefold()
    for keyword in keywords:
        escaped = re.escape(keyword.casefold()).replace(r"\ ", r"\s+")
        if re.search(r"(?<![a-z0-9]){}(?![a-z0-9])".format(escaped), lowered):
            return True
    return False

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

def _is_github_list_url(url: object) -> bool:
    """Reject GitHub repositories/README pages and obvious awesome lists."""
    try:
        parsed = urlparse.urlsplit(str(url or ""))
        host = (parsed.hostname or "").casefold().rstrip(".")
        path = (parsed.path or "").casefold()
    except (TypeError, ValueError):
        return False
    if host == "github.com" or host.endswith(".github.com"):
        return len([part for part in path.split("/") if part]) >= 2
    return bool(re.search(r"(?:^|[-_/])awesome[-_]list(?:[-_/]|$)", path))

_NEWS_STYLE_NAME_PREFIXES = ("first recipients", "announcing", "introducing")

def _is_news_style_name(name: object) -> bool:
    lowered = _collapsed(name).casefold()
    return lowered.startswith(_NEWS_STYLE_NAME_PREFIXES) or " have been " in lowered or " announced" in lowered

def _merge_seed_filter_reason(category: str, name: object, url: object) -> Optional[str]:
    """Apply only durable name/URL negatives when re-filtering stored seeds.

    Page admission may establish technical relevance from body text, so the
    positive category-name gate must never be reapplied during a merge.
    """
    if _is_github_list_url(url):
        return "list_page"
    cleaned = _clean_seed_name(name)
    lowered = cleaned.casefold()
    if lowered.startswith("awesome "):
        return "list_page"
    if _is_news_style_name(cleaned):
        return "news_page"
    if category == "grants":
        if (_GRANT_GENERIC_NAME_PREFIXES.match(cleaned)
                or _GRANT_LIST_NAME_TERMS.search(cleaned)):
            return "list_page"
        if _admission_contains_keywords(cleaned, _GRANT_NEWS_TITLE_KEYWORDS):
            return "news_page"
        if _admission_contains_keywords(cleaned, _GRANT_NON_TECH_NEGATIVE_KEYWORDS):
            return "non_tech_signal"
    if _admission_is_stale_year(cleaned, "", str(url or "")):
        return "stale_year"
    return None

def _collapsed(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()

_TABLE_STATUS = re.compile(r"\u2705|\U0001f525|\u23f3|\[(?:OPEN|CLOSING SOON|OPENS SOON|CLOSED)\]", re.I)

_TABLE_DEADLINE_TAIL = re.compile(r"\s+[\u2014\u2013-]+\s+deadline\b.*$", re.I)

def _table_row_name(cells: List[str]) -> str:
    """Programme name from a markdown-table row scraped as one string.

    The hub tables are ``[date] | status | organiser/state | NAME [- Deadline: x]
    | amount | eligibility``, so the name is the cell two after the status cell
    (the one holding the OPEN / CLOSING SOON marker). Returns "" when the row
    does not follow that shape (the caller then keeps the raw text, which the
    title gates reject).
    """
    for i, cell in enumerate(cells):
        if _TABLE_STATUS.search(cell) and i + 3 < len(cells):  # name must not be the last (possibly clipped) cell
            name = _TABLE_DEADLINE_TAIL.sub("", cells[i + 2].replace("**", "")).strip(" -\u2013\u2014:")
            if 4 <= len(name) <= 120 and not re.match(r"^(?:\$|up to\b|\d)", name, re.I):
                return name
            return ""
    return ""

def _clean_seed_name(value: object) -> str:
    """Turn a discovered markdown label into an official programme name."""
    name = _collapsed(value)
    if "|" in name:
        cells = [cell.strip() for cell in name.split("|") if cell.strip()]
        linked = [
            cell for cell in cells
            if re.search(r"(?:\[[^\]]*\]\([^)]*\)|https?://)", cell, re.IGNORECASE)
        ]
        if linked:
            name = linked[0]
        else:
            name = _table_row_name(cells) or name
    name = re.sub(r"!\[[^\]]*\]\([^)]*(?:\)|$)", "", name)
    name = re.sub(r"\[([^\]]+)\]\([^)]*(?:\)|$)", r"\1", name)
    name = re.sub(r"\]\([^)]*(?:\)|$)", "", name)
    name = re.sub(r"https?://\S+", "", name, flags=re.IGNORECASE)
    name = re.sub(r"`", "", name)
    name = name.replace("**", "").replace("__", "")
    emphasis = re.search(r"(?<!\w)([_*])([^_*]+)\1", name)
    if emphasis:
        name = name[:emphasis.start()]
    name = re.sub(r"[*_]", "", name)
    name = re.sub(r"^\s*\d+[.)]?\s+", "", name)
    name = re.sub(r"^\s*#{1,6}\s+", "", name)
    name = re.sub(r"\s+", " ", name).strip(" -–—:;,.)|[")
    name = re.sub(r"\s+\b(?:URL|Link|Website)\s*$", "", name, flags=re.IGNORECASE)
    if name.count("(") > name.count(")"):
        name = name[:name.rfind("(")].rstrip(" -–—:;,.)|[")
    return name
