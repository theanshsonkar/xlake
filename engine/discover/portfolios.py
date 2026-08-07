"""Portfolio discovery sources."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlsplit

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fetch
import robots


MULTI_PART_SUFFIXES = {
    "co.in", "co.uk", "com.au", "co.jp", "com.br", "co.nz", "com.sg",
    "com.mx", "co.za", "org.uk", "ac.in", "gov.in", "com.tr", "com.cn",
    "co.il",
}
NON_COMPANY_DOMAINS = frozenset({
    "twitter.com", "x.com", "linkedin.com", "facebook.com", "instagram.com",
    "youtube.com", "youtu.be", "github.com", "gitlab.com", "medium.com",
    "substack.com", "crunchbase.com", "angel.co", "wellfound.com", "notion.so",
    "notion.site", "google.com", "docs.google.com", "forms.gle", "apps.apple.com",
    "play.google.com", "t.me", "discord.gg", "discord.com", "slack.com",
    "calendly.com", "eventbrite.com", "vimeo.com", "spotify.com", "reddit.com",
    "producthunt.com", "wikipedia.org", "techcrunch.com", "forbes.com",
    "bloomberg.com", "glassdoor.com", "indeed.com", "naukri.com",
})


def registrable_domain(host: str) -> str:
    host = (host or "").lower().strip()
    if host.startswith("www."):
        host = host[4:]
    if ":" in host:
        host = host.split(":", 1)[0]
    labels = host.split(".")
    if not host or any(not label or not label.replace("-", "").isalnum() for label in labels):
        return ""
    if len(labels) < 2:
        return ""
    suffix = ".".join(labels[-2:])
    count = 3 if suffix in MULTI_PART_SUFFIXES else 2
    if len(labels) < count:
        return ""
    return ".".join(labels[-count:])


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: List[Tuple[str, str, Dict[str, str]]] = []
        self._href: Optional[str] = None
        self._text: List[str] = []
        self._attrs: Dict[str, str] = {}
        self._img_alt: str = ""

    def _flush_anchor(self) -> None:
        if self._href is not None:
            metadata = dict(self._attrs)
            if self._img_alt:
                metadata["img_alt"] = self._img_alt
            self.links.append((self._href, " ".join("".join(self._text).split()), metadata))
            self._href = None
            self._text = []
            self._attrs = {}
            self._img_alt = ""

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        values = {key.lower(): value.strip() for key, value in attrs if value and value.strip()}
        if tag.lower() == "a":
            href = values.get("href")
            if href is not None:
                self._flush_anchor()
                self._href = href
                self._text = []
                self._attrs = values
                self._img_alt = ""
        elif tag.lower() == "img" and self._href is not None and not self._img_alt:
            self._img_alt = values.get("alt", "")

    def handle_startendtag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        values = {key.lower(): value.strip() for key, value in attrs if value and value.strip()}
        if tag.lower() == "img" and self._href is not None and not self._img_alt:
            self._img_alt = values.get("alt", "")
        elif tag.lower() == "a":
            href = values.get("href")
            if href is not None:
                self._flush_anchor()
                self.links.append((href, "", values))

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a" and self._href is not None:
            self._flush_anchor()


def _domain_label(domain: str) -> str:
    label = domain.split(".", 1)[0].replace("-", " ").replace("_", " ")
    return " ".join(word.capitalize() for word in label.split())


def _name(text: str, metadata: Dict[str, str], domain: str) -> Tuple[str, str]:
    for value, source in ((text, "anchor_text"), (metadata.get("img_alt", ""), "img_alt"),
                          (metadata.get("title", ""), "title"),
                          (metadata.get("aria-label", ""), "aria_label")):
        value = " ".join(value.split())
        if value:
            return value, source
    return _domain_label(domain), "domain_label"


def extract_links(html: str, base_url: str) -> List[Tuple[str, str]]:
    parser = _LinkParser()
    parser.feed(html)
    result = []
    for href, text, _metadata in parser.links:
        lowered = href.lower()
        if not href or href == "#" or lowered.startswith(("mailto:", "tel:", "javascript:")):
            continue
        absolute = urljoin(base_url, href)
        if urlsplit(absolute).scheme.lower() in ("http", "https"):
            result.append((absolute, text))
    return result


def harvest_links(html: str, base_url: str, source_domain: str) -> List[Dict]:
    found: List[Dict] = []
    by_domain: Dict[str, Dict] = {}
    source_domain = registrable_domain(source_domain)
    parser = _LinkParser()
    parser.feed(html)
    for website, text, metadata in parser.links:
        if not website or website == "#" or website.lower().startswith(("mailto:", "tel:", "javascript:")):
            continue
        website = urljoin(base_url, website)
        if urlsplit(website).scheme.lower() not in ("http", "https"):
            continue
        domain = registrable_domain(urlsplit(website).hostname or "")
        if not domain or domain in NON_COMPANY_DOMAINS or domain == source_domain:
            continue
        company, company_name_source = _name(text, metadata, domain)
        row = by_domain.get(domain)
        if row is None:
            row = {"company": company, "company_name_source": company_name_source,
                   "website": website, "domain": domain}
            by_domain[domain] = row
            found.append(row)
        elif row["company_name_source"] == "domain_label" and company_name_source != "domain_label":
            row["company"] = company
            row["company_name_source"] = company_name_source
    return found


def _get_path(value: object, path: str) -> object:
    if not path:
        return value
    for part in path.split("."):
        if isinstance(value, dict):
            value = value.get(part, "")
        else:
            return ""
    return value


def extract_json(payload, items_path: str, name_key: str, url_key: str) -> List[Dict]:
    items = _get_path(payload, items_path)
    if not isinstance(items, list):
        return []
    found: List[Dict] = []
    by_domain: Dict[str, Dict] = {}
    for item in items:
        name = _get_path(item, name_key)
        website = _get_path(item, url_key)
        name = name if isinstance(name, str) else ""
        website = website if isinstance(website, str) else ""
        domain = registrable_domain(urlsplit(website).hostname or "")
        if not domain or domain in NON_COMPANY_DOMAINS:
            continue
        row = by_domain.get(domain)
        if row is None:
            row = {"company": name, "website": website, "domain": domain}
            by_domain[domain] = row
            found.append(row)
        elif not row["company"] and name:
            row["company"] = name
    return found


@dataclass
class PortfolioResult:
    slug: str
    url: str
    status: Optional[int]
    robots_allowed: bool
    read_outcome: str
    companies: List[Dict]
    error: Optional[str]
    yield_below_expected: bool = False


def fetch_portfolio(url: str):
    """Thin public wrapper around the existing robots/cache-backed fetch path."""
    # Cache freshness is controlled by the LAKE_MAX_AGE environment variable, not by an argument.
    return fetch._request(url, want_json=False)


def read_portfolio(source: Dict, *, fetcher=None) -> PortfolioResult:
    slug = source["slug"]
    url = source["url"]
    allowed, reason = robots.allowed(url)
    if not allowed:
        return PortfolioResult(slug, url, None, False, "blocked", [], reason)
    try:
        status, payload, error = fetch_portfolio(url) if fetcher is None else fetcher(url)
    except Exception as exc:  # noqa: BLE001
        return PortfolioResult(slug, url, None, True, "errored", [], str(exc))
    if status is None:
        return PortfolioResult(slug, url, status, True, "errored", [], error)
    if status in (401, 403, 429):
        return PortfolioResult(slug, url, status, True, "blocked", [], error)
    if not 200 <= status < 300:
        return PortfolioResult(slug, url, status, True, "errored", [], error or "unexpected status {}".format(status))
    if error is not None:
        return PortfolioResult(slug, url, status, True, "errored", [], error)
    kind = source["kind"]
    try:
        if kind == "links":
            companies = harvest_links(str(payload), url, urlsplit(url).hostname or "")
        elif kind == "json":
            data = json.loads(payload) if isinstance(payload, str) else payload
            items = _get_path(data, source.get("items_path", ""))
            if not isinstance(items, list):
                return PortfolioResult(slug, url, status, True, "partial", [], "items_path did not resolve to a list")
            companies = extract_json(data, source.get("items_path", ""), source.get("name_key", ""), source.get("url_key", ""))
        else:
            raise ValueError("unknown portfolio kind: {}".format(kind))
    except Exception as exc:  # noqa: BLE001
        return PortfolioResult(slug, url, status, True, "errored", [], str(exc))
    below = len(companies) < int(source["min_expected"])
    return PortfolioResult(slug, url, status, True, "complete", companies, None, below)


def merge_companies(existing: List[Dict], found: List[Dict], now: str) -> List[Dict]:
    merged = [dict(row) for row in existing]
    indexes = {(row.get("portfolio_slug"), row.get("domain")): i for i, row in enumerate(merged)}
    for row in found:
        key = (row["portfolio_slug"], row["domain"])
        if key in indexes:
            current = merged[indexes[key]]
            current.update({k: row[k] for k in ("company", "company_name_source", "website", "domain", "portfolio_slug") if k in row})
            if "portfolio_url" in row:
                current["portfolio_url"] = row["portfolio_url"]
            current["last_seen"] = now
        else:
            item = dict(row)
            item["first_seen"] = now
            item["last_seen"] = now
            indexes[key] = len(merged)
            merged.append(item)
    return merged


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def run(catalog_path: str, out_path: str, slugs: Optional[List[str]] = None, audit: bool = False) -> Dict:
    with open(catalog_path, encoding="utf-8") as handle:
        catalog = json.load(handle)
    selected = [source for source in catalog if slugs is None or source["slug"] in slugs]
    results = [read_portfolio(source) for source in selected]
    summary = [{"slug": r.slug, "robots_allowed": r.robots_allowed, "status": r.status,
                "companies_found": len(r.companies), "read_outcome": r.read_outcome,
                "yield_below_expected": r.yield_below_expected} for r in results]
    if audit:
        return {"sources": summary}
    try:
        with open(out_path, encoding="utf-8") as handle:
            existing = json.load(handle)
    except FileNotFoundError:
        existing = []
    found = []
    for source, result in zip(selected, results):
        for company in result.companies:
            found.append({**company, "portfolio_slug": source["slug"], "portfolio_url": source["url"]})
    merged = merge_companies(existing, found, _now())
    with open(out_path, "w", encoding="utf-8") as handle:
        json.dump(merged, handle, indent=2)
        handle.write("\n")
    return {"sources": summary}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audit", action="store_true")
    parser.add_argument("--only", default="")
    parser.add_argument("--catalog", default="data/portfolios.json")
    parser.add_argument("--out", default="data/portfolio_companies.json")
    args = parser.parse_args()
    slugs = [slug for slug in args.only.split(",") if slug] or None
    summary = run(args.catalog, args.out, slugs, args.audit)
    if args.audit:
        for row in summary["sources"]:
            print("{slug:<16} {robots_allowed:<8} {status!s:<6} {companies_found:<8} {read_outcome:<10} {yield_below_expected}".format(**row))


if __name__ == "__main__":
    main()
