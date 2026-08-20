# Open Source - category doc

Status: in progress (beta build). Folder: engine/categories/open_source/.

This doc is the overview and worklist for the Open Source category. It does NOT store opportunity data - those live in engine/data/lake/opportunities.json. It tracks what this category is and which sources we cover.

## What this category is
Official, org-run open-source contribution programmes: structured mentorship/contribution programmes run by open-source orgs and foundations (e.g. Google Summer of Code, Outreachy, MLH Fellowship, LFX Mentorship, Season of Docs, and org-run programmes).

### Included
- Official, org-run open-source programmes with a real application/participation window.
- Programmes with an official source page and verifiable dates.

### Excluded
- Generic 'contribute to our repo' invites with no programme structure.
- Paid courses/bootcamps dressed up as open source.
- Anything without an official source.

## Evidence rules
- Every programme needs its official source URL.
- Dates, eligibility, and status come from the official page (verbatim evidence), never invented.
- Application links stay on the official/organizer origin.

## Liveness model (window-based, not rolling jobs)
- opening_soon - window announced with a future open date.
- open - currently accepting applications.
- rolling - continuous, same-origin application.
- closes DATE - open with a known deadline.
- A failed/blocked read never closes a programme.

## Acceptance gate (when Open Source is beta-live)
- All listed sources evidence-backed with official URLs.
- Liveness status computed correctly for each.
- Floor: about 20+ live/verified programme rows in the lake so the category filter is not thin. (Adjustable.)

## Source worklist
Status values: not-started / collected / verified / blocked. This universe was researched and approved on 2026-08-17: 31 sources total (6 collected seeds + 25 to collect). Add new sources only with a verified official URL.

| Source | Official URL | Status | Notes |
|---|---|---|---|
| MLH Fellowship Open Source Track | https://fellowship.mlh.io/programs/open-source | verified | live now (rolling); evidence captured |
| Google Summer of Code | https://summerofcode.withgoogle.com/ | collected | existing seed; read OK 2026-08-17; off-season, will surface at next window |
| Outreachy | https://www.outreachy.org/ | collected | existing seed; read OK 2026-08-17; off-season, will surface at next window |
| LFX Mentorship | https://lfx.linuxfoundation.org/tools/mentorship | collected | existing seed; read OK 2026-08-17; off-season, will surface at next window |
| RISC-V International Mentorship | https://riscv.org/community/mentorship/ | collected | existing seed; read OK 2026-08-17; off-season, will surface at next window |
| KDE Season of KDE | https://season.kde.org/ | collected | existing seed; read OK 2026-08-17; off-season, will surface at next window |
| Summer of Bitcoin | https://www.summerofbitcoin.org/ | collected | University students; paid; ~Feb applications; read OK 2026-08-17; off-season, will surface at next window |
| Julia Summer of Code | https://julialang.org/jsoc/ | collected | Open to all; aligns with GSoC; read OK 2026-08-17; off-season, will surface at next window |
| Open Source Promotion Plan (OSPP) | https://summer-ospp.ac.cn/ | collected | Open to students worldwide (verified); paid; read OK 2026-08-17; off-season, will surface at next window |
| Linux Kernel Mentorship | https://wiki.linuxfoundation.org/lkmp | blocked | Remote; runs on the LFX platform; blocked: HTTP 403 bot-block; recheck / find alt URL |
| Hyperledger Mentorship | https://wiki.hyperledger.org/display/INTERN/ | collected | Runs on the LFX platform; read OK 2026-08-17; off-season, will surface at next window |
| Open Mainframe Project Mentorship | https://www.openmainframeproject.org/projects/mentorship-program | blocked | Runs on the LFX platform; blocked: HTTP 404; verify correct official URL |
| Hacktoberfest | https://hacktoberfest.com/ | collected | October; no application; beginner-friendly; read OK 2026-08-17; off-season, will surface at next window |
| 24 Pull Requests | https://24pullrequests.com/ | collected | December; beginner-friendly; read OK 2026-08-17; off-season, will surface at next window |
| Igalia Coding Experience | https://www.igalia.com/coding-experience/ | collected | Paid; rolling applications; read OK 2026-08-17; off-season, will surface at next window |
| X.Org EVoC | https://www.x.org/wiki/XorgEVoC/ | collected | Year-round; open to all; read OK 2026-08-17; off-season, will surface at next window |
| Processing Foundation Fellowship | https://processingfoundation.org/fellowships/ | collected | Annual; read OK 2026-08-17; off-season, will surface at next window |
| FOSSASIA Codeheat | https://codeheat.org/ | collected | Cycles; verify current edition at collection; read OK 2026-08-17; off-season, will surface at next window |
| Code for GovTech (C4GT) | https://www.codeforgovtech.in/ | collected | India; stipend; digital public goods; read OK 2026-08-17; off-season, will surface at next window |
| GirlScript Summer of Code (GSSoC) | https://gssoc.girlscript.org/ | verified | live now (open); evidence captured |
| Social Summer of Code (SSoC) | https://socialsummerofcode.com/ | collected | India; summer; read OK 2026-08-17; off-season, will surface at next window |
| Social Winter of Code (SWOC) | https://swoc.in/ | collected | India; winter; read OK 2026-08-17; off-season, will surface at next window |
| FOSSEE Summer Fellowship | https://fossee.in/ | collected | IIT Bombay; India; read OK 2026-08-17; off-season, will surface at next window |
| Kharagpur Winter of Code (KWoC) | https://kwoc.kossiitkgp.org/ | collected | IIT Kharagpur; beginner; read OK 2026-08-17; off-season, will surface at next window |
| DevScript Winter of Code | https://devscript.tech/woc/ | blocked | India; winter; blocked: domain not resolving; likely offline between editions |
| Delta Winter of Code (DWoC) | https://dwoc.io/ | collected | NIT Trichy; read OK 2026-08-17; off-season, will surface at next window |
| FOSS Overflow | https://fossoverflow.dev/ | collected | IIT Bhilai; read OK 2026-08-17; off-season, will surface at next window |
| JGEC Winter of Code | https://jwoc.tech/ | blocked | India; winter; blocked: domain not resolving; likely offline between editions |
| NJACK Winter of Code | https://njackwinterofcode.github.io/ | collected | IIT Patna; read OK 2026-08-17; off-season, will surface at next window |
| OpenCode IIITA | https://opencodeiiita.github.io/ | blocked | IIIT Allahabad; blocked: HTTP 404; verify official URL |
| Cross Winter of Code | https://crosswoc.ieeedtu.in/ | blocked | IEEE DTU; blocked: SSL certificate mismatch; recheck |

