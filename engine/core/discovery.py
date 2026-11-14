"""Generic discovery helpers shared by pipelines and the crawler: sitemaps, robots, Common Crawl."""

from __future__ import annotations

import gzip
import io
import json
import os
import re
import time
import urllib.parse
import urllib.request
from typing import Callable, List, Optional, Tuple

UA = "OpportunityLake/0.1 (+contact: anshsonkar@users.noreply.github.com)"
CC_INDEX = "https://index.commoncrawl.org"


def decode_body(data: bytes, max_bytes: int = 30_000_000) -> str:
    if data[:2] == b"\x1f\x8b":
        data = gzip.GzipFile(fileobj=io.BytesIO(data)).read(max_bytes)
    return data.decode("utf-8", "replace")


def parse_sitemap(text: str) -> Tuple[bool, List[str]]:
    """(is_index, <loc> urls)."""
    locs = [m.strip() for m in re.findall(r"<loc>\s*(?:<!\[CDATA\[)?\s*([^<\]\s]+)", text, flags=re.I)]
    return "<sitemapindex" in text[:2000].lower(), locs


def sitemap_entries(text: str) -> List[Tuple[str, Optional[str]]]:
    """(loc, lastmod YYYY-MM-DD or None) per <url>/<sitemap> block."""
    out: List[Tuple[str, Optional[str]]] = []
    for block in re.findall(r"<(url|sitemap)\b[^>]*>(.*?)</\1\s*>", text, flags=re.I | re.S):
        loc = re.search(r"<loc>\s*(?:<!\[CDATA\[)?\s*([^<\]\s]+)", block[1], flags=re.I)
        if not loc:
            continue
        mod = re.search(r"<lastmod>\s*(\d{4}-\d{2}-\d{2})", block[1], flags=re.I)
        out.append((loc.group(1).strip(), mod.group(1) if mod else None))
    return out


def robots_sitemaps(robots_text: str) -> List[str]:
    return [l.split(":", 1)[1].strip() for l in robots_text.splitlines()
            if l.lower().startswith("sitemap:") and l.split(":", 1)[1].strip()]


def cc_get(url: str, timeout: int = 120, attempts: int = 6, sleep: Callable = time.sleep,
           opener: Optional[Callable] = None) -> str:
    """GET the Common Crawl index with backoff (a free public service: be gentle)."""
    opener = opener or urllib.request.urlopen
    last = ""
    for i in range(attempts):
        if i:
            sleep(min(30, 3 * (2 ** (i - 1))))
        try:
            with opener(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=timeout) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:  # noqa: BLE001
            last = "{}: {}".format(type(e).__name__, str(e)[:120])
    raise RuntimeError("common_crawl_unreachable ({})".format(last))


def latest_crawl(cache_dir: str, get: Optional[Callable] = None) -> str:
    pinned = os.environ.get("CC_CRAWL_ID")
    if pinned:
        return pinned
    cache = os.path.join(cache_dir, "crawl_id.txt")
    if os.path.exists(cache):
        with open(cache) as fh:
            return fh.read().strip()
    get = get or cc_get
    cid = json.loads(get(CC_INDEX + "/collinfo.json", 60))[0]["id"]
    os.makedirs(cache_dir, exist_ok=True)
    with open(cache, "w") as fh:
        fh.write(cid)
    return cid


def cc_host_urls(host: str, crawl: str, get: Callable[[str], str], limit: int = 5000,
                 url_filter: Optional[str] = None) -> List[str]:
    """One CDX page of status-200 URLs under host/*. Raises on network error."""
    q = "url={}&output=json&fl=url,status&filter=status:200&collapse=urlkey&limit={}&page=0".format(
        urllib.parse.quote(host + "/*"), limit)
    if url_filter:
        q += "&filter=" + urllib.parse.quote("~url:" + url_filter)
    body = get("{}/{}-index?{}".format(CC_INDEX, crawl, q))
    out = []
    for line in body.splitlines():
        try:
            out.append(json.loads(line)["url"])
        except Exception:  # noqa: BLE001
            continue
    return out
