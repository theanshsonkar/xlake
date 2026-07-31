# Opportunity Lake — Product Document

**Tagline:** Every opportunity you're actually eligible for. Jobs, internships, fellowships, grants.
**Author:** Ansh Sonkar
**Updated:** 2026-07-31
**Status:** Pre-build. Concept, architecture, memory model and UI direction locked. Collector loop, urgency model and cost model revised 2026-07-31 against measured data from the private system (§4.1, §5.2, §15.4). Active workstreams: secrets hygiene (§14.1), registry Phase 0 (`REGISTRY-PLAN.md`), programme calendar (§10.3). One sequencing decision outstanding — §18.1.

---

## 1. What it is

Not a job portal. A portal lists everything and makes you filter it. Opportunity Lake does the opposite — it holds everything and hands back only what applies to one person.

You drop in a resume, confirm six details, and get a short list where every item has been checked against the real posting to confirm you're eligible — and confirmed still live within the last few hours. Jobs, internships, fellowships, and grants in one list, freshest first, with real programme deadlines called out where they exist.

**Audience: public, and India-first.** Built for strangers, not just the author — and specifically for **Indian B.Tech students**, starting with the author and his friends as users one through five. That decision drives the safety, monitoring and privacy requirements in §14, and it reshaped discovery entirely (§5.3, §10).

Concretely, the audience wants anything good in India — jobs, internships, apprenticeships, fellowships — plus remote roles that genuinely hire from India, plus global-hiring startups. Across big, mid and small companies. Without checking six sites every day.

### 1.1 What the audience decision changed

Two measurements on 2026-07-31 reordered the whole plan.

**The 65-board registry produces no India early-career engineering roles.** A sample of 22 Greenhouse boards returned 4,338 jobs and 316 India-located ones, of which 12 were early-career — and **none were engineering** (HR, sales, content, graphic design, video editing, billing, support). A live agent scan the same day confirmed it across all 65 boards: 116 early-career postings screened, **zero India-compatible results**, six new records all overseas, three explicit long shots.

**But the mechanism was never the problem.** A broad web-search pass that same day found five verified India opportunities, and three of them — CloudSEK on Greenhouse, Hudson Manpower on Recruitee, Cushman & Wakefield on Workday — sat on platforms `ats_fetch.py` already supports. They simply weren't listed. The registry held **zero Recruitee and zero Workable boards** despite full support for both.

The registry contained the wrong companies: 35 Greenhouse boards of US AI startups. So it returned US roles.

**The fix, and the organising principle of the whole collector:** stop curating companies, sweep broadly, and filter *jobs* by whether an Indian student can apply. The company list becomes an output, not an input. Detail in `REGISTRY-PLAN.md`; the five layers are §5.3.

---

## 2. The problem

Every job site optimises for volume. Search "software intern," get 200 results, then spend the evening discovering one wants 3 years' experience, one only takes 2026 graduates, one says "remote" but means remote-inside-the-US, and four links are dead. All the filtering work lands on the candidate.

Worse, an entire category is invisible everywhere: fellowships, apprenticeships, research programs and grants — GSoC, Outreachy, MLH, CERN Technical Student and Openlab, university "Emerging Talent" and "Explore" programs. These don't live on applicant tracking systems, so ATS-scraping tools structurally cannot see them.

---

## 3. Origin — the working private system

This productises a running private system at `~/Desktop/jobs/` ("Job Radar v5"). Not a concept: 21 scans logged, 44 active and 25 rejected opportunities tracked.

### 3.1 Current stores

| Store | File | Role |
|---|---|---|
| **MEMORY** | `jobs_memory.jsonl` | Every opportunity ever seen, all statuses including rejected. Never deleted; statuses and `last_seen` update in place. Dedupe source of truth. |
| **BOARD** | Notion DB "DB Applications" | Human-editable view, non-rejected rows only. Statuses: To apply / Applied / Interviewing / Offer / Watching / Verify. |
| **STATE** | `jobs_state.json` | `last_scan`, `rotation_next`, `rotation_cycle`, `scan_history`. |

### 3.2 The engine — `notion_upsert.py`

Each run: pulls manual Notion status edits back into MEMORY (human owns status), merges new finds split new-vs-still-open, reconciles the board, refreshes a live stats callout and pie chart, stamps `last_scan`, advances the rotation pointer. Flags: `--check` (health), `--stale` (funnel), `--mirror` (read-only snapshot), `--advance`.

Dedupe key: normalised URL (lowercased host, `www.`/query/`#`/trailing slash stripped), falling back to `company|title`.

### 3.3 The verification layer — the real IP

**`ats_registry.json`** — 65+ *verified* board tokens with company and category, plus a `dead` list. The critical insight: **a 404 means a wrong token, not an empty board.** Conflate those two and you can't tell "no openings" from "I guessed the slug wrong."

**`ats_sweep.py`** — sweeps every verified token, prints only early-career titles, filters senior ones. Narrowable by `--category` / `--company`. New candidates go into `ats_candidates.txt` as `platform:token:Company:Category`, then `--verify-tokens` promotes the working ones and records failures as `dead` so they're never re-guessed.

**`ats_fetch.py`** — Greenhouse, Lever, Ashby, SmartRecruiters, Workable, Workday, Personio, Recruitee. Single-job mode returns up to 6000 characters so the *eligibility block* (graduation year, degree, work authorisation) is readable, not just a snippet. Workday tokens are `host|tenant|site`, which unlocks large-company India offices.

**Known dead ends (tested 2026-07-27):** Keka, Darwinbox, Zoho Recruit expose no public JSON. These dominate Indian startups, so India-first coverage still needs official-site checks — and anything unreachable goes to an explicit unverified bucket rather than being guessed.

### 3.4 Eligibility rules

Surface only if the official current posting shows: an internship open to enrolled undergraduates **or** a new-grad role compatible with the candidate's graduation date; a graduation window that includes their year or imposes no incompatible date; no requirement above one year of non-internship professional experience; no completed Master's/PhD unless optional; compatible location and work-authorisation wording; and a live official/ATS application link.

Rejected outright: SDE II/III, Senior, Staff, Principal, Lead, Manager, Director, Architect. 2+ years non-internship experience. Expired, removed, repost-only, or unofficial links.

### 3.5 Remote eligibility tiers

"Remote" does not mean "can hire from your country."

- **Tier A** — explicitly names your country, or `worldwide` / `global remote` / `work from anywhere`. Verdict *Apply now*.
- **Tier B** — genuinely remote, no permitted countries stated. *Needs one confirmation*, with the exact question to ask.
- **Tier C** — remote only in a named region with no alternative. Excluded as not actionable.
- **On-site/hybrid overseas** in sponsorship markets — surfaced as *Needs one confirmation* unless the posting explicitly bars non-nationals or requires existing local authorisation. Never implies the candidate holds a visa.

### 3.6 Categories

Big Tech · Quant/Finance · AI/ML/Data · Startup · **Fellowship** · India-first

### 3.7 Funnel discipline

Every run prints `stale_to_apply` (stuck in *To apply* 5+ days) and `deadlines_within_7d`, and the report leads with those, above new finds. **A queued verified role is worth more than a newly discovered one.** Discovery feels productive while the real bottleneck is unsubmitted applications.

### 3.8 Hard guardrails

Never submit an application, create an account, message a recruiter, or upload a resume without explicit approval. Never mark something Applied autonomously. **Never falsify a graduation year.** Never treat a form accepting a submission as proof of eligibility. Never claim work authorisation the posting hasn't confirmed.

These become product principles, not just agent etiquette.

---

## 4. Positioning

**Wrong pitch (commoditised):** "Upload your resume, get matching jobs." Simplify, JobRight, Sonara and others already do this.

**Right pitch:** "Only opportunities you're actually eligible for — verified against the real posting. Including the fellowships and grants no job site carries."

Differentiators by defensibility:

1. **Fellowships, grants and programmes.** Uncontested — but **not for the reason first assumed.** The original claim was "structurally invisible to ATS scrapers, therefore hard to find." That's weak: an AI agent with web search can assemble the list of 50 names in an hour, and those names are already on public awesome-lists and Reddit. Finding them was never the moat.

   The durable reason is **product shape.** Tsenta's machine is find → tailor → auto-submit, tuned for volume. There is nowhere in it to put a thing that opens in August, closes on a fixed date, requires an essay, and cannot be auto-applied to. Carrying programmes would mean building a second product with different economics. That's a strategic gap, not a data-difficulty gap — and strategic gaps last longer.

2. **Real eligibility extraction from the full posting** — graduation window, experience ceiling, degree, study-year bounds, work authorisation. Measured value: 36% of carefully screened opportunities still weren't applicable (§4.1). This is the strongest technical differentiator and was previously ranked third.

