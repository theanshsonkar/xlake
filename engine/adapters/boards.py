"""Board listing adapters.

One job: given a platform and a token, return EVERY open posting on that board.

Design rules:
  - Full enumeration, always. A truncated board is worse than a failed board,
    because a truncated board looks like a working one. Every paginating
    platform loops until the API says it is done, not until a fixed page count.
  - Errors are returned, never raised and never swallowed. A board that fails
    must be recorded as failed so the run report can show it.
  - HTTP 200 with zero jobs is NOT an error. It is a real and different state
    from a 404, and conflating the two is the mistake this whole registry
    exists to prevent.
  - One request at a time per host, with a delay THE SITE CHOOSES. The delay
    comes from `robots.crawl_delay`, so Lever's `Crawl-delay: 1` is obeyed
    instead of being overridden by our own 0.3.
  - robots.txt is checked before every request, by `robots.py`. The previous
    version of this file claimed compliance and never fetched a robots.txt.
  - 429 is a hard stop for that host, never something to retry through.
  - Every response is recorded to `raw/` by `cache.py` on first fetch.

No AI anywhere in this file.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from core import cache, robots

# One identity for the whole engine, defined in robots.py so that the name we
# match robots.txt groups against and the name we send in the header cannot
# drift apart.
UA = robots.UA

TIMEOUT = 30

PLATFORMS = (
    "greenhouse",
    "lever",
    "ashby",
    "smartrecruiters",
    "workable",
    "workday",
    "personio",
    "recruitee",
    "keka",
    "successfactors",
    "eightfold",
    "zohorecruit",
    "darwinbox",
    "amazon",
)

# Platforms whose public API robots.txt forbids. Measured live 2026-07-31 —
# see SMARTRECRUITERS_NOTE below. Kept as data so the sweep can report "skipped,
# robots" rather than silently omitting a platform.
ROBOTS_FORBIDDEN = frozenset({"smartrecruiters"})

SMARTRECRUITERS_NOTE = """
api.smartrecruiters.com/robots.txt, fetched 2026-07-31:

    User-agent: LinkedInBot
    Allow: /v1/companies/
    User-agent: *
    Disallow: /

SmartRecruiters opens its postings API to LinkedIn's crawler and to nobody else.
The endpoint still answers 200, which is how the old engine swept ~640 boards
from it while the README claimed robots.txt was respected. It was not.

The adapter is kept because the code is correct and the situation may change,
but `list_board` refuses it unless LAKE_IGNORE_ROBOTS=1 is set by hand. The
public HTML board at jobs.smartrecruiters.com/{token} is NOT disallowed, so
SmartRecruiters is a mechanism-2 (page reader) target, not a mechanism-1 one.
"""


# --------------------------------------------------------------------------- #
# Politeness: serialise requests per host, at the site's own pace
# --------------------------------------------------------------------------- #
_host_locks: Dict[str, threading.Lock] = {}
_host_last: Dict[str, float] = {}
_locks_guard = threading.Lock()


def _host_of(url: str) -> str:
    return urllib.parse.urlsplit(url).netloc.lower()


def _throttle(url: str) -> threading.Lock:
    host = _host_of(url)
    with _locks_guard:
        lock = _host_locks.setdefault(host, threading.Lock())
    lock.acquire()
    # The delay is whatever robots.txt asks for, falling back to our own default.
    # This is the line that makes the politeness claim true.
    delay = robots.crawl_delay(url)
    gap = time.monotonic() - _host_last.get(host, 0.0)
    if gap < delay:
        time.sleep(delay - gap)
    return lock


def _release(url: str, lock: threading.Lock) -> None:
    _host_last[_host_of(url)] = time.monotonic()
    lock.release()


# Kept for callers that still read it (resolve.py imported it). It is now only a
# floor — robots.crawl_delay decides the real number per host.
DELAY_PER_HOST = robots.DEFAULT_DELAY


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #
def _request(
    url: str,
    *,
    body: Optional[bytes] = None,
    want_json: bool = True,
    retries: int = 3,
    user_agent: Optional[str] = None,
) -> Tuple[Optional[int], object, Optional[str]]:
    """Return (http_status, parsed_body_or_text, error_string).

    error_string is None on success. A non-2xx status is an error.

    Order of gates, each of which returns a NAMED error rather than a generic
    failure, because "we chose not to fetch this" and "this is broken" must never
    look the same in a run report:

      1. cache      — a fresh recording is used if reading is enabled
      2. robots     — disallowed paths are not fetched at all
      3. rate limit — a host that answered 429 is left alone until its clock runs
      4. offline    — LAKE_OFFLINE=1 forbids the network entirely

    Retries cover genuinely transient failures (timeouts, resets, 502/503/504).
    429 is NOT among them: it is consent being withdrawn, so the host goes into
    back-off and the call returns immediately.
    """
    # 1. Cache. Reading is opt-in (LAKE_MAX_AGE / LAKE_OFFLINE); a normal sweep
    #    skips this and fetches live so the liveness diff means something.
    hit = cache.get(url, body)
    if hit is not None:
        status, text, _age = hit
        if status and 200 <= status < 300:
            if not want_json:
                return status, text, None
            try:
                return status, json.loads(text), None
            except Exception:  # noqa: BLE001
                return status, None, "non_json_response"
        return status, None, "http_{}".format(status)

    # 2. robots.txt.
    may, why = robots.allowed(url)
    if not may:
        return None, None, why

    # 3. A host that has already said 429 is not asked again this run.
    if robots.is_rate_limited(url):
        return None, None, "rate_limited_backoff"

    # 4. Offline mode: cache or nothing.
    if cache.OFFLINE:
        return None, None, "offline_cache_miss"

    headers = {
        "User-Agent": user_agent or UA,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
    }
    if body is not None:
        headers["Content-Type"] = "application/json"

    last: Tuple[Optional[int], object, Optional[str]] = (None, None, "no_attempt")
    for attempt in range(retries):
        if attempt:
            time.sleep(2.0 * attempt)

        lock = _throttle(url)
        try:
            req = urllib.request.Request(url, data=body, headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                    status = resp.getcode()
                    raw = resp.read().decode("utf-8", errors="replace")
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    # Hard back-off. No retry, no exponential creep back in.
                    # 522 of 1,755 Workable boards returned 429 on one sweep;
                    # retrying through that is hammering a service that has
                    # explicitly asked us to stop.
                    robots.note_rate_limited(
                        url, e.headers.get("Retry-After") if e.headers else None
                    )
                    return e.code, None, "rate_limited_429"
                last = (e.code, None, "http_{}".format(e.code))
                if e.code in (502, 503, 504):
                    continue  # transient, retry
                return last  # 404/422 etc: a real answer, do not retry
            except Exception as e:  # noqa: BLE001
                last = (None, None, "{}: {}".format(type(e).__name__, str(e)[:160]))
                continue  # timeout / reset, retry
        finally:
            _release(url, lock)

        # Record before parsing. A response that fails to parse is exactly the
        # one worth having on disk — the Keka Angular shell that got mistaken for
        # "no public JSON" would have been one file away from being read.
        cache.put(url, status, raw, body)

        if not want_json:
            return status, raw, None
        try:
            return status, json.loads(raw), None
        except Exception:
            return status, None, "non_json_response"

    return last


def strip_html(s: Optional[str], limit: Optional[int] = None) -> str:
    if not s:
        return ""
    import html as _html

    s = _html.unescape(s)
    s = re.sub(r"<[^>]+>", " ", s)
    s = _html.unescape(s)
    s = " ".join(s.split())
    return s[:limit] if limit else s


# --------------------------------------------------------------------------- #
# Result types
# --------------------------------------------------------------------------- #
@dataclass
class Posting:
    platform: str
    token: str
    job_id: str
    title: str
    location: str = ""
    url: str = ""
    posted_on: str = ""
    description: str | None = None
    locations: list | None = None
    company: str = ""

    def key(self) -> str:
        return "{}:{}:{}".format(self.platform, self.token, self.job_id)


@dataclass
class BoardResult:
    platform: str
    token: str
    status: Optional[int] = None
    postings: List[Posting] = field(default_factory=list)
    error: Optional[str] = None
    reported_total: Optional[int] = None  # what the API claims, if it says
    extra: Dict = field(default_factory=dict)  # platform-native fields worth keeping
    _truncated: bool = field(default=False, init=False, repr=False)

    @property
    def ok(self) -> bool:
        return self.error is None

    @property
    def count(self) -> int:
        return len(self.postings)

    @property
    def truncated(self) -> bool:
        """True if the API claimed more postings than we actually collected."""
        return (self._truncated or
                (self.reported_total is not None and
                 self.count < self.reported_total))

    @truncated.setter
    def truncated(self, value: bool) -> None:
        self._truncated = bool(value)


# --------------------------------------------------------------------------- #
# Adapters
# --------------------------------------------------------------------------- #
def _greenhouse(token: str) -> BoardResult:
    r = BoardResult("greenhouse", token)
    url = "https://boards-api.greenhouse.io/v1/boards/{}/jobs?content=true".format(
        urllib.parse.quote(token)
    )
    r.status, data, r.error = _request(url)
    if r.error:
        return r
    jobs = (data or {}).get("jobs")
    if jobs is None:
        r.error = "unexpected_shape"
        return r
    for j in jobs:
        r.postings.append(
            Posting(
                "greenhouse",
                token,
                str(j.get("id")),
                j.get("title") or "",
                (j.get("location") or {}).get("name") or "",
                j.get("absolute_url") or "",
                j.get("updated_at") or "",
                description=strip_html(j.get("content")) or None,
            )
        )
    # Greenhouse returns the whole board in one response and reports meta.total.
    meta = (data or {}).get("meta") or {}
    if isinstance(meta.get("total"), int):
        r.reported_total = meta["total"]
    return r


# --------------------------------------------------------------------------- #
# Unstop public opportunities API
# --------------------------------------------------------------------------- #
UNSTOP_SEARCH_URL = "https://unstop.com/api/public/opportunity/search-result"
UNSTOP_PAGE_SIZE = 20
UNSTOP_MAX_PAGES = 60
UNSTOP_QUERY = {"opportunity": "internships", "oppstatus": "open"}
UNSTOP_MIN_DELAY = 2.0


def _unstop_json_value(value):
    """Decode a JSON-encoded Unstop field without letting bad data escape."""
    if isinstance(value, (dict, list)):
        return value
    if not isinstance(value, str):
        return None
    try:
        return json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None


def _unstop_company(record):
    """Real organizing company from an Unstop record (organisation.name)."""
    if not isinstance(record, dict):
        return ""
    org = record.get("organisation")
    if isinstance(org, dict):
        return str(org.get("name") or "").strip()
    return ""


def _unstop_years(value) -> List[int]:
    """Extract years and inclusive year ranges from Unstop's mixed values."""
    found = []
    if isinstance(value, bool):
        return found
    if isinstance(value, int):
        candidates = [value]
    elif isinstance(value, (list, tuple, set)):
        candidates = []
        for item in value:
            candidates.extend(_unstop_years(item))
    elif isinstance(value, str):
        candidates = []
        # `all` is an explicit absence of a year constraint, not a year.
        for match in re.finditer(r"\b(19\d{2}|20\d{2}|21\d{2})\s*[-–—]\s*"
                                 r"(19\d{2}|20\d{2}|21\d{2})\b", value):
            start, end = int(match.group(1)), int(match.group(2))
            if start <= end and end - start <= 20:
                candidates.extend(range(start, end + 1))
        remainder = re.sub(r"\b(?:19\d{2}|20\d{2}|21\d{2})\s*[-–—]\s*"
                           r"(?:19\d{2}|20\d{2}|21\d{2})\b", "", value)
        candidates.extend(int(x) for x in re.findall(
            r"\b(?:19\d{2}|20\d{2}|21\d{2})\b", remainder))
    else:
        candidates = []
    for year in candidates:
        try:
            year = int(year)
        except (TypeError, ValueError):
            continue
        if 1900 <= year <= 2100 and year not in found:
            found.append(year)
    return found


