# Opportunity Radar — the collector

The engine behind Opportunity Radar, a search engine for opportunities from
official sources. It helps people search, inspect evidence and freshness, and
open the original application page. It does not make an individual eligibility
promise and it never submits an application.

The active collector lives under `engine/`. Canonical generated artifacts live
under `engine/data/`. The engine currently lists **15 platform adapters**, with
optional page-reader and LLM enrichment for sources that do not expose a usable
structured endpoint. AI is optional enrichment; it is not a substitute for
source confirmation.

## How it works

```
engine/enumerate_boards.py  discovery leads from public indexes and registries
engine/resolve.py           resolve a company or programme lead to its official source
engine/fetch.py             platform adapters, pagination, and source reads
engine/filters.py           generic title, location, stage, and relevance gates
engine/sweep.py             scheduled collection, merge, retention, and status updates
```

Discovery sources are leads only. Product/display contract: the default surface
must not mark a role live or display it as verified until the original official
employer, ATS, or programme URL, source provenance, and a last successful
confirmation are available. This is a required target, not a claim that the
current collector always persists those fields; provenance and confirmation
persistence, and fail-closed partial-read handling, are implementation
requirements still being hardened where necessary. The official source is the
primary CTA.

## Trust contract

These are product/display semantics and acceptance requirements, not a claim
that current sweeps universally enforce them:

- **Live** means recently confirmed present at the official source; the last
  confirmation is shown and is not a universal freshness SLA.
- Errors, stale checks, ambiguous expiry, blocked pages, and partial reads are
  **needs confirmation**, not live or closed by default.
- Closed rows are hidden from default search but retained historically; the
  collector does not delete records.
- No individual eligibility guarantee is made. Generic gates and evidence help
  people decide what to inspect.
- Coverage is incomplete by design: not every source or role is covered, and
  no universal freshness claim is made.

The product contract requires partial reads to be treated as uncertain and not
to establish completeness or closure. Persistence and fail-closed enforcement
remain implementation requirements being hardened where necessary.

## Current source notes

Keka has a documented public JSON API:
`/careers/api/embedjobs/{portalName}/active/{board_guid}`. Zoho Recruit and
Darwinbox remain page-reader or bespoke-source work. Workday is an implemented
source whose pagination and read completeness must be monitored; it is not
silently treated as fully covered. The optional page-reader/LLM path is used
where a public page must be interpreted, not to invent missing source facts.

## Running it

Run commands from the engine directory so paths and canonical artifacts remain
unambiguous:

```bash
# cheap local test — do this, not a full sweep
cd engine
LAKE_LIMIT=20 LAKE_WORKERS=2 python3 sweep.py keka greenhouse

# filter test set
python3 filters.py

# one board
python3 fetch.py greenhouse vercel

# resolve companies from an engine-local input file
python3 resolve.py --file companies_india.txt
```

Full sweeps belong on CI, not a laptop. `LAKE_WORKERS`, `LAKE_HOST_DELAY`, and
`LAKE_LIMIT` control load.

## Collector rules

- One request at a time per host, with a delay, an honest User-Agent, and
  `robots.txt` respected.
- LinkedIn and Naukri are never accessed; their listings are leads at most and
  are not republished.
- A successful empty result must be distinct from an error or partial read. The
  acceptance requirement is that an uncertain read cannot establish closure or
  completeness; current sweep enforcement is still being hardened where
  necessary.
- Records are retained. A posting that is reliably confirmed absent becomes
  closed/not live; uncertain records become needs confirmation. These are
  required status semantics, not a claim that every current sweep already
  enforces them.
- Never display a full job description; link to the original official source.
