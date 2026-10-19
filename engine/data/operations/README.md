# Operations data

This directory contains resolver inputs/snapshots, run and tier state, and
page-reader processing outputs. `pagereader_rows.json` is an operational
processing/compatibility output, not a second final opportunity lake. The only
canonical final user-facing stores are `../lake/opportunities.json` and its
retained non-default companion `../lake/hidden.json`.

## Hand-verified programme records
`*_programme_verifications.json` records that carry `recheck_after` are hand-verified
(`verified_by: "manual"`). Every asserted fact (status, dates, funding, eligibility,
programme dates) needs `official_evidence.<key> = {quote, url}`. On each run
`recheck_official_urls` re-fetches `official_url` (404/410, or with `recheck_quote`
no evidence quote on the page, flags it); a flagged or past-`recheck_after` record
becomes `programme_status: needs_confirmation` with `verification_flag` set.
