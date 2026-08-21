# Active engine reference

The active collector is `engine/`, and all commands below are run from that
directory. This document describes implemented layout and persistence; it does
not claim universal source coverage or a universal freshness SLA.

## Operating model
The engine runs once a day and its deterministic sweep establishes liveness/freshness for every row. Categories collect in two modes:
- Calendar/programme categories: Open Source programmes are fetched by the engine, with liveness tracked and prose pages read for dates, eligibility, and funding. Fellowships, Grants & Funding, Scholarships, and Hackathons & Competitions are planned / not yet built: category scaffolding only, not actively collected. This uses the evidence-gated extractor (adapters/extractors.py LLMExtractor) or, until an API key is configured, a human-in-the-loop AI verifier. AI records only facts it can quote from the official page and never invents; a failed/unclear read never closes a row. These are low-volume, so AI verification runs about twice a month.
- Listing categories (Jobs, Internships, Apprenticeships, OSS good-first-issues): structured sources (boards/APIs/GitHub) collected by the engine only. Internships and OSS good-first-issues are actively collected; the OSS good-first-issues collector is implemented under engine/categories/open_source/.

Update this file whenever the engine changes.

Location handling is India-first for the audience, but jobs are not hidden by country. Every job is classified by accessibility: `india_located`, `remote_global`, `foreign_onsite`, or `excluded`, and ranked accordingly. Source-aware handling still means Unstop and Keka treat unspecified or generic remote locations as `india_remote`, while explicit foreign locations keep their normal bucket.

The default feed shows ONLY `india_located` and `remote_global` rows. `foreign_onsite` rows are retained, searchable, and ranked lower. Rows classified as `excluded`, including `region_excludes_india` cases such as `Remote – US only`, go to `data/lake/hidden.json`. The old `not_india` location-hiding is no longer produced. `hidden_reason()` remains internship-aware: for internship rows it surfaces only affirmatively technical, non-other-engineering titles and hides the rest as `non_technical`; non-internship job rows keep the prior behavior (only technical is False + discipline `non_tech` hides).

Jobs and Internships are India-first and technical for students and early-career candidates in India. All other categories - Open Source programmes and good-first-issues, Fellowships, Grants & Funding, Scholarships, and Hackathons & Competitions - are worldwide and open to anyone; never apply an India/location filter to them.

On job rows, `quality.annotate` stamps `accessibility` and `access_rank`; non-job rows pass through untouched. `quality.report` emits `surfaced_by_accessibility`. `sweep.py` is unchanged: pass-through for non-job rows, the reconfirmation window, and Unstop/Keka `india_source` handling remain intact. Job rows now also carry `is_internship`, derived from title signals. Resolver registry writes preserve manually curated non-`resolver` entries unless a resolver result has the same platform/token.

## Purpose and flow

The collector resolves named companies to official employer/ATS sources, reads
structured boards where possible, reads selected pages where necessary, filters
and annotates rows, retains evidence, and publishes JSON artifacts. It never
submits applications and never treats generic eligibility signals as an
individual eligibility promise. LinkedIn and Naukri are not accessed or
republished.

```text
optional enumeration -> engine/data/raw/discovery-cache/ (leads only)
company resolver -> engine/data/operations/registry.json
board adapters -> lake/opportunities.json + lake/hidden.json
page reader -> operations/pagereader_rows.json (operational output only)
run/state -> engine/data/operations/
```

A successful empty result is different from an error or partial read. Only a
complete, successful source confirmation can support absence-based liveness;
uncertain reads do not establish closure. Records are retained.

## Packages and commands

`core/` owns shared cache, filters, quality, robots, page-text, tiering, and
`paths.py`. `adapters/boards.py` owns the existing large board adapter module;
`adapters/extractors.py` owns fixture/optional-LLM page extraction. Runnable
collection and maintenance scripts live in `engine/pipeline/` and are invoked
as `python3 -m pipeline.<name>` from `engine/`.

| Script | Invocation from `engine/` | Purpose |
|---|---|---|
| `engine/pipeline/sweep.py` | `python3 -m pipeline.sweep` | Collect resolved boards, apply filters/quality, merge retained lake rows, and append a run report. Network collection; use CI for full sweeps. |
| `engine/pipeline/resolve.py` | `python3 -m pipeline.resolve` | Resolve a company/domain to a source and verify readable boards. Network collection. |
| `engine/pipeline/resolve_companies.py` | `python3 -m pipeline.resolve_companies` | Rewrite the operational registry and page-reader target queue. Network collection. |
| `engine/pipeline/read_pages.py` | `python3 -m pipeline.read_pages` | Read queued careers pages and write operational page-reader state/rows. Network collection and optional model enrichment. |
| `engine/pipeline/read_url.py` | `python3 -m pipeline.read_url` | Inspect one URL using known APIs or HTML fallbacks. Network collection. |
| `engine/pipeline/enumerate_boards.py` | `python3 -m pipeline.enumerate_boards` | Optional Common Crawl lead enumeration; writes discovery cache only. Network collection. |
| `engine/pipeline/build_fixtures.py` | `python3 -m pipeline.build_fixtures` | Fetch/show/check committed offline fixtures; only `check` is offline. |

