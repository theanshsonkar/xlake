# Open Source - category doc

Status: LIVE and actively collected. Folder: engine/categories/open_source/.

This doc is the overview and worklist for the Open Source category. It does NOT store opportunity data - those live in engine/data/lake/opportunities.json. It tracks what this category is and which sources we cover.

## What this category is
Official, org-run open-source contribution programmes plus good-first-issue contribution opportunities from active open-source projects. The category has a calendar-programme layer and a listing good-first-issues layer.

### Included
- Official, org-run open-source programmes with a real application/participation window.
- Programmes with an official source page and verifiable dates.
- Good-first-issue opportunities from active repositories, with the issue URL as the official source.

### Excluded
- Generic 'contribute to our repo' invites with no programme structure in the programme layer.
- Paid courses/bootcamps dressed up as open source.
- Anything without an official source.

## Evidence rules
- Every programme needs its official source URL.
- Dates, eligibility, and status come from the official page (verbatim evidence), never invented.
- Application links stay on the official/organizer origin.
- Programme verification is evidence-gated through `engine/data/operations/programme_verifications.json` (4 records). Only facts quoted from the official page are recorded; a claimed `status`, `opening_date`, or `deadline` requires an official quote and URL. A failed or unclear read never closes a row.
- Manual human-in-the-loop verification runs about twice a month until an AI API key is configured.

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
Status values: not-started / collected / verified / blocked. This universe was researched and approved on 2026-08-17: 41 official programme sources total (20 collected, 15 verified, 6 blocked, 0 not-started as of 2026-08-25). Add new sources only with a verified official URL.

