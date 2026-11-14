"""Generic date, status and quote logic for opportunity pages (stdlib only).

Pure functions on page text: no seeds, no category config, no lake/S3 access.
Moved verbatim out of categories/programme_core.py; that module re-exports every name."""
from __future__ import annotations

import re
import unicodedata
from datetime import date
from typing import Dict, Iterable, List, Optional, Tuple

MONTHS = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)

MONTH_PATTERN = "|".join(MONTHS) + "|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sept|Sep|Oct|Nov|Dec"

APPLICANT_ACTION_TOKENS = (
    "applications open", "apply now", "apply by", "application deadline",
    "applications close", "applications are accepted", "applications accepted",
    "intern applications", "contributor applications", "application period",
    "rolling basis", "applications are rolling", "processed on a rolling basis",
)

# These are deliberately data, not source adapters.  Each cue is checked
# against a nearby date before it can create an applicant window.
APPLICANT_DEADLINE_TOKENS = (
    "deadline for the contributors applications",
    "application deadline", "applicant deadline", "applicant deadlines",
    "applications are due", "applications due", "application is due",
    "nominations due", "nomination deadline", "hard deadline",
    "cutoff date", "cut-off date", "application close on",
    "applications close on", "application closes on", "applications closes on",
    "application close at", "applications close at", "application closes at",
    "applications closes at", "application closed at", "applications closed at",
    "submission deadline", "deadline to apply", "apply by",
    "applications close", "application close", "applications closed", "application closed",
    "closes on", "close on", "closing date", "last date", "last day to apply",
    "last day for applications", "due date", "due by", "due on", "submit by",
    "submitted by", "received by", "apply until", "applications until",
    "open until", "accepted until", "accepting applications until", "available until",
    "is due", "are due", "deadline",
    "registration deadline", "registrations close", "registration closes", "registrations closes",
    "registration ends", "registrations end", "registration close", "last date to register",
    "register by", "registrations until", "registration until", "apply before", "applications end",
    "applications will close", "applications will be accepted until",
)

_DEADLINE_EXCLUSION_TOKENS = (
    "recommend", "reference", "referee", "letter", "mentor", "mentoring",
    "sign-up", "sign up", "host organi", "organisation sign", "organization sign",
    "notif", "announce", "decision", "interview", "webinar", "info session",
    "information session", "orientation", "refund", "payment", "tuition due",
)

ORGANIZER_WINDOW_TOKENS = (
    "mentor sign up", "mentors sign up", "mentoring organization",
    "mentoring organisation", "accepting proposals", "project submission",
    "mentor applications", "organization registration", "organisation registration",
    "call for mentors", "call for projects",
)

ROLLING_TOKENS = (
    "rolling basis", "applications are rolling", "rolling application", "processed on a rolling basis",
    "rolling admission", "accepted year-round", "accepted year round", "apply year-round",
    "accepting applications year", "applications year-round", "no deadline", "apply anytime", "apply any time",
)

_LEXICAL_RELEVANCE_TOKENS = ("application", "apply", "admission", "enrollment", "enrolment", "registration", "deadline", "eligibility", "cohort", "fellowship", "fellows", "programme", "program")

_CLOSED_PATTERNS = (
    re.compile(r"\bapplications?\s+(?:are\s+)?now\s+closed\b", re.I),
    re.compile(r"\bapplications?\s+(?:are\s+)?closed\b", re.I),
    re.compile(r"\bno\s+longer\s+accepting\s+applications?\b", re.I),
    re.compile(r"\bclosed\s+for\s+(?:20\d{2}(?:\s*/\s*20\d{2})?|the\s+20\d{2}\s+(?:cohort|cycle))\b", re.I),
)

_GENERIC_CLOSED_PATTERN = re.compile(r"\bnow\s+closed\b", re.I)

_CLOSED_CONTEXT_PATTERN = re.compile(r"\b(?:applications?|admissions?|enro(?:l|ll)ments?|registrations?)\b", re.I)

