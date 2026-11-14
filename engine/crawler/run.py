"""The crawl loop: pop -> fetch -> extract -> score -> store -> enqueue links."""

from __future__ import annotations

import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from typing import Dict, Iterable, List, Optional, Set

from crawler import extract, score, urls
from crawler.fetch import Fetcher
from crawler.frontier import Frontier, part_of
from crawler.store import Store

MAX_DEPTH = 2
SEED_PER_HOST = 60
STARTUP_PER_HOST = 6
FEED_MAX_AGE_DAYS = 365
PRIORITY = {"seed": 100, "startup_home": 90, "careers_link": 80, "feed": 70, "feed_item": 50, "page": 10}


class Crawler:
    def __init__(self, frontier: Frontier, fetcher: Fetcher, store: Store, workers: int = 8,
                 today: Optional[date] = None):
        self.frontier, self.fetcher, self.store = frontier, fetcher, store
        self.workers = workers
        self.today = today or date.today()
        self.seed_hosts: Set[str] = set()
        self.feed_urls: Set[str] = set()
        self.startup_domains: Set[str] = set()
        self.startups_ok: Set[str] = set()
        self.careers_urls: Set[str] = set()
        self.careers_domains: Set[str] = set()
        self.pages = 0

    def add_seeds(self, seeds: Iterable[dict]) -> None:
        for s in seeds:
            kind = s["kind"]
            self.frontier.push(s["url"], source=s.get("label", ""), kind=kind,
                               priority=PRIORITY[kind])
        for item in self.frontier.items.values():
            if item["kind"] in ("seed", "feed"):
                self.seed_hosts.add(item["host"])
                if item["kind"] == "feed":
                    self.feed_urls.add(item["url"])

    def _limit(self, item: dict) -> int:
        if item["host"] in self.seed_hosts:
            return SEED_PER_HOST
        if item["kind"] in ("startup_home", "careers_link") or item["lead"]:
            return STARTUP_PER_HOST
        return self.fetcher.per_host

    def _work(self, item: dict):
        is_feed = item["kind"] == "feed"
        result = self.fetcher.fetch(item["url"], self._limit(item), feed=is_feed)
        page = None
        if result.outcome == "ok":
            if is_feed:
                page = {"links": [], "feed_items": extract.parse_feed(result.html)}
            else:
                page = extract.extract(result.html, result.final_url, self.today)
                page.update(url=result.final_url, status_code=result.status)
                page["type_guess"] = score.type_guess(page)
                page["score"] = score.score(page)
                page["junk"] = score.is_junk(page)
        return item, result, page

    def run(self, parts: List[int]) -> Dict:
        with ThreadPoolExecutor(self.workers) as pool:
            while self.fetcher.used < self.fetcher.max_pages:
                batch = self._pop_batch(parts, min(self.workers, self.fetcher.max_pages - self.fetcher.used))
                if not batch:
                    break
                for item, result, page in pool.map(self._work, batch):
                    self._handle(item, result, page)
        self.frontier.save(self.store.out)
        stats = self.summary()
        self.store.write_summary(stats)
        return stats

    def _pop_batch(self, parts: List[int], size: int) -> List[dict]:
        batch: List[dict] = []
        while len(batch) < size:
            got = [i for i in (self.frontier.pop(p) for p in parts[:size - len(batch)]) if i]
            if not got:
                parts = [p for p in parts if self.frontier.has_queued(p)]
                if not parts:
                    break
                continue
            batch.extend(got)
        return batch

    def _handle(self, item: dict, result, page: Optional[Dict]) -> None:
        self.store.append(part_of(item["url"], self.frontier.parts), item, result, page)
        if result.outcome == "budget":
            self.frontier.mark(item["url"], "skipped")
            return
        self.pages += 1
        if result.outcome != "ok":
            self.frontier.mark(item["url"], "failed")
            return
        self.frontier.mark(item["url"], "fetched")
        if item["kind"] == "startup_home":
            self.startups_ok.add(urls.registered_domain(item["url"]))
        domain = (item["lead"] or {}).get("domain")
        if domain and page.get("type_guess") == "careers":
            self.careers_urls.add(item["url"])
            self.careers_domains.add(domain)
        if item["kind"] == "feed":
            self._enqueue_feed(item, page["feed_items"])
        else:
            self._enqueue_links(item, page)

    def _enqueue_feed(self, item: dict, entries: List[dict]) -> None:
        cutoff = (self.today - timedelta(days=FEED_MAX_AGE_DAYS)).isoformat()
        words = score.load_types()["funding_news"]
        for e in entries:
            title = (e["title"] or "").lower()
            if (e["date"] is None or e["date"] >= cutoff) and any(w in title for w in words):
                self.frontier.push(e["link"], source=item["url"], depth=0, kind="page",
                                   priority=PRIORITY["feed_item"], parent=item["url"],
                                   lead={"name": None, "domain": None, "source": item["url"],
                                         "date": e["date"]})

    def _enqueue_links(self, item: dict, page: Dict) -> None:
        url = item["url"]
        on_seed = item["host"] in self.seed_hosts
        lead_page = on_seed or item["parent"] in self.feed_urls
        for link in page["links"]:
            target, text = link["url"], link["text"]
            opportunity = score.link_is_opportunity(text, target)
            if urls.same_site(url, target):
                if item["depth"] + 1 > MAX_DEPTH or not (on_seed or opportunity):
                    continue
                kind = "careers_link" if opportunity else "page"
                self.frontier.push(target, item["source"], item["depth"] + 1,
                                   PRIORITY[kind], kind, url, item["lead"])
                continue
            if score.is_denied(target):
                continue
            domain = urls.registered_domain(target)
            name = next((n for n in (text, page.get("h1"), page.get("title_name"))
                         if n and score.name_matches_domain(n, target)), None)
            if lead_page and domain not in self.startup_domains and name:
                self.startup_domains.add(domain)
                parts = urllib.parse.urlsplit(target)
                home = "{}://{}/".format(parts.scheme, parts.netloc)
                inherited = (item["lead"] or {}).get("date")
                self.frontier.push(home, url, 0, PRIORITY["startup_home"], "startup_home", url,
                                   {"name": name, "domain": domain, "source": url, "date": inherited})
            elif opportunity and item["lead"]:
                self.frontier.push(target, item["source"], 0, PRIORITY["careers_link"],
                                   "careers_link", url, item["lead"])

    def summary(self) -> Dict:
        c = self.fetcher.counts
        return {"pages_fetched": self.pages, "ok": c["ok"], "blocked_by_robots": c["robots"],
                "errors": c["http_error"] + c["network_error"], "not_html": c["not_html"],
                "budget_skipped": c["budget"], "unique_startups": len(self.startups_ok),
                "careers_pages": len(self.careers_urls),
                "careers_startups": len(self.careers_domains)}
