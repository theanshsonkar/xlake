Few things is that this lake md is the overall info abt my prodcut and idea and then the registry plan is basically the file that knwo what categorirs and then in that categories what we are having in ouir engine so we work and have info and eveything and then the engine md is the overall info abt our engine that shoudl have whole image of our engine so any ai can knwo and also whenever we make changes in our engine we also upodate the engine md. and the engine folder shoudl not have evrything scatterred as i need sub folder or folder for things not scattered . also in the dsktop is xlake folder that has ui design half so if u have any questions regardiung ui you can get answers from that.

# Xlake

## Product reference

Xlake is a free search engine for early-career opportunities.

Its purpose is simple: help people find trustworthy opportunities, understand
what the official source says, and open the real application page. Opportunity
Radar links users to original sources rather than operating as a job board.
Xlake does not replace the organisation running an opportunity, decide whether
someone is eligible, or submit an application for anyone.

This is the single product reference for Xlake. It records the product
identity, audience, scope, experience, trust rules, and collection principles
that should guide the website and the collector.

## 1. What Xlake is

**Search every opportunity. Decide what fits.**

Xlake is an opportunity search engine for students and early-career people. It
collects opportunities from official sources, makes them searchable, shows the
facts that matter, and sends users to the original application or programme
page.

Xlake is not a conventional job board. Jobs matter, but they are only one kind
of opportunity. A useful opportunity may be an internship, a research
programme, an open-source programme, a fellowship, a scholarship, a grant, or
a hackathon.

Xlake is also not a career-preparation product, a resume product, a social
network, or an application portal. Its job is discovery and clear source
information.

The official source is always the primary destination. The persistent canonical lake is S3 at `s3://$AWS_S3_BUCKET/lake/{opportunities,hidden,opportunities_history}.json`; Supabase is the serving projection. Everything is retained across jobs (the default), Open Source programmes, and Open Source contributions (good-first-issues).

## 2. Who Xlake is for

Xlake initially serves:

- students in India;
- early-career candidates with roughly zero to two years of experience; and
- people looking primarily for technical, STEM, engineering, research, and
  related opportunities.

The product should be useful whether a person is in college, recently
graduated, looking for an internship, seeking research experience, or trying
to find an early-career technical role.

Starting with a focused audience is deliberate. Xlake should first be reliable
for this group, rather than becoming a broad, low-quality listing site for
every career field. Other fields can be added when Xlake has dependable source
coverage and classification for them.

Jobs and Internships are India-first and technical for students and early-career
candidates in India. Every other category - Open Source programmes and
good-first-issues, Fellowships, Grants & Funding, Scholarships, and Hackathons &
Competitions - is worldwide and open to anyone.

## 3. Opportunity scope

Xlake is designed to cover opportunities, not only jobs.

The current user-facing categories follow the opportunities that Xlake can
actually support. Open Source is the hero category and is actively collected,
including calendar programmes and good-first-issue listings. Hackathons &
Competitions are also actively refreshed by the deterministic official-source
collector. Current coverage also includes:

- India-first internships, currently collected via Unstop; and
- India-focused early-career technical roles where source coverage is good
enough.

Scholarships are planned / not yet built (category scaffolding only, not
actively collected). As reliable coverage grows, Xlake can add categories such
as fellowships, grants and funds, student and research programmes, and other
early-career technical opportunities.

Categories in the interface should be dynamic. Xlake should not advertise a
category merely because it sounds useful; it should show a category when it has
real, searchable opportunities within it.

## 4. Geography

Jobs are not hidden by country. Each job is classified by accessibility as
India-located, remote-global, foreign on-site, or excluded, and ranked
accordingly. The default feed shows India-located and remote-global roles.
Foreign on-site roles are retained, searchable, and ranked lower. Roles whose
stated location rules out Indian applicants are kept as hidden records, not
deleted.

A global opportunity can appear when an official source explicitly welcomes
international or Indian applicants. Xlake may also show a strong global
opportunity when visa, work-permission, location, or international eligibility
is not clear. In that case, the uncertainty must be shown plainly.

Xlake must never imply that an Indian applicant can work in a country, obtain a
visa, or meet an organisation's eligibility requirements unless the official
source says so.

## 5. The Xlake experience

Xlake is search-first.

A user should be able to arrive, search for an area such as internships,
cybersecurity, AI, research, companies, or a location, and inspect useful
results without creating an account or uploading a resume.

The main experience has four parts:

1. **Search.** A user searches by role, subject, skill, organisation,
   programme, or place.
2. **Filters.** Users can narrow results by location, opportunity type, status,
   and deadline or timing. Filters should remain simple and useful.
3. **Results.** Each result shows the organisation or programme, title, type,
   location, status, and relevant timing information.
4. **Detail panel.** A selected result explains what the official source says,
   what is known about eligibility, what remains uncertain, and provides the
   official application or programme link.

The default results view shows all useful states together, in a clear order:

