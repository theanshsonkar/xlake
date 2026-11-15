import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
import tempfile
from datetime import date
from pathlib import Path

from crawler.fetch import Fetcher
from crawler.frontier import Frontier
from crawler.run import Crawler
from crawler.store import Store
from pipeline import crawl_merge

TODAY = date(2026, 11, 14)


def page(title, links="", body=""):
    return "<html><head><title>{}</title></head><body>{}{}</body></html>".format(title, body, links)


def a(url, text):
    return "<a href='{}'>{}</a>".format(url, text)


class TestOutlinks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def crawl(self, pages, seeds=("https://seed.test/",), name="r", max_pages=60):
        def fn(url, polite=True):
            return (200, url, pages[url], None) if url in pages else (404, url, "", "http_404")
        c = Crawler(Frontier(1), Fetcher(max_pages, 25, fn), Store(self.out / name), 1,
                    today=TODAY, sitemaps=False, commoncrawl=False)
        c.add_seeds([{"url": u, "kind": "seed", "label": "s"} for u in seeds])
        stats = c.run([0])
        return c, stats

    def test_rules(self):
        links = (a("https://other.test/careers", "Careers") + a("https://notes.test/", "Blog")
                 + a("https://www.linkedin.com/jobs/view/1", "Jobs"))
        pages = {"https://seed.test/": page("Seed", links),
                 "https://other.test/careers": page("Careers at Other", a("https://third.test/jobs", "Jobs")),
                 "https://third.test/jobs": page("Jobs at Third")}
        c, stats = self.crawl(pages)
        items = c.frontier.items
        self.assertEqual(items["https://other.test/careers"]["kind"], "outlink")
        self.assertEqual(items["https://other.test/careers"]["priority"], 40)
        self.assertEqual(items["https://other.test/careers"]["state"], "fetched")
        self.assertNotIn("https://notes.test/", items)
        self.assertFalse([u for u in items if "linkedin" in u])
        self.assertEqual(items["https://third.test/jobs"]["state"], "fetched")  # spread one more site
        self.assertEqual(stats["new_sites"], 2)
        self.assertEqual(stats["pages_by_door"]["outlink"], 2)

    def test_junk_page_does_not_spread(self):
        pages = {"https://seed.test/": page("Seed", a("https://other.test/careers", "Careers"))}
        pages["https://seed.test/"] = page("Seed shop cart login", a("https://other.test/careers", "Careers"))
        c, _ = self.crawl(pages)
        junk = c.frontier.items["https://seed.test/"]
        self.assertEqual(junk["state"], "fetched")
        from crawler import score
        if score.junk_reason({"url": "https://seed.test/", "title": "Seed shop cart login", "text": ""}):
            self.assertNotIn("https://other.test/careers", c.frontier.items)

    def test_caps(self):
        many = "".join(a("https://s{}.test/careers".format(i), "Careers") for i in range(15))
        dup = a("https://dup.test/careers", "Careers") + a("https://dup.test/jobs", "Jobs")
        c, _ = self.crawl({"https://seed.test/": page("Seed", many)}, max_pages=1)
        out = [u for u, i in c.frontier.items.items() if i["kind"] == "outlink"]
        self.assertEqual(len(out), 10)
        c, _ = self.crawl({"https://seed.test/": page("Seed", dup)}, name="d", max_pages=1)
        self.assertEqual(len([i for i in c.frontier.items.values() if i["kind"] == "outlink"]), 1)

    def test_outlink_host_cap(self):
        from crawler.run import OUTLINK_PER_HOST
        c, _ = self.crawl({}, max_pages=1)
        c.outlink_hosts.add("x.test")
        self.assertEqual(c._limit({"host": "x.test", "kind": "page", "lead": None}), OUTLINK_PER_HOST)
        self.assertEqual(c._limit({"host": "y.test", "kind": "outlink", "lead": None}), OUTLINK_PER_HOST)


def item(url, kind="page", state="queued", priority=10, at=None, **kw):
    d = {"url": url, "host": url.split("/")[2], "source": "", "depth": 0, "priority": priority,
         "state": state, "parent": None, "lead": None, "kind": kind, "hop": 0}
    if at:
        d["at"] = at
    d.update(kw)
    return d


def load(items, parts=1):
    f = Frontier(parts)
    for i in items:
        f.items[i["url"]] = i
        f._keys.add(i["url"])
    return f


