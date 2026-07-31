# The Lake — what a run must find

**Status:** working document. Sections marked **DECIDE** are open and meant to be argued out.
**Scope:** this file covers only the collector — what goes looking, what it must come back with, and how we know a run worked. Nothing about the website. `PRODUCT.md` is frozen; this is the live one.
**Updated:** 2026-07-31

---

## 0. The point of the lake

One store of every opportunity we have ever seen, with enough facts attached that a website can filter it in plain code and never call a model.

The lake is built by machines on a schedule. Nobody visits it. Everything expensive happens here, once per opportunity, and is reused by every user forever.

**The single number a run exists to produce:**

> How many opportunities are open right now that an Indian B.Tech student can actually apply to?

Everything else in this document is either how we get that number or how we tell it is wrong.

We do not have this number. Not a guess, not an estimate from a 22-board sample — nobody knows it. It is currently July, the seasonal trough, so whatever the first run says is a floor and not a verdict.

---

## 1. What counts as a find

A row is worth keeping only if all of these are true. This is the acceptance test, and the collector should refuse rows that fail it rather than storing them half-filled.

**Must have:**

- a company or organisation name
- an exact title, as published
- an official application link — the employer's own board or page
- a location string, as published
- a source: which platform and which token or URL it came from
- `first_seen`, `last_seen`, `is_live`

**Must pass the career-stage test:** intern, new grad, trainee, apprentice, graduate programme, fellow, or a role with no experience requirement. Not SDE II, Senior, Staff, Principal, Lead, Manager, Director, Architect.

**Must pass one of three location tests:**

| Bucket | Test |
|---|---|
| `india_located` | Bengaluru, Hyderabad, Pune, Delhi-NCR, Gurugram, Noida, Mumbai, Chennai, Kolkata, Ahmedabad, Kochi, Indore, Jaipur, Coimbatore, Thiruvananthapuram, Bhubaneswar, Chandigarh, or plain "India" |
| `india_remote` | `worldwide`, `global remote`, `work from anywhere`, or India named in the permitted list |
| `global_hiring` | genuinely remote with no countries stated, or overseas with no work-authorisation bar |

**Rejected outright:** aggregator links (LinkedIn, Naukri, Indeed reposts), dead pages, anything behind a login, and remote roles restricted to a named region that excludes India.

Anything we cannot confirm goes to an explicit unverified list with the one thing a human would need to check. It does not get stored as a find.

---

## 2. Three clocks, not one

The biggest thing to get right. "Run every 12 hours" is only correct for one of the four things we look for. Different sources change at wildly different speeds, and sweeping them all on the fast clock wastes the entire budget on pages that change once a year.

### Every 12 hours — the fast loop

Board job-ID lists. One request per board returns every open job ID at that company.

- **New IDs** → fetch the description, extract facts, insert.
- **Missing IDs** → the posting is gone. Mark `is_live: false`. This is the liveness check and it needs no description download and no model.
- **Unchanged IDs** → touch `last_verified_live`, do nothing else.

This is where new jobs and internships appear, and it is the only loop that needs to be fast. Postings go up and come down daily.

### Every week — the slow loop

Pages that have no API and change on a scale of months.

- ~40 campus and graduate-programme pages of global employers hiring in India
- Indian ATS pages (Keka, Darwinbox, Zoho) which are HTML only
- ~50 programme pages — fellowships, OSS programmes, research
- a re-read of live job descriptions to catch silent edits (a company quietly changing "2026 graduates" to "2027")

Fetch, hash the text, and only if the hash moved does anything else happen.

### Every season — the calendar loop

Programmes recur on an annual cycle. GSoC opens in roughly the same weeks every year. This loop is not a sweep at all; it is a check that each programme's stored window still matches its official page, and a flag when a window is about to open.

**Hard rule, no exceptions:** dates come from a fetched page, never from model memory. Ask a model when GSoC 2027 opens and it will invent a confident answer. A wrong programme deadline is worse than no deadline, because the user trusts it, misses the real one, and has no way to discover the error. Every programme row carries `last_verified` and shows it.

**DECIDE — is 12 hours even right for the fast loop?** Twice a day is 2 sweeps/day instead of 4, which halves compute and roughly halves how quickly we notice a new posting. Given that "posted 2 days ago" is the freshness claim and not "posted 4 hours ago", 12h looks correct. But if the pitch becomes speed-to-apply, 6h matters.

