"""Deterministic enrichment for programme pages (no network, no LLM).

Pure functions over the HTML/text of an official programme page: structured
data (JSON-LD / microdata / OpenGraph), description, funding, eligibility
flags, region, logo, organizer domain and application link.  Used by
``programme_core.parse_programme``; publish reuses ``clean_location``.
"""
from __future__ import annotations

import json
import re
import unicodedata
from datetime import date, datetime
from html.parser import HTMLParser
from typing import Dict, Iterable, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

PLACEHOLDERS = {"", "not_stated", "needs_confirmation", "unknown", "n/a", "none", "null"}


def is_placeholder(value) -> bool:
    return value is None or str(value).strip().casefold() in PLACEHOLDERS


def clean_text(value) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", str(value))).strip()


def truncate(value: str, limit: int) -> str:
    value = clean_text(value)
    if len(value) <= limit:
        return value
    cut = value[:limit - 1]
    space = cut.rfind(" ")
    if space > limit * 0.6:
        cut = cut[:space]
    return cut.rstrip(" ,;:-") + "…"


# --------------------------------------------------------------------------- #
# Structured data
# --------------------------------------------------------------------------- #
_LD_TYPES = {
    "event", "educationaloccupationalprogram", "course", "grant", "monetarygrant",
    "organization", "webpage", "collegeoruniversity", "educationalorganization",
    "ngo", "corporation", "researchproject", "scholarlyarticle-not", "program",
    "courseinstance", "project", "fundingscheme", "webSite".casefold(),
}
_ITEMPROPS = {
    "applicationdeadline": "deadline", "validthrough": "deadline",
    "startdate": "start_date", "enddate": "end_date", "description": "description",
    "logo": "logo", "image": "image", "name": "name",
}


class _StructuredParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.ld: List[str] = []
        self.meta: Dict[str, str] = {}
        self.icons: List[Tuple[str, str, str]] = []  # (rel, sizes, href)
        self.itemprops: Dict[str, str] = {}
        self.title = ""
        self._script = False
        self._buf: List[str] = []
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "script":
            self._script = "ld+json" in a.get("type", "").lower()
            self._buf = []
        elif tag == "meta":
            key = (a.get("property") or a.get("name") or a.get("itemprop") or "").lower()
            content = a.get("content", "")
            if key and content and key not in self.meta:
                self.meta[key] = content
        elif tag == "link":
            rel = a.get("rel", "").lower()
            if "icon" in rel and a.get("href"):
                self.icons.append((rel, a.get("sizes", "").lower(), a["href"]))
        elif tag == "title":
            self._in_title = True
        prop = a.get("itemprop", "").lower()
        if prop in _ITEMPROPS and _ITEMPROPS[prop] not in self.itemprops:
            value = (a.get("content") or a.get("datetime") or
                     (a.get("src") if tag in ("img", "meta") else "") or
                     (a.get("href") if tag == "link" else ""))
            if value:
                self.itemprops[_ITEMPROPS[prop]] = value

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag == "script" and self._script:
            self.ld.append("".join(self._buf))
            self._script = False
        elif tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._script:
            self._buf.append(data)
        elif self._in_title and not self.title:
            self.title = clean_text(data)


def _ld_nodes(blocks: Iterable[str]) -> List[dict]:
    nodes: List[dict] = []

    def walk(item, depth=0):
        if depth > 6:
            return
        if isinstance(item, list):
            for sub in item:
                walk(sub, depth + 1)
        elif isinstance(item, dict):
            nodes.append(item)
            for key in ("@graph", "mainEntity", "mainEntityOfPage", "about", "itemListElement"):
                if key in item:
                    walk(item[key], depth + 1)

    for block in blocks:
        try:
            walk(json.loads(block.strip()))
        except (ValueError, TypeError):
            continue
    return nodes


def _types(node: dict) -> set:
    raw = node.get("@type")
    values = raw if isinstance(raw, list) else [raw]
    return {str(v).rsplit("/", 1)[-1].casefold() for v in values if v}


def _ld_str(value) -> str:
    """Return the most useful string for an LD value (string, dict, list)."""
    if isinstance(value, str):
        return clean_text(value)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, list):
        for item in value:
            text = _ld_str(item)
            if text:
                return text
        return ""
    if isinstance(value, dict):
        for key in ("url", "contentUrl", "name", "@id", "value"):
            text = _ld_str(value.get(key))
            if text:
                return text
    return ""


def _ld_date(value) -> Optional[str]:
    text = _ld_str(value)
    match = re.match(r"(\d{4})-(\d{2})-(\d{2})", text)
    if not match:
        return None
    try:
        date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None
    return match.group(0)