3. **Liveness.** Eleven of twenty-five real rejections were dead postings (§4.1). "Every link confirmed live within 6 hours" is cheap, fully automatable, needs no AI, and no competitor advertises it.

4. **The remote Tier A/B/C classifier.** Nobody separates "remote" from "remote where you live."

5. **The verified board registry with a `dead`/`empty` distinction.** Real engineering value — it keeps "wrong token" apart from "not hiring", which is the mistake that silently deletes companies. **But it is not a moat.** REGISTRY-PLAN §5 documents the reason itself: hit `company.com/careers`, read the redirect, and the token falls out. That's one scriptable request per company. Public token dumps also exist. Treat the registry as necessary infrastructure, not defensible IP.

6. **Honest unverified bucket.** Admitting what couldn't be confirmed is a trust feature.

**Where not to compete:** coverage. Tsenta watches 50,000+ career pages; 300 boards is a rounding error against that (§16.1). Every differentiator above is a precision claim, not a volume claim, and the roadmap should reflect that.

### 4.1 Evidence, measured — not asserted

The claim above is usually made with adjectives. Here it is as numbers, from `jobs_memory.jsonl` (69 opportunities, 20 scans, 2026-07-17 → 07-28):

| | Count | Share |
|---|---|---|
| Surfaced by a careful agent reading full postings | 69 | — |
| **Later rejected as not actually applicable** | **25** | **36%** |
| — because the posting was dead, removed, filled or aggregator-only | 11 | 44% of rejections |
| — because of a real eligibility gate | 13 | 52% of rejections |
| Applied | 14 | 20% |

**36% of what survived careful screening still wasn't applicable.** On a normal job portal, with no screening at all, that number is far worse. That is the product, stated as a measurement.

Two things follow, and they set the priorities:

**The most common failure is deadness, not ineligibility.** Eleven of twenty-five: Cloudflare removed, Google taken down, EA closed applications, Workato removed, Airbus removed, Deloitte filled, Tower removed, Ema delisted, Cisco window closed, Zerodha no openings, Walmart aggregator-only. Deadness needs no AI to detect — only a re-fetch. **"Every link here was confirmed live within 6 hours" is therefore the cheapest true promise in the product, and should lead.**

**The eligibility rejections are the Tier 1 spec.** These are real gates found in real postings, and each is a pattern the collector must catch. This list is a test set, not an anecdote:

| Rejection reason found in the posting | What Tier 1 must detect |
|---|---|
| Atlassian — mandates 2028 grad, IIT-Madras only | grad-year mandate; institution restriction |
| Microsoft — 1st/2nd-year students only | *lower* bound on study year, not just upper |
| Optiver / IMC — requires a PhD | degree ceiling |
| Cisco — qualification is a Master's degree | degree ceiling |
| IMC — "graduating September 2027 – July 2028" | grad-window *range* parsing, not a year list |
| MLH — not open to India/APAC; needs prior Hack Week | region exclusion; prerequisite-participation gate |
| Revolut — office/remote limited to EU/UK/UAE | remote Tier C |
| Susquehanna — US on-site, no India/visa route | onsite + no sponsorship route |
| Branch — 3–5 yrs / 4–8 yrs experience | experience ceiling, range form |
| JumpCloud — senior/staff full-time | seniority from body text, not just title |

Note what's here that a naive implementation misses: Microsoft was rejected for wanting students *too early* in their degree, and IMC stated a grad *range* rather than a list of years. Both are easy to get backwards.

---

## 5. Architecture — two halves

**Half A — the collector.** Runs every 6 hours whether anyone visits or not. Builds the Lake. All expensive work happens here, once per opportunity, shared by every user forever.

**Half B — the visitor.** Runs only when someone drops a resume. Takes ~5 seconds. Two AI calls.

That split is the entire cost model.

### 5.1 Half A, step by step

1. **Read the board registry.** Entries like `greenhouse:stripe:Stripe:Big Tech`. Sweep `verified` and `empty`; skip `dead`.
2. **Visit each board's public API.** One request returns every job ID at that company. 404/422 → mark dead, never retry. Valid but empty → `empty`, keep sweeping.
3. **Diff the ID list against last sweep — this is the liveness check.** An ID that has disappeared from the board means the posting is gone: mark `is_live: false`. **No description download is needed to learn this.** Deadness was the single most common rejection cause (§4.1) and it costs one request per company, not one per job.
4. **Drop obvious junk on title alone** — Senior, Staff, Principal, Lead, Manager, Director, Architect. Kills most volume before spending anything.
5. **Download the full description for new IDs only.** Roughly 30–50/day at 65 boards, versus ~900 if you re-fetched everything. Save raw text to `raw/`, keyed by `content_hash`.
6. **Extract eligibility facts** (see §7, three-tier model) — Tier 2 runs on new rows and on rows whose `content_hash` moved. Unchanged rows are skipped entirely.
7. **Compute a skills embedding.** Once per opportunity version.
8. **Upsert into the Lake.** Existing URL → update `last_seen`, `last_verified_live`, `is_live`. Never duplicate. A row that disappears is marked dead, never deleted.
9. **Run the Layer 2–4 page watchers** (§5.3). Weekly cadence, HTML not JSON, one AI read per changed page.

**Weekly, not 6-hourly: the silent-edit pass.** Re-download every live description once a week and re-hash it. Companies don't edit postings hourly, so paying for this every sweep buys nothing. Catching "2026 graduates" quietly becoming "2027 graduates" (§7) at weekly resolution is sufficient.

### 5.2 Sweep cost, in minutes

Politeness means one request at a time per platform, which makes wall-clock time the binding constraint rather than money.

| | Requests | Time |
|---|---|---|
| Board listings, 65 boards | 65 | ~2 min |
| New descriptions only | ~40 | ~1 min |
| **Per sweep** | ~105 | **~3 min** |
| Weekly silent-edit pass | ~900 | ~15 min ×4/month |

`3 min × 4/day × 30 + 60 = ~420 minutes/month`, against **GitHub Actions' 2,000 free minutes for private repos.** Comfortable margin, and it holds to roughly 300 boards.

**Why this matters:** the naive loop — re-download all ~900 descriptions every sweep — takes ~15 minutes, which is 1,800 min/month, i.e. 90% of the free allowance on day one, and it exceeds Lambda's hard 15-minute timeout if you ever migrate. Using the ID list for liveness removes both problems. **The repo therefore stays private** (see §14.1) and no queue/fan-out architecture is needed at this scale.

If the sweep ever does need to be faster: different platforms are different hosts, so Greenhouse, Lever, Ashby and Workday can be swept in parallel lanes while remaining polite to each individually. That is a ~6× speedup available before any architectural change.

### 5.3 The five discovery layers

No single mechanism reaches everything. The old plan had one — a hand-curated registry sweep — which §1.1 shows returns nothing for the actual audience. Each layer below covers what the others structurally cannot.

| Layer | Reaches | Automation |
|---|---|---|
| **1. Board universe** | any company on the 8 supported ATS platforms — including Indian companies and global-hiring startups | complete |
| **2. Campus & programme pages** | India early-career pipelines of global employers | high, after one-time setup |
| **3. Indian ATS platforms** | Indian startups on Keka / Darwinbox / Zoho | high, once HTML shapes are known |
| **4. Programme calendar** | fellowships, grants, OSS programmes, research | medium — manual setup, automated upkeep |
| **5. Growth loop** | whatever the others haven't found yet | complete |

Full method per layer in `REGISTRY-PLAN.md` §3. The three points that matter architecturally:

**Layer 1 enumerates rather than curates.** Common Crawl's public URL index returns every ATS board token ever linked on the web — thousands, for an afternoon's scripting, requiring no company knowledge. Boards are then tiered by yield (`hot` 6-hourly / `warm` daily / `cold` weekly), which is what keeps a sweep of thousands of boards inside the ~3-minute budget in §5.2.

**Layers 2–4 have no API.** Campus pages, Indian ATS pages and programme pages are HTML only. They need a page-reading adapter — fetch, hash, and on change let one AI call extract requisitions. This is a fifth AI use the earlier cost model omitted (§15.3).

**Layer 5 makes the registry self-growing.** Harvest company *names* from public directories, resolve each to its board via the careers-page redirect, sweep forever after. No name is ever typed by hand.

### 5.4 Three location buckets

A single "is this in India" test is too narrow for the audience, which also wants remote and global-hiring roles. A posting is kept if it passes **any** of:

| Bucket | Test | Verdict |
|---|---|---|
| **India-located** | Bengaluru, Hyderabad, Pune, Delhi-NCR, Gurugram, Noida, Mumbai, Chennai, Kolkata, Ahmedabad, Kochi, Indore… | apply now |
| **India-eligible remote** | `worldwide`, `global remote`, `work from anywhere`, or India named explicitly | apply now |
| **Global-hiring** | genuinely remote with countries unstated, or overseas with no authorisation bar | one confirmation needed |

