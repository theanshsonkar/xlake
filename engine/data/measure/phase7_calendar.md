# Phase 7 — Programme calendar

Date: 2026-08-04

## Original schema

`access_channel`, `deadline`, `eligibility`, `evidence`, `excluded_reason`, `id`, `kind`, `name`, `needs_confirmation`, `note`, `official_url`, `org`, `remote_tier`, `stipend_text`, `tags`, `typical_close_month`, `typical_open_month`, `verify_status`, `window_note`

## Fields added

- Per entry: `grad_years_accepted`, `study_year_min`, `study_year_max`, `enrolled_required`, `degree_required`, `opening_soon_ready`.
- `verified` was added to every new entry as required. Existing `verify_status` values were retained.
- The existing `typical_open_month` and `typical_close_month` fields were retained unchanged. Existing rows use month-name strings; new rows use `null` because no dates were verified.
- Each entry evidence object now has keys for the seven requested eligibility/date fields. Values are `null` where no verbatim official-page quote was retained.

## Counts

- Original entries: 44
- New entries: 50
- Entries added: 6
- New entries with `verified: true`: 0
- Total `opening_soon_ready`: 3
- Preservation diff: 0 changed original key/value pairs; only additive fields were introduced.

## New entries

| ID | Official URL | Verified | Grad years accepted | Typical open month | Opening soon ready |
|---|---|---:|---|---:|---:|
| `amazon-hackon` | https://www.amazon.jobs/content/en/career-programs/university/hackon-with-amazon | `false` | `[]` | `None` | `false` |
| `amazon-ml-summer-school` | https://www.amazon.science/academic-engagements/amazon-ml-summer-school | `false` | `[]` | `None` | `false` |
| `microsoft-engage` | https://careers.microsoft.com/v2/global/en/students-and-graduates.html | `false` | `[]` | `None` | `false` |
| `flipkart-grid` | https://www.flipkartcareers.com/#!/joblist | `false` | `[]` | `None` | `false` |
| `uber-hacktag` | https://www.uber.com/in/en/careers/ | `false` | `[]` | `None` | `false` |
| `smart-india-hackathon` | https://www.sih.gov.in/ | `false` | `[]` | `None` | `false` |

## Unverified / needs checking

- All six new entries: Amazon HackOn, Amazon ML Summer School, Microsoft Engage, Flipkart GRiD, Uber HackTag, and Smart India Hackathon. Their official URLs were recorded, but no current cycle, date, stipend, or eligibility rule was verified; all date fields remain null and `verified` is false.
- Microsoft Engage may no longer have a current cycle; the entry is retained only as an explicitly unverified historical target.
- The Uber HackTag and Flipkart GRiD URLs are official company career portals, not programme-specific pages; programme existence and current cycle need direct checking.
- Existing rows with copied `study_year_min`/`study_year_max` values inherit those values from the pre-existing typed `eligibility` object. No official-page quote was available in the retained source data, so their new evidence fields remain null.
- Existing typical month strings were not converted to integers because changing them would violate the requirement to preserve every existing entry's existing data. They remain seasonal display hints, never countdown dates.

## Post-edit schema

`access_channel`, `deadline`, `degree_required`, `eligibility`, `enrolled_required`, `evidence`, `excluded_reason`, `grad_years_accepted`, `id`, `kind`, `name`, `needs_confirmation`, `note`, `official_url`, `opening_soon_ready`, `org`, `remote_tier`, `stipend_text`, `study_year_max`, `study_year_min`, `tags`, `typical_close_month`, `typical_open_month`, `verified`, `verify_status`, `window_note`
