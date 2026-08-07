# LAKE — the engine reference

Technical reference for the Opportunity Radar collector. Updated 2026-08-07.

Companion to `PRODUCT.md`. The split is deliberate:

- **PRODUCT.md** — what we are building, for whom, and which decisions are
  settled. Product, trust contract, scope, growth, decision log.
- **LAKE.md** — how the engine works. Architecture, module map, data flow,
  record shape, how to run it, current state, known defects.

A new session should be able to read both and start work without asking for
background.

## 1. What the engine does

It finds opportunities at official sources, reads them politely, decides which
are relevant to early-career candidates, and maintains a record of what is
currently present and when it was last confirmed. It does not delete history and
it does not republish full descriptions.

Data flow, in order:

```
discover   public indexes, registries, VC and incubator portfolios -> leads
resolve    a lead -> its official ATS / employer / programme URL
read       platform adapters, pagination, page reads
classify   title, location, stage, discipline, eligibility gates
merge      dedupe, update last_seen, decide liveness, retain history
store      jobs.json (public), hidden.json (filtered out), archive
```

The critical asymmetry: **finding a posting is evidence it exists; not finding
one is not evidence it is gone.** Absence only counts when the read that missed
it was both error-free and complete.

## 2. Module inventory

| File | Lines | Role |
| --- | ---: | --- |
| `build_fixtures.py` | 134 | Build page-reader fixtures |
| `cache.py` | 200 | Cache raw HTTP responses |
| `enumerate_boards.py` | 232 | Discover ATS boards from Common Crawl |
| `extractors.py` | 434 | Extract roles from careers pages |
| `fetch.py` | 1,716 | Fetch board listings through platform adapters |
| `filters.py` | 1,180 | Apply title and location filters |
| `pagetext.py` | 112 | Convert HTML to text and hash content |
| `quality.py` | 665 | Check collected rows for lake hygiene |
| `read_pages.py` | 277 | Read and enrich careers pages |
| `read_url.py` | 435 | Read one opportunity URL |
| `resolve.py` | 538 | Resolve companies to official boards |
| `resolve_companies.py` | 212 | Resolve company inputs and write registries |
| `robots.py` | 356 | Enforce robots.txt and crawl delays |
| `sweep.py` | 509 | Sweep boards, merge rows, update liveness |
| `tiering.py` | 223 | Assign board scheduling tiers |

Tests: test_enumerate_boards.py, test_extractors.py, test_partial_read_liveness.py, test_robots.py, test_tiering.py

Run them from the `engine` directory with `python3 -m unittest discover -s tests`.
They are offline and use fixtures; none makes a network call.

## 3. Source adapters

Fifteen platforms are registered: greenhouse, lever, ashby, smartrecruiters,
workable, workday, personio, recruitee, keka, eightfold, successfactors,
zohorecruit, darwinbox, amazon, unstop.

Real pagination loops exist for Unstop, SmartRecruiters, Workday, Eightfold and
SuccessFactors (child sitemaps). The others read a single response.

Keka has a documented public JSON API:
`/careers/api/embedjobs/{portalName}/active/{board_guid}`. Zoho Recruit and
Darwinbox remain page-reader or bespoke work. Workday's pagination completeness
must be monitored rather than assumed.

## 4. Read outcomes — the rule that matters most

`BoardResult.ok` means no error. `count` is the number of postings returned. A
successful empty read is `error=None, count=0` and is genuinely different from a
failure.

Three outcomes, three behaviours:

| Outcome | Enters `boards_read`? | Can close absent rows? |
| --- | --- | --- |
| Errored | No | No |
| Truncated / partial | No | No |
| Complete, including empty | Yes | Yes |

Only boards in `boards_read` are allowed to mark previously-seen rows as not
live. Rows returned by a truncated read are still ingested and still count as
seen — the restriction is only on inferring absence.

## 5. Record shape

Canonical rows live in `data/jobs.json`; rows rejected by filters live in
`data/hidden.json`. Both are retained.

Fields present today include: `platform`, `token`, `job_id`, `title`,
`location`, `url`, `posted_on`, `description`, `company_name`, `company`,
`segment`, `stage`, `stage_title`, `stage_resolved`, `experience_min`,
`experience_max`, `experience_conflict`, `batch_years`, `degree_required`,
`enrolled_required`, `eligibility_evidence`, `gates_found`, `gates_missing`,
`eligibility_status`, `hidden_reason`, `technical`, `discipline`,
`needs_description`, `location_bucket`, `source_mechanism`, `first_seen`,
`last_seen`, `is_live`, `is_recruiter`, `cities`, `states`, `title_norm`,
`posting_age_days`, `is_stale`, `is_pay_to_intern`, `dup_of`, `over_cap`,
`surfaced`.

The eligibility gate fields are the most valuable data in the lake and the
frontend currently displays none of them.

**Fields required by the product and still missing** (see PRODUCT.md §5):
`official_url`, `source_provenance`, `last_confirmed_at`, a three-value
`status`, `opportunity_kind`, `liveness_model`, `deadline`, `read_outcome`.
Canonical rows currently use `url`, not `official_url`; `official_url` exists
only in `calendar.json` and the Unstop adapter.

Dedupe is by normalised official URL, falling back to platform/token/title.
Existing rows keep their original `first_seen` and only `last_seen` is updated.

## 6. Status semantics

Required by the trust contract:

- **live** — recently confirmed present at the official source.
- **needs confirmation** — errors, stale checks, ambiguous expiry, blocked
  pages, partial reads. Uncertainty is never rounded to live or closed.
- **closed** — reliably confirmed absent. Hidden from default search, never
  deleted.

