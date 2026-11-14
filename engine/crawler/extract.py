"""Facts from one fetched page: title, organiser, text, language, links, dates, emails."""

from __future__ import annotations

import json
import re
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import date, datetime
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from typing import Dict, List, Optional, Tuple

from core import opportunity_text, pagetext
from crawler import funding, urls

MAX_WORDS = 2000
SNIPPET_CHARS = 300
GENERIC_LOCALS = {"careers", "jobs", "hiring", "talent", "recruiting", "hr", "hello", "info",
                  "contact", "team"}
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_STOPWORDS = {"the", "and", "of", "to", "in", "for", "with", "is", "on", "our", "you", "we"}
_SCRIPTS = (("hi", "ऀ", "ॿ"), ("ar", "؀", "ۿ"), ("ru", "Ѐ", "ӿ"),
            ("zh", "一", "鿿"), ("ja", "぀", "ヿ"), ("ko", "가", "힯"),
            ("ta", "஀", "௿"), ("bn", "ঀ", "৿"), ("te", "ఀ", "౿"))


class _Parser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.h1 = ""
        self.meta: Dict[str, str] = {}
        self.lang = ""
        self.links: List[Tuple[str, str]] = []
        self.ld: List[str] = []
        self.times: List[str] = []
        self._in: Optional[str] = None
        self._buf: List[str] = []
        self._href: Optional[str] = None
        self._anchor: List[str] = []
        self._ld_on = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "html":
            self.lang = a.get("lang") or ""
        elif tag == "meta":
            key = a.get("property") or a.get("name") or a.get("itemprop")
            if key and a.get("content"):
                self.meta.setdefault(key.lower(), a["content"].strip())
        elif tag == "time" and a.get("datetime") and len(self.times) < 5:
            self.times.append(a["datetime"].strip())
        elif tag in ("title", "h1") and self._in is None:
            self._in, self._buf = tag, []
        elif tag == "a" and a.get("href"):
            self._href, self._anchor = a["href"], []
        elif tag == "img" and self._href is not None and a.get("alt"):
            self._anchor.append(" " + a["alt"] + " ")
        elif tag == "script" and (a.get("type") or "").lower() == "application/ld+json":
            self._ld_on = True
            self.ld.append("")

    def handle_endtag(self, tag):
        if tag == self._in:
            text = " ".join("".join(self._buf).split())
            if tag == "title" and not self.title:
                self.title = text
            elif tag == "h1" and not self.h1:
                self.h1 = text
            self._in = None
        elif tag == "a" and self._href is not None:
            self.links.append((self._href, " ".join("".join(self._anchor).split())))
            self._href = None
        elif tag == "script":
            self._ld_on = False

    def handle_data(self, data):
        if self._ld_on and self.ld:
            self.ld[-1] += data
        if self._in:
            self._buf.append(data)
        if self._href is not None:
            self._anchor.append(data)


def _ld_organiser(blobs: List[str]) -> str:
    def walk(node):
        if isinstance(node, list):
            for n in node:
                yield from walk(n)
        elif isinstance(node, dict):
            yield node
            yield from walk(node.get("@graph", []))
    for blob in blobs:
        try:
            data = json.loads(blob)
        except ValueError:
            continue
        for node in walk(data):
            kinds = node.get("@type")
            kinds = kinds if isinstance(kinds, list) else [kinds]
            if "Organization" in kinds and isinstance(node.get("name"), str):
                return node["name"].strip()
    return ""


def _title_suffix(title: str) -> str:
    for sep in (" | ", " - "):
        if sep in title:
            return title.rsplit(sep, 1)[1].strip()
    return ""


def detect_language(declared: str, og_locale: str, text: str) -> str:
    for value in (declared, og_locale):
        if value and value.strip():
            return re.split(r"[-_]", value.strip().lower())[0]
    letters = [c for c in text[:2000] if c.isalpha()]
    if not letters:
        return "und"
    for code, lo, hi in _SCRIPTS:
        if sum(lo <= c <= hi for c in letters) > len(letters) * 0.3:
            return code
    words = re.findall(r"[a-z]+", text[:2000].lower())
    if words and sum(w in _STOPWORDS for w in words) > len(words) * 0.08:
        return "en"
    return "und"


