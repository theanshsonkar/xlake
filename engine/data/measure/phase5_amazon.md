# Phase 5 — Amazon adapter

Date: 2026-08-04

## Robots

Fetched `https://www.amazon.jobs/robots.txt` with the existing xlake User-Agent. HTTP status: 200. The relevant `User-agent: *` lines are verbatim:

```
User-agent: *
Disallow: /internal
Disallow: /en/internal
Disallow: /en-gb/internal
Disallow: /cs/internal
Disallow: /de/internal
Disallow: /es/internal
Disallow: /fr/internal
Disallow: /it/internal
Disallow: /jp/internal
Disallow: /pl/internal
Disallow: /pt/internal
Disallow: /zh/internal
```

`/search.json` is allowed. No crawl-delay is stated; the existing engine default of one second per host applies.

## API and token

Adapter token format: `COUNTRY` or `COUNTRY|query`; the supported country-token set is `IND`, `USA`, `CAN`, `GBR`, `DEU`, `FRA`, `ITA`, `ESP`, `IRL`, `LUX`, `AUS`, and `SGP`. The query is passed as `base_query`; categories are ignored for all decisions.

Exact request URL template:

```
https://www.amazon.jobs/search.json?base_query={urlencoded_query}&country={country}&result_limit=20&offset={offset}
```

Parameters used: `base_query` (empty for token `IND`, `data analyst` for the limited test), `country=IND`, `result_limit=20`, and zero-based `offset` increments of 20. The API total is the top-level integer `hits`; it is required, must remain stable across pages, and is never inferred from page length.

Observed total for `country=IND` with an empty `base_query`: **2,625**.

## Limited live pagination test

Token: `IND|data analyst`.

The API reported 31 total postings. The adapter made **2 search API requests** (the engine also checked `robots.txt` before the first API request):

| Request | URL | Returned |
|---:|---|---:|
| 1 | `https://www.amazon.jobs/search.json?base_query=data+analyst&country=IND&result_limit=20&offset=0` | 20 |
| 2 | `https://www.amazon.jobs/search.json?base_query=data+analyst&country=IND&result_limit=20&offset=20` | 11 |

Result: `status=200`, `count=31`, `reported_total=31`, `error=None`. Completeness was confirmed because the collected offset reached the API's confirmed total (`31/31`); the 11-row final page was accepted only because it ended exactly at that total. No full 2,625-role fetch was made.

## Fetch states

- **ok:** HTTP response succeeds; JSON shape has a `jobs` list; `hits` is a confirmed non-negative integer and remains unchanged; every job has a public `job_path`; pagination reaches `hits` exactly. A 200 response with `hits=0` and no jobs is also `ok` with count zero.
- **empty:** represented by the `ok` state with `count=0`, never by `dead` or an error.
- **error:** HTTP/request/robots failure, non-JSON or unexpected shape, missing/invalid `hits`, a changed total, an invalid job/path, a short page while the confirmed total says more rows exist, an over-reported page, or a runaway pagination guard. Any failure after rows have been collected is still an error and is marked as partial; it cannot look complete.

Descriptions are populated inline after HTML stripping. `location` remains a compatibility string; `locations` is populated as a normalized list of city/state/country strings. URLs are built from each API `job_path` under `https://www.amazon.jobs`.

## Classification over limited fetch

Counts cover all 31 fetched postings. `stage` is `filters.classify(title, location).stage`; `stage_resolved` is the description-enriched `filters.resolve_stage` result. Eligibility status uses extracted gates and hidden reason; it is independent of source trust.

| Dimension | Value | Count |
|---|---|---:|
| stage | early | 2 |
| stage | senior | 16 |
| stage | unknown | 13 |
| stage_resolved | early | 2 |
| stage_resolved | senior | 16 |
| stage_resolved | unknown | 13 |
| eligibility_status | confirmed | 2 |
| eligibility_status | rules_unclear | 10 |
| eligibility_status | hidden | 19 |

## Ten sample postings

No descriptions are displayed.

| # | Title | First location | Locations | Description length | URL |
|---:|---|---|---:|---:|---|
| 1 | Business Analyst, WHS Data | Bengaluru, Karnataka, India | 1 | 1505 | https://www.amazon.jobs/en/jobs/10462523/business-analyst-whs-data |
| 2 | Senior Financial Analyst, Data Center Finance | Hyderabad, Telangana, India | 1 | 3484 | https://www.amazon.jobs/en/jobs/10481669/senior-financial-analyst-data-center-finance |
| 3 | Business Analyst-Data Insights, Translation Services Operations | Hyderabad, Telangana, India | 1 | 4695 | https://www.amazon.jobs/en/jobs/10460778/business-analyst-data-insights-translation-services-operations |
| 4 | Workflow Analyst , Ring Data Engineering Services | Hyderabad, Telangana, India | 1 | 1125 | https://www.amazon.jobs/en/jobs/10461249/workflow-analyst-ring-data-engineering-services |
| 5 | Business Analyst, Ring Data Engineering Services | Hyderabad, Telangana, India | 1 | 4268 | https://www.amazon.jobs/en/jobs/10461248/business-analyst-ring-data-engineering-services |
| 6 | Workflow Analyst , Ring Data Engineering Services | Chennai, Tamil Nadu, India | 1 | 1125 | https://www.amazon.jobs/en/jobs/10461243/workflow-analyst-ring-data-engineering-services |
| 7 | Workflow Analyst , Ring Data Engineering Services | Chennai, Tamil Nadu, India | 1 | 1125 | https://www.amazon.jobs/en/jobs/10461247/workflow-analyst-ring-data-engineering-services |
| 8 | Workflow Analyst , Ring Data Engineering Services | Hyderabad, Telangana, India | 1 | 1125 | https://www.amazon.jobs/en/jobs/10423554/workflow-analyst-ring-data-engineering-services |
| 9 | Business Analyst II, Selling Partner Dev Services | Bengaluru, Karnataka, India | 1 | 2950 | https://www.amazon.jobs/en/jobs/10426286/business-analyst-ii-selling-partner-dev-services |
| 10 | Business Analyst, India Supply Chain, IN Supply Chain - Analytics and Automation | Bengaluru, Karnataka, India | 1 | 5165 | https://www.amazon.jobs/en/jobs/10469766/business-analyst-india-supply-chain-in-supply-chain-analytics-and-automation |

## Known gaps

- Job `10488368` (`SDE I Intern, Amazon University Talent Acquisition`) is a fully public page but did not appear in `search.json` under any query tried. `country=IND` with `base_query=intern` returned only 13 hits. This adapter therefore cannot be assumed complete for campus/university requisitions; the Phase 2 URL reader remains the route for those URLs.
- Amazon's business/category/family/team fields are not used for classification. Official source trust and eligibility status remain separate axes.
- The limited test used `data analyst` and is not a measurement of the full-country result distribution. The `IND` total of 2,625 is the observed empty-query API total, not a claim that every campus requisition is indexed.
- No Amazon token was added to the registry or sweep entry list; invoking `amazon IND` directly intentionally performs the complete country fetch, while normal sweep board limits remain unchanged.
