# Handoff prompt — paste this into a new chat

---

I'm building **Opportunity Lake**: a site where an Indian B.Tech student drops a
resume and gets back only opportunities they're actually eligible for — jobs,
internships, apprenticeships, fellowships, OSS programmes, research programmes,
grants. Worldwide, India first. Three screens. Never auto-apply.

The collector engine lives at `github.com/theanshsonkar/xlake` (private) and
locally at `~/opportunity-lake`. Read `README.md`, `LAKE.md`, then `PRODUCT.md`.

**Everything below was measured on 2026-07-31, not assumed. Don't re-derive it.**

## What is built and working

```
enumerate_boards.py   Common Crawl -> board tokens. No company names typed.
resolve.py            company domain -> board token, then verified by calling it.
fetch.py              9 adapters: greenhouse lever ashby smartrecruiters
                      workable workday personio recruitee keka. Full pagination.
filters.py            title+location -> keep/reject. 22-case test set, passing.
sweep.py              the 12h run. Merges into jobs.json, never deletes.
.github/workflows/sweep.yml   runs 06:30 + 18:30 IST on GitHub Actions.
```

No AI anywhere yet. That is deliberate: if the counts are near zero, no model
would have rescued them.

## Measured results

Board universe discoverable from Common Crawl, zero company names typed:

| Platform | Boards | State |
|---|---|---|
| Greenhouse | 3,600 | only 201 enumerated into cache so far |
| Workable | 1,756 | enumerated |
| SmartRecruiters | ~640 | needs re-enumeration, cache was lost |
| Keka (India) | 311 | enumerated, adapter written |
| Zoho Recruit (India) | 61 | enumerated, **no adapter** |
| Ashby | ~27 | CC barely crawls it |
| Darwinbox (India) | 12 | enumerated, **no adapter** |
| Lever | 0 | robots.txt blocks CC entirely |
| Workday | **never enumerated** | where top companies are |

Last full CI sweep — 2,340 boards, 20.6 minutes:

```
45,188 postings seen
 1,215 early-career kept (deduped)
   215 in India
    74 India + technical
    40 India + technical + unambiguous stage   <- 38 Keka, 2 Greenhouse
```

That 38-to-2 split is the core finding: Keka yields ~19x more India
early-career engineering roles than Greenhouse.

## Discoveries that contradict the older docs

- **Keka has a public JSON API.** `PRODUCT.md` §3.3 calls it a dead end with no
  public JSON. Wrong. Chain: fetch `https://{tenant}.keka.com/careers/`, regex
  the board GUID out of the page shell, then call
  `/careers/api/embedjobs/default/active/{guid}`. Returns full descriptions
  inline — one request for both list and text, better than Greenhouse.
- **Workday was truncated at 200 postings.** Old loop was
  `for _page in range(10)` at `limit: 20`. Nvidia reports 2,000, Adobe 839.
- **A valid token on an abandoned board is indistinguishable from a company
  that isn't hiring.** `ashby:vercel` returns 200 + empty forever; the real
  board is `greenhouse:vercel` (80 jobs). `lever:mistral` is really
  `ashby:mistral.ai` (171 jobs).
- **Citadel is genuinely dead** (HTTP 404), so REGISTRY-PLAN's plan to
  reclassify it as `empty` is wrong — re-resolve it instead.
- **Lever is not enumerable from Common Crawl** (robots.txt).
- **schema.org JobPosting is absent from Indian careers landing pages** — 0 of
  18 tested. They're JS shells.
- **Competitor check (useastra.in, ₹699 lifetime):** same ATS sources, but page
  1 of 110 had zero student-applicable roles (Senior/Staff/Managing Counsel/
  Payroll Lead Belgium), "Posted 4 hours ago" on every row (scrape time, not
  posting time), INR salary bands on Sweden-remote roles, and two Remote.com
  entries that literally say "This is not an active job opening."

## Open issues, by priority

### A. Data quality — do these first, they make every later number trustworthy
1. **One company is 25% of the lake.** `kiavets` (Workable) posted 311
   near-identical roles across locations. Need a per-company cap and
   duplicate-title collapse. Capping at 10/company: 1,215 -> 853 rows.
2. **Staffing agencies pollute results** — mediix-recruitment, cesna-group,
   alkujobs, classet, peoplelogic, americanchase. They post for unnamed
   clients, which the project's own rules ban. Need a recruiter filter.