def _unstop_nested_values(value, keys):
    """Return values under selected keys from a decoded eligibility object."""
    values = []
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).lower() in keys:
                values.append(item)
            values.extend(_unstop_nested_values(item, keys))
    elif isinstance(value, list):
        for item in value:
            values.extend(_unstop_nested_values(item, keys))
    return values


def _unstop_display_degree(value: str) -> str:
    key = re.sub(r"[^a-z0-9]", "", value.lower())
    return {
        "btech": "B.Tech", "bacheloroftechnology": "B.Tech",
        "be": "B.E.", "bachelorofengineering": "B.E.",
        "bca": "BCA", "mtech": "M.Tech", "mca": "MCA",
        "bsc": "B.Sc", "msc": "M.Sc", "mba": "MBA",
        "bba": "BBA", "bcom": "B.Com", "mcom": "M.Com",
        "ba": "BA", "ma": "MA", "phd": "PhD", "diploma": "Diploma",
        "bpharma": "B.Pharm", "mpharma": "M.Pharm", "barch": "B.Arch",
        "bdes": "B.Des", "mdes": "M.Des", "bftech": "B.F.Tech",
    }.get(key, "")


def _unstop_eligibility(record: dict) -> dict:
    """Normalise Unstop eligibility while retaining source wording as evidence."""
    requirements = record.get("regnRequirements") or {}
    if not isinstance(requirements, dict):
        requirements = {}
    raw_eligibility = requirements.get("eligibility")
    eligibility = _unstop_json_value(raw_eligibility)

    year_values = []
    year_evidence = []
    for source, value in (
        ("passoutYear", record.get("passoutYear")),
        ("fresherPassoutYearsSelected", record.get("fresherPassoutYearsSelected")),
        ("studentPassoutYearsSelected", record.get("studentPassoutYearsSelected")),
    ):
        if value is None and isinstance(eligibility, (dict, list)):
            nested = _unstop_nested_values(eligibility, {source.lower()})
            value = nested[0] if nested else None
        if value is not None:
            years = _unstop_years(value)
            for year in years:
                if year not in year_values:
                    year_values.append(year)
            if years or value not in (None, "", [], {}):
                year_evidence.append('{}={}'.format(
                    source, json.dumps(value, ensure_ascii=False, separators=(",", ":"))
                    if not isinstance(value, str) else value))

    degree_values = []
    degree_evidence = []
    for key in ("course", "degree"):
        for value in _unstop_nested_values(eligibility, {key}):
            values = value if isinstance(value, list) else [value]
            for item in values:
                if isinstance(item, dict):
                    item = item.get("name") or item.get("value") or ""
                if not isinstance(item, str) or not item.strip():
                    continue
                shown = _unstop_display_degree(item)
                if shown and shown not in degree_values:
                    degree_values.append(shown)
                degree_evidence.append('{}={}'.format(key, item))

    # Students/final-year signals are explicit eligibility data; `fresher` alone
    # is not silently treated as enrollment.
    enrolled = False
    enrolled_evidence = []
    student_values = _unstop_nested_values(
        eligibility, {"studentpassoutyearsselected", "students", "enrolled", "enrollment"})
    if student_values:
        enrolled = True
        enrolled_evidence.append("student eligibility fields present")
    sectors = _unstop_nested_values(eligibility, {"sector"})
    for sector in sectors:
        values = sector if isinstance(sector, list) else [sector]
        if any(str(x).lower() in {"student", "students", "final_year"} for x in values):
            enrolled = True
            enrolled_evidence.append("sector=" + json.dumps(sector, ensure_ascii=False))

    evidence = {}
    if year_evidence:
        evidence["batch_years"] = "; ".join(year_evidence)
    if degree_evidence:
        evidence["degree"] = "; ".join(degree_evidence)
    if enrolled_evidence:
        evidence["enrolled"] = "; ".join(enrolled_evidence)
    fresher = any(str(x).lower() == "fresher" for x in sectors for x in (
        x if isinstance(x, list) else [x]))
    if fresher:
        evidence["fresher"] = "sector=fresher"

    gates = []
    if year_values:
        gates.append("batch_years")
    if degree_values:
        gates.append("degree")
    if enrolled:
        gates.append("enrolled")
    if fresher:
        gates.append("fresher")
    return {
        "batch_years": sorted(year_values),
        "degree_required": degree_values,
        "enrolled_required": True if enrolled else None,
        "evidence": evidence,
        "gates_found": gates,
        "gates_missing": [x for x in (
            "experience", "fresher", "stage_early", "batch_years", "degree", "enrolled"
        ) if x not in gates],
        "eligibility_raw": raw_eligibility,
        "eligibility_parseable": isinstance(eligibility, (dict, list)),
    }