---

## 3. What we go looking for, by type

Eight types. They do not share a shape, and that is why one filter cannot serve all of them.

### 3.1 Jobs — new grad, SDE I, Associate, Analyst

Where: ATS boards, fast loop.
Gate shape: mechanical. Graduation year, experience ceiling, degree.
Deadlines: none. Companies just take the posting down, which is why liveness matters more than deadlines here.
Volume: highest of any type.
Honest note: this is the one type where broad-coverage competitors beat us outright. Surface it well, do not try to win on it.

### 3.2 Internships

Where: same boards, same loop.
Gate shape: same as jobs, plus current enrolment.
**Seasonal.** Summer-2027 internships post roughly August–November 2026. Outside that window there is nothing to find no matter how many boards we sweep. A zero count in July is a fact about the calendar, not a fact about our coverage — and the collector should record the run date so the October comparison is possible.

### 3.3 Apprenticeships, graduate programmes, "Emerging Talent"

Where: partly ATS, partly bespoke company pages. Both loops.
Gate shape: the awkward one. These carry **real deadlines**, and they carry a **cohort start date that can conflict with graduation** — a programme starting March 2027 is not open to someone graduating May 2027. This is the only type where a start date is an eligibility gate.
Titles avoid the obvious words: *Explore Program*, *Emerging Talent*, *Graduate Engineer Trainee*, *Apprentice*, *Early Career Program*. Searching for `intern` misses all of them.

### 3.4 Open-source programmes

GSoC, Outreachy, LFX Mentorship, MLH Fellowship, C4GT / Dedicated Mentoring Programme, Season of Docs, Hacktoberfest-adjacent programmes.
Where: programme pages, slow + calendar loop.
Gate shape: currently enrolled, sometimes region-excluded, sometimes requires prior participation.
**Structurally two levels:** the programme has one deadline, but you apply to a specific organisation and project inside it — GSoC alone has ~200 orgs. We track the programme and its window and link to the org list. Matching against orgs is a separate feature, later.

### 3.5 Fellowships

CERN Technical Student and Openlab, DAAD RISE, university "Explore"-style fellowships, policy and research fellowships.
Gate shape: enrolment, and frequently **nationality** — CERN is member-state gated. Nationality is a gate no job posting has, and it is the one most likely to waste a student's time.

### 3.6 Research programmes

IAS Summer Research Fellowship, IIT and IISc summer research, ISRO Student Project Trainee, MITACS Globalink, ETH/EPFL summer research, Max Planck.
Where: university and lab pages, slow loop.
Gate shape: enrolment year, marks, sometimes a faculty recommendation. Hard annual deadlines.
~15 that matter, and the Indian ones are mainstream for this audience, not obscure.

### 3.7 Grants

Gate shape: different in kind. A grant does not ask *are you eligible*, it asks *does your work fit the theme* — and it gates on **artifacts you already have**: an existing open-source project, a publication, a registered organisation. Those are booleans, which is cheap to check, but confirming a grant is genuinely open is slow manual work.

**DECIDE — grants in the first lake or not?** They are the fewest rows and the hardest to verify. The argument for including them anyway is that they are completely uncontested and a student with a real project is exactly who they are for.

### 3.8 Scholarships

Not in `PRODUCT.md` at all — new to this list, and the type furthest from everything else.
Where: national and state portals, university pages, private foundations. No ATS, no consistent shape.
Gate shape: unlike every other type, the gates are **financial and demographic** — family income, category, state of domicile, marks, sometimes gender. A resume does not contain any of that.

**DECIDE — do scholarships belong here?** They are genuinely wanted and genuinely useful, but they would need fields no other type uses and questions we would have to ask the user directly rather than parse. My read: they are a second product wearing the same coat. Worth naming the cost before deciding.

---

## 4. Where we go looking

Ordered by how much work each is versus what it returns. Yields are unknown for all of them — that is the point of the first run.