This is the existing remote Tier A/B/C classifier (§3.5) applied at ingest as a filter rather than at report time as a label. Tier C — remote restricted to a named region excluding India — is dropped, not surfaced.

### 5.5 Half B, step by step

1. Extract text from the uploaded PDF.
2. **One AI call** → structured profile (see §8).
3. Show extracted values resolving live — the scan screen.
4. User confirms six pre-filled details.
5. **Filter in plain code** — no AI. Graduation window, experience ceiling, category, remote tier, closed items.
6. **Rank by embedding similarity.** Pure math.
7. **One batched AI call** writes "why this fits" for the top 20.
8. Render in the §12.4 order — programme deadlines, then freshest jobs.
9. Discard the resume. Profile and seen-list go to the browser.

---

## 6. Memory model

The private system's `jobs_memory.jsonl` does two jobs at once. For many users they must split.

### 6.1 The Lake (shared, global)

Every opportunity ever found, all states including expired. **One row per opportunity, not one row per scrape** — seeing Stripe's role again updates `last_seen`, it does not add a row. Never deleted, so a dead or rejected role never resurfaces as new. Contains zero user data.

### 6.2 Per-user history (tiny)

Just `opportunity_id` + status + timestamp. **Beta: browser localStorage only** — nothing on the server. Later, if people want email digests, a small table holding only IDs and statuses. Never the resume, never the parsed profile's free text.

### 6.3 Three append-only logs

- **Scrape log** — the descendant of `scan_history`: timestamp, boards swept, new found, boards that died. How you notice breakage.
- **Raw posting snapshots** — the description text, keyed by opportunity and `content_hash`. A new snapshot is written only when the hash changes, so an unedited posting stores one copy however many times it's swept. Two payoffs: improve the eligibility reader and re-run it over history without re-scraping, and detect when a company quietly edits "2026" to "2027" (§7).
- **Dead boards** — already in the registry.

### 6.4 Scale reality

A few thousand opportunities at ~2KB each is ~10MB; raw postings ~100MB. Keeping everything forever is effectively free at this scale. The never-delete instinct is correct.

### 6.5 What v1 drops

No statuses, no Applied/Interviewing pipeline, no stale-application nudge. Those need accounts. The stale nudge is one of the private system's best features and is the first thing to add in v2.

---

## 7. Replacing the agent — three-tier judgment

Today an agent reads `ansh-job-radar.md` and reasons about each posting per session. On a website there is no agent, so the prose becomes code. The agent is **demoted from a conversation to a function, and moved to ingest time.**

**Tier 1 — plain code, ~75% of decisions.** Seniority from title. `3+ years` patterns. Explicit graduation-year lists. Deadline dates. Work-authorisation phrases. Remote-tier keywords. Free, instant, cannot hallucinate.

**Tier 2 — one AI call per *version* of the opportunity, at ingest.** The radar file's rules become a system prompt with a strict JSON output schema. It runs when the opportunity **enters the Lake**, and again only if the posting text actually changes. The answer is stored and reused by every user. This is where the model is genuinely needed and where accuracy matters most.

**Change detection, and where it runs.** An earlier version of this document said Tier 2 runs "once in its life, ever" — which contradicted §6.3's requirement to catch a company quietly editing "2026" to "2027". Both are satisfiable, on two different clocks:

- **Every 6 hours:** liveness only, from the board's ID list (§5.1 step 3). No description downloaded, no hash computed, no AI call. Costs one request per company.
- **Weekly:** re-download live descriptions, hash them, and act only on the ones that moved.

```
h = sha256(normalise(description))
if h == row.content_hash:  row.last_verified_live = now(); stop
else:                      snapshot(); rerun_tier2(); diff_facts()
```

If `grad_years_accepted`, `grad_window_*`, `min_years_experience` or `deadline` moved, that's a **silent edit**: log it and refresh the pass card's evidence line.

Descriptions rarely change, so the weekly pass triggers Tier 2 on a low single-digit percentage of rows. Cheap enough that §15.3's cost model is unaffected, and it removes the risk of certifying a candidate against text that no longer exists.

**Tier 3 — the unverified bucket.** Blocked, JavaScript-only, Keka/Darwinbox/Zoho. Surfaced with company, title, best link, and the single thing for the user to check. Because a stranger — unlike the author — never reports the answer back, the Lake does not learn from this bucket. Keep it small; if it grows large the product degrades into handing out homework, which is what §2 positions against.

Today's system re-judges every posting every session. The Lake judges each posting once per version. That is the cost trick.

### 7.1 Accuracy is the whole product

A wrong "you're eligible" destroys the pitch. So: write Tier 1 patterns properly first, then measure the false-eligible rate. **That number is the most important metric in the project** — more than user count.

**Sample size matters more than it looks.** An earlier version of this plan said "hand-check 30 Tier 2 outputs." Thirty cannot distinguish a 2% error rate from a 10% one — if the true rate is 5%, the expected number of errors in the sample is 1.5, so seeing one or two tells you almost nothing. Check **200+** before treating the number as real.

**Measure the error you cannot see, too.** False-*eligible* is visible: click through and the posting contradicts you. False-*ineligible* — roles wrongly filtered out — is invisible to the user and to you, because an over-filtered list looks identical to an accurate one. For a product whose entire function is aggressive filtering, this is the more dangerous direction. So the audit has two halves:

1. Take 200 surfaced verdicts, confirm eligibility against the live posting → false-eligible rate.
2. Take 50 **rejected** rows, hand-check whether they should have passed → false-ineligible rate.

**Also sample Tier 1 through Tier 2.** Tier 1 decides ~75% of cases with regex and is never checked against anything. Periodically run Tier 2 on a sample of Tier 1-decided postings and record the disagreement rate. That is the regression suite for the patterns, and without it Tier 1 rots silently as posting language drifts.

---

## 8. Resume extraction — richer than skills

Jobs ask *are you eligible* (mechanical). Grants ask *does your work fit the theme* (a sustainability grant needs a sustainability project). So the parse must capture projects and proof-artifacts, not just skills:

```json
{
  "skills": ["Python", "FastAPI", "AWS", "Terraform"],
  "grad_month": 5, "grad_year": 2027,
  "years_experience": 0,
  "location": "Delhi-NCR",
  "level": "intern",
  "projects": [
    {"name": "Emfirge", "themes": ["cloud security", "infrastructure", "devtools"]},
    {"name": "carto",   "themes": ["open source", "developer tooling", "AI"]}
  ],
  "artifacts": {
    "has_public_repo": true,
    "has_publication": true,
    "has_founded_company": true,
    "has_deployed_product": true
  }
}
```

The `artifacts` booleans are exactly what grant and fellowship gates check — "must have an existing open-source project" is a boolean. Cheap and exact.

Thematic fit reuses existing machinery: embed the project themes, embed the program's theme tags, compare. Same embeddings, different field. No new infrastructure.

**If nothing matches thematically, don't show the grant.** But there's a genuinely good secondary feature here: a small collapsed section reading *"4 grants you'd qualify for if you had a public repo."* No job site gives advice like that.

---

## 9. Data model

### `opportunities`

```
id, company, title, level (intern | new_grad | mid), category[],
company_tier (big_tech | mid | startup | unknown),
location, remote_policy, remote_tier (A | B | C | onsite),
source_platform, source_token, official_apply_url, posted_on, deadline,
grad_years_accepted[], grad_window_from, grad_window_to,
min_years_experience, max_years_experience,
study_year_min, study_year_max,
degree_required, degree_ceiling,
institution_restriction, prerequisite_gate,
work_auth_required, seniority_flagged,
access_channel (off_campus | campus_only | campus_preferred | unknown),
location_bucket (india_located | india_remote | global_hiring),
hires_from_india (yes | unknown | no), stipend, is_paid,
source_layer (1..5), source_url,
long_shot (bool), long_shot_reason,
stack_tags[], embedding, verification_state (verified | unverified),
content_hash, last_verified_live, extraction_version,
first_seen, last_seen, is_live
```

`company_tier` exists so results can widen toward smaller companies (§12.4) and so users can deliberately choose them.

**`deadline` is nullable and usually null** — 4.3% populated in the private store, effectively programmes only (§12.4). Nothing in the UI may depend on it being present.

**`last_verified_live`** is the timestamp of the last successful re-fetch. It powers the `live 4h ago` line, which §4.1 identifies as the cheapest true promise in the product, and it is the field the never-empty rule should degrade toward rather than deadline.

**`content_hash`** drives change detection (§7): unchanged hash means no Tier 2 call. **`extraction_version`** records which Tier 1/Tier 2 ruleset produced the facts, so improving the reader lets you find and re-run every row extracted by an older version without re-scraping.

