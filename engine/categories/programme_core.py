"""Generic, data-driven collection of official open-source programmes."""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from copy import deepcopy
from dataclasses import dataclass
from datetime import date, datetime, timezone
from html.parser import HTMLParser
from typing import Callable, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

from core.paths import OPPORTUNITIES_PATH, OPERATIONS_DIR

@dataclass(frozen=True)
class ProgrammeConfig:
    category: str
    opportunity_type: str
    source_registry: tuple
    observations_path: str
    verifications_path: str


MONTHS = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)
MONTH_PATTERN = "|".join(MONTHS)
APPLICANT_ACTION_TOKENS = (
    "applications open", "apply now", "apply by", "application deadline",
    "applications close", "applications are accepted", "applications accepted",
    "intern applications", "contributor applications", "application period",
    "rolling basis", "applications are rolling", "processed on a rolling basis",
)
# These are deliberately data, not source adapters.  The extra generic form
# handles pages which put words between "deadline" and "applications".
APPLICANT_DEADLINE_TOKENS = ("deadline for the contributors applications",)
ORGANIZER_WINDOW_TOKENS = (
    "mentor sign up", "mentors sign up", "mentoring organization",
    "mentoring organisation", "accepting proposals", "project submission",
    "mentor applications", "organization registration", "organisation registration",
    "call for mentors", "call for projects",
)
FORMAL_PROGRAMME_TOKENS = (
    "mentorship", "mentoring", "fellowship", "internship", "cohort",
    "stipend", "program", "programme",
)
ROLLING_TOKENS = ("rolling basis", "applications are rolling", "rolling application", "processed on a rolling basis")
APPLY_LINK_TOKENS = ("apply", "application", "applications", "contributor application")

def _month_number(name: str) -> int:
    return MONTHS.index(name.capitalize()) + 1


def parse_dates(text: str, nearby_year: Optional[int] = None) -> List[Dict]:
    """Parse supported dates/ranges into ``start``, ``end`` and exactness."""
    results: List[Dict] = []
    range_re = re.compile(
        rf"\b(?P<sm>{MONTH_PATTERN})\s+(?P<sd>\d{{1,2}})\s*(?:[–—-]|\bto\b)\s*"
        rf"(?P<em>{MONTH_PATTERN})?\s*(?P<ed>\d{{1,2}})(?:,?\s*(?P<year>20\d{{2}}))?\b", re.I)
    consumed: List[Tuple[int, int]] = []

    def make(month: str, day: str, year: Optional[str]) -> Optional[date]:
        actual_year = int(year) if year else nearby_year
        if actual_year is None:
            return None
        try:
            return date(actual_year, _month_number(month), int(day))
        except ValueError:
            return None

    for match in range_re.finditer(text):
        start = make(match.group("sm"), match.group("sd"), match.group("year"))
        end = make(match.group("em") or match.group("sm"), match.group("ed"), match.group("year"))
        if start and end:
            results.append({"start": start, "end": end, "quote": match.group(0), "exact": True, "span": match.span()})
            consumed.append(match.span())
    iso_re = re.compile(r"\b(?P<year>20\d{2})-(?P<month>\d{2})-(?P<day>\d{2})\b")
    for match in iso_re.finditer(text):
        try:
            value = date(int(match.group("year")), int(match.group("month")), int(match.group("day")))
        except ValueError:
            continue
        results.append({"start": value, "end": value, "quote": match.group(0), "exact": True, "span": match.span()})
        consumed.append(match.span())
    full_re = re.compile(rf"\b(?P<month>{MONTH_PATTERN})\s+(?P<day>\d{{1,2}}),?\s+(?P<year>20\d{{2}})\b", re.I)
    for match in full_re.finditer(text):
        if any(a <= match.start() < b for a, b in consumed):
            continue
        value = make(match.group("month"), match.group("day"), match.group("year"))
        if value:
            results.append({"start": value, "end": value, "quote": match.group(0), "exact": True, "span": match.span()})
            consumed.append(match.span())
    short_re = re.compile(rf"\b(?P<month>{MONTH_PATTERN})\s+(?P<day>\d{{1,2}})\b", re.I)
    for match in short_re.finditer(text):
        if any(a <= match.start() < b for a, b in consumed):
            continue
        value = make(match.group("month"), match.group("day"), None)
        if value:
            results.append({"start": value, "end": value, "quote": match.group(0), "exact": False, "span": match.span()})
    return sorted(results, key=lambda item: item["span"][0])