| Source | Official URL | Status | Notes |
|---|---|---|---|
| MLH Fellowship Open Source Track | https://fellowship.mlh.io/programs/open-source | verified | live now (rolling); evidence captured |
| Google Summer of Code | https://summerofcode.withgoogle.com/ | collected | existing seed; read OK 2026-08-17; off-season, will surface at next window |
| Outreachy | https://www.outreachy.org/ | collected | opening_soon after manual verification; read OK 2026-08-17 |
| LFX Mentorship | https://lfx.linuxfoundation.org/tools/mentorship | collected | existing seed; read OK 2026-08-25 but marketing page has no dated application window (portal: mentorship.lfx.dev) - pending window |
| RISC-V International Mentorship | https://riscv.org/community/mentorship/ | collected | existing seed; read OK 2026-08-17; off-season, will surface at next window |
| KDE Season of KDE | https://season.kde.org/ | verified | closed; SoK 2026 applications deadline Jan 14 2026, work ended Mar 20; next season undated; evidence captured 2026-08-25 |
| Summer of Bitcoin | https://www.summerofbitcoin.org/ | collected | University students; paid; ~Feb applications; read OK 2026-08-17; off-season, will surface at next window |
| Julia Summer of Code | https://julialang.org/jsoc/ | collected | Open to all; GSoC-aligned; read OK 2026-08-25 but page has no dated window (GSoC summer over) - pending window |
| Open Source Promotion Plan (OSPP) | https://summer-ospp.ac.cn/ | collected | Open to students worldwide (verified); paid; read OK 2026-08-17; off-season, will surface at next window |
| Linux Kernel Mentorship | https://wiki.linuxfoundation.org/lkmp | blocked | Remote; runs on the LFX platform; blocked: HTTP 403 bot-block; recheck / find alt URL |
| Hyperledger Mentorship | https://wiki.hyperledger.org/display/INTERN/ | collected | Runs on the LFX platform; read OK 2026-08-17; off-season, will surface at next window |
| Open Mainframe Project Mentorship | https://www.openmainframeproject.org/projects/mentorship-program | blocked | Runs on the LFX platform; blocked: HTTP 404; verify correct official URL |
| Hacktoberfest | https://hacktoberfest.com/ | collected | opening_soon; recategorized to community_event; read OK 2026-08-17 |
| 24 Pull Requests | https://24pullrequests.com/ | verified | opening_soon; annual Dec 1-24 challenge, "See you on December 1st, 2026"; beginner-friendly/global; evidence captured 2026-08-25 |
| Igalia Coding Experience | https://www.igalia.com/coding-experience/ | collected | closed; 2026 selection process closed |
| X.Org EVoC | https://www.x.org/wiki/XorgEVoC/ | verified | closed; official wiki: "being sunset and no application will be accepted" (edited Aug 24 2026); evidence captured 2026-08-25 |
| Processing Foundation Fellowship | https://processingfoundation.org/fellowships/ | verified | closed; "no Processing Foundation Fellowship in 2026" (2027 info ~Oct 2026); evidence captured 2026-08-25 |
| FOSSASIA Codeheat | https://codeheat.org/ | collected | Cycles; verify current edition at collection; read OK 2026-08-17; off-season, will surface at next window |
| Code for GovTech (C4GT) | https://www.codeforgovtech.in/ | collected | unverified and deferred: JS-only site; needs its JSON API or a JS-capable fetch; not closed |
| GirlScript Summer of Code (GSSoC) | https://gssoc.girlscript.org/ | verified | live now (open); evidence captured |
| Social Summer of Code (SSoC) | https://socialsummerofcode.com/ | collected | India; summer; read OK 2026-08-17; off-season, will surface at next window |
| Social Winter of Code (SWOC) | https://swoc.in/ | verified | live now (open); Season 7 registrations 2026-08-20 to 2026-12-31 (coding Jan 1-Mar 30 2027); free/certificate; anyone worldwide; evidence captured 2026-08-25 |
| FOSSEE Summer Fellowship | https://fossee.in/ | collected | IIT Bombay; India; read OK 2026-08-17; off-season, will surface at next window |
| Kharagpur Winter of Code (KWoC) | https://kwoc.kossiitkgp.org/ | collected | IIT Kharagpur; beginner; 2026-08-25 recheck returned empty page (not a closure) - reconfirm |
| DevScript Winter of Code | https://devscript.tech/woc/ | blocked | India; winter; blocked: domain not resolving; likely offline between editions |
| Delta Winter of Code (DWoC) | https://dwoc.io/ | collected | NIT Trichy; read OK 2026-08-17; off-season, will surface at next window |
| FOSS Overflow | https://fossoverflow.dev/ | collected | IIT Bhilai; read OK 2026-08-17; off-season, will surface at next window |
| JGEC Winter of Code | https://jwoc.tech/ | blocked | India; winter; blocked: domain not resolving; likely offline between editions |
| NJACK Winter of Code | https://njackwinterofcode.github.io/ | collected | IIT Patna; read OK 2026-08-17; off-season, will surface at next window |
| OpenCode IIITA | https://opencodeiiita.github.io/ | blocked | IIIT Allahabad; blocked: HTTP 404; verify official URL |
| Cross Winter of Code | https://crosswoc.ieeedtu.in/ | blocked | IEEE DTU; blocked: SSL certificate mismatch; recheck |
| Summer of Nix | https://summer.nixos.org/ | collected | NixOS Foundation; paid (EUR 1875 participant); global; read OK 2026-08-25 but README has no dated 2026 application window - pending window |
| Ethereum Protocol Fellowship | https://ps.ethereum.foundation/fellowship | verified | closed (next cycle ~Apr-May); permissionless/global; monthly stipend for selected; evidence captured 2026-08-25 |
| Sovereign Tech Fellowship | https://www.sovereign.tech/programs/fellowship | verified | closed; 2026 window ended Apr 6; EUR 64k-82k/yr or freelance; maintainers/community mgrs/tech writers; evidence captured 2026-08-25 |
| Sequoia Open Source Fellowship | https://www.sequoiacap.com/oss | verified | Sequoia Capital; global, location-agnostic; rolling, open now; evidence captured |
| Djangonaut Space | https://djangonaut.space/ | verified | live now (open); Session 7 apps 2026-08-14 to 2026-09-06 (starts Oct 12); free 8-week group mentoring, global; evidence captured 2026-08-25 |
| Swift Mentorship Program | https://www.swift.org/mentorship/ | verified | closed; 2026 mentee deadline Jun 15, cohort Jul 6-Sep 11; open to everyone 18+; unpaid; evidence captured 2026-08-25 |
| Kubernetes Release Shadow Program | https://github.com/kubernetes/sig-release/blob/master/release-team/shadows.md | collected | Kubernetes/CNCF; per-release-cycle sign-up form; global; read OK 2026-08-25 but no dated window on page - pending per-cycle form |
| Open Source Research Experience | https://ucsc-ospo.github.io/osre/ | verified | closed; OSRE 2026 proposal deadline Mar 31 passed; undergrad/grad worldwide; GSoC/sponsor stipend ($7,500); evidence captured 2026-08-25 |
| sktime Mentorship Program | https://www.sktime.net/docs/get-involved/mentoring/ | verified | live now (rolling); "applications on a rolling basis"; informal 2-3mo, unpaid; global; evidence captured 2026-08-25 |
| European Summer of Code | https://www.esoc.dev/ | verified | closed; 2026 Batch 2 apps closed Apr 30; stipends for newcomers worldwide; evidence captured 2026-08-25 |