The gate fields split apart deliberately, because §4.1's real rejections needed distinctions a single field can't hold: `grad_window_from`/`_to` for IMC's "September 2027 – July 2028" range, `study_year_min` for Microsoft wanting 1st/2nd-years only, `institution_restriction` for Atlassian's IIT-Madras requirement, `prerequisite_gate` for MLH's prior-Hack-Week rule.

**`access_channel` is India-specific and nobody else checks it.** Three real rejections turned on it — Cisco's assessment window was placement-cell gated and closed, Walmart had no public application link, Atlassian was IIT-Madras only. For an Indian B.Tech student the first practical question about any campus role is *"can I apply to this without going through my college?"* Neither Internshala, Unstop nor LinkedIn answers it. For this audience it is a sharper differentiator than the remote tier classifier, which matters less to someone who wants a Bengaluru internship.

**`location_bucket`** records which of §5.4's three tests the posting passed, so the UI can label *why* something is being shown — India-located, India-eligible remote, or global-hiring needing one confirmation.

**`source_layer`** records which of the five discovery layers found it. That is how per-layer hit rate gets measured, and therefore how effort gets allocated.

**`company_tier` is derived, not typed.** At thousands of boards it must be. Two cheap signals: total job count on the board (already stored as `last_probe_count`) and one AI classification per company, once ever. It feeds the *any · include smaller and lesser-known · startups only* control in §12.3.

### `programs` (fellowships, apprenticeships, grants, research)

A program's shape genuinely differs from a job's: recurring season, hard deadline, eligibility framed around enrolment and sometimes nationality, often no salary.

```
id, name, organisation,
kind (fellowship | apprenticeship | grant | research | university_program),
typical_open_month, typical_close_month,
current_cycle_opens, current_cycle_deadline,
enrolment_requirement, nationality_restrictions, stipend, location_mode,
theme_tags[], requires_artifact[],
official_url, last_verified, status (open | upcoming | closed)
```

### `board_registry`

```
platform, token, company, category, company_tier,
status (verified | dead | empty), last_checked, last_ok, jobs_last_seen
```

`empty` is distinct from `dead`: the token works, there are simply no early-career openings right now. Collapsing them is the mistake the whole registry exists to prevent.

---

## 10. Discovery by opportunity type

§5.3 splits discovery into five layers. This is what each opportunity *type* needs, and why one filter cannot serve all of them — the eligibility **shape** differs per type, not just the source.

### 10.1 Types reached by Layer 1 (board sweep)

**Jobs (new grad, SDE I, Associate).** On ATS boards, found by sweep. Highest volume, no deadlines, posted whenever a team gets budget. Eligibility is mechanical: graduation year, experience ceiling, degree. Fully handled by Tier 1 + Tier 2. This is also the category where coverage loses to Tsenta 50,000-to-300 — surface it well, don't compete on it.

**Internships.** Same boards, same method, but **seasonal.** Summer-2027 internships are posted roughly August–November 2026. Outside that window there is nothing to find regardless of how many boards are swept. So internships are found by Layer 1 but *timed* like a programme: when the count is zero, say "big-tech summer internships usually open in September" rather than showing an empty section. This is the never-empty rule (§12.4) applied to seasonality.

**Apprenticeships, graduate programmes, "Emerging Talent".** The awkward middle — partly ATS, partly bespoke company pages. Titles avoid the obvious words: *Explore Program*, *Emerging Talent*, *Graduate Engineer Trainee*, *Apprentice*. Requires the keyword list in §11, not just `intern`.

Two properties unique to this category:
- **They carry real deadlines.** All three deadline-bearing rows in the private store were here — two Google apprenticeships, one Wells Fargo programme.
- **A cohort start date that can conflict with graduation.** Google's apprenticeship starts March 2027 against a May 2027 graduation. This is the only category where a *start* date is an eligibility gate, and it is the source of the "2 of 4 checks" card in §13.2.

### 10.2 Types needing Layers 2–4 (page watchers)

**Fellowships.** GSoC, Outreachy, MLH, CERN Technical Student, CERN Openlab, LFX Mentorship. No ATS, no API. Different gates from a job:

| Gate | Example from real data |
|---|---|
| currently enrolled (not "graduating by") | most programmes |
| region exclusion | MLH — not open to India/APAC |
| nationality restriction | CERN — member states |
| **prior participation** | MLH — requires previous Hack Week |

That last one has no equivalent in any job posting, and it's why the schema has `prerequisite_gate`.

**And they recur.** GSoC opens within the same few weeks every year. So `typical_open_month` supports a claim nobody else can make: *"GSoC usually opens in February — about 6 weeks away,"* said before it is announced. This is the single most novel output of the product and it is a hand-typed date field.

**Open-source programmes.** Structurally two-layer, unlike everything else:
- the **programme** has one deadline (GSoC applications close ~late March)
- but you apply to a specific **organisation and project** inside it — GSoC alone has ~200 orgs

"Am I eligible for GSoC?" and "which GSoC project fits me?" are different questions. **v1 answers only the first** — track the programme, its window, and link to the org list. Org-level matching is a genuine v2 feature and the existing embeddings would serve it directly.

**Research programmes.** CERN, DAAD RISE, MITACS Globalink, ETH/EPFL summer research, Max Planck. University and lab pages, annual cycles, hard deadlines, frequently nationality-gated. ~15 that matter. Handled identically to fellowships.

**Grants.** v2, and correctly deferred. Grants don't ask *are you eligible*, they ask *does your work fit the theme* — which is a match, not a filter. They also gate on **artifacts you possess** rather than attributes you are: an existing open-source project, a publication, a registered organisation. That is exactly why §8's parse captures `projects[].themes` and the `artifacts` booleans. Cheap to implement, hard to *verify*, which is the real reason it waits.

### 10.3 How `programs.json` gets built and kept correct

Assembling the ~50 names is a research task an AI agent with web search does well — an hour, not a day. Maintaining the **dates** is where it becomes dangerous.

**Hard rule: the model may read, never recall.** Asking a model "when does GSoC 2027 open" produces a confident invention. A wrong programme deadline is worse than no deadline, because the user trusts it and misses the real one — and unlike a wrong job verdict, they cannot discover the error by clicking through.

So the maintenance loop mirrors Tier 2 exactly:

1. Store the official URL per programme.
2. Fetch that page on a schedule.
3. Extract dates **from the fetched text**, with the quoted sentence kept as evidence.
4. Show `last verified: N days ago` on every programme row, always visible.
5. If the page can't be read, the programme keeps its last known window and is clearly marked stale — never silently re-dated.

Under those constraints Layers 2–4 are largely automatable after the first pass, which is a correction to the earlier assumption that it required permanent hand-typing. What it does *not* become is trustworthy without the fetch step.

---

## 11. Multi-language title matching

European and Japanese boards don't use English career-stage words. Miss these and SAP, Siemens, Zalando, Rakuten and Mercari all look empty:

| Market | Terms |
|---|---|
| Germany / Austria / Switzerland | `Praktikum` (internship), `Werkstudent` (part-time student), `Praktikant`, `Absolvent` |
| UK / EU | `graduate programme`, `graduate scheme`, `placement year`, `industrial placement` |
| Japan | `新卒` (new graduate), `インターン` (intern), `インターンシップ` |
| France | `stage`, `stagiaire`, `alternance` |

Just a keyword list, but it's the difference between covering Europe and not.

---

## 12. The website

Four screens. No marketing pages — the app is the landing page.

### 12.1 Screen 1 — Drop

One screen, no scroll. Above the drop zone:

1. The promise, one line
2. The privacy statement, plainly and completely: read during your session, never saved on our servers, text sent to an AI provider that doesn't retain it, nothing kept outside your own browser (§14.2)
3. **Live proof from the Lake** — real counters: `1,847 openings confirmed live in the last 6 hours · 214 programmes tracked · 38 programme deadlines this month`. Cheap, and it's what makes the upload feel safe. The first counter is the promise from §4.1 stated as a number; note it says *confirmed live*, not *verified*, because that is exactly what the sweep proves.
4. The drop zone

Note the reference site (unsiloed.ai) puts its upload at the *bottom*, after earning trust with a benchmark. Asking a stranger for a resume as their first interaction is a trust problem — those three elements above the zone are the minimum that earns it.

Escape hatch: "no resume? fill it in manually."

### 12.2 Screen 2 — Scan (the trust moment)

Real extracted values resolving as they're found: skills as chips, `graduation: May 2027`, `experience: 0 years`, `location: Delhi-NCR`. Then `matching against 1,847 verified openings · 214 programs`.

Two rules:

- **Real duration only.** Parse takes ~3s, animation takes ~3s. No padding.
- **Real values only.** Every string on screen was actually extracted. No placeholder theatre.

Padded loaders are exactly the dishonesty this product positions against.

### 12.3 Screen 3 — Confirm (six questions, pre-filled)