def parse_date(text: str, nearby_year: Optional[int] = None) -> Optional[Dict]:
    """Return the first supported date or range, useful to offline callers."""
    values = parse_dates(text, nearby_year)
    return values[0] if values else None


def _year_near(text: str, position: int) -> Optional[int]:
    years = list(re.finditer(r"\b(20\d{2})\b", text[max(0, position - 320):position + 320]))
    if not years:
        return None
    before = [match for match in years if match.start() <= min(320, position)]
    return int((before or years)[-1].group(1))


def _sentences(text: str) -> Iterable[Tuple[int, int, str]]:
    for match in re.finditer(r"[^.!?\n]+(?:[.!?]|$)", text):
        yield match.start(), match.end(), match.group(0).strip()


def detect_applicant_windows(text: str) -> List[Dict]:
    """Find dated applicant windows while rejecting organizer/mentor dates."""
    candidates: List[Dict] = []
    normalized = text.replace("\xa0", " ")
    for start, end, sentence in _sentences(normalized):
        lowered = sentence.lower()
        positive = [token for token in APPLICANT_ACTION_TOKENS + APPLICANT_DEADLINE_TOKENS if token in lowered]
        if not positive:
            continue
        # A page may put an applicant event and an organizer event in one
        # rendered block. Only the text attached to the applicant token is a
        # candidate; an organizer-only block never reaches this point.
        organizer_positions = [lowered.find(token) for token in ORGANIZER_WINDOW_TOKENS if token in lowered]
        candidate_sentence = sentence[:min(organizer_positions)] if organizer_positions else sentence
        dates = parse_dates(candidate_sentence, _year_near(normalized, start))
        if not dates:
            # Dates can sit on an adjacent line or heading, but remain close.
            left, right = max(0, start - 120), min(len(normalized), end + 120)
            context = normalized[left:right]
            if any(token in context.lower() for token in ORGANIZER_WINDOW_TOKENS):
                continue
            dates = parse_dates(context, _year_near(normalized, start))
        for parsed in dates:
            quote = candidate_sentence.strip() if candidate_sentence else parsed["quote"]
            candidates.append({"start": parsed["start"], "end": parsed["end"], "quote": quote, "date_quote": parsed["quote"], "exact": parsed["exact"], "token": positive[0]})
    # Preserve order and avoid a duplicated date discovered through adjacent context.
    unique = {}
    for candidate in candidates:
        unique[(candidate["start"], candidate["end"], candidate["quote"])] = candidate
    return list(unique.values())


def classify_status(text: str, windows: List[Dict], today: date, formal_programme: bool, application_url: Optional[str]) -> str:
    """Classify a page without making vague dates actionable."""
    lowered = text.lower()
    if formal_programme and application_url and any(token in lowered for token in ROLLING_TOKENS):
        return "rolling"
    for window in windows:
        opening, closing = window["start"], window["end"]
        if closing < today:
            return "closed"
        if opening <= today <= closing:
            return "open"
        if opening > today and window.get("exact"):
            return "opening_soon"
    return "non_actionable"


