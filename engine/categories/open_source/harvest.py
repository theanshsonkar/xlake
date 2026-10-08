"""Category-local Open Source programme discovery dry-run.

The hub fetcher and link discovery are deliberately reused from the Research
harvester. This module adds only the Open Source hub policy, page fetch/AI
extraction gates, and an ephemeral preview; it never calls programme_core or
writes a lake, S3, Supabase, or operations file.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from categories.research import harvest as research_harvest
from core.pagetext import to_text


HUBS_PATH = Path(__file__).with_name("open_source_hubs.json")
DEFAULT_OUTPUT = Path("/tmp/open_source_dryrun.json")
DEFAULT_CACHE = Path("/tmp/open_source_ai_cache.json")
DEFAULT_COUNTER = Path("/tmp/open_source_ai_monthly.json")
MAX_HUBS = 50
MAX_CALLS_PER_RUN = 60
MAX_CALLS_PER_MONTH = 100
MAX_PAGE_TEXT = 12_000
LLM_CALL_INTERVAL_SECONDS = 4.0
LLM_RETRY_DELAYS_SECONDS = (5.0, 10.0)
LLM_RETRY_AFTER_CAP_SECONDS = 30.0

# These are deliberately local to Open Source discovery. They are leads, not
# facts: only the fetched candidate page can supply a record or evidence.
OPEN_SOURCE_TERMS = re.compile(
    r"(?:open[\s_-]*source|mentorship|fellowship|summer[\s_-]*of[\s_-]*code|"
    r"gsoc|outreachy|lfx|season[\s_-]*of[\s_-]*code|programme?|program|"
    r"application|contribution|maintainer)",
    re.IGNORECASE,
)
AI_FIELDS = (
    "programme_name",
    "programme_status",
    "opening_date",
    "deadline",
    "eligibility",
    "funding",
    "official_url",
    "evidence_quote",
    "is_opportunity",
    "opportunity_type",
)
VALID_STATUSES = {"open", "opening_soon", "rolling"}
NON_OPPORTUNITY_TYPE = re.compile(
    r"(?:^|[\\s,/_-])(?:product|tool|dashboard|documentation|docs?|marketing|pricing|"
    r"generic[\\s_-]+org(?:anization)?|organization)(?:$|[\\s,/_-])",
    re.IGNORECASE,
)

STRICT_PROMPT = """You are an evidence-only reader of one Open Source programme page.
Return one JSON object with exactly these ten keys and no others:
programme_name, programme_status, opening_date, deadline, eligibility, funding,
official_url, evidence_quote, is_opportunity, opportunity_type.
programme_status must be exactly one of: open, opening_soon, rolling, closed.
is_opportunity must be a boolean. Set it to true ONLY when the supplied page
text describes an actual opportunity that a person can apply to or participate
in, such as a fellowship, mentorship, internship or internship alternative,
grant, scholarship, residency, accelerator, or cohort/programme with applicants.
Set is_opportunity to false for a product, software tool, dashboard,
documentation, marketing, pricing, or generic organization page. Set
opportunity_type to a concise string describing the opportunity type, or an
empty string when is_opportunity is false. Base both fields only on the page
text; do not guess.
Copy facts only from the supplied page text. Never infer, upgrade, or fill a
missing fact. Use null for a missing date, eligibility, or funding value.
programme_name, official_url, and evidence_quote are required when the page
clearly identifies an actionable programme. evidence_quote must be copied
verbatim from the page text and must support the programme/status. official_url
must be the page's official programme/application URL. If the page is closed,
unclear, or is not an actionable Open Source programme, return the same keys
with programme_status set to closed only when the page explicitly says closed;
otherwise use null for programme_status. Do not return Markdown or commentary.
"""


def _is_opportunity_record(data: Dict[str, object]) -> bool:
    opportunity_type = data.get("opportunity_type")
    if data.get("is_opportunity") is not True or not isinstance(opportunity_type, str):
        return False
    value = opportunity_type.strip()
    return bool(value) and not NON_OPPORTUNITY_TYPE.search(value)


def _normalise_page_text(text: str) -> str:
    """Normalize only line endings; preserve source whitespace for evidence."""
    return (text or "").replace("\r\n", "\n").replace("\r", "\n")


def _page_hash(text: str) -> str:
    return hashlib.sha256(_normalise_page_text(text).encode("utf-8", "replace")).hexdigest()


def _same_origin(left: str, right: str) -> bool:
    left_normalized = research_harvest.normalize_url(left)
    right_normalized = research_harvest.normalize_url(right)
    if left_normalized is None or right_normalized is None:
        return False
    left_parsed = research_harvest.parse_http_url(left_normalized)
    right_parsed = research_harvest.parse_http_url(right_normalized)
    if left_parsed is None or right_parsed is None:
        return False
    return research_harvest.origin_key_for(left_parsed) == research_harvest.origin_key_for(right_parsed)


def _contains_exact(value: object, text: str) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    # This is only for proving a returned field appears in its evidence quote;
    # quote validation itself remains an exact substring check.
    compact_value = " ".join(value.replace("\r\n", "\n").replace("\r", "\n").split())
    compact_text = " ".join(text.replace("\r\n", "\n").replace("\r", "\n").split())
    return bool(compact_value) and compact_value.casefold() in compact_text.casefold()


def _status_supported(status: str, quote: str) -> bool:
    patterns = {
        "open": r"\bopen\b|accepting applications?|applications? (?:are|now) open",
        "opening_soon": r"opening soon|opens? soon|will open|applications? .* soon",
        "rolling": r"rolling basis|ongoing|year[- ]round|continuous|always open",
    }
    return bool(re.search(patterns.get(status, r"$^"), quote, re.IGNORECASE))


def _status_closed(quote: str) -> bool:
    """Return whether the evidence explicitly says the programme has ended."""
    return bool(re.search(
        r"\bclosed\b|\bended\b|applications? (?:are|now) no longer accepting|"
        r"no longer accepting applications?|programme has ended|program has ended",
        quote,
        re.IGNORECASE,
    ))


def load_hubs(path: Path = HUBS_PATH) -> List[Dict[str, object]]:
    """Load 1..50 Open Source hubs with optional authoritative provenance."""
    return research_harvest.load_hubs(
        path,
        category="open_source",
        exact_count=None,
        min_hubs=1,
        max_hubs=MAX_HUBS,
        allow_authoritative=True,
    )


def provenance(candidate: research_harvest.Candidate, hubs: Sequence[Dict[str, object]]) -> Dict[str, object]:
    corroborating = research_harvest.build_corroborating_hubs(candidate, hubs)
    authoritative = any(bool(item.get("authoritative")) for item in corroborating)
    return {
        "contributing_hubs": corroborating,
        "source_count": len(corroborating),
        "authoritative": authoritative,
    }


def provenance_reason(candidate: research_harvest.Candidate, hubs: Sequence[Dict[str, object]]) -> Optional[str]:
    evidence = provenance(candidate, hubs)
    if int(evidence["source_count"]) >= 2 or bool(evidence["authoritative"]):
        return None
    return "insufficient_provenance: requires source_count>=2 or authoritative hub"


def _safe_state_path(value: str, default: Path) -> Path:
    path = Path(value).expanduser() if value else default
    resolved = path.resolve()
    try:
        resolved.relative_to(research_harvest.REPO_ROOT)
    except ValueError:
        pass
    else:
        raise ValueError("AI state path must be outside the repository")
    if any(part.lower() == "lake" for part in resolved.parts):
        raise ValueError("AI state path must not contain a lake path component")
    return path.absolute()


def _read_json(path: Path, fallback: Any) -> Any:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return fallback


def _atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Optional[str] = None
    try:
        descriptor, temporary = tempfile.mkstemp(prefix="." + path.name + ".", dir=str(path.parent))
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass


class OpenSourceLLMClient:
    """Small OpenAI-compatible client for the programme schema.

    The shared extractor is jobs-shaped, so programme extraction owns this
    schema-specific request path. It deliberately returns only the JSON object
    found in the model message content; transport and response failures are
    left uncached so a later run can retry them.
    """

    name = "llm"

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        endpoint: Optional[str] = None,
        opener: Any = None,
    ) -> None:
        self.api_key = api_key or os.environ.get("XLAKE_LLM_API_KEY", "").strip()
        self.model = model or os.environ.get("XLAKE_LLM_MODEL", "").strip()
        self.endpoint = endpoint or os.environ.get("XLAKE_LLM_ENDPOINT", "").strip()
        self.opener = opener or urllib.request.urlopen
        self.last_attempted = False
        self._has_called = False
        self.http_statuses: Counter[str] = Counter()
        self.http_attempts = 0

    def available(self) -> bool:
        return bool(self.api_key and self.model and self.endpoint)

    def call(self, page_text: str, url: str) -> Tuple[Optional[Dict[str, object]], str, bool]:
        self.last_attempted = True
        gemini_native = "generativelanguage.googleapis.com" in self.endpoint
        if gemini_native:
            body = json.dumps({
                "system_instruction": {"parts": [{"text": STRICT_PROMPT}]},
                "contents": [{
                    "role": "user",
                    "parts": [{"text": "URL: {}\n\nPAGE TEXT:\n{}".format(url, page_text)}],
                }],
                "generationConfig": {
                    "temperature": 0,
                    "responseMimeType": "application/json",
                },
            }).encode("utf-8")
            headers = {
                "Content-Type": "application/json",
                "x-goog-api-key": self.api_key,
            }
        else:
            body = json.dumps({
                "model": self.model,
                "temperature": 0,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": STRICT_PROMPT},
                    {"role": "user", "content": "URL: {}\n\nPAGE TEXT:\n{}".format(url, page_text)},
                ],
            }).encode("utf-8")
            headers = {
                "Content-Type": "application/json",
                "Authorization": "Bearer {}".format(self.api_key),
            }
        request = urllib.request.Request(
            self.endpoint,
            data=body,
            headers=headers,
        )
        for retry_index in range(len(LLM_RETRY_DELAYS_SECONDS) + 1):
            if self._has_called and retry_index == 0:
                time.sleep(LLM_CALL_INTERVAL_SECONDS)
            self._has_called = True
            try:
                with self.opener(request, timeout=120) as response:
                    self.http_attempts += 1
                    self.http_statuses[str(getattr(response, "status", 200))] += 1
                    payload = json.loads(response.read().decode("utf-8", "replace"))
                break
            except urllib.error.HTTPError as exc:
                self.http_attempts += 1
                self.http_statuses[str(exc.code)] += 1
                if exc.code not in (429, 503) or retry_index >= len(LLM_RETRY_DELAYS_SECONDS):
                    return None, "llm_http_{}".format(exc.code), False
                retry_after = None
                if exc.headers:
                    raw_retry_after = exc.headers.get("Retry-After")
                    try:
                        retry_after = min(float(raw_retry_after), LLM_RETRY_AFTER_CAP_SECONDS)
                    except (TypeError, ValueError):
                        retry_after = None
                delay = retry_after if retry_after is not None else LLM_RETRY_DELAYS_SECONDS[retry_index]
                time.sleep(max(LLM_CALL_INTERVAL_SECONDS, max(0.0, delay)))
            except Exception as exc:  # noqa: BLE001
                return None, "llm_{}".format(type(exc).__name__), False
        else:
            return None, "llm_http_retry_exhausted", False

        try:
            if gemini_native:
                content = payload["candidates"][0]["content"]["parts"][0]["text"]
            else:
                content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            return None, "llm_response_not_json", False
        if not isinstance(content, str):
            return None, "llm_response_not_json", False
        try:
            data = json.loads(content)
        except (TypeError, ValueError):
            return None, "llm_response_not_json", False
        if not isinstance(data, dict):
            return None, "llm_response_not_json", False
        return data, "", True


class AIReader:
    """Evidence-gated reader with completed-result caching and local budgets."""

    def __init__(
        self,
        cache_path: Optional[Path] = None,
        counter_path: Optional[Path] = None,
        client_factory: Any = None,
    ) -> None:
        cache_value = os.environ.get("XLAKE_OPEN_SOURCE_AI_CACHE", "") if cache_path is None else str(cache_path)
        counter_value = os.environ.get("XLAKE_OPEN_SOURCE_AI_COUNTER", "") if counter_path is None else str(counter_path)
        self.cache_path = _safe_state_path(cache_value, DEFAULT_CACHE)
        self.counter_path = _safe_state_path(counter_value, DEFAULT_COUNTER)
        self.client_factory = client_factory or OpenSourceLLMClient
        self.cache: Dict[str, object] = _read_json(self.cache_path, {})
        if not isinstance(self.cache, dict):
            self.cache = {}
        self.calls = 0
        self.cache_hits = 0
        self.reasons: Counter[str] = Counter()
        self._client: Optional[OpenSourceLLMClient] = None
        self._ready_reason = ""
        self._month = datetime.now(timezone.utc).strftime("%Y-%m")
        self._month_calls = 0
        counter = _read_json(self.counter_path, {})
        if isinstance(counter, dict) and counter.get("month") == self._month:
            try:
                self._month_calls = max(0, int(counter.get("attempted_calls", 0)))
            except (TypeError, ValueError):
                self._month_calls = 0

    @property
    def enabled(self) -> bool:
        return os.environ.get("XLAKE_OPEN_SOURCE_AI") == "1"

    def prepare(self) -> str:
        if not self.enabled:
            self._ready_reason = "AI disabled: XLAKE_OPEN_SOURCE_AI is not literal '1'"
            return self._ready_reason
        try:
            configured = self.client_factory()
        except Exception as exc:  # noqa: BLE001
            self._ready_reason = "AI unavailable: client setup {}".format(type(exc).__name__)
            return self._ready_reason
        available = getattr(configured, "available", None)
        if not callable(available) or not available():
            self._ready_reason = "AI unavailable: OpenAI-compatible client credentials/configuration missing"
            return self._ready_reason
        self._client = configured
        self._ready_reason = "AI enabled and category-local OpenAI-compatible client configured"
        return self._ready_reason

    def _mark_attempt(self) -> None:
        self.calls += 1
        self._month_calls += 1
        _atomic_write_json(self.counter_path, {
            "month": self._month,
            "attempted_calls": self._month_calls,
        })

    def _cache_completed(self, digest: str, outcome: str, value: object) -> None:
        self.cache[digest] = {"outcome": outcome, outcome: value}
        _atomic_write_json(self.cache_path, self.cache)

    def read(self, page_text: str, candidate_url: str, response_url: Optional[str] = None) -> Tuple[Optional[Dict[str, object]], str, str]:
        """Return (validated fields, reason, outcome), never exposing response text."""
        if not self._client:
            return None, self._ready_reason or "AI unavailable", "unavailable"
        source_text = _normalise_page_text(page_text)
        digest = _page_hash(source_text)
        cached = self.cache.get(digest)
        if isinstance(cached, dict) and cached.get("outcome") == "accepted" and isinstance(cached.get("accepted"), dict):
            accepted = dict(cached["accepted"])
            if _is_opportunity_record(accepted):
                self.cache_hits += 1
                if "is_live" not in accepted and "needs_confirmation" not in accepted:
                    accepted["is_live"] = accepted.get("programme_status") in VALID_STATUSES
                    accepted["needs_confirmation"] = not accepted["is_live"]
                return accepted, "cache_hit", "accepted"
        if isinstance(cached, dict) and cached.get("outcome") == "rejected" and isinstance(cached.get("rejected"), str):
            self.cache_hits += 1
            return None, "cache_hit: {}".format(cached["rejected"]), "cache_hit"
        if self.calls >= MAX_CALLS_PER_RUN:
            return None, "AI run limit reached ({})".format(MAX_CALLS_PER_RUN), "limited"
        if self._month_calls >= MAX_CALLS_PER_MONTH:
            return None, "AI calendar-month limit reached (100)", "limited"
        prompt_text = source_text[:MAX_PAGE_TEXT]
        final_url = response_url or candidate_url
        self._client.last_attempted = False
        try:
            try:
                data, call_reason, completed = self._client.call(prompt_text, final_url)
            except Exception as exc:  # noqa: BLE001
                data, call_reason, completed = None, "model_call_{}".format(type(exc).__name__), False
        finally:
            # A real local client invocation is budgeted, but transport/response
            # failures are deliberately not cached so the next read can retry.
            if self._client.last_attempted:
                self._mark_attempt()
        if not completed:
            return None, call_reason or "model_call_failed", "rejected"
        if not isinstance(data, dict):
            reason = call_reason or "model_response_not_strict_json"
            self._cache_completed(digest, "rejected", reason)
            return None, reason, "rejected"
        if set(data) != set(AI_FIELDS):
            reason = "model_response_fields_not_exact"
            self._cache_completed(digest, "rejected", reason)
            return None, reason, "rejected"
        if not isinstance(data.get("is_opportunity"), bool) or not isinstance(data.get("opportunity_type"), str):
            reason = "model_response_field_types_invalid"
            self._cache_completed(digest, "rejected", reason)
            return None, reason, "rejected"
        if any(
            data.get(field) is not None and not isinstance(data.get(field), str)
            for field in ("opening_date", "deadline", "eligibility", "funding")
        ):
            reason = "model_response_field_types_invalid"
            self._cache_completed(digest, "rejected", reason)
            return None, reason, "rejected"
        extracted, reason, outcome = self._validate(data, source_text, candidate_url, final_url)
        if outcome == "accepted" and extracted is not None:
            self._cache_completed(digest, "accepted", extracted)
        else:
            self._cache_completed(digest, "rejected", reason)
        return extracted, reason, outcome

    @staticmethod
    def _validate(
        data: Dict[str, object],
        page_text: str,
        candidate_url: str,
        response_url: Optional[str] = None,
    ) -> Tuple[Optional[Dict[str, object]], str, str]:
        response_url = response_url or candidate_url
        name = data.get("programme_name")
        status = data.get("programme_status")
        raw_quote = data.get("evidence_quote")
        official_url = data.get("official_url")
        if not _is_opportunity_record(data):
            return None, "not_an_opportunity", "rejected"
        quote = _normalise_page_text(raw_quote) if isinstance(raw_quote, str) else ""
        if not isinstance(name, str) or not name.strip() or not _contains_exact(name, page_text):
            return None, "missing_or_unsupported_programme_name", "rejected"
        if not quote or quote not in page_text or len(quote.strip()) < 12:
            return None, "missing_or_nonverbatim_evidence", "rejected"
        if not isinstance(official_url, str) or not official_url.strip():
            return None, "missing_official_url", "rejected"
        candidate_canonical = research_harvest.normalize_url(candidate_url)
        response_canonical = research_harvest.normalize_url(response_url)
        canonical = research_harvest.normalize_url(official_url)
        if (
            candidate_canonical is None
            or response_canonical is None
            or canonical is None
            or not _same_origin(candidate_canonical, response_canonical)
            or not _same_origin(canonical, candidate_canonical)
            or not _same_origin(canonical, response_canonical)
        ):
            return None, "official_url_not_same_origin", "rejected"
        record = {field: data.get(field) for field in AI_FIELDS}
        record["programme_name"] = name.strip()
        record["official_url"] = canonical
        record["evidence_quote"] = quote
        if status in VALID_STATUSES and _status_supported(str(status), quote):
            record["programme_status"] = status
            record["is_live"] = True
            record["needs_confirmation"] = False
        elif _status_closed(quote):
            return None, "status_not_supported_by_evidence", "rejected"
        else:
            record["programme_status"] = None
            record["is_live"] = False
            record["needs_confirmation"] = True
        for field in ("opening_date", "deadline", "eligibility", "funding"):
            value = data.get(field)
            record[field] = value.strip() if isinstance(value, str) and value.strip() and _contains_exact(value, quote) else None
        return record, "accepted", "accepted"


def _record(
    extracted: Dict[str, object],
    candidate: research_harvest.Candidate,
    hubs: Sequence[Dict[str, object]],
    page_hash: str,
    checked_at: str,
) -> Dict[str, object]:
    evidence = provenance(candidate, hubs)
    digest = hashlib.sha256(str(extracted["official_url"]).encode("utf-8")).hexdigest()[:20]
    return {
        "record_type": "programme",
        "category": "open_source",
        "opportunity_type": "open_source_programme",
        "programme_id": "open-source-programme-" + digest,
        **extracted,
        "official_evidence": {
            "evidence_quote": extracted["evidence_quote"],
            **evidence,
            "candidate_url": candidate.url,
            "page_text_sha256": page_hash,
        },
        "last_checked_at": checked_at,
    }


def run(
    output: Path = DEFAULT_OUTPUT,
    *,
    hubs_path: Path = HUBS_PATH,
    fetcher: Optional[research_harvest.Fetcher] = None,
    reader: Optional[AIReader] = None,
) -> Dict[str, object]:
    # Public callers must receive the same repository/lake guard as the CLI;
    # otherwise run(output=...) could bypass main entirely.
    safe_output = research_harvest.guarded_output_path(str(output))
    hubs = load_hubs(hubs_path)
    client = fetcher or research_harvest.Fetcher()
    ai = reader or AIReader()
    ready_reason = ai.prepare()
    candidates, states, reasons, counts, failures, blocks = research_harvest.discover_candidates(
        hubs,
        client,
        candidate_terms=OPEN_SOURCE_TERMS,
        authoritative_same_origin=True,
    )
    checked_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    records: List[Dict[str, object]] = []
    rejected: Counter[str] = Counter()
    pages_fetched = 0
    for candidate in candidates:
        try:
            page = client.fetch(candidate.url, {"Accept": "text/html, text/plain;q=0.9, */*;q=0.5"})
        except research_harvest.RequestCapExceeded:
            rejected["candidate_fetch_request_cap"] += 1
            continue
        if page.state != "live" or page.status != 200:
            rejected["candidate_fetch_{}".format(page.state)] += 1
            continue
        if not page.final_url or not _same_origin(candidate.url, page.final_url):
            rejected["candidate_redirect_cross_origin"] += 1
            continue
        pages_fetched += 1
        page_text = _normalise_page_text(to_text(page.body))
        digest = _page_hash(page_text)
        reason = provenance_reason(candidate, hubs)
        if reason:
            rejected[reason] += 1
            continue
        extracted, read_reason, outcome = ai.read(page_text, candidate.url, page.final_url)
        if extracted is not None and outcome in {"accepted", "cache_hit"}:
            records.append(_record(extracted, candidate, hubs, digest, checked_at))
        elif read_reason != "cache_hit":
            rejected[read_reason] += 1
    summary: Dict[str, object] = {
        "hubs_loaded": len(hubs),
        "candidates_discovered": len(candidates),
        "candidate_pages_fetched": pages_fetched,
        "model_calls": ai.calls,
        "model_http_attempts": int(getattr(ai._client, "http_attempts", 0)),
        "model_http_statuses": dict(sorted(getattr(ai._client, "http_statuses", {}).items())),
        "cache_hits": ai.cache_hits,
        "accepted_evidence_gated_records": len(records),
        "accepted_live": sum(1 for record in records if record.get("is_live") is True),
        "accepted_needs_confirmation": sum(1 for record in records if record.get("needs_confirmation") is True),
        "excluded_or_dropped": sum(rejected.values()),
        "rejected": dict(sorted(rejected.items())),
        "ai_reason": ready_reason,
        "hub_failures": failures,
        "hub_blocks": blocks,
        "http_requests": client.total_requests,
        "hub_states": states,
        "hub_candidate_counts": counts,
        "hub_reasons": reasons,
        "accepted_samples": [
            {
                "acceptance_tier": "LIVE" if record.get("is_live") is True else "NEEDS_CONFIRMATION",
                "programme_name": record["programme_name"],
                "opportunity_type": record["opportunity_type"],
                "programme_status": record["programme_status"],
                "evidence_quote": record["evidence_quote"],
                "official_url": record["official_url"],
            }
            for record in records[:12]
        ],
    }
    payload = {"run_summary": summary, "records": records}
    _atomic_write_json(safe_output, payload)
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    print("output: {}".format(safe_output))
    return summary


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Dry-run Open Source programme hub harvester")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Preview path (default: /tmp/open_source_dryrun.json)")
    args = parser.parse_args(argv)
    try:
        output = research_harvest.guarded_output_path(args.output)
        run(output)
        return 0
    except (ValueError, OSError, RuntimeError) as exc:
        print("harvest error: {}".format(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
