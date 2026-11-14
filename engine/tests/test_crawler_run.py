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
from pipeline import crawl_review

PORTFOLIO = """<html><head><title>Portfolio</title></head><body>
<a href="https://acmerobots.com/">Acme Robots</a>
<a href="https://www.linkedin.com/company/foo">LinkedIn</a>
<a href="https://notmatching.com/">Zed</a>
<a href="/portfolio?page=2">Next</a>
<a href="https://logoco.com/"><img alt="Logoco"></a></body></html>"""
HOME = "<html><head><title>Acme Robots</title></head><body><a href='/careers'>Careers</a><a href='/blog'>Blog</a></body></html>"
CAREERS = "<html><head><title>Careers at Acme Robots</title></head><body>We are hiring engineers.</body></html>"
FEED = ("<rss><channel>"
        "<item><title>Beta raises $5M seed</title><link>https://news.test/beta</link>"
        "<pubDate>Mon, 02 Nov 2026 10:00:00 GMT</pubDate></item>"
        "<item><title>Gadget review</title><link>https://news.test/gadget</link></item>"
        "<item><title>Old raises round</title><link>https://news.test/old</link>"
        "<pubDate>Mon, 02 Nov 2020 10:00:00 GMT</pubDate></item></channel></rss>")
ARTICLE = "<html><head><title>Beta raises</title></head><body>Beta Co raised money.</body></html>"

PAGES = {
    "https://vc.test/portfolio": PORTFOLIO,
    "https://acmerobots.com/": HOME,
    "https://logoco.com/": HOME,
    "https://vc.test/company/zed": "<html><head><title>Zed | VC</title></head><body><h1>Notmatching</h1><a href='https://notmatching.com/'>Visit website</a></body></html>",
    "https://acmerobots.com/careers": CAREERS,
    "https://feed.test/rss": FEED,
    "https://news.test/beta": ARTICLE,
}


def fake(url, polite=True):
    if url in PAGES:
        return 200, url, PAGES[url], None
    return 404, url, "", "http_404"


class TestCrawl(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name)
        self.crawler = Crawler(Frontier(2), Fetcher(50, 25, fake), Store(self.out), workers=2,
                               today=date(2026, 11, 14))
        self.crawler.add_seeds([
            {"url": "https://vc.test/portfolio", "kind": "seed", "label": "vc"},
            {"url": "https://feed.test/rss", "kind": "feed", "label": "feed"}])
        self.stats = self.crawler.run([0, 1])

    def tearDown(self):
        self.tmp.cleanup()

    def test_startup_found_and_careers_followed(self):
        items = self.crawler.frontier.items
        self.assertEqual(items["https://acmerobots.com/"]["kind"], "startup_home")
        self.assertEqual(items["https://acmerobots.com/careers"]["state"], "fetched")
        self.assertEqual(self.stats["unique_startups"], 2)
        self.assertGreaterEqual(self.stats["careers_pages"], 1)
        self.assertEqual(self.stats["careers_startups"], 2)

    def test_logo_alt_and_h1_names(self):
        items = self.crawler.frontier.items
        self.assertEqual(items["https://logoco.com/"]["lead"]["name"], "Logoco")

    def test_h1_name_on_detail_page(self):
        c = Crawler(Frontier(1), Fetcher(10, 10, fake), Store(self.out / "x"), 1)
        c.add_seeds([{"url": "https://vc.test/company/zed", "kind": "seed", "label": "vc"}])
        c.run([0])
        self.assertEqual(c.frontier.items["https://notmatching.com/"]["lead"]["name"], "Notmatching")

    def test_denied_unmatched_and_non_opportunity_links_skipped(self):
        items = self.crawler.frontier.items
        self.assertNotIn("https://www.linkedin.com/company/foo", items)

        self.assertNotIn("https://acmerobots.com/blog", items)

    def test_feed_filters_by_date_and_title(self):
        items = self.crawler.frontier.items
        self.assertIn("https://news.test/beta", items)
        self.assertNotIn("https://news.test/gadget", items)
        self.assertNotIn("https://news.test/old", items)
        self.assertEqual(items["https://news.test/beta"]["lead"]["source"], "https://feed.test/rss")

    def test_seed_pagination_followed_and_failure_marked(self):
        items = self.crawler.frontier.items
        self.assertEqual(items["https://vc.test/portfolio?page=2"]["state"], "failed")
        self.assertEqual(self.stats["errors"], 2)  # page=2 and logoco careers

    def test_parse_error_budget_rows_and_summary_survive(self):
        from unittest import mock
        out = self.out / "y"
        c = Crawler(Frontier(1), Fetcher(2, 25, fake), Store(out), 1)
        c.add_seeds([{"url": "https://vc.test/portfolio", "kind": "seed", "label": "vc"}])
        with mock.patch("crawler.run.extract.extract", side_effect=ValueError("boom")):
            stats = c.run([0])
        self.assertEqual(stats["errors"], 1)
        self.assertEqual(stats["ok"], 0)
        self.assertTrue((out / "summary.json").exists())
        rows = [json.loads(l) for l in (out / "pages-0.jsonl").read_text().splitlines()]
        self.assertEqual([r["outcome"] for r in rows], ["parse_error"])

    def test_summary_saved_when_loop_raises(self):
        from unittest import mock
        out = self.out / "z"
        c = Crawler(Frontier(1), Fetcher(5, 25, fake), Store(out), 1)
        c.add_seeds([{"url": "https://vc.test/portfolio", "kind": "seed", "label": "vc"}])
        with mock.patch.object(Crawler, "_handle", side_effect=RuntimeError("x")):
            with self.assertRaises(RuntimeError):
                c.run([0])
        self.assertTrue((out / "summary.json").exists())
        self.assertTrue((out / "frontier-0.jsonl").exists())

    def test_outputs_and_review(self):
        self.assertTrue((self.out / "summary.json").exists())
        records = [json.loads(l) for p in self.out.glob("pages-*.jsonl") for l in p.read_text().splitlines()]
        self.assertEqual(len(records), self.stats["pages_fetched"])
        rows = crawl_review.top_pages(self.out, 5)
        self.assertEqual(rows[0]["url"], "https://acmerobots.com/careers")
        self.assertIn("Careers at Acme Robots", crawl_review.render(rows))

    def test_review_excludes_source_domains(self):
        everything = crawl_review.top_pages(self.out, 50)
        self.assertIn("vc.test", {r["host"] for r in everything})
        kept = crawl_review.top_pages(self.out, 50, frozenset({"vc.test", "news.test"}))
        self.assertNotIn("vc.test", {r["host"] for r in kept})
        self.assertNotIn("news.test", {r["host"] for r in kept})
        self.assertTrue(kept)


if __name__ == "__main__":
    unittest.main()
