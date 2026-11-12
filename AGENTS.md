# AGENTS.md — Xlake engine

Rules for any AI working in this repo. Also follow `CLAUDE.md`.

Full design docs, plans and category worklists are private. If you have the private notes repo
cloned next to this one, read `../xlake-frontend/notes/README.md` and `../xlake-frontend/notes/engine/` first.
Never add plans, audits, strategy or known weaknesses to this public repo; they go in the private notes.

## Working rules
1. **Build cleanly.** Modular code, proper architecture, separation of concerns. Never bolt a feature on.
   If a clean build needs a refactor, stop before doing the work and say so.
2. **Make implicit state machines explicit**, improving UX, DX and AX together without breaking anything.

## Guardrails
- Never fabricate opportunities, sources, dates or eligibility. Every row needs an official source URL and evidence from that page.
- A failed, blocked or partial read is not a closure. Only a successful read updates liveness.
- Never access or republish LinkedIn or Naukri. Never show a full description; link to the official source.
- Never create a second database for a category. The canonical lake lives in S3; Supabase is the serving projection.
- Ask the human before changing shared engine code (`engine/core/`, `engine/adapters/`, `engine/pipeline/`, trust logic).
- On divergence use `git pull --rebase` to keep the daily bot's data commits. Never `merge -s ours`, never force-push.

## Layout
- `engine/core/` shared code · `engine/adapters/` source integrations · `engine/pipeline/` run scripts
  (`python3 -m pipeline.<name>` from `engine/`) · `engine/categories/<category>/` category code ·
  `engine/data/` local working data (lake files are not committed).