def _unstop_kind(record: dict) -> Tuple[str, str]:
    """Map only the observed opportunity taxonomy; retain the raw discriminator."""
    subtype = record.get("subtype")
    kind_type = record.get("type")
    path = urllib.parse.urlsplit(str(record.get("public_url") or "")).path.lower()
    candidates = [x for x in (subtype, kind_type) if x not in (None, "")]
    for candidate in candidates:
        raw = str(candidate).strip()
        key = raw.lower().replace("-", "_").replace(" ", "_")
        if key in {"scholarship", "scholarships", "grant", "grants"}:
            return "scholarship", raw
        if key in {"internship", "internships"}:
            return "internship", raw
        if key in {"hackathon", "hackathons", "competition", "competitions",
                   "online_coding_challenge", "coding_challenge"}:
            return "competition", raw
        if key in {"programme", "programmes", "program", "programs", "fellowship",
                   "fellowships", "workshop", "workshops", "webinar", "webinars",
                   "event", "events", "cultural"}:
            return "programme", raw
        if key in {"job", "jobs"}:
            return "job", raw
    if "/scholarship" in path or "/grant" in path:
        return "scholarship", str(subtype or kind_type or "")
    if "/internship" in path:
        return "internship", str(subtype or kind_type or "")
    if "/hackathon" in path or "/competition" in path:
        return "competition", str(subtype or kind_type or "")
    if "/workshop" in path or "/event" in path or "/program" in path:
        return "programme", str(subtype or kind_type or "")
    # Unknown is deliberately closest to a job, never a guessed scholarship.
    return "job", str(subtype if subtype is not None else kind_type or "")


def _unstop_http_url(value) -> str:
    if not isinstance(value, str):
        return ""
    value = value.strip()
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return value
    return ""


def _unstop_location(record: dict, requirements: dict) -> str:
    value = record.get("location")
    if not value:
        value = record.get("locations")
    if isinstance(value, dict):
        value = ", ".join(str(value.get(k) or "") for k in (
            "name", "city", "state", "country") if value.get(k))
    elif isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, dict):
                text = ", ".join(str(item.get(k) or "") for k in (
                    "name", "city", "state", "country") if item.get(k))
            else:
                text = str(item)
            if text:
                parts.append(text)
        value = "; ".join(parts)
    location = str(value or record.get("region") or "").strip()
    allowed = _unstop_json_value(requirements.get("allowed_countries"))
    if isinstance(allowed, str):
        allowed = [allowed]
    if isinstance(allowed, list) and any(str(x).strip().lower() == "india" for x in allowed):
        if not re.search(r"\bindia\b", location, re.I):
            location = (location + ", India").strip(", ")
    work_type = str(requirements.get("work_location_type") or "").lower()
    if "pan_india" in work_type and not re.search(r"\bindia\b", location, re.I):
        location = (location + ", India").strip(", ")
    return location


def _unstop_eligibility_text(eligibility: dict) -> str:
    """A short filter input, never a copied job description."""
    parts = []
    years = eligibility.get("batch_years") or []
    if years:
        parts.append("{}, batch".format(", ".join(str(x) for x in years)))
    parts.extend(eligibility.get("degree_required") or [])
    if eligibility.get("enrolled_required"):
        parts.append("currently enrolled")
    if "fresher" in eligibility.get("gates_found", []):
        parts.append("freshers")
    return "Eligibility: " + "; ".join(parts) if parts else ""


def _unstop_page(data, requested_page: int):
    """Return (records, current_page, per_page, last_page, total)."""
    if not isinstance(data, dict):
        return None
    payload = data.get("data")
    meta = data
    if isinstance(payload, dict):
        meta = payload
        records = (payload.get("data") or payload.get("opportunities") or
                   payload.get("results") or payload.get("items"))
    else:
        records = payload
    if not isinstance(records, list):
        return None
    def integer(name):
        value = data.get(name)
        if value is None and isinstance(payload, dict):
            value = payload.get(name)
        return value if isinstance(value, int) and not isinstance(value, bool) else None
    current = integer("current_page")
    per_page = integer("per_page")
    last_page = integer("last_page")
    total = integer("total")
    if current is None:
        current = requested_page
    return records, current, per_page, last_page, total


def _unstop(token: str) -> BoardResult:
    """Unstop's public opportunity search, paginated by the API's last_page."""
    r = BoardResult("unstop", token)
    # LAKE_LIMIT is an intentional local-test cap. Production (LAKE_LIMIT=0)
    # must read every page or return an error; the cap is recorded explicitly.
    test_limit = int(os.environ.get("LAKE_LIMIT", "0") or 0)
    collected = 0
    page = 1
    latest_last_page = latest_total = None
    requests = 0
    while True:
        # robots.py supplies the site's delay; Unstop has no measured
        # Crawl-delay, so this adapter keeps the project's stricter 2s floor.
        time.sleep(UNSTOP_MIN_DELAY)
        params = urllib.parse.urlencode({**UNSTOP_QUERY,
                                         "page": page,
                                         "per_page": UNSTOP_PAGE_SIZE})
        url = UNSTOP_SEARCH_URL + "?" + params
        status, data, err = _request(url)
        requests += 1
        r.status = status
        if err:
            r.error = "unstop_{}{}".format(
                err, "_partial_at_{}".format(collected) if collected else "")
            r.extra["requests"] = requests
            return r
        parsed = _unstop_page(data, page)
        if parsed is None:
            r.error = "unstop_unexpected_shape{}".format(
                "_partial_at_{}".format(collected) if collected else "")
            r.extra["requests"] = requests
            return r
        records, current, per_page, last_page, total = parsed
        if current != page or per_page != UNSTOP_PAGE_SIZE or last_page is None or total is None:
            r.error = "unstop_pagination_unconfirmed"
            r.extra["requests"] = requests
            return r
        if r.reported_total is None:
            r.reported_total = total
        latest_last_page, latest_total = last_page, total
        if not records and total > collected:
            r.error = "unstop_empty_page_partial_at_{}".format(collected)
            r.extra["requests"] = requests
            return r

        for record in records:
            if not isinstance(record, dict):
                r.error = "unstop_bad_record_partial_at_{}".format(collected)
                r.extra["requests"] = requests
                return r
            kind, raw_kind = _unstop_kind(record)
            requirements = record.get("regnRequirements")
            if not isinstance(requirements, dict):
                requirements = {}
            eligibility = _unstop_eligibility(record)
            official = _unstop_http_url(record.get("web_url"))
            public = (_unstop_http_url(record.get("public_url")) or
                      _unstop_http_url(record.get("seo_url")))
            canonical = official or public
            origin = "official_company_url" if official else "unstop"
            if not canonical:
                # No URL is fabricated when an incomplete record omits both.
                canonical = ""
            deadline = (record.get("end_date") or requirements.get("end_regn_dt") or "")
            location = _unstop_location(record, requirements)
            jid = str(record.get("id") or "")
            if not jid:
                r.error = "unstop_missing_id_partial_at_{}".format(collected)
                r.extra["requests"] = requests
                return r
            description = _unstop_eligibility_text(eligibility)
            posting = Posting(
                "unstop", token, jid, str(record.get("title") or ""), location,
                canonical, str(record.get("approved_date") or record.get("start_date") or ""),
                description=description or None,
                company=_unstop_company(record),
            )
            # These attributes extend the compatibility Posting without changing
            # the return type used by the established adapters.
            posting.kind = kind
            posting.raw_kind = raw_kind
            posting.deadline = str(deadline or "")
            posting.eligibility = eligibility
            posting.url_origin = origin
            posting.official_url = official
            posting.unstop_url = public
            r.postings.append(posting)
            r.extra.setdefault("records", {})[jid] = {
                "kind": kind, "raw_kind": raw_kind,
                "eligibility": eligibility, "deadline": str(deadline or ""),
                "official_url": official, "unstop_url": public,
                "url_origin": origin,
            }
            collected += 1
            if test_limit and collected >= test_limit:
                r.error = "unstop_test_limit_partial_at_{}".format(collected)
                r.extra.update({"requests": requests, "test_limited": True,
                                "pages_read": page})
                return r

        if page >= latest_last_page or page >= UNSTOP_MAX_PAGES:
            if page < latest_last_page:
                r.truncated = True
            r.extra.update({"requests": requests, "pages_read": page,
                            "last_page": latest_last_page,
                            "total": latest_total})
            return r
        if not records:
            r.error = "unstop_short_page_partial_at_{}".format(collected)
            r.extra["requests"] = requests
            return r
        page += 1


