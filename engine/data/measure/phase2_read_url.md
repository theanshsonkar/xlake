# Phase 2 universal URL reader verification

Date: 2026-08-04

## Required verification output

`env python3 filters.py` passed-lines (verbatim):

```
38 / 38 passed
33 / 33 passed
53 / 53 passed
18 / 18 passed
7 / 7 passed
7 / 7 passed
```

`env python3 read_url.py` self-test passed-lines (verbatim):

```
8 / 8 passed
7 / 7 passed
2 / 2 passed
```

Exit statuses:

- `env python3 filters.py`: 0
- `env python3 read_url.py`: 0
- `env python3 -m py_compile read_url.py filters.py sweep.py`: 0

## URL kinds supported

greenhouse, lever, ashby, keka, smartrecruiters, workable, workday,
successfactors, amazon.jobs, google_form, generic_html, pdf.

## Live end-to-end check

URL: https://job-boards.greenhouse.io/pdtpartners/jobs/1473516
fetch_state: `ok`

Result record (description truncated to 200 characters):

```json
{
  "kind": "job",
  "source_platform": "greenhouse",
  "source_board": "pdtpartners",
  "company": "Pdtpartners",
  "company_domain": "job-boards.greenhouse.io",
  "title": "Applied ML Scientist",
  "locations": [
    {"country": "", "state": "", "city": ""}
  ],
  "is_remote": false,
  "remote_scope": "",
  "url": "https://job-boards.greenhouse.io/pdtpartners/jobs/1473516",
  "alt_urls": [],
  "posted_on": "2026-07-24T15:05:09-04:00",
  "deadline": "",
  "description": "PDT, a quantitative investment manager, is hiring problem solvers who blend programming and applied research experience. Individuals in this role will devise, implement, evaluate, and iterate to creat",
  "stage": "unknown",
  "stage_title": "unknown",
  "stage_resolved": "unknown",
  "technical": true,
  "discipline": "cse",
  "eligibility": {
    "batch_years": [],
    "experience_min": null,
    "experience_max": null,
    "degree_required": ["PhD", "Master's"],
    "enrolled_required": null,
    "evidence": {
      "degree": "PhD; Masters",
      "experience_requirement": "30+ year",
      "experience_requirement_2": "2+ years"
    },
    "gates_found": ["degree"],
    "gates_missing": ["experience", "fresher", "stage_early", "batch_years", "enrolled"]
  },
  "trust": "trusted",
  "trust_reasons": ["known_public_ats_or_company_job_domain"],
  "hidden_reason": "not_india",
  "eligibility_status": "hidden",
  "first_seen": "2026-08-04T03:40:51+00:00",
  "last_seen": "2026-08-04T03:40:51+00:00",
  "is_live": true,
  "fetch_state": "ok"
}
```

## Known gaps and assumptions

- PDF content is detected but not parsed; it returns `fetch_state=needs_pdf_reader` and `needs_pdf_reader=true`.
- The AI fallback hook is present and explicitly not called in Phase 2; no AI/LLM request is made.
- Known ATS detail URLs use clean JSON/API routes where available; Keka and Workable fall back to their existing board adapters, then the original HTML page when no matching board posting is found.
- SmartRecruiters API access remains subject to the existing robots policy; a disallowed request is recorded as `robots_disallowed`, never as empty or successful.
- Unrecognised domains are classified as `generic_html` and always receive `low_trust`; Google Forms are always `low_trust` independently of eligibility status.
- The CLI record description is capped at 200 characters after extraction so a full job description is never displayed; the original URL remains the source of truth.