Not a form to fill — a parse to confirm. Everything arrives pre-filled, so the common case is one tap, and extraction errors become visible and correctable instead of silently ruining results.

1. Graduation month + year — *pre-filled*
2. Years of experience (0 / <1 / 1–2 / 2+) — *pre-filled*
3. What you're looking for — multi-select: Big Tech · Quant/Finance · AI/ML/Data · Startup · Fellowships · India-first — *inferred, editable*
4. Where — city or Remote only — *pre-filled*
5. Remote-only, or open to relocating?
6. Open to roles needing visa sponsorship?
7. Company size — any / include smaller and lesser-known / startups only — *defaults to any*
8. Include long shots? — *defaults on*

Only 5–8 need real input. Nothing beyond this, or people bounce.

### 12.4 Screen 4 — Results

**Urgency first — but the right urgency for each kind of thing.** Measured on `jobs_memory.jsonl`, only **3 of 69 opportunities (4.3%) carried a deadline at all**, and all three were programs (two Google apprenticeships, one Wells Fargo quant programme). Greenhouse, Lever, Ashby and Workday expose no closing-date field; companies simply take a posting down. A deadline-sorted page is therefore sorted on a field that is empty 96% of the time.

Jobs have a different, real urgency: **how recently they appeared.** A posting first seen today has fewer applicants ahead of it, `first_seen` exists for 100% of rows, and it needs no inference. Freshness replaces deadlines for jobs; deadlines stay where they're genuine.

1. **`[ CLOSING SOON ]`** — **programs only**, real published deadline inside 14 days. Genuine scarcity, so it leads.
2. **`[ OPENING SOON ]`** — programs whose window starts shortly. Nobody else has this.
3. **`[ JUST POSTED ]`** — jobs first seen in the last 72 hours, newest first. This is the jobs-side urgency section and will usually be the largest of the top three.
4. **`[ STILL OPEN — YOU HAVEN'T APPLIED ]`** — max 3, from the browser's seen-list, with original first-seen date. Descended from the private system's stale-application nudge, which is one of its best features.
5. **`[ NEW SINCE YOU LAST LOOKED ]`**
6. **`[ VERIFIED ]`** — everything else eligible, ranked by skill match.
7. **`[ LONG SHOTS ]`** — postings that explicitly bar your batch, clearly marked. Shown because a resume still gets in front of someone. Never accompanied by any suggestion to misrepresent a graduation year.
8. **`[ COULD NOT VERIFY ]`** — blocked or JS-only pages, each with the one thing to check. A feature, not an apology.

Each row: organisation, exact title, official apply link, location and real remote policy with tier, one line on why it fits, and — the trust element — **one line on the exact evidence that makes you eligible** ("posting accepts 2027 graduates", "no experience requirement stated"), visible without hovering or expanding.

**The time element on each row is `posted 2 days ago · live 4h ago`**, not a countdown. Both halves are measured: `first_seen` and `last_verified_live`. A real deadline is shown *in addition* when the posting states one — which is mostly programmes. **Never render a countdown from an inferred deadline.** Guessing a closing date to make the page feel urgent is precisely the manufactured signal §13.7 forbids.


**Never-empty rule.** An empty page is a product failure; there is almost always something, just not at Google. But padding with ineligible roles is the dishonesty we're built against. So results **widen in clearly labelled steps** instead:

- nothing at big tech → `12 at smaller companies you may not know`
- nothing this week → `8 programs opening soon`
- nothing in your city → `15 remote, India-eligible`

Each widening is labelled as such. The only hard rule: never present something as eligible when it isn't.

---

## 13. UX and UI direction

Arrived at after four rejected attempts. The rejections were the useful part — see §13.6 for what failed and why, so it isn't repeated.

### 13.1 The UX decision: queue, not list

**The page is a queue with a list behind it, not a list.**

Filtering 2,104 postings down to 31 removes most of the work but not the *deciding*. A 31-row list still asks the user to read, compare, prioritise and choose. And the private system already proved where the real bottleneck is: `notion_upsert.py` tracks `stale_to_apply` (rows sitting in *To apply* for 5+ days), and the radar file mandates leading the report with those, above new finds, because "a queued verified role is worth more than a newly found one."

Discovery isn't the problem. **Unapplied verified opportunities are.** A list makes applying optional; a queue makes it the default path.

So: one opportunity at a time, ordered by the §12.4 sections — programme deadlines first, then freshest jobs — two actions, open the application or skip. Priority is never the user's problem. The full list stays one scroll below for people who want it.

### 13.2 The metaphor: an eligibility pass

Each opportunity is rendered as a **verified pass**, not a job listing. The eligibility receipt is literally a document certifying you're cleared to apply, so the card looks like one — tear line across the middle with punched notches, "ELIGIBILITY PASS" header, the four checks written out below the tear, then a stamp:

```
✓ Graduation year      2027 named explicitly
✓ Experience           None required
✓ Degree               Bachelor's in progress
✓ Work authorisation   India · not required
  4 of 4 checks passed — cleared to apply. No assumptions made.
```

**Failed checks are shown, not hidden.** The Google apprenticeship card reads 2 of 4, with start date and graduation year flagged amber and an honest note that the March 2027 start lands before a May 2027 graduation. A card that explains why something is a long shot is more useful than one that hides it — and it carries the hard rule: never restate a graduation date to fit.

This pattern is lifted from Tsenta's submission receipt (§16) and pointed at a stronger claim. Theirs proves the form was filled correctly. Ours proves you're allowed to apply.

### 13.3 Dashboard layout

The carousel is a module inside a dashboard, not a takeover screen.

- **Left column — "Do this next."** The pass carousel, ordered by the §12.4 sections — programme deadlines first, then freshest jobs — with the neighbouring card partly visible so the queue is legible. Below it a **filmstrip** of the whole queue (number, company, age or deadline) for jumping around; acting on a card greys its entry and adds a ✓. Below that the live collector feed.
- **Right column — context.** This scan's four numbers, programmes closing this week, opening soon with a link to all programmes, and boards swept in the last 6 hours.
- **Below — the full list**, with 4-pip check meters and category filters.

### 13.4 Show the machine working

Both reference sites (unsiloed.ai, tsenta.com) share one trait: **they don't show output, they show the machine working.** Tsenta embeds a terminal feed scanning career pages, a résumé diff with −/+ lines, and a receipt with a ✓ per field. Unsiloed shows "SCANNING & PARSING… Detected: 4 tables · 2 figures."

Applied here: the collector feed (`[06:00:07] workday/redhat … +2 eligible`), the counter counting up to 2,104, checks ticking in one at a time. All real values, never placeholder theatre.

### 13.5 Visual specifics

Light, near-neutral palette (`#F1F2F4` ground, white cards) — chosen because the light/blue/red palette was the one thing praised across attempts, and a dark acid-accent version was rejected outright.

- Accents: blue `#0B62F5` action · green `#0E8A4F` passed · amber `#B26A00` open question · red `#DC2B2B` urgency. Nothing else is coloured.
- SF Pro Display for headings with tight negative tracking; SF Mono **only** for data — dates, counts, IDs, field labels. Per Apple's own guidance, monospace is for tabular data, never prose. Using it for sentences was a specific early mistake.
- Tabular figures everywhere.
- shadcn/ui token names used verbatim so the design ports 1:1 to components.
- Motion: staggered check reveals, counter count-up, card advance on action, live feed. Only genuine published programme deadlines inside 48h pulse — never a job, because jobs have no deadline to be imminent about. Everything respects `prefers-reduced-motion`.

### 13.6 Four rejected attempts — do not repeat

| Attempt | What it was | Verdict |
|---|---|---|
| v1 | Clean list, hairline rules, monospace evidence blocks | "not up to the mark, very bad" |
| v2 | Grouped inset cards, monogram tiles, soft shadows | "very AI generic… not even made in 2026" |
| v3 | Dark full-bleed terminal instrument, acid lime accent | "more shitty" |
| v4 | Light, numbered sections, receipt + live feed, list layout | closer, but still a list |

Root causes, worth keeping:

1. **A list of cards is the generic AI-SaaS signature.** Rounded cards + soft shadows + grey body text + pill badges reads as every AI product shipped since 2023.
2. **"Minimal" was read as restraint.** Stripping things out produced *boring*, not *premium*. What was wanted was impact.
3. **Monospace prose looks like terminal output pasted into a page.** Heavy, hard to read, cheapens everything.
4. **The paradigm was never questioned.** Four passes restyled a spreadsheet. A spreadsheet has a ceiling on how good it can feel. Fixing the UX (queue, one card, receipt as hero) made the visual problem much easier.

### 13.7 Fixed constraints