## Excluded sources (do not re-add without new evidence)
- Google Season of Docs - officially concluded in 2026 (Google announcement).
- Google Summer of Earth Engine - no edition since ~2021; dormant.
- BOSS / Bountiful Open Source Summer (Coding Blocks) - no edition since 2020; dormant.
- FSF Internship - unpaid; applications closed/volatile.
- OSS World Challenge (Korea) - niche competition; weak fit for this audience.
- Millennium Fellowship - leadership program, not open source.
- Rails Girls Summer of Code - defunct.

## Current state
- Sources registered: 31 total.
- Live rows in lake now: 2 (MLH Fellowship - rolling; GSSoC - open).
- Read & confirmed but off-season (no current window): 23.
- Blocked/failed fetch: 6 (see Notes; mostly WoC sites that go offline between editions plus 2 URL/robots issues).
- Last worked: 2026-08-17 - first full collection run of the 31-source universe.

## Collection notes (2026-08-17)
- August is off-season for most programmes, so only rolling/open ones surface now (MLH, GSSoC). The rest are tracked and will surface automatically as their application windows open (Winter-of-Code ~Dec, GSoC apps ~spring, Summer of Bitcoin ~Feb).
- The 6 blocked sources need a recheck: Linux Kernel and Open Mainframe need a working URL; the WoC domains (DevScript, JGEC, Cross, OpenCode IIITA) are likely offline until their season - recheck Nov-Dec.
- Acceptance floor of ~20+ live rows is not reachable in August with programmes alone; it will build up across the season.

## Next actions
1. Collect the not-started sources one at a time from their official pages, with evidence.
2. Update each row's status here (collected/verified/blocked) as you go.
3. Continue until the ~20+ live/verified floor is met.

## Direction (updated 2026-08-18)
This category has two layers:
- Programmes (calendar): the 31 sources in the worklist above. Engine tracks liveness; AI reads each prose page ~2x/month to extract real dates/eligibility/funding with a verbatim quote as evidence. Plan A (small): a minimal parser tweak so genuinely-rolling programmes (with an off-site Apply link) can surface.
- Contributions (listing): good-first-issue style ongoing opportunities from curated, active open-source projects, collected via a category-owned GitHub collector (implemented), keyed by issue URL. This is the main source of daily volume and is engine-only (structured data; needs a GitHub token for rate limits).

AI verification findings 2026-08-18 (read by assistant):
- Outreachy: December 2026 cohort active - intern applications early-to-mid August, internships Dec 2026-Mar 2027; paid $7,000; remote. The deterministic parser missed this; should surface via AI reading.
- Igalia Coding Experience: 2026 selection process CLOSED (annual, not rolling). Correctly not surfaced.
- Hacktoberfest 2026: pivoted from pull-request challenge to local 'Fests' (events) about open-source AI; 'applications open soon'. Recategorize/verify before surfacing as a contribution programme.
- Code for GovTech (C4GT): official site is a JavaScript-only app; raw HTML is empty. Needs a JS-capable fetch or the app API - mark 'needs JS fetch'.

## Contributions collector (built 2026-08-18)

Good-first-issue contribution opportunities are collected by
`categories/open_source/contributions.py` from a curated list of 45 active
repositories. Collection is unauthenticated by default and processes the
curated list only. If `GITHUB_TOKEN` is set, it also performs authenticated
GitHub repository Search API discovery, capped at 10 repositories per language
and 120 repositories overall. Search discovery is token-gated and never runs
without a token.

