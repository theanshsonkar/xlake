# CLAUDE.md — Xlake engine

Also read `AGENTS.md`, `ENGINE.md` and `LAKE.md`.

## What this repo is
The data engine behind xlake.site: Python 3.12, standard library only, **no LLM/API keys** (deterministic crawling and parsing). It writes per-category shards to S3 and publishes to the Supabase table `opportunities`. The frontend is `theanshsonkar/xlake-frontend`.

## How we work
- The main model plans, researches and reviews. Delegate coding, reading and writing to subagents with model **Sonnet** at **low** effort.
- Work directly on `main` (no branches/PRs). Before every push: `cd engine && python3 -m unittest discover -s tests` must pass, then `git pull --rebase origin main && git push origin main`.
- **Always dry-run before a live run**, and ask the user before any live run that writes data (S3/Supabase), especially with `retire_force`. Report keep/retire counts per category first.
- Category workflows: `hackathons` (every 6h), `fellowships`, `scholarships`, `grants`, `research`, `open-source`, `startup`, `community` (daily) — dispatch with `gh workflow run <name> -R theanshsonkar/xlake -f dry_run=true|false`.
- Jobs/internships: `sweep.yml` (matrix legs; `-f platform=<leg>|all`). Only ONE sweep run at a time — overlapping dispatches cancel each other.
- A source must never retire rows unless its read is verifiably complete. Treat a source returning 0 rows (or a sharp drop) as failed.
- Never bypass bot protection or robots.txt; be polite (delays, caps).
- Never change the board registry (`engine/data/operations/registry.json`) without the user's explicit OK.

## Data rules
- Official-first: store the organiser's official page and real application link; aggregators (Unstop, Devpost, …) are discovery sources (`source_kind`, `listed_on`).
- A company/organiser name or logo must never be an aggregator or job board.
- Don't copy long descriptions: store facts plus a neutral 1–2 sentence summary (≤ 300 chars).
- Past-deadline rows must not be served unless they are `upcoming` (next cycle).
- Never store personal emails/phones of organisers or users.
