# Scholarships - category doc

Status: IN PROGRESS. Folder: `engine/categories/scholarships/`.

This doc is the overview and worklist for the Scholarships category. It does NOT store opportunity data - those live in `engine/data/lake/opportunities.json`.

## Scope and evidence
Worldwide scholarships and scholarship programmes with an official source page. There is no India or other location filter; capture each scholarship's own eligibility from its official page. Every recorded fact needs quote-backed evidence from an official page. Never invent dates or infer status from a generic Apply button. A failed, blocked, partial, or unclear read never closes a row.

## Source worklist

| Source | Official URL | Status |
|---|---|---|
| Fulbright Foreign Student Program | https://foreign.fulbrightonline.org/about/foreign-student-program | needs confirmation |
| Rhodes Scholarship | https://www.rhodeshouse.ox.ac.uk/scholarships/the-rhodes-scholarship/ | verified open |
| Gates Cambridge Scholarships | https://www.gatescambridge.org/apply/eligibility/ | needs confirmation |
| Knight-Hennessy Scholars | https://knight-hennessy.stanford.edu/admission | deadline verified; current status needs confirmation |
| DAAD Scholarships & Funding | https://www.daad.de/en/studying-in-germany/scholarships/ | needs confirmation |
| Schwarzman Scholars | https://www.schwarzmanscholars.org/admissions/ | verified open |
| Commonwealth Master's Scholarships | https://cscuk.fcdo.gov.uk/scholarships/commonwealth-masters-scholarships/ | verified opening soon |
| Erasmus Mundus Joint Masters | https://erasmus-plus.ec.europa.eu/opportunities/opportunities-for-individuals/students/erasmus-mundus-joint-masters | needs confirmation |
| Stipendium Hungaricum | https://stipendiumhungaricum.hu/ | verified open |
| Türkiye Scholarships | https://www.turkiyeburslari.gov.tr/ | needs confirmation |

## Local commands

Run from `engine/`:

```bash
python3 -m categories.scholarships.scholarships
python3 -m categories.scholarships.scholarships --apply-verifications
```

The collector is not synced to S3 or published to Supabase by local execution.

## Initial work note
Initial category artifacts and quote-backed verification records created 2026-08-29. The collector and verification application should be rerun on the monthly cadence; no unsupported row count or universal eligibility claim is made here.