_OPENING_PATTERNS = (
    re.compile(r"\bapplications?\s+open\s+in\s+(?:20\d{2}|(?:January|February|March|April|May|June|July|August|September|October|November|December)\b)", re.I),
    re.compile(r"\bopens?\s+(?:on\s+)?(?:20\d{2}|(?:January|February|March|April|May|June|July|August|September|October|November|December)\b)", re.I),
    re.compile(r"\bcheck\s+back\b", re.I),
    re.compile(r"\bwill\s+open\b", re.I),
)

def _month_number(name: str) -> int:
    prefix = name.capitalize()[:3]
    for index, month in enumerate(MONTHS):
        if month.startswith(prefix):
            return index + 1
    raise ValueError(name)

_ORD = r"(?:st|nd|rd|th)?"

_PAST_HINT = re.compile(r"\b(?:closed|ended|passed|expired|concluded|was|were)\b", re.I)

def _infer_date(month: str, day: str, year: Optional[str], nearby_year: Optional[int],
                today: Optional[date], past_hint: bool) -> Tuple[Optional[date], bool]:
    """Build a date; infer a missing year (nearby year, else next/last occurrence)."""
    month_no = _month_number(month) if not str(month).isdigit() else int(month)
    try:
        if year:
            return date(int(year), month_no, int(day)), False
        if nearby_year is not None:
            return date(nearby_year, month_no, int(day)), False
        if today is None:
            return None, False
        candidate = date(today.year, month_no, int(day))
        if past_hint:
            if candidate > today:
                candidate = date(today.year - 1, month_no, int(day))
        elif candidate < today:
            candidate = date(today.year + 1, month_no, int(day))
        return candidate, True
    except ValueError:
        return None, False

