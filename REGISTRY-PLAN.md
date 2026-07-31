# Discovery Plan — how opportunities are found

**Goal:** a registry that **builds itself**, weighted toward what an Indian B.Tech student can actually apply to.
**Updated:** 2026-07-31
**Supersedes:** the previous six-phase plan, which assembled company lists by hand (YC directory, India list, Germany/Japan list). That approach is retired — §1 explains why.

---

## 1. Why the previous plan was wrong

The old plan aimed at 65 → 300+ verified boards by writing company names into `ats_candidates.txt`, one region at a time.

Two measurements killed it.

### 1.1 A hand-written list can only find companies you already thought of

That ceiling doesn't move by grinding. Tripling the list triples nothing structural.

### 1.2 The 65 boards produce essentially zero India early-career engineering roles

Sampled 22 Greenhouse boards from the current registry, 2026-07-31:

```
4,338 jobs total
  316 India-located          (7.3%)
    ├─ 222 senior/mid
    ├─  82 unlabelled (likely mid)
    └─  12 early-career  →  0 software engineering
```

The 12 were HR, sales, content, graphic design, video editing, billing and support. **Zero engineering.**

Confirmed independently by a live agent scan the same day: a registry-led pass over all 65 boards screened 116 early-career postings and returned **zero India-compatible roles** — six new records, all overseas, three explicit long shots.

### 1.3 But the mechanism is fine — the contents are wrong

The same day, a broad web-search pass found five verified India opportunities. Where they lived:

| Found | Platform | Already in registry? | `ats_fetch.py` supports it? |
|---|---|---|---|
| CloudSEK — Security Consultant Intern, Bengaluru | Greenhouse | **no** | yes |
| Hudson Manpower — AI Tools & Automation Intern, remote India | Recruitee | **no** | yes |
| Cushman & Wakefield — EIC Intern, Mumbai | Workday | **no** | yes |
| IIT Hyderabad CCS — Interns, Hyderabad | university page | n/a | no adapter |
| Goldman Sachs — 2027 Summer Analyst APAC, Mumbai | bespoke programme page | n/a | no adapter |

**Three of five were on platforms the code already reads.** They simply weren't listed. And the registry holds **zero Recruitee and zero Workable boards** despite full support for both.

The registry isn't the wrong idea. It contains the wrong 65 companies — 35 Greenhouse boards of US AI startups (Anthropic, OpenAI, Figma, Vercel), which is why it returns US roles.

**Conclusion:** stop curating companies. Sweep broadly and filter *jobs* by whether an Indian student can apply. The company list becomes an output, not an input.

---

## 2. Fix first — three bugs, unchanged from the old plan

### 2.1 A `dead` entry that isn't dead

Citadel is recorded `dead` with `error: "no_jobs"`. A board returning no early-career roles **works** — it's empty. Marking it dead means it's never checked again.

Three states:

- `verified` — token works, returned roles
- `empty` — token works, no qualifying roles at last probe. **Keep sweeping.**
- `dead` — token is wrong (404, 422). Never retry.

Citadel → `empty`. So do the 4 verified-but-zero boards.

### 2.2 A duplicate

ClickHouse appears twice, on Greenhouse and Ashby. Keep the one returning roles. Add a uniqueness check on `company` at promotion time.

### 2.3 Two platforms supported but unused

Zero Recruitee and zero Workable entries. Hudson Manpower — the only *Apply now* India role found all day — is on Recruitee. Free coverage sitting idle.

---

## 3. The five layers

No single mechanism reaches everything. Each layer covers what the others structurally cannot.

| Layer | Reaches | Automation |
|---|---|---|
| **1. Board universe** | any company on the 8 supported ATS platforms, incl. Indian companies and global-hiring startups | complete |
| **2. Campus & programme pages** | India early-career pipelines of global employers | high, after one-time setup |
| **3. Indian ATS platforms** | Indian startups on Keka / Darwinbox / Zoho | high, once HTML shapes are known |
| **4. Programme calendar** | fellowships, grants, OSS, research | medium — manual setup, automated upkeep |
| **5. Growth loop** | everything the others haven't found yet | complete |

### 3.1 Layer 1 — the board universe

**Enumerate, don't guess.** Common Crawl's public URL index supports prefix queries with no API key:

```
index.commoncrawl.org/CC-MAIN-<crawl>-index?url=boards.greenhouse.io/*&output=json
```

Take the first path segment of each result → the token. Repeat for `jobs.lever.co/*`, `jobs.ashbyhq.com/*`, `apply.workable.com/*`, `*.recruitee.com/*`, `*.myworkdayjobs.com/*`, `jobs.smartrecruiters.com/*`, `*.jobs.personio.de/*`. Dedupe, then run the existing `--verify-tokens` loop.