| Source | Reaches | Loop | Effort | Known yield |
|---|---|---|---|---|
| The 8 supported ATS platforms | any company on Greenhouse, Lever, Ashby, SmartRecruiters, Workable, Workday, Personio, Recruitee | 12h | already built | **currently near zero for India — see §5** |
| Campus / graduate-programme pages | India early-career pipelines of Qualcomm, Google, Microsoft, Amazon, Adobe, Nvidia, Salesforce, Uber, Walmart, Cisco, Goldman Sachs, JPMorgan, Standard Chartered, Wells Fargo | weekly | ~40 URLs, one-time | **the only two roles ever actually applied to came from here** |
| Indian ATS as HTML | Indian startups on Keka, Darwinbox, Zoho Recruit | weekly | one day per platform to learn the shape | unknown, likely the best India source |
| Programme pages | everything in §3.4–3.7 | weekly + calendar | ~50 rows typed once | uncontested, and delivers value at ~20 rows |
| Company-name harvest | YC directory, and Indian startup lists | weekly | needs the resolver | grows the board list unattended |

**Excluded on purpose:** LinkedIn and Naukri. Their terms prohibit automated access, both have enforcement history, and their companies appear via the boards anyway. Never any logged-in content.

---

## 5. What the current registry actually does, measured today

This is the uncomfortable part and it should stay in the document.

The existing registry holds **65 verified boards and 3 dead**. A 22-board sample returned 4,338 jobs, of which 316 were India-located, of which 12 were early-career, of which **zero were engineering** — they were HR, sales, content, graphic design, video editing, billing and support. A live agent pass over all 65 boards the same day screened 116 early-career postings and returned zero India-compatible results.

The reason is not the mechanism. It is that 35 of the 65 boards are US AI startups. The registry was asked for US companies, so it returns US roles.

**And the measurement itself is partly broken.** Four bugs found by hitting the live endpoints on 2026-07-31, none of which were visible from reading the code or the docs:

| Bug | Evidence | Consequence |
|---|---|---|
| **Workday truncated at 200** | Nvidia's board reports `total: 2000`, Adobe `839`; the registry records `200` for Adobe, Nvidia, Salesforce, Workday and eBay | ~90% of Nvidia's postings never seen. Pulling postings 200–400 found **12 more India-located roles** — all senior-titled in the sample checked, so this does not yet prove hidden early-career roles exist. What it does prove is that the India count was never measured against the full board. These are exactly the big companies with large India offices, so "zero India roles" is not a trustworthy finding until pagination is fixed |
| **Wrong platform, silently empty** | registry has `ashby:vercel` → 0 jobs; Vercel's real board is `greenhouse:vercel` → **80 jobs**. Same class of error for `lever:mistral`, whose careers page points at Ashby | a valid token on an abandoned board looks identical to a company that is not hiring |
| **Citadel is genuinely dead, not empty** | recorded as `dead` with `error: no_jobs` but `http_status: 404`, confirmed 404 today | the plan to reclassify it as `empty` would re-add a wrong token. The fix is to re-resolve it |
| **A duplicate** | ClickHouse appears on both Greenhouse and Ashby with the same count | double-counting |

**The lesson worth carrying:** three registry bugs were found by reasoning about the docs, and three more were found in thirty minutes of hitting real endpoints. From here, new information comes from data.

### 5.1 A fourth board state we do not currently have

Today a board is `verified`, `empty`, or `dead`. Vercel and Mistral fit none of them: the token works, returns HTTP 200, returns an empty list — forever, because the company moved to a different platform.

Calling that `empty` means re-sweeping it twice a day for years while believing we have coverage of a company we cannot see. That is worse than `dead`, because `dead` is honest.

**Proposal:** a board returning 200-with-zero-jobs for N consecutive sweeps gets re-resolved from the company's careers page rather than swept again.

**DECIDE — what is N?** Boards do legitimately empty out for weeks. 14 days feels right; a hiring freeze is real and we should not thrash.

---

## 6. Who does what — scripts versus AI

The cost of the whole product is decided here. The rule is that **no model call may ever happen because a user visited.** Every model call happens once, at collect time, and its answer is stored and reused forever.

### Scripts only. Never a model.

Fetching. Pagination. Diffing job-ID lists for liveness. Dedupe by normalised URL. Seniority from title. `3+ years` patterns. Explicit graduation-year lists. Deadline dates that are printed as dates. Location bucketing. Hashing. Ranking. Filtering. All date arithmetic.

This is roughly three quarters of every decision, it is free, it is instant, and it cannot hallucinate.

### Where a model is genuinely needed

