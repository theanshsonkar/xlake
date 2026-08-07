# Xlake — Opportunity Radar

Canonical context document. Product decisions, engine architecture, measured
facts, and work order. Updated 2026-08-07.

This file exists so context is not lost between sessions. It separates what is
**decided**, what is **measured and verified**, and what is a **target not yet
true**. Do not blur those three.

## 1. What this is

A search engine for early-career opportunities that come from official sources.

Tagline: **Search every opportunity. Decide what fits.**

Positioned as Skyscanner for opportunities — not a job board, not a career-prep
product, not an application submitter. The value is provenance and freshness:
every result has a known source, an observed-live time, and a verification
state. The official source is always the primary call to action.

What it never does: submit an application, promise an individual is eligible,
republish a full job description, or touch LinkedIn, Naukri, or Wellfound.

## 2. Two repositories

- `/Users/anshsonkar/opportunity-lake` — the collector. Python. 15 ATS
  adapters. Produces the JSON the product consumes. No UI.
- `/Users/anshsonkar/Desktop/xlake` — the frontend. React + Vite + TypeScript
  on the Astryx design system (`@astryxdesign/core` + `theme-neutral`), dark
  mode, search-first two-column layout.
- `/Users/anshsonkar/Desktop/jobs` — an earlier personal collector. Not the
  product, but contains logic worth porting (see section 9).

The collector and frontend are **not yet wired together**. The frontend runs on
11 hardcoded records.

## 3. Audience and scope — decided

**Audience:** Indian early-career technical candidates, student through roughly
two years of experience.

**Decision: do not widen the audience.** The apparent supply shortage is not
caused by the early-career filter. It is caused by the engine failing to
classify what it collects (see section 6). Widening the person dissolves the
positioning and puts us against Naukri. Widening the opportunity type and the
geography grows supply for the same audience and is defensible.

**Opportunity types in scope:** jobs, internships, fellowships, research
programmes, open-source programmes, grants, scholarships, funds, hackathons.

**Geography:** India, plus global remote, plus roles that support visas.

**Beta timing:** no fixed date. Beta is when the engine is ready and the
frontend is wired to it.

## 4. Trust contract

These are display semantics and acceptance requirements. They are targets, and
the collector does not fully enforce them yet.

- **Live** means recently confirmed present at the official source. The last
  confirmation time is shown. This is not a universal freshness guarantee.
- **Needs confirmation** covers errors, stale checks, ambiguous expiry, blocked
  pages, and partial reads. Uncertainty must never be rounded into live or
  closed.
- **Closed** means reliably confirmed absent. Closed rows are hidden from the
  default view but never deleted.
- A partial or truncated read must never establish closure or completeness.
- No individual eligibility promise is ever made. Report what the source says
  and what it does not say.
- Coverage is incomplete by design and must be stated as such.

**Wording rule:** the UI must use observational language, not evaluative.
"Seen at official source on 31 Jul", not "Verified by Xlake". "Verified"
implies vetting that does not happen and invites a claim that cannot be
defended.

## 5. Record model — decided target

One record type, not two. A flag selects the liveness rule. Jobs disappear from
the page when they close; programmes do not, they have deadlines. Two rules,
one pipeline, because the UI treats them identically.

Fields that must exist and do not exist today on canonical rows:

- `official_url` — the real application link. The primary CTA depends on it.
- `source_provenance` — structured record of where this was found.
- `last_confirmed_at` — machine-readable last successful confirmation.
- `status` — one of `live`, `needs_confirmation`, `closed`. Replaces the
  `is_live` boolean, which has no room for uncertainty.
- `opportunity_kind` — job, internship, fellowship, research programme,
  open-source programme, grant, scholarship, fund, hackathon.
- `liveness_model` — `presence` or `deadline`.
- `deadline` — a real date, not free-form text.
- `read_outcome` — records whether the read was complete, partial, blocked, or
  errored.

Existing fields worth keeping: the eligibility gates (`experience_min`,
`experience_max`, `batch_years`, `degree_required`, `enrolled_required`,
`gates_found`, `gates_missing`, `eligibility_evidence`). These are the most
valuable data in the lake and the UI currently shows none of them.

