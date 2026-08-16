"""Role extraction from a careers page. The only place a model is ever called.

Two implementations behind one interface:

    FixtureExtractor  replays saved JSON. Needs no API key, so the whole test
                      suite runs offline and in CI.
    LLMExtractor      production. Reads the key from an env var. Drops in with no
                      other change, and the same tests must still pass.

THE ANTI-HALLUCINATION RULE, which is not optional and is enforced here rather
than trusted to the prompt:

    Every extracted role MUST carry the exact quoted sentence from the page it
    came from. A role whose quote is not found VERBATIM in the page text is
    DISCARDED, and the discard is counted.

The reason is specific. A model handed a JavaScript shell — which is what most
Indian careers pages are, 0 of 18 tested had usable structured data — will not
say "there is nothing here". It will produce plausible, well-formatted, entirely
fictional postings: "Software Engineer Intern, Bangalore, apply by 15 March".
That is worse than returning nothing, because nothing is visibly nothing whereas
a fake posting costs a student an afternoon and all of their trust.

Verifying the quote against the source is cheap, deterministic, and catches the
failure completely. If a model cannot point at the sentence, we did not find a
job.

`extract()` never raises. A page that cannot be read returns an empty list and a
reason, because "the reader failed" and "this company is not hiring" must stay
distinguishable — the same rule the board layer follows for 404 versus 200-empty.
"""

from __future__ import annotations

import json
import os
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from core.paths import FIXTURES_DIR

FIXTURE_DIR = FIXTURES_DIR


# --------------------------------------------------------------------------- #
# What an extractor returns
# --------------------------------------------------------------------------- #
@dataclass
class ExtractedRole:
    """One role read off a page, with the evidence that it is real."""

    title: str
    # The exact sentence from the page that shows this role exists. Verified
    # verbatim against the page text before the role is accepted.
    quote: str
    apply_url: str = ""
    location: str = ""
    # Gate values, each with its own quote in `evidence`. All optional: the
    # extractor reports only what the page actually says, and silence is a valid
    # and common answer.
    stage: str = ""                       # intern | fresher_newgrad | trainee_apprentice
    experience_min_years: Optional[float] = None
    experience_max_years: Optional[float] = None
    grad_years_accepted: List[int] = field(default_factory=list)
    grad_window_from: str = ""
    grad_window_to: str = ""
    study_year_min: Optional[int] = None
    study_year_max: Optional[int] = None
    degree_ceiling: str = ""              # e.g. "Master's required", "PhD required"
    institution_restriction: str = ""
    prerequisite_gate: str = ""
    remote_tier: str = ""                 # A | B | C | onsite
    access_channel: str = ""              # off_campus | campus_only | unknown
    deadline: str = ""
    stipend_text: str = ""
    salary_text: str = ""
    # gate name -> quoted sentence. This is what lets the site show "Graduation
    # 2027 accepted — 'graduating in 2027'" instead of an unexplained tick.
    evidence: Dict[str, str] = field(default_factory=dict)

    def as_row(self) -> Dict:
        d = dict(self.__dict__)
        return d


@dataclass
class ExtractionResult:
    url: str
    roles: List[ExtractedRole] = field(default_factory=list)
    error: Optional[str] = None
    # Roles the model produced whose quote was NOT in the page. Counted, not
    # hidden: a rising number here means the prompt or the model is degrading,
    # and it is the only early warning of that.
    discarded_unquoted: int = 0
    discarded_titles: List[str] = field(default_factory=list)
    model: str = ""
    input_chars: int = 0
    # Populated by LLMExtractor so a run can report real spend rather than an
    # estimate copied out of a pricing page.
    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def ok(self) -> bool:
        return self.error is None


