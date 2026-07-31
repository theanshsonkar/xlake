# xlake — the collector

The engine behind Opportunity Lake. It finds early-career opportunities that an
Indian B.Tech student can actually apply to, worldwide, and keeps them in one
file that a website can filter in plain code.

Runs twice a day on GitHub Actions. No AI anywhere in this repo yet — every
number below comes from fetching and regex, which is deliberate: if the count is
near zero, no amount of model-based eligibility extraction would rescue it.

## How it works

```
enumerate_boards.py   Common Crawl -> every ATS board token that exists.
                      No company names are ever typed.

resolve.py            company domain -> board token, read off the careers page,
                      then verified by actually calling the board.

fetch.py              9 platform adapters. Full pagination, always.

filters.py            title + location -> keep/reject. Career stage, seniority,
                      technical relevance, three India buckets.

sweep.py              the 12-hourly run. Merges into jobs.json, never deletes.
```

## Board universe (measured 2026-07-31)

| Platform | Boards discoverable | Notes |
|---|---|---|
| Greenhouse | 3,600 | |
| Workable | 1,756 | |
| SmartRecruiters | ~640 | |
| **Keka (India)** | **311** | best India source found |
| Zoho Recruit (India) | 61 | adapter not written |
| Ashby | ~27 | Common Crawl barely covers it |
| Darwinbox (India) | 12 | adapter not written |
| Lever | 0 | readable, but robots.txt blocks Common Crawl |
| Workday | not yet enumerated | where the big companies are |

## What one sweep produced

512 boards (311 Keka + 201 Greenhouse), July — the seasonal trough:

```
12,609 postings seen
   909 early-career kept
   302 in India
    74 India + technical
    40 India + technical + unambiguous stage   <- 38 Keka, 2 Greenhouse
```

That 38-to-2 split is the point. Keka produces roughly 19x more India
early-career engineering roles than Greenhouse.

## Findings that contradicted the plan

- **Keka has a public JSON API.** `PRODUCT.md` records it as a dead end with no
  public JSON. The old adapter guessed the path and got an Angular shell. The
  real one is `/careers/api/embedjobs/{portalName}/active/{board_guid}`, and it
  returns full descriptions inline.
- **Workday was truncated at 200 postings.** The old loop was
  `for _page in range(10)` at `limit: 20`. Nvidia reports 2,000 and Adobe 839,
  so five big-company boards were read at 10% and recorded as complete.
- **A valid token on an abandoned board looks like a company that isn't
  hiring.** `ashby:vercel` returned HTTP 200 and an empty list forever; Vercel's
  real board is `greenhouse:vercel` with 80 jobs. Same for `lever:mistral`,
  which is actually `ashby:mistral.ai` with 171.
- **Lever is not enumerable from Common Crawl** — robots.txt disallows it, so
  the index holds only their robots.txt file.
- **schema.org JobPosting is not on Indian careers landing pages** — 0 of 18
  tested. Those pages are JS shells.

## Running it

```bash
# cheap local test — do this, not a full sweep
LAKE_LIMIT=20 LAKE_WORKERS=2 python3 sweep.py keka greenhouse

# filters have a test set built from real rejections
python3 filters.py

# one board
python3 fetch.py greenhouse vercel

# resolve some companies
python3 resolve.py --file companies_india.txt
```

Full sweeps belong on CI, not a laptop. `LAKE_WORKERS`, `LAKE_HOST_DELAY` and
`LAKE_LIMIT` control load.

## Rules the collector follows

- One request at a time per host, with a delay. Honest User-Agent with a contact
  address. `robots.txt` respected.
- LinkedIn and Naukri are never touched — their terms prohibit automated access
  and their postings are reposts of what the boards already give us.
- HTTP 200 with zero jobs is `empty`, not `dead`. Conflating them silently
  deletes companies.
- A partial fetch is always recorded as an error. A half-read board must never
  look complete.
- Nothing is deleted. A posting that disappears is marked `is_live: false` so it
  can never resurface as new.
- Never display a full job description; always link to the original posting.

## Next

1. Enumerate Workday — where the top companies are.
2. Finish Greenhouse: 201 boards swept of 3,600.
3. YC directory through the resolver — the only route to Lever and Ashby.
4. Zoho Recruit and Darwinbox adapters (73 Indian companies already enumerated).
5. Campus and graduate-programme pages (~40 URLs, weekly).
6. The programme calendar — GSoC, Outreachy, LFX, CERN, C4GT (~50 rows).
7. Only then: description download and AI eligibility extraction.
