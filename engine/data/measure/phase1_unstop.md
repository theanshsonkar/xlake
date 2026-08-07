# Phase 1.2 — Unstop public opportunity API measurement

## Provenance

- Date: 2026-08-04 (IST).
- Host: `unstop.com`.
- User-Agent reused exactly from `engine/fetch.py` / `engine/robots.py`:
  `xlake/1.0 (+https://github.com/theanshsonkar/xlake; contact: anshsonkar@users.noreply.github.com)`.
- The first HTTP request was `https://unstop.com/robots.txt`; it returned HTTP 200.
- Relevant robots lines, verbatim:

```text
Allow: /internship/
Allow: /job/
Allow: /competitions/
Allow: /practice/
Allow: /hackathons/
Allow: /api/public/*
Disallow: /api/get-attachment/*
Disallow: /api/*
```

The explicit `/api/public/*` allowance was present, so probing continued. Requests to Unstop were serialized with a 2.2-second gap (one request at a time). Total requests: 25, including the robots request; no request was made outside `unstop.com`'s allowed public API paths.

## Paths tried and statuses

All statuses below were HTTP statuses from the live requests. The first four were endpoint discovery paths. The remaining entries were query variants on the successful path; the query parameters did not alter the result or total.

| Path / URL | Status |
|---|---:|
| `/robots.txt` | 200 |
| `/api/public/search/opportunities` | 404 |
| `/api/public/opportunity/search` | 200 |
| `/api/public/opportunities` | 404 |
| `/api/public/opportunity` | 404 |
| `/api/public/opportunity/search?page=2` | 200 |
| `/api/public/opportunity/search?page=1&subtype=internships` | 200 |
| `/api/public/opportunity/search?page=1&type=jobs&subtype=internships` | 200 |
| `/api/public/opportunity/search?page=1&opportunity_type=internships` | 200 |
| `/api/public/opportunity/search?page=1&category=internships` | 200 |
| `/api/public/opportunity/search?page=1&search=internship` | 200 |
| `/api/public/opportunity/search?page=1&opportunity_type=1` | 200 |
| `/api/public/opportunity/search?page=1&opportunity_type=2` | 200 |
| `/api/public/opportunity/search?page=1&opportunity_type=3` | 200 |
| `/api/public/opportunity/search?page=1&type=internships` | 200 |
| `/api/public/opportunity/search?page=1&sub_type=internships` | 200 |
| `/api/public/opportunity/search?page=1&opportunity_subtype=internships` | 200 |
| `/api/public/opportunity/search?page=1&subtype=internship` | 200 |
| `/api/public/opportunity/search?page=1&opportunity_type=internship` | 200 |

The six first query checks were repeated once because the local measurement script errored while formatting a `null` subtype after the HTTP response; those repeated responses were also HTTP 200 and were used for the saved analysis. No response status was fabricated from the local formatting error.

## Working endpoint and pagination

Working endpoint, page 1:

```text
https://unstop.com/api/public/opportunity/search?page=1
```

The request to `unstop.com` returned JSON with top-level key `data`. The response's own canonical `path` and pagination links use the equivalent API host:

```text
https://api.unstop.com/api/public/opportunity/search?page=1
```

Pagination is by the `page` query parameter. The response reported:

```text
current_page: 1
per_page: 20
last_page: 15310
total: 306191
```

`https://unstop.com/api/public/opportunity/search?page=2` returned `current_page: 2`, 20 records, and different IDs. Page 1 began with IDs `1195069, 1142464, 626464`; page 2 began with IDs `1729927, 1729826, 1729921`. Therefore `page` is real pagination, not a repeated page. No `offset` mechanism was observed. `per_page` is returned as 20; changing it was not established.

The `total` field is the total for this unfiltered endpoint: `306191`. It is not an India-internship total.

## Complete top-level field names on one record

The first record contained 46 top-level fields, exactly:

```text
id
visibility
paid
title
festival_id
organization_id
public_url
web_url
start_date
end_date
location
type
region
overall_prizes
regn_open
regn_url
regn_email
registration_clicks
user_id
moderation_status
combined_leaderboard
display_date
approved_date
remarks
subtype
source
logoUrl
logoUrl2
regnRequirements
organisation
seo_url
status
tags
viewsCount
registerCount
thumb
banner
banner_mobile
filters
festival
review_details
fields
time_left
prizes
register_start_time
seo_details
```

There is no top-level `eligibility`, `eligibility_criteria`, `description`, or `graduation_year` field.

## India internship eligibility sample

The endpoint cannot currently be filtered reliably using the tested query names. The sample below is therefore the internship-shaped subset present on captured page 1, with India evidence reported conservatively. `subtype` was the internship marker; `type` was still `jobs`.

Observed exact values include:

