"""Budgeted, thread-safe page fetch on top of core.webfetch."""

from __future__ import annotations

import threading
from collections import Counter
from typing import Callable, NamedTuple, Optional

from core import webfetch
from crawler import urls

OUTCOMES = ("ok", "robots", "http_error", "network_error", "not_html", "budget")
_HTML_MARKERS = ("<html", "<body", "<head", "<div", "<p>", "<title", "<!doctype")
_FEED_MARKERS = ("<rss", "<feed", "<rdf", "<?xml")


class Result(NamedTuple):
    status: Optional[int]
    final_url: str
    html: str
    error: Optional[str]
    outcome: str


class Fetcher:
    def __init__(self, max_pages: int, per_host: int = 25,
                 fetch_fn: Callable = webfetch.fetch_page):
        self.max_pages = max_pages
        self.per_host = per_host
        self.fetch_fn = fetch_fn
        self.counts: Counter = Counter()
        self._hosts: Counter = Counter()
        self._used = 0
        self._lock = threading.Lock()

    @property
    def used(self) -> int:
        return self._used

    def fetch(self, url: str, host_limit: Optional[int] = None, feed: bool = False) -> Result:
        host = urls.host(url)
        limit = self.per_host if host_limit is None else host_limit
        with self._lock:
            if self._used >= self.max_pages or self._hosts[host] >= limit:
                self.counts["budget"] += 1
                return Result(None, url, "", "budget", "budget")
            self._used += 1
            self._hosts[host] += 1
        status, final, html, err = self.fetch_fn(url, polite=True)
        result = Result(status, final, html, err, self._classify(status, html, err, feed))
        with self._lock:
            self.counts[result.outcome] += 1
        return result

    @staticmethod
    def _classify(status, html, err, feed) -> str:
        if err and err.startswith("robots"):
            return "robots"
        if status is None:
            return "network_error"
        if status >= 400 or err:
            return "http_error"
        head = (html or "")[:2000].lower()
        markers = _HTML_MARKERS + (_FEED_MARKERS if feed else ())
        if "\x00" in head or not any(m in head for m in markers):
            return "not_html"
        return "ok"
