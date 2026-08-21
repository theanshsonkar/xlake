# Hackathons - category doc

## What this category is

A structured listing of official build-and-ship hackathons and buildathons with
current dates and action links. This category is collected by a deterministic
source collector, not by the programme page reader.

### Included

- Upcoming or currently-open build-and-ship hackathons/buildathons worldwide.
- Opportunities with an official page and dates.

### Excluded

- Accelerators and founder programmes (a separate future category).
- Past or ended events.
- Anything without an official URL.

## Audience

WORLDWIDE, open to anyone, anywhere. No India filter is applied. Each row
carries its own location/online status and eligibility.

## Sources

| Source | Endpoint | Type | Status | Notes |
|---|---|---|---|---|
| Devpost | https://devpost.com/api/hackathons (status[]=upcoming&status[]=open) | public JSON | live | official `*.devpost.com` links; dates are display strings parsed with null fallback |
| MLH | https://mlh.io/seasons/{year}/events (current + next season) | public HTML (schema.org/Event) | live | ISO startDate/endDate; official outbound URL (UTM stripped) |
| Unstop | https://unstop.com/api/public/opportunity/search-result?opportunity=hackathons | public JSON (robots Allow /api/public/*) | live | seo_url official link; India-centric, included worldwide without filter |

## Freshness & trust model

- Only upcoming or currently-open hackathons are surfaced.
- Ended or past events are dropped at build time.
- Rows are sorted soonest-first.
- OFFICIAL links only.
- Dates are left null when unparseable — never fabricated.
- Liveness uses source-grouped closure: a hackathon absent from a
  successfully-fetched source is closed; a source that fails to fetch keeps its
  rows for a 7-day reconfirmation window.

## Row schema

Rows are `record_type='hackathon'`, `opportunity_type='hackathon'`, and
`category='hackathons'`, keyed by `official_url` as `hackathon_id`.

Fields: `title`, `organizer`, `source`, `official_url`, `application_url`,
`location`, `is_online`, `start_date`, `end_date`, `registration_deadline`,
`prize`, `tags`, `eligibility`, `status`, `official_evidence`,
`source_confirmation`, `source_mechanism`, `last_checked_at`.

The merge adds `first_seen`, `last_seen`, `is_live`, and `needs_confirmation`.

## Pass-through safety

`record_type='hackathon'` is a non-job row: `hackathon` is in
`core/quality.py` `_is_job_row`'s non-job set alongside `programme` and
`contribution`. The daily sweep passes non-job rows through untouched, and the
hackathon merge preserves all non-hackathon rows.

## Collector

Collect with:

```bash
python3 -m categories.hackathons.hackathons
```

Use `--list` to preview. The collector runs as its own daily sweep step, uses
zero adapter changes, and talks to sources with direct stdlib `urllib`.

## Current state (2026-08-21)

The initial live run surfaced approximately 348 upcoming hackathons: Devpost
169, MLH 65, and Unstop 114.

## Next actions

- Normalize MLH location whitespace (`City , Region` -> `City, Region`).
- Set `is_online` from MLH digital format when location text is absent.
- Consider more worldwide sources.

## Direction (updated 2026-08-21)

Last worked: 2026-08-21 — wired the worldwide Devpost, MLH, and Unstop
structured collector into the daily sweep, documented its source-grouped
freshness model, and seeded the canonical lake.
