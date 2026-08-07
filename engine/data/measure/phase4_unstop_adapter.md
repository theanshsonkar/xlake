# Phase 4 — Unstop adapter measurement

- Date: 2026-08-04 (IST)
- Adapter: `engine/fetch.py`, platform `unstop`
- Endpoint: `https://unstop.com/api/public/opportunity/search`
- Exact params: `page=1..last_page`, `per_page=20`
- Test cap: `LAKE_LIMIT=40` (intentional test-only cap; production `LAKE_LIMIT=0`)
- API records fetched for this report: 40 (pages 1–2)
- Adapter search requests: 2; `reported_total=306191`, `last_page=15310`
- Pagination proof: page 1 IDs began `1195069, 1142464, 626464`; page 2 began `1729927, 1729826, 1729921`.
- The engine checked `robots.py` before the API requests; no detail pages or descriptions were fetched.
- Because the capped run is intentionally partial, the adapter returned `error=unstop_test_limit_partial_at_40`; this is required by the partial-fetch invariant, not a server failure.

## Kind mapping

The adapter uses `subtype` first, then `type`, then the public URL path. Platform labels are used only for this kind mapping, never for stage or discipline.

| Unstop value observed | Our kind | Rule |
|---|---|---|
| `subtype=internships` | `internship` | exact observed subtype |
| `subtype=jobs` / `type=jobs` | `job` | exact observed job value |
| `subtype=online_coding_challenge` | `competition` | exact challenge subtype |
| `type=hackathons` | `competition` | exact competition-like type |
| `subtype=events` | `programme` | closest non-job kind; raw value retained |
| `type=workshops` | `programme` | closest non-job kind; raw value retained |
| `type=cultural` | `programme` | closest non-job kind; raw value retained |
| explicit `scholarship(s)` or `grant(s)` | `scholarship` | only explicit scholarship/grant values; never inferred |
| null or unrecognised value | `job` | conservative closest fallback; raw value retained, never scholarship |

Observed distinct values in the measurement pages: `type`: `jobs`, `hackathons`, `workshops`, `cultural`; `subtype`: `internships`, `jobs`, `online_coding_challenge`, `events`, null; public URL prefixes: `internships`, `jobs`, `hackathons`, `workshops-webinars`, `events`.

## Ten samples

No full descriptions are included or fetched.

| Title | Kind | Batch years | Degree/course extracted | Deadline | Official company URL? | Canonical URL |
|---|---|---|---|---|---|---|
| Canva Designer | internship | 2023, 2024, 2025, 2026 | B.Tech, M.Tech, BBA, B.Com, M.Com, B.Sc, M.Sc, BA, MA, B.Des, B.Arch, B.F.Tech, M.Des, BCA, MCA, B.Pharm, M.Pharm | 2025-02-01T23:59:59+05:30 | no | https://unstop.com/internships/canva-designer-internship-quantum-dot-1195069 |
| Hands on training on x ray diffractometer | programme | — | — | 2024-09-12T00:00:00+05:30 | no | https://unstop.com/workshops-webinars/hands-on-training-on-x-ray-diffractometer-kalinga-university-1142464 |
| Social Media Marketing | internship | — | — | 2023-03-03T00:00:00+05:30 | no | https://unstop.com/internships/social-media-marketing-westinbridge-consulting-private-limited-626464 |
| Partner Onboarding Executive | job | 2026 | — | 2026-08-17T00:00:00+05:30 | no | https://unstop.com/jobs/partner-onboarding-executive-myhauz-1730346 |
| Marketing Internship | internship | 2026 | BBA, B.Com, M.Com, B.Sc, M.Sc, BA, MA, M.Des, B.Des, B.Arch, B.F.Tech | 2026-08-10T14:08:32+05:30 | no | https://unstop.com/internships/marketing-internship-cogniza-private-limited-1729814 |
| Campus Community Manager Internship | internship | — | BBA, B.Com, M.Com, B.Sc, M.Sc, BA, MA, M.Des, B.Des, B.Arch, B.F.Tech | 2026-08-17T00:00:00+05:30 | no | https://unstop.com/internships/campus-community-manager-internship-mycaptain-by-imarticus-learning-1729937 |
| App Developer Internship | internship | 2026 | B.Tech, M.Tech, BCA, MCA, Diploma, B.Sc, M.Sc, BA, MA, M.Des, B.Des, B.Arch, B.F.Tech | 2026-08-17T00:00:00+05:30 | no | https://unstop.com/internships/app-developer-internship-navrasa-it-solutions-1730339 |
| Community Manager Internship | internship | 2029, 2030, 2031, 2032 | B.Tech, BCA, Diploma, BBA, B.Com, B.Sc, BA, B.Pharm | 2026-08-17T00:00:00+05:30 | no | https://unstop.com/internships/community-manager-internship-mycaptain-1729859 |
| Campus Growth Ambassador Internship | internship | 2028, 2029, 2030, 2031, 2032 | B.Tech, BCA, BBA, B.Com, B.Sc, BA, B.Des | 2026-08-17T00:00:00+05:30 | no | https://unstop.com/internships/campus-growth-ambassador-internship-mycaptain-1729864 |
| Student Career Leader Internship | internship | 2028, 2029, 2030 | B.Tech, BCA, Diploma, BBA, B.Com, M.Com, B.Sc, M.Sc, BA, MA, M.Des, B.Des, B.Arch, B.F.Tech | 2026-08-06T23:57:00+05:30 | no | https://unstop.com/internships/student-career-leader-internship-unlox-academy-1729940 |

