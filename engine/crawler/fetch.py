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

    def fetch(self, url: str, host_limit: Optional[int] = None, feed: bool = False,
              accept: Optional[str] = None) -> Result:
        accept = accept or ("feed" if feed else "html")
        host = urls.host(url)
        limit = self.per_host if host_limit is None else host_limit
        with self._lock:
            door = accept == "text"  # door files do not use a page's per-host allowance
            if self._used >= self.max_pages or (not door and self._hosts[host] >= limit):
                self.counts["budget"] += 1
                return Result(None, url, "", "budget", "budget")
            self._used += 1
            if not door:
                self._hosts[host] += 1
        status, final, html, err = self.fetch_fn(url, polite=True)
        result = Result(status, final, html, err, self._classify(status, html, err, accept))
        with self._lock:
            self.counts[result.outcome] += 1
        return result

    @staticmethod
    def _classify(status, html, err, accept="html") -> str:
        if accept is True:
            accept = "feed"
        elif accept is False:
            accept = "html"
        if err and err.startswith("robots"):
            return "robots"
        if status is None:
            return "network_error"
        if status >= 400 or err:
            return "http_error"
        head = (html or "")[:2000].lower()
        if accept == "text":
            return "not_html" if "\x00" in head else "ok"
        markers = _HTML_MARKERS + (_FEED_MARKERS if accept == "feed" else ())
        if "\x00" in head or not any(m in head for m in markers):
            return "not_html"
        return "ok"