def _lever(token: str) -> BoardResult:
    r = BoardResult("lever", token)
    url = "https://api.lever.co/v0/postings/{}?mode=json".format(
        urllib.parse.quote(token)
    )
    r.status, data, r.error = _request(url)
    if r.error:
        return r
    if not isinstance(data, list):
        r.error = "unexpected_shape"
        return r
    for j in data:
        cat = j.get("categories") or {}
        r.postings.append(
            Posting(
                "lever",
                token,
                str(j.get("id") or ""),
                j.get("text") or "",
                cat.get("location") or "",
                j.get("hostedUrl") or j.get("applyUrl") or "",
                str(j.get("createdAt") or ""),
                description=j.get("descriptionPlain") or j.get("description") or None,
            )
        )
    return r


def _ashby(token: str) -> BoardResult:
    r = BoardResult("ashby", token)
    url = "https://api.ashbyhq.com/posting-api/job-board/{}".format(
        urllib.parse.quote(token)
    )
    r.status, data, r.error = _request(url)
    if r.error:
        return r
    jobs = (data or {}).get("jobs")
    if jobs is None:
        r.error = "unexpected_shape"
        return r
    for j in jobs:
        r.postings.append(
            Posting(
                "ashby",
                token,
                str(j.get("id") or ""),
                j.get("title") or "",
                j.get("location") or "",
                j.get("jobUrl") or j.get("applyUrl") or "",
                j.get("publishedAt") or "",
                description=(
                    j.get("descriptionPlain")
                    or (strip_html(j.get("descriptionHtml")) or None)
                ),
            )
        )
    return r


def _smartrecruiters(token: str) -> BoardResult:
    offset, page_size = 0, 100
    while True:
        url = (
            "https://api.smartrecruiters.com/v1/companies/{}/postings"
            "?limit={}&offset={}".format(urllib.parse.quote(token), page_size, offset)
        )
        status, data, err = _request(url)
        r.status = status
        if err:
            r.error = "{}{}".format(
                err, "_partial_at_{}".format(len(r.postings)) if r.postings else ""
            )
            return r
        content = (data or {}).get("content")
        if content is None:
            if not r.postings:
                r.error = "unexpected_shape"
            return r
        if r.reported_total is None and isinstance((data or {}).get("totalFound"), int):
            r.reported_total = data["totalFound"]
        for j in content:
            loc = j.get("location") or {}
            city = loc.get("city") or ""
            country = loc.get("country") or ""
            r.postings.append(
                Posting(
                    "smartrecruiters",
                    token,
                    str(j.get("id") or ""),
                    j.get("name") or "",
                    ", ".join(x for x in (city, country) if x),
                    (j.get("ref") or "")
                    or "https://jobs.smartrecruiters.com/{}/{}".format(
                        token, j.get("id")
                    ),
                    j.get("releasedDate") or "",
                )
            )
        offset += page_size
        if len(content) < page_size:
            return r
        if r.reported_total is not None and offset >= r.reported_total:
            return r
        if offset > 20000:  # runaway guard
            r.error = "pagination_runaway"
            return r


def _workable(token: str) -> BoardResult:
    r = BoardResult("workable", token)
    url = "https://apply.workable.com/api/v1/widget/accounts/{}?details=true".format(
        urllib.parse.quote(token)
    )
    r.status, data, r.error = _request(url)
    if r.error:
        return r
    jobs = (data or {}).get("jobs")
    if jobs is None:
        r.error = "unexpected_shape"
        return r
    for j in jobs:
        bits = [j.get("city") or "", j.get("country") or ""]
        location = ", ".join(x for x in bits if x)
        if not location:
            for entry in (j.get("locations") or []):
                if isinstance(entry, dict) and not entry.get("hidden"):
                    parts = [entry.get("city") or "", entry.get("country") or ""]
                    location = ", ".join(x for x in parts if x)
                    if location:
                        break
        if not location and j.get("telecommuting"):
            location = "Remote"
        r.postings.append(
            Posting(
                "workable",
                token,
                str(j.get("shortcode") or j.get("id") or ""),
                j.get("title") or "",
                location,
                j.get("url") or j.get("application_url") or "",
                j.get("published_on") or "",
            )
        )
    return r


def _workday(token: str) -> BoardResult:
    """Workday CXS. Token is 'host|tenant|site'.

    THE PAGINATION FIX. The previous implementation looped
    `for _page in range(10)` at limit 20, a hard cap of 200 postings. Nvidia
    reports 2,000 and Adobe 839, so five big-company boards were being read at
    10% and reported as complete. This loops until `total` is reached.
    """
    r = BoardResult("workday", token)
    parts = token.split("|")
    host = parts[0]
    tenant = parts[1] if len(parts) > 1 else host.split(".")[0]
    site = parts[2] if len(parts) > 2 else tenant
    url = "https://{}/wday/cxs/{}/{}/jobs".format(host, tenant, site)

    offset, page_size = 0, 20  # Workday caps limit at 20
    while True:
        body = json.dumps(
            {"appliedFacets": {}, "limit": page_size, "offset": offset, "searchText": ""}
        ).encode()
        status, data, err = _request(url, body=body)
        r.status = status
        if err:
            # A failure partway through pagination is NOT a success with fewer
            # jobs. Record it either way, or a half-read board looks complete.
            r.error = "workday_{}{}".format(
                err, "_partial_at_{}".format(len(r.postings)) if r.postings else ""
            )
            return r
        posts = (data or {}).get("jobPostings")
        if posts is None:
            if not r.postings:
                r.error = "unexpected_shape"
            return r
        if r.reported_total is None and isinstance((data or {}).get("total"), int):
            r.reported_total = data["total"]
        for j in posts:
            path = j.get("externalPath") or ""
            bullets = j.get("bulletFields") or []
            r.postings.append(
                Posting(
                    "workday",
                    token,
                    str((bullets[0] if bullets else None) or path.rsplit("/", 1)[-1]),
                    j.get("title") or "",
                    j.get("locationsText") or "",
                    "https://{}/{}{}".format(host, site, path),
                    j.get("postedOn") or "",
                )
            )
        offset += page_size
        if len(posts) < page_size:
            return r
        if r.reported_total is not None and offset >= r.reported_total:
            return r
        if offset > 20000:
            r.error = "pagination_runaway"
            return r


def _personio(token: str) -> BoardResult:
    r = BoardResult("personio", token)
    url = "https://{}.jobs.personio.de/search.json".format(urllib.parse.quote(token))
    r.status, data, r.error = _request(url)
    if r.error:
        return r
    if not isinstance(data, list):
        r.error = "unexpected_shape"
        return r
    for j in data:
        r.postings.append(
            Posting(
                "personio",
                token,
                str(j.get("id") or ""),
                j.get("name") or "",
                j.get("office") or "",
                "https://{}.jobs.personio.de/job/{}".format(token, j.get("id")),
                str(j.get("createdAt") or ""),
            )
        )
    return r


def _recruitee(token: str) -> BoardResult:
    r = BoardResult("recruitee", token)
    url = "https://{}.recruitee.com/api/offers/".format(urllib.parse.quote(token))
    r.status, data, r.error = _request(url)
    if r.error:
        return r
    offers = (data or {}).get("offers")
    if offers is None:
        r.error = "unexpected_shape"
        return r
    for j in offers:
        bits = [j.get("city") or "", j.get("country") or ""]
        r.postings.append(
            Posting(
                "recruitee",
                token,
                str(j.get("id") or ""),
                j.get("title") or "",
                ", ".join(x for x in bits if x),
                j.get("careers_url") or j.get("careers_apply_url") or "",
                j.get("published_at") or "",
            )
        )
    return r


