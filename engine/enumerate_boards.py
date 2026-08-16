"""Board discovery from Common Crawl. No company names typed, ever.

Common Crawl publishes a URL index of everything it has crawled, queryable by
prefix or domain with no API key. Every ATS board that has ever been linked
publicly is in there, so the board universe can be enumerated instead of
curated. The company list becomes an output.

Caveats measured on 2026-07-31:
  - Lever is absent. Common Crawl honours robots.txt and Lever disallows it, so
    the index holds only their robots.txt. Lever boards must come from the
    resolver instead.
  - Ashby is crawled very thinly (~27 boards).
  - Keka, Zoho Recruit and Darwinbox are subdomain-per-company, so they need
    matchType=domain rather than a path prefix.

Workday added 2026-08-01, NOT YET LIVE-VERIFIED against Common Crawl in this
session — the sandbox this was written in has no outbound network route to
index.commoncrawl.org (connection timed out on collinfo.json), so the query
below is built from the SAME matchType=domain pattern already proven to work
for keka.com/zohorecruit.com/darwinbox.in, plus the token shape resolve.py
already extracts from a live Workday URL (WORKDAY_RE, resolve.py). It has not
been run end-to-end. Before relying on it: run
`python3 enumerate_boards.py workday` somewhere with real network access and
confirm token count > 0 before trusting the cache.

Workday is subdomain-per-tenant like Keka (matchType=domain on
myworkdayjobs.com), but the useful token is host+site, not just the tenant
subdomain — resolve.py's fetch adapter needs 'host|tenant|site', and site is a
PATH segment (e.g. accenture.wd103.myworkdayjobs.com/AccentureCareers), not
part of the domain. So Workday cannot reuse the plain domain-mode token
extraction the other three domain-mode platforms use; it needs the full URL,
which is why _index_page's raw url list is walked directly by
_workday_token_from_url() below instead of the generic path/domain switch.

Results are cached to disk. Re-enumerating on every run would be rude and slow.
"""

from __future__ import annotations

import json
import os
import re
import urllib.parse
import urllib.request
from typing import Dict, List, Set

from core.paths import DISCOVERY_CACHE_DIR

CACHE_DIR = DISCOVERY_CACHE_DIR
UA = "OpportunityLake/0.1 (+contact: anshsonkar@users.noreply.github.com)"

# platform -> (query, mode). mode 'path' takes the first path segment as token,
# mode 'domain' takes the subdomain as token.
SOURCES: Dict[str, List[tuple]] = {
    "greenhouse": [("job-boards.greenhouse.io/*", "path", "job-boards.greenhouse.io"),
                   ("boards.greenhouse.io/*", "path", "boards.greenhouse.io")],
    "workable": [("apply.workable.com/*", "path", "apply.workable.com")],
    "smartrecruiters": [("jobs.smartrecruiters.com/*", "path", "jobs.smartrecruiters.com")],
    "ashby": [("jobs.ashbyhq.com/*", "path", "jobs.ashbyhq.com")],
    "recruitee": [("recruitee.com", "domain", "recruitee.com")],
    "keka": [("keka.com", "domain", "keka.com")],
    "zohorecruit": [("zohorecruit.com", "domain", "zohorecruit.com")],
    "darwinbox": [("darwinbox.in", "domain", "darwinbox.in")],
    # Workday is subdomain-per-tenant (matchType=domain) but the token also
    # needs a path segment (the "site"), so it is handled by its own code path
    # in enumerate_platform() rather than the generic path/domain extractor.
    "workday": [("myworkdayjobs.com", "domain", "myworkdayjobs.com")],
}

# https://{tenant}.{wdN}.myworkdayjobs.com/{locale?}/{site}
WORKDAY_URL_RE = re.compile(
    r"https?://([a-z0-9][a-z0-9-]*)\.(wd\d+)\.myworkdayjobs\.com/"
    r"(?:([a-z]{2}-[A-Z]{2})/)?([a-zA-Z0-9_-]+)",
    re.I,
)

NOT_TOKENS = {
    "www", "api", "jobs", "careers", "career", "app", "help", "docs", "embed",
    "static", "assets", "images", "cdn", "blog", "support", "mail", "en",
    "job_board", "boards", "search", "job", "v1", "v0", "share", "robots.txt",
}


def _cc_get(url: str, timeout: int = 120, attempts: int = 6) -> str:
    """GET the Common Crawl index with backoff.

    The index will drop connections or 503 if queried hard, which is fair — it
    is a free public service. Backing off is both polite and necessary.
    """
    import time

    last = ""
    for i in range(attempts):
        if i:
            time.sleep(min(30, 3 * (2 ** (i - 1))))
        try:
            with urllib.request.urlopen(
                urllib.request.Request(url, headers={"User-Agent": UA}),
                timeout=timeout,
            ) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:  # noqa: BLE001
            last = "{}: {}".format(type(e).__name__, str(e)[:120])
    raise RuntimeError("common_crawl_unreachable ({})".format(last))