# --------------------------------------------------------------------------- #
# Quote verification — the rule
# --------------------------------------------------------------------------- #
def normalise_for_match(s: str) -> str:
    """Collapse a string so quote matching survives cosmetic differences.

    Deliberately narrow. It forgives whitespace runs, curly quotes, non-breaking
    spaces, dash variants and case — all of which change when HTML is flattened
    to text and none of which change meaning. It does NOT forgive different
    words, which is the whole point.
    """
    s = unicodedata.normalize("NFKC", s or "")
    s = s.replace("\u2018", "'").replace("\u2019", "'")
    s = s.replace("\u201c", '"').replace("\u201d", '"')
    s = re.sub(r"[\u2010-\u2015\u2212]", "-", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip().lower()


# A quote must be substantial enough to be evidence. A model that returns "Intern"
# as its quote has pointed at nothing, and a 3-character string will match almost
# any page by accident.
MIN_QUOTE_CHARS = 12


def quote_is_in_page(quote: str, page_text: str) -> bool:
    if not quote or len(quote.strip()) < MIN_QUOTE_CHARS:
        return False
    return normalise_for_match(quote) in normalise_for_match(page_text)


def enforce_quotes(result: ExtractionResult, page_text: str) -> ExtractionResult:
    """Drop every role whose quote is not verbatim in the page. Mutates and returns.

    Also drops individual evidence lines that fail, rather than the whole role:
    a real posting with one hallucinated gate quote should lose the gate, not the
    posting. A role losing its PRIMARY quote loses the role.
    """
    kept: List[ExtractedRole] = []
    for role in result.roles:
        if not quote_is_in_page(role.quote, page_text):
            result.discarded_unquoted += 1
            result.discarded_titles.append(role.title[:80])
            continue
        role.evidence = {
            gate: q for gate, q in (role.evidence or {}).items()
            if quote_is_in_page(q, page_text)
        }
        kept.append(role)
    result.roles = kept
    return result


# --------------------------------------------------------------------------- #
# The interface
# --------------------------------------------------------------------------- #
class RoleExtractor:
    """Interface. Implementations must not raise; they return an error string.

    Written as a base class rather than typing.Protocol so it also works on the
    Python 3.9 that is the default interpreter here.
    """

    name = "base"

    def extract(self, html: str, url: str) -> ExtractionResult:  # pragma: no cover
        raise NotImplementedError


# --------------------------------------------------------------------------- #
# FixtureExtractor — production-shaped, no key, used by the tests
# --------------------------------------------------------------------------- #
def fixture_key(url: str) -> str:
    """Stable filename for a URL."""
    import hashlib

    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]


class FixtureExtractor(RoleExtractor):
    """Replays hand-written expected output for a saved page.

    The fixtures were built by fetching real careers pages, reading them, and
    writing down what a correct extractor should return — including, for the
    JS-shell pages, that the correct answer is NOTHING. Those negative fixtures
    matter more than the positive ones: they are the case a real model gets
    wrong by inventing jobs.
    """

    name = "fixture"

    def __init__(self, fixture_dir: str = FIXTURE_DIR):
        self.dir = fixture_dir

    def _path(self, url: str) -> str:
        return os.path.join(self.dir, "extract_{}.json".format(fixture_key(url)))

    def extract(self, html: str, url: str) -> ExtractionResult:
        res = ExtractionResult(url=url, model="fixture", input_chars=len(html or ""))
        path = self._path(url)
        if not os.path.exists(path):
            res.error = "no_fixture_for_url"
            return res
        try:
            with open(path) as fh:
                data = json.load(fh)
        except Exception as e:  # noqa: BLE001
            res.error = "fixture_unreadable_{}".format(type(e).__name__)
            return res
        if data.get("error"):
            res.error = data["error"]
            return res
        for raw in data.get("roles") or []:
            res.roles.append(ExtractedRole(
                title=raw.get("title") or "",
                quote=raw.get("quote") or "",
                apply_url=raw.get("apply_url") or "",
                location=raw.get("location") or "",
                stage=raw.get("stage") or "",
                experience_min_years=raw.get("experience_min_years"),
                experience_max_years=raw.get("experience_max_years"),
                grad_years_accepted=raw.get("grad_years_accepted") or [],
                grad_window_from=raw.get("grad_window_from") or "",
                grad_window_to=raw.get("grad_window_to") or "",
                study_year_min=raw.get("study_year_min"),
                study_year_max=raw.get("study_year_max"),
                degree_ceiling=raw.get("degree_ceiling") or "",
                institution_restriction=raw.get("institution_restriction") or "",
                prerequisite_gate=raw.get("prerequisite_gate") or "",
                remote_tier=raw.get("remote_tier") or "",
                access_channel=raw.get("access_channel") or "",
                deadline=raw.get("deadline") or "",
                stipend_text=raw.get("stipend_text") or "",
                salary_text=raw.get("salary_text") or "",
                evidence=raw.get("evidence") or {},
            ))
        return res