def _keka(token: str) -> BoardResult:
    """Keka (India). Two requests: careers shell -> board GUID -> jobs JSON.

    Keka was recorded in the old docs as "no public JSON". That was wrong. The
    old adapter guessed /careers/api/embedjobs and /api/careers/jobs and got the
    Angular shell back, and the conclusion was written down as impossible. The
    real endpoint has two extra path segments:

        /careers/api/embedjobs/{portalName}/active/{board_guid}

    portalName is "default" unless the company configured one. The response
    includes the FULL job description inline, so unlike Greenhouse this is one
    request for both the listing and the text.

    This is the single best source of India early-career roles found so far.
    """
    r = BoardResult("keka", token)
    host = "https://{}.keka.com".format(urllib.parse.quote(token))

    status, shell, err = _request(host + "/careers/", want_json=False)
    r.status = status
    if err:
        r.error = "shell_{}".format(err)
        return r
    if not isinstance(shell, str):
        r.error = "shell_not_text"
        return r

    # The shell fetches its own content fragment; the GUID is the board id.
    m = re.search(r"/ats/documents/([0-9a-fA-F-]{36})/", shell)
    if not m:
        m = re.search(r"embedjobs/js/([0-9a-fA-F-]{36})", shell)
    if not m:
        m = re.search(r"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
                      r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12})", shell)
    if not m:
        r.error = "no_board_guid"
        return r
    guid = m.group(1)

    data = None
    for portal in ("default", token):
        status, body, err = _request(
            "{}/careers/api/embedjobs/{}/active/{}".format(host, portal, guid)
        )
        r.status = status
        if not err and isinstance(body, list) and body:
            data = body
            break
        if not err and isinstance(body, list):
            data = data if data is not None else []
    if data is None:
        r.error = "jobs_unreadable"
        return r

    for j in data:
        loc = j.get("jobLocations") or j.get("location") or ""
        if isinstance(loc, list):
            bits = []
            for x in loc:
                if isinstance(x, dict):
                    bits += [
                        str(x.get(k) or "")
                        for k in ("name", "city", "state", "country")
                    ]
                else:
                    bits.append(str(x))
            loc = " ".join(b for b in bits if b)
        elif isinstance(loc, dict):
            loc = " ".join(
                str(loc.get(k) or "") for k in ("name", "city", "state", "country")
            )
        jid = str(j.get("id") or "")
        r.postings.append(
            Posting(
                "keka",
                token,
                jid,
                j.get("title") or "",
                str(loc).strip(),
                "{}/careers/jobdetails/{}".format(host, jid),
                str(j.get("createdOn") or j.get("postedOn") or ""),
                description=(
                    strip_html(j.get("description") or j.get("jobDescription")) or None
                ),
            )
        )
    return r


AMAZON_SEARCH_COUNTRIES = frozenset({
    "IND", "USA", "CAN", "GBR", "DEU", "FRA", "ITA", "ESP", "IRL",
    "LUX", "AUS", "SGP",
})
AMAZON_SEARCH_URL = "https://www.amazon.jobs/search.json"


def _amazon(token: str) -> BoardResult:
    """Amazon Jobs search API. Token is ``COUNTRY`` or ``COUNTRY|query``.

    The API's ``hits`` value is mandatory: without it, a partial response must
    be an error rather than a successful-looking board. ``locations`` is kept
    separately while ``location`` remains the compatibility string used by the
    existing filters.

    Known limitation: job 10488368 (SDE I Intern, Amazon University Talent
    Acquisition) is a fully public page but does not appear in search.json under
    any query tried; country=IND with base_query=intern returned only 13 hits.
    Campus and university requisitions therefore still require the Phase 2 URL
    reader and this adapter must not be assumed complete for them.
    """
    r = BoardResult("amazon", token)
    parts = token.split("|", 1)
    country = (parts[0] or "").strip().upper()
    query = parts[1] if len(parts) == 2 else ""
    if country not in AMAZON_SEARCH_COUNTRIES:
        r.error = "invalid_token"
        return r

    def _location_text(value) -> str:
        if isinstance(value, str):
            text = value.strip()
            if text.startswith("{") and text.endswith("}"):
                try:
                    return _location_text(json.loads(text))
                except (TypeError, ValueError):
                    pass
            return text
        if isinstance(value, dict):
            city = value.get("normalizedCityName") or value.get("city")
            state = value.get("normalizedStateName") or value.get("state")
            country_name = value.get("normalizedCountryName") or value.get("country")
            parts = [str(x).strip() for x in (city, state, country_name) if x]
            if parts:
                return ", ".join(parts)
            return str(value.get("normalizedLocation") or value.get("location") or
                       value.get("name") or "").strip()
        if isinstance(value, list):
            return "; ".join(
                text for text in (_location_text(item) for item in value) if text
            )
        return ""

    offset, page_size = 0, 20
    while True:
        params = urllib.parse.urlencode({
            "base_query": query,
            "country": country,
            "result_limit": page_size,
            "offset": offset,
        })
        url = AMAZON_SEARCH_URL + "?" + params
        status, data, err = _request(url)
        r.status = status
        if err:
            r.error = "amazon_{}{}".format(
                err, "_partial_at_{}".format(len(r.postings))
                if r.postings else ""
            )
            return r
        if not isinstance(data, dict):
            r.error = "unexpected_shape"
            return r

        jobs = data.get("jobs")
        total = data.get("hits")
        if not isinstance(jobs, list):
            r.error = "amazon_unexpected_shape{}".format(
                "_partial_at_{}".format(len(r.postings)) if r.postings else ""
            )
            return r
        # `hits` is the API's total count. Never infer completeness from a short
        # page or from the number collected; missing/non-integer totals fail.
        if isinstance(total, bool) or not isinstance(total, int) or total < 0:
            r.error = "amazon_total_unconfirmed{}".format(
                "_partial_at_{}".format(len(r.postings)) if r.postings else ""
            )
            return r
        if r.reported_total is None:
            r.reported_total = total
        elif total != r.reported_total:
            r.error = "amazon_total_changed"
            return r

        if offset + len(jobs) > total:
            r.error = "amazon_total_underreported"
            return r
        for job in jobs:
            if not isinstance(job, dict):
                r.error = "amazon_bad_job{}".format(
                    "_partial_at_{}".format(len(r.postings))
                    if r.postings else ""
                )
                return r
            path = str(job.get("job_path") or "").strip()
            if not path:
                r.error = "amazon_missing_job_path{}".format(
                    "_partial_at_{}".format(len(r.postings))
                    if r.postings else ""
                )
                return r
            public_url = path if path.startswith("http") else (
                "https://www.amazon.jobs/" + path.lstrip("/")
            )
            raw_locations = job.get("locations")
            locations = (
                [_location_text(item) for item in raw_locations]
                if isinstance(raw_locations, list) else None
            )
            location = _location_text(job.get("location"))
            if not location and locations:
                location = _location_text(locations[0])
            r.postings.append(
                Posting(
                    "amazon",
                    token,
                    str(job.get("id_icims") or job.get("id") or ""),
                    job.get("title") or "",
                    location,
                    public_url,
                    job.get("posted_date") or "",
                    description=strip_html(job.get("description")) or None,
                    locations=locations,
                )
            )

        offset += len(jobs)
        if offset >= total:
            return r
        # A short page while the confirmed total says more rows exist is a
        # partial fetch and must never be recorded as success.
        if not jobs or len(jobs) < page_size:
            r.error = "amazon_short_page_partial_at_{}".format(len(r.postings))
            return r
        if offset > 100000:
            r.error = "pagination_runaway"
            return r


# --------------------------------------------------------------------------- #
# Eightfold AI. Where Nvidia is, and nine of the ten adapters above cannot see.
# --------------------------------------------------------------------------- #
# Token format: "tenant|domain", e.g. "nvidia|nvidia.com".
#
# Verified live 2026-07-31. The obvious endpoint is a decoy:
#
#   /api/apply/v2/jobs?domain=nvidia.com   ->  403 {"message": "Not authorized
#                                               for PCSX"}
#   /api/pcsx/search?domain=nvidia.com     ->  200, data.positions, count 2604
#
# The 403 names the API you are supposed to be using. Guessing once and writing
# "Eightfold needs auth" in a doc is exactly how Keka got recorded as having no
# public JSON for a month.
#
# robots.txt on nvidia.eightfold.ai is the same longest-match shape as Keka's,
# and it opens the path we need explicitly:
#
#   Disallow: /
#   Allow: /$        Allow: /careers      Allow: /api/apply
#   Allow: /api/pcsx      <- the one we use
#   Allow: /careerhub/explore/jobs  ...
#
# Fields it gives free, no AI: department (technical classification, like Keka's
# departmentName), postedTs and creationTs as real epochs, locations[] and
# standardizedLocations[] already split into a list rather than Keka's blob, and
# workLocationOption (onsite/remote) which feeds the remote tier directly.
EIGHTFOLD_PAGE = 10  # hard server-side cap; num=50/100/200 all return 10

