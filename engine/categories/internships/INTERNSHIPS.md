# Internships - category doc

This category is an India-first listing view for early-career internships. It
uses the shared lake and shared `india_source` machinery; it does not own a
separate database. Unstop is the main India-first source, alongside official
employer and ATS listings collected by the engine.

## Listing view

`list_internships(india=None, surfaced=None, platform=None, company=None)` reads
`engine/data/lake/opportunities.json` and returns only rows with
`is_internship == True` and no non-null `record_type` (the job-row shape used by
the lake). Optional filters select India-located or India-remote rows, surfaced
rows, or exact case-insensitive platform/company values. It is read-only and
performs no network access.

The equivalent view-only CLI is:

```bash
cd engine
python3 -m categories.internships.internships --list \
  [--india] [--surfaced] [--platform unstop] [--company "Company Name"]
```

It prints a count and up to five title/company/location/URL summaries. The
`is_internship` flag comes from `core.filters` classification at sweep time; the
category view does not reclassify or infer it.

Last worked: 2026-08-20 - added the read-only internships listing view, CLI,
and offline regression coverage.
