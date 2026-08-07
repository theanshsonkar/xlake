# Phase 3 lead-source robots check

- **Checked:** 2026-08-04
- **User-Agent:** `xlake/1.0 (+https://github.com/theanshsonkar/xlake; contact: anshsonkar@users.noreply.github.com)`
- **Method:** robots.txt was fetched first for each host. Requests were serialized per host with at least a 2-second delay. Three robots requests, three permitted homepages, and only the advertised/obvious sitemap/feed status checks were made; no links were followed and no article text was copied.

## freshershunt.in

**robots.txt:** HTTP 200.

The complete body was under 2,000 characters:

```text
User-agent: *
Disallow: /wp-admin/
Disallow: /tag/
Disallow: /?s=
Disallow: /search/
Disallow: /author/
Disallow: /wp-includes/
Disallow: /trackback/
Disallow: /feed/
Disallow: /comments/
Allow: /wp-admin/admin-ajax.php

Sitemap: https://freshershunt.in/sitemap_index.xml
```

**Verdict:** **ALLOWED** for a generic non-named crawler using the `*` group. Deciding line: `User-agent: *`; there is no rule matching `/`, so the homepage and ordinary listing/archive paths are allowed. The explicitly named paths `/tag/`, `/search/`, `/author/`, `/feed/`, and `/comments/` are disallowed; `/wp-admin/admin-ajax.php` is the more-specific exception within `/wp-admin/`.

**Crawl-delay:** No `Crawl-delay` is stated. The 2-second project delay therefore applies and is satisfied.

**Permitted homepage check:** `https://freshershunt.in/` returned HTTP 200. No official apply URL was visible in the page links inspected. No verbatim official outbound URL examples are available; visible navigation/article links were internal.

**Sitemap/feed status:**

- Sitemap: `https://freshershunt.in/sitemap_index.xml` — HTTP 200.
- RSS/Atom: `https://freshershunt.in/feed/` — not fetched because robots explicitly disallows `/feed/`.

**Recommendation:** **GO** for a narrowly scoped, robots-compliant follow-up on permitted listing/article paths. Do not request `/tag/`, `/search/`, `/author/`, `/feed/`, or `/comments/`.

## freshersdunia.in

**robots.txt:** HTTP 200.

The complete body was under 2,000 characters:

```text
# As a condition of accessing this website, you agree to abide by the following
# content signals:

# (a)  If a Content-Signal = yes, you may collect content for the corresponding
#      use.
# (b)  If a Content-Signal = no, you may not collect content for the corresponding
#      use.
# (c)  If the website operator does not include a Content-Signal for a
#      corresponding use, the website operator neither grants nor restricts
#      permission via Content-Signal with respect to the corresponding use.

# The content signals and their meanings are:

# search:   building a search index and providing search results (e.g., returning
#           hyperlinks and short excerpts from your website's contents). Search does not
#           include providing AI-generated search summaries.
# ai-input: inputting content into one or more AI models (e.g., retrieval
#           augmented generation, grounding, or other real-time taking of content for
#           generative AI search answers).
# ai-train: training or fine-tuning AI models.
# use:      how AI systems may consume the content (immediate, reference, or full).

# ANY RESTRICTIONS EXPRESSED VIA CONTENT SIGNALS ARE EXPRESS RESERVATIONS OF
# RIGHTS UNDER ARTICLE 4 OF THE EUROPEAN UNION DIRECTIVE 2019/790 AND RELATED RIGHTS IN THE DIGITAL SINGLE MARKET.

# BEGIN Cloudflare Managed content

User-agent: *
Content-Signal: search=yes,ai-train=no,use=reference
Allow: /

User-agent: Amazonbot
Disallow: /

User-agent: Applebot-Extended
Disallow: /

User-agent: Bytespider
Disallow: /

User-agent: CCBot
Disallow: /

User-agent: ClaudeBot
Disallow: /

User-agent: CloudflareBrowserRenderingCrawler
Disallow: /

User-agent: Google-Extended
Disallow: /

User-agent: GPTBot
Disallow: /

User-agent: meta-externalagent
Disallow: /

# END Cloudflare Managed Content

User-agent: *

Sitemap: https://freshersdunia.in/sitemap_index.xml
```

