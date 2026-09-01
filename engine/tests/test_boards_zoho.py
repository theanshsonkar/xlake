import html
import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from adapters import boards  # noqa: E402


class ZohoRecruitAdapterTest(unittest.TestCase):
    def test_embedded_jobs_are_parsed_and_visibility_filtered(self):
        openings = [
            {
                "id": "101",
                "Posting_Title": "Platform Engineer",
                "City": "Bengaluru",
                "State": "Karnataka",
                "Country": "India",
                "Job_Description": "<p>Build systems</p>",
                "Date_Opened": "2026-08-20",
            },
            {
                "id": "102",
                "Job_Opening_Name": "Remote Analyst",
                "Remote_Job": True,
            },
            {"id": "103", "Posting_Title": "Locked", "Is_Locked": True},
            {"id": "104", "Posting_Title": "Unpublished", "Publish": False},
            {
                "id": "105",
                "Posting_Title": "Not on site",
                "Keep_on_Career_Site": False,
            },
        ]
        page = '<input type="hidden" id="jobs" value="{}">'.format(
            html.escape(json.dumps({"jobs": openings}), quote=True)
        )

        with mock.patch.object(
            boards, "_request", return_value=(200, page, None)
        ) as request:
            result = boards._zoho("example")

        self.assertEqual(result.status, 200)
        self.assertIsNone(result.error)
        self.assertEqual(result.count, 2)
        self.assertEqual(
            [
                (posting.job_id, posting.title, posting.url, posting.location)
                for posting in result.postings
            ],
            [
                (
                    "101",
                    "Platform Engineer",
                    "https://example.zohorecruit.com/jobs/Careers/101",
                    "Bengaluru, Karnataka, India",
                ),
                (
                    "102",
                    "Remote Analyst",
                    "https://example.zohorecruit.com/jobs/Careers/102",
                    "Remote",
                ),
            ],
        )
        request.assert_called_once_with(
            "https://example.zohorecruit.com/jobs/Careers",
            want_json=False,
            user_agent=boards.ZOHO_BROWSER_UA,
        )


if __name__ == "__main__":
    unittest.main()
