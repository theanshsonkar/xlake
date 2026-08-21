# AGENTS.md - how to work on Opportunity Radar

Read this first. It tells any AI chat how to work on this project.

## Read order
1. LAKE.md - what the product is and why.
2. REGISTRY-PLAN.md - the list of categories and their status.
3. ENGINE.md - how the engine works (the whole picture).
4. The category's own doc, e.g. engine/categories/open_source/OPEN_SOURCE.md - your worklist for this chat.

## The one rule
Work on ONE category per chat. Do not spread across categories. The category doc is your worklist and your memory.

## Audience
Jobs and Internships are India-first and technical (students and early-career candidates in India). Every other category - Open Source (programmes and good-first-issues), Fellowships, Research programmes, Grants & Funding, Scholarships, and Hackathons & Competitions - is worldwide and open to anyone, anywhere. Never apply an India or location filter to these worldwide categories; capture each opportunity's own eligibility from its official page. Open-source programmes in particular are global.

## Two kinds of categories
Categories are collected in one of two ways:

- Calendar/programme categories - Fellowships, Research programmes, Open Source programmes, Grants & Funding, Scholarships, Hackathons & Competitions, Startup/Founder programmes, Community & Leadership programmes, Graduate & Campus programmes. They have application windows/deadlines and prose pages, with few official sources that change slowly. Collected by: the engine for fetching, liveness, dedup and storage, PLUS AI to read each page and extract dates/eligibility/funding. AI rule: only record what you can quote from the official page; never invent a date; a failed or unclear read never closes a row. Because these are low-volume, AI verification runs about twice a month (a human-in-the-loop AI does it until an API key is configured).
- Listing categories - Jobs, Internships, Apprenticeships, and OSS good-first-issues. High volume, structured data (job boards / APIs / GitHub), collected by the engine only. Internships and OSS good-first-issues are now actively collected.

Schedule: the engine runs once a day for liveness/freshness. The daily sweep also runs the Open Source programme and contribution collectors, then makes one atomic commit covering all record types and pushes; the page-reader commits and pushes separately.

## Guardrails
- Never fabricate opportunities, sources, dates, or eligibility. Every row needs an official source URL and evidence from that page.
- Do not change shared engine code (engine/core/, engine/adapters/, engine/pipeline/, trust logic) during category work. If you believe shared code must change, STOP and tell the human.
- Use the one canonical lake: engine/data/lake/opportunities.json. Never create a second database for a category.
- Never access or republish LinkedIn or Naukri. Never show a full description - link to the official source.
- A failed, blocked, or partial read is not a closure. Only a successful read updates liveness.
- On divergence, use git pull --rebase to keep the daily bot's data commits and replay our commits on top. Never use merge -s ours (it discards the bot's data) and never force-push.

## Per-chat loop
1. Open the category doc; read its status and source worklist.
2. Pick the next source(s) needing collection/verification or reconfirmation.
3. Collect from the official source with evidence; verify.
4. Merge results into the canonical lake.
5. Update the category doc: mark sources collected/verified/blocked, update counts and a short 'last worked' note.
6. Stop. Leave the doc clean for the next chat.

## Where things live
- engine/core/ - shared engine code
- engine/adapters/ - source integrations
- engine/pipeline/ - run scripts (run as `python3 -m pipeline.<name>` from engine/)
- engine/categories/<category>/ - one folder per category: its code + its <CATEGORY>.md doc
- engine/data/lake/opportunities.json - the one canonical lake

## Commands (run from engine/)
- `python3 -m pipeline.sweep`
- `python3 -m pipeline.fetch greenhouse vercel`
- `python3 -m pipeline.resolve --file data/operations/companies.txt`
- `python3 -m pipeline.read_url URL`
- `python3 -m pipeline.build_fixtures check`
- `python3 -m categories.open_source.programmes`
- `python3 -m categories.open_source.contributions`
- `python3 -m categories.internships.internships`
- `python3 -m unittest tests.test_robots`

Contribution discovery uses the `GITHUB_TOKEN` environment variable (from a
`GH_PAT` secret in CI, else the built-in token). Without it, only curated
repositories are collected.

## When things change
Update ENGINE.md when the engine changes. Update a category's doc when its coverage changes.
