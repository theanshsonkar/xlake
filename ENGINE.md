# Active engine reference

The active collector is `engine/`, and all commands below are run from that
directory. This document describes implemented layout and persistence; it does
not claim universal source coverage or a universal freshness SLA.

## Purpose and flow

The collector resolves named companies to official employer/ATS sources, reads
structured boards where possible, reads selected pages where necessary, filters
and annotates rows, retains evidence, and publishes JSON artifacts. It never
submits applications and never treats generic eligibility signals as an
individual eligibility promise. LinkedIn and Naukri are not accessed or
republished.

```text
optional enumeration -> engine/data/raw/discovery-cache/ (leads only)
company resolver -> engine/data/operations/registry.json
board adapters -> lake/opportunities.json + lake/hidden.json
page reader -> operations/pagereader_rows.json (operational output only)
run/state -> engine/data/operations/
```

A successful empty result is different from an error or partial read. Only a
complete, successful source confirmation can support absence-based liveness;
uncertain reads do not establish closure. Records are retained.

## Packages and commands

`core/` owns shared cache, filters, quality, robots, page-text, tiering, and
`paths.py`. `adapters/boards.py` owns the existing large board adapter module;
`adapters/extractors.py` owns fixture/optional-LLM page extraction. The root
modules with those names are thin backward-compatible import facades. In
particular, `python3 fetch.py greenhouse vercel` delegates to
`adapters.boards.main()` and keeps the historical launcher behavior.

The remaining command files stay at the engine root:

| Command | Purpose |
|---|---|
| `sweep.py` | Collect resolved boards, apply filters/quality, merge retained lake rows, and append a run report. Network collection; use CI for full sweeps. |
| `resolve.py` | Resolve a company/domain to a source and verify readable boards. Network collection. |
| `resolve_companies.py` | Rewrite the operational registry and page-reader target queue. Network collection. |
| `read_pages.py` | Read queued careers pages and write operational page-reader state/rows. Network collection and optional model enrichment. |
| `read_url.py` | Inspect one URL using known APIs or HTML fallbacks. Network collection. |
| `enumerate_boards.py` | Optional Common Crawl lead enumeration; writes discovery cache only. Network collection. |
| `build_fixtures.py` | Fetch/show/check committed offline fixtures; only `check` is offline. |

Useful offline checks from `engine/` include `python3 build_fixtures.py check`,
`python3 -m unittest tests.test_robots`, and the archive verifier at
`python3 engine/tools/verify_oldengine_archive.py`. Do not interpret these as a
sweep or source-coverage check.

## Canonical persistence

All paths are absolute/package-derived by `core.paths` and are listed here
relative to `engine/`:

| Path | Role |
|---|---|
| `data/lake/opportunities.json` | The only canonical final user-facing opportunity lake. |
| `data/lake/hidden.json` | Retained non-default companion for rejected/hidden rows; not deleted. |
| `data/lake/opportunities_history.json` | Historical opportunity evidence. |
| `data/operations/registry.json` | Resolver-confirmed company-scoped board registry. |
| `data/operations/runs.jsonl` | Append-only operational sweep reports. |
| `data/operations/tier_state.json` | Persistent board tier history. |
| `data/operations/pagereader_state.json` | Page content hashes and extraction state. |
| `data/operations/pagereader_targets.json` | Resolver queue for page-reader/re-resolution work. |
| `data/operations/pagereader_rows.json` | Operational processing/compatibility output from the page reader; explicitly not a second final lake. |
| `data/operations/companies.txt` | Resolver input. |
| `data/raw/` | Private HTTP response recordings; raw source text is not product output. |
| `data/raw/discovery-cache/` | Common Crawl lead caches, separate from private HTTP recordings. |
| `data/measure/` | Historical measurement evidence; old command strings there are historical records, not active paths. |

The sweep writes the canonical opportunities and hidden stores. The page reader
maintains its operational rows separately and does not create a category lake.
`LAKE_RAW_DIR` may relocate private HTTP recordings; it must not relocate the
discovery cache. Raw recordings and the discovery cache are not the canonical
user-facing data.

## Trust and source notes

Discovery leads are never product verification. A row should not be displayed
as live or verified without the official source URL, provenance, and a recent
successful confirmation. Errors, stale checks, blocked pages, and partial reads
are needs-confirmation states rather than closure facts. Descriptions may be
retained internally for extraction and audit, but user surfaces link to the
official source rather than displaying a full description.

Keka has a documented public JSON API. Zoho Recruit and Darwinbox remain
page-reader or bespoke-source work. Workday is implemented, but pagination and
read completeness need monitoring. AI is optional page enrichment and the quote
gate prevents it from inventing source facts.

## CI

The root workflow is `.github/workflows/sweep.yml`; its jobs keep
`working-directory: engine`. It stages canonical lake files and operational run,
tier, and page-reader state files from `engine/data/**`. Artifact uploads use
the reorganized paths and deliberately exclude private raw recordings. Full
sweeps are CI work, not lightweight migration validation.

## Categories

`engine/categories/` is scaffolding for category predicates/annotations and
category-specific processing helpers only. It does not activate or claim any
category, and it must not own a final database. Category work is one category at
a time and uses the shared canonical lake and trust policy. Structural
scaffolding is allowed; premature category contract documents or implementation
stubs are not. See `REGISTRY-PLAN.md`.

## Archived legacy tree

The inactive legacy source was archived, verified, and deleted with explicit
approval. Its dated archive is
`archive/opportunity-lake-oldengine-2026-08-16/`. The archive manifest records
included files, sizes, hashes, capture metadata, exceptions, and cache files
omitted because they were byte-identical to the active discovery cache.
`SHA256SUMS` covers included archive files. Verify the archive with:

```bash
python3 engine/tools/verify_oldengine_archive.py
```
