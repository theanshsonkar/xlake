"""Read one opportunity URL without an AI or browser dependency.

The reader is deliberately regex-first. It uses the same fetch/robots/UA and
filter functions as the board sweep, and keeps trust (source provenance)
separate from eligibility (whether the posting stated rules).
"""
from __future__ import annotations

import datetime as _datetime
import html
import json
import re
import sys
import urllib.parse
from typing import Any, Dict, List, Optional, Tuple

import fetch
import filters
import pagetext
import quality
import robots

ATS_KINDS = {
    "greenhouse", "lever", "ashby", "keka", "smartrecruiters", "workable",
    "workday", "successfactors",
}


def detect_url_kind(url: str, content_type: str = "", body: bytes = b"") -> str:
    """Classify by URL shape first, then content when supplied."""
    lower = (url or "").lower()
    host = urllib.parse.urlsplit(url).netloc.lower()
    ctype = (content_type or "").lower()
    if "application/pdf" in ctype or lower.split("?", 1)[0].endswith(".pdf") or body.startswith(b"%PDF"):
        return "pdf"
    path = urllib.parse.urlsplit(url).path.lower()
    if (host == "docs.google.com" and path.startswith("/forms")) or host == "forms.gle":
        return "google_form"
    if "amazon.jobs" in host:
        return "amazon.jobs"
    if "greenhouse.io" in host:
        return "greenhouse"
    if "lever.co" in host:
        return "lever"
    if "ashbyhq.com" in host:
        return "ashby"
    if ".keka.com" in host or ".kekahire.com" in host:
        return "keka"
    if "smartrecruiters.com" in host:
        return "smartrecruiters"
    if "workable.com" in host:
        return "workable"
    if "myworkdayjobs.com" in host or "myworkdaysite.com" in host:
        return "workday"
    if "successfactors.com" in host or "/job/" in urllib.parse.urlsplit(url).path.lower() and "careers" in host:
        return "successfactors"
    return "generic_html"


# Alias is useful to callers that use the wording from the phase brief.
classify_url = detect_url_kind


def trust_for_url(url: str, kind: Optional[str] = None) -> Tuple[str, List[str]]:
    """Return provenance trust only; this must not be used as eligibility."""
    kind = kind or detect_url_kind(url)
    host = urllib.parse.urlsplit(url).netloc.lower()
    if kind == "google_form":
        return "low_trust", ["google_form_is_not_a_company_or_known_ats"]
    if kind in ATS_KINDS or kind == "amazon.jobs":
        return "trusted", ["known_public_ats_or_company_job_domain"]
    return "low_trust", ["unrecognised_source_domain_{}".format(host or "missing")]


def _empty_record(url: str, kind: str, state: str, reason: str = "") -> Dict[str, Any]:
    now = _datetime.datetime.now(_datetime.timezone.utc).isoformat(timespec="seconds")
    trust, trust_reasons = trust_for_url(url, kind)
    return {
        "kind": "job", "source_platform": kind, "source_board": "",
        "company": "", "company_domain": urllib.parse.urlsplit(url).netloc.lower(),
        "title": "", "locations": [], "is_remote": False, "remote_scope": "",
        "url": url, "alt_urls": [], "posted_on": "", "deadline": "",
        "description": "", "stage": "unknown", "stage_title": "unknown",
        "stage_resolved": "unknown", "technical": None, "discipline": filters.UNKNOWN_D,
        "eligibility": {
            "batch_years": [], "experience_min": None, "experience_max": None,
            "degree_required": [], "enrolled_required": None, "evidence": {},
            "gates_found": [], "gates_missing": list(filters.ELIGIBILITY_GATES),
        },
        "trust": trust, "trust_reasons": trust_reasons,
        "hidden_reason": None, "eligibility_status": filters.ELIG_RULES_UNCLEAR,
        "first_seen": now, "last_seen": now, "is_live": False,
        "fetch_state": state,
    }


