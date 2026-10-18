"""Deterministic job-posting metadata helpers (no network, no AI).

Shared by the ATS adapters, the sweep, the dedupe step and the publisher:
URL canonicalisation, employment type / workplace / level normalisation,
salary parsing, posted-date normalisation, company-domain derivation and a
JSON-LD ``JobPosting`` reader for pages.
"""
from __future__ import annotations

import html as _html
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# --------------------------------------------------------------------------- #
# URL canonicalisation
# --------------------------------------------------------------------------- #
_TRACKING_PARAMS = {
    "gh_src", "lever-source", "lever-origin", "ref", "refid", "ref_id",
    "source", "src", "fbclid", "gclid", "mc_cid", "mc_eid", "_hsenc", "_hsmi",
    "trk", "trkinfo", "sid", "campaign", "referrer", "referral",
}
_APPLY_SUFFIX = re.compile(r"/(apply|application)$", re.I)


def canonical_url(url: Optional[str]) -> str:
    """Normalise a posting URL for comparison. Never used for id hashing.

    Strips tracking parameters (utm_*, gh_src, lever-source, ref, source...),
    the fragment, default ports, trailing slashes and a trailing /apply or
    /application segment; lower-cases scheme and host; sorts what remains.
    ``gh_jid`` is kept: on company-hosted Greenhouse pages it IS the identity.
    """
    if not url or not isinstance(url, str):
        return ""
    try:
        p = urlsplit(url.strip())
    except ValueError:
        return url.strip().rstrip("/").lower()
    if not p.netloc:
        return url.strip().rstrip("/").lower()
    host = (p.hostname or "").lower()
    if p.port and p.port not in (80, 443):
        host = "{}:{}".format(host, p.port)
    query = sorted(
        (k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
        if k.lower() not in _TRACKING_PARAMS and not k.lower().startswith("utm_"))
    path = _APPLY_SUFFIX.sub("", p.path.rstrip("/"))
    return urlunsplit(((p.scheme or "https").lower(), host, path,
                       urlencode(query), ""))


# --------------------------------------------------------------------------- #
# Text
# --------------------------------------------------------------------------- #
def clean_text(s: Optional[str], limit: Optional[int] = None) -> str:
    """HTML -> single-spaced plain text (handles double-escaped HTML)."""
    if not s:
        return ""
    s = _html.unescape(str(s))
    s = re.sub(r"(?i)<\s*(br|/p|/li|/div|/h[1-6])\s*/?>", " ", s)
    s = re.sub(r"<[^>]+>", " ", s)
    s = _html.unescape(s)
    s = " ".join(s.split())
    return s[:limit] if limit else s


def snippet(s: Optional[str], limit: int = 300) -> Optional[str]:
    """Plain-text snippet of at most ``limit`` chars, cut at a word boundary."""
    s = clean_text(s)
    if not s:
        return None
    if len(s) <= limit:
        return s
    cut = s[:limit]
    if s[limit] != " " and " " in cut:
        cut = cut[:cut.rfind(" ")]
    return cut.rstrip(" ,;:-") or s[:limit]


# --------------------------------------------------------------------------- #
# Employment type / workplace / level
# --------------------------------------------------------------------------- #
def norm_employment_type(value) -> Optional[str]:
    """full-time | part-time | internship | contract | temporary | apprenticeship."""
    if not value:
        return None
    v = re.sub(r"[^a-z]+", " ", str(value).lower()).strip()
    if not v:
        return None
    if "intern" in v or "co op" in v or "coop" in v:
        return "internship"
    if "apprentic" in v:
        return "apprenticeship"
    if "part" in v and "time" in v or v == "parttime":
        return "part-time"
    if "full" in v and "time" in v or v == "fulltime" or v == "regular" or v == "permanent":
        return "full-time"
    if any(w in v for w in ("contract", "freelance", "consultant")):
        return "contract"
    if any(w in v for w in ("temp", "seasonal")):
        return "temporary"
    return None


def norm_workplace(value) -> Optional[str]:
    """remote | hybrid | onsite."""
    if value is None or value == "":
        return None
    if value is True:
        return "remote"
    v = re.sub(r"[^a-z]+", " ", str(value).lower()).strip()
    if "hybrid" in v:
        return "hybrid"
    if "remote" in v or "telecommut" in v or "work from home" in v:
        return "remote"
    if "on site" in v or "onsite" in v or "in office" in v or "office" == v:
        return "onsite"
    return None


_HYBRID_RE = re.compile(r"\bhybrid\b", re.I)
_REMOTE_RE = re.compile(r"\b(remote|work from home|wfh|distributed)\b", re.I)


def workplace_from_text(*texts) -> Optional[str]:
    blob = " ".join(t for t in texts if t)
    if not blob:
        return None
    if _HYBRID_RE.search(blob):
        return "hybrid"
    if _REMOTE_RE.search(blob):
        return "remote"
    return None


_TITLE_EMPLOYMENT = (
    (re.compile(r"\b(interns?|internships?|co-?op|working student|werkstudent)\b", re.I), "internship"),
    (re.compile(r"\bapprentice(ship)?\b", re.I), "apprenticeship"),
    (re.compile(r"\b(part[- ]time)\b", re.I), "part-time"),
    (re.compile(r"\b(contract|contractor|freelance|fixed[- ]term)\b", re.I), "contract"),
    (re.compile(r"\b(temporary|seasonal)\b", re.I), "temporary"),
)


def employment_from_title(title: Optional[str]) -> Optional[str]:
    for rx, label in _TITLE_EMPLOYMENT:
        if rx.search(title or ""):
            return label
    return None


_LEVEL_RULES = (
    (re.compile(r"\b(interns?|internships?|co-?op|trainee|working student)\b", re.I), "intern"),
    (re.compile(r"\b(new[- ]?grad(uate)?s?|graduate (program|scheme|engineer|developer)|"
                r"campus|university grad(uate)?|early careers?)\b", re.I), "new_grad"),
    (re.compile(r"\b(entry[- ]level|entry level)\b", re.I), "entry"),
    (re.compile(r"\b(junior|jr\.?|associate (software|engineer|developer|analyst))\b", re.I), "junior"),
)


def detect_level(title: Optional[str], employment_type: Optional[str] = None,
                 seniority_hint: Optional[str] = None) -> Optional[str]:
    """intern | new_grad | entry | junior from title keywords / ATS hints."""
    if employment_type == "internship":
        return "intern"
    for rx, label in _LEVEL_RULES:
        if rx.search(title or ""):
            return label
    hint = (seniority_hint or "").lower()
    if hint:
        if "intern" in hint:
            return "intern"
        if "entry" in hint:
            return "entry"
        if "junior" in hint:
            return "junior"
    return None


def region_of(bucket: Optional[str]) -> str:
    """Coarse audience region tag from a location bucket."""
    if bucket in ("us_located", "us_remote"):
        return "us"
    if bucket in ("india_located", "india_remote"):
        return "india"
    if bucket in ("remote_global", "global_hiring"):
        return "global"
    return "other"


# --------------------------------------------------------------------------- #
# Dates
# --------------------------------------------------------------------------- #
def to_iso(value, now: Optional[datetime] = None) -> Optional[str]:
    """Normalise epoch ms/s, ISO strings and Workday 'Posted N Days Ago'."""
    if value in (None, "", 0):
        return None
    now = now or datetime.now(timezone.utc)
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        ts = float(value)
        if ts > 1e11:
            ts /= 1000.0
        try:
            return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds")
        except (OverflowError, OSError, ValueError):
            return None
    s = str(value).strip()
    if not s:
        return None
    low = s.lower()
    if low.startswith("posted"):
        if "today" in low:
            return now.date().isoformat()
        if "yesterday" in low:
            return (now - timedelta(days=1)).date().isoformat()
        m = re.search(r"(\d+)\+?\s*day", low)
        if m and "+" not in low:
            return (now - timedelta(days=int(m.group(1)))).date().isoformat()
        return None  # "30+ days ago": unknown, not a date
    if re.match(r"^\d{4}-\d{2}-\d{2}", s):
        return s
    return None


# --------------------------------------------------------------------------- #
# Salary
# --------------------------------------------------------------------------- #
_CURRENCY = {"$": "USD", "us$": "USD", "usd": "USD", "£": "GBP", "gbp": "GBP",
             "€": "EUR", "eur": "EUR", "₹": "INR", "inr": "INR", "cad": "CAD",
             "c$": "CAD", "aud": "AUD", "a$": "AUD", "sgd": "SGD", "chf": "CHF"}
_CUR_RE = r"(?:US\$|USD|C\$|CAD|A\$|AUD|SGD|CHF|GBP|EUR|INR|\$|£|€|₹)"
_NUM_RE = r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?"
_RANGE_RE = re.compile(
    r"(?P<c1>{c})\s?(?P<a>{n})\s?(?P<ak>[kK])?\s?(?:[-–—]|to)\s?(?P<c2>{c})?\s?"
    r"(?P<b>{n})\s?(?P<bk>[kK])?(?P<tail>[^.;\n]{{0,28}})".format(c=_CUR_RE, n=_NUM_RE))
_INTERVALS = (("hour", ("hour", "/hr", "/h", "per hr", "hourly")),
              ("month", ("month", "/mo")),
              ("week", ("week", "/wk")),
              ("day", ("day", "daily")),
              ("year", ("year", "annual", "/yr", "p.a", "per annum", "yearly")))


def _interval_of(text: str) -> Optional[str]:
    t = (text or "").lower()
    for name, keys in _INTERVALS:
        if any(k in t for k in keys):
            return name
    return None


def norm_interval(value) -> Optional[str]:
    v = str(value or "").lower()
    for name in ("year", "month", "week", "day", "hour"):
        if name in v:
            return name
    return None


def format_salary(lo, hi, currency: Optional[str], interval: Optional[str]) -> str:
    def f(x):
        return "{:,.0f}".format(x) if float(x).is_integer() else "{:,.2f}".format(x)
    amt = f(lo) if hi in (None, lo) else "{}-{}".format(f(lo), f(hi))
    out = "{} {}".format(currency, amt).strip() if currency else amt
    return out + (" per {}".format(interval) if interval else "")


def salary_fields(lo, hi, currency, interval) -> Dict:
    """Structured salary -> extra.salary_* keys (empty dict if no amount)."""
    nums = [x for x in (lo, hi) if isinstance(x, (int, float)) and not isinstance(x, bool) and x > 0]
    if not nums:
        return {}
    lo_v, hi_v = (min(nums), max(nums)) if len(nums) == 2 else (nums[0], nums[0])
    out = {"salary_min": lo_v, "salary_max": hi_v,
           "salary_text": format_salary(lo_v, hi_v, currency, interval)}
    if currency:
        out["salary_currency"] = currency
    if interval:
        out["salary_interval"] = interval
    return out


def parse_salary_text(text: Optional[str]) -> Dict:
    """Find the first explicit currency range ('$120,000 - $150,000') in text."""
    if not text:
        return {}
    for m in _RANGE_RE.finditer(text):
        tail = m.group("tail") or ""
        if re.match(r"\s*(million|billion|m\b|bn\b|b\b|%|employees|users|customers)", tail, re.I):
            continue
        try:
            lo = float(m.group("a").replace(",", ""))
            hi = float(m.group("b").replace(",", ""))
        except ValueError:
            continue
        if m.group("ak"):
            lo *= 1000
        if m.group("bk") or (m.group("ak") and hi < 1000):
            hi *= 1000
        if lo > hi:
            continue
        interval = _interval_of(tail) or ("year" if lo >= 8000 else None)
        if interval == "year" and lo < 8000:
            continue
        cur = _CURRENCY.get((m.group("c1") or "").lower())
        fields = salary_fields(lo, hi, cur, interval)
        if fields:
            return fields
    return {}


# --------------------------------------------------------------------------- #
# Company domain
# --------------------------------------------------------------------------- #
_ATS_HOST_SUFFIXES = (
    "greenhouse.io", "lever.co", "ashbyhq.com", "workable.com", "myworkdayjobs.com",
    "myworkdaysite.com", "smartrecruiters.com", "eightfold.ai", "keka.com",
    "zohorecruit.com", "zoho.com", "darwinbox.in", "darwinbox.com", "personio.de",
    "personio.com", "recruitee.com", "successfactors.com", "successfactors.eu",
    "icims.com", "jobvite.com", "taleo.net", "unstop.com", "github.com",
    "github.io", "linkedin.com", "facebook.com", "twitter.com", "x.com",
    "instagram.com", "youtube.com", "google.com", "workday.com", "oraclecloud.com",
    "bamboohr.com", "breezy.hr", "applytojob.com", "teamtailor.com", "jobs.lever.co",
)
_STRIP_PREFIXES = {"www", "careers", "career", "jobs", "job", "apply", "work", "join",
                   "talent", "hiring", "boards", "recruiting", "en", "us"}
_SLD = {"co", "com", "org", "net", "ac", "gov", "edu"}


def is_ats_host(host: str) -> bool:
    host = (host or "").lower()
    return any(host == s or host.endswith("." + s) for s in _ATS_HOST_SUFFIXES)


def registrable_domain(host: str) -> Optional[str]:
    host = (host or "").lower().strip(".")
    if not host or "." not in host or re.match(r"^\d+\.\d+\.\d+\.\d+$", host):
        return None
    labels = host.split(".")
    while len(labels) > 2 and labels[0] in _STRIP_PREFIXES:
        labels.pop(0)
    if len(labels) >= 3 and len(labels[-1]) == 2 and labels[-2] in _SLD:
        labels = labels[-3:]
    else:
        labels = labels[-2:]
    return ".".join(labels)


def domain_from_url(url: Optional[str]) -> Optional[str]:
    """Employer domain from a URL, or None for ATS/social hosts."""
    if not url or not isinstance(url, str):
        return None
    try:
        host = urlsplit(url if "//" in url else "//" + url).hostname or ""
    except ValueError:
        return None
    if not host or is_ats_host(host):
        return None
    return registrable_domain(host)


def _name_key(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def domain_matches_name(domain: str, *names: str) -> bool:
    """True if the domain's main label and a company name overlap (safety net
    for domains scraped from free text, where the first URL may be a partner's)."""
    label = _name_key(domain.split(".")[0])
    if len(label) < 3:
        return False
    for n in names:
        k = _name_key(n)
        if len(k) >= 3 and (label in k or k in label):
            return True
    return False


_URL_IN_TEXT = re.compile(
    r"(?:https?://)?(?:www\.)?((?:[a-z0-9-]+\.)+[a-z]{2,})(?:/[^\s<>\"']*)?", re.I)


def domain_from_text(text: Optional[str], *names: str) -> Optional[str]:
    """First URL-like domain in free text that matches a company name."""
    for m in _URL_IN_TEXT.finditer(text or ""):
        d = domain_from_url(m.group(0))
        if d and domain_matches_name(d, *names):
            return d
    return None


def favicon_logo(domain: Optional[str], size: int = 128) -> Optional[str]:
    if not domain:
        return None
    return "https://www.google.com/s2/favicons?domain={}&sz={}".format(domain, size)


# --------------------------------------------------------------------------- #
# JSON-LD JobPosting (pages)
# --------------------------------------------------------------------------- #
_LD_RE = re.compile(
    r"<script[^>]+type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>", re.I | re.S)


def _walk_ld(node, out: List[dict]) -> None:
    if isinstance(node, list):
        for n in node:
            _walk_ld(n, out)
    elif isinstance(node, dict):
        t = node.get("@type")
        types = t if isinstance(t, list) else [t]
        if "JobPosting" in types:
            out.append(node)
        for v in node.values():
            if isinstance(v, (list, dict)):
                _walk_ld(v, out)


def parse_jsonld_job(page_html: Optional[str]) -> Dict:
    """Extract salary, validThrough, posted date, employment type, workplace and
    hiring-organization identity from a page's JSON-LD ``JobPosting``."""
    postings: List[dict] = []
    for m in _LD_RE.finditer(page_html or ""):
        try:
            _walk_ld(json.loads(_html.unescape(m.group(1).strip())), postings)
        except (ValueError, TypeError):
            continue
    if not postings:
        return {}
    j = postings[0]
    out: Dict = {}
    if j.get("datePosted"):
        out["posted_at"] = to_iso(str(j["datePosted"])) or str(j["datePosted"])[:25]
    if j.get("validThrough"):
        out["deadline"] = str(j["validThrough"])[:10]
    et = j.get("employmentType")
    if isinstance(et, list):
        et = et[0] if et else None
    if norm_employment_type(et):
        out["employment_type"] = norm_employment_type(et)
    if str(j.get("jobLocationType", "")).upper() == "TELECOMMUTE":
        out["workplace"] = "remote"
    bs = j.get("baseSalary")
    if isinstance(bs, dict):
        cur = bs.get("currency")
        val = bs.get("value")
        if isinstance(val, dict):
            lo, hi = val.get("minValue", val.get("value")), val.get("maxValue", val.get("value"))
            unit = val.get("unitText")
        else:
            lo = hi = val
            unit = None
        try:
            lo = float(lo) if lo is not None else None
            hi = float(hi) if hi is not None else None
        except (TypeError, ValueError):
            lo = hi = None
        out.update(salary_fields(lo, hi, cur, norm_interval(unit)))
    org = j.get("hiringOrganization")
    if isinstance(org, dict):
        if org.get("name"):
            out["company_display_name"] = str(org["name"]).strip()
        dom = domain_from_url(org.get("sameAs") or org.get("url"))
        if dom:
            out["company_domain"] = dom
    return out