| Question | Observation and verbatim examples |
|---|---|
| Eligibility field | No top-level field. Nested `regnRequirements.eligibility` exists and is a JSON-encoded string for many records; it can also be `null`. Verbatim examples: `"eligibility":null` and `"eligibility":"{\"sector\":[\"students\",\"fresher\"],...}"` (the captured JSON string continues with course rules). |
| Batch / graduation year | Yes, nested in the eligibility JSON. Exact values observed: `"fresherPassoutYearsSelected":[2026]`, `"studentPassoutYearsSelected":[2029,2030,2031,2032]`, `"passoutYear":["2023","2024","2025","2026"]`, and `"passoutYear":["all"]`. |
| Degree requirement | Yes where specified, via structured course entries. Exact values observed: `"course":"btech"`, `"course":"mtech"`, and `"course":"bca"` under `"engineering"`; empty `"engineering":[]` was also observed. |
| Deadline / end date | Yes. Exact values: `"end_date":"2026-08-17T00:00:00+05:30"` and nested `"end_regn_dt":"2026-08-17T00:00:00+05:30"`. |
| Location | Top-level `location` was `null` in sampled internship records. Exact value: `"location":null`. |
| Remote indication | No explicit `remote` boolean or text field was observed. Exact values included `"region":"online"` and nested `"work_location_type":"pan_india"` or `"work_location_type":"city"`; `region:"online"` is not treated as proof of remote work. |
| Full description | No full description field was present in the listing record. `seo_details.description` contains short marketing/apply text, e.g. `"description":"Click the link to apply for Marketing Internship at Cogniza Private Limited."`; this is not a full job description. No second-request detail endpoint was probed. |
| Official company posting vs Unstop page | `public_url` / `seo_url` point to Unstop, e.g. `https://unstop.com/internships/app-developer-internship-navrasa-it-solutions-1730339`. `web_url` was usually `null`; one captured sample had exact external value `"web_url":"zuhaus.org"`. No sampled external URL was verified as the company's official posting. `regn_url` was commonly `null` or empty. |
| Explicit India scope | One captured internship had nested `"allowed_countries":"[\"India\"]"`. Other samples had nested `"allowed_countries":"[]"` or `null`, which means no explicit country restriction in this field, not proof of India. |

Concise verbatim excerpts from captured records:

```json
{"subtype":"internships","type":"jobs","region":"online","location":null,
 "regnRequirements":{"eligibility":null,"allowed_countries":"[\"India\"]"}}
```

```json
{"subtype":"internships","type":"jobs","end_date":"2026-08-17T00:00:00+05:30",
 "regnRequirements":{"end_regn_dt":"2026-08-17T00:00:00+05:30",
 "eligibility":"{\"sector\":[\"students\",\"fresher\"],...}"},
 "seo_details":[{"description":"Click the link to apply for Marketing Internship at Cogniza Private Limited."}]}
```

The `...` marks omitted continuation for readability; it is not asserted as a literal API value. The complete raw response was not copied into this report, consistent with the project's rule not to publish full descriptions.

## India internship volume

**Not established from this endpoint within the measurement budget.** The only defensible total returned by the endpoint is `306191`, which covers all opportunity kinds. The endpoint returned `total:306191` for every tested text, numeric, singular, and plural internship query, and records remained mixed (`jobs`, `hackathons`, `workshops`, and multiple subtypes). Counting pages of the unfiltered endpoint would require reading all `15310` pages and still would not establish India scope from the available fields.

A page-1 observation is not a volume estimate: it contains internship records, but only one sampled internship explicitly carries `regnRequirements.allowed_countries` equal to `"[\"India\"]"`; records with `allowed_countries:"[]"` are unrestricted rather than demonstrably India-only. No India-internship count is therefore reported.

## Mapping Unstop records to xlake kinds

The distinction is carried primarily by `subtype`, `type`, and the prefix of `public_url`; it is not carried by a single normalized `kind` field.

| xlake kind | Field(s) and observed values |
|---|---|
| job | `subtype:"jobs"`; `public_url` prefix `jobs`; `type:"jobs"` also occurs. |
| internship | `subtype:"internships"`; `public_url` prefix `internships`; notably `type:"jobs"` for these records. |
| competition | Observed `type:"hackathons"`, `subtype:"online_coding_challenge"`, and `public_url` prefix `hackathons`; `type:"cultural"` and `subtype:"events"` were also observed but are not confidently mapped to one of the five xlake kinds. |
| programme | No value confidently identifying a programme was observed on the captured two pages. `subtype:"events"` was observed, but is not assumed to mean programme. |
| scholarship | No scholarship value was observed on the captured two pages; the adapter needs broader sampling or documented API filter semantics. |

Observed distinct values on captured page 1, verbatim:

```text
type:    "jobs", "hackathons", "workshops", "cultural"
subtype: "internships", "jobs", "online_coding_challenge", "events", null
public_url prefixes: "internships", "jobs", "hackathons", "workshops-webinars", "events"
```

## What an adapter would need

1. The undocumented filter syntax or request shape that reliably restricts `/api/public/opportunity/search` to `subtype:"internships"` and to India. All tested query parameters were accepted with HTTP 200 but ignored.
2. A way to count the filtered India-internship result set; `total` currently counts all 306191 records.
3. Confirmation of whether `web_url` is a company-owned official posting, an arbitrary external link, or a redirect, and whether another allowed public API field contains a verified original posting URL.
4. A detail endpoint or documented field for the full opportunity description; the listing response contains only short `seo_details.description` text.
5. Complete type taxonomy for programme and scholarship, including whether `type`, `subtype`, `public_url`, or another nested field is authoritative.
6. Semantics of `region:"online"`, `work_location_type:"city"`, and `work_location_type:"pan_india"`; none is assumed to equal an explicit remote-work statement.
7. Eligibility normalization rules for JSON strings containing `"all"`, empty arrays, `passoutYear`, `fresherPassoutYearsSelected`, course names, and experience constraints.

## Assumptions and non-claims

- “India internship” was not inferred merely from an Indian-looking organization name or an Unstop URL. Explicit country evidence was limited to the nested `allowed_countries` value; unrestricted `[]` was not counted as India.
- `subtype:"internships"` was treated as the observed internship label only for sampling, not as a successful server-side filter.
- `seo_details.description` was treated as metadata/marketing copy, not as a full job description.
- No adapter code was written. No request was made to a detail page or any path outside the tested robots-allowed public API paths.