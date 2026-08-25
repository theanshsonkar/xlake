# Jobs / Boards — state & parked work (as of 2026-08-25)

## State
Discovery graph is live. `registry.json` holds ~1,417 boards (Keka, Greenhouse, Workable) — auto-discovered, verified live, located, named. 21 staffing agencies permanently rejected (`discovery_rejected.json`, skipped by future admission). 6 opaque boards held for review (`discovery_review.json`). Admitted boards' jobs flow into the lake on daily sweeps.

## Left to do (parked)
1. **More ATS platforms:**
   - **Recruitee** — one-line adapter fix: in `engine/adapters/boards.py` Recruitee branch (~L982–1000), map `company = offer.get("company_name")`. Location already works → then admit-ready. (Mostly European SMBs.)
   - **Ashby** — location works, but the posting API has NO company name; needs enrichment (parse `jobs.ashbyhq.com/<token>` page title, like Keka). High-value tech cos (OpenAI, Notion).
   - **Workday** — supported but complex (composite host|tenant|site tokens, pagination, read-completeness). Big enterprises. Own careful effort.
   - **Lever** — no Common Crawl token source in `enumerate_boards`; needs another discovery route.
2. **CI enumeration** — `enumerate_boards` (Common Crawl) can't run interactively (~30 min+). Add/extend a CI job (model on `discovery-refresh.yml`) to run enumeration and populate `discovery-cache`. Prerequisite before admitting any new platform.
3. **6 held boards** (d2b-1, digital-368, fuku, gramian, icbd-holdings, lago-1) — opaque names; await AI classifier to admit/reject.
4. **Keka names** — 201 boards use cleaned-token fallback (Keka SPA exposes no real name without JS). Await AI or alternate source.
5. **Jobs backstop (core, optional)** — liveness is disappearance-based; a board that stops being swept never flips `is_live=false` (only the 180-day surfacing cutoff hides it). Consider age-based expiry in `sweep.py`. Shared-core change → needs approval.
6. **Screen tuning** — the outlier job-count flag (≥200) over-flags big legit employers; the real agency signal is name-based. Tune thresholds / lean on name patterns + future AI.
7. **Verify post-sweep** — confirm the ~1,417 admitted boards collect correctly, and that Workable jobs get India/foreign tags from the location fix, on the first daily sweep after 2026-08-25.
