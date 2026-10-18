"""Collect hackathon opportunities from official public sources."""

from __future__ import annotations

import argparse
import html as html_module
import json
import os
import re
import socket
import tempfile
import time
from datetime import date, datetime, timezone
from html.parser import HTMLParser
from urllib import error, request
from urllib.parse import urlencode, urljoin, urlsplit, urlunsplit

from core import robots
from core.paths import OPPORTUNITIES_PATH


USER_AGENT = "Mozilla/5.0 (compatible; OpportunityRadarBot/1.0; +https://opportunity-radar.example)"
RECONFIRM_WINDOW_DAYS = 7


def _stale_days():
    try:
        return int(os.environ.get("XLAKE_HACKATHON_STALE_DAYS", "14"))
    except ValueError:
        return 14

DEVPOST_MAX_PAGES = 30
UNSTOP_MAX_PAGES = 30
HOST_DELAY = 1.5
DEVPOST_API_URL = "https://devpost.com/api/hackathons"
UNSTOP_API_URL = "https://unstop.com/api/public/opportunity/search-result?opportunity=hackathons&per_page=15"

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def _http_headers():
    return {"User-Agent": USER_AGENT, "Accept": "application/json, text/html;q=0.9, */*;q=0.8"}


def _http_json(url):
    try:
        req = request.Request(url, headers=_http_headers())
        with request.urlopen(req, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception:
        return None


def _http_text(url):
    try:
        req = request.Request(url, headers=_http_headers())
        with request.urlopen(req, timeout=20) as response:
            return response.read().decode("utf-8", errors="replace")
    except Exception:
        return None


def _iso_date(dt_or_isostring):
    if isinstance(dt_or_isostring, datetime):
        return dt_or_isostring.date().isoformat()
    if isinstance(dt_or_isostring, date):
        return dt_or_isostring.isoformat()
    if not isinstance(dt_or_isostring, str):
        return None
    value = dt_or_isostring.strip()
    match = re.match(r"^(\d{4}-\d{2}-\d{2})", value)
    if not match:
        return None
    try:
        date.fromisoformat(match.group(1))
    except ValueError:
        return None
    return match.group(1)


def _parse_month_day(value, inherited_month=None):
    value = re.sub(r"\s+", " ", value.strip())
    match = re.fullmatch(r"([A-Za-z]{3})\s+(\d{1,2})(?:,\s*(\d{4}))?", value)
    if match:
        month = _MONTHS.get(match.group(1).lower())
        if month is None:
            return None
        return month, int(match.group(2)), int(match.group(3)) if match.group(3) else None
    match = re.fullmatch(r"(\d{1,2})(?:,\s*(\d{4}))", value)
    if match and inherited_month is not None:
        return inherited_month, int(match.group(1)), int(match.group(2))
    return None


def _make_iso(month, day_number, year):
    if month is None or day_number is None or year is None:
        return None
    try:
        return date(year, month, day_number).isoformat()
    except ValueError:
        return None


def parse_devpost_dates(text):
    if not isinstance(text, str) or not text.strip():
        return None, None
    value = re.sub(r"\s+", " ", text.strip())
    years = re.findall(r"\b(\d{4})\b", value)
    default_year = int(years[-1]) if years else None
    if " - " not in value:
        parsed = _parse_month_day(value)
        if parsed is None:
            return None, None
        month, day_number, year = parsed
        iso = _make_iso(month, day_number, year or default_year)
        return (iso, iso) if iso else (None, None)

    left_text, right_text = value.split(" - ", 1)
    left = _parse_month_day(left_text)
    if left is None:
        return None, None
    right = _parse_month_day(right_text, inherited_month=left[0])
    if right is None:
        return None, None
    left_month, left_day, left_year = left
    right_month, right_day, right_year = right
    if left_year is None:
        left_year = default_year
    if right_year is None:
        right_year = default_year
    # In a range such as "Dec 15 - Jan 20, 2026", the only trailing year is
    # the end year and the range started in the preceding calendar year.
    if (
        left_year is not None
        and right_year is not None
        and left_month > right_month
        and not re.search(r"\b\d{4}\b", left_text)
        and len(years) == 1
    ):
        left_year = right_year - 1
    start = _make_iso(left_month, left_day, left_year)
    end = _make_iso(right_month, right_day, right_year)
    return (start, end) if start and end else (None, None)


def _strip_utm(url):
    if not isinstance(url, str):
        return url
    parts = urlsplit(url)
    if not parts.query:
        return url
    kept = []
    for component in parts.query.split("&"):
        key = component.split("=", 1)[0]
        if not key.lower().startswith("utm_"):
            kept.append(component)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "&".join(kept), parts.fragment))


def _is_online(location_text):
    value = str(location_text or "").lower()
    return any(word in value for word in ("online", "digital", "virtual", "remote", "everywhere", "worldwide"))


def _normalize_mlh_location(location):
    if location is None:
        return None
    value = re.sub(r"\s+", " ", str(location)).strip()
    value = re.sub(r"\s+,", ",", value)
    return value or None


def _mlh_format_from_attrs(attrs):
    for key in ("format", "data-format", "event-format", "data-event-format"):
        if attrs.get(key):
            return attrs[key]
    return None


def _mlh_is_digital(event):
    value = str(event.get("format") or "").strip().casefold()
    return value in {"digital", "online", "virtual"} or "onlineeventattendancemode" in value


DESCRIPTION_MAX = 300
ENRICH_LIMIT = int(os.environ.get("XLAKE_HACKATHON_ENRICH_LIMIT", "300"))
ENRICH_DELAY = 1.0
CACHED_KEYS = ("description", "eligibility", "logo_url", "organizer_domain", "page_enriched")