class TestPrepare(unittest.TestCase):
    def test_states(self):
        f = load([
            item("https://a.test/skipped", state="skipped", at="2026-11-13"),
            item("https://a.test/seed", "seed", "fetched", 100, "2026-11-13"),
            item("https://a.test/feed", "feed", "failed", 70, "2026-11-13"),
            item("https://a.test/oldcar", "careers_link", "fetched", 80, "2026-10-01"),
            item("https://a.test/freshcar", "careers_link", "fetched", 80, "2026-11-12"),
            item("https://a.test/oldfail", state="failed", at="2026-09-01"),
            item("https://a.test/maxfail", state="failed", at="2026-09-01", retries=2),
            item("https://a.test/newfail", state="failed", at="2026-11-10"),
        ])
        f.prepare_next_run(TODAY)
        it = f.items
        self.assertEqual(it["https://a.test/skipped"]["state"], "queued")
        self.assertEqual(it["https://a.test/seed"]["state"], "queued")
        self.assertEqual(it["https://a.test/seed"]["priority"], 100)
        self.assertEqual(it["https://a.test/feed"]["state"], "queued")
        c = it["https://a.test/oldcar"]
        self.assertEqual((c["state"], c["recheck"], c["priority"]), ("queued", True, 60))
        self.assertEqual(it["https://a.test/freshcar"]["state"], "fetched")
        self.assertEqual(it["https://a.test/oldfail"]["state"], "queued")
        self.assertEqual(it["https://a.test/oldfail"]["retries"], 1)
        self.assertEqual(it["https://a.test/maxfail"]["state"], "failed")
        self.assertEqual(it["https://a.test/newfail"]["state"], "failed")
        self.assertEqual(f.pop(0)["url"], "https://a.test/seed")  # heaps rebuilt, priority order

    def test_empty_noop(self):
        Frontier(2).prepare_next_run(TODAY)

    def test_cap_drops_lowest_priority_queued_first(self):
        f = load([
            item("https://a.test/low", priority=5, at="2026-11-01"),
            item("https://a.test/high", priority=50, at="2026-11-01"),
            item("https://a.test/done", "careers_link", "fetched", 80, "2026-11-13"),
            item("https://a.test/pg", "page", "fetched", 10, "2026-01-01"),
        ])
        f.prepare_next_run(TODAY, max_items=3)
        self.assertNotIn("https://a.test/low", f.items)
        self.assertEqual(len(f.items), 3)
        f.prepare_next_run(TODAY, max_items=1)
        self.assertEqual(list(f.items), ["https://a.test/done"])


class TestRecheck(unittest.TestCase):
    def test_dead_link_share(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = load([item("https://gone.test/careers", "careers_link", "queued", 60, recheck=True)])
            c = Crawler(f, Fetcher(5, 25, lambda u, polite=True: (404, u, "", "http_404")),
                        Store(Path(tmp)), 1, today=TODAY, sitemaps=False, commoncrawl=False)
            c.frontier._rebuild_heaps()
            stats = c.run([0])
            self.assertEqual((stats["rechecked"], stats["recheck_dead"]), (1, 1))
            self.assertEqual(stats["dead_link_share"], 1.0)
            rows = [json.loads(l) for l in (Path(tmp) / "pages-0.jsonl").read_text().splitlines()]
            self.assertTrue(rows[0]["recheck"])
            self.assertEqual(f.items["https://gone.test/careers"]["at"], "2026-11-14")


class TestMergeFrontier(unittest.TestCase):
    def test_precedence_and_parts(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            u = "https://a.test/x"
            w = lambda d, items: (d.mkdir(), (d / "frontier-0.jsonl").write_text(
                "".join(json.dumps(i) + "\n" for i in items)))
            w(tmp / "l0", [item(u, state="queued"), item("https://b.test/y", state="failed", at="2026-11-01", retries=1),
                           item("https://c.test/z", state="queued", lead={"funding": {"date": "x"}})])
            w(tmp / "l1", [item(u, state="fetched", at="2026-11-14"),
                           item("https://b.test/y", state="failed", at="2026-11-10", retries=0),
                           item("https://c.test/z", state="fetched", at="2026-11-14", lead={"funding": None})])
            s = crawl_merge.merge_frontiers([tmp / "l0", tmp / "l1"], tmp / "out", 4)
            self.assertEqual(s, {"frontier_items": 3, "frontier_queued": 0})
            rows = {}
            for p in (tmp / "out" / "frontier").glob("frontier-*.jsonl"):
                for line in p.read_text().splitlines():
                    r = json.loads(line)
                    rows[r["url"]] = r
                    from crawler.frontier import part_of
                    self.assertTrue(p.name.endswith("-{}.jsonl".format(part_of(r["url"], 4))))
            self.assertEqual(rows[u]["state"], "fetched")
            self.assertEqual(rows["https://b.test/y"]["at"], "2026-11-10")
            self.assertEqual(rows["https://b.test/y"]["retries"], 1)
            self.assertEqual(rows["https://c.test/z"]["lead"]["funding"]["date"], "x")


if __name__ == "__main__":
    unittest.main()