def parse_dates(text: str, nearby_year: Optional[int] = None, today: Optional[date] = None,
                past_hint: Optional[bool] = None) -> List[Dict]:
    """Parse supported dates/ranges into ``start``, ``end`` and exactness.

    Handles ``Jan 15, 2027``, ``15 January 2027``, ``January 15th``, ISO and
    numeric dates (``1/15/2027`` US month-first, ``15.01.2027`` day-first).
    A missing year is taken from ``nearby_year``, else (when ``today`` is given)
    inferred as the next occurrence, or the last one for past-tense text.
    """
    results: List[Dict] = []
    if past_hint is None:
        past_hint = bool(_PAST_HINT.search(text or ""))
    range_re = re.compile(
        rf"\b(?P<sm>{MONTH_PATTERN})\s+(?P<sd>\d{{1,2}}){_ORD}\s*(?:[–—-]|\bto\b)\s*"
        rf"(?P<em>{MONTH_PATTERN})?\s*(?P<ed>\d{{1,2}}){_ORD}(?:,?\s*(?P<year>20\d{{2}}))?\b", re.I)
    consumed: List[Tuple[int, int]] = []

    def add(match, value, exact, inferred=False):
        item = {"start": value[0], "end": value[1], "quote": match.group(0), "exact": exact, "span": match.span()}
        if inferred:
            item["inferred"] = True
        results.append(item)
        consumed.append(match.span())

    def free(match) -> bool:
        return not any(a <= match.start() < b for a, b in consumed)

    for match in range_re.finditer(text):
        start, inf1 = _infer_date(match.group("sm"), match.group("sd"), match.group("year"), nearby_year, today, past_hint)
        end, inf2 = _infer_date(match.group("em") or match.group("sm"), match.group("ed"), match.group("year"), nearby_year, today, past_hint)
        if start and end:
            if end < start and inf1 and inf2:
                end = date(end.year + 1, end.month, end.day)
            add(match, (start, end), True, inf1 or inf2)
    iso_re = re.compile(r"\b(?P<year>20\d{2})-(?P<month>\d{2})-(?P<day>\d{2})\b")
    for match in iso_re.finditer(text):
        try:
            value = date(int(match.group("year")), int(match.group("month")), int(match.group("day")))
        except ValueError:
            continue
        add(match, (value, value), True)
    numeric_re = re.compile(r"(?<![\d/.-])(?P<a>\d{1,2})(?P<sep>[/.-])(?P<b>\d{1,2})(?P=sep)(?P<y>20\d{2}|\d{2})(?![\d/-])")
    for match in numeric_re.finditer(text):
        if not free(match):
            continue
        if match.group("sep") == "-" and len(match.group("y")) != 4:
            continue  # "30-11-26" is too ambiguous; only dash dates with a 4-digit year
        a, b = int(match.group("a")), int(match.group("b"))
        year = int(match.group("y"))
        year += 2000 if year < 100 else 0
        month, day = (b, a) if (match.group("sep") in ".-" or a > 12) else (a, b)
        try:
            value = date(year, month, day)
        except ValueError:
            continue
        add(match, (value, value), True)
    day_first_re = re.compile(
        rf"\b(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)?\s*"
        rf"(?P<day>\d{{1,2}}){_ORD}\s+(?:of\s+)?(?P<month>{MONTH_PATTERN})(?:,?\s+(?P<year>20\d{{2}}))?\b", re.I)
    for match in day_first_re.finditer(text):
        if not free(match):
            continue
        value, inferred = _infer_date(match.group("month"), match.group("day"), match.group("year"), nearby_year, today, past_hint)
        if value:
            add(match, (value, value), bool(match.group("year")), inferred)
    full_re = re.compile(rf"\b(?P<month>{MONTH_PATTERN})\s+(?P<day>\d{{1,2}}){_ORD},?\s+(?P<year>20\d{{2}})\b", re.I)
    for match in full_re.finditer(text):
        if not free(match):
            continue
        value, _ = _infer_date(match.group("month"), match.group("day"), match.group("year"), None, None, False)
        if value:
            add(match, (value, value), True)
    short_re = re.compile(rf"\b(?P<month>{MONTH_PATTERN})\s+(?P<day>\d{{1,2}}){_ORD}\b", re.I)
    for match in short_re.finditer(text):
        if not free(match):
            continue
        value, inferred = _infer_date(match.group("month"), match.group("day"), None, nearby_year, today, past_hint)
        if value:
            results.append({"start": value, "end": value, "quote": match.group(0), "exact": False, "span": match.span(),
                            **({"inferred": True} if inferred else {})})
    return sorted(results, key=lambda item: item["span"][0])

def _deadline_cue_matches(sentence: str) -> List[Tuple[int, int, str]]:
    lowered = sentence.casefold()
    matches = []
    for token in APPLICANT_DEADLINE_TOKENS:
        value = token.casefold()
        start = lowered.find(value)
        while start >= 0:
            matches.append((start, start + len(value), token))
            start = lowered.find(value, start + 1)
    return sorted(set(matches), key=lambda item: (item[0], -(item[1] - item[0])))

def _deadline_candidate(sentence: str, nearby_year: Optional[int] = None, today: Optional[date] = None) -> Optional[Dict]:
    """Return the first non-excluded deadline cue with a nearby date."""
    for cue_start, cue_end, token in _deadline_cue_matches(sentence):
        tail = sentence[cue_end:min(len(sentence), cue_end + 100)]
        past = bool(_PAST_HINT.search(sentence[max(0, cue_start - 30):cue_end] + " " + tail))
        for parsed in parse_dates(tail, nearby_year, today, past):
            date_start = cue_end + parsed["span"][0]
            before_date = sentence[max(0, date_start - 60):date_start].casefold()
            if any(exclusion in before_date for exclusion in _DEADLINE_EXCLUSION_TOKENS):
                continue
            return {"token": token, "parsed": parsed, "cue_start": cue_start, "cue_end": cue_end}
    return None

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
    for match in re.finditer(r"(?:[^.!?\n]|(?<=\d)\.(?=\d))+(?:[.!?]|$)", text, re.M):
        yield match.start(), match.end(), match.group(0).strip()