Discovered repositories must meet these quality floors in the search query:
- at least 500 stars;
- more than 2 good-first issues (3 or more);
- pushed within the previous 60 days;
- public and not archived.

The search covers Python, JavaScript, TypeScript, Java, Go, Rust, C++, C, Ruby,
PHP, C#, and Kotlin. Search requests are paced at about two seconds apart for
the authenticated Search API. A 403/429 or any other search-read error returns
the results collected so far as a partial read; it never makes a repository
look closed and does not abort curated collection.

Rows are keyed by issue URL, with pull requests and already-assigned issues
excluded. Each row carries `discovery_source` (`curated` or `search`) and
`repo_stars` (the discovered repository star count, or null for curated rows).
Freshness is available through `posted_on`, `created_age_days`, and
`activity_age_days`. `is_recently_active` is true when the issue was updated
within the last 3 days (inclusive), while `is_new_this_month` is true when the
issue was created within the last 30 days (inclusive). Missing or unparseable
timestamps produce a null age and a false freshness flag. Each row also
carries its repository `language`, plus `difficulty` and `difficulty_signal`:
labels such as `good first issue` map to `beginner`, labels such as `help
wanted` or `medium` map to `intermediate`, and unmatched labels default to
`beginner`.

The collector's view-only list CLI reads the canonical lake without network
access. For example:

```bash
python3 -m categories.open_source.contributions --list \
  --language Python --difficulty beginner --recently-active --new-this-month
```

It prints a count and up to five title/official-URL summaries. Collection with
no arguments retains the existing network behavior. Quality filters: drop
issues stale >120d or with >30 comments; search discovery restricted to
recently-updated issues; surfaced freshest-first. The 2026-08-18 live run
found 116 repositories through search (45 curated plus 116 discovered),
collected 909 contribution rows total (up from 101), and produced 76
`is_recently_active` rows and 55 `is_new_this_month` rows. The final lake has
18,738 rows total, including 909 contribution rows and the unchanged five
programme rows. Contribution provenance was 101 curated and 808 search rows.
The language distribution was C 50, C# 76, C++ 121, Go 69, Java 60,
JavaScript 63, Kotlin 81, PHP 63, Python 116, Ruby 71, Rust 55, and
TypeScript 84.

### Contribution reconfirmation window

Contribution rows use a seven-day (`RECONFIRM_WINDOW_DAYS = 7`) reconfirmation
window. A row seen in the newly collected set is live, gets
`needs_confirmation: false`, clears `liveness_reason`, and updates `last_seen`.
New rows initialize the same fields. If an absent row's repository was
successfully fetched, its absence is a confirmed closure: it becomes
`is_live: false` with `went_dead_at` set. If its repository was not fetched,
an absent row older than seven whole days becomes `is_live: false` with
`needs_confirmation: true` and `liveness_reason: "not_reconfirmed"`; this is
not closure, does not set `went_dead_at`, and remains retained in the lake as
history/needs-confirmation. Rows within the window remain presumed live, and a
later rediscovery self-heals the row. Missing or unparseable `last_seen` values
are not decayed.

Last worked: 2026-08-18 - added token-gated search discovery, quality floors,
provenance fields, rate-limit-safe partial reads, live collection validation,
offline tests, and the seven-day contribution reconfirmation window. The
current lake check found 909 contribution rows, all with the latest
`last_seen` timestamp and none needing confirmation, so applying this policy
now would change no liveness outcomes.


## Manual verification (2026-08-18)

Manual programme facts are stored in `engine/data/operations/programme_verifications.json` and applied to the canonical lake by `load_verifications`, `validate_verification`, and `apply_verifications` in `categories/open_source/programmes.py`. Run `python3 -m categories.open_source.programmes --apply-verifications` from `engine/` to apply the records without a network fetch. Every asserted `programme_status`, `opening_date`, or `deadline` is rejected unless its official evidence contains a non-empty quote and URL (opening dates may use the `opening_date` or `status` evidence key). Manual facts take precedence over deterministic rows and are retained with `manually_verified`, verifier, timestamp, and merged evidence fields.

Verified programmes:
- **Outreachy** (`outreachy`) - `opening_soon`, opening 2026-08-24, deadline 2026-08-31; schedule and applicant-page quotes confirm the window, stipend, and eligibility.
- **Igalia Coding Experience** (`igalia-coding-experience`) - `closed`; the official page says “2026 Selection Process is closed.”
- **Hacktoberfest** (`hacktoberfest`) - `opening_soon`, recategorized as `community_event`; the official page says host applications open soon and describes local/online open-source AI Fests.

Code for GovTech (C4GT) remains unverified and still needs a JS-capable fetch (or the app API); its empty raw HTML is not evidence of closure.

Last worked: 2026-08-18 - added evidence-gated manual verification and applied the Outreachy, Igalia Coding Experience, and Hacktoberfest records.
