import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawler.fetch import Fetcher

PAGE = "<html><body><p>hello</p></body></html>"


def fake(table):
    def fn(url, polite=True):
        return table[url]
    return fn


class TestFetcher(unittest.TestCase):
    def test_outcomes(self):
        table = {
            "https://a.com/ok": (200, "https://a.com/ok", PAGE, None),
            "https://a.com/robots": (None, "https://a.com/robots", "", "robots_disallow"),
            "https://a.com/404": (404, "https://a.com/404", "", "http_404"),
            "https://a.com/net": (None, "https://a.com/net", "", "URLError: x"),
            "https://a.com/pdf": (200, "https://a.com/pdf", "%PDF-1.4 binary", None),
        }
        f = Fetcher(100, 100, fake(table))
        got = {u.rsplit("/", 1)[1]: f.fetch(u).outcome for u in table}
        self.assertEqual(got, {"ok": "ok", "robots": "robots", "404": "http_error",
                               "net": "network_error", "pdf": "not_html"})

    def test_host_and_run_budget(self):
        f = Fetcher(3, 2, fake({"https://a.com/%d" % i: (200, "", PAGE, None) for i in range(5)}
                               | {"https://b.com/1": (200, "", PAGE, None)}))
        self.assertEqual(f.fetch("https://a.com/0").outcome, "ok")
        self.assertEqual(f.fetch("https://a.com/1").outcome, "ok")
        self.assertEqual(f.fetch("https://a.com/2").outcome, "budget")
        self.assertEqual(f.fetch("https://b.com/1").outcome, "ok")
        self.assertEqual(f.fetch("https://a.com/3", host_limit=9).outcome, "budget")  # run cap
        self.assertEqual(f.used, 3)

    def test_feed_xml_allowed_only_when_feed(self):
        xml = "<?xml version='1.0'?><rss></rss>"
        f = Fetcher(10, 10, fake({"https://a.com/f": (200, "", xml, None)}))
        self.assertEqual(f.fetch("https://a.com/f").outcome, "not_html")
        self.assertEqual(f.fetch("https://a.com/f", feed=True).outcome, "ok")


if __name__ == "__main__":
    unittest.main()
