# Research - category doc

Status: IN PROGRESS. Folder: engine/categories/research/.

This doc is the overview and worklist for the Research category. It does NOT store opportunity data - those live in engine/data/lake/opportunities.json.

## What this category is
Structured worldwide research programmes and opportunities for students and early-career candidates with an official page and an application window. This includes summer research programmes, research internships and fellowships such as Mitacs Globalink, DAAD RISE, CERN/DESY Summer Student, Amgen Scholars, Caltech SURF, ETH/EPFL summer fellowships, and RIKEN IPA. REU-style programmes are in scope.

### Included
- Worldwide, structured research programmes or opportunities for students and early-career candidates.
- Summer research programmes, research internships, and research fellowships with an official source page and an application window.
- REU-style programmes and equivalent structured student research calls.

### Excluded
- Email-a-professor opportunities with no programme structure.
- Paid courses.
- Pure taught degrees.

## Evidence rules
- Every programme needs its official source URL and quotable evidence from that official page.
- Dates, eligibility, funding, and status come from the official page; never invent a date.
- A failed, blocked, partial, or off-season read never closes a row.
- Manual verification is evidence-gated: only facts that can be quoted from the official page are recorded.

## Liveness model (window-based, not rolling jobs)
- `opening_soon` - an exact future application window is announced.
- `open` - the programme is currently accepting applications.
- `closed` - a successful official read confirms that the application window has passed; the row is retained as history.
- `non_actionable` - the official page is readable but does not provide an actionable applicant window.
- A failed or blocked read never closes a programme.

## Audience
WORLDWIDE - open to anyone, anywhere. Capture each programme's own eligibility from its official page; never apply an India or other location filter.

## Source worklist
Status values: not-started / collected / verified / blocked.

| Source | Official URL | Status | Notes |
|---|---|---|---|
| Mitacs Globalink Research Internship | https://www.mitacs.ca/our-programs/globalink-research-internship-students/ | verified | Open for summer 2027; deadline 2026-09-16 (1pm PT); evidence-backed, surfaced live; intl undergrads from partner countries |
| DAAD RISE Germany | https://www.daad.de/rise/en/ | not-started | Window ~mid-Oct to late-Nov; off-season now; undergrads at North American/UK/Irish universities |
| CERN Summer Student Programme | https://home.cern/summer-student-programme/ | not-started | All nationalities; window ~Nov to end Jan |
| DESY Summer Student Programme | https://summerstudents.desy.de/ | not-started | Opens early Dec, deadline 31 Jan; intl |
| ETH Zurich Student Summer Research Fellowship | https://www.inf.ethz.ch/studies/summer-research-fellowship.html | not-started | Open to all students worldwide except ETH; opens ~early Nov |
| Summer@EPFL | https://summer.epfl.ch/ | not-started | International students; CS & Communication Sciences |
| Amgen Scholars Program | https://amgenscholars.com/ | not-started | Regional incl. Asia (worldwide); window ~Nov to Feb |
| Caltech Summer Undergraduate Research Fellowships (SURF) | https://sfp.caltech.edu/undergraduate-research/programs/surf | not-started | Intl eligible on Caltech campus; JPL US citizens/PR only |
| RIKEN International Program Associate (IPA) | https://www.riken.jp/en/careers/programs/ipa/index.html | not-started | PhD research at RIKEN |

## Current programme state

| Programme | Category | Status | Deadline |
|---|---|---|---|
| Mitacs Globalink Research Internship | research | open | 2026-09-16 |

One row is live in the lake: Mitacs Globalink. There are 9 seeds total; most are off-season and awaiting their application windows.

## Manual verification
Evidence-backed records are stored in `data/operations/research_programme_verifications.json` and surfaced via `python3 -m categories.research.research --apply-verifications`.

## Collector
`python3 -m categories.research.research` runs the live collector. It is built on the shared programme engine `categories/programme_core.py`. It is NOT yet wired into the daily sweep - research collection is in progress.

## Next actions
- Collect and verify the 8 seeded programmes when their windows open.
- Confirm each official URL is still live.
- Consider wiring the collector into the daily sweep once stable.

## Direction (updated 2026-08-21)
New worldwide Research category built on shared `programme_core`; 9 verified seeds, with Mitacs Globalink surfaced as the first evidence-backed live programme.