- **Recency and liveness are the loudest elements.** `posted 2 days ago · live 4h ago` carries the urgency for jobs; a real published deadline carries it for programmes. Never a countdown from a guessed date (§12.4).
- **The eligibility receipt is always fully visible** — never behind a hover or expander. It's the trust mechanism.
- **No fake progress.** Animation duration matches real work.
- **Never imply auto-apply.** The button reads "Open the application," not "Apply."
- WCAG AA contrast, real focus states, keyboard navigation (`A` apply, `S` skip, arrows to move), semantic markup.

---

## 14. Public-audience requirements

Because this goes to strangers rather than the author, four things stop being optional.

**Never log resume content.** The "we never store your resume" claim must be literally true — which means no resume text in application logs, error traces, or crash reports. Log a request ID and a byte count, nothing else. This is the single easiest way to accidentally make the privacy claim false.

**Upload safety.** Hard file-size cap, PDF-only by content sniffing rather than extension, a page-count ceiling, and a timeout on parsing. Malformed PDFs are a real crash and resource-exhaustion vector.

**Rate limiting.** Per-IP limits on the parse endpoint. It's the only expensive endpoint and the obvious one to abuse.

**A plain privacy note.** Three sentences, not a legal wall: what's parsed, what's kept (nothing server-side), what's in your browser.

Plus basic monitoring — the productised descendant of `--check`: alert when a board that used to return jobs returns zero, when a scrape run fails, or when the parse error rate spikes.

### 14.1 Repository privacy and secrets

**The repo stays private.** §5.2 shows why it can: the ID-list liveness check puts a full sweep at ~3 minutes, so monthly usage is ~420 of GitHub Actions' 2,000 free private-repo minutes. The free tier is sufficient, so there is no compute reason to go public.

There are reasons not to go public, and "nobody knows the repo exists" is not a defence — **public repositories are crawled by automated secret scanners within minutes of creation**, regardless of whether anything links to them.

What a public repo would expose, worst first:

1. **Credentials.** `.jobs-config` in the private system holds `NOTION_TOKEN`. Committed once, it is harvested in minutes — and **git retains it in history forever** unless the history is rewritten. This is the only item on this list that is hard to undo.
2. **The Lake.** `jobs.json` is the output of paid Tier 2 extraction. Publishing it hands over the one genuinely expensive asset for free.
3. **The registry.** Lower loss than it appears, since §4 already concedes the tokens are scriptable.
4. **Evidence of scale.** A public repo openly sweeping ATS endpoints makes blocking or a takedown trivially easy to justify. §17 rejected LinkedIn scraping on terms-of-service grounds; the same standard argues for not advertising this.

**Required regardless of visibility:**

- `.jobs-config`, `.env` and any credential file in `.gitignore` **before** any code moves into a repo
- secrets in GitHub Actions secrets / platform environment variables, never in a tracked file
- GitHub secret scanning **and push protection** enabled — it blocks the commit rather than reporting the leak afterwards

**If the free tier is ever exhausted**, in order of effort: sweep platforms in parallel lanes (~6× faster, still polite per host, §5.2); drop to 12-hourly sweeps (halves usage); run the collector on local `launchd`, which is where it already lives; or a permanently-free small cloud VM. Going public with code while writing data to private object storage is a valid fifth option, but only after the free tier actually runs out.

### 14.2 Legality and data protection

Not legal advice, and worth real advice before this ever takes money. The substantive position:

**Safe — no real concern**

| Activity | Why |
|---|---|
| Common Crawl enumeration | a public dataset published explicitly for reuse |
| Public ATS JSON endpoints | the same URLs the employer's own careers page calls — no auth, no paywall |
| Company careers pages | published to be read, and traffic is sent back to them |
| University, government and programme pages | these want to be found |

**Moderate — proceed carefully.** Workday is historically less tolerant of automated access; keep volume low. Keka / Darwinbox / Zoho HTML is fine to read but never to reproduce in full.

**Do not use.** **LinkedIn and Naukri** — terms prohibit automated access and both have enforcement history. Their companies surface via Layer 1 regardless, so incremental value is near zero. Internshala and Unstop may be used sparingly for company *names* only, honouring `robots.txt`, and treated as optional. **Never any logged-in content** — the radar file's existing rule, kept.

**Operational rules that make good faith demonstrable**

- honest `User-Agent` naming the tool, **with a contact address**
- respect `robots.txt`; one request at a time per host, with a delay
- **honour takedown requests immediately**, and keep a permanent blocklist
- **never display a full job description** — title, company, location, official link, and one short quoted line of evidence. Facts plus fair quotation, not republication.
- keep `raw/` snapshots private; never publish the Lake (§14.1)
- always link to the original posting

**India's DPDP Act 2023 applies, and there is one real gap.**

A resume is personal data, and *processing* it triggers obligations even when nothing is stored. The design is mostly well-positioned — session-only, no server-side retention, the user actively initiates the upload. But:

**The resume text is sent to a third-party AI provider.** The planned privacy line — *"parsed in your session, never stored"* — is true and incomplete, because it does not disclose that transfer. That is a genuine compliance defect, and the fix is three sentences shown at the point of upload:

> Your resume is read during your session and never saved on our servers. To extract your details we send the text to an AI provider, which does not retain it. Nothing about you is stored anywhere except in your own browser.

Also required: state that the service is for users aged 18 and over. DPDP imposes stricter obligations for children's data, including verifiable parental consent, and that is not an edge case worth inheriting.

**Liability on eligibility claims** is low while the product is free — a wasted application is not damages. Keeping the pass card's wording factual (§13.2) is the mitigation. And **never-auto-apply removes the largest liability class entirely**: submitting applications on someone's behalf, potentially with embellished content, is where real exposure lives. Ruling it out permanently is the single best legal decision in the project.

---

## 15. Tech stack (beta)

Deliberately minimal. For ten users the backend is two Python files and a cron job; SQS, Lambda fan-out and pgvector are what you'd need at ten thousand.

| Layer | Choice |
|---|---|
| Collector | `scraper.py` on a GitHub Actions cron, 6-hourly — free. Wraps the existing `ats_fetch.py` / `ats_sweep.py`. |
| Store | `jobs.json` + `programs.json` + `raw/`. A few thousand rows filters instantly in memory. |
| API | `api.py`, FastAPI on Render — two endpoints: `POST /parse-resume`, `POST /match`. |
| Frontend | Vite + React + Tailwind + shadcn/ui on Cloudflare Pages. |
| Similarity | numpy dot product in memory. No vector database at this size. |
| Secrets | Platform environment variables. Never a plaintext config file in the repo. |

### 15.1 When to add complexity

Each row is a measurable trigger, not a guess. Until one fires, the work is imaginary.

| Add | Only when | Concrete signal |
|---|---|---|
| Object storage for `raw/` | a local folder becomes awkward — worth doing early-ish | thousands of files slow to sync |
| Postgres | the JSON file gets slow, or two writers collide | load time noticeable, or a corrupted write |
| pgvector | more than ~20k opportunities | numpy array no longer comfortable in memory |
| Parallel sweep lanes | wall-clock, not money | sweep approaches Actions' free minutes |
| A queue + fan-out workers | one sweep outlasts the gap between runs | **or any single run exceeds 15 min — Lambda's hard timeout** |
| Lambda / SQS / EventBridge | Render or Actions free tiers can't keep up | over 2,000 Actions min/month |
| Accounts | someone asks for email digests | actual request from a real user |

**On the queue row specifically:** the ID-list liveness design (§5.1) puts a sweep at ~3 minutes, so this trigger is far off. It would fire immediately under the naive design that re-downloads every description each sweep — ~15 minutes, which exceeds Lambda's timeout outright and forces EventBridge → SQS → parallel workers. Worth knowing that the architecture in §15.2 is a consequence of sweep duration, not a preference.

Every row is a real problem you'll recognise when you hit it. Until then it's imaginary work.

### 15.2 If AWS later

A defensible AWS shape exists, service by service:

| Piece | Service | Note |
|---|---|---|
| Collector schedule | EventBridge Scheduler | replaces the Actions cron |
| Collector work | Lambda | **15-min hard timeout** — fine at ~3 min/sweep |
| Fan-out, only if needed | SQS + parallel Lambda workers | one message per board; 10 workers turn 55 min serial into ~6 min |
| Store | S3 | `jobs.json`, `programs.json`, `raw/` — ~110MB, cents/month |
| API | Lambda Function URL | **not API Gateway** — two endpoints need none of its features, and it charges per million requests |
| Models | Bedrock | cheap-tier model for extraction, Titan Text Embeddings V2 (1,024-dim) for vectors |
| Frontend | S3 + CloudFront | static build |
| Secrets | **SSM Parameter Store** | free standard tier; Secrets Manager charges per secret per month for no benefit here |
| Alerts | CloudWatch Logs → metric filter → SNS | the board-dropped-to-zero alert of §14 |
| Postgres, eventually | **Neon**, not RDS | AWS has no free Postgres and RDS free tier expires after 12 months; pgvector needed past ~20k rows |

