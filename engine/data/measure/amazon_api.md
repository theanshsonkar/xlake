# Amazon jobs API probe

Date: 2026-08-04
Endpoint: `https://www.amazon.jobs/search.json`

All seven requests returned HTTP 200; no HTTP error occurred. Requests used the requested User-Agent and two seconds between calls.

## Required query

`base_query=University Talent Acquisition`, `country=IND`, `result_limit=20`, `offset=0` returned top-level keys: `error`, `hits`, `facets`, `content`, `jobs`, `job_posting_search_request`. `hits` was **7** and `jobs` contained 7 objects.

One job object had exactly these fields: `basic_qualifications`, `business_category`, `city`, `company_name`, `country_code`, `description`, `department_cost_center`, `description_short`, `display_distance`, `id`, `id_icims`, `is_intern`, `is_manager`, `job_category`, `job_family`, `job_function_id`, `job_path`, `job_schedule_type`, `location`, `locations`, `normalized_location`, `optional_search_labels`, `posted_date`, `preferred_qualifications`, `primary_search_label`, `source_system`, `state`, `title`, `university_job`, `updated_time`, `url_next_step`, `team`.

The response includes a full `description`, not only a snippet; `description_short` is also present. It includes `id_icims` (not `job_id`), `title`, `location` as a single string, `locations` as a list, and `posted_date`. Category/team fields are `business_category`, `job_category`, `job_family`, `primary_search_label`, and `team`.

## Search and pagination checks

- The requested requisition was **NO**: neither `SDE I Intern` nor `University Talent Acquisition` returned it. `SDE I Intern` returned 0 hits at offsets 0 (requested with limit 100) and 100; University returned 7 hits at offset 0 and no jobs at offsets 20 and 100.
- `base_query=intern`, `country=IND`: **13** total hits.
- `base_query=` (empty), `country=IND`: **2,625** total hits.
- Offset pagination works: offset 20 returned a different result from offset 0 (the first page had 7 jobs; offset 20 had none, with zero overlap).

## Adapter verdict

This is a viable adapter: the endpoint is public, paginated, and supplies IDs, titles, locations, dates, categories, and full descriptions. It does **not** surface the hidden requisition through the tested searches. India volume is **2,625** total roles, of which **13** matched `intern` and **7** matched `University Talent Acquisition` at probe time. For one returned job, category values were `job_category=Human Resources`, `job_family=Human Resources`, `business_category=global-corporate`, and `team.label=team-hr-for-hr`; these appear useful but should be treated as source metadata rather than an eligibility guarantee.