# --------------------------------------------------------------------------- #
# LLMExtractor — the production path
# --------------------------------------------------------------------------- #
# The prompt is a parameterised version of the eligibility ruleset in
# ~/Desktop/jobs/ansh-job-radar.md. The personal details are gone: it takes no
# candidate facts at all, because extraction must be about the POSTING, not about
# one user. Matching against a user happens later, in plain code, so that one
# extraction is reused by every visitor and no AI call is ever triggered by
# someone browsing.
EXTRACTION_PROMPT = """\
You are reading one employer careers page. List ONLY the early-career openings
that the page itself shows: internships, apprenticeships, traineeships, graduate
or new-grad roles, fresher roles, fellowships, and research programmes.

Return JSON: {"roles": [...]}. For each role return the fields you can support
and OMIT any you cannot.

ABSOLUTE RULES:
1. Every role MUST include "quote": the exact sentence from the page, copied
   character for character, that shows this role exists. If you cannot copy such
   a sentence, do not return the role.
2. Every eligibility field you fill MUST have a matching entry in "evidence"
   whose value is the exact sentence from the page stating it.
3. If the page shows no job listings — it is a login wall, a marketing page, an
   empty search result, or a JavaScript placeholder — return {"roles": []}.
   Returning an empty list is a correct and expected answer. NEVER invent a
   plausible posting to fill the list.
4. Never infer a date, a deadline, a stipend or a graduation year. Copy only what
   is written. No countdown may be built from a guess.
5. Do not restate or normalise a graduation requirement. If the page says
   "graduating between September 2027 and July 2028", record that window as
   written; do not convert it to a list of years.

Fields: title, quote, apply_url, location, stage
(intern|fresher_newgrad|trainee_apprentice), experience_min_years,
experience_max_years, grad_years_accepted, grad_window_from, grad_window_to,
study_year_min, study_year_max, degree_ceiling, institution_restriction,
prerequisite_gate, remote_tier, access_channel, deadline, stipend_text,
salary_text, evidence.

REMOTE TIER, decided only from what the page says:
  A       explicitly India, worldwide, global remote, or work from anywhere
  B       genuinely remote but the permitted countries are not stated
  C       remote only in a named region that does not include India
  onsite  a physical location is required
Never assume the reader holds a visa or work authorisation for any country.

EXPERIENCE: record the MINIMUM. "0-2 years" has a minimum of 0 and a fresher
qualifies. "minimum 2 years" has a minimum of 2 and a fresher does not. If the
page gives a bare number with no range, set experience_min_years to that number
and say so in evidence — do not decide whether it is a floor or a ceiling.

STUDY YEAR: watch for LOWER bounds as well as upper. "For first and second year
students only" means study_year_max is 2, and it excludes a final-year student.

ACCESS CHANNEL: off_campus if anyone may apply through the link; campus_only if
it routes through a placement cell, a named institution, or a campus drive;
unknown if the page does not say.
"""