_EU = set("AL AD AT BY BE BA BG HR CY CZ DK EE FI FR DE GR HU IS IE IT XK LV LI LT LU MT MD MC ME NL MK NO PL PT RO RU SM RS SK SI ES SE CH UA GB VA".split())
_ASIA = set("AF AM AZ BH BD BT BN KH CN GE ID IR IQ IL JP JO KZ KW KG LA LB MY MV MN MM NP KP OM PK PS PH QA SA SG KR LK SY TW TJ TH TL TR TM AE UZ VN YE HK".split())
_AFRICA = set("DZ AO BJ BW BF BI CM CV CF TD KM CG CD CI DJ EG GQ ER SZ ET GA GM GH GN GW KE LS LR LY MG MW ML MR MU MA MZ NA NE NG RW ST SN SC SL SO ZA SS SD TZ TG TN UG ZM ZW".split())
_LATAM = set("AR BO BR CL CO CR CU DO EC SV GT HN MX NI PA PY PE UY VE PR JM TT".split())
_OCEANIA = set("AU NZ FJ PG WS TO VU".split())
_US_STATES = set("AL AK AZ AR CA CO CT DE FL GA HI ID IL IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC".split())
_COUNTRY_NAMES = {
    "united states": "US", "united states of america": "US", "usa": "US", "u.s.": "US", "u.s.a.": "US",
    "india": "IN", "united kingdom": "GB", "uk": "GB", "england": "GB", "scotland": "GB", "germany": "DE",
    "france": "FR", "spain": "ES", "italy": "IT", "netherlands": "NL", "portugal": "PT", "ireland": "IE",
    "poland": "PL", "sweden": "SE", "norway": "NO", "denmark": "DK", "finland": "FI", "switzerland": "CH",
    "austria": "AT", "belgium": "BE", "greece": "GR", "romania": "RO", "ukraine": "UA", "czechia": "CZ",
    "czech republic": "CZ", "hungary": "HU", "turkey": "TR", "canada": "CA", "mexico": "MX", "brazil": "BR",
    "argentina": "AR", "colombia": "CO", "chile": "CL", "australia": "AU", "new zealand": "NZ", "china": "CN",
    "japan": "JP", "singapore": "SG", "south korea": "KR", "indonesia": "ID", "malaysia": "MY",
    "pakistan": "PK", "bangladesh": "BD", "sri lanka": "LK", "nepal": "NP", "philippines": "PH",
    "vietnam": "VN", "thailand": "TH", "united arab emirates": "AE", "uae": "AE", "saudi arabia": "SA",
    "israel": "IL", "egypt": "EG", "nigeria": "NG", "kenya": "KE", "south africa": "ZA", "ghana": "GH",
    "morocco": "MA", "ethiopia": "ET", "estonia": "EE", "lithuania": "LT", "latvia": "LV", "croatia": "HR",
    "serbia": "RS", "bulgaria": "BG", "slovakia": "SK", "slovenia": "SI", "iceland": "IS", "luxembourg": "LU",
}


def region_for(country=None, location=None, online=False):
    """Coarse region from an ISO country code/name, else the trailing token of a location string."""
    code = None
    if isinstance(country, str) and country.strip():
        value = country.strip()
        code = value.upper() if len(value) == 2 else _COUNTRY_NAMES.get(value.casefold())
    if code is None and isinstance(location, str) and location.strip() and not _is_online(location):
        parts = [part.strip() for part in location.split(",") if part.strip()]
        tail = parts[-1] if parts else ""
        if tail.casefold() in _COUNTRY_NAMES:
            code = _COUNTRY_NAMES[tail.casefold()]
        elif len(parts) > 1 and len(tail) == 2 and tail.isalpha():
            tail = tail.upper()
            code = "IN" if tail == "IN" else ("US" if tail in _US_STATES else tail)
    if online:
        return "Global/Online"
    if code is None:
        return None
    if code == "US":
        return "US"
    if code == "IN":
        return "India"
    if code == "CA":
        return "Canada"
    for names, label in ((_EU, "Europe"), (_ASIA, "Asia"), (_AFRICA, "Africa"), (_LATAM, "Latin America"), (_OCEANIA, "Oceania")):
        if code in names:
            return label
    return None


def _mode(online, text=None):
    value = str(text or "").casefold()
    if "hybrid" in value or "mixed" in value:
        return "hybrid"
    if online:
        return "online"
    return "in-person" if value else None


def _abs_https(url):
    if not isinstance(url, str) or not url.strip():
        return None
    url = url.strip()
    if url.startswith("//"):
        url = "https:" + url
    elif url.startswith("http://"):
        url = "https://" + url[len("http://"):]
    return url if _usable_url(url) else None


def _domain(url):
    host = urlsplit(url).netloc.lower() if isinstance(url, str) else ""
    host = host.split("@")[-1].split(":")[0]
    return (host[4:] if host.startswith("www.") else host) or None


def clean_description(value, limit=DESCRIPTION_MAX):
    """Strip HTML, collapse whitespace, keep at most two sentences within ``limit`` characters."""
    text = _plain_text(value)
    if not text:
        return None
    sentences = re.findall(r"[^.!?]+[.!?]+(?=\s|$)|[^.!?]+$", text)
    if len(sentences) > 2:
        text = " ".join(part.strip() for part in sentences[:2])
    if len(text) <= limit:
        return text
    cut = text[:limit]
    end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
    if end >= limit * 0.4:
        return cut[:end + 1].strip()
    if " " not in cut:
        return cut
    return cut[:cut.rfind(" ")].rstrip(" ,;:-") + "..."


def compute_status(start, end, deadline, today, fallback=None):
    """open/upcoming/ended from ISO dates; ended only when every known end/deadline date is past."""
    today_iso = today.isoformat()
    ends = [d for d in (deadline, end) if d]
    if ends and max(ends) < today_iso:
        return "ended"
    if start and start > today_iso:
        return "upcoming"
    if not start and not ends and str(fallback or "").casefold() == "upcoming":
        return "upcoming"
    return "open"


