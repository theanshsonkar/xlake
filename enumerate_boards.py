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

Results are cached to disk. Re-enumerating on every run would be rude and slow.
"""

from __future__ import annotations

import json
import os
import re
import urllib.parse
import urllib.request
from typing import Dict, List, Set

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".cache")
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
}

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
