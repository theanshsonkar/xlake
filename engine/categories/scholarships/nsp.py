"""National Scholarship Portal (scholarships.gov.in) per-scheme enrichment.

The portal's All-Scholarships page is server-rendered: each scheme block lists
its application window and links a guideline ("Specifications") PDF. Those PDFs
state the award ("Rs. 50,000 per annum"), which the shared page never does. This
reads the page once, matches schemes to existing lake rows by name, fetches each
scheme's guideline PDF (cached, capped, robots-respecting, text via ``pdftotext``
when installed) and writes the quote-backed amount onto the row. A scheme whose
PDF cannot be read is left untouched.
"""
from __future__ import annotations

import html as html_lib
import json
import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from typing import Callable, Dict, Iterable, List, Optional
from urllib import request
from urllib.parse import quote, urljoin

from core import robots
from core.paths import OPERATIONS_DIR
from categories import programme_enrich as enrich

NSP_PAGE = "https://scholarships.gov.in/All-Scholarships"
CACHE_PATH = os.path.join(OPERATIONS_DIR, "nsp_schemes.json")
MAX_PDFS_PER_RUN = 40
CACHE_DAYS = 30
UA = "opportunity-radar (+official-source reader)"
_BLOCK = re.compile(r'<div class="row mb-4 border-1 border-bottom">(.*?)(?=<div class="row mb-4 border-1 border-bottom">|\Z)', re.S)
_TITLE = re.compile(r"<h6>\s*(.*?)\s*</h6>", re.S)
_LINK = re.compile(r'<a href="([^"]+)"[^>]*>\s*(Specifications|FAQ)\s*</a>', re.I)
_TILL = re.compile(r"Student\s+Application\s+Open\s+till[^:]*:\s*(\d{2})-(\d{2})-(\d{4})", re.I)
_FROM = re.compile(r"Scheme\s+Open\s+from[^:]*:\s*(\d{2})-(\d{2})-(\d{4})", re.I)
_RS = re.compile(r"(?:Rs\.?|\u20b9|INR)\s?(?P<num>\d{1,3}(?:,\d{2,3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s?(?P<mult>lakhs?|lacs?|crores?)?", re.I)
_PERIOD = re.compile(r"^[^.;]{0,25}?(?:(?P<month>per\s+month|monthly|p\.?m\b|/\s?month)|(?P<year>per\s+annum|per\s+year|p\.?a\b|annually|/\s?year|yearly))", re.I)
_AWARD_BEFORE = re.compile(r"(?:amount of scholarship|rate of scholarship|scholarships?[^.]{0,60}rate of|at the rate of|maintenance allowance|stipend\s*@)", re.I)
_NOT_AWARD = re.compile(r"(?:income|ceiling|maximum|exceed|not more than|less than|below|limit|\bfees?\b|tuition|parental|family|reimburs|books?|stationery|hostel|living|course)", re.I)
_MULT = {"lakh": 1e5, "lakhs": 1e5, "lac": 1e5, "lacs": 1e5, "crore": 1e7, "crores": 1e7}


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", html_lib.unescape(re.sub(r"<[^>]+>", " ", text))).strip()


def scheme_key(title: str) -> str:
    """Comparable scheme name: drop the trailing '(... Scheme)' tag, punctuation, case."""
    title = re.sub(r"\((?:[^()]*\bScheme)\)\s*$", "", title or "", flags=re.I)
    return re.sub(r"[^a-z0-9]+", "", title.casefold())


def _iso(match) -> Optional[str]:
    return "{}-{}-{}".format(match.group(3), match.group(2), match.group(1)) if match else None


def parse_schemes(page_html: str) -> List[Dict]:
    schemes = []
    for block in _BLOCK.findall(page_html or ""):
        title_match = _TITLE.search(block)
        if not title_match:
            continue
        links = {kind.casefold(): url for url, kind in _LINK.findall(block)}
        guideline = links.get("specifications")
        if guideline and guideline.endswith("not_available.pdf"):
            guideline = None
        text = _clean(block)
        schemes.append({
            "title": _clean(title_match.group(1)),
            "key": scheme_key(_clean(title_match.group(1))),
            "guideline_url": urljoin(NSP_PAGE, guideline.replace(" ", "%20")) if guideline else None,
            "opens": _iso(_FROM.search(text)),
            "deadline": _iso(_TILL.search(text)),
        })
    return schemes


