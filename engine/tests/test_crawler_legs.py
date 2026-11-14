import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
from datetime import date
from pathlib import Path

from crawler.fetch import Fetcher
from crawler.frontier import Frontier
from crawler.run import Crawler
from crawler.store import Store
from pipeline import crawl_merge

TODAY = date(2026, 11, 14)
PORTFOLIO = """<html><head><title>Portfolio</title></head><body>
<a href="https://acmerobots.com/">Acme Robots</a>
<a href="https://logoco.com/"><img alt="Logoco"></a></body></html>"""
HOME = "<html><head><title>Home</title></head><body>hello</body></html>"
PAGES = {"https://vc.test/portfolio": PORTFOLIO, "https://acmerobots.com/": HOME,
         "https://logoco.com/": HOME}
SEEDS = [{"url": "https://vc.test/portfolio", "kind": "seed", "label": "vc"}]
PARTS = 2


def make(log, out, max_pages=50, frontier_in=None, **kw):
    def fn(url, polite=True):
        log.append(url)
        if url in PAGES:
            return 200, url, PAGES[url], None
        return 404, url, "", "http_404"
    fr = Frontier(PARTS)
    fr.load(frontier_in or out)
    c = Crawler(fr, Fetcher(max_pages, 25, fn), Store(out), 2, today=TODAY, **kw)
    c.add_seeds(SEEDS)
    return c


class TestLegs(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def stage1(self):
        log = []
        c = make(log, self.root / "seeds", seeds_only=True)
        c.run(list(range(PARTS)))
        return log, c

    def test_seeds_only_leaves_offsite_queued(self):
        log, c = self.stage1()
        self.assertEqual(log, ["https://vc.test/portfolio"])
        self.assertEqual(c.pages, 1)
        saved = Frontier(PARTS)
        saved.load(self.root / "seeds")
        for u in ("https://acmerobots.com/", "https://logoco.com/"):
            self.assertEqual(saved.items[u]["state"], "queued")
        self.assertEqual(saved.items["https://vc.test/portfolio"]["state"], "fetched")

    def test_legs_fetch_startups_once_and_not_seeds(self):
        self.stage1()
        log = []
        for part in range(PARTS):
            c = make(log, self.root / "leg-{}".format(part), frontier_in=self.root / "seeds",
                     sitemaps=False, commoncrawl=False)
            self.assertIn("vc.test", c.seed_hosts)
            self.assertEqual(len(c.startup_domains), 2)
            c.run([part])
        self.assertEqual(sorted(log), ["https://acmerobots.com/", "https://logoco.com/"])

    def test_merge(self):
        a, b = self.root / "a", self.root / "b"
        for d in (a, b):
            d.mkdir()
        rec = lambda u: json.dumps({"final_url": u, "outcome": "ok"}) + "\n"
        (a / "pages-0.jsonl").write_text(rec("https://x.com/") + rec("https://www.x.com"))
        (b / "pages-1.jsonl").write_text(rec("https://y.com/"))
        (a / "summary.json").write_text(json.dumps({"pages_fetched": 2, "pages_by_door": {"link": 2}}))
        (b / "summary.json").write_text(json.dumps({"pages_fetched": 1, "pages_by_door": {"link": 1}}))
        ev = lambda d: {"date": d, "source_kind": "news"}
        (a / "startups.jsonl").write_text(json.dumps(
            {"domain": "s.com", "name": "S", "funding": ev("2025-01-01"), "careers_urls": ["https://s.com/c1"]}) + "\n")
        (b / "startups.jsonl").write_text(json.dumps(
            {"domain": "s.com", "name": None, "funding": ev("2026-10-01"), "careers_urls": ["https://s.com/c2"]}) + "\n")
        out = self.root / "out"
        s = crawl_merge.merge([a, b, self.root / "gone"], out, TODAY)
        self.assertEqual(s["pages_fetched"], 3)
        self.assertEqual(s["pages_by_door"]["link"], 3)
        self.assertEqual(s["legs_missing"], [str(self.root / "gone")])
        self.assertEqual(len(s["legs_ok"]), 2)
        self.assertEqual(len((out / "pages-merged.jsonl").read_text().splitlines()), 2)
        rows = [json.loads(l) for l in (out / "startups.jsonl").read_text().splitlines()]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["funding"]["date"], "2026-10-01")
        self.assertEqual(rows[0]["careers_urls"], ["https://s.com/c1", "https://s.com/c2"])
        self.assertTrue(rows[0]["startup"])


if __name__ == "__main__":
    unittest.main()