1. live opportunities;
2. opening-soon opportunities; and
3. opportunities that need confirmation.

Within a relevant search, opportunities with a real upcoming deadline and live
status should receive priority. Freshly confirmed or newly found live
opportunities follow. Search relevance must still matter: a matching research
or cybersecurity result should not be buried beneath an unrelated role solely
because it closes sooner.

A later sort control may offer options such as recommended, closing soon,
newest, and recently confirmed.

## 6. Filters and local saves

The beta experience should support practical filters:

- **Location:** India, remote, and global;
- **Opportunity type:** based on categories actually present in the results;
- **Status:** live, opening soon, and needs confirmation; and
- **Timing:** closing soon, rolling, or no deadline stated.

Search is the first way to explore subject areas such as AI, software,
cybersecurity, research, and other technical topics. More specialised filters
should be added only when the underlying data is dependable.

A user may save an opportunity locally in their browser. This does not require
an account or sign-in during beta. Saved opportunities are a convenience, not a
profile, resume, or eligibility system.

## 7. Opportunity states

Xlake uses clear status language. Status describes what Xlake observed at a
source; it does not certify the opportunity or the applicant.

### Live

A live opportunity was recently found at its official source and appears to be
currently open or present there.

### Opening soon

An opening-soon opportunity has an official programme page, announcement, or
confirmed upcoming application window, but applications are not yet open. Its
primary action should be **View official page** or **View programme**, not
**Open application**.

Recurring programmes can appear in this state when their future window is
supported by an official source. Xlake must not invent an opening date from
history alone.

### Needs confirmation

Needs confirmation means an important fact is uncertain. Examples include an
unclear deadline, uncertain visa or work-permission support, a blocked or
partial source read, an old confirmation, or incomplete source information.

These opportunities remain visible by default because they may still be useful.
Xlake must make the uncertainty easy to understand and must not quietly treat
it as a live guarantee.

### Closed

Closed means an opportunity was reliably confirmed absent, expired, or no
longer accepting applications. Closed records are retained for history but are
not shown in normal search.

## 8. Trust contract

Trust is Xlake's core product requirement.

Xlake must:

- use the original official application, employer, university, lab, programme,
  or organisation page as the primary link;
- show when an opportunity was last confirmed at an official source;
- explain facts using observational language;
- show important uncertainty instead of hiding or guessing it;
- preserve historical records rather than silently deleting them; and
- make it clear that coverage is incomplete.

Xlake must not:

- promise that an individual user is eligible;
- say that an application will succeed;
- claim complete market coverage;
- present an uncertain, blocked, partial, stale, or failed source read as live;
- republish a full job description instead of linking to the source; or
- present a lead, directory listing, or search result as an application link.

The product should use wording such as:

- **Seen at official source**
- **Last confirmed at official source**
- **The source does not state a batch-year requirement**
- **Visa or work-permission support needs confirmation**
- **Read the official source before applying**

The product should avoid language such as **Verified by Xlake**. That wording
implies human vetting or a guarantee that Xlake does not provide.

## 9. Eligibility information

Xlake helps users inspect eligibility. It does not decide eligibility.

Where the official source provides it, Xlake may show:

- opportunity type and career stage;
- degree or study requirements;
- graduation or batch-year requirements;
- experience requirements;
- enrolled-student requirements;
- location and work arrangement;
- international, visa, or work-permission information;
- deadline or rolling-application information; and
- concise evidence from the official source.

When a requirement is missing, Xlake should say that it was not stated by the
source. It must not infer eligibility from a title, company, location, or
previous programme cycle.

The official organisation and the applicant make the final eligibility
decision.

## 10. Minimum quality bar for a result

An opportunity may appear in Xlake when it has, at minimum:

- a meaningful title;
- an organisation or programme name;
- an official source or application URL;
- source provenance or a clear record of where Xlake found it;
- a status; and
- a last-confirmed or last-observed time.

Eligibility details, deadlines, compensation, funding, and location may be
missing from an official source. Their absence should be displayed honestly,
not guessed.

A lead without an official source is not a user-visible opportunity. It can be
kept internally for further resolution, but users should not be sent to a
third-party directory, a social post, or a guessed application link.

## 11. The detail panel

The opportunity detail view should help a user make a quick, informed decision
about what to inspect next. It should include:

- organisation or programme name;
- opportunity title;
- status and last-confirmed information;
- location;
- a concise source-based summary;
- an eligibility snapshot;
- source evidence;
- an explicit uncertainty note when needed;
- a local save action; and
- the official application or programme link.

For live opportunities, the primary action is **Open application**. For an
opening-soon opportunity, it is **View official page**. For a needs-confirmation
opportunity, the action can still open the official source, while the interface
makes the unresolved fact clear.

Xlake should not require sign-in, a resume, or a personal profile before a user
can search, inspect an opportunity, save it locally, or open its official page.

## 12. Current interface direction

