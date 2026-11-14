import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
from datetime import date
from pathlib import Path

from crawler import doors
from crawler.fetch import Fetcher
from crawler.frontier import Frontier
from crawler.run import Crawler
from crawler.store import Store

TODAY = date(2026, 11, 14)
HOME = "<html><head><title>Acme Robots</title></head><body>Robots for everyone.</body></html>"
JOB = "<html><head><title>Careers at Acme Robots</title></head><body>We are hiring engineers.</body></html>"
INDEX = ("<sitemapindex><sitemap><loc>https://acme.com/sitemap-blog.xml</loc></sitemap>"
         "<sitemap><loc>https://acme.com/sitemap-jobs.xml</loc></sitemap>"
         "<sitemap><loc>https://other.com/s.xml</loc></sitemap>"
         "<sitemap><loc>https://acme.com/s.xml.gz</loc></sitemap></sitemapindex>")
URLSET = ("<urlset>"
          "<url><loc>https://acme.com/careers/old</loc><lastmod>2024-01-01</lastmod></url>"
          "<url><loc>https://acme.com/careers/new</loc><lastmod>2026-10-01</lastmod></url>"
          "<url><loc>https://acme.com/blog/our-hiring-story</loc></url>"
          "<url><loc>https://acme.com/careers/guide.pdf</loc></url></urlset>")
SEED = {"url": "https://acme.com/", "kind": "startup_home", "label": "x"}


def make(pages, tmp, **kw):
    def fn(url, polite=True):
        if url in pages:
            return 200, url, pages[url], None
        return 404, url, "", "http_404"
    c = Crawler(Frontier(1), Fetcher(100, 25, fn), Store(Path(tmp)), 1, today=TODAY, **kw)
    c.frontier.push("https://acme.com/", "t", 0, 90, "startup_home", None,
                    {"name": "Acme", "domain": "acme.com", "source": "t", "date": None, "funding": None})
    return c


def stored(tmp):
    rows = []
    for p in Path(tmp).glob("pages-*.jsonl"):
        rows += [json.loads(l) for l in p.read_text().splitlines()]
    return rows


class NoCC:
    """Common Crawl door that must not be used."""
    def __init__(self):
        self.calls = []

    def get(self, url):
        self.calls.append(url)
        raise AssertionError("cc not expected")


class TestDoors(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_robots_index_urlset(self):
        pages = {"https://acme.com/": HOME,
                 "https://acme.com/robots.txt": "User-agent: *\nSitemap: https://acme.com/sitemap.xml\n"
                                                "Sitemap: https://evil.com/sm.xml\n",
                 "https://acme.com/sitemap.xml": INDEX,
                 "https://acme.com/sitemap-jobs.xml": URLSET,
                 "https://acme.com/sitemap-blog.xml": "<urlset></urlset>",
                 "https://acme.com/careers/new": JOB, "https://acme.com/careers/old": JOB}
        cc = doors.CommonCrawlDoor(get=NoCC().get)
        c = make(pages, self.tmp.name, cc_door=cc)
        s = c.run([0])
        self.assertEqual(s["sitemap_files"], 3)  # sitemap.xml + two same-domain children
        self.assertEqual(s["sitemap_urls_queued"], 1)
        rows = stored(self.tmp.name)
        urls_ = {r["url"] for r in rows}
        self.assertIn("https://acme.com/careers/new", urls_)
        self.assertFalse(urls_ & {"https://acme.com/careers/old", "https://acme.com/blog/our-hiring-story",
                                  "https://acme.com/careers/guide.pdf"})
        self.assertEqual(s["pages_by_door"]["sitemap"], 1)
        self.assertEqual(s["cc_queries"], 0)

    def test_door_items_not_stored(self):
        pages = {"https://acme.com/": HOME, "https://acme.com/robots.txt": "Sitemap: https://acme.com/s.xml",
                 "https://acme.com/s.xml": URLSET, "https://acme.com/careers/new": JOB}
        c = make(pages, self.tmp.name, commoncrawl=False)
        s = c.run([0])
        self.assertEqual(s["door_items"], 2)
        self.assertFalse([r for r in stored(self.tmp.name) if r["kind"] in ("sitemap", "cc")])

    def test_sitemap_xml_fallback(self):
        pages = {"https://acme.com/": HOME, "https://acme.com/robots.txt": "User-agent: *\nDisallow:\n",
                 "https://acme.com/sitemap.xml": URLSET, "https://acme.com/careers/new": JOB}
        s = make(pages, self.tmp.name, commoncrawl=False).run([0])
        self.assertEqual(s["sitemap_urls_queued"], 1)
        self.assertEqual(s["pages_by_door"]["sitemap"], 1)

    def test_no_sitemap_triggers_cc(self):
        pages = {"https://acme.com/": HOME, "https://acme.com/careers/cc": JOB}
        got = []

        def get(u):
            got.append(u)
            if "collinfo" in u:
                return '[{"id": "CC-TEST"}]'
            return ('{"url": "https://acme.com/careers/cc"}\n{"url": "https://acme.com/blog/x-jobs"}\n'
                    '{"url": "https://zzz.com/careers"}')
        cc = doors.CommonCrawlDoor(get=get, delay=0, crawl_id="CC-TEST")
        s = make(pages, self.tmp.name, cc_door=cc).run([0])
        self.assertEqual(s["cc_queries"], 1)
        self.assertEqual(s["cc_urls_queued"], 1)
        self.assertFalse(s["cc_down"])
        self.assertEqual(s["pages_by_door"]["commoncrawl"], 1)
        self.assertIn("filter=~url", got[0])

    def test_cc_failure_marks_down_and_finishes(self):
        pages = {"https://acme.com/": HOME}

        def get(u):
            raise RuntimeError("503")
        cc = doors.CommonCrawlDoor(get=get, delay=0, crawl_id="X")
        s = make(pages, self.tmp.name, cc_door=cc).run([0])
        self.assertTrue(s["cc_down"])
        self.assertEqual(s["ok"] >= 1, True)

    def test_cc_budget(self):
        calls = []
        cc = doors.CommonCrawlDoor(max_queries=1, delay=0, crawl_id="X", get=lambda u: calls.append(u) or "")
        self.assertEqual(cc.query("a.com"), [])
        self.assertEqual(cc.query("b.com"), [])
        self.assertEqual(len(calls), 1)

    def test_caps(self):
        locs = "".join("<url><loc>https://acme.com/careers/p{}</loc></url>".format(i) for i in range(40))
        kids = "".join("<sitemap><loc>https://acme.com/careers-{}.xml</loc></sitemap>".format(i) for i in range(10))
        d = doors.SitemapDoor(TODAY)
        robots = d.start("acme.com", "acme.com")
        self.assertTrue(robots.endswith("/robots.txt"))
        first = d.handle_robots(robots, "Sitemap: https://acme.com/i.xml", "acme.com", "acme.com")
        push, _ = d.handle_sitemap(first[0], "<sitemapindex>" + kids + "</sitemapindex>", "acme.com")
        self.assertEqual(len(push), doors.MAX_SITEMAP_FILES_PER_DOMAIN - 1)
        _, cands = d.handle_sitemap("u", "<urlset>" + locs + "</urlset>", "acme.com")
        self.assertEqual(len(cands), 40)
        n = d.queue_urls("acme.com", cands, lambda u: True)
        self.assertEqual(n, doors.SITEMAP_URLS_PER_DOMAIN)


if __name__ == "__main__":
    unittest.main()