## 6. Measured facts as of 2026-08-07

Verified by reading the actual data and code, not inferred from docs.

**CI has never persisted a sweep.** There are no `opportunity-lake-bot` commits
and `engine/data/jobs.json` is not in the git index. The current data is a
local working-tree artifact from three manual runs on 2026-08-04, recorded in
`runs.jsonl`: 04:13:58Z (20/20 boards, kept_total 8,026), 06:51:38Z (23/24 ok,
kept_total 8,477), 14:47:02Z (19/20 ok, kept_total 9,385). The workflow itself
looks sound — twice-daily schedule enabled, checkout, commit and push as a bot,
no regeneration step — it simply has not run or has never succeeded. Evidence
limitation: only git reflog was available, not full git log, so bot commits
existing on the remote cannot be ruled out.

**Root cause of the CI failure — established 2026-08-07.** The whole `engine/`
directory is untracked. `git ls-files engine/data/` is empty and
`git log --all -- engine/data/jobs.json` returns nothing; nothing under
`engine/` has ever been committed. An `opportunity-lake-bot` commit exists from
2026-07-31, so CI did work once — against the old layout, when the collector
lived at the repo root. The local restructure into `engine/` was never
committed, so CI checks out a tree that no longer matches what runs locally and
its `git add data/...` finds nothing. The step has no `--allow-empty`, so it
skips the commit and pushes nothing. Not a gitignore issue — the data files are
untracked, not ignored. The remote is `https://github.com/theanshsonkar/xlake.git`.

**Risk: the engine exists only on one disk.** 15 adapters, filters, sweep,
tests and data are untracked, not on any remote, not backed up. Losing the
working tree loses the project. Committing `engine/` is both the CI fix and the
backup fix.

**Merge logic is correct — verified.** `engine/sweep.py:161-164` loads the
existing `jobs.json` from disk before writing. `:177-199` updates an existing
record by setting only `last_seen`, preserving `first_seen`. New rows get both
at `:202-206`. History does accumulate. Current records show genuine same-day
re-confirmation: `first_seen` 2026-08-04T04:13:56Z, `last_seen`
2026-08-04T14:47:00Z.

**What is actually missing is cross-day history.** Nothing has ever been
confirmed on a later calendar date, because no sweep has run since 2026-08-04.
So liveness is unproven in practice even though the mechanism works, and 8,340
rows are marked `is_live=true` having last been checked three days ago. The gap
is operational, not logical.

**Supply is throttled by classification, not by filters.** Of 9,385 rows only
198 are surfaced — 2.1%. `stage` is unknown on 8,013 rows (85%). `discipline`
is unknown on 4,794 rows (51%). `eligibility_status` is hidden on 8,214 with
677 more as `rules_unclear`. These rows are not rejected for being senior or
non-technical; they are rejected because the engine could not tell. If a fifth
of the unknown-stage rows are genuinely early-career, that is roughly 1,600
surfaceable rows instead of 198.

**The india_remote bucket is broken.** `location_bucket` counts:
`global_hiring` 7,992, `india_located` 1,392, `india_remote` **1**. India-remote
is core to the declared scope and is effectively not working.

**The partial-read bug — FIXED 2026-08-07.** In `engine/sweep.py`, a board is
added to `boards_read` before the `truncated` check (around lines 278-282). A
successful-but-truncated read therefore becomes liveness-eligible and can mark
absent rows not live. Errored reads are correctly excluded. This is the one
place where code directly contradicts the trust contract. Fixed: a board now enters `boards_read` only when the read is both error-free and not truncated. Regression test at `engine/tests/test_partial_read_liveness.py` asserts the invariant in both directions against a real `sweep.sweep()` call.

**Other verified state.** `hidden.json` holds 9,218 rows. Canonical rows use
`url`, not `official_url`; `official_url` exists only in `calendar.json` and
the Unstop adapter. Page-reader output is orphaned — `pagereader_rows.json` is
2 bytes and its CI job exits early without an LLM key. Four unittest modules
exist and CI never runs them. There is no dependency manifest. CI commits ~34
MB of JSON back to the repo twice daily.