_ABBREV_DOT = re.compile(r"\b(Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sept|Sep|Oct|Nov|Dec)\.(?=\s*\d)")

# "PhD must be received by <date>": a degree-date eligibility rule, not an application deadline.
_APPLY_WORD = re.compile(r"\b(?:applic\w*|apply|nominat\w*|submi\w*|deadline)", re.I)

_DEGREE_DATE = re.compile(r"\b(?:ph\.?d|doctora(?:te|l)|degree|cannot be received before)\b", re.I)

def detect_applicant_windows(text: str, today: Optional[date] = None) -> List[Dict]:
    """Find dated applicant windows while rejecting organizer/mentor dates."""
    candidates: List[Dict] = []
    normalized = _ABBREV_DOT.sub(r"\1", text.replace("\xa0", " "))
    sentence_list = list(_sentences(normalized))
    for index, (start, end, sentence) in enumerate(sentence_list):
        lowered = sentence.lower()
        # Deadline cues are stricter than the older action vocabulary: a date
        # must follow the cue in this sentence, and organizer language near it
        # must not turn a recommendation/mentor date into an applicant date.
        organizer_positions = [lowered.find(token) for token in ORGANIZER_WINDOW_TOKENS if token in lowered]
        candidate_sentence = sentence[:min(organizer_positions)] if organizer_positions else sentence
        deadline_cues = _deadline_cue_matches(candidate_sentence)
        if deadline_cues:
            nearby_year = _year_near(normalized, start)
            candidate = _deadline_candidate(candidate_sentence, nearby_year, today)
            if not candidate and not organizer_positions and index + 1 < len(sentence_list):
                # "Application deadline" / "January 15, 2027" rendered as two table cells.
                following = sentence_list[index + 1][2]
                if len(following) <= 90 and len(candidate_sentence) <= 60:
                    combined = candidate_sentence.rstrip(".") + ": " + following
                    candidate = _deadline_candidate(combined, nearby_year, today)
                    if candidate:
                        candidate_sentence = combined
            if not candidate:
                continue
            parsed = candidate["parsed"]
            candidates.append({
                "start": parsed["start"], "end": parsed["end"],
                "quote": candidate_sentence.strip() if candidate_sentence else parsed["quote"],
                "date_quote": parsed["quote"],
                "exact": parsed["exact"] or nearby_year is not None or bool(parsed.get("inferred")),
                "token": candidate["token"], "deadline_cue": True,
                "basis": "applicant_deadline_inferred_year" if parsed.get("inferred") else "applicant_deadline",
            })
            continue
        positive = [token for token in APPLICANT_ACTION_TOKENS if token in lowered]
        if not positive:
            continue
        # A page may put an applicant event and an organizer event in one
        # rendered block. Only the text attached to the applicant token is a
        # candidate; an organizer-only block never reaches this point.
        dates = parse_dates(candidate_sentence, _year_near(normalized, start), today)
        if not dates:
            # Dates can sit on an adjacent line or heading, but remain close.
            left, right = max(0, start - 120), min(len(normalized), end + 120)
            context = normalized[left:right]
            if any(token in context.lower() for token in ORGANIZER_WINDOW_TOKENS):
                continue
            dates = parse_dates(context, _year_near(normalized, start), today)
            from_context = True
        else:
            from_context = False
        for parsed in dates:
            quote = candidate_sentence.strip() if candidate_sentence else parsed["quote"]
            if from_context:
                # The sentence is only a heading ("General Application Period."):
                # quote the line that holds the date, with the heading as its label.
                line = next((ln.strip() for ln in context.split("\n") if parsed["quote"] in ln), parsed["quote"])
                label = quote.rstrip(".:; ")
                quote = line if parsed["quote"] and label and label.lower() in line.lower() else (label + ": " + line if label else line)
                quote = quote[:200]
            candidates.append({"start": parsed["start"], "end": parsed["end"], "quote": quote, "date_quote": parsed["quote"], "exact": parsed["exact"], "token": positive[0], "basis": "application_window"})
    # Preserve order and avoid a duplicated date discovered through adjacent context.
    unique = {}
    for candidate in candidates:
        unique[(candidate["start"], candidate["end"], candidate["quote"])] = candidate
    return list(unique.values())