The interface is a two-column opportunity browser: search and results on the
left, with a detail panel on the right. It is the reference direction for the
product experience, not a claim that every visible control is already active.

The sidebar can show:

- All opportunities;
- Saved; and
- Programme calendar.

Programme calendar is a future surface. It may remain visible in the interface,
but it is not required to work in the current beta.

Similarly, alerts and an eligibility profile are future ideas, not current beta
features. The beta should not claim that they are active. It has no sign-in,
alerts, resume upload, or personalised eligibility matching.

Header statistics must be sourced from current, real data or omitted. Xlake
must not ship invented figures for live roles, programme counts, or newly added
opportunities.

## 13. How Xlake finds opportunities

Xlake uses a collector that works in stages:

```text
discover -> resolve -> read -> classify -> merge -> store
```

- **Discover:** public indexes, registries, portfolios, and directories provide
  leads.
- **Resolve:** a lead is traced to an official careers page, ATS, university,
  lab, programme, or application source.
- **Read:** Xlake reads permitted official sources and identifies opportunity
  data, deadlines, and source evidence.
- **Classify:** Xlake identifies useful facts such as type, location, career
  stage, discipline, and stated eligibility requirements.
- **Merge:** repeated observations are deduplicated, confirmation history is
  preserved, and liveness is handled cautiously.
- **Store:** user-visible opportunity data and historical records are retained.

Discovery sources are leads only. A directory, public company list, search
result, or portfolio page never becomes the user-facing application link unless
Xlake resolves it to the relevant official source.

## 14. Collection principles

Xlake collects responsibly.

- It respects `robots.txt`, uses an honest user agent, and limits requests per
  host.
- It prefers structured, public official sources such as ATS APIs, official
  careers pages, university pages, research-lab pages, and programme sites.
- It treats pagination, transport errors, blocked pages, and partial reads as
  uncertainty.
- Finding an opportunity is evidence that it exists; failing to find it is not
  automatically evidence that it closed.
- A complete, reliable official read is required before marking a previously
  seen opportunity closed.
- It retains historical records rather than deleting opportunities from the
  underlying system.
- It does not automate access to LinkedIn, Naukri, or Wellfound, and it does
  not republish their listings.

Artificial intelligence may be used as optional enrichment where an official
page needs interpretation. It must not invent source facts, replace source
confirmation, or create an eligibility guarantee.

## 15. Product data requirements

To support the Xlake experience, a user-visible opportunity record should carry
at least:

- title;
- organisation or programme name;
- opportunity type;
- official URL;
- source provenance;
- status;
- last confirmation or observation time;
- read outcome;
- location or remote information when stated; and
- a liveness model: present-at-source or deadline-based.

When available, it should also carry a real deadline, eligibility facts,
evidence, and concise source-based context.

A boolean such as `is_live` alone is not enough for the product. Xlake needs a
clear three-state user model: **live**, **opening soon**, and **needs
confirmation**, with closed records retained outside normal search.

## 16. What Xlake does not do

Xlake does not:

- submit applications;
- host application forms;
- require a resume to search;
- require sign-in during beta;
- make eligibility decisions;
- promise an interview, offer, visa, funding, or selection outcome;
- act as a complete list of every opportunity in the world;
- build a personalised matching profile during beta; or
- act as a paid career-preparation product.

Xlake remains a free opportunity search engine. Business-model decisions are
separate from this product reference and are intentionally not defined here.

## 17. Product decisions

The following decisions guide Xlake unless new evidence justifies changing
them:

- Xlake is the product name.
- Xlake is a free search engine for opportunities.
- The initial audience is Indian students and early-career technical/STEM
  candidates with roughly zero to two years of experience.
- Jobs are classified as India-located, remote-global, foreign on-site, or excluded; the default feed shows India-located and remote-global roles, while foreign on-site roles are retained, searchable, and ranked lower.
- Roles whose stated location rules out Indian applicants are retained as hidden records, not deleted.
- Xlake includes global opportunities with explicit international access and
  may include strong global opportunities whose visa or work-permission
  conditions are unknown, as long as that uncertainty is clear.
- Xlake begins with the opportunity types it can support reliably, not with an
  artificial promise of every category.
- Users can browse without sign-in and save opportunities locally in beta.
- Live, opening-soon, and needs-confirmation opportunities appear together in
  the default results view with clear status labels.
- Xlake never states that a user is eligible; it reports source facts and
  missing information.
- Official links, source provenance, and confirmation information are required
  for user-visible opportunities.
- The programme calendar, alerts, and eligibility profile may appear as future
  interface directions but are not current beta functionality.
- Xlake uses observational language, not claims of verification or guarantee.

## 18. The standard Xlake should meet

A user should be able to open Xlake, search for an opportunity, understand
whether it is live, opening soon, or uncertain, see what the official source
actually says, and go directly to the real page without a resume, sign-in, or
unnecessary gate.

That is the product: a clear, trustworthy search engine for early-career
opportunities.