The code today has only a boolean `is_live` plus `is_stale` and `went_dead_at`.
There is no third state, so "needs confirmation" has nowhere to live. This is a
known gap, not a design choice.

## 7. Collector conduct — non-negotiable

- One request at a time per host, with a delay, an honest User-Agent, and
  `robots.txt` respected.
- LinkedIn, Naukri and Wellfound are never accessed. Their listings are leads at
  most and are never republished.
- Never display a full job description. Link to the official source.
- Presence-based rows (jobs, internships) are read daily. Deadline-based rows
  (fellowships, grants, scholarships, research and OSS programmes) are read
  weekly — their state comes from stored dates, so daily reads buy nothing.
- Getting banned costs more than the marginal supply.

## 8. Running it

Always run from the `engine` directory so paths and artifacts stay unambiguous.

```bash
cd engine

# cheap local test — do this, not a full sweep
LAKE_LIMIT=20 LAKE_WORKERS=2 python3 sweep.py keka greenhouse

# filter test set
python3 filters.py

# one board
python3 fetch.py greenhouse vercel

# resolve companies from an engine-local input file
python3 resolve.py --file companies_india.txt

# tests
python3 -m unittest discover -s tests
```

Environment: `LAKE_REGISTRY`, `LAKE_WORKERS`, `LAKE_HOST_DELAY`, `LAKE_LIMIT`,
`LAKE_COMPANY_CAP`. Full sweeps belong on CI, not a laptop.

CI (`.github/workflows/sweep.yml`) runs `sweep.py` twice daily at 01:00 and
13:00 UTC, and `read_pages.py` daily at 02:30 UTC. The page-reader job exits 0
when `XLAKE_LLM_API_KEY` is absent, so it is normally a no-op.

## 9. Current state — measured 2026-08-07

- `jobs.json` 9,385 rows. `hidden.json` 9,218 rows. Roughly 34 MB combined.
- **198 rows surfaced — 2.1%.** The bottleneck is classification, not filters.
- `stage` unknown on 8,013 rows (85%). `discipline` unknown on 4,794 (51%).
- `eligibility_status`: hidden 8,214, confirmed 494, rules_unclear 677.
- `location_bucket`: global_hiring 7,992, india_located 1,392, **india_remote 1**.
- Three successful local sweeps on 2026-08-04 (kept_total 8,026 -> 8,477 ->
  9,385). Same-day re-confirmation works; `first_seen` is preserved.
- No cross-day history exists, because no sweep has run since.

## 10. Known defects and gaps

1. **`engine/` is untracked.** Nothing under it has ever been committed. CI
   checks out a pre-restructure tree, finds nothing to add, and its commit step
   has no `--allow-empty`, so it silently pushes nothing. This is also why the
   project has no backup. Highest priority.
2. **`india_remote` classifier is broken** — 1 row out of 9,385, while
   India-remote is core to the declared scope.
3. **No third status state**, no `last_confirmed_at`, no `source_provenance`, no
   `official_url` on canonical rows.
4. **Stale robots test** —
   `test_robots.TestKeka.test_stdlib_disagrees_which_is_why_this_module_exists`
   fails because stdlib behaviour changed. Robots handling rests on an
   assumption that no longer holds.
5. **Tiering leak** — a truncated read returning zero rows still calls
   `tiering.record_sweep(qualifying_count=0)`, so an unreliable read can demote
   a board's scheduling tier.
6. **Page-reader output is orphaned** — `data/pagereader_rows.json` is 2 bytes
   and never merges into `jobs.json`.
7. **CI does not run the tests**, so nothing protects the trust invariants.
8. **No dependency manifest**, so runtime reproducibility is unverified.
9. **34 MB of generated JSON is committed to git** twice daily by design. This
   should move to S3 with a small serving file.

Fixed 2026-08-07: truncated reads no longer enter `boards_read`, so a partial
read can no longer mark absent rows not live. Regression test at
`tests/test_partial_read_liveness.py`.

## 11. Proposed directory structure — not yet applied

Currently every module sits flat in `engine/`, and `fetch.py` holds all fifteen
adapters in one file. The proposed layout groups by pipeline stage, which is the
order data actually moves in:

```
engine/
  core/        shared plumbing: http, robots, rate limiting, record model
  discover/    finding leads: VC and incubator portfolios, registries, indexes
  resolve/     lead -> official source
  sources/
    ats/       one file per platform
    programmes/  GSoC, LFX, Outreachy, government and university programmes
    pages/     page-reader and the AI recipe cache
  classify/    filters, eligibility gates, stage/discipline/location
  pipeline/    sweep, merge, liveness, tiering, retention
  store/       jobs/hidden IO, S3 archive
  data/        generated artifacts
  tests/
```

Why not a folder per source category (ATS, startups, incubators, programmes):
those mix two different axes. "ATS" is a way of *reading*; an incubator
portfolio is a way of *finding*; and a startup is neither — it is a company
found via a portfolio and read via an ATS. Grouping by pipeline stage keeps each
folder meaning one kind of thing, and new source families land in an obvious
place.

**Do not perform this refactor until `engine/` is committed.** Restructuring
untracked code with no revert path is how work gets lost.

## 12. Work order

Authoritative list lives in PRODUCT.md §13. Summary:

1. Commit `engine/`, keep generated data out of git, fix CI paths, prove
   cross-day accumulation.
2. Port the unreachable-versus-empty distinction from the Desktop engine; stop
   truncated reads from demoting tier state.
3. Fix the `india_remote` classifier.
4. Add the missing record fields and S3 archiving.
5. Backfill-classify the 8,013 unknown-stage rows with a cheap model — the
   largest available supply unlock.
6. Add new source families, accelerator portfolios first.
