"""The crawl loop: pop -> fetch -> extract -> score -> store -> enqueue links."""

from __future__ import annotations

import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from collections import Counter
from typing import Dict, Iterable, List, Optional, Set

from crawler import doors, extract, funding, score, urls
from crawler.fetch import Fetcher
from crawler.frontier import Frontier, part_of
from crawler.store import Store

MAX_DEPTH = 2
SEED_PER_HOST = 60
STARTUP_PER_HOST = 6
FEED_MAX_AGE_DAYS = 365
PRIORITY = {"seed": 100, "startup_home": 90, "careers_link": 80, "feed": 70, "feed_item": 50,
            "sitemap": 30, "cc": 25, "page": 10}


class Crawler:
    def __init__(self, frontier: Frontier, fetcher: Fetcher, store: Store, workers: int = 8,
                 today: Optional[date] = None, sitemaps: bool = True, commoncrawl: bool = True,
                 cc_max: int = doors.CC_MAX_DEFAULT, cc_door: Optional[doors.CommonCrawlDoor] = None):
        self.frontier, self.fetcher, self.store = frontier, fetcher, store
        self.workers = workers
        self.today = today or date.today()
        self.seed_hosts: Set[str] = set()
        self.feed_urls: Set[str] = set()
        self.startup_domains: Set[str] = set()
        self.startups_ok: Set[str] = set()
        self.careers_urls: Set[str] = set()
        self.careers_domains: Set[str] = set()
        self.seed_kind: Dict[str, str] = {}
        self.funding: Dict[str, Dict] = {}
        self.names: Dict[str, str] = {}
        self.domain_careers: Dict[str, Set[str]] = {}
        self.pages = 0
        self.sitemaps_on = sitemaps
        self.cc = (cc_door or doors.CommonCrawlDoor(cc_max)) if commoncrawl else None
        self.sitemap = doors.SitemapDoor(self.today)
        self.probed: Set[str] = set()
        self.door_items = 0
        self.pages_by_door: Counter = Counter()

    def add_seeds(self, seeds: Iterable[dict]) -> None:
        for s in seeds:
            kind = s["kind"]
            self.seed_kind[urls.host(s["url"])] = s.get("source_kind") or (
                "news" if kind == "feed" else "investor")
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
        if item["kind"] == "cc":
            found = self.cc.query(item["host"]) if self.cc else []
            return item, doors_result(item), {"cc_urls": found}
        is_feed = item["kind"] == "feed"
        accept = "text" if item["kind"] == "sitemap" else ("feed" if is_feed else "html")
        result = self.fetcher.fetch(item["url"], self._limit(item), accept=accept)
        page = None
        if result.outcome == "ok" and item["kind"] == "sitemap":
            page = {"body": result.html}
        elif result.outcome == "ok":
            try:
                page = self._parse(item, result, is_feed)
            except Exception:  # noqa: BLE001 - one bad page must never kill the run
                result = result._replace(outcome="parse_error", error="parse_error")
                with self.fetcher._lock:
                    self.fetcher.counts["ok"] -= 1
                    self.fetcher.counts["parse_error"] += 1
        return item, result, page

    def _parse(self, item: dict, result, is_feed: bool) -> Dict:
        if is_feed:
            return {"links": [], "feed_items": extract.parse_feed(result.html)}
        page = extract.extract(result.html, result.final_url, self.today)
        page.update(url=result.final_url, status_code=result.status)
        page["lead_domain"] = (item["lead"] or {}).get("domain")
        page["hop"] = item.get("hop", 0)
        page["type_guess"] = score.type_guess(page)
        page["score"] = score.score(page)
        lead = item["lead"] or {}
        final_host = urls.host(result.final_url)
        own_site = bool(lead.get("domain") and urls.registered_domain(final_host) == lead["domain"])
        if own_site:
            kind = "own_site"
        elif item["parent"] in self.feed_urls:
            kind = "news"
        elif item["host"] in self.seed_hosts:
            kind = self.seed_kind.get(item["host"], "investor")
        else:
            kind = "page"
        page["funding"] = funding.from_page(page, result.final_url, kind, self.today)
        page["own_site"] = own_site
        ev = funding.best(lead.get("funding"), page["funding"] if own_site else None)
        if funding.is_recent(ev, self.today):
            page["tags"] = ["startup"]
            page["company_funding"] = ev
        else:
            page["tags"] = []
            if page["type_guess"] == "startup":
                page["type_guess"] = score.type_guess(page, exclude=("startup",))
        page["junk_reason"] = score.junk_reason(page)
        page["junk"] = page["junk_reason"] is not None
        return page

    def run(self, parts: List[int]) -> Dict:
        try:
            with ThreadPoolExecutor(self.workers) as pool:
                while self.fetcher.used < self.fetcher.max_pages:
                    batch = self._pop_batch(parts, min(self.workers, self.fetcher.max_pages - self.fetcher.used))
                    if not batch:
                        break
                    for item, result, page in pool.map(self._work, batch):
                        self._handle(item, result, page)
        finally:
            self.frontier.save(self.store.out)
            self.store.write_startups(self._startup_rows())
            self.store.write_summary(self.summary())
        return self.summary()

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
        if result.outcome == "budget":
            self.frontier.mark(item["url"], "skipped")
            return
        if item["kind"] in doors.DOOR_KINDS:
            self._handle_door(item, result, page)
            return
        written = self.store.append(part_of(item["url"], self.frontier.parts), item, result, page)
        self.pages += 1
        if written and result.outcome == "ok":
            self.pages_by_door[doors.SOURCE_DOORS.get(item["source"], "link")] += 1
        if result.outcome != "ok":
            self.frontier.mark(item["url"], "failed")
            return
        self.frontier.mark(item["url"], "fetched")
        if item["kind"] == "startup_home":
            self.startups_ok.add(urls.registered_domain(item["url"]))
        domain = (item["lead"] or {}).get("domain")
        if domain and item["kind"] != "feed":
            self.funding_note(domain, item, page)
        if domain and page.get("type_guess") == "careers":
            self.careers_urls.add(item["url"])
            self.careers_domains.add(domain)
            self.domain_careers.setdefault(domain, set()).add(item["url"])
        if item["kind"] == "feed":
            self._enqueue_feed(item, page["feed_items"])
        else:
            self._enqueue_links(item, page)
            self._probe_door(item, result, page)

    def _probe_door(self, item: dict, result, page: Dict) -> None:
        if not self.sitemaps_on or page.get("junk_reason") in ("parked", "vendor"):
            return
        final = result.final_url
        domain = urls.registered_domain(final)
        if domain in self.probed or score.is_denied(final):
            return
        if self.sitemap.files_total + len(self.probed) >= doors.DOOR_SHARE * self.fetcher.max_pages:
            return  # door budget spent; pages come first
        self.probed.add(domain)
        robots = self.sitemap.start(domain, urls.host(final))
        self.frontier.push(robots, "sitemap", 0, PRIORITY["sitemap"], "sitemap", item["url"], item["lead"])

    def _push_door_url(self, item: dict, source: str, url: str) -> bool:
        return self.frontier.push(url, source, 1, PRIORITY["careers_link"], "careers_link",
                                  item["url"], item["lead"])

    def _handle_door(self, item: dict, result, page: Optional[Dict]) -> None:
        self.door_items += 1
        ok = result.outcome == "ok"
        self.frontier.mark(item["url"], "fetched" if ok else "failed")
        if item["kind"] == "cc":
            domain = urls.registered_domain(item["host"])
            cands = [u for u in page["cc_urls"] if doors.url_wanted(u, domain, None, self.today)]
            self.cc.urls_queued += self.sitemap.queue_urls(
                domain, cands, lambda u: self._push_door_url(item, "commoncrawl", u))
            return
        domain = urls.registered_domain(item["url"])
        push = []
        if ok:
            body = page["body"]
            if urls.normalise(item["url"]).split("?")[0].endswith("/robots.txt"):
                push = self.sitemap.handle_robots(item["url"], body, domain, item["host"])
            else:
                push, cands = self.sitemap.handle_sitemap(item["url"], body, domain)
                self.sitemap.queue_urls(domain, cands, lambda u: self._push_door_url(item, "sitemap", u))
        elif result.outcome in ("http_error", "network_error", "not_html") and \
                item["url"].endswith("/robots.txt"):
            push = self.sitemap.plan_files(domain, ["https://{}/sitemap.xml".format(item["host"])])
        for u in push:
            self.frontier.push(u, "sitemap", 0, PRIORITY["sitemap"], "sitemap", item["url"], item["lead"])
        host = self.sitemap.finish(domain)
        if host and self.cc and not self.cc.down:
            self.frontier.push(doors.cc_item_url(host), "commoncrawl", 0, PRIORITY["cc"], "cc",
                               item["url"], item["lead"])

    def funding_note(self, domain: str, item: dict, page: Dict) -> None:
        lead = item["lead"]
        own = page.get("own_site")
        ev = funding.best(self.funding.get(domain), lead.get("funding"),
                          page.get("funding") if own else None)
        if ev:
            self.funding[domain] = ev
        if lead.get("name"):
            self.names.setdefault(domain, lead["name"])

    def _startup_rows(self) -> List[Dict]:
        rows = [{"domain": d, "name": self.names.get(d), "startup": funding.is_recent(ev, self.today),
                 "funding": ev, "careers_urls": sorted(self.domain_careers.get(d, ()))}
                for d, ev in self.funding.items()]
        rows.sort(key=lambda r: r["funding"]["date"], reverse=True)
        return rows

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
        if page.get("junk_reason") in ("parked", "vendor"):
            return
        url, lead, hop = item["url"], item["lead"], item.get("hop", 0)
        on_seed = item["host"] in self.seed_hosts
        lead_page = on_seed or item["parent"] in self.feed_urls
        own_site = bool(lead and lead.get("domain")
                        and urls.registered_domain(item["host"]) == lead["domain"])
        for link in page["links"]:
            target, text = link["url"], link["text"]
            opportunity = score.link_is_opportunity(text, target)
            if hop == 1:  # off-site hop: stay on this exact host, opportunity links only
                if urls.host(target) == item["host"] and opportunity and item["depth"] + 1 <= MAX_DEPTH:
                    self.frontier.push(target, item["source"], item["depth"] + 1,
                                       PRIORITY["careers_link"], "careers_link", url, lead, hop=1)
                continue
            if urls.same_site(url, target):
                if item["depth"] + 1 > MAX_DEPTH or not (on_seed or opportunity):
                    continue
                kind = "careers_link" if opportunity else "page"
                self.frontier.push(target, item["source"], item["depth"] + 1,
                                   PRIORITY[kind], kind, url, lead)
                continue
            if score.is_denied(target):
                continue
            domain = urls.registered_domain(target)
            name = next((n for n in (text, page.get("h1"), page.get("title_name"))
                         if n and score.name_matches_domain(n, target)), None) if lead_page else None
            if name and domain not in self.startup_domains:
                self.startup_domains.add(domain)
                parts = urllib.parse.urlsplit(target)
                home = "{}://{}/".format(parts.scheme, parts.netloc)
                ev = funding.from_anchor(text, url, self.today)
                if not ev and page.get("funding") and funding.mentions(page["funding"], page, name):
                    ev = page["funding"]
                if not ev:
                    ev = (lead or {}).get("funding")
                inherited = ev["date"] if ev else (lead or {}).get("date")
                self.frontier.push(home, url, 0, PRIORITY["startup_home"], "startup_home", url,
                                   {"name": name, "domain": domain, "source": url, "date": inherited,
                                    "funding": ev})
            elif opportunity and own_site:
                self.frontier.push(target, item["source"], 0, PRIORITY["careers_link"],
                                   "careers_link", url, lead, hop=1)

    def summary(self) -> Dict:
        c = self.fetcher.counts
        recent = {d: ev for d, ev in self.funding.items() if funding.is_recent(ev, self.today)}
        return {"pages_fetched": self.pages, "ok": c["ok"], "blocked_by_robots": c["robots"],
                "errors": c["http_error"] + c["network_error"] + c["parse_error"], "not_html": c["not_html"],
                "budget_skipped": c["budget"], "startup_leads": len(self.startups_ok),
                "unique_startups": len(recent), "startups_by_source": dict(Counter(
                    ev["source_kind"] for ev in recent.values())),
                "funding_evidence_old": len(self.funding) - len(recent),
                "careers_pages": len(self.careers_urls),
                "careers_startups": len(self.careers_domains),
                "duplicate": self.store.duplicates,
                "sitemap_files": self.sitemap.files_total, "sitemap_urls_queued": self.sitemap.urls_total,
                "cc_queries": self.cc.queries if self.cc else 0,
                "cc_urls_queued": self.cc.urls_queued if self.cc else 0,
                "cc_down": bool(self.cc and self.cc.down),
                "door_items": self.door_items,
                "pages_by_door": {k: self.pages_by_door.get(k, 0) for k in ("sitemap", "commoncrawl", "link")}}


def doors_result(item: dict):
    from crawler.fetch import Result
    return Result(None, item["url"], "", None, "ok")
