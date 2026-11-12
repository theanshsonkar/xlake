"""Standard row shape: one fixed 26-field view of any lake row (pure, no I/O).

``to_standard(row)`` maps a raw per-category row (job, internship, programme,
hackathon, open-source contribution) onto ``FIELDS``. Every key is always
present; unknown values are ``None`` / ``[]`` / ``{}``. Nothing is invented:
this is a mapping, not an inference engine, and it never emits descriptions.

Rules enforced here:
  * ``org`` / ``logo`` are never a job board or aggregator (``jobmeta``'s list).
  * Email addresses and phone numbers are scrubbed from every text value.
  * Dates are ``YYYY-MM-DD`` or ``None``.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any, Dict, List, Optional

from categories.programme_enrich import clean_location, is_placeholder
from core import cycles, jobmeta, lifecycle
from pipeline import publish_supabase as ps

FIELDS = (
    "id", "type", "title", "org", "logo", "url", "apply_url",
    "status", "deadline", "opens", "posted_at", "last_deadline", "next_cycle",
    "eligibility", "level", "skills",
    "location", "country", "workplace",
    "funding", "funding_amount", "currency", "duration", "cost_to_apply",
    "proof", "last_checked",
)
REQUIRED = ("id", "type", "title", "org", "url", "proof", "last_checked")

TEXT_MAX = 300
_EXTRA_PLACEHOLDERS = {"nill", "nil", "null", "tbd", "not specified", "not_specified"}

# programme `category` -> standard type
_PROGRAMME_TYPES = {
    "fellowship": "fellowship", "scholarship": "scholarship", "grant": "grant",
    "research": "research", "open-source-programmes": "open_source",
    "startup-founder": "startup", "community": "community",
}
_OPPORTUNITY_TYPES = {
    "fellowship": "fellowship", "scholarship": "scholarship", "grant": "grant",
    "research": "research", "open_source_programme": "open_source",
    "startup": "startup", "community": "community",
}

# Country name / region label -> ISO 3166-1 alpha-2 (only unambiguous names).
_COUNTRIES = {
    "india": "IN", "united states": "US", "usa": "US", "us": "US", "united states of america": "US",
    "united kingdom": "GB", "uk": "GB", "canada": "CA", "germany": "DE", "france": "FR",
    "australia": "AU", "singapore": "SG", "ireland": "IE", "netherlands": "NL", "japan": "JP",
    "switzerland": "CH", "spain": "ES", "italy": "IT", "brazil": "BR", "mexico": "MX",
    "china": "CN", "israel": "IL", "sweden": "SE", "norway": "NO", "denmark": "DK",
    "finland": "FI", "poland": "PL", "south africa": "ZA", "nigeria": "NG", "kenya": "KE",
    "united arab emirates": "AE", "uae": "AE", "new zealand": "NZ", "south korea": "KR",
    "portugal": "PT", "belgium": "BE", "austria": "AT", "indonesia": "ID", "philippines": "PH",
    "pakistan": "PK", "bangladesh": "BD", "sri lanka": "LK", "nepal": "NP", "egypt": "EG",
}
_BUCKET_COUNTRY = {"us_located": "US", "us_remote": "US", "india_located": "IN", "india_remote": "IN"}

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_PHONE_RE = re.compile(r"\+?\d[\d\s().-]{7,}\d")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")
_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")


# --------------------------------------------------------------------------- #
# Generic helpers
# --------------------------------------------------------------------------- #
def _phone_sub(m: "re.Match") -> str:
    digits = sum(c.isdigit() for c in m.group(0))
    return "" if digits >= 9 and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", m.group(0)) else m.group(0)


def scrub(value: Any, limit: int = TEXT_MAX) -> Optional[str]:
    """Clean text: collapse whitespace, drop emails/phones and placeholders, cap length."""
    if value is None or isinstance(value, (dict, list, bool)):
        return None
    text = re.sub(r"\s+", " ", str(value)).strip()
    text = _EMAIL_RE.sub("", text)
    text = _PHONE_RE.sub(_phone_sub, text)
    text = re.sub(r"\s{2,}", " ", text).strip(" ,;")
    if not text or text.casefold() in ps.HACKATHON_PLACEHOLDERS or text.casefold() in _EXTRA_PLACEHOLDERS:
        return None
    return text[:limit].rstrip()


def to_date(value: Any) -> Optional[str]:
    """YYYY-MM-DD from an ISO date/datetime string, else None."""
    if isinstance(value, str) and _DATE_RE.match(value.strip()):
        return value.strip()[:10]
    iso = jobmeta.to_iso(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None
    return iso[:10] if iso else None


def _first(*vals):
    return ps._first(*vals)


def _number(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    return None


def _currency(value: Any) -> Optional[str]:
    v = str(value or "").strip().upper()
    return v if _CURRENCY_RE.match(v) else None


def real_org(name: Any) -> Optional[str]:
    """Organisation name, or None when empty/placeholder/hostname/aggregator."""
    text = scrub(name, 120)
    if not text or not jobmeta.real_company(text):
        return None
    return text


def clean_logo(url: Any) -> Optional[str]:
    """Logo URL unless it is hosted by a job board / aggregator."""
    if not isinstance(url, str) or not url.startswith(("http://", "https://")):
        return None
    host = (jobmeta.domain_from_url(url) or "").lower()
    if any(host == h or host.endswith("." + h) for h in jobmeta._AGGREGATOR_LOGO_HOSTS):
        return None
    return url


def _country(*texts: Any) -> Optional[str]:
    for text in texts:
        if not isinstance(text, str):
            continue
        key = text.split(",")[-1].strip().casefold()
        if key in _COUNTRIES:
            return _COUNTRIES[key]
    return None


def _workplace(*values: Any) -> Optional[str]:
    for v in values:
        if v in (None, "", False):
            continue
        s = str(v).lower().replace("_", "-")
        if "in-person" in s or "onsite" in s or "on-site" in s:
            return "onsite"
        found = jobmeta.norm_workplace(v)
        if found:
            return found
    return None


_LEVEL_ORDER = ("high_school", "undergrad", "grad", "early_career")


def _one_level(raw: Any) -> Optional[str]:
    s = str(raw or "").lower().replace("_", " ").replace("-", " ")
    if "high school" in s or s == "school":
        return "high_school"
    if "undergrad" in s or "bachelor" in s or s == "student":
        return "undergrad"
    if any(w in s for w in ("graduate", "master", "phd", "doctor", "postdoc")):
        return "grad"
    if any(w in s for w in ("early career", "professional", "entry")):
        return "early_career"
    return None


def _level_of(values: Any) -> List[str]:
    """Every recognisable level in a programme's ``levels`` (a programme can
    accept several, e.g. undergrad + grad), in a fixed order."""
    found = {_one_level(v) for v in (values if isinstance(values, list) else [values])}
    return [lv for lv in _LEVEL_ORDER if lv in found]


def _evidence_proof(row: dict, url: Optional[str]) -> Dict[str, Any]:
    """Stored evidence quote+url (status/deadline first), else only the url."""
    ev = row.get("official_evidence")
    if isinstance(ev, dict):
        keys = ["status", "programme_status", "deadline", "application", "official_page"]
        ordered = [ev[k] for k in keys if k in ev] + [v for k, v in ev.items() if k not in keys]
        for item in ordered:
            if isinstance(item, dict) and scrub(item.get("quote")):
                return {"quote": scrub(item["quote"]), "url": item.get("url") or url}
        for k, v in ev.items():  # flat evidence (hackathons): dates text
            if k.endswith("dates") and scrub(v):
                return {"quote": scrub(v), "url": url}
    return {"quote": None, "url": url}


def _list(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    return [s for s in (scrub(v, 60) for v in value) if s]


def _eligibility(row: dict, level: List[str]) -> Dict[str, Any]:
    other = [scrub(row.get("eligibility"))]
    if row.get("gender"):
        other.append("Gender: {}".format(scrub(row["gender"], 40)))
    if row.get("citizenship"):
        other.append("Citizenship: {}".format(scrub(row["citizenship"], 60)))
    other = [o for o in other if o]
    return {
        "countries": [],
        "age": scrub(row.get("age_limit"), 60),
        "level": level,
        "other": scrub("; ".join(other)) if other else None,
    }


# --------------------------------------------------------------------------- #
# Per-family mapping
# --------------------------------------------------------------------------- #
def _type_of(row: dict) -> Optional[str]:
    t = ps.record_type(row)
    if t == "contribution":
        return "open_source"
    if t == "programme":
        return _PROGRAMME_TYPES.get(row.get("category")) or _OPPORTUNITY_TYPES.get(row.get("opportunity_type"))
    return t if t in ("job", "internship", "hackathon") else None


def _job_level(row: dict) -> List[str]:
    lvl = row.get("level")
    if lvl in ("junior", "entry", "new_grad"):
        return ["early_career"]
    if lvl == "intern" and row.get("enrolled_required") is True:
        return ["undergrad"]
    return []


def map_job(row: dict) -> Dict[str, Any]:
    """Jobs and internships (ATS boards, Unstop/internship lists)."""
    url = row.get("url")
    title = scrub(row.get("title"), 200)
    org = real_org(_first(row.get("company_display_name"), row.get("company_name")))
    logo = clean_logo(_first(row.get("logo_url"), jobmeta.favicon_logo(row.get("company_domain"))))
    amount = _number(_first(row.get("salary_min"), row.get("salary_max")))
    return {
        "org": org, "logo": logo, "url": url, "apply_url": url,
        "opens": to_date(row.get("registration_start")),
        "posted_at": to_date(_first(row.get("posted_at"), jobmeta.to_iso(row.get("posted_on")))),
        "level": _job_level(row),
        "skills": _list(row.get("skills")),
        "location": scrub(row.get("location"), 120),
        "country": _BUCKET_COUNTRY.get(row.get("location_bucket")) or _country(row.get("location")),
        "workplace": _workplace(row.get("workplace")),
        "funding": scrub(_first(row.get("salary_text"), row.get("funding")), 120),
        "funding_amount": amount, "currency": _currency(row.get("salary_currency")) if amount is not None else None,
        "proof": {"quote": title, "url": url},
    }


def map_programme(row: dict) -> Dict[str, Any]:
    """Fellowships, scholarships, grants, research, startup, community, open-source programmes."""
    url = _first(row.get("official_url"), row.get("url"), row.get("application_url"))
    amount = _number(_first(row.get("funding_amount"), row.get("funding_amount_usd")))
    currency = _currency(row.get("funding_currency")) or (
        "USD" if amount is not None and row.get("funding_amount") is None else None)
    today = date.today()
    own_last = to_date(row.get("last_deadline"))
    if not own_last:
        past = [c["deadline"] for c in (row.get("cycles") or [])
                if isinstance(c, dict) and to_date(c.get("deadline")) and c["deadline"] < today.isoformat()]
        own_last = max(past) if past else None
    next_cycle = scrub(row.get("next_cycle_hint"), 120) or scrub(
        cycles.next_cycle_text(cycles.predict_next(row, today)), 120)
    return {
        "org": real_org(ps._display_company(row)),
        "logo": clean_logo(row.get("logo_url")),
        "url": url, "apply_url": _first(row.get("application_url"), url),
        "opens": to_date(row.get("opening_date")),
        "last_deadline": own_last,
        "next_cycle": next_cycle,
        "level": _level_of(row.get("levels")),
        "location": scrub(clean_location(row.get("location")), 120),
        "country": _country(clean_location(row.get("location")), row.get("region")),
        "workplace": _workplace(row.get("mode")),
        "funding": scrub(row.get("funding"), 120),
        "funding_amount": amount, "currency": currency,
        "duration": scrub(row.get("duration"), 60),
        "proof": _evidence_proof(row, url),
    }


def map_hackathon(row: dict) -> Dict[str, Any]:
    url = _first(row.get("official_url"), row.get("application_url"))
    pool = _number(row.get("prize_pool_usd"))
    return {
        "org": real_org(row.get("organizer")),
        "logo": clean_logo(row.get("logo_url")),
        "url": url, "apply_url": _first(row.get("application_url"), url),
        "opens": to_date(row.get("registration_start")),
        "skills": _list(row.get("skills")),
        "location": scrub(row.get("location"), 120),
        "country": _country(row.get("location")),
        "workplace": _workplace(row.get("mode"), "remote" if row.get("is_online") is True else None),
        "funding": scrub(_first(row.get("funding"), row.get("top_prize")), 120),
        "funding_amount": pool, "currency": "USD" if pool is not None else None,
        "proof": _evidence_proof(row, url),
    }


def map_contribution(row: dict) -> Dict[str, Any]:
    url = _first(row.get("official_url"), row.get("application_url"))
    return {
        "org": real_org(row.get("organizer")),
        "logo": clean_logo(row.get("logo_url")),
        "url": url, "apply_url": _first(row.get("application_url"), url),
        "posted_at": to_date(_first(row.get("created_at"), row.get("posted_on"))),
        "skills": _list([row.get("language")] if row.get("language") else []),
        "workplace": _workplace(row.get("mode")),
        "proof": _evidence_proof(row, url),
    }


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
def to_standard(row: dict) -> Dict[str, Any]:
    t = ps.record_type(row)
    if t == "programme":
        part = map_programme(row)
    elif t == "hackathon":
        part = map_hackathon(row)
    elif t == "contribution":
        part = map_contribution(row)
    else:
        part = map_job(row)

    title = scrub(ps._display_title(row, t) or row.get("repo"), 200)
    out: Dict[str, Any] = {k: None for k in FIELDS}
    out["skills"] = []
    out["level"] = []
    out["eligibility"] = {"countries": [], "age": None, "level": None, "other": None}
    out["proof"] = {"quote": None, "url": None}
    out.update(part)
    out["id"] = ps.stable_id(row)
    out["type"] = _type_of(row)
    out["title"] = title
    out["status"] = row.get("lifecycle") or lifecycle.infer(row)
    out["deadline"] = to_date(_first(row.get("deadline"), row.get("registration_deadline")))
    out["eligibility"] = _eligibility(row, out["level"])
    out["last_checked"] = _first(row.get("last_checked_at"), row.get("last_seen"), row.get("checked_at"))
    return {k: out[k] for k in FIELDS}