# Nvidia alone reports 2,604 openings. At 10 per request and a 1s crawl-delay
# that is 261 requests and ~4.5 minutes for ONE board, which does not fit a
# 12-hourly CI budget. The API takes a server-side location filter that cuts
# Nvidia to 212, so the 12h loop filters and the weekly loop takes everything.
# A filtered read is recorded as filtered in `extra`, and reported_total is set
# to the filtered count, so `truncated` keeps meaning "we failed to finish".
EIGHTFOLD_LOCATION = os.environ.get("LAKE_EIGHTFOLD_LOCATION", "").strip()


def _eightfold(token: str) -> BoardResult:
    r = BoardResult("eightfold", token)
    parts = token.split("|")
    tenant = parts[0]
    domain = parts[1] if len(parts) > 1 else "{}.com".format(tenant)
    host = "https://{}.eightfold.ai".format(urllib.parse.quote(tenant))

    # Eightfold tenants are configured one of two ways and there is no way to
    # tell from outside which. Measured: nvidia answers on /api/pcsx/search and
    # 403s on /api/apply/v2/jobs with "Not authorized for PCSX"; mlp does the
    # reverse. Trying only one endpoint marked working boards as dead, so both
    # are tried and the shape of the response says which one answered.
    # robots.txt on eightfold tenants Allows both paths explicitly.
    endpoints = (
        ("pcsx", "{}/api/pcsx/search?domain={}".format(
            host, urllib.parse.quote(domain))),
        ("apply", "{}/api/apply/v2/jobs?domain={}".format(
            host, urllib.parse.quote(domain))),
    )

    last_err = None
    for flavour, base in endpoints:
        r = BoardResult("eightfold", token)
        ok = _eightfold_collect(r, flavour, base)
        if ok:
            r.extra["endpoint"] = flavour
            return r
        last_err = r.error
    r = BoardResult("eightfold", token, error=last_err or "eightfold_unreadable")
    return r


def _eightfold_collect(r: BoardResult, flavour: str, base: str) -> bool:
    """Page one Eightfold endpoint into `r`. True if it answered."""
    start = 0
    while True:
        url = "{}&start={}&num={}".format(base, start, EIGHTFOLD_PAGE)
        if EIGHTFOLD_LOCATION:
            url += "&location=" + urllib.parse.quote(EIGHTFOLD_LOCATION)
            r.extra["location_filter"] = EIGHTFOLD_LOCATION

        status, data, err = _request(url)
        r.status = status
        if err:
            r.error = "eightfold_{}{}".format(
                err, "_partial_at_{}".format(len(r.postings)) if r.postings else ""
            )
            # A failure partway through is still a partial read, and a partial
            # read must never look complete — so it is reported as an error even
            # though we already have rows.
            return bool(r.postings) and "partial" not in r.error

        # pcsx wraps everything in `data`; apply returns it at the top level.
        payload = (data or {}).get("data") if flavour == "pcsx" else (data or {})
        if not isinstance(payload, dict):
            if not r.postings:
                r.error = "unexpected_shape"
            return False
        posts = payload.get("positions")
        if posts is None:
            if not r.postings:
                r.error = "unexpected_shape"
            return False
        if r.reported_total is None and isinstance(payload.get("count"), int):
            r.reported_total = payload["count"]

        for j in posts:
            locs = j.get("locations") or j.get("standardizedLocations") or []
            if isinstance(locs, list):
                loc = "; ".join(str(x) for x in locs if x)
            else:
                loc = str(locs or "")
            jid = str(j.get("id") or j.get("atsJobId") or "")
            # postedTs is a real epoch, so the posting age is a fact here rather
            # than an inference. Emitted as ISO for consistency with the others.
            posted = ""
            ts = j.get("postedTs") or j.get("creationTs")
            if isinstance(ts, (int, float)) and ts > 0:
                posted = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))
            r.postings.append(
                Posting(
                    "eightfold",
                    r.token,
                    jid,
                    j.get("name") or "",
                    loc,
                    "{}/careers/job/{}".format(base.split("/api/")[0], jid),
                    posted,
                )
            )
            # Kept for the free technical classification and the remote tier.
            if j.get("department"):
                r.extra.setdefault("departments", {})[jid] = j["department"]
            if j.get("workLocationOption"):
                r.extra.setdefault("work_location", {})[jid] = j["workLocationOption"]

        start += EIGHTFOLD_PAGE
        if len(posts) < EIGHTFOLD_PAGE:
            return True
        if r.reported_total is not None and start >= r.reported_total:
            return True
        if start > 20000:
            r.error = "pagination_runaway"
            return False


# --------------------------------------------------------------------------- #
# SAP SuccessFactors. Where Wipro is: 4,419 open postings, one request.
# --------------------------------------------------------------------------- #
# Token format: the careers host, e.g. "careers.wipro.com".
#
# Verified live 2026-07-31 against careers.wipro.com. What does NOT work, so
# nobody retries it:
#
#   /search/?q=            200, but zero job rows — the results are rendered
#                          client-side, so there is nothing to parse
#   /api/jobs, /api/apply/v2/jobs      302 to the shell
#   job detail pages       ZERO schema.org JobPosting blocks. This extends the
#                          project's existing "no JSON-LD on Indian careers
#                          landing pages" finding to SF *detail* pages too.
#
# What does work is the sitemap, which is the route a site publishes precisely
# so that crawlers use it instead of hammering search:
#
#   GET https://careers.wipro.com/sitemap.xml   ->  4,419 <url> entries,
#                                                   100% of them job URLs
#
# Confirmed to generalise: jobs.mahindracareers.com/sitemap.xml gives 731.
# robots.txt disallows /services/, /applybutton/, /talentcommunity/ and friends
# but not /sitemap.xml or /job/.
#
# One honesty constraint: every <lastmod> in Wipro's sitemap was the same date
# (2026-07-25), i.e. the sitemap's own regeneration date, NOT when each job was
# posted. So it is recorded in `extra` and `posted_on` is left EMPTY. Treating a
# sitemap timestamp as a posting date would invent a freshness signal, and
# freshness is what this product sorts on.
SF_JOB_RE = re.compile(r"<loc>\s*([^<\s]*?/job/[^<\s]+?)\s*</loc>"
                       r"(?:\s*<lastmod>\s*([^<\s]+)\s*</lastmod>)?", re.I)
SF_SLUG_RE = re.compile(r"/job/([^/]+)/(\d+)/?$")
# Trailing "-IND-570016": ISO-3-ish country then a postcode.
SF_TAIL_RE = re.compile(r"^(.*?)-([A-Za-z]{2,3})-([A-Za-z0-9]{3,10})$")
SF_TAIL_ONLY_RE = re.compile(r"^(.*?)-([A-Za-z]{3})$")

# How many child sitemaps to read from a <sitemapindex>. A cap exists because
# a large corporate site can list hundreds and we only need the job ones.
SF_MAX_CHILD_SITEMAPS = int(os.environ.get("LAKE_SF_MAX_SITEMAPS", "12"))

# Only the codes that appear in the target company set. An unknown code is
# passed through unchanged rather than guessed at.
SF_COUNTRY = {
    "ind": "India", "usa": "United States", "gbr": "United Kingdom",
    "deu": "Germany", "fra": "France", "can": "Canada", "aus": "Australia",
    "sgp": "Singapore", "jpn": "Japan", "che": "Switzerland", "irl": "Ireland",
    "nld": "Netherlands", "pol": "Poland", "rou": "Romania", "bra": "Brazil",
    "mex": "Mexico", "phl": "Philippines", "chn": "China", "are": "UAE",
    "esp": "Spain", "ita": "Italy", "swe": "Sweden", "mys": "Malaysia",
}