def _prize_funding(prize):
    """'$10,000' -> '$10,000 in prizes'; None when there is no positive amount."""
    if not prize or not re.search(r"[1-9]", prize):
        return None
    return prize if "prize" in prize.casefold() else prize + " in prizes"


def _devpost_prize(value):
    if not isinstance(value, str):
        return None
    text = _plain_text(re.sub(r"<[^>]*>", "", value))
    return text if text and re.search(r"[1-9]", text) else None


def parse_time_left(text, today):
    """Exact-unit 'N days/hours/minutes left' -> ISO date; months/years are too coarse to use."""
    match = re.search(r"(\d+)\s+(day|hour|minute)s?\s+left", str(text or ""), re.I)
    if not match:
        return None
    if match.group(2).lower() != "day":
        return today.isoformat()
    return date.fromordinal(today.toordinal() + int(match.group(1))).isoformat()



def build_row(
    source,
    *,
    title,
    official_url,
    organizer=None,
    location=None,
    start_date=None,
    end_date=None,
    registration_deadline=None,
    prize=None,
    tags=None,
    eligibility=None,
    open_state=None,
    source_mechanism,
    evidence,
    checked_at,
    description=None,
    funding=None,
    logo_url=None,
    organizer_domain=None,
    region=None,
    country=None,
    mode=None,
    participants=None,
    deadline_basis=None,
):
    is_online = _is_online(location or "")
    tag_list = list(tags or [])
    mode_text = mode if mode is not None else location
    row_mode = _mode(is_online, mode_text)
    today = _checked_date(checked_at)
    return {
        "record_type": "hackathon",
        "category": "hackathons",
        "opportunity_type": "hackathon",
        "hackathon_id": official_url,
        "title": title,
        "organizer": organizer,
        "source": source,
        "official_url": official_url,
        "application_url": official_url,
        "location": location,
        "is_online": is_online,
        "start_date": start_date,
        "end_date": end_date,
        "registration_deadline": registration_deadline,
        "deadline": registration_deadline,
        "deadline_basis": deadline_basis if registration_deadline else None,
        "prize": prize,
        "funding": funding,
        "description": clean_description(description),
        "logo_url": _abs_https(logo_url),
        "organizer_domain": organizer_domain,
        "region": region if region is not None else region_for(country, location, is_online),
        "mode": row_mode,
        "themes": tag_list,
        "participants": participants if isinstance(participants, int) and participants > 0 else None,
        "tags": tag_list,
        "eligibility": eligibility,
        "status": compute_status(start_date, end_date, registration_deadline, today, open_state),
        "official_evidence": evidence,
        "source_confirmation": "official_source",
        "source_mechanism": source_mechanism,
        "last_checked_at": checked_at,
    }


def _usable_url(value):
    return isinstance(value, str) and urlsplit(value).scheme.lower() in ("http", "https") and bool(urlsplit(value).netloc)


def _plain_text(value):
    if value is None:
        return None
    if not isinstance(value, str):
        value = str(value)
    value = html_module.unescape(re.sub(r"<[^>]*>", " ", value))
    value = re.sub(r"\s+", " ", value).strip()
    return value or None


def _checked_date(checked_at):
    if isinstance(checked_at, datetime):
        return checked_at.date()
    if isinstance(checked_at, date):
        return checked_at
    if isinstance(checked_at, str):
        parsed = checked_at.replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(parsed).date()
        except ValueError:
            pass
    return datetime.now(timezone.utc).date()


def _devpost_items(raw_list):
    if isinstance(raw_list, dict):
        raw_list = raw_list.get("hackathons", [])
    return raw_list if isinstance(raw_list, list) else []


def normalize_devpost(raw_list, checked_at):
    today = _checked_date(checked_at)
    rows = []
    for item in _devpost_items(raw_list):
        if not isinstance(item, dict):
            continue
        official_url = item.get("url")
        if not _usable_url(official_url):
            continue
        submission_dates = item.get("submission_period_dates")
        start, end = parse_devpost_dates(submission_dates)
        if end is None:
            end = parse_time_left(item.get("time_left_to_submission"), today)
        if str(item.get("open_state", "")).casefold() not in ("open", "upcoming"):
            continue
        if end and date.fromisoformat(end) < today:
            continue
        displayed_location = item.get("displayed_location") or {}
        location = displayed_location.get("location") if isinstance(displayed_location, dict) else displayed_location
        themes = item.get("themes") or []
        tags = [theme.get("name") for theme in themes if isinstance(theme, dict) and theme.get("name")]
        prize = _devpost_prize(item.get("prize_amount"))
        invite_only = item.get("invite_only") is True
        rows.append(build_row(
            "devpost",
            title=item.get("title"),
            official_url=official_url,
            organizer=item.get("organization_name"),
            location=location,
            start_date=start,
            end_date=end,
            registration_deadline=end,
            deadline_basis="submission_deadline",
            prize=prize,
            funding=_prize_funding(prize),
            description=item.get("tagline") or item.get("summary"),
            logo_url=item.get("thumbnail_url"),
            participants=item.get("registrations_count"),
            tags=tags,
            eligibility=_plain_text(item.get("eligibility_requirement_invite_only_description"))
            or ("Invite only" if invite_only else None),
            open_state=item.get("open_state"),
            source_mechanism="devpost_api",
            evidence={
                "source": "devpost",
                "source_url": DEVPOST_API_URL,
                "submission_period_dates": submission_dates,
                "time_left_to_submission": item.get("time_left_to_submission"),
            },
            checked_at=checked_at,
        ))
    return rows


