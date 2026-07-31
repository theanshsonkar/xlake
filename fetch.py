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
  - One request at a time per host, with a delay. Different platforms are
    different hosts, so they may be swept in parallel lanes later.

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

# An honest User-Agent with a contact address. This is what makes good faith
# demonstrable if anyone ever looks at their logs and wonders who we are.
UA = "OpportunityLake/0.1 (+https://github.com/anshsonkar/opportunity-lake; contact: anshsonkar@users.noreply.github.com)"

TIMEOUT = 30
# Seconds between requests to the SAME host. Different platforms are different
# hosts, so lanes run in parallel while each host stays politely serialised.
# Public JSON APIs tolerate more than a careers page does; tune per run.
DELAY_PER_HOST = float(os.environ.get("LAKE_HOST_DELAY", "1.0"))

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
)


# --------------------------------------------------------------------------- #
# Politeness: serialise requests per host
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
    gap = time.monotonic() - _host_last.get(host, 0.0)
    if gap < DELAY_PER_HOST:
        time.sleep(DELAY_PER_HOST - gap)
    return lock


def _release(url: str, lock: threading.Lock) -> None:
    _host_last[_host_of(url)] = time.monotonic()
    lock.release()


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #
def _request(
    url: str,
    *,
    body: Optional[bytes] = None,
    want_json: bool = True,
    retries: int = 3,
) -> Tuple[Optional[int], object, Optional[str]]:
    """Return (http_status, parsed_body_or_text, error_string).

    error_string is None on success. A non-2xx status is an error.

    Retries transient failures (timeouts, connection resets, 429, 502/503/504)
    with backoff. Long paginated sweeps of a big Workday board WILL hit one of
    these eventually, and without a retry the board silently truncates.
    """
    headers = {
        "User-Agent": UA,
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
                last = (e.code, None, "http_{}".format(e.code))
                if e.code in (429, 502, 503, 504):
                    continue  # transient, retry
                return last  # 404/422 etc: a real answer, do not retry
            except Exception as e:  # noqa: BLE001
                last = (None, None, "{}: {}".format(type(e).__name__, str(e)[:160]))
                continue  # timeout / reset, retry
        finally:
            _release(url, lock)

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

    @property
    def ok(self) -> bool:
        return self.error is None

    @property
    def count(self) -> int:
        return len(self.postings)

    @property
    def truncated(self) -> bool:
        """True if the API claimed more postings than we actually collected.

        This must always be False in production. If it is ever True we are
        silently under-reporting a board, which is the Workday bug that made
        Nvidia look like a 200-job company when it has 2,000.
        """
        return self.reported_total is not None and self.count < self.reported_total


# --------------------------------------------------------------------------- #
# Adapters
# --------------------------------------------------------------------------- #
def _greenhouse(token: str) -> BoardResult:
    r = BoardResult("greenhouse", token)
    url = "https://boards-api.greenhouse.io/v1/boards/{}/jobs".format(
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
            )
        )
    # Greenhouse returns the whole board in one response and reports meta.total.
    meta = (data or {}).get("meta") or {}
    if isinstance(meta.get("total"), int):
        r.reported_total = meta["total"]
    return r


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
            )
        )
    return r


def _smartrecruiters(token: str) -> BoardResult:
    """Paginated. limit max is 100; loop on totalFound."""
    r = BoardResult("smartrecruiters", token)
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
        loc = j.get("location") or {}
        bits = [loc.get("city") or "", loc.get("country") or ""]
        r.postings.append(
            Posting(
                "workable",
                token,
                str(j.get("shortcode") or j.get("id") or ""),
                j.get("title") or "",
                ", ".join(x for x in bits if x),
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
            )
        )
    return r


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
}


def list_board(platform: str, token: str) -> BoardResult:
    """Return every open posting on one board."""
    fn = _ADAPTERS.get(platform)
    if fn is None:
        return BoardResult(platform, token, error="unsupported_platform")
    return fn(token)


# --------------------------------------------------------------------------- #
# CLI: python3 fetch.py greenhouse vercel
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    import sys

    if len(sys.argv) < 3:
        print("usage: python3 fetch.py <platform> <token>")
        print("platforms: {}".format(", ".join(PLATFORMS)))
        raise SystemExit(2)

    res = list_board(sys.argv[1], sys.argv[2])
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
