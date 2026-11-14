import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gzip
from core import discovery


class FakeResp:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self.body


class TestDiscovery(unittest.TestCase):
    def test_decode_gzip_and_plain(self):
        self.assertEqual(discovery.decode_body(gzip.compress("héllo".encode()), 1000), "héllo")
        self.assertEqual(discovery.decode_body(b"a\xffb", 1000), "a�b")

    def test_parse_and_entries(self):
        xml = ("<urlset><url><loc>https://a.com/x</loc><lastmod>2026-01-02T10:00:00Z</lastmod></url>"
               "<url><loc><![CDATA[https://a.com/y]]></loc></url></urlset>")
        self.assertEqual(discovery.parse_sitemap(xml), (False, ["https://a.com/x", "https://a.com/y"]))
        self.assertEqual(discovery.sitemap_entries(xml),
                         [("https://a.com/x", "2026-01-02"), ("https://a.com/y", None)])
        idx = "<sitemapindex><sitemap><loc>https://a.com/s1.xml</loc></sitemap></sitemapindex>"
        self.assertTrue(discovery.parse_sitemap(idx)[0])
        self.assertEqual(discovery.sitemap_entries(idx), [("https://a.com/s1.xml", None)])

    def test_robots(self):
        self.assertEqual(discovery.robots_sitemaps("User-agent: *\nSitemap: https://a.com/s.xml\nsitemap:\n"),
                         ["https://a.com/s.xml"])

    def test_cc_get_retries_then_raises(self):
        sleeps, calls = [], []

        def opener(req, timeout):
            calls.append(1)
            raise OSError("boom")
        with self.assertRaises(RuntimeError):
            discovery.cc_get("https://x", attempts=3, sleep=sleeps.append, opener=opener)
        self.assertEqual((len(calls), sleeps), (3, [3, 6]))
        self.assertEqual(discovery.cc_get("https://x", opener=lambda r, timeout: FakeResp(b"ok")), "ok")

    def test_latest_crawl_pin_and_cache(self):
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.dict(os.environ, {"CC_CRAWL_ID": "PIN"}):
                self.assertEqual(discovery.latest_crawl(d), "PIN")
            env = {k: v for k, v in os.environ.items() if k != "CC_CRAWL_ID"}
            with mock.patch.dict(os.environ, env, clear=True):
                got = discovery.latest_crawl(d, get=lambda u, t=0: '[{"id": "CC-1"}]')
                self.assertEqual(got, "CC-1")
                self.assertEqual(discovery.latest_crawl(d, get=lambda u, t=0: 1 / 0), "CC-1")

    def test_cc_host_urls_query(self):
        seen = []

        def get(u):
            seen.append(u)
            return '{"url": "https://a.com/careers"}\nbad\n{"url": "https://a.com/jobs"}'
        out = discovery.cc_host_urls("a.com", "CC-1", get, limit=200, url_filter="(careers|jobs)")
        self.assertEqual(out, ["https://a.com/careers", "https://a.com/jobs"])
        self.assertIn("CC-1-index?url=a.com/%2A", seen[0])
        self.assertIn("filter=status:200&collapse=urlkey&limit=200&page=0", seen[0])
        self.assertTrue(seen[0].endswith("&filter=~url%3A%28careers%7Cjobs%29"))
        with self.assertRaises(ZeroDivisionError):
            discovery.cc_host_urls("a.com", "c", lambda u: 1 / 0)


if __name__ == "__main__":
    unittest.main()