def _allowed(url: str) -> Tuple[bool, str]:
    # Check the requested URL before cache/API work: a disallowed URL must never
    # be fetched, even if a stale cached response happens to exist.
    return robots.allowed(url)


def _json_request(url: str, body: Optional[bytes] = None) -> Tuple[Optional[int], Any, Optional[str]]:
    allowed, why = _allowed(url)
    if not allowed:
        return None, None, "robots_disallowed:{}".format(why)
    return fetch._request(url, body=body, want_json=True)


def _html_request(url: str) -> Tuple[Optional[int], str, Optional[str]]:
    allowed, why = _allowed(url)
    if not allowed:
        return None, "", "robots_disallowed:{}".format(why)
    status, raw, err = fetch._request(url, want_json=False)
    return status, raw if isinstance(raw, str) else "", err


def _path_parts(url: str) -> List[str]:
    return [urllib.parse.unquote(x) for x in urllib.parse.urlsplit(url).path.split("/") if x]


def _api_target(url: str, kind: str) -> Optional[Tuple[str, Optional[bytes]]]:
    """Known clean detail/list routes; None means use the served page."""
    parts = _path_parts(url)
    host = urllib.parse.urlsplit(url).netloc.lower()
    if kind == "greenhouse" and "jobs" in parts:
        i = parts.index("jobs")
        if i and i + 1 < len(parts):
            return "https://boards-api.greenhouse.io/v1/boards/{}/jobs/{}?content=true".format(parts[i - 1], parts[i + 1]), None
    if kind == "lever" and len(parts) >= 2:
        return "https://api.lever.co/v0/postings/{}?mode=json".format(parts[-1]), None
    if kind == "ashby" and len(parts) >= 2:
        return "https://api.ashbyhq.com/posting-api/job-board/{}".format(parts[0]), None
    if kind == "smartrecruiters" and len(parts) >= 2:
        return "https://api.smartrecruiters.com/v1/companies/{}/postings/{}".format(parts[0], parts[-1]), None
    if kind == "amazon.jobs" and parts:
        job_id = next((p for p in parts if re.fullmatch(r"\d{5,}", p)), "")
        if job_id:
            return "https://www.amazon.jobs/en/search.json?base_query={}".format(urllib.parse.quote(job_id)), None
    if kind == "workday" and parts:
        # CXS search is the published Workday route. The detail page is used as
        # a fallback when the search response does not contain this requisition.
        tenant = host.split(".", 1)[0]
        site = parts[0]
        api = "https://{}/wday/cxs/{}/{}/jobs".format(host, tenant, site)
        body = json.dumps({"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": parts[-1]}).encode()
        return api, body
    return None


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return " ".join(_as_text(x) for x in (value.values() if isinstance(value, dict) else value))
    return fetch.strip_html(str(value))


def _payload_fields(payload: Dict[str, Any], url: str, kind: str) -> Dict[str, Any]:
    loc = payload.get("location") or payload.get("locations") or payload.get("locationsText") or ""
    if isinstance(loc, dict):
        loc = ", ".join(str(loc.get(k) or "") for k in ("name", "city", "state", "country"))
    elif isinstance(loc, list):
        loc = "; ".join(_as_text(x) for x in loc)
    description = (payload.get("descriptionPlain") or payload.get("description") or
                   payload.get("content") or payload.get("descriptionHtml") or
                   payload.get("jobDescription") or "")
    return {
        "title": _as_text(payload.get("title") or payload.get("text") or payload.get("name")),
        "location": _as_text(loc), "description": _as_text(description),
        "company": _as_text(payload.get("company") or payload.get("companyName")),
        "posted_on": _as_text(payload.get("updated_at") or payload.get("publishedAt") or
                               payload.get("published_on") or payload.get("postedOn") or
                               payload.get("releasedDate")),
        "deadline": _as_text(payload.get("deadline") or payload.get("expirationDate")),
        "url": _as_text(payload.get("absolute_url") or payload.get("hostedUrl") or
                         payload.get("jobUrl") or payload.get("url") or url),
        "board": _as_text(payload.get("boardToken") or payload.get("token")),
        "raw": payload,
    }