_OPEN_NOW_PATTERNS = (
    re.compile(r"\bapplications?\s+(?:are\s+|is\s+)?(?:now\s+|currently\s+)?open\b(?!\s+(?:on|in|from|soon|for\s+(?:the\s+)?(?:next|upcoming)))", re.I),
    re.compile(r"\b(?:now|currently)\s+(?:accepting|taking)\s+applications?\b", re.I),
    re.compile(r"\bcall\s+for\s+applications?\s+(?:is\s+)?(?:now\s+)?open\b", re.I),
    re.compile(r"\bapply\s+now\s+for\b", re.I),
)

_OPEN_NEGATION = re.compile(r"\b(?:not|no\s+longer|never|until|once|when|will|soon|closed|were|was)\b", re.I)

def _open_now_sentence(sentence: str) -> bool:
    return any(p.search(sentence) for p in _OPEN_NOW_PATTERNS) and not _OPEN_NEGATION.search(sentence)

def _open_now(text: str) -> bool:
    return any(_open_now_sentence(sentence) for _, _, sentence in _sentences(text))

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
            if window.get("deadline_cue") and _open_now(text):
                return "open"
            return "opening_soon"
    return "non_actionable"

def _clean_quote(quote: Optional[str]) -> str:
    if not quote:
        return ""
    normalized = unicodedata.normalize("NFKC", str(quote))
    return re.sub(r"\s+", " ", normalized).strip()

def is_quality_evidence(quote: Optional[str]) -> bool:
    """Return whether text is a meaningful programme-related human quote."""
    cleaned = _clean_quote(quote)
    if not cleaned or re.fullmatch(r"https?://\S+", cleaned, re.I):
        return False
    if re.search(r"[{};]|(?:^|\s)[.#][\w-]+|[\w-]+\s+h[1-6]\s*,?$", cleaned, re.I):
        return False
    words = re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ0-9]+", cleaned)
    if len(words) < 2 or len(cleaned) < 8:
        return False
    # Short punctuated headings/titles are not programme evidence.
    if len(words) <= 2 and cleaned.endswith((".", "!", "?")):
        return False
    lowered = cleaned.casefold()
    anchors = ("application", "apply", "deadline", "eligibility", "admission", "enrollment", "enrolment", "registration", "fellowship", "fellows", "programme", "program", "funding", "stipend")
    strong_anchors = ("application", "apply", "deadline", "eligibility", "admission", "enrollment", "enrolment", "registration", "funding", "stipend")
    if len(words) <= 4 and not any(anchor in lowered for anchor in strong_anchors):
        return False
    return any(anchor in lowered for anchor in anchors) or bool(re.search(r"[.!?]$", cleaned) and len(words) >= 8)