class _VisibleText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts: List[str] = []
        self.links: List[Tuple[str, str]] = []
        self.href: Optional[str] = None
        self.anchor: List[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.href = dict(attrs).get("href")
            self.anchor = []

    def handle_data(self, data):
        if data.strip():
            self.parts.append(data.strip())
            if self.href is not None:
                self.anchor.append(data.strip())

    def handle_endtag(self, tag):
        if tag == "a" and self.href is not None:
            self.links.append((" ".join(self.anchor), self.href))
            self.href, self.anchor = None, []


def _text(html: str) -> Tuple[str, List[Tuple[str, str]]]:
    parser = _VisibleText()
    parser.feed(html)
    return ". ".join(parser.parts), parser.links


def _quote_with(text: str, tokens: Iterable[str], minimum_words: int = 1) -> Optional[str]:
    for _, _, sentence in _sentences(text):
        if any(token in sentence.lower() for token in tokens) and len(re.findall(r"\b\w+\b", sentence)) >= minimum_words:
            return sentence.strip()
    return None


def _evidence(quote: Optional[str], url: str) -> Dict:
    return {"quote": quote, "url": url} if quote else {}


def _application_url(seed_url: str, href: str, final_url: Optional[str]) -> Optional[str]:
    base_url = final_url or seed_url
    seed = urlparse(seed_url)
    base = urlparse(base_url)
    if base.scheme not in ("http", "https") or not base.netloc:
        base = seed
        base_url = seed_url
    resolved = urljoin(base_url, href or "")
    target = urlparse(resolved)
    trusted = {(seed.scheme, seed.netloc.lower()), (base.scheme, base.netloc.lower())}
    if target.scheme not in ("http", "https") or not target.netloc or (target.scheme, target.netloc.lower()) not in trusted:
        return None
    return resolved


def _observation(seed: Dict, checked: str, state: str, reason: str, evidence: Optional[Dict] = None) -> Dict:
    value = {"source_id": seed["source_id"], "programme_id": seed["programme_id"], "official_url": seed["official_url"], "checked_at": checked, "result": "failed" if state == "failed" else ("actionable" if state == "actionable" else "non_actionable"), "state": state, "reason": reason}
    if evidence:
        value["official_evidence"] = evidence
    return value


def _base(seed: Dict, checked: str, evidence: Dict, config: ProgrammeConfig) -> Dict:
    return {"record_type": "programme", "category": config.category, "opportunity_type": config.opportunity_type, "programme_id": seed["programme_id"], "programme_name": seed["programme_name"], "organizer": seed["organizer"], "official_url": seed["official_url"], "application_url": None, "programme_status": "non_actionable", "opening_date": None, "deadline": None, "location": "not_stated", "remote": None, "international_eligibility": "needs_confirmation", "funding": "not_stated", "eligibility": "needs_confirmation", "official_evidence": evidence, "last_checked_at": checked, "source_confirmation": "official_source", "source_mechanism": "official_html"}


def parse_programme(seed: Dict, html: str, checked_at: Optional[datetime] = None, final_url: Optional[str] = None, *, config: ProgrammeConfig) -> Tuple[Optional[Dict], Dict]:
    """Run the same extraction and actionability pipeline for every seed."""
    checked_at = checked_at or datetime.now(timezone.utc)
    checked = checked_at.isoformat(timespec="seconds")
    text, links = _text(html)
    if not text.strip():
        return None, _observation(seed, checked, "failed", "empty or unparsable official response")
    apply_link = next(((label, href) for label, href in links if any(token in label.lower() for token in APPLY_LINK_TOKENS)), None)
    resolved_apply = _application_url(seed["official_url"], apply_link[1], final_url) if apply_link else None
    formal = any(token in text.lower() for token in FORMAL_PROGRAMME_TOKENS)
    windows = detect_applicant_windows(text)
    status = classify_status(text, windows, checked_at.date(), formal, resolved_apply)
    # Explicit dated deadlines are still useful closed observations even where
    # a site uses an unusual grammatical form around "applications".
    if status == "non_actionable":
        deadline_quote = _quote_with(text, APPLICANT_DEADLINE_TOKENS)
        if deadline_quote:
            deadline = parse_dates(deadline_quote, _year_near(text, text.lower().find("deadline")))
            if deadline and deadline[0]["end"] < checked_at.date():
                status, windows = "closed", [{"start": deadline[0]["start"], "end": deadline[0]["end"], "quote": deadline_quote, "date_quote": deadline[0]["quote"], "exact": True, "token": APPLICANT_DEADLINE_TOKENS[0]}]
    if status not in ("open", "rolling", "opening_soon"):
        evidence = {}
        if windows and status == "closed":
            window = windows[0]
            evidence = {"programme_status": _evidence(window["quote"], seed["official_url"]), "deadline": _evidence(window["quote"], seed["official_url"])}
            if window["start"] != window["end"]:
                evidence["application_window"] = _evidence(window["quote"], seed["official_url"])
        return None, _observation(seed, checked, status, "no actionable applicant window" if status == "non_actionable" else "official applicant deadline passed", evidence)
    # Every surfaced state must retain the registry's official URL. Rolling
    # additionally needs a resolvable same-origin application URL; for open
    # and opening_soon, the exact official date window is sufficient evidence
    # and the official URL remains the action link (application_url may be null).
    if not formal or (status == "rolling" and not resolved_apply):
        return None, _observation(seed, checked, "non_actionable", "formal programme or resolvable application evidence is absent")

    window = windows[0] if windows else None
    status_quote = (_quote_with(text, ROLLING_TOKENS) if status == "rolling" else (window["quote"] if window else None))
    evidence = {"programme_name": {}, "organizer": {}, "official_url": {}, "programme_status": _evidence(status_quote, seed["official_url"]), "application": _evidence(apply_link[0] if apply_link else None, resolved_apply or seed["official_url"]), "application_url": _evidence(apply_link[0] if apply_link else None, resolved_apply or seed["official_url"]), "opening_date": {}, "deadline": {}, "funding": {}, "location": {}, "remote": {}, "international_eligibility": {}, "eligibility": {}}
    record = _base(seed, checked, evidence, config)
    record["application_url"] = resolved_apply
    record["programme_status"] = status
    if window:
        record["opening_date"] = window["start"].isoformat()
        record["deadline"] = window["end"].isoformat() if window["end"] != window["start"] else None
        evidence["opening_date"] = _evidence(window["quote"], seed["official_url"])
        evidence["deadline"] = _evidence(window["quote"], seed["official_url"])
        if record.get("deadline") is None and record.get("opening_date"):
            deadline_evidence = evidence.get("deadline", {})
            opening_evidence = evidence.get("opening_date", {})
            deadline_quote = str(deadline_evidence.get("quote", ""))
            opening_quote = str(opening_evidence.get("quote", ""))
            opening_signal = re.search(r"\b(?:open(?:ing)?|start(?:s|ed|ing)?|begin(?:s|ning)?)\b", opening_quote, re.I)
            if "deadline" in deadline_quote.lower():
                parsed_date = record["opening_date"]
                record["deadline"] = parsed_date
                if not opening_signal:
                    record["opening_date"] = None
    funding = _quote_with(text, ("stipend", "paid", "unpaid", "funded", "$"))
    remote = _quote_with(text, ("remote",), 3)
    international = _quote_with(text, ("worldwide", "international"), 3)
    eligibility = _quote_with(text, ("eligibility", "eligible", "who can apply"), 4)
    if funding:
        record["funding"], evidence["funding"] = funding, _evidence(funding, seed["official_url"])
    if remote:
        record["location"], record["remote"], evidence["location"], evidence["remote"] = remote, True, _evidence(remote, seed["official_url"]), _evidence(remote, seed["official_url"])
    if international:
        record["international_eligibility"], evidence["international_eligibility"] = "confirmed", _evidence(international, seed["official_url"])
    if eligibility:
        record["eligibility"], evidence["eligibility"] = eligibility, _evidence(eligibility, seed["official_url"])
    return record, _observation(seed, checked, "actionable", "generic evidence-based applicant window", evidence)


def _default_fetch(url: str) -> Tuple[str, str]:
    from pipeline.resolve import _fetch_page
    status, final_url, html, error = _fetch_page(url)
    if error or status is None or status >= 400:
        raise RuntimeError(error or "http_{}".format(status))
    return html, final_url


def _atomic_json(path: str, value) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".programmes-", dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(value, handle, indent=1)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _load_json(path: str, default):
    if not os.path.exists(path):
        return default
    with open(path) as handle:
        value = json.load(handle)
    if not isinstance(value, type(default)):
        raise ValueError("invalid JSON shape in {}".format(path))
    return value


def load_verifications(path: str) -> List[Dict]:
    """Load manually authored programme verification records."""
    return _load_json(path, [])


def validate_verification(rec: Dict) -> Tuple[bool, str]:
    """Require official quote and URL evidence for every asserted status/date."""
    if not isinstance(rec, dict):
        return False, "record must be an object"
    programme_id = rec.get("programme_id")
    if not programme_id:
        return False, "programme_id is required"
    evidence = rec.get("official_evidence")
    if not isinstance(evidence, dict):
        evidence = {}
    evidence_keys = {
        "programme_status": ("status",),
        "opening_date": ("opening_date", "status"),
        "deadline": ("deadline",),
    }
    for field, keys in evidence_keys.items():
        if field not in rec or rec[field] in (None, ""):
            continue
        entry = next((evidence.get(key) for key in keys if evidence.get(key) is not None), None)
        if not isinstance(entry, dict) or not str(entry.get("quote", "")).strip() or not str(entry.get("url", "")).strip():
            return False, "{} requires non-empty quote and url evidence ({})".format(field, ", ".join(keys))
    return True, ""


def _timestamp(value) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds")
    return str(value)


def _later_timestamp(existing, candidate: str) -> str:
    existing_value = _timestamp(existing)
    if not existing_value:
        return candidate
    try:
        left = datetime.fromisoformat(existing_value.replace("Z", "+00:00"))
        right = datetime.fromisoformat(candidate.replace("Z", "+00:00"))
        return existing_value if left >= right else candidate
    except (TypeError, ValueError):
        return candidate


def apply_verifications(rows: Iterable[Dict], verifications: Iterable[Dict], now, *, config: ProgrammeConfig) -> List[Dict]:
    """Overlay valid manual facts, retaining all unrelated lake rows."""
    now_value = _timestamp(now) or datetime.now(timezone.utc).isoformat(timespec="seconds")
    result = deepcopy(list(rows))
    source_by_id = {seed["programme_id"]: seed for seed in config.source_registry}
    overlay_fields = (
        "programme_status", "opening_date", "deadline", "eligibility", "funding",
        "remote", "international_eligibility", "official_url", "application_url",
        "opportunity_type", "verification_note",
    )
    for verification in verifications:
        valid, reason = validate_verification(verification)
        if not valid:
            identifier = verification.get("programme_id") if isinstance(verification, dict) else None
            print("Skipping invalid programme verification {}: {}".format(identifier or "<missing id>", reason), file=sys.stderr)
            continue
        programme_id = verification["programme_id"]
        row = next((item for item in result if item.get("record_type") == "programme" and item.get("programme_id") == programme_id), None)
        verified_at = _timestamp(verification.get("verified_at")) or now_value
        verified_by = verification.get("verified_by") or "manual-verification"
        seed = source_by_id.get(programme_id, {})
        if row is None:
            row = {
                "record_type": "programme",
                "category": config.category,
                "opportunity_type": config.opportunity_type,
                "programme_id": programme_id,
                "programme_name": seed.get("programme_name") or verification.get("programme_name") or verification.get("name") or programme_id,
                "organizer": seed.get("organizer") or verification.get("organizer") or "not_stated",
                "official_url": seed.get("official_url") or verification.get("official_url"),
                "application_url": None,
                "programme_status": "non_actionable",
                "opening_date": None,
                "deadline": None,
                "location": "not_stated",
                "remote": None,
                "international_eligibility": "needs_confirmation",
                "funding": "not_stated",
                "eligibility": "needs_confirmation",
                "official_evidence": {},
                "source_confirmation": "official_source",
                "source_mechanism": "manual-verification",
                "first_seen": now_value,
                "last_seen": now_value,
            }
            result.append(row)
        for field in overlay_fields:
            if field in verification:
                row[field] = verification[field]
        existing_evidence = row.get("official_evidence")
        merged_evidence = dict(existing_evidence) if isinstance(existing_evidence, dict) else {}
        verification_evidence = verification.get("official_evidence")
        if isinstance(verification_evidence, dict):
            merged_evidence.update(verification_evidence)
        row["official_evidence"] = merged_evidence
        row["manually_verified"] = True
        row["verified_at"] = verified_at
        row["verified_by"] = verified_by
        row["last_checked_at"] = _later_timestamp(row.get("last_checked_at"), verified_at)
        row["source_mechanism"] = "manual-verification"
        status = row.get("programme_status")
        if status in ("live", "open", "opening_soon"):
            row["is_live"] = True
        elif status in ("closed", "ended"):
            row["is_live"] = False
            if not row.get("went_dead_at"):
                row["went_dead_at"] = now_value
    return result


def merge_programmes(records: Iterable[Dict], observations: Iterable[Dict], lake_path: str = OPPORTUNITIES_PATH, observations_path: str = None, now: Optional[str] = None) -> List[Dict]:
    now = now or datetime.now(timezone.utc).isoformat(timespec="seconds")
    lake = _load_json(lake_path, [])
    programme_rows = {r.get("programme_id"): r for r in lake if r.get("record_type") == "programme" and r.get("programme_id")}
    jobs = [r for r in lake if r.get("record_type") != "programme"]
    records, observed = list(records), list(observations)
    for record in records:
        old = programme_rows.get(record["programme_id"])
        if old:
            first_seen = old.get("first_seen", now)
            old.update(record)
            old.update({"first_seen": first_seen, "last_seen": now, "is_live": True})
        else:
            record = dict(record)
            record.update({"first_seen": now, "last_seen": now, "is_live": True})
            programme_rows[record["programme_id"]] = record
    successful_sources = {o["official_url"] for o in observed if o.get("result") == "non_actionable"}
    current_ids = {r.get("programme_id") for r in records}
    for row in programme_rows.values():
        if row.get("official_url") in successful_sources and row.get("programme_id") not in current_ids and row.get("is_live", True):
            row["is_live"], row["went_dead_at"] = False, now
    merged = jobs + list(programme_rows.values())
    _atomic_json(lake_path, merged)
    prior = _load_json(observations_path, [])
    _atomic_json(observations_path, prior + observed)
    return merged


def collect(config: ProgrammeConfig, fetch: Callable[[str], str] = _default_fetch, checked_at: Optional[datetime] = None, lake_path: str = OPPORTUNITIES_PATH, observations_path: Optional[str] = None) -> Dict:
    records, observations = [], []
    for seed in config.source_registry:
        try:
            fetched = fetch(seed["official_url"])
            html, final_url = fetched if isinstance(fetched, tuple) else (fetched, None)
            record, observation = parse_programme(seed, html, checked_at, final_url, config=config)
        except Exception as exc:
            checked = (checked_at or datetime.now(timezone.utc)).isoformat(timespec="seconds")
            observation = _observation(seed, checked, "failed", "{}: {}".format(type(exc).__name__, str(exc)[:160]))
            record = None
        if record:
            records.append(record)
        observations.append(observation)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    merged = merge_programmes(records, observations, lake_path, observations_path or config.observations_path, now)
    verification_now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    merged = apply_verifications(merged, load_verifications(config.verifications_path), verification_now, config=config)
    _atomic_json(lake_path, merged)
    return {"records": records, "observations": observations, "merged_count": len(merged)}


def _apply_verifications_cli(config: ProgrammeConfig) -> None:
    rows = _load_json(OPPORTUNITIES_PATH, [])
    verifications = load_verifications(config.verifications_path)
    valid_count = sum(1 for verification in verifications if validate_verification(verification)[0])
    updated = apply_verifications(rows, verifications, datetime.now(timezone.utc).isoformat(timespec="seconds"), config=config)
    _atomic_json(OPPORTUNITIES_PATH, updated)
    print(json.dumps({"verification_records": len(verifications), "valid_records": valid_count, "programme_rows": sum(1 for row in updated if row.get("record_type") == "programme")}, indent=2))


def run_module_cli(config: ProgrammeConfig, argv=None) -> None:
    args = sys.argv[1:] if argv is None else argv
    if "--apply-verifications" in args:
        _apply_verifications_cli(config)
    else:
        result = collect(config)
        print(json.dumps({"records": len(result["records"]), "observations": len(result["observations"])}, indent=2))