def _find_payload(data: Any, url: str, kind: str) -> Optional[Dict[str, Any]]:
    if isinstance(data, dict):
        if any(k in data for k in ("title", "text", "name")):
            return _payload_fields(data, url, kind)
        for key in ("job", "posting", "position"):
            if isinstance(data.get(key), dict):
                return _payload_fields(data[key], url, kind)
        items = data.get("jobs") or data.get("content") or data.get("jobPostings") or data.get("positions")
        if isinstance(items, list):
            return _find_payload(items, url, kind)
    if isinstance(data, list):
        wanted = urllib.parse.urlsplit(url).path.rstrip("/").split("/")[-1]
        for item in data:
            if not isinstance(item, dict):
                continue
            candidate = _payload_fields(item, url, kind)
            ids = {str(item.get(k) or "") for k in ("id", "shortcode", "jobId", "atsJobId")}
            if wanted in ids or wanted in candidate["url"] or not wanted:
                return candidate
    return None


def _adapter_fields(url: str, kind: str) -> Optional[Dict[str, Any]]:
    """Use an existing board adapter when a platform has no detail endpoint."""
    if kind not in {"keka", "workable"}:
        return None
    parts = _path_parts(url)
    host = urllib.parse.urlsplit(url).netloc.lower()
    if kind == "keka":
        token = host.split(".")[0]
    else:
        token = parts[0] if parts else ""
    if not token:
        return None
    result = fetch.list_board(kind, token)
    if result.error:
        return None
    wanted = parts[-1] if kind == "keka" else (parts[2] if len(parts) > 2 and parts[1].lower() == "j" else parts[-1])
    for posting in result.postings:
        if str(posting.job_id) == str(wanted) or posting.url.rstrip("/") == url.rstrip("/"):
            return {
                "title": posting.title, "location": posting.location,
                "description": posting.description or "", "company": "",
                "posted_on": posting.posted_on, "deadline": "", "url": posting.url,
                "board": token, "raw": {},
            }
    return None


def _html_fields(raw: str, url: str, kind: str) -> Dict[str, Any]:
    text = pagetext.to_text(raw)
    title_match = re.search(r"<title\b[^>]*>(.*?)</title\s*>", raw or "", re.I | re.S)
    title = fetch.strip_html(title_match.group(1)) if title_match else ""
    heading = re.search(r"<(?:h1|h2)\b[^>]*>(.*?)</h[12]\s*>", raw or "", re.I | re.S)
    if heading:
        title = fetch.strip_html(heading.group(1)) or title
    title = re.sub(r"\s*[|–—-]\s*(?:careers?|jobs?|google forms?).*$", "", title, flags=re.I).strip()
    # Google Forms has no dependable JSON contract; the served visible text is
    # the complete source we can honestly read without a browser.
    description = text
    return {"title": title, "location": "", "description": description,
            "company": "", "posted_on": "", "deadline": "", "url": url,
            "board": "", "raw": {}}


def _locations(blob: str) -> Tuple[List[Dict[str, str]], bool, str]:
    parsed = quality.parse_locations(blob or "")
    cities = parsed.get("cities") or []
    states = parsed.get("states") or []
    country = "India" if filters.INDIA_RE.search(blob or "") else ""
    if not cities and not states and blob:
        return [{"country": country, "state": "", "city": ""}], bool(parsed.get("remote")), ""
    out = []
    for index, city in enumerate(cities):
        out.append({"country": country, "state": states[index] if len(states) == len(cities) else (states[0] if len(states) == 1 else ""), "city": city})
    if not out:
        out = [{"country": country, "state": state, "city": ""} for state in states]
    remote = bool(parsed.get("remote")) or bool(filters.REMOTE_ANY.search(blob or ""))
    scope = "global" if filters.REMOTE_OPEN.search(blob or "") else ("india" if country else "unknown")
    return out, remote, scope


