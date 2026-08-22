# Xlake source registry

A simple list of the source platforms and official pages Xlake uses or plans to
use. Individual company boards are stored in the collector registry data.

## Audience rule

Jobs and Internships are India-first and technical: they target students and early-career candidates in India. Every other category is worldwide and open to anyone, anywhere: Open Source (programmes and good-first-issues), Fellowships, Research programmes, Grants & Funding, Scholarships, and Hackathons & Competitions. Never apply an India or other location filter to these worldwide categories; record each opportunity's own eligibility from its official page instead. Open-source programmes in particular are global.

## Opportunity categories

Jobs and Internships are the India-first, technical part of this catalog (students and early-career candidates). All other categories are worldwide and open to anyone (see the Audience rule above). For the listing categories (Jobs and Internships), the engine keeps a comprehensive global index rather than hiding non-India roles: India-located and remote/global opportunities are surfaced first for an India-based user, while foreign on-site roles are retained and searchable behind a filter, ranked lower by accessibility. These types are user-browseable categories and are distinct from collection sources and adapters.

- **Jobs** — entry-level/early-career full-time — good enough; India tech roles surface through the shared `india_source` machinery, and we are not grinding more employers by design
- **Internships** — student, summer, off-cycle, industrial training — LIVE via the Unstop public feed, `india_source` machinery, hand-audited registry companies, and the zshah101 community tech-internship list (MIT, official ATS apply links only, US Summer 2027 + Fall 2026, deduped and accessibility-ranked)
- **Apprenticeships** — structured work-and-learning; a standalone category — not yet implemented
- **Graduate & Campus Programmes** — GET, campus hiring, new-grad cohorts, rotational — not yet implemented
- **Fellowships** — structured/selective learning, work, or research — not yet implemented
- **Research Opportunities** — worldwide research internships, fellowships, and summer research programmes for students & early-career (e.g. Mitacs Globalink, DAAD RISE, CERN/DESY Summer Student, Amgen Scholars, Caltech SURF, ETH/EPFL summer fellowships, RIKEN IPA) — IN PROGRESS (worldwide, open to anyone, anywhere); calendar programmes on the shared programme engine; 9 verified seeds, first evidence-backed programme live (Mitacs Globalink)
- **Open Source Opportunities** — mentorship, paid OSS internships, contributor programmes, issue-based pathways — LIVE and actively collected (calendar programmes + listing good-first-issues); hero category
- **Grants & Funding** — project, student innovation, creator, startup, research funding — not yet implemented
- **Startup & Founder Programmes** — accelerators, incubators, founder/student-founder programmes, founder fellowships, pre-accelerators — not yet implemented
- **Community & Leadership Programmes** — campus ambassadors, communities, leadership cohorts, developer communities, volunteer leadership — not yet implemented
- **Scholarships** — student funding and scholarship calls — planned / not yet built
- **Hackathons & Competitions** — worldwide upcoming/open build-and-ship hackathons with official links and dates (Devpost + MLH + Unstop) — IN PROGRESS (worldwide, open to anyone, anywhere); structured live-source collector, fresh daily, keyed by official URL; ~348 upcoming surfaced in first run

Learning-to-Opportunity Programmes remains deferred. Categories marked not yet
implemented remain under that disclaimer; this is focus, not a statement of
importance. Category-specific inclusion criteria, evidence, liveness/deadline
rules, collection status, and priority will be defined one category at a time.

## Collection method by category
Each category is either calendar (application windows, prose pages, few slow-changing sources; collected by engine plumbing + AI reading) or listing (high-volume structured data; engine only).

| Category | Type | Collection |
|---|---|---|
| Jobs | listing | engine (boards/APIs) |
| Internships | listing | engine (boards/APIs) |
| Apprenticeships | listing | engine (boards/APIs) |
| Graduate & Campus Programmes | calendar | engine + AI reading |
| Fellowships | calendar | planned / not yet built |
| Research Opportunities | calendar | engine + AI reading |
| Open Source Opportunities | calendar (programmes) + listing (good-first-issues) | engine + AI for programmes; engine-only GitHub collector for issues |
| Grants & Funding | calendar | planned / not yet built |
| Startup & Founder Programmes | calendar | engine + AI reading |
| Community & Leadership Programmes | calendar | engine + AI reading |
| Scholarships | calendar | planned / not yet built |
| Hackathons & Competitions | calendar | planned / not yet built |

Open Source contributions (good-first-issues) are collected from curated repositories plus token-gated GitHub search; stale and over-commented issues are dropped, with a 7-day reconfirmation window.

The one canonical lake holds three record types: jobs (no `record_type`), programmes, and contributions. Region-excluded roles are retained in hidden records with `region_excludes_india`, not deleted.

Currently active categories: Open Source (LIVE and actively collected),
Internships (LIVE), and Jobs (good enough). Fellowships, Grants & Funding,
Scholarships, and Hackathons & Competitions are planned / not yet built;
category scaffolding is not actively collected. AI verification for active
calendar programmes runs ~2x/month; the engine sweep runs once a day.

## Future category-work convention

`engine/categories/` may contain structural scaffolding for category predicates,
annotations, and category-specific processing helpers. Scaffolding alone does
not activate a category or claim collector support, and it must not own a final
database. Do not create a category contract document or implementation stub
until work on that category has explicitly begun; when it begins, keep its
requirements in one canonical Markdown document for that category.

The shared collector remains `engine/`. Category documents define category
scope, evidence, liveness, deadline, and acceptance requirements; they do not
duplicate or replace shared fetch, sweep, storage, or trust logic. Only one
category is actively worked on at a time, and each document must cover:

- scope, inclusion, and exclusions
- official-source and evidence requirements
- liveness and deadline rules
- candidate sources and collection gaps
- acceptance gate
- implementation and status evidence

The category catalog is a roadmap for the statuses above. Categories marked
not yet implemented are not claimed as supported by the scaffold or by this
convention.

## Active sources

- **Greenhouse** — official company ATS boards — jobs and internships — active
- **Lever** — official company ATS boards — jobs and internships — active
- **Ashby** — official company ATS boards — jobs and internships — active
- **Workable** — official company ATS boards — jobs and internships — active
- **Workday** — official company ATS boards — jobs and internships — active;
  pagination needs care
- **Keka** — official Indian company career boards — public API — active
- **Eightfold** — official company ATS boards — jobs and internships — active
- **SuccessFactors** — official company ATS boards — jobs and internships —
  active
- **Unstop** — official opportunity platform/API — active

## Planned sources

- **Additional university and research-lab pages** — official research programmes — planned
- **Government scholarship and grant pages** — official programmes — planned
- **Additional fellowship, scholarship, and hackathon pages** — official programme pages — planned

Open Source programme sources, including Google Summer of Code, are already
tracked in the 41-source worklist at
`engine/categories/open_source/OPEN_SOURCE.md`; they are not merely planned.

## Not used

- LinkedIn
- Naukri
- Wellfound