Lambda's free tier (1M requests, 400k GB-seconds/month) and SQS's (1M requests) both comfortably cover this workload, so an AWS migration would not increase cost — only token spend is material either way (§15.4).

Worth doing for the portfolio narrative and to point Emfirge at your own account. **Not worth doing first** — moving a working system to AWS is a weekend; building on AWS first costs two weeks before a single job is in the Lake.

### 15.3 AI usage — four calls, and where they run

| Use | Where | How often |
|---|---|---|
| Eligibility extraction from the posting | Half A, Layer 1 | once per posting *version* — new rows, plus the low single-digit % whose `content_hash` changed (§7) |
| **Reading pages that have no API** | Half A, Layers 2–4 | only when a watched page's hash changes — ~40 campus pages, Indian ATS pages and ~50 programme pages, checked weekly |
| Company size classification | Half A | once per company, ever |
| Skills embedding | Half A | once per posting version |
| Resume parsing | Half B | once per visitor |
| "Why this fits" blurbs | Half B | once per visitor (batched, top 20) |

**The page-reading row is not optional.** Layers 2–4 — campus pages, Keka/Darwinbox/Zoho, programme pages — expose no JSON. HTML plus one extraction call is the only way to reach them, and they are where the audience's best opportunities live (§1.1: the only two roles ever actually applied to came from Layer 2). Cost is trivial: ~90 watched pages checked weekly is a few hundred calls a month, and only changed pages trigger a call.

Only two run per visitor, whether there are 10 users or 10,000. Adding the entire grants feature added **zero** extra per-user calls — richer resume schema, same single call.

**Deliberately not AI:** matching, filtering, ranking, dedupe, seniority detection, deadline parsing, liveness. All plain code. The naive version of this product runs a model call per job per user — hundreds per visit instead of two.

**The one number that decides the bill:** how many new postings per day fall through Tier 1 and need a Tier 2 call. Write the patterns well and this stays small.

### 15.4 What it actually costs

Rates below are approximate and **must be re-verified before committing** (§20, open question 3). The formulas are the durable part; substitute current prices into them.

Assume a cheap-tier model at roughly **$1 per 1M input tokens / $5 per 1M output**, and embeddings at $0.02–0.20 per 1M.

**Per Tier 2 extraction** — a job description is ~5,500 tokens, the ruleset prompt ~1,500, output ~300:

```
(7,000 / 1M × $1) + (300 / 1M × $5)  =  $0.0085   ≈ 0.85¢ per posting
```

**Per visitor** — resume parse (~1,300 in / 300 out) plus one batched blurb call (~4,000 in / 800 out):

```
parse   $0.003
blurbs  $0.008
        ──────
        $0.011  ≈ 1¢ per visitor
```

**Correction to an earlier claim in this document:** per-visitor cost is approximately **one cent, not "fractions of a cent."** Roughly 3× the original estimate. Still negligible in absolute terms, but the doc should not overstate it.

If it needs to be lower, the blurb call is ~70% of it. Cut to the top 10, or compose the sentence from the stored `evidence` fields, and per-visitor cost drops to ~0.3¢ with no model call at all.

**Monthly, at 1,000 visitors:**

| Line | 65 boards | 300 boards |
|---|---|---|
| Tier 2 (new postings/day) | ~$13 | ~$60 |
| Embeddings | <$1 | ~$2 |
| Storage (~110MB) | ~$0.01 | ~$0.05 |
| Compute (Actions / Render / Pages free tiers) | $0 | $0 |
| Visitors | $11 | $11 |
| **Total** | **≈ $25/mo** | **≈ $73/mo** |

Two things to read off this. **Compute is free at both sizes** — the entire bill is tokens. And **tripling the registry roughly triples the only real cost line**, which is worth weighing against §18's ordering while the false-eligible rate is still unmeasured.

---

## 16. Competitors

### 16.1 Tsenta — the direct one