**Frontend gap.** `type Opportunity` in `src/App.tsx` is `id`, `company`,
`title`, `kind`, `location`, `freshness`, `status`, `summary`, `evidence`,
`tags`, `logo`. There is no URL field at all, so "Open application" has nothing
behind it, and `freshness` is free-form text so deadlines are not sortable.

**The robots test is stale.** `test_robots.TestKeka.test_stdlib_disagrees_which_is_why_this_module_exists`
fails: it asserts stdlib robots behaviour that has since changed. Pre-existing
and unrelated to any current change, but it means robots handling rests on an
assumption that no longer holds — which matters given that not getting banned is
a hard requirement.

**Remaining leak of the partial-read class.** A truncated read that returns zero
rows still calls `tiering.record_sweep(qualifying_count=0)`, so an unreliable
read can still demote a board's scheduling tier. Smaller consequence than false
liveness — it affects scheduling, not display — but the same mistake. Clean up
when tiering is next touched.

## 7. Cost architecture — decided

Budget ceiling: **$15 per month.** That is sufficient with this design and
impossible without it.

**Principle: spend AI once per source shape, never once per page per day.**

Ladder, cheapest first. AI is the last resort.

1. **Detect the ATS, don't read the site.** Most companies use a supported
   platform. Resolving a domain to its ATS API costs nothing per day.
2. **JSON-LD `JobPosting`.** Google for Jobs pushed structured markup into a
   large share of career pages. Free to parse, near-ATS quality. Hit rate
   across our companies is not yet measured and should be.
3. **Sitemaps, feeds, and change detection.** `robots.txt` → `sitemap.xml`
   often exposes job URLs with `lastmod`. Combined with ETag / Last-Modified /
   content hashing, almost all daily work is skipped because career pages
   rarely change.
4. **Recipe cache.** When a page needs interpretation, the model writes a
   reusable extractor once, keyed by domain plus structure hash. Replay it
   deterministically at zero cost. Re-invoke only when it breaks — zero rows,
   missing required fields, or changed structure hash. Cost scales with the
   number of distinct page templates, amortised, not pages times days.
5. **Direct AI page read.** Last resort, hard budget cap.

**Quality without expensive models — three mechanisms:**

- Never ask the same question twice. Hash content; reuse prior answers.
- Cheap model does the work, deterministic rules check it. If the model says
  "0-2 years" and the text says "8+ years", the rule catches it free. Escalate
  to a stronger model only on failed validation.
- Recipe induction uses a mid-tier model because it is rare; validation uses
  the cheapest because it is high-volume and trivial.

**Highest-value AI spend is not new sources.** It is a one-time cheap-model
backfill classifying the 8,013 unknown-stage rows already collected. That is
the supply unlock. Ongoing spend then touches only genuinely new rows.

## 8. Source families and build order

All of these are in scope. This is the order.

1. **Accelerator and VC portfolio directories** — YC, Antler, Peak XV, Accel
   India, Blume, a16z, Founders Inc, Techstars, Sequoia. These are discovery
   sources, not listing sources: take the public portfolio company list,
   resolve each company to its own ATS, and one page becomes hundreds of
   boards with zero per-company code. Reuses existing machinery. Highest
   leverage available.
2. **Foundation open-source programmes** — GSoC, LFX Mentorship, Outreachy,
   Season of Docs, MLH Fellowship. Small, fixed, stable, annually recurring,
   high value.
3. **Indian government and university research programmes** — ISRO, DRDO,
   BARC, IISc SRFP, IITK SURGE, INAE, DST/SERB/ICMR. Hardest to collect and
   the strongest differentiator: no commercial job board carries these, and
   they are exactly what this audience wants. Currently discovered through
   WhatsApp forwards and Instagram screenshots.
4. **Grants, scholarships, funds, hackathons.** Devfolio adjacent to the
   existing Unstop adapter. OSS bounty programmes. Conference travel grants
   and student volunteer programmes — low competition, high value.

**Recurring-programme leverage:** programmes repeat annually on roughly the
same schedule. Once GSoC 2026 is recorded, GSoC 2027 can be predicted and
pre-staged as "opens in about six weeks". That is supply generated from
memory rather than crawling.