def _latest_crawl() -> str:
    # Allow pinning so a long run is reproducible and needs no extra request.
    pinned = os.environ.get("CC_CRAWL_ID")
    if pinned:
        return pinned
    cache = os.path.join(CACHE_DIR, "crawl_id.txt")
    if os.path.exists(cache):
        return open(cache).read().strip()
    cid = json.loads(_cc_get("https://index.commoncrawl.org/collinfo.json", 60))[0]["id"]
    os.makedirs(CACHE_DIR, exist_ok=True)
    open(cache, "w").write(cid)
    return cid


def _index_pages(crawl: str, query: str, mode: str) -> int:
    q = "url={}&output=json&showNumPages=true".format(urllib.parse.quote(query))
    if mode == "domain":
        q += "&matchType=domain"
    url = "https://index.commoncrawl.org/{}-index?{}".format(crawl, q)
    try:
        return int(json.loads(_cc_get(url, 90)).get("pages") or 0)
    except Exception:
        return 0


def _index_page(crawl: str, query: str, mode: str, page: int) -> List[str]:
    q = "url={}&output=json&page={}".format(urllib.parse.quote(query), page)
    if mode == "domain":
        q += "&matchType=domain"
    url = "https://index.commoncrawl.org/{}-index?{}".format(crawl, q)
    out = []
    try:
        body = _cc_get(url, 180)
    except Exception:
        return out
    for line in body.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line).get("url", ""))
        except Exception:
            continue
    return out


def _workday_token_from_url(u: str) -> str:
    """Extract 'host|tenant|site' the way fetch._workday()/resolve.py expect.

    host is the full subdomain (tenant.wdN.myworkdayjobs.com), tenant is its
    first label, site is the path segment after the optional locale. Mirrors
    resolve.WORKDAY_RE's shape but keeps the wdN cluster instead of discarding
    it, since fetch._workday() needs the real host to hit /wday/cxs/.
    """
    m = WORKDAY_URL_RE.match(u)
    if not m:
        return ""
    tenant, wd, _locale, site = m.groups()
    host = "{}.{}.myworkdayjobs.com".format(tenant, wd)
    return "{}|{}|{}".format(host, tenant, site)


def enumerate_platform(platform: str, max_pages: int = 12,
                       refresh: bool = False) -> List[str]:
    """Return distinct board tokens for one platform, cached to disk."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    cache = os.path.join(CACHE_DIR, "boards_{}.json".format(platform))
    if os.path.exists(cache) and not refresh:
        return json.load(open(cache))

    crawl = _latest_crawl()
    tokens: Set[str] = set()
    for query, mode, host in SOURCES.get(platform, []):
        pages = _index_pages(crawl, query, mode) or 1
        for p in range(min(pages, max_pages)):
            for u in _index_page(crawl, query, mode, p):
                if u.endswith("robots.txt"):
                    continue
                if platform == "workday":
                    tok = _workday_token_from_url(u)
                    if tok:
                        tokens.add(tok)
                    continue
                tok = ""
                if mode == "path":
                    if host in u:
                        tok = u.split(host, 1)[1].lstrip("/").split("/")[0].split("?")[0]
                else:
                    m = re.match(
                        r"https?://([a-z0-9][a-z0-9-]*)\." + re.escape(host), u, re.I
                    )
                    tok = m.group(1) if m else ""
                tok = tok.strip().lower()
                if not tok or tok in NOT_TOKENS:
                    continue
                if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{1,60}", tok):
                    continue
                # Pure numbers are almost always ids, not company slugs.
                if tok.isdigit() and len(tok) > 4:
                    continue
                tokens.add(tok)

    result = sorted(tokens)
    # Never cache an empty result. Common Crawl throttles aggressive querying and
    # returns nothing; caching that would permanently poison the registry with
    # "this platform has no boards", which is the silent-failure mode this whole
    # project is built to avoid.
    if result:
        json.dump(result, open(cache, "w"), indent=0)
    else:
        raise RuntimeError(
            "enumeration returned 0 boards for {} — refusing to cache. "
            "Common Crawl is likely throttling; retry later.".format(platform)
        )
    return result


if __name__ == "__main__":
    import sys

    plats = sys.argv[1:] or list(SOURCES)
    grand = 0
    for p in plats:
        toks = enumerate_platform(p)
        grand += len(toks)
        print("{:<18} {:>6} boards   e.g. {}".format(
            p, len(toks), ", ".join(toks[:5])))
    print("\ntotal boards discoverable: {}".format(grand))
