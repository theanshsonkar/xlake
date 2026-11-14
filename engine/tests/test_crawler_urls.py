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


if __name__ == "__main__":
    unittest.main()
