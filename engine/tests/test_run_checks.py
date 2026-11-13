import datetime as dt
import json
import os
import unittest

from pipeline import run_checks as rc


def mcp(payload):
    return {"result": {"content": [{"text": json.dumps(payload)}]}}


class RunChecksTest(unittest.TestCase):
    def setUp(self):
        rc.RESULTS.clear()
        self._get, self._post = rc._get, rc._post
        self._env = dict(os.environ)
        for k in ("GITHUB_STEP_SUMMARY", "GITHUB_TOKEN", "CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID"):
            os.environ.pop(k, None)

    def tearDown(self):
        rc._get, rc._post = self._get, self._post
        os.environ.clear()
        os.environ.update(self._env)

    def levels(self):
        return [l for l, _ in rc.RESULTS]

    def test_cron_slots(self):
        self.assertEqual(rc.cron_hours_today('- cron: "11 3 * * *"'), [(3, 11)])
        self.assertEqual(len(rc.cron_hours_today('- cron: "7 */6 * * *"')), 4)
        self.assertEqual(rc.cron_hours_today('- cron: "17 6 * * 0"'), [])

    def test_expect_open(self):
        rc._post = lambda u, d, h=None: mcp({"status": "open" if d["params"]["arguments"]["id"] == "a" else "upcoming"})
        rc.check_status(["a", "b"], "open", "2026-11-15")
        self.assertEqual(self.levels(), ["PASS", "FAIL"])

    def test_soon(self):
        rows = [{"id": "x", "title": "X", "deadline": "2026-12-01"}]
        rc._post = lambda u, d, h=None: mcp(rows)
        rc.check_soon(60, 1, "2026-11-14")
        self.assertEqual(self.levels(), ["PASS", "INFO"])
        rc.RESULTS.clear()
        rc._post = lambda u, d, h=None: mcp(rows + [{"id": "y", "title": "Y", "deadline": "2026-01-01"}])
        rc.check_soon(60, 1, "2026-11-14")
        self.assertIn("FAIL", self.levels())
        rc.RESULTS.clear()
        rc._post = lambda u, d, h=None: mcp([])
        rc.check_soon(60, 1, "2026-11-14")
        self.assertEqual(self.levels(), ["FAIL"])

    def test_scheduler_skipped_without_token(self):
        rc.check_scheduler()
        self.assertEqual(self.levels(), ["INFO"])

    def test_scheduler(self):
        os.environ.update(GITHUB_TOKEN="t", GITHUB_REPOSITORY="o/r")
        now = dt.datetime(2026, 11, 14, 12, 0, tzinfo=dt.timezone.utc)
        run = {"run_started_at": "2026-11-14T03:12:00Z", "status": "completed", "conclusion": "success"}
        rc._get = lambda u, h=None: {"workflow_runs": [run]}
        rc.check_scheduler(now)
        self.assertIn("PASS", self.levels())
        self.assertIn("FAIL", self.levels())  # hackathons/sweep need more runs than one
        rc.RESULTS.clear()
        rc._get = lambda u, h=None: {"workflow_runs": []}
        rc.check_scheduler(now)
        self.assertNotIn("PASS", self.levels())

    def test_d1_skipped(self):
        rc.check_d1(80000)
        self.assertEqual(self.levels(), ["INFO"])

    def test_d1_writes(self):
        os.environ.update(CLOUDFLARE_API_TOKEN="t", CLOUDFLARE_ACCOUNT_ID="a")
        rc._get = lambda u, h=None: {"result": [{"uuid": "u1", "name": "xlake-jobs"}]} if u.endswith("database") else {"result": {"file_size": 1}}

        def post(u, d, h=None):
            if u.endswith("/query"):
                return {"result": [{"results": [{"n": 5}]}]}
            return {"data": {"viewer": {"accounts": [{"d1AnalyticsAdaptiveGroups": [{"sum": {"rowsWritten": 90000}}]}]}}}
        rc._post = post
        rc.check_d1(80000)
        self.assertIn("FAIL", self.levels())


if __name__ == "__main__":
    unittest.main()
