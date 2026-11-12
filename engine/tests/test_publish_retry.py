import io
import os
import sys
import unittest
import urllib.error
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline import publish_supabase as ps  # noqa: E402


def http_error(code):
    return urllib.error.HTTPError("u", code, "x", {}, io.BytesIO(b"err"))


class UpsertRetryTest(unittest.TestCase):
    def setUp(self):
        self.client = ps.Supabase.__new__(ps.Supabase)
        self.client.base, self.client.key = "https://x.test/rest/v1", "k"

    def test_upsert_retries_then_succeeds(self):
        calls = []

        class Resp:
            status, headers = 201, {}
            def read(self): return b""
            def __enter__(self): return self
            def __exit__(self, *a): return False

        def fake(req):
            calls.append(1)
            if len(calls) == 1:
                raise http_error(500)
            return Resp()

        with mock.patch("urllib.request.urlopen", fake), mock.patch("time.sleep"):
            self.client.upsert([{"id": "a"}])
        self.assertEqual(len(calls), 2)

    def test_persistent_500_splits_batch(self):
        ok = []

        def fake_request(method, path, body=None, headers=None):
            if len(body) > 60:
                raise http_error(500)
            ok.append(len(body))

        self.client._request = fake_request
        self.client.upsert([{"id": str(i)} for i in range(200)])
        self.assertEqual(sum(ok), 200)
        self.assertTrue(all(s <= 60 for s in ok))

    def test_client_error_not_split(self):
        def fake_request(method, path, body=None, headers=None):
            raise http_error(400)

        self.client._request = fake_request
        with self.assertRaises(urllib.error.HTTPError):
            self.client.upsert([{"id": str(i)} for i in range(200)])


if __name__ == "__main__":
    unittest.main()
