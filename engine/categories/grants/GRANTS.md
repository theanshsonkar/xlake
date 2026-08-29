# Grants & Funding - category doc

Status: IN PROGRESS. Folder: `engine/categories/grants/`.

This doc is the overview and worklist for the Grants & Funding category. It does NOT store opportunity data - those live in `engine/data/lake/opportunities.json`.

## Scope and evidence
Worldwide grants and funding programmes with an official source page. There is no India or other location filter; capture each opportunity's own eligibility from its official page. Every recorded fact needs quote-backed evidence from an official page. Never invent dates or infer status from a generic Apply button. A failed, blocked, partial, or unclear read never closes a row.

Verification is evidence-gated: a fact is written only when its official quote and exact source URL are recorded. Fields without quote-backed evidence remain `needs_confirmation` or `not_stated`. A rolling funding-decision cadence is not treated as proof that applications are open.

## Source worklist

| Source | Official URL | Status |
|---|---|---|
| Open Technology Fund — Internet Freedom Fund | https://www.opentech.fund/funds/internet-freedom-fund/ | verified rolling applications; eligibility and funding verified |
| Ethereum Foundation — Ecosystem Support Program | https://esp.ethereum.foundation/ | needs confirmation; support and funding mechanism verified, no open/status claim |
| Awesome Foundation — Grant Application | https://www.awesomefoundation.org/en/submissions/new | needs confirmation; application form evidence only, no amount/status claim |
| Mercatus Center — Emergent Ventures | https://www.mercatus.org/emergent-ventures | needs confirmation; grant eligibility verified, no amount/status claim |
| The Pollination Project — Daily Grants | https://thepollinationproject.org/apply/ | needs confirmation; eligibility, seed funding, budget caps, and rolling decisions verified; no open claim |
| National Geographic Society — Understanding Ecosystem Dynamics and the Ecology of the Okavango River Basin | https://funding.nationalgeographic.org/s/fundingopportunity/119Hr000000byRrIAI/understanding-ecosystem-dynamics-ecology-of-the-okavango-river-basin | deadline verified; current status needs confirmation |

## Included

- Worldwide project, research, community, technology, and other grant/funding programmes with an identifiable official source.
- Official application or programme pages whose dates, eligibility, funding, or status can be quoted and checked.
- Programmes that retain unconfirmed fields when the official page is readable but does not support a fact claim.

## Exclusions and drop reasons

- Aggregators, directories, newsletters, and discovery pages: dropped because they are not the official source for the programme facts.
- Generic Apply buttons or application forms without a dated window or explicit acceptance status: retained only as needs confirmation; never classified as open.
- Crowdfunding, donations, loans, procurement/contracts, and ordinary commercial finance: dropped because they are not grant or funding programmes in this category.
- Prizes, awards, contests, and competitions without a grant/funding programme structure: dropped; Hackathons & Competitions has its own category.
- Fellowship, scholarship, internship, or accelerator pages with no explicit grant/funding component: dropped or left to their owning category.
- Duplicate organization landing pages or duplicate calls: dropped in favor of the most specific official programme/RFP URL.
- A blocked, failed, partial, or unclear read: not a drop and not a closure; leave the source pending or needs confirmation.

## Local commands

Run from `engine/`:

```bash
python3 -m categories.grants.grants
python3 -m categories.grants.grants --apply-verifications
```

The collector is not synced to S3 or published to Supabase by local execution.

## Manual verification

Evidence-backed records are stored in `data/operations/grant_programme_verifications.json` and surfaced via `python3 -m categories.grants.grants --apply-verifications`.

## Initial work note

Initial category artifacts and quote-backed verification records created 2026-08-29. The collector and verification application should be rerun on the monthly cadence; no unsupported row count or universal eligibility or open-status claim is made here.