## Excluded sources (do not re-add without new evidence)
- Google Season of Docs - officially concluded in 2026 (Google announcement).
- Google Summer of Earth Engine - no edition since ~2021; dormant.
- BOSS / Bountiful Open Source Summer (Coding Blocks) - no edition since 2020; dormant.
- FSF Internship - unpaid; applications closed/volatile.
- OSS World Challenge (Korea) - niche competition; weak fit for this audience.
- Millennium Fellowship - leadership program, not open source.
- Rails Girls Summer of Code - defunct.

## Current programme state
- Official programme sources tracked: 41 total.
- Worklist status: 20 collected, 15 verified, 6 blocked, 0 not-started (as of 2026-08-25).
- ~19 programme rows currently in the lake; 9 live open-source programme rows (up from 6).
- Current live statuses: MLH Fellowship - `rolling`; GSSoC - `open`; Sequoia OSS Fellowship - `open` (rolling); sktime Mentorship - `rolling`; Outreachy - `opening_soon`; Hacktoberfest - `opening_soon` (recategorized `community_event`); Djangonaut Space - `open` (Aug 14-Sep 6); Social Winter of Code - `open` (Aug 20-Dec 31); 24 Pull Requests - `opening_soon` (Dec 1). Closed/retained: Igalia, X.Org EVoC, Ethereum Protocol Fellowship, Sovereign Tech Fellowship, Swift Mentorship, OSRE, European Summer of Code, Processing Foundation Fellowship, Season of KDE.
- C4GT remains unverified, not closed, and deferred pending its JSON API or a JS-capable fetch.
- Last worked: 2026-08-21 - added 10 verified worldwide programmes (31->41) and a rolling-open evidence record for Sequoia OSS Fellowship.
- Last worked: 2026-08-25 - read the 9 not-started sources + a prioritized batch of collected sources; applied 12 manual verification records. Live open-source rows 6 -> 9 (Djangonaut Space open, Social Winter of Code open, 24 Pull Requests opening_soon newly live; sktime reconfirmed rolling). Recorded 8 `closed` with quoted evidence (Ethereum PF, Sovereign Tech, Swift, OSRE, ESoC, X.Org EVoC, Processing Foundation, Season of KDE). Pending - successful read but no dated window, or failed read (not closures): Summer of Nix, Kubernetes Release Shadow, Julia SoC, LFX Mentorship, KWoC.

## Collection notes (2026-08-17)
- August is off-season for most programmes, so MLH, GSSoC, and the manually verified current statuses surface now. The rest are tracked and will surface automatically as their application windows open (Winter-of-Code ~Dec, GSoC apps ~spring, Summer of Bitcoin ~Feb).
- The 6 blocked sources need a recheck: Linux Kernel and Open Mainframe need a working URL; the WoC domains (DevScript, JGEC, Cross, OpenCode IIITA) are likely offline until their season - recheck Nov-Dec.
- Acceptance floor of ~20+ live rows is not reachable in August with programmes alone; it will build up across the season.

## Next actions
1. Reconfirm and verify already-collected programme sources with official quotes and URLs.
2. Clear or recheck the 6 blocked sources when their official pages or replacement URLs are available.
3. Continue applying evidence-gated status, opening-date, and deadline facts; there are 9 not-started sources.

## Direction (updated 2026-08-18)
This category has two layers:
- Programmes (calendar): the 41 official sources in the worklist above. Engine tracks liveness; manual human-in-the-loop verification reads each prose page about twice a month to extract real dates, eligibility, and funding with a verbatim quote as evidence. Manual verification continues until an AI API key is configured.
- Contributions (listing): good-first-issue style ongoing opportunities from curated, active open-source projects, collected via a category-owned GitHub collector (implemented), keyed by issue URL. This is the main source of daily volume and is engine-only.

AI verification findings 2026-08-18:
- Outreachy: December 2026 cohort active - intern applications early-to-mid August, internships Dec 2026-Mar 2027; paid $7,000; remote. The deterministic parser missed this; manual evidence makes it `opening_soon`.
- Igalia Coding Experience: 2026 selection process CLOSED (annual, not rolling). Correctly not surfaced.
- Hacktoberfest 2026: pivoted from pull-request challenge to local 'Fests' (events) about open-source AI; `opening_soon` and recategorized to `community_event`.
- Code for GovTech (C4GT): official site is a JavaScript-only app; raw HTML is empty. Needs a JS-capable fetch or the app API; it remains unverified and is not closed.

## Contributions collector (built 2026-08-18)

Good-first-issue contribution opportunities are collected by
`categories/open_source/contributions.py` from ~45 curated active repositories,
plus token-gated GitHub Search discovery. The collector reads `GITHUB_TOKEN`
from the environment; in CI that comes from a `GH_PAT` secret or the built-in
token. Without a token, only curated repositories are collected.

