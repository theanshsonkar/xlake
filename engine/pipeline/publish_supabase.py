"""Publish the lake's serving rows into Supabase (PostgREST).

This is a READ-ONLY consumer of the lake. It never touches the collectors or
the merge logic (AGENTS.md guardrail): it only reads
``engine/data/lake/opportunities.json`` and writes to the Supabase
``opportunities`` serving table.

Serving set
-----------
A row is *serving* when ``is_live is True`` OR ``needs_confirmation is True``.
Dead/hidden rows are retained in the lake only for the collector's internal
dedup and are never published.

Stable id strategy (collision-free across the whole serving set)
----------------------------------------------------------------
* job / internship: ``job:<sha1(url)[:20]>`` — the posting URL is the stable
  source identity (it embeds the immutable ATS requisition id). It is used
  instead of ``job_id`` because some boards (e.g. Workday) emit a placeholder
  ``job_id`` like ``"Spotlight Job"`` for many distinct postings. The URL hash
  is also stable across ``is_internship`` flips, so a job that is later
  reclassified as an internship keeps the same id (no duplicate + no false
  removal). Fallback ``job:<platform>:<token>:<job_id>`` only if a URL is
  missing (currently 0 rows).
* programme:    ``programme:<programme_id>``
* contribution: ``contribution:<contribution_id>``
* hackathon:    ``hackathon:<hackathon_id>``

Removal handling (no hard delete)
---------------------------------
Any id currently present in Supabase but NOT in the freshly-built serving set
is *soft-retired*: we PATCH ``is_live=false`` for those ids (batched
``id=in.(...)`` filters). We never DELETE — retention is a project rule.

Usage (run from engine/)::

    python3 -m pipeline.publish_supabase            # DRY-RUN (default): writes nothing
    python3 -m pipeline.publish_supabase --execute  # perform upsert + soft-retire

Environment: ``SUPABASE_URL``, ``SUPABASE_SERVICE_KEY``.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from core import jobmeta, shards
from categories.programme_enrich import clean_location

LAKE_PATH = Path("data/lake/opportunities.json")
TABLE = "opportunities"
UPSERT_BATCH = 500
RETIRE_BATCH = 200
# Some Supabase edges sit behind Cloudflare which rejects the default urllib
# UA with HTTP 403 code 1010; send a browser-ish UA to be safe.
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# Hackathon-only extra keys: never published for jobs/internships/other types.
HACKATHON_ONLY_KEYS = {
    "logo_url", "status", "themes", "participants", "mode", "region",
    "organizer_domain", "deadline_basis",
}
# Placeholders that must publish as NULL for hackathons.
HACKATHON_PLACEHOLDERS = {"not_stated", "needs_confirmation", "unknown", "n/a", "none"}
HACKATHON_DESCRIPTION_MAX = 300
# Hackathon-only keys that programmes also publish.
PROGRAMME_SHARED_KEYS = {"logo_url", "region", "organizer_domain", "deadline_basis"}
# Programme-only keys (never published for jobs/internships/hackathons).
PROGRAMME_ONLY_KEYS = {"funding_amount_usd", "intl_eligible", "levels"}
# Programmes and hackathons share the placeholder->NULL rules.
PLACEHOLDER_NULL_TYPES = {"hackathon", "programme", "contribution", "job", "internship"}
DESCRIPTION_MAX_TYPES = {"hackathon", "programme", "contribution", "job", "internship"}
JOB_TYPES = {"job", "internship"}
# Hackathon-style keys that job/internship rows also publish.
JOB_SHARED_KEYS = {"logo_url", "region"}
# Job/internship-only keys (never published for other types).
JOB_ONLY_KEYS = {
    "employment_type", "workplace", "salary_min", "salary_max", "salary_currency",
    "salary_text", "salary_interval", "posted_at", "level", "team",
    "company_display_name",
}
JOB_DESCRIPTION_MAX = 300
# Hackathon keys that contributions also publish.
CONTRIBUTION_SHARED_KEYS = {"logo_url", "region", "mode"}
# Contribution-only keys (never published for other types).
CONTRIBUTION_ONLY_KEYS = {"repo_description", "updated_at"}

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Fields surfaced into the `extra` jsonb, by relevance. Null/empty are dropped.
EXTRA_KEYS = [
    # jobs / internships
    "platform", "token", "job_id", "company_domain", "discipline", "skills", "salary",
    "season", "sponsorship", "program", "segment", "posting_age_days",
    "employment_type", "workplace", "salary_min", "salary_max", "salary_currency",
    "salary_text", "salary_interval", "posted_at", "level", "team",
    "company_display_name",
    # contributions
    "repo", "labels", "language", "difficulty", "difficulty_signal",
    "issue_number", "repo_stars", "discovery_source", "repo_description", "updated_at",
    # hackathons
    "prize", "tags", "start_date", "end_date", "is_online",
    "registration_deadline", "source", "logo_url", "status", "themes",
    "participants", "mode", "region", "organizer_domain", "deadline_basis",
    "source_kind", "listed_on", "team_min", "team_max", "tracks", "timezone",
    "prize_pool_usd", "top_prize", "rounds", "perks", "stipend",
    # programmes
    "organizer", "programme_status", "opening_date", "opportunity_type",
    "international_eligibility", "funding_amount_usd", "intl_eligible", "levels",
    # provenance (all types)
    "source_mechanism", "source_confirmation", "official_url",
    "application_url",
]


# --------------------------------------------------------------------------- #
# Classification + id
# --------------------------------------------------------------------------- #
def record_type(r: dict) -> str:
    if r.get("record_type"):
        return r["record_type"]
    if r.get("is_internship"):
        return "internship"
    return "job"


def _closed_and_past(r: dict) -> bool:
    """Programme whose status is closed and whose deadline is already past."""
    if r.get("record_type") != "programme" or r.get("programme_status") != "closed":
        return False
    deadline = r.get("deadline")
    return bool(isinstance(deadline, str) and DATE_RE.match(deadline)
                and deadline < datetime.date.today().isoformat())


def is_serving(r: dict) -> bool:
    if _closed_and_past(r):
        return False
    if r.get("is_duplicate") is True:  # a fresher twin is serving instead
        return False
    return r.get("is_live") is True or r.get("needs_confirmation") is True


def stable_id(r: dict) -> str:
    t = record_type(r)
    if t in ("job", "internship"):
        url = r.get("url") or ""
        if url:
            return "job:" + hashlib.sha1(url.encode("utf-8")).hexdigest()[:20]
        return "job:{}:{}:{}".format(
            r.get("platform") or "na", r.get("token") or "na",
            r.get("job_id") or "na")
    if t == "programme":
        return "programme:{}".format(r.get("programme_id"))
    if t == "contribution":
        return "contribution:{}".format(r.get("contribution_id"))
    if t == "hackathon":
        return "hackathon:{}".format(r.get("hackathon_id"))
    return "unknown:{}".format(r.get("job_id") or r.get("url"))


# --------------------------------------------------------------------------- #
# Mapping
# --------------------------------------------------------------------------- #
def _first(*vals):
    for v in vals:
        if v not in (None, "", []):
            return v
    return None


def _as_date(v):
    """Return v if it is a YYYY-MM-DD date string, else None (column is date)."""
    if isinstance(v, str) and DATE_RE.match(v):
        return v
    return None


def _truncate(v, n=200):
    if not v:
        return None
    s = str(v)
    return s[:n]


def map_row(r: dict) -> dict:
    t = record_type(r)
    verified = bool(r.get("manually_verified")) or bool(r.get("verified_by"))
    deadline = _as_date(_first(r.get("deadline"), r.get("registration_deadline")))

    extra = {}
    for k in EXTRA_KEYS:
        if k in HACKATHON_ONLY_KEYS and t != "hackathon" and not (
                t == "programme" and k in PROGRAMME_SHARED_KEYS) and not (
                t == "contribution" and k in CONTRIBUTION_SHARED_KEYS) and not (
                t in JOB_TYPES and k in JOB_SHARED_KEYS):
            continue
        if k in JOB_ONLY_KEYS and t not in JOB_TYPES:
            continue
        if k in CONTRIBUTION_ONLY_KEYS and t != "contribution":
            continue
        if k in PROGRAMME_ONLY_KEYS and t != "programme":
            continue
        v = r.get(k)
        if v not in (None, "", []):
            if t in PLACEHOLDER_NULL_TYPES and isinstance(v, str) and v.strip().casefold() in HACKATHON_PLACEHOLDERS:
                continue
            extra[k] = v
    if t in JOB_TYPES and not extra.get("logo_url"):
        logo = jobmeta.favicon_logo(extra.get("company_domain"))
        if logo:
            extra["logo_url"] = logo
    if t == "programme":
        extra["programme_status"] = r.get("programme_status") or "unknown"
        extra.setdefault("deadline_basis", "unknown")

    eligibility = _first(r.get("eligibility"), r.get("international_eligibility"))
    funding = r.get("funding")
    location = r.get("location")
    if t == "programme":
        # Real eligibility text only: placeholders and the bare "confirmed"
        # international flag are not eligibility.
        eligibility = _first(r.get("eligibility"))
        location = clean_location(location)
    if t in PLACEHOLDER_NULL_TYPES:
        if str(eligibility or "").strip().casefold() in HACKATHON_PLACEHOLDERS:
            eligibility = None
        if str(funding or "").strip().casefold() in HACKATHON_PLACEHOLDERS:
            funding = None

    return {
        "id": stable_id(r),
        "type": t,
        "category": r.get("category"),
        "title": _first(r.get("title"), r.get("programme_name"),
                        r.get("organizer"), r.get("repo")),
        "company": _first(r.get("company_name"), r.get("company"),
                          r.get("organizer")),
        "location": location,
        "location_bucket": r.get("location_bucket"),
        "url": _first(r.get("url"), r.get("official_url"),
                      r.get("application_url")),
        "is_live": bool(r.get("is_live", False)),
        "surfaced": bool(r.get("surfaced", True)),
        "is_internship": bool(r.get("is_internship", False)),
        "technical": r.get("technical"),
        "needs_confirmation": bool(r.get("needs_confirmation", False)),
        "last_checked": _first(r.get("last_checked_at"), r.get("last_seen")),
        "verified": verified,
        "description": (
            jobmeta.snippet(r.get("description"), JOB_DESCRIPTION_MAX)
            if t in JOB_TYPES else
            _truncate(r.get("description"),
                      HACKATHON_DESCRIPTION_MAX if t in DESCRIPTION_MAX_TYPES else 200)),
        "deadline": deadline,
        "eligibility": eligibility,
        "funding": funding,
        "extra": extra,
    }


def build_serving(lake: list, category: str = None) -> list:
    return [map_row(r) for r in lake if is_serving(r)
            and (category is None or shards.shard_of(r) == category)]


RETIRE_GUARD_RATIO = 0.5
RETIRE_GUARD_MIN = 20
_SCOPE_ID_PREFIX = {"hackathon": "hackathon:", "contribution": "contribution:",
                    "programme": "programme:"}


def plan_retire(existing, serving_ids, category: str = None,
                force: bool = False):
    """Return (ids_to_retire, error). With ``category`` only ids that belong
    to that category's record types (by id prefix) can ever be retired, so a
    scoped run cannot touch another category even if ``existing`` leaked."""
    to_retire = set(existing) - set(serving_ids)
    if category is not None and shards.is_job_shard(category):
        prefixes = ("job:",)
        to_retire = {i for i in to_retire if i.startswith(prefixes)}
    elif category is not None:
        prefixes = tuple(_SCOPE_ID_PREFIX[t] for t, _ in shards.SHARD_SCOPES[category])
        to_retire = {i for i in to_retire if i.startswith(prefixes)}
    err = None
    if (not force and len(existing) >= RETIRE_GUARD_MIN
            and len(to_retire) > len(existing) * RETIRE_GUARD_RATIO):
        err = ("would soft-retire %d of %d existing rows (>%d%%); pass "
               "--force-retire if intended"
               % (len(to_retire), len(existing), int(RETIRE_GUARD_RATIO * 100)))
    return sorted(to_retire), err


# --------------------------------------------------------------------------- #
# Supabase / PostgREST client
# --------------------------------------------------------------------------- #
class Supabase:
    def __init__(self, url: str, key: str):
        self.base = url.rstrip("/") + "/rest/v1"
        self.key = key

    def _headers(self, extra=None):
        h = {
            "apikey": self.key,
            "Authorization": "Bearer " + self.key,
            "Content-Type": "application/json",
            "User-Agent": UA,
            "Accept": "application/json",
        }
        if extra:
            h.update(extra)
        return h

    def _request(self, method, path, body=None, headers=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            self.base + path, data=data, method=method,
            headers=self._headers(headers))
        try:
            with urllib.request.urlopen(req) as resp:
                raw = resp.read().decode()
                return resp.status, resp.headers, raw
        except urllib.error.HTTPError as e:
            e.body_text = e.read().decode(errors="replace")[:300]
            raise

    def fetch_all_ids(self, scopes=None):
        """Return the set of ids currently in the table (paginated).

        ``scopes`` = [(type, category|None)] restricts the query server-side
        (used by --category so other categories' ids are never even listed).
        """
        if scopes is None:
            return self._fetch_ids("")
        ids = set()
        for t, c in scopes:
            f = "&type=eq.%s" % urllib.parse.quote(t, safe="")
            if c:
                f += "&category=eq.%s" % urllib.parse.quote(c, safe="")
            ids |= self._fetch_ids(f)
        return ids

    def fetch_job_ids(self, shard: str):
        """LIVE ids (already-retired rows are excluded so they are neither
        counted nor re-patched) of job/internship rows whose extra.platform
        belongs to ``shard``
        (filtered client-side so the catch-all shard needs no platform list)."""
        ids, offset, page = set(), 0, 1000
        while True:
            status, hdrs, raw = self._request(
                "GET", "/%s?select=id,platform:extra->>platform&type=in.(job,internship)"
                       "&is_live=eq.true&limit=%d&offset=%d" % (TABLE, page, offset),
                headers={"Range-Unit": "items"})
            rows = json.loads(raw) if raw else []
            for row in rows:
                if shards.job_shard_of_platform(row.get("platform")) == shard:
                    ids.add(row["id"])
            if len(rows) < page:
                break
            offset += page
        return ids

    def _fetch_ids(self, flt):
        ids, offset, page = set(), 0, 1000
        while True:
            status, hdrs, raw = self._request(
                "GET", "/%s?select=id%s&is_live=eq.true&limit=%d&offset=%d" % (TABLE, flt, page, offset),
                headers={"Range-Unit": "items"})
            rows = json.loads(raw) if raw else []
            ids.update(row["id"] for row in rows)
            if len(rows) < page:
                break
            offset += page
        return ids

    def upsert(self, rows):
        """Upsert (on conflict id) a batch via merge-duplicates."""
        self._request(
            "POST", "/%s?on_conflict=id" % TABLE, body=rows,
            headers={"Prefer": "resolution=merge-duplicates,return=minimal"})

    def retire(self, ids):
        """Soft-retire: set is_live=false for the given ids (batched).

        Ids may embed URLs (contributions/hackathons), so each value is
        double-quoted (handles commas) and percent-encoded for the query
        string.
        """
        def retire_chunk(chunk):
            in_list = ",".join(
                '"%s"' % urllib.parse.quote(
                    x.replace("\\", "\\\\").replace('"', ''), safe="")
                for x in chunk)
            try:
                self._request(
                    "PATCH", "/%s?id=in.(%s)" % (TABLE, in_list),
                    body={"is_live": False, "needs_confirmation": False},
                    headers={"Prefer": "return=minimal"})
                return 0
            except urllib.error.HTTPError as e:
                if e.code not in (400, 414):
                    raise
                if len(chunk) > 1:
                    middle = len(chunk) // 2
                    return (retire_chunk(chunk[:middle]) +
                            retire_chunk(chunk[middle:]))
                print("RETIRE SKIP id=%s http=%s body=%s" % (
                    repr(chunk[0])[:200], e.code,
                    getattr(e, "body_text", "")))
                return 1

        skipped = 0
        for i in range(0, len(ids), RETIRE_BATCH):
            skipped += retire_chunk(ids[i:i + RETIRE_BATCH])
        return skipped


# --------------------------------------------------------------------------- #
# Report helpers
# --------------------------------------------------------------------------- #
def summarize(mapped: list):
    by_type, dups = {}, {}
    seen = {}
    nc = 0
    for m in mapped:
        by_type[m["type"]] = by_type.get(m["type"], 0) + 1
        if m["needs_confirmation"]:
            nc += 1
        seen[m["id"]] = seen.get(m["id"], 0) + 1
    dups = {k: v for k, v in seen.items() if v > 1}
    return by_type, nc, len(seen), dups


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--execute", action="store_true",
                    help="perform writes (default: dry-run, writes nothing)")
    ap.add_argument("--samples", type=int, default=3)
    ap.add_argument("--category", choices=list(shards.ALL_SHARDS),
                    help="publish and soft-retire ONLY this category's rows")
    ap.add_argument("--force-retire", action="store_true",
                    help="bypass the >50%% soft-retire guard")
    args = ap.parse_args()
    dry = not args.execute
    cat = args.category
    job_shard = bool(cat) and shards.is_job_shard(cat)
    scopes = shards.SHARD_SCOPES[cat] if cat and not job_shard else None

    if not LAKE_PATH.exists():
        print("ERROR: lake not found at %s — restore it from S3 first "
              "(aws s3 cp s3://$AWS_S3_BUCKET/lake/opportunities.json %s)"
              % (LAKE_PATH, LAKE_PATH), file=sys.stderr)
        return 2

    if cat:
        lake = json.load(open(LAKE_PATH))
    else:
        # whole lake = main + any local shards (shards override main copies)
        lake = shards.load_whole_lake(str(LAKE_PATH))
    mapped = build_serving(lake, cat)
    by_type, nc, uniq, dups = summarize(mapped)

    print("=" * 64)
    print("MODE: %s%s" % ("DRY-RUN (nothing written)" if dry else "EXECUTE",
                         " [category=%s]" % cat if cat else ""))
    print("lake rows total        : %d" % len(lake))
    print("serving rows to publish: %d" % len(mapped))
    print("-" * 64)
    print("count by type:")
    for t in sorted(by_type, key=lambda k: -by_type[k]):
        print("  %-13s %d" % (t, by_type[t]))
    print("needs_confirmation rows: %d" % nc)
    print("-" * 64)
    print("id uniqueness: %d ids, %d unique, %d colliding"
          % (len(mapped), uniq, len(dups)))
    if dups:
        for k, v in list(dups.items())[:10]:
            print("  COLLISION %s x%d" % (k, v))

    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_KEY")

    if dry:
        print("-" * 64)
        print("SAMPLE MAPPED ROWS (one per type where available):")
        shown = set()
        for want in ("job", "programme", "contribution", "hackathon",
                     "internship"):
            for m in mapped:
                if m["type"] == want and want not in shown:
                    shown.add(want)
                    print("\n--- %s ---" % want)
                    print(json.dumps(m, indent=2, ensure_ascii=False,
                                     default=str))
                    break
            if len(shown) >= args.samples and want == "contribution":
                break
        # read-only connectivity + removal preview (no writes)
        print("-" * 64)
        if url and key:
            try:
                client = Supabase(url, key)
                existing = (client.fetch_job_ids(cat) if job_shard
                            else client.fetch_all_ids(scopes))
                serving_ids = {m["id"] for m in mapped}
                to_retire, _ = plan_retire(existing, serving_ids, cat, True)
                print("Supabase reachable (read-only). existing rows: %d"
                      % len(existing))
                print("would upsert: %d ; would soft-retire (is_live=false): %d"
                      % (len(mapped), len(to_retire)))
            except urllib.error.HTTPError as e:
                print("Supabase read check failed: HTTP %s %s"
                      % (e.code, e.read().decode()[:200]))
            except Exception as e:  # noqa: BLE001
                print("Supabase read check skipped: %s" % e)
        else:
            print("SUPABASE_URL / SUPABASE_SERVICE_KEY not set — skipping "
                  "read-only connectivity check.")
        print("=" * 64)
        print("DRY-RUN complete. Nothing was written to Supabase.")
        return 0

    # --- EXECUTE path ---
    if not (url and key):
        print("ERROR: SUPABASE_URL / SUPABASE_SERVICE_KEY required for --execute",
              file=sys.stderr)
        return 2
    client = Supabase(url, key)
    existing = (client.fetch_job_ids(cat) if job_shard
                else client.fetch_all_ids(scopes))
    serving_ids = {m["id"] for m in mapped}
    to_retire, guard_err = plan_retire(existing, serving_ids, cat, args.force_retire)
    if guard_err:
        print("ERROR: " + guard_err, file=sys.stderr)
        return 3
    for i in range(0, len(mapped), UPSERT_BATCH):
        client.upsert(mapped[i:i + UPSERT_BATCH])
        print("upserted %d/%d" % (min(i + UPSERT_BATCH, len(mapped)), len(mapped)))
    skipped = client.retire(to_retire) if to_retire else 0
    print("retire skipped: %d" % skipped)
    print("done. upserted=%d soft_retired=%d" % (len(mapped), len(to_retire)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