def _kind(title: str, stage: str) -> str:
    if re.search(r"\b(scholarship)\b", title, re.I):
        return "scholarship"
    if re.search(r"\b(programme|program|fellowship)\b", title, re.I):
        return "programme"
    if re.search(r"\b(intern|internship|apprentice|trainee|placement)\b", title, re.I) or stage == "early" and re.search(r"\b(student|campus)\b", title, re.I):
        return "internship"
    return "job"


def extract_record(fields: Dict[str, Any], url: str, kind: str, fetch_state: str = "ok") -> Dict[str, Any]:
    """Pure record shaping from already fetched fields."""
    title = (fields.get("title") or "").strip()
    location = (fields.get("location") or "").strip()
    description = (fields.get("description") or "").strip()
    # All classifiers come from filters.py; this reader has no second copy of
    # stage, technical, discipline, or eligibility rules.
    verdict = filters.classify(title, location)
    resolution = filters.resolve_stage(verdict.stage, description, title)
    gates_found, gates_missing = filters.gates_of(resolution, verdict.stage, title)
    locations, is_remote, remote_scope = _locations(location)
    hidden = filters.hidden_reason(resolution.stage_resolved, verdict.bucket,
                                   verdict.technical, resolution.experience_min,
                                   verdict.discipline)
    eligibility_status = filters.eligibility_status(hidden, gates_found)
    trust, trust_reasons = trust_for_url(url, kind)
    now = _datetime.datetime.now(_datetime.timezone.utc).isoformat(timespec="seconds")
    source_host = urllib.parse.urlsplit(url).netloc.lower()
    # Eligibility status says whether rules were stated, not whether the source
    # is trustworthy. A real Razorpay job labelled low_trust would be a scam
    # warning, while the same posting can still have confirmed eligibility.
    return {
        "kind": _kind(title, resolution.stage_resolved),
        "source_platform": kind, "source_board": fields.get("board") or "",
        "company": fields.get("company") or (fields.get("board") or source_host.split(".")[0]).replace("-", " ").title(),
        "company_domain": source_host, "title": title, "locations": locations,
        "is_remote": is_remote, "remote_scope": remote_scope, "url": url,
        "alt_urls": [fields["url"]] if fields.get("url") and fields["url"] != url else [],
        "posted_on": fields.get("posted_on") or "", "deadline": fields.get("deadline") or "",
        # Keep stdout safe for users: extraction runs on the complete text, but
        # the record never displays a full job description.
        "description": description[:200], "stage": verdict.stage,
        "stage_title": verdict.stage, "stage_resolved": resolution.stage_resolved,
        "technical": verdict.technical, "discipline": verdict.discipline,
        "eligibility": {
            "batch_years": resolution.batch_years,
            "experience_min": resolution.experience_min,
            "experience_max": resolution.experience_max,
            "degree_required": resolution.degree_required,
            "enrolled_required": resolution.enrolled_required,
            "evidence": resolution.evidence, "gates_found": gates_found,
            "gates_missing": gates_missing,
        },
        "trust": trust, "trust_reasons": trust_reasons,
        "hidden_reason": hidden, "eligibility_status": eligibility_status,
        "first_seen": now, "last_seen": now, "is_live": fetch_state == "ok",
        "fetch_state": fetch_state,
    }