def _snippet(text: str) -> str:
    out = ""
    for line in text.split("\n"):
        if len(line.split()) >= 6:
            out = (out + " " + line).strip()
            if len(out) >= 80:
                break
    return out[:SNIPPET_CHARS]


def _emails(mailtos: List[str], text: str, page_url: str) -> List[str]:
    domain = urls.registered_domain(page_url)
    found = set()
    for addr in mailtos + _EMAIL.findall(text):
        addr = addr.strip().lower()
        local, _, dom = addr.partition("@")
        if local in GENERIC_LOCALS and urls.registered_domain(dom) == domain:
            found.add(addr)
    return sorted(found)


def _dates(text: str, today: date) -> Dict:
    windows = opportunity_text.detect_applicant_windows(text, today)
    if not windows:
        return {"deadline": None, "status": None, "quote": None}
    status = opportunity_text.classify_status(text, windows, today, False, None)
    first = windows[0]
    return {"deadline": first["end"].isoformat(), "status": status, "quote": first["quote"]}


def extract(html: str, url: str, today: Optional[date] = None) -> Dict:
    today = today or date.today()
    parser = _Parser()
    try:
        parser.feed(html or "")
        parser.close()
    except (TypeError, ValueError, AssertionError):
        pass
    meta = parser.meta
    title = meta.get("og:title") or parser.title or parser.h1
    organiser = (meta.get("og:site_name") or _ld_organiser(parser.ld)
                 or _title_suffix(parser.title))
    flat = pagetext.to_text(html)
    words = flat.split()
    text = " ".join(words[:MAX_WORDS])
    links, mailtos = [], []
    for href, anchor in parser.links:
        href = href.strip()
        if href.lower().startswith("mailto:"):
            mailtos.append(href[7:].split("?")[0])
        elif href and not href.lower().startswith(("tel:", "javascript:", "#")):
            link = urls.normalise(urllib.parse.urljoin(url, href))
            if link.startswith(("http://", "https://")):
                links.append({"url": link, "text": anchor})
    structured = {}
    try:
        from categories.programme_enrich import parse_structured
        structured = parse_structured(html, url)
    except Exception:  # noqa: BLE001
        pass
    dates = _dates(flat, today)
    if not dates["deadline"] and structured.get("deadline"):
        dates["deadline"] = str(structured["deadline"])
    return {"title": title, "h1": parser.h1, "title_name": parser.title.split(" | ")[0].split(" - ")[0].strip(),
            "organiser": organiser, "text": text,
            "snippet": _snippet(flat), "words": len(words),
            "language": detect_language(parser.lang, meta.get("og:locale", ""), flat),
            "links": links, "emails": _emails(mailtos, flat, url),
            "published": funding.published_date(meta, parser.ld, parser.times, today), **dates}


def _feed_date(value: str) -> Optional[str]:
    value = (value or "").strip()
    if not value:
        return None
    try:
        return parsedate_to_datetime(value).date().isoformat()
    except (TypeError, ValueError):
        pass
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return None


def parse_feed(xml: str) -> List[Dict]:
    """RSS or Atom -> [{title, link, date}]."""
    try:
        root = ET.fromstring((xml or "").lstrip().encode("utf-8"))
    except ET.ParseError:
        return []
    items = []
    for node in root.iter():
        tag = node.tag.rsplit("}", 1)[-1]
        if tag not in ("item", "entry"):
            continue
        fields: Dict[str, str] = {}
        for child in node:
            name = child.tag.rsplit("}", 1)[-1]
            if name == "link":
                fields.setdefault("link", child.get("href") or (child.text or "").strip())
            elif name in ("title", "pubDate", "published", "updated"):
                fields.setdefault(name, (child.text or "").strip())
        link = fields.get("link")
        if link:
            items.append({"title": fields.get("title", ""), "link": link,
                          "date": _feed_date(fields.get("pubDate") or fields.get("published")
                                             or fields.get("updated", ""))})
    return items