**Verdict:** **ALLOWED** for this generic non-named crawler: no `xlake`-specific group exists, so the `*` group applies. Deciding lines: `User-agent: *` and `Allow: /`. The named bot groups with `Disallow: /` do not apply to `xlake`. The trailing empty `User-agent: *` group adds no restriction. The Cloudflare `Content-Signal` is recorded above but is not an Allow/Disallow robots rule.

**Crawl-delay:** No `Crawl-delay` is stated. The 2-second project delay therefore applies and is satisfied.

**Permitted homepage check:** `https://freshersdunia.in/` returned HTTP 200. No official apply URL was visible in the page links inspected. No verbatim official outbound URL examples are available; visible navigation/article links were internal.

**Sitemap/feed status:**

- Sitemap: `https://freshersdunia.in/sitemap_index.xml` — HTTP 403.
- RSS/Atom: `https://freshersdunia.in/feed/` — HTTP 200.

**Recommendation:** **GO** for a narrowly scoped, robots-compliant follow-up. The homepage itself exposed no official apply URL, so source utility remains unconfirmed without inspecting permitted listing/article pages.

## coursejoiner.com

**robots.txt:** HTTP 200.

The complete body was under 2,000 characters:

```text
User-agent: *
Disallow: /wp-admin/
Allow: /wp-admin/admin-ajax.php

Sitemap: https://coursejoiner.com/sitemap_index.xml
```

**Verdict:** **ALLOWED** for a generic non-named crawler using the `*` group. Deciding line: `User-agent: *`; `Disallow: /wp-admin/` does not match `/`, and ordinary listing/archive pages are not disallowed. The more-specific `Allow: /wp-admin/admin-ajax.php` applies only inside the otherwise disallowed admin path.

**Crawl-delay:** No `Crawl-delay` is stated. The 2-second project delay therefore applies and is satisfied.

**Permitted homepage check:** `https://coursejoiner.com/` returned HTTP 200. No official apply URL was visible in the page links inspected. No verbatim official outbound URL examples are available; visible navigation/article links were internal.

**Sitemap/feed status:**

- Sitemap: `https://coursejoiner.com/sitemap_index.xml` — HTTP 200.
- RSS/Atom: `https://coursejoiner.com/feed/` — HTTP 200.

**Recommendation:** **GO** for a narrowly scoped, robots-compliant follow-up. The homepage itself exposed no official apply URL, so source utility remains unconfirmed without inspecting permitted listing/article pages.

## VERDICT

| host | robots status | listing pages allowed | crawl-delay | feed available | official apply URLs visible | recommendation |
|---|---:|---|---|---|---|---|
| freshershunt.in | 200 | Yes, except explicitly disallowed paths including `/tag/`, `/search/`, `/author/`, `/feed/`, `/comments/` | Not stated; 2 s satisfied | Sitemap 200; RSS/Atom not fetched because `/feed/` is disallowed | No | GO |
| freshersdunia.in | 200 | Yes: `Allow: /` under `*` | Not stated; 2 s satisfied | Sitemap 403; RSS/Atom 200 | No | GO |
| coursejoiner.com | 200 | Yes, except `/wp-admin/` | Not stated; 2 s satisfied | Sitemap 200; RSS/Atom 200 | No | GO |

## Assumptions and limits

- “Generic non-named crawler” means this project’s `xlake` crawler identity; because no host-specific `xlake` group was present, the `*` group was selected.
- Listing-page permission was evaluated for the homepage path `/` and the ordinary archive/listing paths not covered by an explicit Disallow rule. A path-specific Disallow remains binding.
- A 2-second delay means at least 2 seconds between requests to the same host; no site stated a larger delay.
- Feed and sitemap checks were status-only checks. The response bodies were not read beyond a small bounded prefix, and no feed/sitemap entries were followed.
- Official apply URL visibility was assessed only on one permitted homepage per host. No conclusion is made about links on unvisited article/listing pages.
- The `Content-Signal` lines on freshersdunia.in were preserved verbatim as nonstandard metadata; the robots Allow/Disallow decision used the User-agent groups and robots rules.