This is thousands of tokens for an afternoon's scripting, and it is the *only* enumeration source that requires no company knowledge at all. Common Crawl is published explicitly for reuse, so it carries no access risk.

**Then filter jobs, not companies.** Keep a posting if it passes any of three tests:

| Bucket | Test | Verdict |
|---|---|---|
| **India-located** | location matches Bengaluru, Hyderabad, Pune, Delhi-NCR, Gurugram, Noida, Mumbai, Chennai, Kolkata, Ahmedabad, Kochi, Indore… | apply now |
| **India-eligible remote** | `worldwide`, `global remote`, `work from anywhere`, or India named explicitly | apply now |
| **Global-hiring** | genuinely remote with countries unstated, or overseas with no authorisation bar | one confirmation needed |

CloudSEK enters the registry because it posted a Bengaluru role — not because anyone typed its name.

**Then tier boards by yield.** A board's sweep frequency follows what it has produced:

| Tier | Sweep | Promotion rule |
|---|---|---|
| `hot` | every 6h | produced a qualifying early-career role in the last 30 days |
| `warm` | daily | produced one at some point |
| `cold` | weekly | verified, never produced one |
| `dead` | never | wrong token |

Most enumerated boards land in `cold`. That's the mechanism that keeps a sweep of thousands of boards inside a ~3-minute budget (PRODUCT.md §5.2).

### 3.2 Layer 2 — campus and programme pages

~40 URLs. The India early-career pipelines of Qualcomm, Google, Microsoft, Amazon, Adobe, Nvidia, Salesforce, Uber, Walmart Global Tech, Cisco, Goldman Sachs, JPMorgan, Standard Chartered, Wells Fargo.

**Not optional.** The only two roles ever actually applied to in the private system came from here — Qualcomm campus and the Google apprenticeship. These never appear on Greenhouse, and they carry real deadlines, which Layer 1 postings almost never do.

Mechanism: store the URL, fetch weekly, hash the text. On change, one AI call extracts open requisitions from the HTML. Pages change roughly annually, so upkeep is near zero after setup.

Build these tokens with the **careers-page redirect** (§4), never by guessing — that is why the two dead Workday entries failed.

### 3.3 Layer 3 — Indian ATS platforms

Keka, Darwinbox, Zoho Recruit. These dominate Indian startups, and the old note said they expose no public JSON.

**That note is too strong.** The 2026-07-31 scan successfully read Zenskar's Keka page and correctly reported it was hiring Content, Customer Success and RevOps rather than Engineering. No JSON, but the HTML is parseable.

Mechanism: fetch the careers page, one AI call extracts the job list — identical to Layer 2. Worth a dedicated day to establish the HTML shape per platform, because this is the layer that unlocks Indian companies specifically.

### 3.4 Layer 4 — the programme calendar

~50 rows, typed once, then watched. India-weighted:

GSoC · C4GT / DMP (Samagra) · IAS Summer Research Fellowship · IIT & IISc summer research · ISRO Student Project Trainee · Outreachy · MLH Fellowship · LFX Mentorship · CERN Technical Student & Openlab · DAAD RISE · MITACS Globalink

India is the largest GSoC participant country, and C4GT already appears in the private system's memory — for this audience these are mainstream, not obscure.

Upkeep rule from PRODUCT.md §10.3: **the model may read a fetched page, never recall a date.** Every row shows `last verified`.

### 3.5 Layer 5 — the growth loop

Harvest **company names only**, then resolve each to its board:

| Source | Status |
|---|---|
| YC company directory | **use** — genuinely public and stable |
| Wellfound, RemoteOK, Himalayas | use sparingly |
| Internshala, Unstop | use sparingly, honour `robots.txt`, treat as optional |
| **LinkedIn, Naukri** | **do not use** — see §7 |

Never republish their listings. Take the name, go to the company's own board. This is what makes the registry grow daily without anyone touching it.

---

## 4. The one utility everything depends on

**Company name → board token, via careers-page redirect.**

```
fetch  company.com/careers   →  follow redirect
  boards.greenhouse.io/cloudsek        =  greenhouse:cloudsek
  hudsonmanpower.recruitee.com/o/...   =  recruitee:hudsonmanpower
  cw.wd1.myworkdayjobs.com/External    =  workday:cw.wd1.myworkdayjobs.com|cw|External
```

