# Phase 0 acceptance gate

Date: 2026-08-04

Exact command actually run (working directory `/Users/anshsonkar/opportunity-lake/engine`):

```sh
env LAKE_LIMIT=20 LAKE_WORKERS=2 python3 sweep.py keka greenhouse
```

The requested shell form was equivalent to running this from the engine directory. `sweep.py` only parses `--segment`; the positional `keka greenhouse` arguments are ignored. Therefore the actual run was the first 20 entries of `registry.json`, not a keka/greenhouse-only selection.

## Run 1

| metric | value |
|---|---:|
| boards swept | 20 |
| ok | 19 |
| empty | 0 |
| error | 1 |
| truncated | 0 |
| postings | 16,262 |
| kept, pre-dedupe | 8,003 |
| boards read without error | 19 |
| deduped jobs store rows after merge | 9,385 |

Failure: `sitemap_IncompleteRead: IncompleteRead(3 1` (one board; it was not added to `boards_read`).

Boards actually swept, in registry order:

| platform | board/token | company |
|---|---|---|
| successfactors | `careers.wipro.com` | Wipro |
| workday | `accenture.wd103.myworkdayjobs.com|accenture|AccentureCareers` | Accenture |
| successfactors | `jobs.sap.com` | SAP |
| workday | `intel.wd1.myworkdayjobs.com|intel|External` | Intel |
| workday | `target.wd5.myworkdayjobs.com|target|targetcareers` | Target |
| workday | `visa.wd5.myworkdayjobs.com|visa|Visa` | Visa |
| workday | `citi.wd5.myworkdayjobs.com|citi|2` | Citi |
| workday | `philips.wd3.myworkdayjobs.com|philips|jobs-and-careers` | Philips |
| eightfold | `micron|micron.com` | Micron |
| workday | `redhat.wd5.myworkdayjobs.com|redhat|jobs` | Red Hat |
| lever | `palantir` | Palantir |
| workday | `expedia.wd108.myworkdayjobs.com|expedia|search` | Expedia |
| lever | `paytm` | Paytm |
| greenhouse | `razorpaysoftwareprivatelimited` | Razorpay |
| workday | `browserstack.wd3.myworkdayjobs.com|browserstack|External` | BrowserStack |
| greenhouse | `druva` | Druva |
| greenhouse | `netskope` | Netskope |
| lever | `mindtickle` | MindTickle |
| ashby | `sarvam` | Sarvam AI |
| keka | `jupiter` | Jupiter |

### Sweep stdout tail

```text
   lake: 9385 rows total, 8340 live, 198 surfaced, 820 newly dead
   lake: 9218 rows total, 8666 live, 225 surfaced, 499 newly dead

========================================================================
SWEEP REPORT   2026-08-04T14:47:02+00:00   (2023.6s)
========================================================================
boards: 20  ok=19 empty=0 failed=1 truncated=0
postings seen : 16262
kept (pre-dedupe) : 8003
boards read without error (liveness-eligible) : 19

early-career kept (deduped) : 9385
  by stage                  : {'early': 1372, 'unknown': 8013}
  by location bucket        : {'global_hiring': 7992, 'india_located': 1392, 'india_remote': 1}
  technical / non / unknown : 4551 / 2230 / 2604
  india early-career         : 1393  (technical: 563)

failure modes:
  sitemap_IncompleteRead: IncompleteRead(3 1

hygiene (flagged, never deleted)
  staffing agencies         : -0
  duplicate titles          : -3628
  over per-company cap      : -5541
  stale (>180 days)          : -146
  pay-to-intern             : -0
  surfaced                  : 198 rows across 24 companies
```

## C1-C8 verdicts

| check | verdict | evidence |
|---|---|---|
| C1 ARTIFACTS | PASS | `jobs.json` exists, 19,873,583 bytes, 9,385 rows; `hidden.json` exists, 14,295,688 bytes, 9,218 rows; `runs.jsonl` exists, 4,643 bytes, 3 records. |
| C2 RUN RECORD | PASS | Latest record contains every required key; full key list and requested values are quoted below. |
| C3 STORE SEPARATION | FAIL | 6 shared `(platform, token, job_id)` identities and 1 shared normalized URL occur in both stores; required count is zero. |
| C4 HIDDEN ROW COMPLETENESS | FAIL | In all three deterministic sample rows, required keys are present, but `eligibility_evidence` and `gates_found` are present as empty lists; `technical` is present as explicit `false`. |
| C5 DESCRIPTION CONTAINMENT | PASS | Longest string is 238 characters in `hidden.json` (a URL) and 25 in `runs.jsonl` (a timestamp); 8,504 hidden rows have a `description` key but all values are empty, with no description prose; no public output directory found. |
| C6 DEDUPE | PASS | Duplicate `_key` values inside `jobs.json`: 0; current run was 16,262 raw postings / 8,003 pre-dedupe kept, with 9,385 stored rows including prior history. 823 possible same-company/normalized-title groups are reported as review candidates below. |
| C7 GATES ON REAL DATA | PASS | Eligibility and gate distributions were countable over all 9,385 `jobs.json` rows; live gate counts are reported below, including `batch_years: 0`. |
| C8 OFFLINE MERGE/LIVENESS | PASS | Temporary-path three-call test retained the missing row, set `is_live=false` and `went_dead_at`, preserved every surviving `first_seen` exactly, then restored `is_live=true` while retaining `went_dead_at`. |