3. **54% of rows (659/1,215) are technically unclassified.** `filters.py`
   pattern lists don't cover enough title vocabulary.
4. **Bare titles carry no signal** — "Intern", "Trainee", "Campus Hiring 2025".
   Only the description can classify these.
5. **Location strings are unparsed blobs** from Keka, e.g.
   "Bangalore Bengaluru KA Hyderabad HYD".
6. **Same company appears twice** across tokens (alphasense + alphasenseindia).

### B. Coverage
7. **Workable 429s.** 522 of 1,755 boards rate-limited; only 41% read. Needs
   longer backoff and lower per-host concurrency. Biggest single coverage loss.
8. **Zoho Recruit + Darwinbox adapters** — 73 Indian companies already
   enumerated, returning nothing. Keka proved the method: read the page's JS,
   find the API it calls.
9. **Enumerate Workday** — top companies and their India offices. Adapter
   already works. Tokens are `host|tenant|site`.
10. **Finish Greenhouse** — 201 of 3,600 cached. Common Crawl throttles, so the
    enumerator needs to be slow and resumable.
11. **Keka `no_board_guid` on 54 of 311 tenants** — a second portal template.
12. **Lever + Ashby need the YC directory through the resolver** — the only
    route, since CC can't see them.
13. **Bespoke careers pages** — 39% of Indian companies, no mechanism yet.

### C. The product doesn't exist yet
14. **No eligibility extraction at all.** No descriptions downloaded, no
    graduation-window / experience-ceiling / degree parsing. The eligibility
    pass card has no data behind it. This is the actual differentiator.
15. **Programme calendar entirely absent** — GSoC, Outreachy, LFX, CERN, C4GT,
    IAS SRFP, ISRO. ~50 rows typed once. The only uncontested part of the
    product, and it needs no scraping. Rule: the model may READ a fetched page,
    never RECALL a date.
16. **Campus / graduate-programme pages absent** — ~40 URLs (Qualcomm, Google,
    Microsoft, Goldman India pipelines). The only two roles ever actually
    applied to in the private system came from here.
17. **Liveness never verified.** `is_live` logic is written but no two sweeps
    have been compared, so the ID-diff is unproven.
18. **No accuracy measurement.** No false-eligible or false-ineligible rate.
    `filters.py`'s test set is 22 cases I wrote myself, not an audit.

### D. Operational
19. **CI budget.** 20.6 min/sweep x 2/day = 1,234 of 2,000 free minutes/month,
    while reading only 201 Greenhouse boards and 41% of Workable. Full
    enumeration would exceed the free tier. **Board tiering (hot/warm/cold by
    yield) is now mandatory arithmetic, not a nice-to-have.**
20. **No board registry persisted.** `sweep.py` doesn't record per-board
    verified/empty/dead/abandoned state between runs.
21. **No alerting on the silent-death signal** — a board that returned 40 roles
    last week and 0 today raises no exception and returns HTTP 200 forever.
22. **Docs debt.** `PRODUCT.md` and `REGISTRY-PLAN.md` still assert Keka has no
    JSON, that Lever is enumerable, and that the registry is 65 curated boards.

## Rules that must not be broken

- **Never LinkedIn or Naukri.** Terms prohibit automated access, they enforce
  it, their posts are reposts of what the boards already give us, and you can't
  verify eligibility from a LinkedIn post. Attribution does not cure a ToS
  breach.
- One request at a time per host with a delay. Honest User-Agent with a contact
  address. Respect robots.txt.
- HTTP 200 with zero jobs is `empty`, never `dead`.
- A partial fetch is always recorded as an error. A half-read board must never
  look complete.
- Nothing is deleted. A vanished posting is `is_live: false`, kept forever.
- Never display a full job description. Link to the original.
- Never auto-apply. Never restate a graduation year to fit a posting.
- Never infer a deadline or a countdown. Never let a model recall a date.
- No AI call may ever happen because a user visited. All extraction happens
  once per posting version at collect time and is reused by everyone.
- Full sweeps run on CI, never on the laptop. Locally use
  `LAKE_LIMIT=20 LAKE_WORKERS=2`.

## What I want from you

Start with section A (data quality), then B7 and B8 (Workable 429s, Zoho +
Darwinbox adapters), then C15 (programme calendar). Verify every claim against
live endpoints rather than trusting the docs — six real bugs in this project
were found that way and none were visible from reading code.

Tell me when a number I'm relying on is wrong.
