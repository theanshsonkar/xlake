# Legal checks

Date: 2026-08-04. User-Agent: `xlake-research/0.1 (+opportunity-lake)`.

## robots.txt
All four robots.txt requests returned HTTP 200. No `Allow:` or `Disallow:` line matching a `job`, `intern`, `listing`, or `api` path was present in any response. Therefore the deciding line for each is: “No matching Allow/Disallow directive.”

- **unstop.com — UNCLEAR.** Exact deciding line: no matching directive.
- **freshershunt.in — UNCLEAR.** Exact deciding line: no matching directive.
- **freshersdunia.in — UNCLEAR.** Exact deciding line: no matching directive.
- **coursejoiner.com — UNCLEAR.** Exact deciding line: no matching directive.

## Unstop public API
Four paths were tried:

- `/api/public/search/opportunities` — HTTP **404**.
- `/api/public/opportunity/search` — HTTP **200**, JSON, top-level key `data`; opportunity/job/internship terms and eligibility/degree/CGPA/batch terms were present.
- `/api/public/opportunities` — HTTP **404**.
- `/api/public/opportunity` — HTTP **404**.

The successful JSON response contained opportunity-listing data and eligibility-related fields in the response; the probe did not establish record-level field association.

## FreshersHunt listing
Homepage/category discovery led to `https://freshershunt.in/shopback-off-campus-drive-2026/` (HTTP 200). It contained this direct ATS URL: `https://jobs.lever.co/shopback-2/12ad282d-bab1-4b02-8d16-5028ce42c9b9`.

No plain-text **batch-year** statement was found. Eligibility quote: “Computer Science, Information Technology, Electronics & Communication, or any related information discipline are eligible.”

## Telegram ToS
`https://telegram.org/tos` returned HTTP 200 and redirected to `/tos/in`. No clause mentioning automated access, scraping, or crawling was found. The only matching bot clause was: “Promote violence on publicly viewable Telegram channels, bots, etc.” **UNCLEAR** for automated crawling; exact deciding line: “No clause mentioning automated access, scraping, or crawling.”