Useful offline checks from `engine/` include
`python3 -m pipeline.build_fixtures check`, `python3 -m unittest tests.test_robots`,
and the archive verifier at `python3 tools/verify_oldengine_archive.py`. Do not
interpret these as a sweep or source-coverage check.

## Canonical persistence

All paths are absolute/package-derived by `core.paths` and are listed here
relative to `engine/`:

| Path | Role |
|---|---|
| `data/lake/opportunities.json` | The one canonical final user-facing opportunity lake. It holds three record types: job rows (the absence of a `record_type` field), programme rows (`record_type='programme'`), and contribution rows (`record_type='contribution'`). |
| `data/lake/hidden.json` | Retained non-default companion for rejected/hidden rows; not deleted. |
| `data/lake/opportunities_history.json` | Historical opportunity evidence. |
| `data/operations/registry.json` | Resolver-confirmed company-scoped board registry. |
| `data/operations/runs.jsonl` | Append-only operational sweep reports. |
| `data/operations/tier_state.json` | Persistent board tier history. |
| `data/operations/pagereader_state.json` | Page content hashes and extraction state. |
| `data/operations/pagereader_targets.json` | Resolver queue for page-reader/re-resolution work. |
| `data/operations/pagereader_rows.json` | Operational processing/compatibility output from the page reader; explicitly not a second final lake. |
| `data/operations/companies.txt` | Resolver input. |
| `data/raw/` | Private HTTP response recordings; raw source text is not product output. |
| `data/raw/discovery-cache/` | Common Crawl lead caches, separate from private HTTP recordings. |
| `data/measure/` | Historical measurement evidence; old command strings there are historical records, not active paths. |

The sweep writes the canonical opportunities and hidden stores. The page reader
maintains its operational rows separately and does not create a category lake.
`LAKE_RAW_DIR` may relocate private HTTP recordings; it must not relocate the
discovery cache. Raw recordings and the discovery cache are not the canonical
user-facing data.

### Pass-through safety

The daily sweep reads and writes programme and contribution rows untouched: it
never re-keys, merges, closes, or quality-annotates non-job rows. Only job rows
enter the merge/liveness/quality path. This is locked by regression tests
`tests/test_sweep_passthrough.py` and `tests/test_quality_record_types.py`.
`core/quality.py` skips non-job rows: `_is_job_row` returns
`record_type not in ('programme','contribution','hackathon')`. Hackathon rows are
non-job pass-through records; this is the one shared-engine behavior change for
the category. `engine/categories/hackathons/` is a structured live-source
collector for Devpost, MLH, and Unstop, built on the contributions.py pattern
with direct stdlib `urllib` and no adapter changes. It runs as its own daily
sweep step; the sweep never merges, closes, or quality-annotates these rows, and
the collector owns their freshness/liveness.

## Trust and source notes

Discovery leads are never product verification. A row should not be displayed
as live or verified without the official source URL, provenance, and a recent
successful confirmation. Errors, stale checks, blocked pages, and partial reads
are needs-confirmation states rather than closure facts. Descriptions may be
retained internally for extraction and audit, but user surfaces link to the
official source rather than displaying a full description.

Keka has a documented public JSON API. Zoho Recruit and Darwinbox remain
page-reader or bespoke-source work. Workday is implemented, but pagination and
read completeness need monitoring. AI is optional page enrichment and the quote
gate prevents it from inventing source facts.

## CI

The engine runs once a day: the board sweep runs at 06:30 IST (`0 1 * * *` UTC)
and the page-reader runs at 08:00 IST (`30 2 * * *` UTC). The daily sweep also
runs the Open Source programme and contribution collectors, then makes one
atomic commit covering all record types and pushes it. The page-reader commits
and pushes separately. Everything ends up on `origin/main`.

The root workflow is `.github/workflows/sweep.yml`; its jobs keep
`working-directory: engine`. It stages canonical lake files and operational run,
tier, and page-reader state files from `engine/data/**`. Artifact uploads use
the reorganized paths and deliberately exclude private raw recordings. Full
sweeps are CI work, not lightweight migration validation.

## Categories

`engine/categories/` is scaffolding for category predicates/annotations and
category-specific processing helpers only. It does not activate or claim any
category, and it must not own a final database. Category work is one category at
a time and uses the shared canonical lake and trust policy. Category-specific docs and implementation helpers belong under the relevant
category folder; they use the shared canonical lake and trust policy and do not
create a category database. See `REGISTRY-PLAN.md`.

## Archived legacy tree

The inactive legacy source was archived, verified, and deleted with explicit
approval. Its dated archive is
`archive/opportunity-lake-oldengine-2026-08-16/`. The archive manifest records
included files, sizes, hashes, capture metadata, exceptions, and cache files
omitted because they were byte-identical to the active discovery cache.
`SHA256SUMS` covers included archive files. Verify the archive with:

