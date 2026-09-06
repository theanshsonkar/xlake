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
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

LAKE_PATH = Path("data/lake/opportunities.json")
TABLE = "opportunities"
UPSERT_BATCH = 500
RETIRE_BATCH = 200
# Some Supabase edges sit behind Cloudflare which rejects the default urllib
# UA with HTTP 403 code 1010; send a browser-ish UA to be safe.
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36")

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Fields surfaced into the `extra` jsonb, by relevance. Null/empty are dropped.
EXTRA_KEYS = [
    # jobs / internships
    "platform", "token", "job_id", "company_domain", "discipline", "skills", "salary",
    "season", "sponsorship", "program", "segment", "posting_age_days",
    # contributions
    "repo", "labels", "language", "difficulty", "difficulty_signal",
    "issue_number", "repo_stars", "discovery_source",
    # hackathons
    "prize", "tags", "start_date", "end_date", "is_online",
    "registration_deadline", "source",
    # programmes
    "organizer", "programme_status", "opening_date", "opportunity_type",
    "international_eligibility",
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


def is_serving(r: dict) -> bool:
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
        v = r.get(k)
        if v not in (None, "", []):
            extra[k] = v

    return {
        "id": stable_id(r),
        "type": t,
        "category": r.get("category"),
        "title": _first(r.get("title"), r.get("programme_name"),
                        r.get("organizer"), r.get("repo")),
        "company": _first(r.get("company_name"), r.get("company"),
                          r.get("organizer")),
        "location": r.get("location"),
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
        "description": _truncate(r.get("description"), 200),
        "deadline": deadline,
        "eligibility": _first(r.get("eligibility"),
                              r.get("international_eligibility")),
        "funding": r.get("funding"),
        "extra": extra,
    }


def build_serving(lake: list) -> list:
    return [map_row(r) for r in lake if is_serving(r)]


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
        with urllib.request.urlopen(req) as resp:
            raw = resp.read().decode()
            return resp.status, resp.headers, raw

    def fetch_all_ids(self):
        """Return the set of all ids currently in the table (paginated)."""
        ids, offset, page = set(), 0, 1000
        while True:
            status, hdrs, raw = self._request(
                "GET", "/%s?select=id&limit=%d&offset=%d" % (TABLE, page, offset),
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
        for i in range(0, len(ids), RETIRE_BATCH):
            chunk = ids[i:i + RETIRE_BATCH]
            in_list = ",".join(
                '"%s"' % urllib.parse.quote(x.replace('"', ''), safe="")
                for x in chunk)
            self._request(
                "PATCH", "/%s?id=in.(%s)" % (TABLE, in_list),
                body={"is_live": False},
                headers={"Prefer": "return=minimal"})


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
    args = ap.parse_args()
    dry = not args.execute

    if not LAKE_PATH.exists():
        print("ERROR: lake not found at %s — restore it from S3 first "
              "(aws s3 cp s3://$AWS_S3_BUCKET/lake/opportunities.json %s)"
              % (LAKE_PATH, LAKE_PATH), file=sys.stderr)
        return 2

    lake = json.load(open(LAKE_PATH))
    mapped = build_serving(lake)
    by_type, nc, uniq, dups = summarize(mapped)

    print("=" * 64)
    print("MODE: %s" % ("DRY-RUN (nothing written)" if dry else "EXECUTE"))
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
                existing = Supabase(url, key).fetch_all_ids()
                serving_ids = {m["id"] for m in mapped}
                to_retire = existing - serving_ids
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
    existing = client.fetch_all_ids()
    serving_ids = {m["id"] for m in mapped}
    for i in range(0, len(mapped), UPSERT_BATCH):
        client.upsert(mapped[i:i + UPSERT_BATCH])
        print("upserted %d/%d" % (min(i + UPSERT_BATCH, len(mapped)), len(mapped)))
    to_retire = sorted(existing - serving_ids)
    if to_retire:
        client.retire(to_retire)
    print("done. upserted=%d soft_retired=%d" % (len(mapped), len(to_retire)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