def _money(amount, currency) -> Optional[Tuple[str, Optional[int]]]:
    if isinstance(amount, dict):
        currency = amount.get("currency") or amount.get("priceCurrency") or currency
        amount = amount.get("value", amount.get("maxValue", amount.get("minValue")))
    try:
        number = float(str(amount).replace(",", ""))
    except (TypeError, ValueError):
        return None
    if number <= 0:
        return None
    code = str(currency or "").upper()
    symbol = {"USD": "$", "EUR": "€", "GBP": "£", "INR": "₹", "": "$"}.get(code)
    shown = "{:,.0f}".format(number) if number == int(number) else "{:,.2f}".format(number)
    text = "{}{}".format(symbol, shown) if symbol else "{} {}".format(shown, code)
    return text, (int(number) if code in ("USD", "") and symbol == "$" else None)


def parse_structured(html: str, base_url: str = "") -> Dict:
    """Extract schema.org / microdata / OpenGraph facts from a page."""
    parser = _StructuredParser()
    try:
        parser.feed(html or "")
        parser.close()
    except (TypeError, ValueError, AssertionError):
        pass
    out: Dict = {"meta": parser.meta, "icons": parser.icons, "title": parser.title}
    nodes = _ld_nodes(parser.ld)
    wanted = [n for n in nodes if _types(n) & _LD_TYPES]
    # Programme-like nodes first so e.g. a WebPage description never beats a Program's.
    rank = {"event": 0, "educationaloccupationalprogram": 0, "course": 0, "grant": 0,
            "monetarygrant": 0, "courseinstance": 0, "program": 0}
    wanted.sort(key=lambda n: min((rank.get(t, 1) for t in _types(n)), default=2))
    for node in wanted:
        for field in ("applicationDeadline", "validThrough"):
            found = _ld_date(node.get(field))
            if found and "deadline" not in out:
                out["deadline"], out["deadline_field"] = found, field
        offers = node.get("offers")
        offer_list = offers if isinstance(offers, list) else [offers]
        for offer in offer_list:
            if isinstance(offer, dict):
                found = _ld_date(offer.get("validThrough"))
                if found and "deadline" not in out:
                    out["deadline"], out["deadline_field"] = found, "offers.validThrough"
        for field, key in (("startDate", "start_date"), ("endDate", "end_date")):
            found = _ld_date(node.get(field))
            if found and key not in out:
                out[key] = found
        if "description" not in out and _ld_str(node.get("description")):
            out["description"] = _ld_str(node.get("description"))
        if "funding" not in out:
            candidates = [node.get("amount"), node.get("funding"), node.get("monetaryAmount")]
            candidates += [o for o in offer_list if isinstance(o, dict) and o.get("price") not in (None, "", 0, "0")]
            for cand in candidates:
                if isinstance(cand, dict) and ("price" in cand):
                    money = _money(cand.get("price"), cand.get("priceCurrency"))
                elif isinstance(cand, dict) and "@type" in cand and "grant" in str(cand.get("@type")).casefold():
                    money = _money(cand.get("amount"), None)
                else:
                    money = _money(cand, None)
                if money:
                    out["funding"], out["funding_usd"] = money
                    break
        for field in ("eligibleRegion", "applicantLocationRequirements", "spatialCoverage"):
            value = _ld_str(node.get(field))
            if value and "region" not in out:
                out["region_text"] = value
        for field in ("audience", "educationalLevel", "educationalCredentialAwarded", "typicalAgeRange"):
            value = _ld_str(node.get(field))
            if value and "audience" not in out:
                out["audience"] = value
        if "organizer" not in out:
            for field in ("organizer", "provider", "funder", "publisher", "sponsor"):
                value = _ld_str(node.get(field)) if not isinstance(node.get(field), dict) else _ld_str(node[field].get("name"))
                if value:
                    out["organizer"] = value
                    break
        for field in ("logo", "image", "thumbnailUrl"):
            value = _ld_str(node.get(field))
            if value and field not in out:
                out[field] = value
        for field in ("provider", "organizer", "publisher", "funder"):
            sub = node.get(field)
            if isinstance(sub, dict) and "logo_nested" not in out and _ld_str(sub.get("logo")):
                out["logo_nested"] = _ld_str(sub.get("logo"))
        location = node.get("location")
        loc_node = location[0] if isinstance(location, list) and location else location
        if isinstance(loc_node, dict) and "location_text" not in out:
            address = loc_node.get("address")
            parts = []
            if isinstance(address, dict):
                parts = [_ld_str(address.get(k)) for k in ("addressLocality", "addressRegion", "addressCountry")]
            elif isinstance(address, str):
                parts = [clean_text(address)]
            text = ", ".join(p for p in parts if p) or _ld_str(loc_node.get("name"))
            if text:
                out["location_text"] = text
    # Microdata fills only what JSON-LD did not provide.
    props = parser.itemprops
    if "deadline" not in out and _ld_date(props.get("deadline")):
        out["deadline"], out["deadline_field"] = _ld_date(props["deadline"]), "microdata"
    for key in ("start_date", "end_date"):
        if key not in out and _ld_date(props.get(key)):
            out[key] = _ld_date(props[key])
    if "description" not in out and props.get("description"):
        out["description"] = clean_text(props["description"])
    if "logo" not in out and props.get("logo"):
        out["logo"] = props["logo"]
    out["base_url"] = base_url
    return out