```bash
python3 tools/verify_oldengine_archive.py
```

### Official open-source programmes

`python3 -m categories.open_source.programmes` from
`engine/categories/open_source/programmes.py` tracks 41 verified worldwide
programme sources. Open Source programmes are worldwide and open to anyone.
Evidence-gated verification records only facts quoted from the official page
and their official URLs, and requires an official quote and URL for `status`,
`opening_date`, and `deadline`. Programme rows set
`record_type='programme'`.

The pipeline extracts only source-backed quotes and URLs, resolves application
links only on the seed or final redirect origin, and leaves unstated fields as
`not_stated` or `needs_confirmation`. Only evidence-verified open, opening, or
rolling records surface as live now (~6 live now); the rest are off-season. A
surfaced `open`, `rolling`, or `opening_soon` record always has the registry's
`official_url`. `rolling` also requires a resolvable absolute
`application_url` restricted to the seed/final origin as its actionability
evidence. `open` and `opening_soon` require no separate apply link: their exact
official date window is sufficient, so `application_url` may be null and
`official_url` is the action link. Only `open`, `rolling`, and exact-date
`opening_soon` states become canonical programme rows. A failed or blocked read
never closes a row, but a successful read showing a programme is off-season or
closed can close a previously-live row.
Programme observations and rows are written atomically, malformed existing lake
state fails closed, and merge preserves unrelated job rows and source-scoped
liveness fields.

### Open-source contributions

`engine/categories/open_source/contributions.py` (run with
`python3 -m categories.open_source.contributions`) collects good-first-issues
from ~45 curated repositories plus GitHub Search discovery. Discovery is
token-gated: it reads `GITHUB_TOKEN`, populated in CI from a `GH_PAT` secret or
the built-in token; without a token it collects curated repositories only. The
discovery floor is stars>=500, good-first-issues>=3, pushed within 60 days, plus
an updated-recency qualifier. Quality filters drop issues stale >120 days or
with >30 comments. Results are surfaced freshest-first, and each contribution
row carries `language`, `difficulty`, `is_new_this_month` (30-day window), and
`is_recently_active` (3-day window). A 7-day reconfirmation window retires
unseen rows to `needs-confirmation` (`is_live=False`) rather than leaving them
falsely live. Contribution rows set `record_type='contribution'`.

### Shared programme engine

`engine/categories/programme_core.py` provides category-parameterized programme collection via `ProgrammeConfig(category, opportunity_type, source_registry, observations_path, verifications_path)`. `engine/categories/open_source/programmes.py` and `engine/categories/research/research.py` are thin wrappers over it; the Open Source public API is unchanged. Research rows are `record_type='programme'`, `opportunity_type='research_programme'`, `category='research'`, and follow the same pass-through rules as Open Source programme rows: the daily sweep never re-keys, merges, or closes non-job rows.

`parse_programme` now includes an additive, evidence-gated normalization: when a single application date's official evidence quote contains `deadline`, it is recorded as the deadline and is not surfaced as an opening date. Research is collected via `python3 -m categories.research.research` and is not yet wired into the daily sweep.

## Internships and jobs

Internships are collected via the Unstop public feed adapter in
`engine/adapters/boards.py`: `unstop.com/api/public/opportunity/search-result`
with `opportunity=internships` and `oppstatus=open`, bounded to 60 pages;
over-long reads are marked truncated and are churn-tolerant. The `india_source`
machinery in `pipeline/sweep.py` marks `{unstop, keka}` as India-first, and
`core/filters.classify` maps their generic-remote rows to `india_remote` and
explicit-India rows to `india_located`. `is_internship` is classified from
title words (intern/internship/trainee/apprentice); `REMOTE_ANY` also matches
online and virtual, plus remote/wfh/hybrid. `Posting` has a `company` field.
Single-company boards leave it blank and inherit the registry entry company;
aggregator adapters (e.g. Unstop) populate it per posting (Unstop from
`organisation.name`). The sweep writes `company_name = posting.company or
registry entry company`, so aggregators show the real employer while
single-company boards are unchanged.

Hand-audited Indian companies live in
`engine/data/operations/registry.json`: Groww is manual-verified; Sprinklr,
Zluri, Fractal, Observe.AI, and Uniphore were resolved from an audited lead
list. A `list_internships` view/CLI exists in
`engine/categories/internships/internships.py`. ~179 technical internships
surface at runtime, not as a stored metric. Jobs are good enough through
the same `india_source` machinery: India tech roles surface through it, rather
than grinding more employers by design.

## Deferred / future work

Fellowships, Grants & Funding, Scholarships, and Hackathons & Competitions are planned / not yet built; their category scaffolding is not actively collected. Deferred work also includes Darwinbox (the biggest untapped India employer source),
C4GT (JS-only site; it needs its JSON API or a JS-capable fetch, with no
headless browser), the AWS move at launch (data moves from the git repo to
S3/DB), and an AI API key to automate programme verification. Until then,
programme verification is done manually by a human-in-the-loop AI.