1. **Reading a job description for eligibility gates** — once per posting *version*. Runs when the posting enters the lake, and again only if its text actually changed. Output is a strict JSON schema, and every extracted fact carries the sentence it came from.
2. **Reading pages that have no API** — campus pages, Keka/Darwinbox/Zoho, programme pages. Only when the page's hash changes. Roughly 90 pages checked weekly, so a few hundred calls a month.
3. **Classifying company size** — once per company, ever.
4. **Embedding the skills text** — once per posting version.

That is the whole list for the collector. Two more calls exist on the website side, per visitor, and they do not grow with the size of the lake.

### What a model is never allowed to do

- recall a date it was not shown on a page
- guess a board token
- infer a deadline that the posting does not state
- decide whether a posting is live
- decide whether a form submission means someone is eligible

### The one number that decides the bill

How many new postings per day get past the script layer and need a model call. Write the patterns properly and this stays small. At roughly a cent per posting judged, a few hundred new postings a day is a few dollars a day, and it does not change when a thousand users arrive.

---

## 7. What a run reports

A run that finds nothing and a run that is broken look identical unless it says so. Every run appends one record:

```
timestamp, run_type (fast | slow | calendar)
boards_swept, boards_ok, boards_zero, boards_failed
ids_seen, ids_new, ids_disappeared
postings_fetched, model_calls, tokens_spent
rows_inserted, rows_marked_dead
rows_by_bucket: india_located / india_remote / global_hiring
INDIA_ELIGIBLE_EARLY_CAREER_OPEN     <- the number
programmes_open, programmes_opening_within_30d, programmes_stale
unverified_count
```

**Alert on drops, not on errors.** A board that returned 40 roles last week and 0 today has almost certainly broken — a changed JSON shape, a moved token, a silent block. It will not raise an exception. It will return HTTP 200 and an empty array forever. That drop is the most important signal the collector produces and the easiest one to miss.

Also alert when: a run fails outright, a programme page has been unreadable for two consecutive weeks, or the unverified count grows faster than the verified count.

---

## 8. When a run is good enough

A run is successful if every board was either read or explicitly recorded as failed, no row was stored that fails §1, and the report was written. Finding zero opportunities is a valid successful run.

A run is a failure if any board failed silently, or any row was stored with a missing official link, or a programme date changed without a fetched page behind it.

**What we are not measuring yet:** whether the eligibility facts are correct. That needs hand-checking surfaced verdicts against live postings, and it needs enough volume to hand-check. In July there may not be enough. That check comes before anyone outside sees the results, not before the lake exists.

---

## 9. Open questions — to argue out

1. **12 hours or 6?** §2. Leaning 12.
2. **Grants in the first lake?** §3.7.
3. **Scholarships at all?** §3.8. They need fields and user inputs nothing else uses.
4. **How long before a 200-with-zero board gets re-resolved?** §5.1. Leaning 14 days.
5. **Do we store `global_hiring` rows or drop them?** They were most of what the current registry returns, and they were almost all irrelevant to the audience. Storing them costs nothing; surfacing them by default may make the list feel like noise.
6. **Campus-only roles — store or drop?** For an Indian student the first practical question about any campus role is whether they can apply without going through their college. No Indian competitor answers it. That argues for storing them with the channel recorded rather than dropping them.
7. **How many boards before we stop adding and start reading the number?** Adding boards is cheap and endless. Somewhere there is a point where more boards stop teaching us anything new.
8. **What is "early-career" exactly?** 0 years only, or up to 2? Include Graduate Engineer Trainee? The answer changes the count by a lot.

---

## 10. First run, concretely

Nothing here needs a model. The first version of the lake is fetch, filter by title, filter by location — and that is enough to answer whether there is anything here at all. If the count comes back near zero across a few hundred boards, no amount of eligibility extraction would have rescued it.

1. `.gitignore` the credential file before any of this becomes a repo. It currently sits world-readable with a live token in it, and it is the only mistake on this list that cannot be undone.
2. Fix Workday pagination. Confirmed 2,000 postings visible where we were reading 200.
3. Build the resolver: company name → board token from the careers page. Fixes the Vercel and Mistral class of error, and it is the most reused code in the project.
4. Re-resolve all 65 existing boards through it. Some are on the wrong platform.
5. Add India-relevant companies by name, resolved not typed.
6. Sweep, write `jobs.json`, write the run report.
7. Read the number. Then decide what the product is.