def amount_from_text(text: str):
    """(funding_text, quote) from guideline text, or (None, None) when unclear.

    Only award statements count ("Amount of scholarship: Rs. 50,000 per annum",
    "at the rate of Rs. 8,000 per month"); income limits, fee ceilings and
    reimbursements are skipped. Several different rates (per level or
    component) are ambiguous and return nothing rather than one misleading figure.
    """
    text = re.sub(r"\s+", " ", (text or "").replace("\xa0", " "))
    hits = []
    for match in _RS.finditer(text):
        before = text[max(0, match.start() - 70):match.start()]
        after = text[match.end():match.end() + 60]
        period = _PERIOD.match(after)
        if not period or not _AWARD_BEFORE.search(before) or _NOT_AWARD.search(before[-45:]):
            continue
        try:
            number = float(match.group("num").replace(",", "")) * _MULT.get((match.group("mult") or "").casefold(), 1)
        except ValueError:
            continue
        if number < 100:
            continue
        hits.append(("month" if period.group("month") else "year", number,
                     text[max(0, match.start() - 90):match.end() + 70].strip()))
    if not hits:
        return None, None
    unit = hits[0][0]
    amounts = {h[1] for h in hits if h[0] == unit}
    if len(amounts) != 1 or any(h[0] != unit for h in hits):
        return None, None  # several rates (levels/components): not one honest number
    return "\u20b9{} scholarship per {}".format(enrich.format_inr(amounts.pop()), unit), hits[0][2]


def pdf_text(url: str) -> Optional[str]:
    if not shutil.which("pdftotext") or not robots.allowed(url)[0]:
        return None
    try:
        req = request.Request(quote(url, safe=":/%?=&;()"), headers={"User-Agent": UA})
        with request.urlopen(req, timeout=60) as response:
            data = response.read(8_000_000)
        with tempfile.NamedTemporaryFile(suffix=".pdf") as handle:
            handle.write(data)
            handle.flush()
            return subprocess.run(["pdftotext", handle.name, "-"], capture_output=True, text=True,
                                  timeout=60, check=True).stdout
    except Exception:
        return None


def _page_html(url: str) -> Optional[str]:
    try:
        if not robots.allowed(url)[0]:
            return None
        req = request.Request(url, headers={"User-Agent": UA})
        with request.urlopen(req, timeout=60) as response:
            return response.read().decode("utf-8", "replace")
    except Exception:
        return None


def _fresh(entry: Dict, now: datetime) -> bool:
    try:
        age = now - datetime.fromisoformat(entry["fetched_at"])
        return age.days < CACHE_DAYS
    except (KeyError, ValueError, TypeError):
        return False


def is_nsp_row(row: Dict) -> bool:
    return (row.get("record_type") == "programme"
            and "scholarships.gov.in/All-Scholarships" in str(row.get("official_url") or ""))


def enrich_rows(rows: Iterable[Dict], fetch_page: Callable[[str], Optional[str]] = _page_html,
                fetch_pdf: Callable[[str], Optional[str]] = pdf_text, cache_path: str = CACHE_PATH,
                now: Optional[datetime] = None) -> List[Dict]:
    rows = list(rows)
    targets = [r for r in rows if is_nsp_row(r)]
    if not targets:
        return rows
    now = now or datetime.now(timezone.utc)
    try:
        with open(cache_path) as handle:
            cache = json.load(handle)
    except (OSError, ValueError):
        cache = {}
    page = fetch_page(NSP_PAGE)
    schemes = {s["key"]: s for s in parse_schemes(page)} if page else {}
    budget = MAX_PDFS_PER_RUN
    for row in targets:
        key = scheme_key(row.get("title") or row.get("programme_name") or "")
        scheme = schemes.get(key)
        if scheme is None:
            scheme = next((s for k, s in schemes.items() if key and (k.startswith(key) or key.startswith(k))), None)
        if not scheme or not scheme.get("guideline_url"):
            continue
        url = scheme["guideline_url"]
        entry = cache.get(url)
        if not entry or not _fresh(entry, now):
            if budget <= 0:
                continue
            budget -= 1
            text = fetch_pdf(url)
            if text is None:
                continue
            funding, quote_text = amount_from_text(text)
            entry = {"funding": funding, "quote": quote_text, "fetched_at": now.isoformat(timespec="seconds")}
            cache[url] = entry
        if entry.get("funding") and str(row.get("funding") or "not_stated") in ("not_stated", "None", "needs_confirmation"):
            row["funding"] = entry["funding"]
            row.update(enrich.normalise_funding(entry["funding"]))
            evidence = row.get("official_evidence")
            if not isinstance(evidence, dict):
                evidence = row["official_evidence"] = {}
            evidence["funding"] = {"quote": entry["quote"], "url": url}
        row["guidelines_url"] = url
    if cache:
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        with open(cache_path, "w") as handle:
            json.dump(cache, handle, indent=1, sort_keys=True)
    return rows
