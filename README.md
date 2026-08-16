# Opportunity Radar — the collector

Opportunity Radar collects opportunities from official employer, programme, ATS,
and other source pages. It helps people inspect evidence and freshness and open
the original application page; it does not promise individual eligibility and
never submits an application.

The operational root is `engine/`. Discovery sources are leads only. A role is
not product-live or verified until its original official URL, provenance, and a
successful confirmation are available. Errors, stale checks, blocked pages, and
partial reads need confirmation; they do not establish closure. Records are
retained.

## Layout

```text
engine/
  core/                 shared policy/infrastructure implementations
  adapters/             source integrations (`boards.py`, `extractors.py`)
  categories/           inactive category predicate/annotation scaffold only
  data/
    lake/               canonical final opportunities + retained hidden rows
    operations/         registry, run/state, resolver input, page-reader output
    raw/                private HTTP recordings and discovery-cache/
    measure/            historical measurement evidence
  fixtures/             committed offline page/extractor fixtures
```

`engine/data/lake/opportunities.json` is the only canonical final user-facing
opportunity lake. `lake/hidden.json` is its retained non-default companion and
`lake/opportunities_history.json` is historical evidence. The page reader keeps
`data/operations/pagereader_rows.json` as an operational processing/
compatibility output; it is not a second final lake. No category owns a final
database.

The implementations live in `core` and `adapters`. Root files `cache.py`,
`filters.py`, `quality.py`, `robots.py`, `pagetext.py`, `tiering.py`,
`extractors.py`, and `fetch.py` are documented backward-compatible import
facades. The `fetch.py` facade also preserves `python3 fetch.py ...`.

## Commands

Run commands from the engine directory:

```bash
cd engine
python3 filters.py                         # compatibility CLI
python3 fetch.py greenhouse vercel         # one board; may access network
python3 resolve.py --file data/operations/companies.txt # resolver input; may access network
python3 read_url.py URL                    # one URL; may access network
python3 build_fixtures.py check             # offline fixture check
python3 -m unittest tests.test_robots      # targeted offline test example
```

A sweep is network collection and is intentionally not part of the lightweight
migration validation. Full sweeps belong on CI. `LAKE_WORKERS`,
`LAKE_HOST_DELAY`, and `LAKE_LIMIT` control collection load.

Discovery enumeration caches leads in `engine/data/raw/discovery-cache/`; it is
not the scheduled collection universe. HTTP response recordings live under
`engine/data/raw/` and are private. `LAKE_RAW_DIR` may relocate those response
recordings without relocating the discovery cache.

## Trust and collection rules

- Live means recently confirmed at the official source; it is not a universal
  freshness SLA.
- A successful empty result is distinct from an error or partial read. An
  uncertain read cannot establish completeness or closure.
- Closed rows are hidden from default search but retained historically.
- LinkedIn and Naukri are never accessed or republished.
- Never display a full description; link to the official source.
- AI is optional page enrichment and cannot invent missing source facts.

Keka has a documented public JSON API. Zoho Recruit and Darwinbox remain
page-reader or bespoke-source work. Workday is implemented, but pagination and
read completeness require monitoring rather than a universal coverage claim.

## Categories

`engine/categories/` is structural scaffolding for category predicates,
annotations, and category-specific processing helpers only. Its existence does
not activate or claim support for any category. Category work remains one
category at a time, and category helpers must use the shared lake and trust
policy rather than creating a category database. See `REGISTRY-PLAN.md` for the
category-work convention.

## Legacy archive

The inactive legacy tree was archived and then deleted with explicit approval.
The dated archive is `archive/opportunity-lake-oldengine-2026-08-16/`.
`manifest.json` records included files, SHA-256 hashes, and omitted duplicate
cache mappings; `SHA256SUMS` records the included archive files. Verify it with:

```bash
python3 engine/tools/verify_oldengine_archive.py
```

The verifier is stdlib-only and checks both archive contents and omitted-cache
mappings against `engine/data/raw/discovery-cache/`.