# --------------------------------------------------------------------------- #
# Description
# --------------------------------------------------------------------------- #
_BOILERPLATE = re.compile(
    r"cookie|privacy policy|we use (?:cookies|analytics)|accept all|all rights reserved|"
    r"javascript|sign up for|subscribe|newsletter|skip to|log ?in|sign in|menu|copyright|"
    r"terms of (?:use|service)|enable (?:js|javascript)|browser", re.I)
_SKIP_CONTAINERS = frozenset(("nav", "header", "footer", "aside", "form", "script", "style",
                              "noscript", "template", "svg", "button", "select", "dialog"))
_SKIP_ATTR = re.compile(r"cookie|consent|banner|gdpr|modal|popup|newsletter|breadcrumb|sidebar|menu|nav", re.I)


class _Paragraphs(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.in_main: List[str] = []
        self.anywhere: List[str] = []
        self._stack: List[Tuple[str, bool, bool]] = []  # tag, skip, main
        self._skip = 0
        self._main = 0
        self._buf: Optional[List[str]] = None
        self._p_skip = False
        self._p_main = False

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in ("br", "img", "meta", "link", "input", "hr"):
            return
        a = dict(attrs)
        marker = "{} {}".format(a.get("class") or "", a.get("id") or "")
        skip = tag in _SKIP_CONTAINERS or bool(_SKIP_ATTR.search(marker)) or (a.get("aria-hidden") == "true") or ("hidden" in a)
        main = tag in ("main", "article") or (a.get("role") == "main")
        self._stack.append((tag, skip, main))
        self._skip += skip
        self._main += main
        if tag == "p":
            self._buf = []
            self._p_skip, self._p_main = bool(self._skip), bool(self._main)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag == "p" and self._buf is not None:
            text = clean_text(" ".join(self._buf))
            if text and not self._p_skip:
                (self.in_main if self._p_main else self.anywhere).append(text)
            self._buf = None
        for i in range(len(self._stack) - 1, -1, -1):
            if self._stack[i][0] == tag:
                for _, skip, main in self._stack[i:]:
                    self._skip -= skip
                    self._main -= main
                del self._stack[i:]
                break

    def handle_data(self, data):
        if self._buf is not None:
            self._buf.append(data)


def _good_description(text: str, title: str = "") -> bool:
    text = clean_text(text)
    words = text.split()
    if len(text) < 40 or len(words) < 7 or _BOILERPLATE.search(text):
        return False
    if title and text.casefold() == clean_text(title).casefold():
        return False
    return not re.search(r"[{};]|https?://\S{30,}", text)


def extract_description(html: str, structured: Optional[Dict] = None, limit: int = 300) -> Optional[str]:
    structured = structured or parse_structured(html)
    title = structured.get("title", "")
    meta = structured.get("meta", {})
    for candidate in (structured.get("description"), meta.get("og:description"),
                      meta.get("description"), meta.get("twitter:description")):
        if candidate and _good_description(candidate, title):
            return truncate(re.sub(r"<[^>]+>", " ", candidate), limit)
    parser = _Paragraphs()
    try:
        parser.feed(html or "")
        parser.close()
    except (ValueError, TypeError, AssertionError):
        pass
    for paragraph in parser.in_main + parser.anywhere:
        if _good_description(paragraph, title):
            return truncate(paragraph, limit)
    return None


# --------------------------------------------------------------------------- #
# Funding
# --------------------------------------------------------------------------- #
_CURRENCY = {
    "$": ("$", "USD"), "us$": ("$", "USD"), "usd": ("$", "USD"), "us dollars": ("$", "USD"),
    "€": ("€", "EUR"), "eur": ("€", "EUR"), "euro": ("€", "EUR"), "euros": ("€", "EUR"),
    "£": ("£", "GBP"), "gbp": ("£", "GBP"),
    "chf": ("CHF ", "CHF"), "₹": ("₹", "INR"), "inr": ("₹", "INR"), "rs": ("₹", "INR"),
    "cad": ("CA$", "CAD"), "aud": ("A$", "AUD"), "c$": ("CA$", "CAD"), "a$": ("A$", "AUD"),
}
_AMOUNT = re.compile(
    r"(?P<pre>US\$|USD|C\$|A\$|CAD|AUD|CHF|EUR|GBP|INR|Rs\.?|[$€£₹])\s?"
    r"(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s?(?P<mult>million|thousand|lakhs?|[kKmM](?![a-z]))?"
    r"|(?P<num2>\d{1,3}(?:,\d{3})+|\d{3,})\s?(?P<post>USD|EUR|GBP|CHF|INR|euros?|US dollars)\b", re.I)
_FUND_LABELS = (
    ("monthly allowance", "monthly allowance"), ("living allowance", "living allowance"),
    ("stipend", "stipend"), ("allowance", "allowance"), ("tuition", "tuition"),
    ("scholarship", "scholarship"), ("grant", "grant"), ("award", "award"), ("prize", "prize"),
    ("salary", "salary"), ("fellowship", "fellowship"), ("funding", "funding"), ("fund", "funding"),
    ("honorarium", "honorarium"), ("bursary", "bursary"), ("support", "support"),
)
_FUND_NEGATIVE = re.compile(
    r"\b(?:fee|fees|dues|donat\w*|cost|costs|price|purchase|ticket|revenue|raised|valuation|"
    r"series [a-e]|investors?|deposit|refund\w*|membership|registration|loan|debt|salary range)\b", re.I)
_FULLY_FUNDED = re.compile(
    r"\bfully[- ]funded\b|\bfull(?:y)? (?:tuition )?(?:funding|scholarship|ride)\b|"
    r"\ball expenses paid\b|\bfull funding\b", re.I)
_TUITION_COVERED = re.compile(
    r"\btuition (?:is |will be )?(?:fully )?(?:covered|waived|paid)\b|\b(?:covers?|waives?) (?:full |all )?tuition\b|"
    r"\btuition (?:waiver|remission)\b", re.I)
_STIPEND_PROVIDED = re.compile(
    r"\b(?:receive|receives|provid(?:e|es|ed|ing)|offer(?:s|ed|ing)?|include(?:s|d)?|paid|with|earn)\s+"
    r"(?:a |an |the )?(?:[\w-]+\s+){0,3}(?:monthly )?(?:stipend|allowance)\b", re.I)


def _sentence_split(text: str) -> List[str]:
    return [s.strip() for s in re.findall(r"(?:[^.!?\n]|(?<=\d)\.(?=\d))+(?:[.!?]|$)", text) if s.strip()]


def extract_funding(text: str) -> Tuple[Optional[str], Optional[int], Optional[str]]:
    """Return ``(short_text, usd_amount, quote)`` for a page's funding facts."""
    text = (text or "").replace("\xa0", " ")
    best = None
    for sentence in _sentence_split(text):
        lowered = sentence.casefold()
        if not any(label in lowered for label, _ in _FUND_LABELS):
            continue
        for match in _AMOUNT.finditer(sentence):
            pre = (match.group("pre") or match.group("post") or "").casefold().rstrip(".")
            symbol, code = _CURRENCY.get(pre, (None, None))
            if not symbol:
                continue
            raw = (match.group("num") or match.group("num2")).replace(",", "")
            try:
                number = float(raw)
            except ValueError:
                continue
            mult = (match.group("mult") or "").casefold()
            number *= {"k": 1e3, "thousand": 1e3, "m": 1e6, "million": 1e6, "lakh": 1e5, "lakhs": 1e5}.get(mult, 1)
            if number < 100 or number > 5e8:
                continue
            window_before = sentence[max(0, match.start() - 45):match.start()]
            window_after = sentence[match.end():match.end() + 45]
            near = window_before + " " + window_after
            if _FUND_NEGATIVE.search(window_before) or re.match(r"\s*(?:application )?(?:fee|fees)\b", window_after, re.I):
                continue
            label = None
            best_pos = 999
            after_l, before_l = window_after.casefold(), window_before.casefold()
            for key, name in _FUND_LABELS:
                found = after_l.find(key)
                if found >= 0 and found < best_pos:
                    best_pos, label = found, name
                found = before_l.rfind(key)
                if found >= 0 and len(before_l) - found - 16 < best_pos:
                    best_pos, label = len(before_l) - found - 16, name
            if not label:
                continue
            shown = "{:,.0f}".format(number) if number == int(number) else "{:,.2f}".format(number)
            if mult in ("m", "million") and number % 1e5 == 0:
                shown = "{:g}M".format(number / 1e6)
            elif mult in ("k", "thousand") and number % 100 == 0:
                shown = "{:g}K".format(number / 1e3)
            period = ""
            if re.search(r"per month|monthly|a month|/\s?month|each month", near, re.I):
                period = " per month"
            elif re.search(r"per year|annual|a year|/\s?year|each year|per annum", near, re.I):
                period = " per year"
            prefix = "Up to " if re.search(r"\bup to\s*$", window_before, re.I) else ""
            amount_text = "{}{}{}".format(prefix, symbol, shown)
            result = "{} {}{}".format(amount_text, label, period).strip()
            usd = int(number) if code == "USD" else None
            if best is None:
                best = (result, usd, clean_text(sentence))
            break
        if best:
            break
    if best:
        text_value, usd, quote = best
        if _FULLY_FUNDED.search(text):
            text_value = "{} (fully funded)".format(text_value)
        return truncate(text_value, 80), usd, quote
    match = _FULLY_FUNDED.search(text)
    if match:
        return "Fully funded", None, _quote_around(text, match)
    match = _TUITION_COVERED.search(text)
    if match:
        return "Tuition covered", None, _quote_around(text, match)
    match = re.search(r"\b(?:monthly|living) allowance\b", text, re.I)
    if match:
        return "Monthly allowance", None, _quote_around(text, match)
    match = _STIPEND_PROVIDED.search(text)
    if match:
        return "Stipend provided", None, _quote_around(text, match)
    return None, None, None


def _quote_around(text: str, match) -> str:
    start = max(text.rfind(".", 0, match.start()) + 1, match.start() - 160)
    end = text.find(".", match.end())
    end = match.end() + 160 if end < 0 else min(end + 1, match.end() + 160)
    return clean_text(text[start:end])


# --------------------------------------------------------------------------- #
# Eligibility
# --------------------------------------------------------------------------- #
_ELIG_STRONG = re.compile(
    r"\b(?:eligible|eligibility|who can apply|open to|applicants? (?:must|should|need)|"
    r"you (?:must|should) be|must be (?:a |an |currently )|to be considered|citizens?|residents?|"
    r"requirements?|are encouraged to apply|candidates? (?:must|should))\b", re.I)
_ELIG_HEADING = re.compile(r"^(?:who (?:can|may) apply|eligibility(?: criteria| requirements)?|requirements?|"
                           r"who is eligible|am i eligible)\??[:.]?$", re.I)
_ELIG_JUNK = re.compile(r"cookie|click here|sign up|subscribe|privacy|\bfaq\b|read more|learn more", re.I)


def extract_eligibility(text: str, limit: int = 200) -> Tuple[Optional[str], List[str]]:
    """Return ``(clean_sentence, all_cue_sentences)`` for eligibility text."""
    sentences = [clean_text(s) for s in _sentence_split((text or "").replace("\xa0", " "))]
    cue: List[str] = []
    for index, sentence in enumerate(sentences):
        bare = sentence.rstrip(".:?! ")
        if _ELIG_HEADING.match(bare) or _ELIG_HEADING.match(sentence):
            following = [s for s in sentences[index + 1:index + 3] if len(s) > 20]
            if following:
                cue.append(" ".join(following[:1]))
            continue
        if _ELIG_STRONG.search(sentence) and 5 <= len(sentence.split()) <= 60 and not _ELIG_JUNK.search(sentence):
            cue.append(sentence)

    def score(sentence: str) -> int:
        lowered = sentence.casefold()
        points = 0
        for key in ("eligible", "who can apply", "open to", "must be", "applicants must", "to be considered", "citizen", "student"):
            points += key in lowered
        return -points
    cue = list(dict.fromkeys(cue))
    ranked = sorted(cue, key=score)
    first = ranked[0] if ranked else None
    return (truncate(first, limit) if first else None), cue[:8]


_INTL_FALSE = re.compile(
    r"\b(?:(?:only|exclusively)\s+(?:to\s+|for\s+)?(?:u\.?s\.?|american|canadian|uk|british|indian|australian|german|eu)\s+(?:citizens?|nationals?|residents?)|"
    r"(?:open|available|restricted|limited)\s+(?:only\s+)?to\s+(?:u\.?s\.?|american|canadian|uk|british|indian|australian|german|eu)\s+(?:citizens?|nationals?)|"
    r"(?:u\.?s\.?|united states)\s+citizens?(?:\s+or\s+(?:lawful\s+)?permanent\s+residents?)?\s+only|"
    r"must\s+be\s+(?:a\s+)?(?:u\.?s\.?|american|canadian|british|indian|australian)\s+(?:citizen|national|permanent resident)|"
    r"(?:u\.?s\.?\s+)?citizens?\s+(?:or|and)\s+(?:lawful\s+)?permanent\s+residents?\b|"
    r"international\s+(?:students?|applicants?)\s+(?:are\s+)?(?:not\s+eligible|ineligible)|"
    r"not\s+open\s+to\s+international)", re.I)
_INTL_TRUE = re.compile(
    r"\b(?:international\s+(?:students?|applicants?|candidates?|scholars?)\s+(?:are\s+)?(?:welcome|eligible|encouraged|can apply|may apply)|"
    r"open\s+to\s+(?:all\s+)?international|applicants?\s+from\s+(?:any|all)\s+countr|from\s+any\s+country|"
    r"regardless\s+of\s+(?:nationality|citizenship)|open\s+worldwide|worldwide|"
    r"(?:students?|applicants?)\s+(?:of\s+)?any\s+nationality|all\s+nationalities|international\s+applicants?)\b", re.I)
_LEVELS = (
    ("high school", re.compile(r"\bhigh[- ]school\b|\bsecondary[- ]school\b|\bpre-?college\b", re.I)),
    ("undergraduate", re.compile(r"\bundergraduates?\b|\bbachelor'?s?\b|\bB\.?(?:Sc|Tech|E)\b", re.I)),
    ("graduate", re.compile(r"(?<!under)\bgraduate\b|\bpostgraduate\b|\bmaster'?s\b|\bM\.?(?:Sc|Tech|S)\b", re.I)),
    ("phd", re.compile(r"\bph\.?d\.?s?\b|\bdoctoral\b|\bdoctorate\b|\bdoctoral candidates?\b", re.I)),
    ("postdoc", re.compile(r"\bpost-?docs?\b|\bpostdoctoral\b", re.I)),
    ("early-career", re.compile(r"\bearly[- ]career\b|\brecent graduates?\b|\bjunior (?:researchers?|scientists?)\b|\bnew graduates?\b", re.I)),
)


def eligibility_flags(text: str) -> Tuple[Optional[bool], List[str]]:
    text = text or ""
    negative = _INTL_FALSE.search(text)
    positive = _INTL_TRUE.search(text)
    if negative and not positive:
        intl: Optional[bool] = False
    elif positive and not negative:
        intl = True
    else:
        intl = None
    levels = [name for name, pattern in _LEVELS if pattern.search(text)]
    return intl, levels


# --------------------------------------------------------------------------- #
# Region / location
# --------------------------------------------------------------------------- #
_COMMON_SUFFIXES = frozenset((
    "ac.uk", "co.in", "co.jp", "co.nz", "co.uk", "com.au", "com.br", "com.cn", "com.sg",
    "edu.au", "edu.cn", "edu.tw", "gov.au", "gov.in", "gov.uk", "net.au", "org.au",
    "org.cn", "org.in", "org.uk", "ac.in", "res.in", "nic.in", "edu.in", "ac.jp", "ac.za",
    "edu.sg", "edu.hk", "ac.il", "org.nz", "ac.nz", "ac.kr", "co.za",
))


def registrable_domain(url: str) -> Optional[str]:
    try:
        host = (urlparse(str(url)).hostname or "").casefold().rstrip(".")
    except (TypeError, ValueError):
        return None
    labels = [x for x in host.split(".") if x]
    if len(labels) < 2:
        return None
    if ".".join(labels[-2:]) in _COMMON_SUFFIXES and len(labels) >= 3:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


_TLD_REGION = (
    ((".edu", ".gov", ".mil"), "US"),
    ((".ac.uk", ".gov.uk", ".co.uk", ".org.uk", ".uk"), "UK"),
    ((".ac.in", ".res.in", ".nic.in", ".gov.in", ".edu.in", ".co.in", ".in"), "India"),
    ((".ca",), "Canada"),
    ((".com.au", ".edu.au", ".gov.au", ".org.au", ".au"), "Australia"),
    ((".de", ".fr", ".ch", ".nl", ".es", ".it", ".se", ".dk", ".no", ".fi", ".be", ".at", ".ie",
      ".pl", ".pt", ".cz", ".eu", ".lu", ".gr", ".hu", ".ee", ".lt", ".lv", ".si", ".sk", ".hr", ".ro", ".bg"), "Europe"),
    ((".sg", ".jp", ".kr", ".cn", ".tw", ".hk", ".il", ".sa", ".ae", ".my", ".th", ".vn", ".id", ".ph", ".pk", ".bd", ".lk"), "Asia"),
    ((".za", ".ke", ".ng", ".gh", ".rw", ".ug", ".tz", ".et", ".eg", ".ma"), "Africa"),
    ((".br", ".mx", ".ar", ".cl", ".co", ".pe"), "Latin America"),
    ((".nz",), "New Zealand"),
)
_REGION_TEXT = (
    ("US", re.compile(r"\b(?:u\.?s\.?|united states|american)\s+(?:citizens?|residents?|nationals?|permanent residents?|students?|universit\w+)\b", re.I)),
    ("Canada", re.compile(r"\b(?:canadian\s+(?:citizens?|residents?|students?|universit\w+)|residents? of canada|canada)\b", re.I)),
    ("UK", re.compile(r"\b(?:uk|british|united kingdom)\s+(?:citizens?|residents?|students?|universit\w+)\b|\bresidents? of the (?:uk|united kingdom)\b", re.I)),
    ("India", re.compile(r"\b(?:indian\s+(?:citizens?|nationals?|students?|institutions?)|residents? of india|students? (?:from|in|of) india)\b", re.I)),
    ("Europe", re.compile(r"\b(?:eu|european|schengen)\s+(?:citizens?|nationals?|residents?|students?|countries|member states)\b|\bresidents? of (?:the )?(?:eu|europe)\b", re.I)),
    ("Australia", re.compile(r"\b(?:australian\s+(?:citizens?|residents?|students?)|residents? of australia)\b", re.I)),
)
_GLOBAL_TEXT = re.compile(
    r"\b(?:worldwide|global(?:ly)?\s+(?:programme|program|community|applicants?|fellows)|"
    r"open to (?:applicants|students|researchers|people) (?:from )?(?:all|any)|from (?:any|all) countr\w+|"
    r"all nationalities|anyone,? anywhere|around the world|international applicants?)\b", re.I)


def region_from_host(url: str) -> Optional[str]:
    try:
        host = (urlparse(str(url)).hostname or "").casefold().rstrip(".")
    except (TypeError, ValueError):
        return None
    for suffixes, region in _TLD_REGION:
        if any(host.endswith(s) for s in suffixes):
            return region
    return None


def infer_region(url: str, text: str, structured: Optional[Dict] = None,
                 intl_eligible: Optional[bool] = None, remote: bool = False) -> Optional[str]:
    structured = structured or {}
    text = text or ""
    if intl_eligible is False:
        counts = [(len(p.findall(text)), name) for name, p in _REGION_TEXT]
        counts = [item for item in counts if item[0]]
        if counts:
            return max(counts)[1]
    hint = clean_text(structured.get("region_text", ""))
    if hint:
        for name, pattern in _REGION_TEXT:
            if pattern.search(hint + " citizens") or hint.casefold() in ("us", "usa", "united states", name.casefold()):
                return name
        if re.search(r"worldwide|global|\bearth\b", hint, re.I):
            return "Global"
    region = region_from_host(url)
    if region:
        return region
    if intl_eligible is True or _GLOBAL_TEXT.search(text):
        return "Global"
    counts = [(len(p.findall(text)), name) for name, p in _REGION_TEXT]
    counts = [item for item in counts if item[0] >= 2]
    if counts:
        return max(counts)[1]
    return "Global/Remote" if remote else None


_LOC_STOPWORDS = frozenset((
    "is", "are", "was", "were", "be", "been", "being", "designed", "will", "would", "can",
    "could", "should", "may", "must", "our", "we", "you", "your", "their", "this", "that",
    "these", "those", "which", "who", "program", "programme", "apply", "application", "offers",
    "offer", "provide", "provides", "includes", "help", "helps", "learn", "work", "works",
    "join", "has", "have", "had", "do", "does", "not", "the", "a", "an", "to", "for", "with",
    "from", "by", "at", "on", "it", "its", "as", "or", "if", "when", "while", "about", "how",
    "what", "all", "any", "more", "than", "each", "every", "also", "over", "into", "through",
))


def clean_location(value) -> Optional[str]:
    """Return a short place-like string or ``None`` for junk/prose fragments."""
    text = clean_text(value)
    if is_placeholder(text):
        return None
    if len(text) > 40 or text.endswith((".", "?", "!", ":")) or re.search(r"[@<>{}|\\/]|https?:|\d{4,}", text):
        return None
    words = re.findall(r"[^\W\d_][\w'’.-]*", text, re.UNICODE)
    if not words or len(words) > 6:
        return None
    lowered = [w.casefold().strip(".'’-") for w in words]
    # "of"/"and"/"in" appear in real places ("United States of America", "Trinidad and Tobago").
    if any(w in _LOC_STOPWORDS for w in lowered):
        return None
    if not any(w[0].isupper() for w in words):
        return None
    return text


# --------------------------------------------------------------------------- #
# Logo
# --------------------------------------------------------------------------- #
def _abs_https(value, base: str) -> Optional[str]:
    value = clean_text(value)
    if not value or value.startswith(("data:", "javascript:", "#")):
        return None
    try:
        resolved = urljoin(base or "", value)
        parsed = urlparse(resolved)
    except ValueError:
        return None
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None
    return "https://" + resolved.split("://", 1)[1]


def _icon_size(sizes: str, href: str) -> int:
    best = 0
    for match in re.finditer(r"(\d+)x(\d+)", sizes or ""):
        best = max(best, min(int(match.group(1)), int(match.group(2))))
    if not best and (sizes == "any" or href.lower().split("?")[0].endswith(".svg")):
        best = 512
    return best


def pick_logo(structured: Dict, base_url: str) -> Optional[str]:
    """Prefer square logos/icons over banners; absolute https only."""
    base = base_url or structured.get("base_url", "")
    meta = structured.get("meta", {})
    icons = structured.get("icons", [])
    apple = sorted(((_icon_size(sz, href) or 180, href) for rel, sz, href in icons if "apple-touch-icon" in rel), reverse=True)
    regular = sorted(((_icon_size(sz, href), href) for rel, sz, href in icons
                      if "icon" in rel and "apple" not in rel and "mask" not in rel), reverse=True)
    og = meta.get("og:image") or meta.get("og:image:url") or meta.get("twitter:image")
    candidates = [structured.get("logo"), structured.get("logo_nested")]
    candidates += [href for _, href in apple[:1]]
    candidates += [href for size, href in regular if size >= 64][:1]
    if og and re.search(r"logo|icon|mark|square", og, re.I):
        candidates.append(og)
    candidates += [href for size, href in regular[:1]]
    candidates += [og, structured.get("image"), structured.get("thumbnailUrl")]
    for candidate in candidates:
        resolved = _abs_https(candidate, base)
        if resolved:
            return resolved
    return None


# --------------------------------------------------------------------------- #
# Application link
# --------------------------------------------------------------------------- #
_APPLY_STRONG = re.compile(
    r"^\W*(?:apply(?:\s+(?:now|here|today|online|for\b.*|to\b.*))?|start\s+(?:your\s+|an\s+|the\s+)?application|"
    r"application\s+(?:portal|form|link|page|system)|submit\s+(?:your\s+|an\s+|the\s+)?application|"
    r"begin\s+(?:your\s+)?application|apply\s+online|open\s+application|go\s+to\s+application\s+portal)\W*$", re.I)
_APPLY_WEAK = re.compile(r"\bapply\b|\bapplication\s+(?:portal|form)\b", re.I)
_APPLY_BAD = re.compile(r"\b(?:how\s+to|tips|guide|faq|instructions?|requirements?|checklist|login|log in|sign in|status|deadline|webinar|advice|process)\b", re.I)
_APPLY_PORTAL_HOSTS = (
    "smapply.io", "smapply.org", "fluidreview.com", "submittable.com", "airtable.com",
    "forms.gle", "docs.google.com", "typeform.com", "tfaforms.net", "slideroom.com",
    "grants.gov", "formstack.com", "jotform.com", "workable.com", "ashbyhq.com",
    "lever.co", "greenhouse.io", "apply.", "wufoo.com", "cognitoforms.com", "surveymonkey.com",
    "zohoforms", "forms.office.com", "interfolio.com", "embark.", "smartsheet.com",
)


def find_application_link(links: Iterable[Tuple[str, str]], seed_url: str,
                          final_url: Optional[str] = None) -> Optional[Tuple[str, str]]:
    """Return ``(label, absolute_url)`` of the best Apply link on the page."""
    base = final_url or seed_url
    page_domain = registrable_domain(base) or registrable_domain(seed_url)
    seed_domain = registrable_domain(seed_url)
    best = None
    for label, href in links:
        label, href = clean_text(label), (href or "").strip()
        if not label or not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        if len(label) > 70 or _APPLY_BAD.search(label):
            continue
        strong = bool(_APPLY_STRONG.match(label))
        if not strong and not _APPLY_WEAK.search(label):
            continue
        resolved = urljoin(base, href)
        parsed = urlparse(resolved)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            continue
        domain = registrable_domain(resolved)
        host = parsed.netloc.lower()
        trusted = domain in (page_domain, seed_domain) or any(
            host.endswith(p) or host.startswith(p) for p in _APPLY_PORTAL_HOSTS)
        if not trusted:
            continue
        if resolved.rstrip("/") == (final_url or seed_url).rstrip("/"):
            continue
        rank = (0 if strong else 1, 0 if domain in (page_domain, seed_domain) else 1)
        if best is None or rank < best[0]:
            best = (rank, label, resolved)
    return (best[1], best[2]) if best else None


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
ENRICH_KEYS = ("description", "funding", "eligibility", "location", "region", "logo_url",
               "organizer_domain", "application_url", "funding_amount_usd", "intl_eligible",
               "levels", "deadline_basis", "start_date", "end_date")


def enrich_fields(html: str, text: str, url: str, final_url: Optional[str] = None,
                  links: Optional[List[Tuple[str, str]]] = None,
                  structured: Optional[Dict] = None) -> Dict:
    """Return only the fields we could extract (never placeholders)."""
    base = final_url or url
    structured = structured or parse_structured(html, base)
    out: Dict = {}
    description = extract_description(html, structured)
    if description:
        out["description"] = description
    funding, usd, funding_quote = extract_funding(text)
    if structured.get("funding") and not funding:
        funding, usd, funding_quote = structured["funding"], structured.get("funding_usd"), None
    if funding:
        out["funding"] = funding
        if usd:
            out["funding_amount_usd"] = usd
        if funding_quote:
            out["_funding_quote"] = funding_quote
    eligibility, cues = extract_eligibility(text)
    if eligibility:
        out["eligibility"] = eligibility
        out["_eligibility_quote"] = eligibility
    flag_text = " ".join(cues + [structured.get("audience", ""), out.get("description", "")])
    intl, levels = eligibility_flags(flag_text if flag_text.strip() else "")
    if intl is None:
        # Whole-page fallback for explicit statements only.
        intl, _ = eligibility_flags(text)
    if intl is not None:
        out["intl_eligible"] = intl
    if levels:
        out["levels"] = levels
    remote = bool(re.search(r"\b(?:fully remote|remote program|virtual program|online program|100% (?:remote|online))", text, re.I))
    region = infer_region(base, " ".join(cues) or text[:4000], structured, intl, remote)
    if region:
        out["region"] = region
    location = clean_location(structured.get("location_text"))
    if location:
        out["location"] = location
    elif remote:
        out["location"] = "Remote"
        out["remote"] = True
    logo = pick_logo(structured, base)
    if logo:
        out["logo_url"] = logo
    domain = registrable_domain(base) or registrable_domain(url)
    if domain:
        out["organizer_domain"] = domain
    for key in ("start_date", "end_date"):
        if structured.get(key):
            out[key] = structured[key]
    if links:
        apply_link = find_application_link(links, url, final_url)
        if apply_link:
            out["application_url"] = apply_link[1]
            out["_application_label"] = apply_link[0]
    return out
