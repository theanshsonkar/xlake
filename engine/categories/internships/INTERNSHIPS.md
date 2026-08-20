# Internships - category doc

Status: LIVE. This category covers India-relevant internships for students and
early-career candidates. It uses official sources only, links to the official
page, and never submits an application. LinkedIn and Naukri are never accessed
or republished.

## How collected

Internships are a listing category collected by the engine only. The Unstop
public feed adapter in `engine/adapters/boards.py` reads
`unstop.com/api/public/opportunity/search-result` with `opportunity=internships`
and `oppstatus=open`. It is bounded to 60 pages; over-long reads are marked
`truncated`, and the adapter is churn-tolerant.

The `india_source` machinery in `pipeline/sweep.py` treats `{unstop, keka}` as
India-first. `core/filters.classify` maps their generic-remote rows to
`india_remote` and explicit-India rows to `india_located`. `is_internship` is
classified from title words: `intern`, `internship`, `trainee`, or `apprentice`.
`REMOTE_ANY` matches `online`, `virtual`, `remote`, `wfh`, or `hybrid`.

## Registry and view

The hand-audited Indian companies in
`engine/data/operations/registry.json` include Groww (manual-verified) and
Sprinklr, Zluri, Fractal, Observe.AI, and Uniphore (resolved from an audited
lead list).

`list_internships` in `engine/categories/internships/internships.py` reads the
canonical lake and filters rows with `record_type` absent and `is_internship`
true. Its default view sorts by `access_rank`: `india_located` first, then
`remote_global` (including `india_remote`), and `foreign_onsite` last.
Accessibility ranks are `india_located` (0), `remote_global` (1),
`foreign_onsite` (2), and `excluded` (3). Foreign-onsite internships are
retained, labeled, and ranked lower; they are not deleted.

Run its view-only CLI from `engine/`. `--india` selects India-located and
India-remote rows, `--surfaced` selects rows with `hidden_reason` of `None`,
and `--foreign` selects on-site-abroad rows only:

```bash
python3 -m categories.internships.internships --list
python3 -m categories.internships.internships --list --india
python3 -m categories.internships.internships --list --surfaced
python3 -m categories.internships.internships --list --foreign
```

~300+ Indian internships are surfaced at runtime; this is not a stored metric.

## Jobs note

Jobs are good enough via the same `india_source` machinery: India tech roles
surface through it, and there is no separate jobs doc or worklist. We are not
grinding more employers by design. Darwinbox is deferred as the biggest untapped
India employer source.

## Guardrails

The one canonical lake is `engine/data/lake/opportunities.json`. Failed,
blocked, or partial reads never close a row.
