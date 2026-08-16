"""Tests that partial board reads cannot establish liveness absence."""

import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from adapters.boards import BoardResult  # noqa: E402
import sweep  # noqa: E402


class TestPartialReadLiveness(unittest.TestCase):
    def _run_with_result(self, result):
        known = {
            "platform": "greenhouse",
            "token": "acme",
            "job_id": "old",
            "title": "Software Engineer",
            "location": "Remote",
            "url": "https://example.com/jobs/old",
            "posted_on": "",
            "description": None,
            "stage": "early-career",
            "stage_resolved": "early-career",
            "technical": True,
            "discipline": "software",
            "location_bucket": "remote",
            "experience_min": None,
            "experience_max": None,
            "experience_conflict": False,
            "eligibility_status": "rules_unclear",
            "hidden_reason": None,
            "is_live": True,
        }
        entry = {"platform": "greenhouse", "token": "acme",
                 "company": "Acme"}
        with tempfile.TemporaryDirectory() as td:
            jobs_path = os.path.join(td, "jobs.json")
            hidden_path = os.path.join(td, "hidden.json")
            runs_path = os.path.join(td, "runs.jsonl")
            with open(jobs_path, "w") as fh:
                json.dump([known], fh)
            with mock.patch.object(sweep, "DATA", td), \
                    mock.patch.object(sweep, "OUT_JOBS", jobs_path), \
                    mock.patch.object(sweep, "OUT_HIDDEN", hidden_path), \
                    mock.patch.object(sweep, "OUT_RUNS", runs_path), \
                    mock.patch.object(sweep, "list_board", return_value=result), \
                    mock.patch.object(sweep.tiering, "load_tier_state", return_value={}), \
                    mock.patch.object(sweep.tiering, "save_tier_state"):
                sweep.sweep([entry], workers=1)
            with open(jobs_path) as fh:
                return json.load(fh)[0]["is_live"]

    def test_truncated_read_does_not_mark_absent_row_not_live(self):
        result = BoardResult("greenhouse", "acme", reported_total=1)
        self.assertTrue(result.truncated)
        self.assertTrue(self._run_with_result(result))

    def test_complete_read_marks_absent_row_not_live(self):
        result = BoardResult("greenhouse", "acme", reported_total=0)
        self.assertFalse(result.truncated)
        self.assertFalse(self._run_with_result(result))


if __name__ == "__main__":
    unittest.main()
