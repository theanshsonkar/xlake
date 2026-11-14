"""Discovery doors: sitemap and Common Crawl URL sources for a domain the crawl already reached.

Doors only propose candidate URLs. Every candidate still goes through the normal fetch,
robots check and extraction, and shares the same per-domain caps.
"""

from __future__ import annotations

import re
import threading
import time
import urllib.parse
from collections import Counter
from datetime import date, timedelta
from typing import Callable, Dict, List, Optional, Set

from core import discovery
from core.paths import DISCOVERY_CACHE_DIR
from crawler import score, urls

MAX_SITEMAP_FILES_PER_DOMAIN = 3
DOOR_SHARE = 0.15  # doors may use at most this share of the page budget
MAX_SLUG_TOKENS = 3  # longer slugs are articles, not opportunity sections
SITEMAP_URLS_PER_DOMAIN = 25
LASTMOD_MAX_AGE_DAYS = 365
CC_DELAY = 1.0
CC_MAX_DEFAULT = 50
CC_URL_LIMIT = 200
DOOR_KINDS = ("sitemap", "cc")
SOURCE_DOORS = {"sitemap": "sitemap", "commoncrawl": "commoncrawl"}
_BAD_EXT = re.compile(r"\.(pdf|jpe?g|png|gif|svg|webp|zip|gz|xml|docx?|xlsx?|pptx?|mp4|mp3|css|js)$", re.I)


def cc_item_url(host: str) -> str:
    """Placeholder frontier key for a Common Crawl lookup (never fetched)."""
    return "https://{}/.well-known/xlake-cc-lookup".format(host)


_LOCALE = re.compile(r"^[a-z]{2}(?:[-_][a-z]{2,4})?$", re.I)


def canonical_path(loc: str) -> str:
    """Path without a leading locale segment, so /fr/careers and /careers count once."""
    segs = [x for x in urllib.parse.urlsplit(loc).path.lower().split("/") if x]
    if segs and _LOCALE.match(segs[0]):
        segs = segs[1:]
    return "/" + "/".join(segs)


def path_is_opportunity(path: str) -> bool:
    """An opportunity word must be a short path segment (/careers, /jobs/123), not part of a long slug."""
    words = [w.replace(" ", "-") for w in score.load_types()["link_words"]]
    for seg in (x for x in path.lower().split("/") if x):
        tokens = [t for t in re.split(r"[-_.]", seg) if t]
        if seg in words or (len(tokens) <= MAX_SLUG_TOKENS and any(w in tokens for w in words)):
            return True
    return False


def url_wanted(loc: str, domain: str, lastmod: Optional[str], today: date) -> bool:
    path = urllib.parse.urlsplit(loc).path
    if urls.registered_domain(loc) != domain or not path_is_opportunity(path):
        return False
    if _BAD_EXT.search(path):
        return False
    junk = set(score.load_types()["junk"])
    if junk & set(re.findall(r"[a-z0-9]+", path.lower())):
        return False
    if lastmod:
        try:
            if date.fromisoformat(lastmod) < today - timedelta(days=LASTMOD_MAX_AGE_DAYS):
                return False
        except ValueError:
            pass
    return True