**Legal line — must hold.** Public and robots-respecting only. LinkedIn,
Naukri, and Wellfound are never accessed and are leads at most. YC portfolio
directory is acceptable; YC Work at a Startup only if its robots and terms
allow it, checked first. One request at a time per host, with delay and an
honest User-Agent. Getting banned costs more than the marginal supply.

**Scan cadence differs by liveness model.** Presence-based rows (jobs,
internships) churn constantly and need a daily read. Deadline-based rows
(fellowships, grants, scholarships, research and OSS programmes) barely change
for months, and their state is computed from stored dates rather than observed
presence — so weekly is sufficient and daily is waste. This is both cheaper and
more correct: re-reading a programme page daily produces no new information and
spends politeness budget for nothing. One read per host at a time, with delay,
regardless of cadence.

## 9. Worth porting from the Desktop `jobs` engine

Verified present there, absent or weaker here:

- A proven-token ATS registry that distinguishes **unreachable** from
  **genuinely empty**. This is exactly the fail-closed distinction the main
  engine gets wrong.
- URL plus company/title dedupe keys.
- Immutable rejected-history so dead rows do not resurface.
- A split between a fast board sweep and a slower detailed eligibility fetch,
  which maps well onto the budget constraint.

It contains no AI or LLM code — parsing is regex and API based. Nothing to
reuse on extraction.

## 10. Storage — decided

Constraint: $5,000 of AWS credits available, and minimal infrastructure
wanted.

- **S3 for the archive.** Every raw board response, gzipped, keyed by date and
  platform. Costs cents at this volume. Gives permanent history, allows replay
  and recomputation without re-crawling anyone, and directly addresses the
  no-history problem.
- **A single small file for serving.** SQLite or one JSON file the frontend
  reads. No database service, no API layer, no running cost. Not needed at
  9,000 rows.
- Committing 34 MB of JSON to git twice daily is already a poor fit and will
  get worse. Moving the working store off git is a near-term need.

**Closed rows:** removed from the default view, retained in S3 permanently,
reachable behind a quiet toggle. Hiding is correct — users do not want dead
listings. Deleting is wrong — the recurring-programme prediction depends on
knowing when things opened in previous years.

## 11. Product surface decisions

- Two tabs: newly posted, and closing soon. **Closing soon is the default.**
  Deadline pressure creates a reason to return even on a day with no new
  supply. A search engine does not need daily new supply to earn daily visits.
- The detail panel leads with the **eligibility gates already extracted** —
  batch years, degree, experience, enrolled — plus, importantly, what the
  posting does **not** state. "The posting does not state a batch requirement"
  is high-value and stays safely on the right side of the trust contract.
- AI-written role summaries are deferred until budget allows.
- Personalised eligibility matching stays deferred. Broad search first. No
  candidate profile or matcher exists today.
- Chip counts must be scoped to the current query, never global.
- Row status line third slot needs explicit precedence: hard deadline, then
  rolling, then freshness.
- The mockup's header stats ("1,847 live roles") must not ship. That number
  restates a claim the docs already retracted in favour of a 150 confirmed-live
  V1 target, and nothing can currently prove liveness for any row. Header counts
  must be computed from real confirmed data or omitted. "New this week" is
  legitimately derivable from `first_seen`; "programmes" needs an
  `opportunity_kind` taxonomy that does not exist yet.
- Coverage must be stated as partial. ATS APIs often expose reqs that a
  company's styled career page does not render, which is a real free advantage.
  But roles posted only to LinkedIn or Wellfound are deliberately out of reach.
  Saying so plainly costs nothing; implying completeness is the one thing that
  actually breaks trust.
- The mockup and the built frontend have already diverged: the mockup shows
  letter monograms, the built UI uses `https://unavatar.io/{domain}` logos
  (Clearbit blocked, DuckDuckGo too low-res). Treat the built code as the
  reference.

## 12. Growth position

The Instagram pattern of "comment and I will DM the link" works because the
link is made artificially scarce. Xlake is the inverse: the link is free,
instant, and points at the official source. The hook is the absence of a gate.
Show a real opportunity with a real deadline and say the link is already
public, no comment and no DM needed. Do not accidentally build a gate.

