import unittest
import urllib.error
from unittest import mock

from pipeline import publish_supabase as ps


class PastDeadlineJobs(unittest.TestCase):
    def row(self, t, deadline):
        return {"type": t, "is_live": True, "deadline": deadline}

    def test_jobs_and_internships(self):
        with mock.patch.object(ps, "_today", return_value="2026-10-27"):
            for t in ("job", "internship"):
                self.assertFalse(ps.is_serving(self.row(t, "2025-12-31")))
                self.assertFalse(ps.is_serving(self.row(t, "2026-10-26")))
                self.assertTrue(ps.is_serving(self.row(t, "2026-10-27")))
                self.assertTrue(ps.is_serving(self.row(t, None)))


class Resp:
    status = 200
    headers = {}
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def read(self): return b"[]"


class Retry(unittest.TestCase):
    def client(self):
        c = ps.Supabase.__new__(ps.Supabase)
        c.base = "http://x"
        c._headers = lambda h=None: {}
        return c

    def run_req(self, method, effects):
        fake = mock.Mock(side_effect=effects)
        with mock.patch("urllib.request.urlopen", fake), \
                mock.patch.object(ps.time, "sleep") as sl:
            try:
                out = self.client()._request(method, "/t")
            except Exception as e:
                out = e
        return out, fake.call_count, sl

    def err(self, code):
        return urllib.error.HTTPError("http://x", code, "e", {}, None)

    def test_get_retries_5xx_then_ok(self):
        out, n, sl = self.run_req("GET", [self.err(503), urllib.error.URLError("x"), Resp()])
        self.assertEqual(n, 3)
        self.assertEqual([c.args[0] for c in sl.call_args_list], [1, 3])
        self.assertEqual(out[0], 200)

    def test_get_gives_up(self):
        out, n, _ = self.run_req("GET", [self.err(500)] * 3)
        self.assertEqual(n, 3)
        self.assertIsInstance(out, urllib.error.HTTPError)

    def test_get_no_retry_4xx(self):
        _, n, _ = self.run_req("GET", [self.err(404)] * 3)
        self.assertEqual(n, 1)

    def test_post_not_retried(self):
        _, n, _ = self.run_req("POST", [self.err(503)] * 3)
        self.assertEqual(n, 1)


if __name__ == "__main__":
    unittest.main()