def _sf_split_slug(slug: str) -> Tuple[str, str]:
    """A SuccessFactors job slug -> (title, location).

    The slug is "{City}-{TITLE}-{COUNTRY}-{postcode}", hyphen-joined, so the
    city/title boundary is genuinely ambiguous — cities have hyphens too. The
    country code and postcode at the end ARE unambiguous, so those are taken
    first, and the leading city is only removed when it matches the measured
    city vocabulary in quality.py. When it does not match, the city stays in the
    title as harmless noise rather than being guessed at and cut wrongly.
    """
    import html as _html

    text = _html.unescape(urllib.parse.unquote(slug)).strip()
    country = postcode = ""
    m = SF_TAIL_RE.match(text)
    if m:
        text, code, postcode = m.group(1), m.group(2), m.group(3)
        country = SF_COUNTRY.get(code.lower(), code.upper())
    else:
        # Not every slug carries a postcode: "...-Executive-with-Dutch-ROU" ends
        # at the country code. Only accept a bare trailing code when it is one we
        # actually know, or every job whose title ends in a three-letter word
        # ("...-Lead-SAP") would lose it to a fake country.
        m = SF_TAIL_ONLY_RE.match(text)
        if m and m.group(2).lower() in SF_COUNTRY:
            text, country = m.group(1), SF_COUNTRY[m.group(2).lower()]

    words = [w for w in text.replace("-", " ").split() if w]
    city = ""
    # Reuse the alias table rather than duplicating a city list. Longest first,
    # so "Greater Noida" and "Navi Mumbai" beat "Noida" and "Mumbai".
    try:
        from core.quality import CITY_ALIASES
    except Exception:  # noqa: BLE001
        CITY_ALIASES = {}
    for n in (3, 2, 1):
        # `continue`, not `break`: a two-word slug like "Bengaluru-Analyst" must
        # still get a chance at the 1-word match after 3 and 2 are skipped.
        if len(words) <= n:
            continue
        head = " ".join(words[:n]).lower()
        if head in CITY_ALIASES:
            city = CITY_ALIASES[head]
            words = words[n:]
            break

    title = " ".join(words)
    location = ", ".join(x for x in (city, country) if x)
    if postcode and location:
        location += " " + postcode
    return title, location


SF_ITEM_RE = re.compile(r"<item\b[^>]*>(.*?)</item>", re.S | re.I)


def _sf_tag(chunk: str, tag: str) -> str:
    """First value of one XML tag, CDATA unwrapped, entities decoded."""
    import html as _html

    m = re.search(r"<{}\b[^>]*>(.*?)</{}>".format(re.escape(tag), re.escape(tag)),
                  chunk, re.S | re.I)
    if not m:
        return ""
    v = m.group(1).strip()
    cd = re.match(r"^<!\[CDATA\[(.*)\]\]>$", v, re.S)
    if cd:
        v = cd.group(1)
    return " ".join(_html.unescape(v).split())


def _sf_from_rss(r: BoardResult, xml: str) -> BoardResult:
    """Parse a SuccessFactors Google-Jobs RSS feed.

    Better than the <urlset> path in every way: the title, location and job
    function are real fields rather than guesses off a URL slug.

    `g:expiration_date` is an EXPIRY, not a posting date, so it goes to `extra`
    as a deadline candidate and `posted_on` stays empty. The feed carries no
    posting date at all, and inventing one from an expiry would be exactly the
    freshness lie the sitemap <lastmod> note warns about.
    """
    for chunk in SF_ITEM_RE.findall(xml):
        jid = _sf_tag(chunk, "g:id") or _sf_tag(chunk, "guid")
        title = _sf_tag(chunk, "title")
        link = _sf_tag(chunk, "link")
        location = _sf_tag(chunk, "g:location")
        if not (title or link):
            continue
        # Titles in this feed carry a trailing "(City, CC)". Strip it into the
        # location only when location is otherwise empty, so the title reads
        # cleanly for the filters either way.
        m = re.match(r"^(.*?)\s*\(([^()]{2,60})\)\s*$", title)
        if m:
            title = m.group(1).strip()
            location = location or m.group(2).strip()
        r.postings.append(
            Posting(
                "successfactors", r.token, str(jid), title, location, link, "",
                description=(strip_html(_sf_tag(chunk, "description")) or None),
            )
        )
        fn = _sf_tag(chunk, "g:job_function")
        if fn:
            r.extra.setdefault("job_functions", {})[str(jid)] = fn
        exp = _sf_tag(chunk, "g:expiration_date")
        if exp:
            r.extra.setdefault("expires", {})[str(jid)] = exp
    r.extra["feed_format"] = "rss_google_jobs"
    r.reported_total = len(r.postings)
    if not r.postings:
        r.extra["rss_had_no_items"] = True
    return r


def _successfactors(token: str) -> BoardResult:
    r = BoardResult("successfactors", token)
    host = token.strip().rstrip("/")
    if "://" in host:
        host = urllib.parse.urlsplit(host).netloc
    url = "https://{}/sitemap.xml".format(host)

    status, xml, err = _request(url, want_json=False)
    r.status = status
    if err:
        r.error = "sitemap_{}".format(err)
        return r
    if not isinstance(xml, str):
        r.error = "sitemap_not_text"
        return r

    # SuccessFactors serves /sitemap.xml in one of THREE shapes. Measured:
    #   <urlset>       careers.wipro.com, jobs.mahindracareers.com — job URLs
    #                  only, so title and location come from the slug
    #   <sitemapindex> a sitemap of sitemaps; follow the children
    #   <rss>          jobs.sap.com — a Google Jobs feed with REAL fields
    #                  (g:location, g:job_function, g:expiration_date) and the
    #                  full description inline. Strictly better than the slug.
    # Assuming one shape is why SAP first reported as a dead board.
    low = xml.lower()
    if "<rss" in low and "<item" in low:
        return _sf_from_rss(r, xml)
    if "<loc" not in low:
        r.error = "sitemap_not_xml"
        return r

    if "<sitemapindex" in low:
        children = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", xml, re.I)
        jobbish = [c for c in children if re.search(r"job|requisition|position", c, re.I)]
        chosen = (jobbish or children)[:SF_MAX_CHILD_SITEMAPS]
        r.extra["sitemap_index_children"] = len(children)
        r.extra["sitemap_children_read"] = len(chosen)
        parts = []
        for child in chosen:
            cstatus, cxml, cerr = _request(child, want_json=False)
            if cerr or not isinstance(cxml, str):
                # A child sitemap we could not read means the enumeration is
                # incomplete. Recorded as an error so a partial board is never
                # mistaken for a complete one.
                r.error = "sitemap_child_{}".format(cerr or "unreadable")
                return r
            parts.append(cxml)
        xml = "\n".join(parts)

    seen = set()
    lastmods = set()
    for job_url, lastmod in SF_JOB_RE.findall(xml):
        m = SF_SLUG_RE.search(job_url)
        if not m:
            continue
        jid = m.group(2)
        if jid in seen:
            continue
        seen.add(jid)
        if lastmod:
            lastmods.add(lastmod)
        title, location = _sf_split_slug(m.group(1))
        r.postings.append(
            Posting(
                "successfactors",
                token,
                jid,
                title,
                location,
                job_url,
                "",  # deliberately empty — see the note above about <lastmod>
            )
        )
    if not r.postings:
        # A sitemap that parses but holds no /job/ URLs is a real answer: this
        # host is not a SuccessFactors career site. Not an error, just empty.
        r.extra["sitemap_had_no_job_urls"] = True
    if lastmods:
        r.extra["sitemap_lastmod"] = sorted(lastmods)[-1]
    r.reported_total = len(r.postings)  # the sitemap IS the full list
    return r


# --------------------------------------------------------------------------- #
# Zoho Recruit: public Careers HTML with an embedded jobs JSON input.
# --------------------------------------------------------------------------- #
ZOHO_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"
)


def _zoho_openings(data):
    """Return the openings list from Zoho's array or wrapped JSON shape."""
    if isinstance(data, list):
        return data
    if not isinstance(data, dict):
        return None
    for key in ("jobs", "openings", "job_openings", "records", "results", "data"):
        if key in data:
            found = _zoho_openings(data[key])
            if found is not None:
                return found
    for value in data.values():
        if isinstance(value, (dict, list)):
            found = _zoho_openings(value)
            if found is not None:
                return found
    return None


def _zoho_explicit_false(value) -> bool:
    if isinstance(value, bool):
        return not value
    if isinstance(value, (int, float)):
        return value == 0
    if isinstance(value, str):
        return value.strip().lower() in {"false", "0", "no", "off"}
    return False