class _MlhEventParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.current = None
        self.depth = 0
        self.h4_depth = None
        self.location_depth = None
        self.events = []

    def _finish(self):
        if self.current is not None:
            event = dict(self.current)
            event["name"] = " ".join(event.pop("name_parts")).strip()
            event["location"] = " ".join(event.pop("location_parts")).strip()
            self.events.append(event)
        self.current = None
        self.depth = 0
        self.h4_depth = None
        self.location_depth = None

    def handle_starttag(self, tag, attrs):
        attrs = {key.lower(): value for key, value in attrs}
        if tag.lower() == "a" and self.current is None:
            itemtype = attrs.get("itemtype", "") or ""
            href = attrs.get("href")
            if href and "event" in itemtype.lower():
                self.current = {
                    "href": href,
                    "name_parts": [],
                    "location_parts": [],
                    "startDate": None,
                    "endDate": None,
                    "image": None,
                    "site": None,
                    "country": None,
                    "format": _mlh_format_from_attrs(attrs),
                }
                self.depth = 1
                return
        if self.current is None:
            return
        itemprop = (attrs.get("itemprop") or "").lower()
        if self.current.get("format") is None:
            self.current["format"] = _mlh_format_from_attrs(attrs)
        if itemprop in ("eventattendancemode", "format"):
            self.current["format"] = (
                attrs.get("content")
                or attrs.get("href")
                or attrs.get("value")
                or self.current.get("format")
            )
        if tag.lower() not in {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}:
            self.depth += 1
        if tag.lower() == "h4":
            self.h4_depth = self.depth
        if itemprop == "location":
            self.location_depth = self.depth
        if tag.lower() == "meta" and attrs.get("content"):
            if itemprop == "image" and not self.current.get("image"):
                self.current["image"] = attrs["content"]
            elif itemprop == "url" and not self.current.get("site"):
                self.current["site"] = attrs["content"]
            elif itemprop == "addresscountry":
                self.current["country"] = attrs["content"]
        if (tag.lower() == "img" and not self.current.get("image") and attrs.get("src")
                and "logos/events" in attrs["src"]):
            self.current["image"] = attrs["src"]
        if itemprop in ("startdate", "enddate") and attrs.get("content") is not None:
            self.current["startDate" if itemprop == "startdate" else "endDate"] = attrs["content"]

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_data(self, data):
        if self.current is None:
            return
        text = data.strip()
        if not text:
            return
        if self.h4_depth is not None:
            self.current["name_parts"].append(text)
        if self.location_depth is not None:
            self.current["location_parts"].append(text)

    def handle_endtag(self, tag):
        if self.current is None:
            return
        if tag.lower() == "a" and self.depth == 1:
            self._finish()
            return
        if self.depth == self.h4_depth:
            self.h4_depth = None
        if self.depth == self.location_depth:
            self.location_depth = None
        self.depth -= 1

    def close(self):
        super().close()
        if self.current is not None:
            self._finish()


def normalize_mlh(html, checked_at, source_url="https://mlh.io/seasons/events"):
    if not isinstance(html, str):
        return []
    parser = _MlhEventParser()
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        return []
    today = _checked_date(checked_at)
    rows = []
    for event in parser.events:
        official_url = _strip_utm(event.get("href"))
        title = event.get("name")
        if not _usable_url(official_url) or not title:
            continue
        start_raw, end_raw = event.get("startDate"), event.get("endDate")
        start, end = _iso_date(start_raw), _iso_date(end_raw)
        if end and date.fromisoformat(end) < today:
            continue
        location = _normalize_mlh_location(event.get("location"))
        site = _strip_utm(event.get("site")) if _usable_url(event.get("site")) else None
        attendance = str(event.get("format") or "")
        hybrid = "mixed" in attendance.casefold()
        row = build_row(
            "mlh",
            title=title,
            official_url=official_url,
            location=location,
            start_date=start,
            end_date=end,
            registration_deadline=end,
            deadline_basis="event_end",
            logo_url=event.get("image"),
            organizer_domain=_domain(site) if site else None,
            country=event.get("country"),
            mode="hybrid" if hybrid else None,
            tags=[],
            source_mechanism="mlh_events",
            evidence={"source": "mlh", "source_url": source_url, "start": start_raw, "end": end_raw},
            checked_at=checked_at,
        )
        if _mlh_is_digital(event):
            row["is_online"] = True
            row["mode"] = "online"
            row["region"] = "Global/Online"
        rows.append(row)
    return rows


def _unstop_items(raw_list):
    if isinstance(raw_list, dict):
        data = raw_list.get("data")
        if isinstance(data, dict) and isinstance(data.get("data"), list):
            return data["data"]
        raw_list = raw_list.get("items", data if isinstance(data, list) else [])
    return raw_list if isinstance(raw_list, list) else []


def _unstop_location(item):
    value = item.get("region")
    if value:
        return value
    value = item.get("locations")
    if isinstance(value, list):
        values = []
        for entry in value:
            if isinstance(entry, dict):
                values.append(str(entry.get("name") or entry.get("location") or ""))
            else:
                values.append(str(entry))
        return ", ".join(value for value in values if value) or None
    return value


def _unstop_prize(value):
    if isinstance(value, (str, int, float)):
        return _plain_text(value)
    if isinstance(value, dict):
        for key in ("amount", "prize", "title", "name"):
            if value.get(key) is not None:
                return _plain_text(value[key])
    if isinstance(value, list) and value and len(value) <= 3:
        simple = [_unstop_prize(entry) for entry in value]
        simple = [entry for entry in simple if entry]
        return ", ".join(simple) if simple else None
    return None


