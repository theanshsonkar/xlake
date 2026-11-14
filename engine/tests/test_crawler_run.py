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
                               today=date(2026, 11, 14), sitemaps=False, commoncrawl=False)
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
        self.assertEqual(self.stats["startup_leads"], 2)
        self.assertEqual(self.stats["unique_startups"], 0)
        self.assertGreaterEqual(self.stats["careers_pages"], 1)
        self.assertEqual(self.stats["careers_startups"], 2)

    def test_logo_alt_and_h1_names(self):
        items = self.crawler.frontier.items
        self.assertEqual(items["https://logoco.com/"]["lead"]["name"], "Logoco")

    def test_h1_name_on_detail_page(self):
        c = Crawler(Frontier(1), Fetcher(10, 10, fake), Store(self.out / "x"), 1, sitemaps=False, commoncrawl=False)
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
        c = Crawler(Frontier(1), Fetcher(2, 25, fake), Store(out), 1, sitemaps=False, commoncrawl=False)
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
        c = Crawler(Frontier(1), Fetcher(5, 25, fake), Store(out), 1, sitemaps=False, commoncrawl=False)
        c.add_seeds([{"url": "https://vc.test/portfolio", "kind": "seed", "label": "vc"}])
        with mock.patch.object(Crawler, "_handle", side_effect=RuntimeError("x")):
            with self.assertRaises(RuntimeError):
                c.run([0])
        self.assertTrue((out / "summary.json").exists())
        self.assertTrue((out / "frontier-0.jsonl").exists())

    def _crawl(self, pages, seeds, name):
        table = dict(pages)

        def fn(url, polite=True):
            return (200, url, table[url], None) if url in table else (404, url, "", "http_404")
        c = Crawler(Frontier(1), Fetcher(50, 25, fn), Store(self.out / name), 1, today=date(2026, 11, 14), sitemaps=False, commoncrawl=False)
        c.add_seeds(seeds)
        c.run([0])
        return c.frontier.items

    def test_funding_door(self):
        pages = {
            "https://yc.test/companies": "<title>Companies</title><a href='/companies/acme'>Acme</a>",
            "https://yc.test/companies/acme": "<title>Acme | YC</title><h1>Acme</h1>"
                "<p>Batch: Winter 2026</p><p>Apply for Winter 2027</p>"
                "<a href='https://acme.com/'>Acme</a>",
            "https://acme.com/": "<title>Acme</title><a href='/careers'>Careers</a>",
            "https://acme.com/careers": "<title>Careers at Acme</title>We are hiring.",
            "https://news.test/a": "<html><head><title>News</title>"
                "<meta property='article:published_time' content='2026-10-01T09:00:00Z'></head><body>"
                "<p>Betaco raised a $5M seed round led by Foo Ventures.</p>"
                "<a href='https://betaco.com/'>Betaco</a>"
                "<a href='https://othercorp.com/'>Othercorp</a></body></html>",
            "https://betaco.com/": "<title>Beta Co</title>hello",
            "https://othercorp.com/": "<title>Othercorp</title>hello",
            "https://vc.test/p": "<title>P</title><a href='https://plainco.com/'>Plainco</a>",
            "https://plainco.com/": "<title>Plainco</title><a href='/careers'>Careers</a>",
            "https://plainco.com/careers": "<title>Careers at Plainco</title>We are hiring.",
        }
        seeds = [{"url": "https://yc.test/companies", "kind": "seed", "label": "yc", "source_kind": "accelerator"},
                 {"url": "https://news.test/a", "kind": "seed", "label": "n", "source_kind": "news"},
                 {"url": "https://vc.test/p", "kind": "seed", "label": "vc"}]
        out = self.out / "door"
        table = dict(pages)

        def fn(url, polite=True):
            return (200, url, table[url], None) if url in table else (404, url, "", "http_404")
        c = Crawler(Frontier(1), Fetcher(50, 25, fn), Store(out), 1, today=date(2026, 11, 14), sitemaps=False, commoncrawl=False)
        c.add_seeds(seeds)
        stats = c.run([0])
        rows = {json.loads(l)["domain"]: json.loads(l)
                for l in (out / "startups.jsonl").read_text().splitlines()}
        self.assertTrue(rows["acme.com"]["startup"])
        self.assertEqual(rows["acme.com"]["funding"]["source_kind"], "accelerator")
        self.assertEqual(rows["acme.com"]["funding"]["proof"], "https://yc.test/companies/acme")
        self.assertTrue(rows["betaco.com"]["startup"])
        self.assertEqual(rows["betaco.com"]["funding"]["source_kind"], "news")
        self.assertNotIn("othercorp.com", {d for d, r in rows.items() if r["startup"]})
        self.assertNotIn("plainco.com", {d for d, r in rows.items() if r["startup"]})
        self.assertEqual(stats["unique_startups"], 2)
        self.assertEqual(stats["startups_by_source"], {"accelerator": 1, "news": 1})
        self.assertEqual(c.frontier.items["https://plainco.com/careers"]["state"], "fetched")
        recs = [json.loads(l) for l in (out / "pages-0.jsonl").read_text().splitlines()]
        plain = [r for r in recs if r["final_url"] == "https://plainco.com/"][0]
        self.assertEqual(plain["tags"], [])
        acme = [r for r in recs if r["final_url"] == "https://acme.com/"][0]
        self.assertEqual(acme["tags"], ["startup"])

    def test_offsite_hop_rules(self):
        pages = {
            "https://vc.test/p": "<title>P</title><a href='https://acmerobots.com/'>Acme Robots</a>",
            "https://acmerobots.com/": "<title>Acme Robots</title><a href='https://ats.test/acme/jobs'>Jobs</a>",
            "https://ats.test/acme/jobs": "<title>Jobs</title><a href='/acme/jobs/1'>Open job</a>"
                                          "<a href='https://other.test/careers'>More careers</a>"
                                          "<a href='/about'>About</a>",
            "https://ats.test/acme/jobs/1": "<title>Role</title>",
        }
        items = self._crawl(pages, [{"url": "https://vc.test/p", "kind": "seed", "label": "v"}], "hop")
        self.assertEqual(items["https://ats.test/acme/jobs"]["hop"], 1)
        self.assertEqual(items["https://ats.test/acme/jobs"]["lead"]["domain"], "acmerobots.com")
        self.assertEqual(items["https://ats.test/acme/jobs/1"]["hop"], 1)
        self.assertNotIn("https://other.test/careers", items)
        self.assertNotIn("https://ats.test/about", items)

    def test_no_links_from_parked_or_vendor_pages(self):
        pages = {
            "https://vc.test/p": "<title>P</title><a href='https://acmerobots.com/'>Acme Robots</a>",
            "https://acmerobots.com/": "<title>Acme Robots</title><p>This domain is for sale</p>"
                                       "<a href='/careers'>Careers</a>",
        }
        items = self._crawl(pages, [{"url": "https://vc.test/p", "kind": "seed", "label": "v"}], "park")
        self.assertNotIn("https://acmerobots.com/careers", items)

    def test_duplicate_final_url_written_once(self):
        pages = {"https://a.test/x": "<title>X</title>hello", "https://www.a.test/x/": "<title>X</title>hello"}

        def fn(url, polite=True):
            return 200, "https://a.test/x", pages["https://a.test/x"], None
        store = Store(self.out / "dup")
        c = Crawler(Frontier(1), Fetcher(10, 10, fn), store, 1, sitemaps=False, commoncrawl=False)
        c.add_seeds([{"url": "https://a.test/x", "kind": "seed", "label": "a"},
                     {"url": "https://b.test/y", "kind": "seed", "label": "b"}])
        stats = c.run([0])
        rows = (self.out / "dup" / "pages-0.jsonl").read_text().splitlines()
        self.assertEqual(len(rows), 1)
        self.assertEqual(stats["duplicate"], 1)
        self.assertEqual(stats["pages_fetched"], 2)

    def test_review_columns_and_stats_line(self):
        rows = crawl_review.read_rows(self.out)
        text = crawl_review.render(crawl_review.top_pages(rows, 5), rows, "My title")
        self.assertTrue(text.startswith("# My title"))
        self.assertIn("careers startups:", text)
        self.assertIn("| rank | url | title | organiser | type | score | status | startup | snippet | real/junk |", text)
        self.assertEqual(crawl_review.stats(rows)["unique startups"], 2)

    def test_outputs_and_review(self):
        self.assertTrue((self.out / "summary.json").exists())
        records = [json.loads(l) for p in self.out.glob("pages-*.jsonl") for l in p.read_text().splitlines()]
        self.assertEqual(len(records), self.stats["pages_fetched"])
        rows = crawl_review.top_pages(crawl_review.read_rows(self.out), 5)
        self.assertEqual(rows[0]["url"], "https://acmerobots.com/careers")
        self.assertIn("Careers at Acme Robots", crawl_review.render(rows, crawl_review.read_rows(self.out)))

    def test_review_excludes_source_domains(self):
        everything = crawl_review.top_pages(crawl_review.read_rows(self.out), 50)
        self.assertIn("vc.test", {r["host"] for r in everything})
        kept = crawl_review.top_pages(crawl_review.read_rows(self.out), 50, frozenset({"vc.test", "news.test"}))
        self.assertNotIn("vc.test", {r["host"] for r in kept})
        self.assertNotIn("news.test", {r["host"] for r in kept})
        self.assertTrue(kept)


if __name__ == "__main__":
    unittest.main()