def read_url(url: str) -> Dict[str, Any]:
    kind = detect_url_kind(url)
    allowed, why = _allowed(url)
    if not allowed:
        rec = _empty_record(url, kind, "robots_disallowed", why)
        return rec
    if kind == "pdf":
        rec = _empty_record(url, kind, "needs_pdf_reader", "pdf parsing not installed")
        rec["needs_pdf_reader"] = True
        return rec

    fields: Optional[Dict[str, Any]] = None
    api = _api_target(url, kind)
    if api:
        api_url, body = api
        status, data, err = _json_request(api_url, body)
        if not err:
            fields = _find_payload(data, url, kind)
            if fields:
                fields["board"] = fields.get("board") or (_path_parts(url)[0] if kind in {"greenhouse", "ashby", "smartrecruiters"} else "")
        # An API denial/shape mismatch falls back to the original page only if
        # that page itself is robots-permitted; a partial API read is never ok.

    if fields is None:
        fields = _adapter_fields(url, kind)

    if fields is None:
        status, raw, err = _html_request(url)
        if err:
            state = "robots_disallowed" if str(err).startswith("robots_disallowed") else "error"
            return _empty_record(url, kind, state, str(err))
        if raw.startswith("%PDF"):
            rec = _empty_record(url, kind, "needs_pdf_reader", "pdf magic bytes")
            rec["needs_pdf_reader"] = True
            return rec
        if status is None or status < 200 or status >= 300:
            return _empty_record(url, kind, "error", "http_{}".format(status))
        fields = _html_fields(raw, url, kind)

    if not fields.get("title") and not fields.get("description"):
        return _empty_record(url, kind, "empty", "no opportunity text")
    return extract_record(fields, url, kind, "ok")


# Future AI fallback hook: after the deterministic extraction is measured, an
# explicitly budgeted/content-hashed model fallback may be inserted here. It is
# intentionally not called in Phase 2.


def _self_test() -> int:
    cases = [
        ("https://job-boards.greenhouse.io/vercel/jobs/1", "greenhouse"),
        ("https://jobs.lever.co/acme/abc", "lever"),
        ("https://jobs.ashbyhq.com/acme/abc", "ashby"),
        ("https://acme.keka.com/careers/jobdetails/1", "keka"),
        ("https://www.amazon.jobs/en/jobs/123456/title", "amazon.jobs"),
        ("https://docs.google.com/forms/d/e/abc/viewform", "google_form"),
        ("https://example.com/files/role.pdf", "pdf"),
        ("https://unknown.example/jobs/role", "generic_html"),
    ]
    passed = 0
    for url, expected in cases:
        got = detect_url_kind(url)
        ok = got == expected
        passed += int(ok)
        print("{} url kind {} -> {}".format("PASS" if ok else "FAIL", url, got))
    print("\n{} / {} passed".format(passed, len(cases)))

    extraction_cases = [
        ("2027 batch", [2027], ""),
        ("Year of Graduation: 2027", [2027], ""),
        ("2025-2027 batch", [2025, 2026, 2027], ""),
        ("passout 2026", [2026], ""),
        ("No batch year appears here", [], ""),
        ("B.Tech/B.E. in Computer Science", [], "B.Tech; B.E."),
        ("must be currently enrolled", [], ""),
    ]
    epassed = 0
    for text, expected_years, expected_degree in extraction_cases:
        years, _ = filters.batch_years_of(text)
        degrees, _ = filters.degrees_of(text)
        enrolled, _ = filters.enrolled_of(text)
        expected_enrolled = text == "must be currently enrolled"
        ok = years == expected_years and "; ".join(degrees) == expected_degree and enrolled == expected_enrolled
        epassed += int(ok)
        print("{} extraction {}".format("PASS" if ok else "FAIL", text))
    print("\n{} / {} passed".format(epassed, len(extraction_cases)))

    trust_cases = [
        ("https://docs.google.com/forms/d/e/abc/viewform", "low_trust"),
        ("https://job-boards.greenhouse.io/acme/jobs/1", "trusted"),
    ]
    tpassed = 0
    for url, expected in trust_cases:
        got = trust_for_url(url)[0]
        ok = got == expected
        tpassed += int(ok)
        print("{} trust {} -> {}".format("PASS" if ok else "FAIL", url, got))
    print("\n{} / {} passed".format(tpassed, len(trust_cases)))
    return 0 if passed == len(cases) and epassed == len(extraction_cases) and tpassed == len(trust_cases) else 1


if __name__ == "__main__":
    if len(sys.argv) == 1:
        raise SystemExit(_self_test())
    if len(sys.argv) != 2:
        print("usage: env python3 read_url.py <url>", file=sys.stderr)
        raise SystemExit(2)
    print(json.dumps(read_url(sys.argv[1]), ensure_ascii=False))