One request, high accuracy, no guessing. Layers 2, 3 and 5 all depend on it, and it is how Workday tokens (`host|tenant|site`) must be built. Write this well — it is the most reused code in the project.

Token guessing remains a fallback only: lowercased name for Greenhouse/Lever/Ashby/Recruitee, PascalCase for SmartRecruiters. One guess per company, never brute force.

---

## 5. Company size, derived not typed

At thousands of boards, `company_tier` cannot be hand-entered. Two cheap signals:

- **Total job count on the board** — already recorded as `last_probe_count`, a decent size proxy
- **One AI classification per company, once ever** → `big_tech | large | mid | startup | unknown`

Feeds the user control in PRODUCT.md §12.3: *any · include smaller and lesser-known · startups only*. Small companies matter — availability lives there, and the never-empty rule depends on them.

---

## 6. Order of work

| Step | Work | Why here |
|---|---|---|
| **0** | Fix `dead`/`empty`, reclassify Citadel, drop ClickHouse duplicate, add Recruitee + Workable | bugs and free coverage |
| **1** | Build the resolver (§4) | everything else needs it |
| **2** | Layer 1 — enumerate 8 platforms, three location buckets, board tiering | the workhorse; one weekend |
| **3** | Layer 5 — point the growth loop at YC and Internshala | registry starts growing unattended |
| **4** | Layer 4 — type the 50 programmes | uncontested, real deadlines, one day |
| **5** | Layer 2 — the ~40 campus pages | where real applications actually came from |
| **6** | Layer 3 — Keka / Darwinbox / Zoho as HTML | unlocks Indian startups |
| **7** | **Measure eligibility accuracy** before anyone else sees it | PRODUCT.md §7.1 |

Steps 1–3 replace the entire old six-phase plan and take about a weekend.

**Cut entirely:** the old Phase 5 (Germany, Switzerland, Japan). Those lists served the author's personal visa-market interest, not an Indian B.Tech audience. Enumeration will surface those companies anyway if they post India-eligible remote roles.

---

## 7. Etiquette, legality and rate limits

This is a public product, so politeness is not optional. Full legal treatment in PRODUCT.md §14.2; the operational rules:

**Safe — no real concern**
- Common Crawl — a public dataset published for exactly this use
- Public ATS JSON endpoints — the same URLs the employers' own careers pages call
- Company careers pages, university and programme pages — published to be read

**Moderate — proceed carefully**
- Workday — historically less tolerant of automated access; keep volume low
- Keka / Darwinbox / Zoho HTML — fine to read, do not reproduce in full

**Do not use**
- **LinkedIn and Naukri.** Terms prohibit automated access and both have a history of enforcement. Their companies appear via Layer 1 anyway, so the incremental value is near zero.
- Any logged-in content, ever.

**Operational rules**
- one request at a time per host, with a delay — different platforms are different hosts, so lanes may run in parallel
- honest `User-Agent` naming the tool **with a contact address**
- respect `robots.txt`
- **liveness comes from the board's job-ID list, not from re-fetching descriptions** — one request per company; descriptions only for new IDs, with a weekly re-read for silent edits (PRODUCT.md §5.1–5.2)
- never re-fetch a description whose `content_hash` is unchanged
- **honour takedown requests immediately** and keep a permanent blocklist
- **never display a full job description** — title, company, location, official link, and one short quoted line of evidence
- keep `raw/` snapshots private; never publish the Lake (PRODUCT.md §14.1)
- always link to the original posting

`verified` and `empty` boards are both re-swept — that's the point of the distinction. `dead` boards are never retried, but the dead list gets a manual review roughly quarterly, since a wrong token can be corrected later.

---

## 8. Metrics per run

- verified / empty / dead counts, and hot / warm / cold tier distribution
- **qualifying India-eligible early-career roles found** — the number that actually matters
- hit rate per layer, so effort goes where it pays
- roles per board, so low-yield boards get demoted automatically
- **boards that dropped from many roles to zero** — the silent-death signal that becomes the alert
- resolver success rate (names in → tokens out)
- share of results in each location bucket: India-located / India-remote / global-hiring

---

## 9. The open question

Nobody knows how many India-eligible early-career engineering roles this actually yields. It is July — the seasonal trough, since summer internships post August–November. Estimates from either intuition or a 22-board sample are unreliable.

That is the real reason to build Layers 1 and 5 first: they are cheap, they run unattended, and in two weeks they produce a real number.

**Worth scheduling:** re-run the §1.2 measurement in October, at peak season. If India early-career engineering roles on enumerated boards are still near zero, Layers 2–4 become the entire product and Layer 1 is demoted permanently.