_CURRENCY_SYMBOLS = {"INR": "\u20b9", "USD": "$", "EUR": "\u20ac", "GBP": "\u00a3"}
_COURSE_LABELS = {
    "btech": "B.Tech", "mtech": "M.Tech", "integrated": "Integrated", "mcm": "MCM", "diploma": "Diploma",
    "bca": "BCA", "mca": "MCA", "mca1": "MCA", "engothers": "other engineering", "bsc": "B.Sc",
    "msc": "M.Sc", "ba": "BA", "ma": "MA", "bcom": "B.Com", "mcom": "M.Com", "mba": "MBA", "bba": "BBA",
    "pgdm": "PGDM", "llb": "LLB", "llm": "LLM", "mbbs": "MBBS",
}
_STREAM_LABELS = (
    ("engineering", "Engineering students"), ("bSchools", "Business school students"),
    ("arts", "Arts & science students"), ("medicine", "Medical students"), ("law", "Law students"),
)


def _unstop_stream(entries):
    if not isinstance(entries, list) or not entries:
        return None
    courses, years = [], []
    if not any(isinstance(entry, dict) for entry in entries):
        return None
    for entry in entries:
        if isinstance(entry, dict):
            course = str(entry.get("course") or "")
            label = _COURSE_LABELS.get(course.casefold(), course)
            if label and label not in courses:
                courses.append(label)
            for year in entry.get("passoutYear") or []:
                if str(year).casefold() not in ("all", "allcourses") and str(year) not in years:
                    years.append(str(year))
    parts = list(courses[:4])
    if len(courses) > 4:
        parts.append("+{} more".format(len(courses) - 4))
    if not courses:
        parts.append("all courses")
    parts.append("{} batches".format("/".join(years)) if years else "all years")
    return ", ".join(parts)


def unstop_eligibility_text(raw, filters=None):
    """Readable eligibility from Unstop's JSON blob string (plain text passes through)."""
    data = raw
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            data = None
        elif text[0] in "{[":
            try:
                data = json.loads(text)
            except ValueError:
                return _plain_text(text)
        else:
            return _plain_text(text)
    parts = []
    if isinstance(data, dict):
        sectors = [str(item).casefold() for item in data.get("sector") or []]
        for key, label in _STREAM_LABELS:
            detail = _unstop_stream(data.get(key))
            if detail:
                parts.append("{} ({})".format(label, detail))
        if any(word in sectors for word in ("professionals", "professional", "working_professionals")):
            parts.append("Working professionals")
        if any(word in sectors for word in ("startups", "startup")):
            parts.append("Startups")
        if not parts and "students" in sectors:
            all_courses = any("allcourses" in [str(e).casefold() for e in data.get(key) or []]
                              for key, _label in _STREAM_LABELS)
            parts.append("Students (all courses)" if all_courses else "Students")
        if not parts and "all" in sectors:
            parts.append("Everyone")
    if not parts:
        names = [
            str(entry.get("name")) for entry in filters or []
            if isinstance(entry, dict) and entry.get("type") == "eligible" and entry.get("name")
        ]
        parts = ["Everyone"] if names == ["All"] else names
    return "Open to: " + ", ".join(parts) if parts else None


def _unstop_funding(prizes):
    """Total cash across prize tiers -> '\u20b92,500' (single currency only); None if no cash."""
    if not isinstance(prizes, list):
        return None
    totals = {}
    for entry in prizes:
        if isinstance(entry, dict) and isinstance(entry.get("cash"), (int, float)) and entry["cash"] > 0:
            code = str(entry.get("currencyCode") or "INR").upper()
            totals[code] = totals.get(code, 0) + entry["cash"]
    if len(totals) != 1:
        return None
    code, amount = next(iter(totals.items()))
    symbol = _CURRENCY_SYMBOLS.get(code, code + " ")
    return "{}{:,}".format(symbol, int(amount)) if float(amount).is_integer() else "{}{:,.2f}".format(symbol, amount)


def _unstop_location_details(item):
    address = item.get("address_with_country_logo")
    if not isinstance(address, dict):
        return None, None
    country = address.get("country")
    country_name = country.get("name") if isinstance(country, dict) else None
    city_parts = [str(address.get(key)) for key in ("city", "state") if address.get(key)]
    return (", ".join(city_parts + ([country_name] if country_name else [])) or None), country_name


def normalize_unstop(raw_list, checked_at):
    today = _checked_date(checked_at)
    rows = []
    for item in _unstop_items(raw_list):
        if not isinstance(item, dict):
            continue
        official_url = item.get("seo_url")
        if not _usable_url(official_url):
            continue
        status = item.get("status", item.get("opportunity_status"))
        status_active = str(status or "").casefold() in ("upcoming", "live", "open")
        regn_open = item.get("regn_open")
        if isinstance(regn_open, str):
            regn_open = regn_open.strip().casefold() not in ("", "0", "false", "no", "null", "none")
        if not status_active and not bool(regn_open):
            continue
        requirements = item.get("regnRequirements") or {}
        deadline_raw = requirements.get("end_regn_dt")
        registration_deadline = _iso_date(deadline_raw)
        end_date = _iso_date(item.get("end_date"))
        start_date = _iso_date(requirements.get("start_regn_dt"))
        # Retire only when both the registration deadline and the event end are past.
        known = [d for d in (registration_deadline, end_date) if d]
        if known and date.fromisoformat(max(known)) < today:
            continue
        organisation = item.get("organisation") or {}
        organizer = organisation.get("name") if isinstance(organisation, dict) else None
        emails = organisation.get("official_email_domains") if isinstance(organisation, dict) else None
        organizer_domain = None
        if isinstance(emails, str) and emails.strip():
            organizer_domain = emails.split(",")[0].strip().lstrip("@").lower() or None
        logo = item.get("logoUrl2") or item.get("logoUrl") or (
            (organisation.get("logoUrl2") or organisation.get("logoUrl")) if isinstance(organisation, dict) else None)
        tags = item.get("tags") or []
        tags = [tag.get("name") if isinstance(tag, dict) else str(tag) for tag in tags]
        location_text, country = _unstop_location_details(item)
        region_value = str(item.get("region") or "").strip()
        is_offline = region_value.casefold() in ("offline", "in-person", "in person")
        location = location_text if (is_offline and location_text) else _unstop_location(item)
        prizes = item.get("prizes")
        funding_amount = _unstop_funding(prizes)
        prize = funding_amount or _unstop_prize(prizes)
        rows.append(build_row(
            "unstop",
            title=item.get("title"),
            official_url=official_url,
            organizer=organizer,
            location=location,
            start_date=start_date,
            end_date=end_date,
            registration_deadline=registration_deadline,
            deadline_basis="registration_deadline",
            prize=prize,
            funding=_prize_funding(prize),
            description=item.get("details"),
            logo_url=logo,
            organizer_domain=organizer_domain,
            country=country,
            mode=region_value if region_value.casefold() in ("online", "offline", "hybrid", "in-person") else None,
            participants=item.get("registerCount"),
            tags=[tag for tag in tags if tag],
            eligibility=unstop_eligibility_text(requirements.get("eligibility"), item.get("filters")),
            open_state=status,
            source_mechanism="unstop_public_api",
            evidence={
                "source": "unstop",
                "source_url": UNSTOP_API_URL,
                "start_regn_dt": requirements.get("start_regn_dt"),
                "end_regn_dt": deadline_raw,
                "end_date": item.get("end_date"),
            },
            checked_at=checked_at,
        ))
    return rows