class SitemapDoor:
    """Per-domain sitemap state. Used from the single result-handling thread."""

    def __init__(self, today: date):
        self.today = today
        self.files: Counter = Counter()
        self.queued: Counter = Counter()
        self.pending: Counter = Counter()
        self.host: Dict[str, str] = {}
        self.cc_asked: Set[str] = set()
        self.files_total = 0
        self.urls_total = 0
        self.seen_paths: Set[str] = set()

    # -- bookkeeping ------------------------------------------------------- #
    def start(self, domain: str, host: str) -> str:
        self.host[domain] = host
        self.pending[domain] += 1
        return "https://{}/robots.txt".format(host)

    def _room(self, domain: str) -> int:
        return MAX_SITEMAP_FILES_PER_DOMAIN - self.files[domain]

    def _take_files(self, domain: str, cands: List[str]) -> List[str]:
        out = []
        for u in cands:
            if self._room(domain) <= 0:
                break
            out.append(u)
            self.files[domain] += 1
            self.pending[domain] += 1
        return out

    def finish(self, domain: str, ok: bool = True) -> Optional[str]:
        """Called once per handled door item; returns a host to ask Common Crawl about, or None."""
        self.pending[domain] -= 1
        if self.pending[domain] <= 0 and self.queued[domain] == 0 and domain not in self.cc_asked:
            self.cc_asked.add(domain)
            return self.host.get(domain)
        return None

    # -- handling -------------------------------------------------------- #
    def handle_robots(self, url: str, body: str, domain: str, host: str) -> List[str]:
        listed = [u for u in discovery.robots_sitemaps(body or "") if urls.registered_domain(u) == domain]
        return self.plan_files(domain, listed or ["https://{}/sitemap.xml".format(host)])

    def plan_files(self, domain: str, cands: List[str]) -> List[str]:
        picked = self._take_files(domain, cands)
        self.files_total += len(picked)
        return picked

    def handle_sitemap(self, url: str, body: str, domain: str):
        """(child_sitemaps_to_push, candidate_page_urls)."""
        is_index, _ = discovery.parse_sitemap(body or "")
        entries = discovery.sitemap_entries(body or "")
        if is_index:
            kids = [loc for loc, _m in entries
                    if urls.registered_domain(loc) == domain and not loc.lower().split("?")[0].endswith(".gz")]
            words = score.load_types()["link_words"]
            kids.sort(key=lambda u: 0 if any(w in u.lower() for w in words) else 1)
            return self.plan_files(domain, kids), []
        return [], [loc for loc, mod in entries if url_wanted(loc, domain, mod, self.today)]

    def queue_urls(self, domain: str, cands: List[str], push: Callable[[str], bool]) -> int:
        n = 0
        for u in cands:
            if self.queued[domain] >= SITEMAP_URLS_PER_DOMAIN:
                break
            key = domain + canonical_path(u)
            if key in self.seen_paths:
                continue
            self.seen_paths.add(key)
            if push(u):
                self.queued[domain] += 1
                n += 1
        self.urls_total += n
        return n


class CommonCrawlDoor:
    """Thread-safe, rate-limited, budgeted Common Crawl lookups; any error switches it off."""

    def __init__(self, max_queries: int = CC_MAX_DEFAULT, delay: float = CC_DELAY,
                 get: Optional[Callable[[str], str]] = None, crawl_id: Optional[str] = None,
                 clock: Callable[[], float] = time.monotonic, sleep: Callable = time.sleep,
                 cache_dir=DISCOVERY_CACHE_DIR):
        self.max_queries, self.delay = max_queries, delay
        self.get = get or (lambda u: discovery.cc_get(u, 60, attempts=2))
        self.crawl_id, self.cache_dir = crawl_id, cache_dir
        self.clock, self.sleep = clock, sleep
        self.down = False
        self.queries = 0
        self.urls_queued = 0
        self._next = 0.0
        self._lock = threading.Lock()

    @staticmethod
    def url_filter() -> str:
        words = [w for w in score.load_types()["link_words"] if " " not in w]
        return "(" + "|".join(re.escape(w) for w in words) + ")"

    def query(self, host: str) -> List[str]:
        with self._lock:
            if self.down or self.queries >= self.max_queries:
                return []
            self.queries += 1
            now = self.clock()
            slot = max(now, self._next)
            self._next = slot + self.delay
        if slot > now:
            self.sleep(slot - now)
        if self.down:
            return []
        try:
            with self._lock:
                if not self.crawl_id:
                    self.crawl_id = discovery.latest_crawl(str(self.cache_dir), get=lambda u, t=60: self.get(u))
            return discovery.cc_host_urls(host, self.crawl_id, self.get, CC_URL_LIMIT, self.url_filter())
        except Exception:  # noqa: BLE001 - one door among many; never fail the run
            self.down = True
            return []
