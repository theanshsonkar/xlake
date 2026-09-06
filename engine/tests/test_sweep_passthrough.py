import copy
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline import sweep  # noqa: E402


class TestSweepPassthrough(unittest.TestCase):
    @staticmethod
    def _job(url, title, location="Bengaluru, India"):
        return {
            "platform": "greenhouse",
            "token": "acme",
            "job_id": url.rsplit("/", 1)[-1],
            "title": title,
            "location": location,
            "url": url,
            "posted_on": "2026-08-18",
            "description": None,
            "company_name": "Acme",
            "segment": "india",
            "stage": "early-career",
            "stage_title": "early-career",
            "stage_resolved": "early-career",
            "technical": True,
            "discipline": "software",
            "needs_description": False,
            "experience_min": None,
            "experience_max": None,
            "experience_conflict": False,
            "batch_years": [],
            "degree_required": [],
            "enrolled_required": None,
            "eligibility_evidence": {},
            "gates_found": [],
            "gates_missing": [],
            "eligibility_status": "eligible",
            "hidden_reason": None,
            "location_bucket": "india_located",
            "is_internship": False,
            "source_mechanism": "board",
        }

    def test_programmes_and_contributions_pass_through_unchanged(self):
        existing_job = self._job("https://jobs.example/acme/old", "Old title")
        existing_job["company_domain"] = "old.acme.example"
        second_job = self._job("https://jobs.example/acme/keep", "Keep title")
        programme = {
            "record_type": "programme",
            "programme_id": "acme-fellowship-2026",
            "official_url": "https://acme.example/fellowship",
            "official_evidence": {"title": "Acme Fellowship", "read": True},
            "is_live": True,
            "title": "Acme Fellowship",
            "organizer": "Acme",
            "record_note": "preserve exactly",
        }
        contributions = [
            {
                "record_type": "contribution",
                "contribution_id": "acme-repo-1",
                "url": "https://github.com/acme/repo/issues/1",
                "language": "Python",
                "difficulty": "good first issue",
                "is_recently_active": True,
                "official_url": "https://github.com/acme/repo/issues/1",
                "title": "Improve docs",
            },
            {
                "record_type": "contribution",
                "contribution_id": "acme-repo-2",
                "url": "https://github.com/acme/repo/issues/2",
                "language": "Rust",
                "difficulty": "beginner",
                "is_recently_active": False,
                "official_url": "https://github.com/acme/repo/issues/2",
                "title": "Fix typo",
            },
        ]
        before_non_jobs = copy.deepcopy([programme] + contributions)
        new_existing_job = self._job(
            "https://jobs.example/acme/old", "Updated title", "Hyderabad, India")
        new_existing_job["company_domain"] = "new.acme.example"
        new_job = self._job("https://jobs.example/acme/new", "New title")

        with tempfile.TemporaryDirectory() as td:
            lake_path = os.path.join(td, "opportunities.json")
            with open(lake_path, "w") as fh:
                json.dump([existing_job, second_job, programme] + contributions, fh)

            sweep._merge_store(
                lake_path,
                [new_existing_job, new_job],
                {("greenhouse", "acme")},
            )

            with open(lake_path) as fh:
                merged = json.load(fh)

        merged_non_jobs = [r for r in merged if r.get("record_type")]
        self.assertEqual(merged_non_jobs, before_non_jobs)
        self.assertEqual(len(merged_non_jobs), 3)
        self.assertNotIn("surfaced", merged_non_jobs[0])
        self.assertNotIn("last_seen", merged_non_jobs[0])

        jobs = [r for r in merged if not r.get("record_type")]
        by_url = {r["url"]: r for r in jobs}
        self.assertEqual(set(by_url), {
            "https://jobs.example/acme/old",
            "https://jobs.example/acme/keep",
            "https://jobs.example/acme/new",
        })
        self.assertEqual(by_url["https://jobs.example/acme/old"]["title"],
                         "Updated title")
        self.assertEqual(by_url["https://jobs.example/acme/old"]["location"],
                         "Hyderabad, India")
        self.assertEqual(by_url["https://jobs.example/acme/old"]["company_domain"],
                         "new.acme.example")
        self.assertEqual(by_url["https://jobs.example/acme/old"]["is_live"], True)
        self.assertTrue(by_url["https://jobs.example/acme/old"].get("last_seen"))
        self.assertTrue(by_url["https://jobs.example/acme/new"].get("first_seen"))
        self.assertTrue(by_url["https://jobs.example/acme/new"].get("last_seen"))


if __name__ == "__main__":
    unittest.main()