def devpost_fetch():
    rows = []
    for page in range(1, DEVPOST_MAX_PAGES + 1):
        if page > 1:
            time.sleep(HOST_DELAY)
        query = urlencode([
            ("status[]", "upcoming"),
            ("status[]", "open"),
            ("order_by", "deadline"),
            ("page", page),
        ])
        payload = _http_json(DEVPOST_API_URL + "?" + query)
        if payload is None:
            return None
        items = payload.get("hackathons", []) if isinstance(payload, dict) else payload
        if not isinstance(items, list):
            return None
        if not items:
            break
        rows.extend(items)
    return rows


def _fetch_year(checked_at):
    if checked_at is None:
        return datetime.now(timezone.utc).year
    if isinstance(checked_at, datetime):
        return checked_at.year
    if isinstance(checked_at, str):
        try:
            return datetime.fromisoformat(checked_at.replace("Z", "+00:00")).year
        except ValueError:
            pass
    return datetime.now(timezone.utc).year


def mlh_fetch(checked_at=None):
    year = _fetch_year(checked_at)
    pages = []
    for season in (year, year + 1):
        season_url = "https://mlh.io/seasons/{}/events".format(season)
        html = _http_text(season_url)
        if html is not None:
            pages.append((html, season_url))
    return pages if pages else None


def unstop_fetch():
    rows = []
    for page in range(1, UNSTOP_MAX_PAGES + 1):
        if page > 1:
            time.sleep(HOST_DELAY)
        payload = _http_json(UNSTOP_API_URL + "&page=" + str(page))
        if payload is None or not isinstance(payload, dict):
            return None
        data = payload.get("data") or {}
        if isinstance(data, list):
            items = data
            current_page, last_page = page, page
        else:
            items = data.get("data", data.get("items", data.get("results", data.get("opportunities", []))))
            current_page = data.get("current_page", page)
            last_page = data.get("last_page", current_page)
        if not isinstance(items, list):
            return None
        rows.extend(items)
        if not items or current_page >= last_page:
            break
    return rows


def _parse_timestamp(value):
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def _last_seen_age_days(value, checked_at):
    if not isinstance(value, str):
        return None
    try:
        seen = date.fromisoformat(value[:10])
    except ValueError:
        return None
    checked = _parse_timestamp(checked_at)
    return (checked.date() - seen).days if checked else None


def _hackathon_sort_key(row):
    return row.get("start_date") or row.get("registration_deadline") or row.get("end_date") or "9999"


def _load_json(path, default):
    if not os.path.exists(path):
        return default
    with open(path) as handle:
        value = json.load(handle)
    if not isinstance(value, type(default)):
        raise ValueError("invalid JSON shape in {}".format(path))
    return value


def _atomic_json(path, value):
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".hackathons-", dir=directory)
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(value, handle, indent=1)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


