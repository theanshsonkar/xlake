# Fellowships - category doc

Status: IN PROGRESS. Folder: engine/categories/fellowships/.

This doc is the overview and worklist for the Fellowships category. It does NOT store opportunity data - those live in engine/data/lake/opportunities.json.

## What this category is
Structured worldwide fellowships and fellowship programmes with an official source page. Capture each programme's own status, eligibility, funding, and application information only when supported by quotable evidence from its official page.

### Included
- Worldwide fellowships and fellowship programmes.
- Official programme pages with evidence that can be checked and refreshed.

### Excluded
- Unverified claims about dates, eligibility, funding, or status.
- Programmes without an official source URL.

## Audience
WORLDWIDE - open to anyone, anywhere. There is no India or other location filter. Capture each fellowship's own eligibility from its official page.

## Evidence rules
- Every programme needs its official source URL and quote-backed evidence from an official page for each recorded fact.
- Dates, eligibility, funding, and status come from official pages; never invent a date or infer a status.
- A failed, blocked, partial, or unclear read never closes a row.
- Verification records may contain only facts supported by their recorded official evidence. Fields without evidence remain unconfirmed.

## Liveness model
- `programme_status: "open"` or `"closed"` is recorded only when the official page provides quote-backed evidence for that status.
- `needs_confirmation: true` is a row-level serving flag for a fellowship whose official eligibility/funding facts may be verified but whose current programme status is not. Such a row has no `programme_status` assertion, is conservatively `is_live: false`, and is not treated as officially closed.
- A failed, blocked, partial, or unclear read never closes a fellowship and does not create a status claim.

## Source worklist
Status values: not-started / collected / verified open / verified closed / needs confirmation / pending / blocked.

| Source | Official URL | Status |
|---|---|---|
| MLH Fellowship | https://fellowship.mlh.io/ | verified open |
| Thiel Fellowship | https://thielfellowship.org/ | needs confirmation |
| Echoing Green Fellowship | https://echoinggreen.org/fellowship/apply/ | verified closed |
| Kleiner Perkins Fellows Program | https://www.kleinerperkins.com/fellows/ | verified closed |
| Acumen Fellowship Program | https://acumenacademy.org/fellowship/ | needs confirmation |
| Mozilla Fellowship Program | https://www.mozillafoundation.org/en/what-we-do/grantmaking/fellowship/ | needs confirmation |
| Emergent Ventures | https://www.mercatus.org/emergent-ventures | needs confirmation |
| Eisenhower Fellowships Global Program | https://www.efworld.org/apply-now/ | verified closed |
| Schmidt Science Fellows | https://schmidtsciencefellows.org/selection/who-can-apply/ | needs confirmation |
| Ashoka Fellowship | https://www.ashoka.org/en-us/program/ashoka-fellowship | needs confirmation |

## Manual verification
Evidence-backed records are stored in `data/operations/fellowship_programme_verifications.json` and surfaced via `python3 -m categories.fellowships.fellowships --apply-verifications`.

## Collector
`python3 -m categories.fellowships.fellowships` runs the live collector. It is built on the shared programme engine `categories/programme_core.py`. It is not yet wired into the daily sweep.

## Local commands
Run from `engine/`:

```bash
python3 -m categories.fellowships.fellowships
python3 -m categories.fellowships.fellowships --apply-verifications
```

## Initial work note
Initial category artifacts and quote-backed verification records created 2026-08-28. The collector and verification application should be rerun on the monthly cadence; no unsupported row count or universal eligibility claim is made here.