def _lexical_status(text: str, today: date) -> Tuple[Optional[str], Optional[str]]:
    """Return a high-confidence sentence-scoped lexical status, if present."""
    for _, _, sentence in _sentences(text):
        lowered = sentence.casefold()
        relevant = any(token in lowered for token in _LEXICAL_RELEVANCE_TOKENS)
        if not relevant or not is_quality_evidence(sentence):
            continue
        closed = any(pattern.search(sentence) for pattern in _CLOSED_PATTERNS)
        if not closed:
            generic_closed = _GENERIC_CLOSED_PATTERN.search(sentence)
            if generic_closed:
                nearby = sentence[max(0, generic_closed.start() - 96):generic_closed.start()]
                nearby += sentence[generic_closed.end():generic_closed.end() + 96]
                closed = bool(_CLOSED_CONTEXT_PATTERN.search(nearby))
        if closed:
            return "closed", _clean_quote(sentence)
        if _open_now_sentence(sentence):
            return "open", _clean_quote(sentence)
        if not any(pattern.search(sentence) for pattern in _OPENING_PATTERNS):
            continue
        # Explicit month/year signals are only opening-soon evidence when they
        # are demonstrably in the future.  Do not invent a day or a date.
        year_match = re.search(r"\b(20\d{2})\b", sentence)
        month_match = re.search(rf"\b({MONTH_PATTERN})\b", sentence, re.I)
        if year_match and int(year_match.group(1)) < today.year:
            continue
        if year_match and int(year_match.group(1)) == today.year and month_match:
            if _month_number(month_match.group(1)) < today.month:
                continue
        if month_match and not year_match and _month_number(month_match.group(1)) < today.month:
            continue
        return "opening_soon", _clean_quote(sentence)
    return None, None

def _quote_with(text: str, tokens: Iterable[str], minimum_words: int = 1, prefer_relevant: bool = False, deadline_cues: bool = False) -> Optional[str]:
    candidates = []
    token_values = tuple(token.casefold() for token in tokens)
    for start, _, sentence in _sentences(text):
        lowered = sentence.casefold()
        if deadline_cues:
            if not _deadline_candidate(sentence, _year_near(text, start)):
                continue
        elif not any(token in lowered for token in token_values):
            continue
        if len(re.findall(r"\b\w+\b", sentence)) < minimum_words:
            continue
        cleaned = _clean_quote(sentence)
        if is_quality_evidence(cleaned):
            relevant = any(token in lowered for token in _LEXICAL_RELEVANCE_TOKENS)
            candidates.append((not (prefer_relevant and relevant), cleaned))
    if candidates:
        candidates.sort(key=lambda item: item[0])
        return candidates[0][1]
    return None

_RECUR = re.compile(r"\b(?:every\s+(?:year|january|february|march|april|may|june|july|august|september|october|november|december)|each\s+year|annually|yearly)\b", re.I)

_OPENS_VERB = re.compile(r"\b(?:opens?|begins?|launch(?:es)?|starts?|accepting)\b", re.I)

_MONTH_NUM = {m.lower(): i + 1 for i, m in enumerate(MONTHS)}

def detect_opens_pattern(text: str, url: str) -> Optional[Dict]:
    """An explicit recurring opening statement ("applications open every September",
    "opens annually on 1 March") as {month, day|None, quote, url}. Only explicit
    every/each year/annually/yearly wording plus a month; never inferred from dates."""
    for _, _, sentence in _sentences(_ABBREV_DOT.sub(r"\1", text.replace("\xa0", " "))):
        if len(sentence) > 200 or not _RECUR.search(sentence) or not _OPENS_VERB.search(sentence):
            continue
        if re.search(r"\b(?:deadline|clos(?:e|es|ing)|due)\b", sentence, re.I):
            continue
        m = re.search(rf"\b(?:(?P<d1>\d{{1,2}}){_ORD}\s+(?:of\s+)?(?P<m1>{MONTH_PATTERN})|(?P<m2>{MONTH_PATTERN})(?:\s+(?P<d2>\d{{1,2}}){_ORD})?)\b(?!\s+\d{{4}})", sentence, re.I)
        if not m:
            continue
        month = _MONTH_NUM.get((m.group("m1") or m.group("m2")).lower())
        day = int(m.group("d1") or m.group("d2") or 0) or None
        if month and (day is None or 1 <= day <= 31):
            return {"month": month, "day": day, "quote": _clean_quote(sentence), "url": url}
    return None