class _PageMeta(HTMLParser):
    """Collect meta tags, JSON-LD scripts and Devpost's eligibility list from an event page."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.meta = {}
        self.ld = []
        self.eligibility = []
        self._ld_buf = None
        self._eligibility_depth = 0
        self._li = None

    def handle_starttag(self, tag, attrs):
        attrs = {key.lower(): value for key, value in attrs}
        tag = tag.lower()
        if tag == "meta":
            key = (attrs.get("property") or attrs.get("name") or "").lower()
            if key and attrs.get("content") and key not in self.meta:
                self.meta[key] = attrs["content"]
        elif tag == "script" and "ld+json" in (attrs.get("type") or "").lower():
            self._ld_buf = []
        elif tag == "ul" and attrs.get("id") == "eligibility-list":
            self._eligibility_depth = 1
        elif self._eligibility_depth and tag == "ul":
            self._eligibility_depth += 1
        elif self._eligibility_depth and tag == "li" and self._li is None:
            self._li = []

    def handle_data(self, data):
        if self._ld_buf is not None:
            self._ld_buf.append(data)
        elif self._li is not None:
            self._li.append(data)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag == "script" and self._ld_buf is not None:
            try:
                self.ld.append(json.loads("".join(self._ld_buf)))
            except ValueError:
                pass
            self._ld_buf = None
        elif self._eligibility_depth and tag == "li" and self._li is not None:
            text = _plain_text(" ".join(self._li))
            if text:
                self.eligibility.append(text)
            self._li = None
        elif self._eligibility_depth and tag == "ul":
            self._eligibility_depth -= 1


def _ld_events(blocks):
    for block in blocks:
        stack = [block]
        while stack:
            node = stack.pop()
            if isinstance(node, list):
                stack.extend(node)
            elif isinstance(node, dict):
                if "@graph" in node:
                    stack.append(node["@graph"])
                kind = node.get("@type")
                kinds = kind if isinstance(kind, list) else [kind]
                if any(isinstance(k, str) and k.endswith("Event") for k in kinds):
                    yield node


def parse_event_page(html, page_url):
    """Return description / logo_url / eligibility found on an event page (all optional)."""
    if not isinstance(html, str):
        return {}
    parser = _PageMeta()
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        return {}
    description = parser.meta.get("og:description") or parser.meta.get("description")
    image = parser.meta.get("og:image")
    for event in _ld_events(parser.ld):
        description = description or event.get("description")
        node = event.get("image")
        node = node[0] if isinstance(node, list) and node else node
        image = image or (node.get("url") if isinstance(node, dict) else node)
    result = {}
    cleaned = clean_description(description)
    if cleaned:
        result["description"] = cleaned
    if isinstance(image, str) and image.strip():
        absolute = _abs_https(urljoin(page_url, image.strip()))
        if absolute:
            result["logo_url"] = absolute
    if parser.eligibility:
        result["eligibility"] = clean_description("; ".join(parser.eligibility), limit=400)
    return result


def _polite_page_fetch(url):
    allowed, _reason = robots.allowed(url)
    return _http_text(url) if allowed else None


def enrich_rows(rows, cache, fetch=None, limit=ENRICH_LIMIT, today=None, delay=ENRICH_DELAY):
    """Fill description/logo/eligibility from cached lake rows, else from the event page.

    Only rows still missing description or (for Devpost) eligibility are fetched, at most ``limit``
    per run; a failed fetch leaves the row unenriched so the next run retries it.
    """
    fetch = fetch or _polite_page_fetch
    fetched = 0
    for row in rows:
        old = cache.get(row.get("hackathon_id")) or {}
        for key in CACHED_KEYS:
            if not row.get(key) and old.get(key):
                row[key] = old[key]
        if row.get("page_enriched") or row.get("source") == "unstop":
            continue
        if row.get("description") and (row.get("source") != "devpost" or row.get("eligibility")):
            continue
        if fetched >= limit:
            continue
        if fetched:
            time.sleep(delay)
        fetched += 1
        try:
            html = fetch(row["official_url"])
        except Exception:
            html = None
        if html is None:
            continue
        found = parse_event_page(html, row["official_url"])
        for key, value in found.items():
            if not row.get(key):
                row[key] = value
        row["page_enriched"] = (today or datetime.now(timezone.utc).date()).isoformat()
    return fetched


def merge_hackathons(rows_by_id, successful_sources, lake_path=OPPORTUNITIES_PATH, now=None, today=None):
    now = now or datetime.now(timezone.utc).isoformat(timespec="seconds")
    if isinstance(now, datetime):
        now = now.isoformat(timespec="seconds")
    today = today or datetime.now(timezone.utc).date()
    if isinstance(today, datetime):
        today = today.date()
    elif not isinstance(today, date):
        today = date.fromisoformat(str(today))
    lake = _load_json(lake_path, [])
    preserved = [row for row in lake if row.get("record_type") != "hackathon"]
    hackathon_rows = {
        row.get("hackathon_id"): row
        for row in lake
        if row.get("record_type") == "hackathon" and row.get("hackathon_id")
    }
    unkeyed = [
        row for row in lake
        if row.get("record_type") == "hackathon" and not row.get("hackathon_id")
    ]

    incoming = []
    values = rows_by_id.values() if isinstance(rows_by_id, dict) else rows_by_id
    for value in values:
        if isinstance(value, list):
            incoming.extend(value)
        elif isinstance(value, dict):
            incoming.append(value)
    current_ids = set()
    for row in incoming:
        hackathon_id = row.get("hackathon_id") or row.get("official_url")
        if not hackathon_id or hackathon_id in current_ids:
            continue
        current_ids.add(hackathon_id)
        old = hackathon_rows.get(hackathon_id)
        if old is not None:
            first_seen = old.get("first_seen", now)
            old.update(row)
            old.update({
                "first_seen": first_seen,
                "last_seen": now,
                "is_live": True,
                "needs_confirmation": False,
            })
            old.pop("liveness_reason", None)
            old.pop("went_dead_at", None)
        else:
            row = dict(row)
            row.update({
                "first_seen": now,
                "last_seen": now,
                "is_live": True,
                "needs_confirmation": False,
            })
            row.pop("liveness_reason", None)
            hackathon_rows[hackathon_id] = row

    successful_sources = set(successful_sources)
    for row in hackathon_rows.values():
        if row.get("hackathon_id") in current_ids:
            continue
        if row.get("source") in successful_sources:
            row["is_live"] = False
            row["went_dead_at"] = now
            row["needs_confirmation"] = False
            row["liveness_reason"] = "ended_or_removed"
            continue
        age_days = _last_seen_age_days(row.get("last_seen"), now)
        if age_days is not None and age_days > RECONFIRM_WINDOW_DAYS:
            row["is_live"] = False
            row["needs_confirmation"] = True
            row["liveness_reason"] = "not_reconfirmed"

    merged = sorted(unkeyed + list(hackathon_rows.values()), key=_hackathon_sort_key)
    stale_days = _stale_days()
    for row in merged:
        if row.get("record_type", "hackathon") != "hackathon":
            continue
        if row.get("hackathon_id") in current_ids or row.get("liveness_reason") == "ended_or_removed":
            continue
        # Rows no source returned this run: legacy rows (not live, never given a status) and rows
        # whose last check is older than the stale window are retired so they stop being served.
        # Age-out applies even when the row's source failed this run.
        age = _last_seen_age_days(row.get("last_checked_at") or row.get("last_checked") or row.get("last_seen"), now)
        legacy = not row.get("is_live", True) and not row.get("status")
        if legacy or (age is not None and age > stale_days):
            row["is_live"] = False
            row["needs_confirmation"] = False
            row.setdefault("went_dead_at", now)
            row["liveness_reason"] = "stale_legacy" if legacy else "stale_age"
    for row in merged:
        if row.get("record_type", "hackathon") != "hackathon":
            continue
        deadline = _iso_date(row.get("deadline") or row.get("registration_deadline"))
        end = _iso_date(row.get("end_date"))
        if not (deadline or end):
            continue
        status = compute_status(_iso_date(row.get("start_date")), end, deadline, today, row.get("status"))
        row["status"] = status
        if status != "ended" or row.get("liveness_reason") == "ended_or_removed":
            continue
        # Ended events leave the serving set (publish serves is_live OR needs_confirmation, so
        # both must be false for the soft-retire to pick the id up).
        row["is_live"] = False
        row["needs_confirmation"] = False
        row.setdefault("went_dead_at", now)
        row["liveness_reason"] = "event_ended"
    _atomic_json(lake_path, preserved + merged)
    return merged


def collect(
    devpost_fetch=devpost_fetch,
    mlh_fetch=mlh_fetch,
    unstop_fetch=unstop_fetch,
    checked_at=None,
    lake_path=OPPORTUNITIES_PATH,
    page_fetch=None,
    limit=None,
):
    checked_datetime = checked_at or datetime.now(timezone.utc)
    if isinstance(checked_datetime, str):
        checked_datetime = _parse_timestamp(checked_datetime) or datetime.now(timezone.utc)
    checked_at = checked_datetime.isoformat(timespec="seconds") if isinstance(checked_datetime, datetime) else str(checked_datetime)
    rows_by_id = {}
    successful_sources = set()
    counts = {"devpost": 0, "mlh": 0, "unstop": 0}

    try:
        raw = devpost_fetch()
    except Exception:
        raw = None
    if raw is not None:
        rows = normalize_devpost(raw, checked_at)
        counts["devpost"] = len(rows)
        successful_sources.add("devpost")
        for row in rows:
            rows_by_id.setdefault(row["official_url"], row)

    try:
        raw = mlh_fetch(checked_datetime)
    except Exception:
        raw = None
    if raw is not None:
        if isinstance(raw, list):
            pages = raw
        elif isinstance(raw, tuple):
            pages = [raw]
        else:
            pages = [(raw, "https://mlh.io/seasons/events")]
        mlh_rows = {}
        for page in pages:
            if isinstance(page, tuple):
                html, source_url = page
            else:
                html, source_url = page, "https://mlh.io/seasons/events"
            for row in normalize_mlh(html, checked_at, source_url=source_url):
                mlh_rows.setdefault(row["official_url"], row)
        counts["mlh"] = len(mlh_rows)
        successful_sources.add("mlh")
        for row in mlh_rows.values():
            rows_by_id.setdefault(row["official_url"], row)

    try:
        raw = unstop_fetch()
    except Exception:
        raw = None
    if raw is not None:
        rows = normalize_unstop(raw, checked_at)
        counts["unstop"] = len(rows)
        successful_sources.add("unstop")
        for row in rows:
            rows_by_id.setdefault(row["official_url"], row)

    if limit is not None:
        rows_by_id = dict(list(rows_by_id.items())[:limit])
    cache = {
        row.get("hackathon_id"): row for row in _load_json(lake_path, [])
        if row.get("record_type") == "hackathon" and row.get("hackathon_id")
    }
    enrich_rows(
        list(rows_by_id.values()), cache, fetch=page_fetch,
        today=_checked_date(checked_at), delay=ENRICH_DELAY if page_fetch is None else 0,
    )

    merge_hackathons(
        rows_by_id, successful_sources, lake_path=lake_path, now=checked_at,
        today=_checked_date(checked_at),
    )
    return {
        "devpost": counts["devpost"],
        "mlh": counts["mlh"],
        "unstop": counts["unstop"],
        "total_surfaced": len(rows_by_id),
        "sources_ok": sorted(successful_sources),
    }


def list_hackathons(lake_path=OPPORTUNITIES_PATH, online=None, source=None):
    rows = [
        row for row in _load_json(lake_path, [])
        if row.get("record_type") == "hackathon"
        and row.get("is_live", True)
        and str(row.get("status", "")).casefold() in ("open", "upcoming", "live")
    ]
    if online is not None:
        rows = [row for row in rows if row.get("is_online") == online]
    if source is not None:
        rows = [row for row in rows if row.get("source") == source]
    return sorted(rows, key=_hackathon_sort_key)


def _list_cli():
    parser = argparse.ArgumentParser(description="List collected hackathons without collecting")
    parser.add_argument("--list", action="store_true", help="list hackathons from the canonical lake")
    parser.add_argument("--online", action="store_true", default=None)
    parser.add_argument("--source")
    parser.add_argument("--lake", default=OPPORTUNITIES_PATH, help="lake file to read/write (use a copy for dry runs)")
    parser.add_argument("--limit", type=int, default=None, help="cap rows kept per run (dry runs)")
    args = parser.parse_args()
    if not args.list:
        print(json.dumps(collect(lake_path=args.lake, limit=args.limit)))
        return
    rows = list_hackathons(lake_path=args.lake, source=args.source, online=args.online)
    print("{} hackathon(s)".format(len(rows)))
    for row in rows[:15]:
        start = row.get("start_date") or "?"
        end = row.get("end_date") or "?"
        deadline = row.get("registration_deadline") or "?"
        print("{} | {} | {}..{} ({}) | {} | {}".format(
            row.get("title", ""), row.get("source", ""), start, end,
            deadline, row.get("location", "") or "", row.get("official_url", ""),
        ))


if __name__ == "__main__":
    _list_cli()