def _zoho_truthy(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "on"}
    return bool(value)


def _zoho(token: str) -> BoardResult:
    r = BoardResult("zohorecruit", token)
    url = "https://{}.zohorecruit.com/jobs/Careers".format(
        urllib.parse.quote(token, safe="")
    )
    r.status, page, r.error = _request(
        url, want_json=False, user_agent=ZOHO_BROWSER_UA
    )
    if r.error:
        return r
    if not isinstance(page, str):
        r.error = "unexpected_shape"
        return r

    import html as _html

    id_match = re.search(
        r"\bid\s*=\s*([\"'])jobs\1", page, flags=re.IGNORECASE
    )
    if not id_match:
        r.error = "missing_jobs_input"
        return r
    input_start = page.rfind("<input", 0, id_match.start())
    if input_start < 0:
        r.error = "missing_jobs_input"
        return r
    input_end = page.find("<input", id_match.end())
    if input_end < 0:
        input_end = len(page)
    value_match = re.search(
        r"\bvalue\s*=\s*([\"'])(.*?)\1",
        page[input_start:input_end],
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not value_match:
        r.error = "missing_jobs_value"
        return r
    try:
        data = json.loads(_html.unescape(value_match.group(2)))
    except (TypeError, ValueError, json.JSONDecodeError):
        r.error = "invalid_jobs_json"
        return r

    openings = _zoho_openings(data)
    if openings is None:
        r.error = "unexpected_shape"
        return r
    for opening in openings:
        if not isinstance(opening, dict):
            continue
        if _zoho_explicit_false(opening.get("Publish")):
            continue
        if _zoho_explicit_false(opening.get("Keep_on_Career_Site")):
            continue
        if _zoho_truthy(opening.get("Is_Locked")):
            continue

        raw_id = opening.get("id")
        if raw_id is None:
            raw_id = opening.get("ID", "")
        job_id = str(raw_id)
        title = opening.get("Posting_Title") or opening.get("Job_Opening_Name") or ""
        if not isinstance(title, str):
            title = str(title)
        if _zoho_truthy(opening.get("Remote_Job")):
            location = "Remote"
        else:
            location = ", ".join(
                str(opening.get(field)).strip()
                for field in ("City", "State", "Country")
                if opening.get(field) not in (None, "")
                and str(opening.get(field)).strip()
            )
        description = opening.get("Job_Description")
        if description is not None and not isinstance(description, str):
            description = str(description)
        r.postings.append(
            Posting(
                "zohorecruit",
                token,
                job_id,
                title,
                location,
                "https://{}.zohorecruit.com/jobs/Careers/{}".format(
                    urllib.parse.quote(token, safe=""),
                    urllib.parse.quote(job_id, safe=""),
                ),
                str(opening.get("Date_Opened") or ""),
                description=strip_html(description) or None,
            )
        )
    return r


# --------------------------------------------------------------------------- #
# Darwinbox: public all-jobs JSON endpoint.
# --------------------------------------------------------------------------- #
def _darwinbox_openings(data):
    """Return Darwinbox openings from its wrapped or direct JSON shape."""
    if isinstance(data, list):
        return data
    if not isinstance(data, dict):
        return None
    for key in ("data", "jobs", "openings", "job_openings", "results"):
        if key in data:
            found = _darwinbox_openings(data[key])
            if found is not None:
                return found
    return None


def _darwinbox_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _darwinbox_location(value) -> str:
    """Flatten Darwinbox's string/list/dict location fields for display."""
    if value in (None, ""):
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        for key in ("name", "location_name", "location", "label", "value"):
            if value.get(key) not in (None, ""):
                return _darwinbox_location(value[key])
        return ""
    if isinstance(value, (list, tuple)):
        parts = []
        for item in value:
            text = _darwinbox_location(item)
            if text and text not in parts:
                parts.append(text)
        return ", ".join(parts)
    return _darwinbox_text(value)


DARWINBOX_PAGE_SIZE = 100


def _darwinbox(token: str) -> BoardResult:
    r = BoardResult("darwinbox", token)
    url = (
        "https://{}.darwinbox.in/ms/candidateapi/job/alljobs?companyId=main"
        .format(urllib.parse.quote(token, safe=""))
    )
    page = 1
    while True:
        body = json.dumps(
            {"page": page, "limit": DARWINBOX_PAGE_SIZE},
            separators=(",", ":"),
        ).encode("utf-8")
        status, data, error = _request(url, body=body)
        if page == 1:
            r.status = status
        if error:
            r.error = error
            return r

        openings = _darwinbox_openings(data)
        if openings is None:
            r.error = "unexpected_shape"
            return r
        if page == 1 and isinstance(data, dict):
            total = data.get("job_counts")
            if isinstance(total, int):
                r.reported_total = total

        for opening in openings:
            if not isinstance(opening, dict):
                continue
            raw_id = opening.get("id")
            if raw_id is None:
                raw_id = opening.get("job_id", "")
            job_id = _darwinbox_text(raw_id)
            title = _darwinbox_text(
                opening.get("designation_name") or opening.get("title")
            )
            raw_locations = opening.get("officelocation_show_arr")
            if raw_locations in (None, ""):
                raw_locations = opening.get("locations")
            location = _darwinbox_location(raw_locations)
            description = opening.get("jd_summary")
            if description in (None, ""):
                description = opening.get("jd")
            posted_on = _darwinbox_text(
                opening.get("posted_on") or opening.get("created_on")
            )
            r.postings.append(
                Posting(
                    "darwinbox",
                    token,
                    job_id,
                    title,
                    location,
                    "https://{}.darwinbox.in/ms/candidatev2/main/careers/jobDetails/{}".format(
                        urllib.parse.quote(token, safe=""),
                        urllib.parse.quote(job_id, safe=""),
                    ),
                    posted_on,
                    description=strip_html(_darwinbox_text(description)) or None,
                )
            )

        if not openings or len(openings) < DARWINBOX_PAGE_SIZE:
            return r
        if r.reported_total is not None and r.count >= r.reported_total:
            return r
        page += 1


_ADAPTERS = {
    "greenhouse": _greenhouse,
    "lever": _lever,
    "ashby": _ashby,
    "smartrecruiters": _smartrecruiters,
    "workable": _workable,
    "workday": _workday,
    "personio": _personio,
    "recruitee": _recruitee,
    "keka": _keka,
    "eightfold": _eightfold,
    "successfactors": _successfactors,
    "zohorecruit": _zoho,
    "darwinbox": _darwinbox,
    "amazon": _amazon,
}


# Unstop is a public opportunity feed rather than a company board; token is
# retained for the common list_board(platform, token) interface.
_ADAPTERS["unstop"] = _unstop
if "unstop" not in PLATFORMS:
    PLATFORMS += ("unstop",)


def list_board(platform: str, token: str) -> BoardResult:
    """Return every open posting on one board."""
    fn = _ADAPTERS.get(platform)
    if fn is None:
        return BoardResult(platform, token, error="unsupported_platform")
    if platform in ROBOTS_FORBIDDEN and os.environ.get("LAKE_IGNORE_ROBOTS") != "1":
        # Refused here rather than inside the adapter, so the reason is the same
        # whether or not the adapter would have worked.
        return BoardResult(platform, token, error="platform_robots_disallowed")
    return fn(token)


# --------------------------------------------------------------------------- #
# CLI: python3 fetch.py greenhouse vercel
# --------------------------------------------------------------------------- #
def main(argv=None) -> None:
    import sys

    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) < 2:
        print("usage: python3 fetch.py <platform> <token>")
        print("platforms: {}".format(", ".join(PLATFORMS)))
        raise SystemExit(2)

    res = list_board(argv[0], argv[1])
    print(
        "{}:{}  status={}  jobs={}  reported_total={}  error={}".format(
            res.platform,
            res.token,
            res.status,
            res.count,
            res.reported_total,
            res.error,
        )
    )
    if res.truncated:
        print("!! TRUNCATED — collected {} of {}".format(res.count, res.reported_total))
    for p in res.postings[:15]:
        print("   {:<60} | {}".format(p.title[:60], p.location))
    if res.count > 15:
        print("   ... and {} more".format(res.count - 15))


if __name__ == "__main__":
    main()
