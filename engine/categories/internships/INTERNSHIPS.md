# Internships - category doc

Status: LIVE. This category covers India-relevant internships for students and
early-career candidates. It uses official sources only, links to the official
page, and never submits an application. LinkedIn and Naukri are never accessed
or republished.

## How collected

Internships are a listing category collected by the engine only. The Unstop
public feed adapter in `engine/adapters/boards.py` reads
`unstop.com/api/public/opportunity/search-result` with `opportunity=internships`
and `oppstatus=open`. It is bounded to 60 pages; over-long reads are marked
`truncated`, and the adapter is churn-tolerant.

The `india_source` machinery in `pipeline/sweep.py` treats `{unstop, keka}` as
India-first. `core/filters.classify` maps their generic-remote rows to
`india_remote` and explicit-India rows to `india_located`. `is_internship` is
classified from title words: `intern`, `internship`, `trainee`, or `apprentice`.
`REMOTE_ANY` matches `online`, `virtual`, `remote`, `wfh`, or `hybrid`.
Each Unstop internship shows its real organizing company, read from the source
record's `organisation.name`; aggregator rows no longer display the platform
label `Unstop`. The sweep writes `company_name = posting.company or the
registry entry's company`.

### Technical-only surfacing

The internships feed targets a software/CS/data audience. A row surfaces only
when its title is affirmatively technical and not another engineering branch.
Non-technical roles (marketing, business development, campus ambassador,
community, HR, content/video, operations) and non-software engineering (civil,
mechanical, electrical, etc.) are retained in the lake but hidden from the
default feed via `hidden_reason='non_technical'` (internship-gated in
`core/filters.py`). Regular Jobs are unaffected.

## Registry and view

The hand-audited Indian companies in
`engine/data/operations/registry.json` include Groww (manual-verified) and
Sprinklr, Zluri, Fractal, Observe.AI, and Uniphore (resolved from an audited
lead list).

`list_internships` in `engine/categories/internships/internships.py` reads the
canonical lake and filters rows with `record_type` absent and `is_internship`
true. Its default view sorts by `access_rank`: `india_located` first, then
`remote_global` (including `india_remote`), and `foreign_onsite` last.
Accessibility ranks are `india_located` (0), `remote_global` (1),
`foreign_onsite` (2), and `excluded` (3). Foreign-onsite internships are
retained, labeled, and ranked lower; they are not deleted.

Run its view-only CLI from `engine/`. `--india` selects India-located and
India-remote rows, `--surfaced` selects rows with `hidden_reason` of `None`,
and `--foreign` selects on-site-abroad rows only:

```bash
python3 -m categories.internships.internships --list
python3 -m categories.internships.internships --list --india
python3 -m categories.internships.internships --list --surfaced
python3 -m categories.internships.internships --list --foreign
```

Bounded validation 2026-08-20: Unstop returned 800 open opportunities / 773
internships; ~179 surface as technical (cse=111, technical-unknown=68); ~150
non-technical dropped from the feed vs. the prior generic filter. Runtime metric,
not a stored count.
The code change does not rewrite already-collected rows; the stored lake reflects
the real company names and technical-only surfacing after the next daily sweep.

## Jobs note

Jobs are good enough via the same `india_source` machinery: India tech roles
surface through it, and there is no separate jobs doc or worklist. We are not
grinding more employers by design. Darwinbox is deferred as the biggest untapped
India employer source.

## Guardrails

The one canonical lake is `engine/data/lake/opportunities.json`. Failed,
blocked, or partial reads never close a row.

## Community lists (2026-08-22)

The category also ingests zshah101's
`Automated-List-Of-Summer-2027-and-Fall-2026-Tech-Internships` (MIT © Shah
Zain); provenance and attribution are recorded on every row. The machine-readable
source is `docs/api/jobs.json` via `raw.githubusercontent.com`. Its scope is US
Software and Data/ML internships for Summer 2027 and Fall 2026.

The category-owned collector is `python3 -m categories.internships.lists`. It
runs **before the daily sweep**, so accessibility, quality, and deduplication
apply in the same run. It accepts **official employer/ATS apply links only**
(Workday, Greenhouse, Ashby, Lever, SmartRecruiters, Workable, and Oracle
Cloud), never a repository or aggregator URL. Rows are job-shaped (`record_type`
absent), and `is_internship` is set from the source authority, including Co-op
listings that the title regex would miss. Accessibility uses `core.filters`: US
roles land in `foreign_onsite` (kept and searchable, ranked below India/remote),
while remote roles land in the remote tier.

Rows are deduplicated by normalized official apply URL across the whole lake
(board jobs, Unstop, and within the list). The source owns liveness with a
7-day reconfirmation window: a listing dropped by the source after a successful
fetch is closed; a failed fetch never closes rows.

dreamworkhq/Tech-Internships-2027 was **EVALUATED and SKIPPED**: MIT-licensed
but every listing links to `www.dreamworkhq.com/job/<uuid>` (an intermediary
aggregator), never the employer's official apply URL — rejected under the
official-links-only rule, same class as LinkedIn/Naukri.

Last worked 2026-08-22: first run added 241 rows, deduped 7 against existing
lake rows, and produced 233 `foreign_onsite` / 8 remote.

Last worked 2026-08-27: the missing-only `is_internship` backfill bug was fixed;
the next sweep is expected to recover approximately 292 real-company
internships from Jobs. The intended UI source ordering is real-company ATS
platforms first, then `zshah101-list`, with Unstop last.
