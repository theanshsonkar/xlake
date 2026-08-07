# Discovery and registry plan

**Purpose:** find official opportunity sources without mistaking a lead for an
application. The registry is collection infrastructure, not a list of pages to
republish.

**Updated:** 2026-08-07

## 1. Source truth

Company lists, Common Crawl results, public directories, search results, and
other crawls are lead sources only. They may supply a company or programme name,
domain, or candidate ATS token, but they must never be displayed as an
application.

Resolution must land on a company-owned ATS, employer careers page, university,
lab, programme, or other official application URL. The following is the target
registry/display contract and acceptance behavior, not a claim that the current
collector always persists every field. A resolved registry entry must record:

- the official URL actually reached;
- source provenance and the resolver path;
- platform and token, where applicable;
- the last successful confirmation; and
- a distinct result state: `verified`, `empty`, `error`, or `partial`.

The default product surface must not mark a role live or display it as verified
until the official URL, provenance, and last successful confirmation are
available. Provenance and confirmation persistence, and fail-closed partial-read
handling, are implementation requirements still being hardened where necessary.

Only `verified` means the source was successfully read and its result can be
used for normal display. `empty` means a reliable, complete read found no
current postings; it does not mean the company is permanently inactive.
`error` means the read failed. `partial` means pagination, parsing, transport,
access, or another completeness condition was not satisfied. Neither errors nor
partial results establish closure or completeness.

## 2. Resolution flow

Use the official careers route rather than guessing a token:

```text
company.example/careers
        -> follow the official link or redirect
        -> company-owned ATS/programme/application URL
        -> verify by reading that source
        -> record URL, provenance, status, and last confirmation
```

A token guess is a fallback, not an enumeration strategy. One failed guess does
not prove that a company has no openings. A source that returns HTTP 200 with
zero jobs is not automatically verified: the read must be complete and tied to
the correct official board. A failed, blocked, stale, or partial resolution is
recorded as such and may be retried or routed to a page reader.

Resolver output is a lead until the official URL is recorded and confirmed.
As an acceptance requirement, rows promoted for users must carry the original
official application URL, provenance, and last successful confirmation—not merely
the directory or registry URL. Current persistence of those fields is still
being hardened where necessary.

## 3. Source layers

### 3.1 Structured ATS discovery

Enumerate public ATS tokens where permitted, then verify each token against the
official source. Sweep complete pagination, retain source status, and demote or
recheck sources whose counts drop unexpectedly. A broad token universe is a way
to discover leads; it is not evidence of coverage.

### 3.2 Employer, campus, university, and programme pages

Watch official pages on a slower cadence. Store the page URL, fetch status,
last confirmation, and evidence. If a page is JavaScript-only or blocked, route
it to the page-reader/bespoke path and mark uncertainty rather than publishing
an inferred application.

### 3.3 Indian ATS sources

- **Keka:** source mode is its public JSON API at
  `/careers/api/embedjobs/{portalName}/active/{board_guid}`. Confirm the board,
paginate completely, and retain the official application URL and provenance.
- **Zoho Recruit:** page-reader or bespoke handling remains required.
- **Darwinbox:** page-reader or bespoke handling remains required.

The old planning assumption that all three Indian ATS platforms were
HTML-only/no-JSON is historical and superseded for Keka. It remains a
limitation note for Zoho Recruit and Darwinbox only.

### 3.4 Growth leads

YC directories, company lists, Common Crawl, and similar public sources can
supply names for resolution. They are never application links. LinkedIn and
Naukri are excluded from automated access and are not republished.

## 4. Status handling

The resolver and sweeper must distinguish at least:

- **verified:** official source read successfully and completely;
- **empty:** official source read successfully and completely, with no current
  postings;
- **error:** request, parsing, access, or other failure;
- **partial:** a read returned data but completeness could not be established.

**Acceptance requirement, not a claim that the current sweep universally
complies:** partial, truncated, or no-error reads whose completeness is not
established must be treated as uncertain. They must not establish completeness
or closure. A partial page, truncated pagination, timeout after a partial
response, or blocked subrequest must not establish that a board is empty,
closed, or fully swept. Fail-closed handling and persistence of this uncertainty
remain implementation requirements being hardened where necessary.

Preserve the previous known state, mark the new observation partial or error,
and surface it for confirmation.

A posting may be marked not live/closed only from a reliable official signal or
complete reliable listing comparison. Otherwise retain it and mark it
`needs_confirmation`. Default search can hide closed records, but the registry
and Lake retain the history.

## 5. Operational rules

- Respect `robots.txt`, use an honest User-Agent with a contact address, and
  pace requests per host.
- Complete pagination or explicitly record why it was not completed.
- Never treat a valid token with an empty response as proof that the company is
  not hiring until the source and read completeness are confirmed.
- As an acceptance target, store the official URL, provenance, and last
  successful confirmation before promotion to a user-visible row; current
  persistence is still being hardened where necessary.
- Keep raw snapshots private and display only concise evidence with a link to
  the official source.
- A generic gate classifier is not candidate-specific eligibility matching.
  Any personalized matching is future work and must be labelled separately.

## 6. Historical measurements

No historical scaling or run figures are asserted here. Any future measurement
must name its local artifact, date, and input scope, and must be labelled a
historical observation rather than current coverage or a reproducible guarantee.