Seven of the ten samples yielded a non-empty `batch_years` list. No official company URL was available in the ten samples or in the 40 fetched records; all canonical URLs therefore used the Unstop origin. The adapter accepts an absolute external `web_url` as an official URL when one is present, but does not fabricate one; `regn_url` is not used as a posting URL.

## Counts over the 40 fetched records

| Kind | Count |
|---|---:|
| internship | 27 |
| job | 9 |
| programme | 2 |
| competition | 2 |
| scholarship | 0 |

| Eligibility status | Count |
|---|---:|
| confirmed (one or more structured gates stated) | 38 |
| rules_unclear (no structured gate found) | 2 |

Structured fields are stored on each `Posting` as `eligibility` and in `BoardResult.extra["records"]`; the adapter also creates only a short eligibility projection for the existing `filters.resolve_stage()` gate path. Raw field/value evidence is retained separately and no trust value is used to derive eligibility status.

## Known gaps

- India filtering is unresolved. The measured `internship`, `type`, `subtype`, `category`, text, and numeric query parameters all returned the same mixed `total=306191`; the adapter therefore does not claim an India-only server-side feed.
- If `regnRequirements.allowed_countries` explicitly contains `India`, or `work_location_type` explicitly contains `pan_india`, the adapter appends `India` to the location so the existing `filters.classify()` location bucket can handle it. `[]`, null, `region=online`, and Indian-looking organisation names are not treated as India evidence. Other records are left for downstream location classification and may remain `global_hiring`.
- The API taxonomy observed so far has no confirmed scholarship or programme vocabulary beyond the closest mappings above; explicit grants/scholarships are kept separate, while unknown values fall back to `job` and retain their raw value.
- `eligibility` can be null or malformed; those values are ignored without crashing. `all` is treated as no finite batch-year constraint. Course taxonomy values are reduced to recognised degree names for the shared degree gate while raw course values remain in evidence.
- The listing endpoint exposes no full description in the measured schema. No detail endpoint was probed; the adapter never publishes a full description.
- The test cap intentionally returns after page 2. A production run with `LAKE_LIMIT=0` must reach the API's own `last_page` and `total`; any request/shape/total mismatch is an error. The test cap is explicitly marked `test_limited`.
- The public Unstop URL is a low-trust/community-origin source in the separate provenance axis; this adapter does not merge that trust judgment into `eligibility_status`.