### C2 run-record evidence

Full key list from the latest `runs.jsonl` record:

```text
['ts', 'seconds', 'entries_swept', 'boards_read_ok', 'totals', 'failure_modes', 'kept_total', 'by_stage', 'by_bucket', 'technical', 'non_technical', 'unclassified', 'filtered_out', 'hidden', 'visible_total', 'by_stage_resolved', 'stage_resolved_changed', 'experience_stated', 'experience_conflicts', 'by_eligibility_status', 'worth_checking_total', 'india_early_career', 'india_early_career_technical', 'quality']
```

Requested values:

```json
{
  "filtered_out": {"total": 8259, "by_reason": {"senior": 8224, "no_title": 25, "not_india": 10}},
  "hidden": {"total": 8214, "by_reason": {"not_india": 7861, "non_technical": 173, "senior": 171, "experience_3plus": 9}},
  "visible_total": 1171,
  "by_stage_resolved": {"early": 1404, "unknown": 7810, "senior": 171},
  "stage_resolved_changed": 207,
  "experience_stated": 287,
  "experience_conflicts": 23,
  "by_eligibility_status": {"hidden": 8214, "confirmed": 494, "rules_unclear": 677},
  "worth_checking_total": 677
}
```

### C4 sample evidence

The first three rows in `hidden.json` were sampled. For each sample, these fields were present and non-empty: `url`, `title`, `company_name`, `stage`, `stage_title`, `stage_resolved`, `discipline`, `location_bucket`, `hidden_reason`, `gates_missing`, `eligibility_status`, `first_seen`, `last_seen`, and `is_live`. `technical` was present with explicit boolean value `false` in each sample. `eligibility_evidence` and `gates_found` were present but empty lists in each sample, which makes C4 FAIL under the requested non-empty test.

Hidden reason distribution:

```json
{"senior": 9203, "no_title": 5, "not_india": 10}
```

Sample identities:

1. `successfactors / careers.wipro.com / 1166854955`
2. `successfactors / careers.wipro.com / 1341790755`
3. `successfactors / careers.wipro.com / 1337156755`

### C5 evidence

- Longest string in `hidden.json`: 238 characters, at `[4901].url`.
- Longest string in `runs.jsonl`: 25 characters, at `[2].ts`.
- `hidden.json` description keys: 8,504; non-empty description values: 0; maximum description value length: 0.
- `runs.jsonl` has no `description` key.
- Public output directories checked: `engine/public`, `engine/data/public`, `engine/output`, and `engine/data/output`; none exists.

### C6 evidence

- Duplicate dedupe keys in `jobs.json`: 0 duplicate keys and 0 duplicate rows.
- Run volume: 16,262 raw postings -> 8,003 kept before dedupe; the merged `jobs.json` contains 9,385 rows because it already contained history before this run.
- Possible same-company plus `quality.normalise_title` candidates: 823 groups. Examples (these are reported candidates, not counted as duplicate `_key` failures):
  1. Accenture / `custom software engineer`: Hyderabad, Chennai, Bengaluru URLs.
  2. Target / `target security specialist`: three distinct US location URLs.
  3. Wipro / `production agent l1`: three distinct Chennai URLs.

### C7 evidence

Eligibility status over all `jobs.json` rows:

```json
{"hidden": 8214, "confirmed": 494, "rules_unclear": 677}
```

Gate firing counts over all `jobs.json` rows:

```json
{
  "batch_years": 0,
  "experience": 287,
  "degree": 354,
  "enrolled": 70,
  "fresher": 51,
  "stage_early": 1372
}
```

### C8 evidence

The three calls used a synthetic three-row set at a `tempfile.TemporaryDirectory` path and never used a real store path:

```json
{
  "missing_row_still_present_b": true,
  "missing_row_is_live_false_b": true,
  "missing_row_went_dead_at_set_b": true,
  "surviving_first_seen_byte_identical": true,
  "c_is_live_job2": true,
  "c_went_dead_at_job2": "2026-08-04T15:08:18+00:00",
  "c_restores_live_but_retains_went_dead_at": true,
  "PASS": true
}
```

## FAILURES AND WHAT THEY IMPLY

- The stated clean-slate precondition was false: `jobs.json`, `hidden.json`, and `runs.jsonl` existed before this acceptance run. The measured stores therefore include prior history; this run merged into existing artifacts rather than measuring an empty first run.
- Positional `keka greenhouse` arguments are ignored by `sweep.py`; the actual 20-board sample included successfactors, workday, eightfold, lever, greenhouse, ashby, and keka boards. It was not a keka/greenhouse-only sample.
- C3 failed: six platform/token/job-id identities and one URL are present in both public and hidden stores. Public and private store separation is not true for the resulting artifacts.
- C4 failed: the three sampled hidden rows contain empty `eligibility_evidence` and `gates_found` lists, despite those keys being present. The sampled hidden-row records do not satisfy the requested non-empty completeness condition.
- One board fetch returned `sitemap_IncompleteRead` and was recorded as an error; it was not included in `boards_read`, so its rows were not eligible for board-scoped dead marking.
- C6 reports 823 possible same-company/normalized-title groups for review, while exact `_key` dedupe remains zero. These candidates are not counted as exact-key duplicates in the C6 verdict.

GATE VERDICT: FAIL