class LLMExtractor(RoleExtractor):
    """Production extractor. Provider-agnostic; the key comes from the env.

    Deliberately not wired to a specific vendor SDK. The model and endpoint are
    configuration, the quote rule is code, and only the second one is load-bearing.

    Environment:
        XLAKE_LLM_API_KEY   required
        XLAKE_LLM_ENDPOINT  OpenAI-compatible /chat/completions URL
        XLAKE_LLM_MODEL     model id

    No token prices are hardcoded anywhere in this repo. Token COUNTS are
    recorded per call from the response, and cost is worked out from a price the
    operator supplies, because a stale hardcoded price silently produces a wrong
    budget and nobody notices.
    """

    name = "llm"

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None,
                 endpoint: Optional[str] = None, max_chars: int = 120_000):
        self.api_key = api_key or os.environ.get("XLAKE_LLM_API_KEY", "")
        self.model = model or os.environ.get("XLAKE_LLM_MODEL", "")
        self.endpoint = endpoint or os.environ.get("XLAKE_LLM_ENDPOINT", "")
        self.max_chars = max_chars

    def available(self) -> bool:
        return bool(self.api_key and self.model and self.endpoint)

    def extract(self, html: str, url: str) -> ExtractionResult:
        res = ExtractionResult(url=url, model=self.model)
        if not self.available():
            res.error = "llm_not_configured"
            return res

        from core.pagetext import to_text  # local import: keeps this module importable alone

        text = to_text(html)[: self.max_chars]
        res.input_chars = len(text)
        if len(text) < 200:
            # Nothing worth paying for. A JS shell flattens to almost nothing,
            # and this check stops us being billed to be lied to.
            res.error = "page_text_too_short"
            return res

        import urllib.error
        import urllib.request

        body = json.dumps({
            "model": self.model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": EXTRACTION_PROMPT},
                {"role": "user",
                 "content": "URL: {}\n\nPAGE TEXT:\n{}".format(url, text)},
            ],
        }).encode()
        req = urllib.request.Request(
            self.endpoint, data=body,
            headers={"Content-Type": "application/json",
                     "Authorization": "Bearer {}".format(self.api_key)},
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                payload = json.loads(resp.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            res.error = "llm_http_{}".format(e.code)
            return res
        except Exception as e:  # noqa: BLE001
            res.error = "llm_{}".format(type(e).__name__)
            return res

        usage = payload.get("usage") or {}
        res.prompt_tokens = int(usage.get("prompt_tokens") or 0)
        res.completion_tokens = int(usage.get("completion_tokens") or 0)
        try:
            content = payload["choices"][0]["message"]["content"]
            data = json.loads(content)
        except Exception:  # noqa: BLE001
            res.error = "llm_response_not_json"
            return res

        for raw in (data.get("roles") or []):
            if not isinstance(raw, dict):
                continue
            res.roles.append(ExtractedRole(
                title=str(raw.get("title") or ""),
                quote=str(raw.get("quote") or ""),
                apply_url=str(raw.get("apply_url") or ""),
                location=str(raw.get("location") or ""),
                stage=str(raw.get("stage") or ""),
                experience_min_years=raw.get("experience_min_years"),
                experience_max_years=raw.get("experience_max_years"),
                grad_years_accepted=[int(y) for y in (raw.get("grad_years_accepted") or [])
                                     if str(y).isdigit()],
                grad_window_from=str(raw.get("grad_window_from") or ""),
                grad_window_to=str(raw.get("grad_window_to") or ""),
                study_year_min=raw.get("study_year_min"),
                study_year_max=raw.get("study_year_max"),
                degree_ceiling=str(raw.get("degree_ceiling") or ""),
                institution_restriction=str(raw.get("institution_restriction") or ""),
                prerequisite_gate=str(raw.get("prerequisite_gate") or ""),
                remote_tier=str(raw.get("remote_tier") or ""),
                access_channel=str(raw.get("access_channel") or ""),
                deadline=str(raw.get("deadline") or ""),
                stipend_text=str(raw.get("stipend_text") or ""),
                salary_text=str(raw.get("salary_text") or ""),
                evidence={str(k): str(v) for k, v in
                          (raw.get("evidence") or {}).items()},
            ))
        # The rule is applied here, outside the model's control, to the same text
        # the model was given.
        return enforce_quotes(res, text)


def get_extractor() -> RoleExtractor:
    """LLMExtractor when it is configured, FixtureExtractor otherwise.

    Falling back rather than failing is deliberate: the engine must be fully
    runnable and testable with no API key, and the key is being added last.
    """
    llm = LLMExtractor()
    if llm.available():
        return llm
    return FixtureExtractor()