Monetisation: free official-link search forever. Pro at Rs 99 for velocity —
alerts, saves, instant push. Sponsored verified placement later, employer paid.
Placement-cell product only after demand is proven.

UseAstra (useastra.in) is the nearby competitor — a paid career-preparation OS
at Rs 699 lifetime with DSA, aptitude, interview kits, resume tools and a job
board. Xlake differentiates as free opportunity intelligence, not career prep.

**The category does not exist yet in the user's mind.** People need an
opportunity search engine but do not know to look for one — they search for
"internships" or wait for a WhatsApp forward. That makes this partly a demand
education problem, not only a distribution problem. Reels should demonstrate
the category by showing something the user could not have found on their own — a
research programme, a fellowship deadline, a fully-funded grant — rather than
advertising a search box. Show the thing, not the tool.

## 13. Work order

1. **Commit `engine/` and get CI persisting.** Nothing under `engine/` is
   tracked, which is why CI commits nothing and why the project is unbacked.
   Commit the code, keep generated data out of git, fix the workflow's paths for
   the current layout, then verify cross-day accumulation with two successful
   consecutive runs before trusting any liveness claim.
2. **DONE — partial-read bug fixed and tested.** Still outstanding from this
   step: port the unreachable-versus-genuinely-empty distinction from the
   Desktop engine, and stop truncated reads from demoting tier state.
3. **Fix the `india_remote` classifier.** One row out of 9,385 lands in that
   bucket, so it is effectively broken, and India-remote is core to the declared
   scope. Cheap to fix and it directly unlocks in-scope supply.
4. **Add the record fields** from section 5 — `official_url`,
   `source_provenance`, `last_confirmed_at`, three-value `status`,
   `opportunity_kind`, `liveness_model`, `deadline`, `read_outcome`. Stand up
   S3 archiving in the same pass.
5. **Classify the unknown rows** with a cheap model. This is the supply
   unlock, and it is worth more than any new source.
6. **Add new source families** in the section 8 order, portfolios first.

Wiring the frontend comes after step 3, because that is when an apply link
exists to wire.

**Make CI run the tests.** Four test modules exist and nothing runs them, so
nothing protects the trust rules. Add a CI step, and add tests asserting the
trust invariants directly — in particular that a partial read can never mark a
row closed or not live.

**Housekeeping.** Add a dependency manifest — none exists, so CI installs only
Python and runtime reproducibility is unverified. Mine `oldengine/` for anything
worth keeping and then delete it; it currently only adds confusion. Move the
working store off git.

## 14. Open questions

- JSON-LD `JobPosting` hit rate across our existing companies. Unmeasured, and
  a high rate would remove much of the need for AI page reading.
- Real daily new-supply rate. Unmeasurable until history accumulates.
- Whether YC Work at a Startup is permissible under its robots and terms.
- Whether any CI sweep exists on the remote. Local evidence shows none, but
  only git reflog was available, so this is not conclusive.
- The previous 986-line PRODUCT.md is preserved in git history. It contained
  detail not carried forward — the resume-drop eligibility flow, urgency model,
  cost model, secrets hygiene, registry Phase 0, and programme calendar notes.
  Recover selectively if needed.

## 15. Decision log

Decisions made 2026-08-07 that should not be relitigated without new evidence:

- Audience stays narrow (Indian early-career technical). Supply grows by
  widening opportunity type and geography, and by fixing classification — not by
  widening the person.
- One record type with a `liveness_model` flag, not two pipelines.
- AI spends once per source shape via cached recipes, never per page per day.
  Budget $15/month.
- Highest-value AI spend is backfill-classifying the 8,013 unknown-stage rows
  already collected, not acquiring new sources.
- S3 for permanent raw archive; a single small file for serving. No database
  service, no API layer.
- UI language is observational, never evaluative. No "Verified by Xlake".
- Closing-soon is the default view, not newly-posted.
- LinkedIn, Naukri and Wellfound are never accessed. This is not revisited for
  supply reasons.