[tsenta.com](https://tsenta.com/) · YC-backed · ~$500K raised · verified 2026-07-29.

- Watches **50,000+ career pages** across Workday, Greenhouse, Lever, Ashby and 15+ more ATSes
- **Auto-applies** — tailors a résumé and cover letter per role and submits it, "hundreds of applications a week"
- Surfaces: web, iOS, Android, iMessage, WhatsApp, Chrome extension, MCP server + CLI
- Pricing $19 / $39 / $99 per month, metered by applications; first 25 free
- Positioning: *"Be the first to apply to every job that fits you. Hands off."*

**Where they beat us outright: coverage.** 50,000 pages against our 65 verified boards. Do not compete on this axis.

**Where they don't compete at all:**

- **No fellowships, grants or programs.** Their four-stage pipeline (find → prep → apply → track) has no concept of a window that opens in August. Nothing in it handles GSoC, Outreachy, CERN, or LFX. **The gap is product shape, not data difficulty** (§4): an AI agent could assemble the programme list in an hour, but there is nowhere in an auto-apply funnel to put an opportunity that opens in August, closes on a fixed date, requires an essay, and cannot be submitted on the user's behalf. Carrying programmes would mean building a second product with different economics — which is why the gap is likely to persist.
- **No eligibility verification.** They optimise for volume and speed-to-submit. They do not tell you whether the posting will accept your graduation year. Their match score is a fuzzy percentage; ours is a count of passed checks.
- **Opposite trust posture.** Their FAQ answers "Will recruiters know I used Tsenta?" with "No." We never submit anything and say so on the button.

**What this changes:**

1. **The market is validated.** People pay $19–99/month for this. That's genuinely good news for a product that was unsure anyone wanted it.
2. **Never-auto-apply flips from limitation to positioning.** We're the honest option in a category whose funded leader optimises for undetectable mass submission.
3. **It sharpens the roadmap.** Fellowships, grants and the eligibility receipt are uncontested. Broad coverage of standard software jobs is where we lose.

### 16.2 The commodity tier

Simplify, JobRight, Sonara and similar: resume-in → ranked-jobs-out. This is why "upload your resume, get matching jobs" is the wrong pitch (§4).

### 16.3 The real competitors, given an Indian audience

Tsenta is largely irrelevant to Indian B.Tech students — US-focused, and auto-applying to US jobs. The actual alternatives this product is measured against:

| Competitor | Strength | Gap |
|---|---|---|
| **Unstop** | huge Indian student mindshare, competitions + internships | no eligibility verification |
| **Internshala** | default destination for Indian internships | volume over accuracy; no grad-year checking |
| **LinkedIn** | everything is there | filtering entirely on the candidate |
| **College placement cells** | the primary channel for most students | on-campus only; nothing off-campus |
| **Telegram / WhatsApp groups** | where off-campus openings actually spread, fastest | unstructured, unverified, no memory |

**None of them verify eligibility, flag dead postings, or say whether a campus role is applicable off-campus** (§9, `access_channel`). That is the opening.

**But they all have distribution and this product has none.** That is the honest asymmetry, and it is a harder problem than any of the engineering in this document. No marketing pages plus no SEO surface (§12) plus no email (§20, open question 6) means there is currently no answer to "how does anyone arrive?" — beyond the author's own friends, which is a legitimate start for users one through five.

---

---

## 17. Cut from v1

**Twitter/X and LinkedIn founder-post listening.** The most exciting feature and the worst first investment: X API v2 filtered stream starts around $200/month, and LinkedIn post scraping via SerpAPI is metered *and* against their terms, which they litigate. Revisit when something is working.

**Grants** ship in v2, after thematic matching is proven on fellowships. They're the fewest and hardest to verify.

**Rotation slices.** Needed today because an agent can't cover 300 boards in one session. A script has no such limit and sweeps everything every run. The constraint disappears.

---

## 18. Build order

Discovery before interface. An empty Lake makes a beautiful UI worthless — but §1.1 showed that *curating* discovery is what was empty, not discovery itself.

1. **Secrets hygiene** — `.gitignore` credential files, enable GitHub secret scanning and push protection (§14.1). Five minutes; the only irreversible mistake on this list.
2. **Registry bug fixes** — `dead`/`empty` states, reclassify Citadel, drop the ClickHouse duplicate, add Recruitee and Workable (supported, zero boards, and the only *Apply now* India role found was on Recruitee).
3. **The resolver** — company name → board token via careers-page redirect. Layers 2, 3 and 5 all depend on it; it is the most reused code in the project.
4. **Layer 1** — enumerate the 8 platforms from Common Crawl, apply the three location buckets (§5.4), tier boards by yield. One weekend, replaces the entire old six-phase registry plan.
5. **Layer 5** — point the growth loop at YC and Internshala. The registry starts growing unattended.
6. **Collector proper** — Tier 1 patterns written against the §4.1 rejection table, then Tier 2 extraction and embeddings.
7. **Layer 4** — type the ~50 programmes with official URLs so the §10.3 watch loop can maintain them. India-weighted: GSoC, C4GT, IAS SRFP, IIT/IISc, ISRO, Outreachy.
8. **Layer 2** — the ~40 campus pages. Where the only two real applications came from.
9. **Layer 3** — Keka / Darwinbox / Zoho as HTML, not JSON.
10. **Measure accuracy** — false-eligible on 200+ verdicts, false-ineligible on 50 rejected rows (§7.1). **Gate before any UI work.**
11. **API** — two endpoints, no auth, no storage.
12. **Website** — the four screens. Smallest phase.
13. **Beta** — the author and friends first, then 10 strangers. Measure one thing above all: what fraction of surfaced opportunities were genuinely eligible *and* applicable off-campus.

Steps 3–5 are roughly a weekend and produce the number nobody currently has: how many India-eligible early-career engineering roles actually exist at once.

### 18.1 Unresolved: how much breadth before the accuracy gate?

Enumeration (step 4) makes board count nearly free, which removes the *labour* argument for stopping early. The error-multiplication argument survives, but with a distinction worth being precise about: **board count is not what gets audited.** The gate is 200 hand-checked *verdicts*, and that stays constant whether the Lake is built from 65 boards or 5,000.

So: enumerate wide because it is cheap, and still do not ship until step 10 produces a number.

The genuine unknown is yield, not breadth. It is currently July — the seasonal trough, since summer internships post August–November — so neither the 22-board sample in §1.1 nor anyone's intuition is reliable. **Worth scheduling: re-run the §1.1 measurement in October.** If India early-career engineering roles on enumerated boards are still near zero at peak season, Layers 2–4 become the entire product and Layer 1 is permanently demoted to a supporting role.

---

## 19. Honest assessment

**As a public tool and portfolio piece:** strong. Real infrastructure, a problem the author actually has, and a verification layer that's genuine engineering rather than an API wrapper.

**As a business:** students don't pay. If revenue ever matters, the buyer is university placement cells purchasing verified-eligibility feeds. Decide before sinking months in.

**Main risks:**

- **Coverage cold-start.** Little to show at low board counts. Mitigated by the programme calendar, which delivers value at ~20 rows, and by the never-empty rule's labelled widening (§12.4). Note the tension with §18.1: coverage argues for scaling the registry early, accuracy argues for measuring first.
- **Eligibility accuracy.** A wrong "eligible" kills the pitch. Mitigated by rules-before-models, a 200+ verdict audit including the false-*ineligible* side, Tier 1 sampled through Tier 2, and a visible unverified bucket (§7.1).
- **Silent board death.** Tokens die, JSON shapes change, and a board can return HTTP 200 with an empty array forever. Mitigated by the `dead`/`empty`/`verified` distinction and by alerting on *drops* rather than errors (§14).
- **Stale certification.** The pass card asserts eligibility from stored text. Mitigated by weekly `content_hash` re-reads and by showing `live 4h ago` rather than implying continuous verification (§7).
- **Programme dates going wrong.** A bad deadline is worse than no deadline, and the user cannot detect it. Mitigated by the read-never-recall rule and a visible `last verified` stamp (§10.3).
- **Leaked credentials.** The one irreversible operational mistake. Mitigated by §14.1 — private repo, `.gitignore`, push protection.
- **Scope creep into "we apply for you."** Tempting; destroys the trust position and creates real liability. Never-auto-apply stays a permanent principle, not a beta limitation.

---

## 20. Decisions log

**Locked:**

- Name: **Opportunity Lake** (folder renamed 2026-07-29)
- Audience: **public and India-first** — Indian B.Tech students, author and friends as users 1–5 (§1)
- Scope: jobs + internships + fellowships in v1; **grants in v2**
- **Long shots shown by default**, tagged, with failed checks visible — never a suggestion to misstate a graduation date
- Beta state lives in **browser localStorage**; nothing server-side
- **Never-empty rule** — widen in labelled steps, never pad with ineligible roles
- **Urgency = freshness for jobs, real deadlines for programmes** (§12.4). `deadline` was populated on 4.3% of the private store and only for programmes; no countdown may ever be inferred.
- **"Confirmed live within 6 hours" is a lead promise** — deadness caused 11 of 25 real rejections (§4.1), and detecting it needs no AI.
- **Tier 2 runs once per posting *version*, gated on `content_hash`** (§7) — resolves the old "once ever" vs. silent-edit-detection contradiction at negligible cost.
- **The §4.1 rejection log is the Tier 1 test set** — patterns are written against real observed gates, not imagined ones.
- **Liveness comes from the board's ID list, not from re-downloading descriptions** (§5.1). One request per company, ~3 min/sweep. Descriptions are fetched for new IDs only; the silent-edit re-read runs weekly.
- **Repo stays private** (§14.1). The free Actions tier covers ~420 of 2,000 minutes/month, so there is no compute reason to publish. Secret scanning and `.gitignore` for credential files are required regardless.
- **Five discovery layers** (§5.3), not one curated registry — enumerate boards, watch campus/Indian-ATS/programme pages, and grow the list automatically. `jobs.json` machine-filled, `programs.json` human-assembled then page-watched. Users see one list.
- **Filter jobs by India-eligibility, never curate companies** (§1.1, §5.4). The registry is an output, not an input. Three location buckets: India-located, India-eligible remote, global-hiring.
- **For programmes, the model may read but never recall** (§10.3) — dates are extracted from a fetched page with `last verified` shown, never generated from model memory.
- **Programmes are uncontested because of competitor product shape, not data difficulty** (§4, §16.1) — an AI agent can find them; an auto-apply funnel has nowhere to put them.
- **The board registry is infrastructure, not a moat** (§4) — careers-page redirects make tokens scriptable.
- **Registry is enumerated, never curated** (§1.1, §5.3). Common Crawl gives the token universe; boards are tiered by yield; the company list is an output.
- **`access_channel` (off-campus vs campus-only) is tracked** (§9) — three real rejections turned on it and no Indian competitor answers it.
- **Layers 2–4 need an HTML page-reading AI adapter** (§15.3). Campus, Indian-ATS and programme pages have no JSON, and they hold the audience's best opportunities.
- **Keka/Darwinbox/Zoho are readable as HTML**, contrary to the earlier "no public JSON" blocker — a live scan read Zenskar's Keka page correctly (REGISTRY-PLAN §3.3).
- **LinkedIn and Naukri are excluded** from lead harvesting on terms-of-service grounds (§14.2); their companies surface via Layer 1 anyway.
- **The privacy notice discloses the AI provider** (§14.2). "Parsed in your session, never stored" was incomplete under DPDP 2023; resume text leaves for a model provider and that must be said.
- **Rotation stays removed** — and for a second reason: on 2026-07-31 the Slice-1 rotation spent an entire scan on Big Tech + Quant and returned six overseas roles with zero India results. It allocated attention by category instead of by actionability. Do not reintroduce it as "balanced results across categories."
- **Germany / Switzerland / Japan registry expansion is cut** — it served the author's personal visa-market interest, not the audience.
- **Accuracy audit is 200+ verdicts plus 50 rejected rows** (§7.1), not 30. Tier 1 is sampled through Tier 2 to catch pattern rot.
- **Queue-first UX** (§13.1) with the full list one scroll below
- **Eligibility-pass card** as the core UI object (§13.2)
- Dashboard layout: carousel + filmstrip + side context + full list (§13.3)
- Light palette, blue/green/amber/red accents; SF Mono for data only (§13.5)
- No marketing landing page — the app is the landing page
- Stack §15; social listening deferred §17; rotation removed
- **Never auto-apply** — permanent product principle, not a beta limitation

**Open:**

1. **Portfolio project or business?** Still the biggest unanswered question. Tsenta's existence (§16) makes the business case more real *and* the competition harder.
2. Domain and final wordmark.
3. Model choice and current pricing — **verify before committing.** §15.4's arithmetic assumes roughly $1/$5 per million tokens; the formulas hold, the rates may not.
4. Whether skip should ever become permanent (currently "not now" only).
5. **Actual India yield** — how many India-eligible early-career engineering roles exist at once? Unknown, and July is the trough. Layers 1 and 5 answer it in two weeks; re-measure in October (§18.1).
6. **Retention.** localStorage-only means `[OPENING SOON]` — the most novel output (§10.2) — only reaches users who happen to visit in the right week. Email would fix it and would cost the "nothing server-side" claim. Unresolved.
7. **GSoC org-level matching.** Programme-level tracking ships in v1; matching against ~200 orgs inside a programme is a separate feature (§10.2).

**Next steps:** see §18 build order. The first three are secrets hygiene, the registry bug fixes including Recruitee/Workable, and the name→token resolver.
