"""core.webfetch with a fake opener (no network)."""
import gzip
import io
import os
import ssl
import sys
import unittest
import urllib.error
from email.message import Message
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import webfetch  # noqa: E402


def hdrs(**kw):
    m = Message()
    for k, v in kw.items():
        m[k.replace("_", "-")] = v
    return m


class Resp:
    def __init__(self, body=b"<html>ok</html>", code=200, **h):
        self._b, self.code, self.headers = body, code, hdrs(**h)

    def read(self, n=-1):
        return self._b

    def getcode(self):
        return self.code

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def err(code, **h):
    return urllib.error.HTTPError("http://x", code, "m", hdrs(**h), io.BytesIO(b""))


class Fake:
    def __init__(self, script):
        self.script, self.calls = list(script), []

    def __call__(self, req, timeout):
        self.calls.append((req.full_url, req.get_header("User-agent")))
        item = self.script.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


def run(script, url="https://a.org/p", **kw):
    f = Fake(script)
    sleeps = []
    out = webfetch.fetch_page(url, opener=f, sleep=sleeps.append, polite=False, **kw)
    return out, f, sleeps


class T(unittest.TestCase):
    def test_headers_and_gzip(self):
        (st, fin, html, e), f, _ = run([Resp(gzip.compress(b"hello"), Content_Encoding="gzip")])
        self.assertEqual((st, html, e), (200, "hello", None))
        self.assertIn("XlakeBot", f.calls[0][1])
        h = webfetch.headers()
        self.assertEqual(h["Accept-Encoding"], "gzip")
        self.assertEqual(h["Upgrade-Insecure-Requests"], "1")

    def test_redirects_all_codes_and_final_url(self):
        for code in (301, 302, 303, 307, 308):
            (st, fin, _, e), _, _ = run([err(code, Location="/new"), Resp()])
            self.assertEqual((st, fin, e), (200, "https://a.org/new", None))

    def test_redirect_limit(self):
        (st, _, _, e), _, _ = run([err(302, Location="/x")] * 7)
        self.assertEqual(e, "too_many_redirects")

    def test_429_retry_after_capped(self):
        (st, *_), f, sl = run([err(429, Retry_After="100"), err(503, Retry_After="3"), Resp()])
        self.assertEqual(st, 200)
        self.assertEqual(sl, [20.0, 3.0])

    def test_429_gives_up_after_two_retries(self):
        (st, _, _, e), f, _ = run([err(429)] * 3)
        self.assertEqual((st, e, len(f.calls)), (429, "http_429", 3))

    def test_403_retries_with_browser_ua(self):
        (st, *_), f, _ = run([err(403), Resp()])
        self.assertEqual(st, 200)
        self.assertIn("XlakeBot", f.calls[0][1])
        self.assertNotIn("XlakeBot", f.calls[1][1])

    def test_403_no_retry_when_robots_disallows(self):
        f = Fake([err(403)])
        with mock.patch.object(webfetch, "_robots_ok", return_value=False), \
                mock.patch.object(webfetch.robots, "allowed", return_value=(True, "ok")), \
                mock.patch.object(webfetch, "_throttle_pair", return_value=(None, None)):
            st, _, _, e = webfetch.fetch_page("https://a.org/p", opener=f, sleep=lambda s: None, polite=True)
        self.assertEqual((st, len(f.calls)), (403, 1))

    def test_tls_tries_www_variant(self):
        bad = urllib.error.URLError(ssl.SSLCertVerificationError("Hostname mismatch"))
        (st, fin, *_), f, _ = run([bad, Resp()], url="https://a.org/p")
        self.assertEqual((st, fin), (200, "https://www.a.org/p"))
        (st, _, _, e), f, _ = run([bad, bad], url="https://a.org/p")
        self.assertTrue(e.startswith("tls"))
        self.assertEqual(len(f.calls), 2)

    def test_normalize(self):
        self.assertEqual(webfetch.normalize_url("https://a.org/café?q=ü"),
                         "https://a.org/caf%C3%A9?q=%C3%BC")
        self.assertEqual(webfetch.normalize_url("https://a.org/a%20b"), "https://a.org/a%20b")
        for bad in ("https://a.org/foo…", "https://a.org/x)(y", "ftp://a.org", ""):
            with self.assertRaises(webfetch.InvalidSeedURL):
                webfetch.normalize_url(bad)

    def test_invalid_seed_reported(self):
        (st, _, _, e), f, _ = run([], url="https://a.org/…")
        self.assertTrue(e.startswith("invalid_seed_url"))
        self.assertEqual(f.calls, [])

    def test_fetch_html_raises(self):
        f = Fake([err(404)])
        with self.assertRaises(RuntimeError):
            webfetch.fetch_html("https://a.org/p", opener=f, sleep=lambda s: None, polite=False)


class RobotsUnreachable(unittest.TestCase):
    def test_5xx_and_network_allow(self):
        from core import robots
        for exc in (urllib.error.HTTPError("u", 525, "m", hdrs(), io.BytesIO(b"")), OSError("boom")):
            with mock.patch.object(robots.urllib.request, "urlopen", side_effect=exc):
                self.assertFalse(robots._fetch_rules("https://x.org").blanket_deny)


if __name__ == "__main__":
    unittest.main()
