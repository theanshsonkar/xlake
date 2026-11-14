import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawler import urls


class TestUrls(unittest.TestCase):
    def test_normalise_strips_tracking_and_fragment(self):
        self.assertEqual(urls.normalise("HTTPS://Example.com/a?utm_source=x&id=2&fbclid=z#top"),
                         "https://example.com/a?id=2")

    def test_registered_domain(self):
        self.assertEqual(urls.registered_domain("https://blog.acme.io/x"), "acme.io")
        self.assertEqual(urls.registered_domain("https://jobs.acme.co.in/x"), "acme.co.in")

    def test_same_site(self):
        self.assertTrue(urls.same_site("https://a.acme.com/", "https://www.acme.com/x"))
        self.assertFalse(urls.same_site("https://acme.com/", "https://acme.org/"))

    def test_invalid_url_gives_empty(self):
        bad = "http://host:Experience Optimization, Q4 2024/x"
        self.assertEqual(urls.normalise(bad), "")
        urls.host(bad)  # must not raise
        urls.registered_domain(bad)

    def test_key_ignores_scheme_www_slash_and_tracking(self):
        a = urls.key("https://www.Acme.com/jobs/?gh_src=x&source=y&gh_jid=7")
        self.assertEqual(a, urls.key("http://acme.com/jobs?gh_jid=7"))
        self.assertEqual(urls.key("https://acme.com/"), "acme.com/")
        self.assertNotEqual(urls.key("https://acme.com/jobs?gh_jid=7"), urls.key("https://acme.com/jobs?gh_jid=8"))


if __name__ == "__main__":
    unittest.main()