def quote_has_date(quote: Optional[str], iso_date: Optional[str]) -> bool:
    """True when ``quote`` writes out ``iso_date`` (month name/abbrev + day, day +
    month, ISO or numeric forms; the year may come from the quote or the date)."""
    if not quote or not iso_date:
        return False
    try:
        want = date.fromisoformat(str(iso_date)[:10])
    except ValueError:
        return False
    return any(want in (p["start"], p["end"]) for p in parse_dates(str(quote), want.year))

_NOT_OPENING = re.compile(r"\b(?:clos(?:e|es|ed|ing)|deadlines?|due|notif\w*|decisions?|announce\w*|results?|interviews?|programme?s?\s+(?:dates?|starts?|begins?)|start\s+dates?|orientation|arrival)\b", re.I)

_OPENING_CUE = re.compile(r"\bopen(?:s|ing)?\b|\bbegin(?:s)?\b|\bstarts?\s+accepting|\blaunch\w*|\baccepted\s+between|\bapplication\s+(?:period|window)|\bonline\s+application|\bfrom\s*$", re.I)

OPENING_QUOTE_MAX = 220

def _opening_ok(quote: str, want: date) -> bool:
    if len(quote) > OPENING_QUOTE_MAX:
        return False
    for p in parse_dates(quote, want.year):
        if p["start"] != want:
            continue
        a, b = p["span"]
        before, after = quote[max(0, a - 70):a], quote[b:b + 30]
        if re.search(r"(?:[–—-]|\bto\b)\s*$", before):
            continue  # the second date of a window is its end
        if _NOT_OPENING.search(before[-50:] + " " + after[:25]):
            continue
        if _OPENING_CUE.search(before + " " + after):
            return True
    return False

def official_opening_quote(quote: Optional[str], iso_date: Optional[str]) -> Optional[str]:
    """The quote (trimmed to the single sentence/line holding the date when long)
    if it is an official OPENING statement for ``iso_date``: it has the date as the
    first/only date, an opening cue next to it, and no close/deadline/decision/
    programme-start wording next to it. Else None."""
    quote = _clean_quote(quote)
    if not quote or not iso_date:
        return None
    try:
        want = date.fromisoformat(str(iso_date)[:10])
    except ValueError:
        return None
    parts = [x.strip() for x in re.split(r"(?<=[.!?])\s+", quote) if x.strip()]
    options = [" ".join(parts[i:i + n]) for n in (1, 2, 3) for i in range(len(parts) - n + 1)]
    for piece in sorted(options, key=len) + [quote]:
        if _opening_ok(piece, want):
            return piece
    return None

_RANGE_JOIN = re.compile(r"^\s*(?:[-\u2013\u2014]|to|through|until|and)\s*$", re.I)

def closing_from_opening_quote(quote: Optional[str], iso_date: Optional[str]) -> Optional[str]:
    """ISO end date when ``quote`` states a range "<opening date> - <end date>" whose
    opening date is written with a year; a missing end year is the opening year and
    needs an end month no earlier than the start month. Else None."""
    if not quote or not iso_date:
        return None
    try:
        start = date.fromisoformat(str(iso_date)[:10])
    except ValueError:
        return None
    first = parse_dates(quote)
    if not first or first[0]["start"] != start:
        return None
    dates = first if len(first) > 1 else parse_dates(quote, nearby_year=start.year)
    if len(dates) != 2 or dates[0]["start"] != start:
        return None
    a, b = dates
    if not _RANGE_JOIN.match(quote[a["span"][1]:b["span"][0]]):
        return None
    end = b["start"]
    return end.isoformat() if end > start and (len(first) > 1 or end.month >= start.month) else None

def _evidence(quote: Optional[str], url: str) -> Dict:
    cleaned = _clean_quote(quote)
    return {"quote": cleaned, "url": url} if is_quality_evidence(cleaned) else {}
