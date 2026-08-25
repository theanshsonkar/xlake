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
Status values: not-started / collected / verified+live / verified+closed / pending / blocked.

| Source | Official URL | Status | Notes |
|---|---|---|---|
| Mitacs Globalink Research Internship | https://www.mitacs.ca/our-programs/globalink-research-internship-students/ | verified+live | Open for summer 2027; deadline 2026-09-16 (1pm PT); evidence-backed, surfaced live; intl undergrads from partner countries |
| DAAD RISE Germany | https://www.daad.de/rise/en/ | verified+live | Opening soon; application window 2026-10-15 to 2026-11-30; undergrads at North American/UK/Irish universities |
| CERN Summer Student Programme | https://home.cern/summer-student-programme/ | verified+live | Open; all nationalities; applications due no later than end of January |
| DESY Summer Student Programme | https://summerstudents.desy.de/ | verified+closed | Recorded, not live; 2026 cycle runs 21 July–10 September 2026; international |
| ETH Zurich Student Summer Research Fellowship | https://www.inf.ethz.ch/studies/summer-research-fellowship.html | pending | Official programme and eligibility page found, but no application window/deadline; revisit when applications open |
| Summer@EPFL | https://summer.epfl.ch/ | verified+live | Opening soon; deadline on the Sunday closest to 1 December; international students; CS & Communication Sciences |
| Amgen Scholars Program | https://amgenscholars.com/ | verified+live | Opening soon; Summer 2027 applications available for Australia and coming November 1 for other regions; regional programmes worldwide |
| Caltech Summer Undergraduate Research Fellowships (SURF) | https://sfp.caltech.edu/undergraduate-research/programs/surf | verified+live | Opening soon; SURF 2027 application opens November 1 and is due March 1; visiting students eligible on Caltech campus |
| RIKEN International Program Associate (IPA) | https://www.riken.jp/en/careers/programs/ipa/index.html | verified+live | Opening soon; calls issued in April and September; PhD research at RIKEN |
| NSF Research Experiences for Undergraduates (REU) | https://www.nsf.gov/funding/initiatives/reu | verified+live | Open; undergraduates apply directly to REU Sites; stipends and possible housing, meals, and travel assistance |

## Current programme state

| Programme | Category | Status | Deadline |
|---|---|---|---|
| Mitacs Globalink Research Internship | research | open | 2026-09-16 |
| CERN Summer Student Programme | research | open | End of January (specific annual deadline on official site) |
| DAAD RISE Germany | research | opening_soon | 2026-11-30 |
| Summer@EPFL Research Fellowship | research | opening_soon | Sunday closest to 2026-12-01 |
| Amgen Scholars Program | research | opening_soon | Regional deadlines; other regions open November 1 |
| RIKEN International Program Associate (IPA) | research | opening_soon | Calls in April and September |
| Caltech Summer Undergraduate Research Fellowships (SURF) | research | opening_soon | 2027-03-01 |
| NSF Research Experiences for Undergraduates (REU) | research | open | Site-specific |
| DESY Summer Student Programme | research | closed | 2026 cycle in session: 2026-07-21 to 2026-09-10 |
| ETH Zurich Student Summer Research Fellowship | research | pending | Not stated |

Eight rows are live in the lake: Mitacs, CERN, DAAD RISE Germany, Summer@EPFL, Amgen Scholars, RIKEN IPA, Caltech SURF, and NSF REU. One recorded row is not live: DESY (2026 cycle in session). One programme is pending: ETH Zurich SSRF. There are 10 seeds total.

## Manual verification
Evidence-backed records are stored in `data/operations/research_programme_verifications.json` and surfaced via `python3 -m categories.research.research --apply-verifications`.

## Collector
`python3 -m categories.research.research` runs the live collector. It is built on the shared programme engine `categories/programme_core.py`. It is NOT yet wired into the daily sweep - research collection is in progress.

## Next actions
- Revisit ETH Zurich Student Summer Research Fellowship when the official page publishes an application window or deadline.
- Reconfirm the eight live programmes and DESY against their official pages on the monthly cadence.
- Consider wiring the collector into the daily sweep once stable.

## Direction (updated 2026-08-25)
Worldwide Research category built on shared `programme_core`; 10 seeded sources, 8 evidence-backed live programmes, 1 recorded closed programme, and 1 pending programme.

Last worked (2026-08-25): collected+verified 7 programmes from official pages via manual-ai verifications, added NSF REU seed, DESY recorded closed, ETH pending.
