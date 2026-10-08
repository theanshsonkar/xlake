import io
import io
import unittest
import urllib.error
import urllib.parse
from contextlib import redirect_stdout
from unittest.mock import patch

from pipeline.publish_supabase import Supabase


class FakeSupabase(Supabase):
    def __init__(self, error_code=None):
        super().__init__("https://example.test", "key")
        self.error_code = error_code
        self.attempted_paths = []
        self.successful_paths = []

    def _request(self, method, path, body=None, headers=None):
        self.attempted_paths.append(path)
        if self.error_code == 400 and "BAD" in urllib.parse.unquote(path):
            error = urllib.error.HTTPError(
                path, 400, "Bad Request", {}, io.BytesIO(b"bad id"))
            error.body_text = "bad id"
            raise error
        if self.error_code and self.error_code != 400:
            raise urllib.error.HTTPError(
                path, self.error_code, "Server Error", {}, io.BytesIO(b"error"))
        self.successful_paths.append(path)
        return 204, {}, ""


class RetireTests(unittest.TestCase):
    def test_bad_id_isolated_and_skipped(self):
        ids = ["good-%d" % i for i in range(5)] + ["BAD"] + [
            "good-%d" % i for i in range(5, 9)]
        client = FakeSupabase(error_code=400)

        with redirect_stdout(io.StringIO()) as output:
            skipped = client.retire(ids)

        self.assertEqual(skipped, 1)
        successful_ids = {
            item
            for path in client.successful_paths
            for item in ids
            if item in urllib.parse.unquote(path)
        }
        self.assertEqual(successful_ids, set(ids) - {"BAD"})
        self.assertIn("RETIRE SKIP id='BAD' http=400 body=bad id", output.getvalue())

    def test_server_error_is_not_suppressed(self):
        client = FakeSupabase(error_code=500)
        with self.assertRaises(urllib.error.HTTPError) as raised:
            client.retire(["one"])
        self.assertEqual(raised.exception.code, 500)


class RequestTests(unittest.TestCase):
    @patch("pipeline.publish_supabase.urllib.request.urlopen")
    def test_request_attaches_truncated_error_body(self, urlopen):
        body = b"x" * 400
        urlopen.side_effect = urllib.error.HTTPError(
            "https://example.test", 400, "Bad Request", {}, io.BytesIO(body))
        client = Supabase("https://example.test", "key")

        with self.assertRaises(urllib.error.HTTPError) as raised:
            client._request("GET", "/opportunities")

        self.assertEqual(raised.exception.body_text, "x" * 300)


class QuotingTests(unittest.TestCase):
    def test_retire_doubles_backslashes_before_quoting(self):
        client = FakeSupabase()
        client.retire([r"path\with\slashes"])
        self.assertIn("path%5C%5Cwith%5C%5Cslashes", client.successful_paths[0])


if __name__ == "__main__":
    unittest.main()
