import os
import sys
import unittest
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline.scorecard import score


class ScorecardTest(unittest.TestCase):
    def test_scores_categories_and_excludes_job(self):
        records = [
            {
                "record_type": "programme", "category": "alpha",
                "surfaced": True, "is_live": True,
                "needs_confirmation": False, "deadline": "2026-10-10",
                "programme_status": "open", "eligibility": "students",
                "official_evidence": {"url": "https://a.example"},
                "official_url": "https://a.example/one",
                "last_checked_at": "2026-09-20T00:00:00Z",
            },
            {
                "record_type": "programme", "category": "alpha",
                "surfaced": False, "is_live": False,
                "needs_confirmation": True,
                "registration_deadline": "2026-11-01",
                "programme_status": "rolling", "eligibility": "",
                "official_evidence": {}, "official_url": "https://a.example/one",
                "last_checked_at": "2026-08-01T00:00:00Z",
            },
            {
                "record_type": "programme", "category": "alpha",
                "surfaced": True, "is_live": True,
                "needs_confirmation": False, "deadline": None,
                "registration_deadline": None, "official_evidence": {"x": 1},
                "official_url": "https://b.example/two",
            },
            {
                "record_type": "programme", "category": "alpha",
                "surfaced": False, "is_live": True,
                "needs_confirmation": True, "programme_status": "closed",
                "eligibility": ["all"], "official_evidence": None,
                "official_url": "", "last_checked_at": "2026-09-04T00:00:00Z",
            },
            {
                "record_type": "hackathon", "category": "beta",
                "surfaced": False, "is_live": True,
                "needs_confirmation": False,
                "registration_deadline": "2026-10-01", "status": "open",
                "eligibility": "everyone", "official_evidence": {"source": "x"},
                "official_url": "https://c.example/one",
                "last_checked_at": "2026-10-04T00:00:00Z",
            },
            {
                "record_type": "programme", "category": "beta",
                "surfaced": True, "is_live": False,
                "needs_confirmation": True, "deadline": None,
                "registration_deadline": None, "status": "",
                "eligibility": {}, "official_evidence": {},
                "official_url": "https://d.example/two",
                "last_checked_at": "2026-06-01T00:00:00Z",
            },
            {
                "record_type": "programme", "category": "beta",
                "surfaced": False, "is_live": True,
                "needs_confirmation": False, "registration_deadline": "2026-12-01",
                "eligibility": "students", "official_evidence": {"source": "y"},
                "official_url": "https://c.example/one",
            },
            {
                "record_type": "programme", "category": "beta",
                "surfaced": True, "is_live": False,
                "needs_confirmation": False, "programme_status": "rolling",
                "eligibility": None, "official_evidence": None,
                "official_url": "https://c.example/three",
                "checked_at": "2026-09-14T00:00:00Z",
            },
            {
                "record_type": "job", "category": "alpha", "surfaced": True,
                "is_live": True, "official_url": "https://jobs.example/ignored",
            },
        ]
        now = datetime(2026, 10, 4, tzinfo=timezone.utc)

        result = score(records, now)

        self.assertEqual(set(result), {"alpha", "beta"})
        self.assertEqual(result["alpha"], {
            "total": 4,
            "surfaced": 2,
            "live": 3,
            "needs_confirmation": 2,
            "with_deadline": 2,
            "with_status": 3,
            "with_eligibility": 2,
            "with_evidence": 2,
            "distinct_official_hosts": 2,
            "duplicate_official_urls": 1,
            "stale_30d": 0.5,
            "median_age_days": 30.0,
        })
        self.assertEqual(result["beta"], {
            "total": 4,
            "surfaced": 2,
            "live": 2,
            "needs_confirmation": 1,
            "with_deadline": 2,
            "with_status": 2,
            "with_eligibility": 2,
            "with_evidence": 2,
            "distinct_official_hosts": 2,
            "duplicate_official_urls": 1,
            "stale_30d": 0.5,
            "median_age_days": 20.0,
        })


if __name__ == "__main__":
    unittest.main()
