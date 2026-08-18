# Xlake source registry

A simple list of the source platforms and official pages Xlake uses or plans to
use. Individual company boards are stored in the collector registry data.

## Beta opportunity types

This is the India-first beta catalog for students and early-career candidates. Global opportunities are included only when explicitly accessible to applicants in India. These types are user-browseable categories and are distinct from collection sources and adapters.

- **Jobs** — entry-level/early-career full-time
- **Internships** — student, summer, off-cycle, industrial training
- **Apprenticeships** — structured work-and-learning; a standalone category
- **Graduate & Campus Programmes** — GET, campus hiring, new-grad cohorts, rotational
- **Fellowships** — structured/selective learning, work, or research
- **Research Opportunities** — research internships, assistantships, labs, student research calls
- **Open Source Opportunities** — mentorship, paid OSS internships, contributor programmes, issue-based pathways
- **Grants & Funding** — project, student innovation, creator, startup, research funding
- **Startup & Founder Programmes** — accelerators, incubators, founder/student-founder programmes, founder fellowships, pre-accelerators
- **Community & Leadership Programmes** — campus ambassadors, communities, leadership cohorts, developer communities, volunteer leadership

Only Learning-to-Opportunity Programmes remains deferred; this is focus, not a statement of importance. Scholarships and Hackathons & Competitions were promoted into beta on 2026-08-18 (strong fit for the student audience). Category-specific inclusion criteria, evidence, liveness/deadline rules, collection status, and priority will be defined one category at a time; no category should be understood as currently implemented or collectible.

## Collection method by category
Each category is either calendar (application windows, prose pages, few slow-changing sources; collected by engine plumbing + AI reading) or listing (high-volume structured data; engine only).

| Category | Type | Collection |
|---|---|---|
| Jobs | listing | engine (boards/APIs) |
| Internships | listing | engine (boards/APIs) |
| Apprenticeships | listing | engine (boards/APIs) |
| Graduate & Campus Programmes | calendar | engine + AI reading |
| Fellowships | calendar | engine + AI reading |
| Research Opportunities | calendar | engine + AI reading |
| Open Source Opportunities | calendar (programmes) + listing (good-first-issues) | engine + AI for programmes; engine-only GitHub collector for issues |
| Grants & Funding | calendar | engine + AI reading |
| Startup & Founder Programmes | calendar | engine + AI reading |
| Community & Leadership Programmes | calendar | engine + AI reading |
| Scholarships | calendar | engine + AI reading |
| Hackathons & Competitions | calendar | engine + AI reading |

Currently active category: Open Source (in progress). AI verification for calendar categories runs ~2x/month; the engine sweep runs once a day.

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

The beta catalog is a roadmap, not a claim that every category is currently
supported. No category implementation is claimed by the scaffold or by this
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

- **Google Summer of Code** — official open-source programme page — planned
- **Other open-source programmes** — official programme pages — planned
- **University and research-lab pages** — official research programmes — planned
- **Government scholarship and grant pages** — official programmes — planned
- **Fellowship, scholarship, and hackathon pages** — official programme pages —
  planned

## Not used

- LinkedIn
- Naukri
- Wellfound