Discovered repositories must meet these quality floors in the search query:
- stars >= 500;
- good-first-issues >= 3;
- pushed within the previous 60 days;
- an updated-recency qualifier, plus public and not archived.

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
no arguments retains the existing network behavior. Quality filters drop issues
stale >120 days or with >30 comments; search discovery is restricted to
recently-updated issues; surfaced rows are freshest-first.

Observed sample run (2026-08-18; not a fixed guarantee): 116 repositories were
found through search (45 curated plus 116 discovered), 909 contribution rows
were collected total (up from 101), with 76 `is_recently_active` rows and 55
`is_new_this_month` rows. The final lake then had 18,738 rows total, including
909 contribution rows and the unchanged five programme rows. Contribution
provenance was 101 curated and 808 search rows. The language distribution was
C 50, C# 76, C++ 121, Go 69, Java 60, JavaScript 63, Kotlin 81, PHP 63,
Python 116, Ruby 71, Rust 55, and TypeScript 84. These are observed run
snapshots, not fixed guarantees.

### Contribution reconfirmation window

Contribution rows use a seven-day (`RECONFIRM_WINDOW_DAYS = 7`) reconfirmation
window. A row seen in the newly collected set is live, gets
`needs_confirmation: false`, clears `liveness_reason`, and updates `last_seen`.
New rows initialize the same fields. An unseen row whose repository was not
successfully fetched and which is older than seven whole days is retired to
`needs-confirmation`: `is_live: false`, `needs_confirmation: true`, and
`liveness_reason: "not_reconfirmed"`. This is not closure, does not set
`went_dead_at`, and remains retained in the lake as history/needs-confirmation.
If an absent row's repository was successfully fetched, its absence is a
confirmed closure and it becomes `is_live: false` with `went_dead_at` set. Rows
within the window remain presumed live, and a later rediscovery self-heals the
row. Missing or unparseable `last_seen` values are not decayed.

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
- **Djangonaut Space** (`djangonaut-space`) - `open`, opening 2026-08-14, deadline 2026-09-06; official sessions page shows the Session 7 window with an Apply button; free 8-week group mentoring, global.
- **Social Winter of Code** (`social-winter-of-code`) - `open`, 2026-08-20 to 2026-12-31; "Registrations open 20 August 2026 and close 31 December 2026"; free, open to anyone worldwide.
- **24 Pull Requests** (`24-pull-requests`) - `opening_soon`, opening 2026-12-01; "See you on December 1st, 2026"; annual Dec 1-24 contribution challenge.
- **sktime Mentorship Program** (`sktime-mentorship`) - `rolling`; "We accept applications on a rolling basis"; informal 2-3 month unpaid mentorship, global.
- **Ethereum Protocol Fellowship** (`ethereum-protocol-fellowship`) - `closed`; "Applications open annually, typically in April-May"; permissionless, monthly stipend for selected.
- **Sovereign Tech Fellowship** (`sovereign-tech-fellowship`) - `closed`; "The application period ended on April 6, 2026"; EUR 64k-82k/yr or freelance.
- **Swift Mentorship Program** (`swift-mentorship`) - `closed`; 2026 mentee deadline June 15, cohort Jul 6-Sep 11; open to everyone 18+.
- **Open Source Research Experience** (`open-source-research-experience`) - `closed`; "The FINAL proposal deadline is March 31"; undergrad/grad worldwide, GSoC/sponsor stipend.
- **European Summer of Code** (`european-summer-of-code`) - `closed`; Batch 2 applications closed April 30, 2026; stipends for newcomers worldwide.
- **X.Org EVoC** (`xorg-evoc`) - `closed`; "being sunset and no application will be accepted" (wiki edited Aug 24, 2026).
- **Processing Foundation Fellowship** (`processing-foundation-fellowship`) - `closed`; "There will be no Processing Foundation Fellowship in 2026" (2027 info ~Oct 2026).
- **KDE Season of KDE** (`kde-season-of-kde`) - `closed`; SoK 2026 applications deadline 2026-01-14, work ended 2026-03-20.

Code for GovTech (C4GT) remains unverified and still needs a JS-capable fetch (or the app API); its empty raw HTML is not evidence of closure.

Last worked: 2026-08-18 - added evidence-gated manual verification and applied the Outreachy, Igalia Coding Experience, and Hacktoberfest records.

Last worked: 2026-08-25 - read the 9 not-started sources and a prioritized batch of collected sources; authored and applied 12 evidence-gated verification records. Live open-source programme rows grew 6 -> 9 (Djangonaut Space, Social Winter of Code, 24 Pull Requests newly live; sktime reconfirmed rolling). Eight programmes recorded `closed` with quoted evidence. Pending (successful read but no dated application window, or failed read - not closures): Summer of Nix, Kubernetes Release Shadow, Julia Summer of Code, LFX Mentorship, KWoC.
