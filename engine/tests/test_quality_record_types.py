import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.quality import annotate


class TestQualityRecordTypes(unittest.TestCase):
    def test_non_job_rows_bypass_job_hygiene_without_changing_jobs(self):
        jobs = [
            {
                "url": f"https://jobs.example/{index}",
                "token": "acme",
                "platform": "greenhouse",
                "title": "Software Engineer",
                "location_bucket": f"location-{index}",
                "first_seen": f"2026-08-{index:02d}",
            }
            for index in range(1, 12)
        ]
        jobs.append({
            "url": "https://jobs.example/duplicate",
            "token": "acme",
            "platform": "greenhouse",
            "title": "Software Engineer",
            "location_bucket": "location-1",
            "first_seen": "2026-08-12",
        })
        contributions = [
            {
                "record_type": "contribution",
                "url": f"https://github.com/acme/repo/issues/{index}",
                "repo": "acme/repo",
                "organizer": "Acme",
                "token": "acme",
                "platform": "greenhouse",
                "title": "Software Engineer",
                "location_bucket": "location-1",
                "posted_on": "2020-01-01",
                "first_seen": f"2026-08-{index:02d}",
            }
            for index in range(1, 16)
        ]
        programme = {
            "record_type": "programme",
            "programme_id": "acme-programme",
            "url": "https://acme.example/programme",
            "organizer": "Acme",
            "token": "acme",
            "platform": "greenhouse",
            "title": "Software Engineer",
            "location_bucket": "location-1",
            "posted_on": "2020-01-01",
            "first_seen": "2026-08-16",
        }

        rows = annotate(jobs + contributions + [programme], cap=10)

        for row in contributions + [programme]:
            self.assertTrue(row["surfaced"])
            self.assertIsNone(row.get("over_cap"))
            self.assertIsNone(row.get("dup_of"))
            self.assertNotIn("is_recruiter", row)
            self.assertNotIn("is_stale", row)
        self.assertTrue(any(row["over_cap"] for row in jobs))
        self.assertTrue(any(row["dup_of"] for row in jobs))
        self.assertEqual(len(rows), 28)

    def test_unknown_record_type_bypasses_job_hygiene(self):
        rows = [
            {
                "url": "https://jobs.example/job",
                "token": "acme-job",
                "platform": "greenhouse",
                "title": "Software Engineer",
                "location": "Bengaluru, India",
                "location_bucket": "location-job",
                "posted_on": "2026-08-20",
                "first_seen": "2026-08-20",
            },
            {
                "record_type": "programme",
                "url": "https://acme.example/programme",
                "token": "acme-programme",
                "platform": "programme",
                "title": "Software Engineering Programme",
                "location": "Remote",
                "location_bucket": "location-programme",
                "posted_on": "2026-08-20",
                "first_seen": "2026-08-20",
            },
            {
                "record_type": "contribution",
                "url": "https://github.com/acme/repo/issues/1",
                "token": "acme-contribution",
                "platform": "github",
                "title": "Good first issue",
                "location": "Remote",
                "location_bucket": "location-contribution",
                "posted_on": "2026-08-20",
                "first_seen": "2026-08-20",
            },
            {
                "record_type": "hackathon",
                "url": "https://acme.example/hackathon",
                "token": "acme-hackathon",
                "platform": "acme",
                "title": "Acme Hackathon",
                "location": "New York, United States",
                "location_bucket": "location-hackathon",
                "posted_on": "2026-08-20",
                "first_seen": "2026-08-20",
            },
            {
                "record_type": "fellowship",
                "url": "https://acme.example/fellowship",
                "token": "acme-fellowship",
                "platform": "acme",
                "title": "Acme Fellowship",
                "location": "Remote",
                "location_bucket": "location-fellowship",
                "posted_on": "2026-08-20",
                "first_seen": "2026-08-20",
            },
        ]

        annotate(rows, cap=10)

        for row in rows[1:]:
            self.assertIs(row["surfaced"], True)
            self.assertIsNone(row.get("over_cap"))
            self.assertIsNone(row.get("dup_of"))
            self.assertNotIn("is_recruiter", row)
            self.assertNotIn("is_stale", row)
        self.assertIn("is_recruiter", rows[0])
        self.assertIn("is_stale", rows[0])


if __name__ == "__main__":
    unittest.main()
