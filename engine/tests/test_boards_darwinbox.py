import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from adapters import boards  # noqa: E402


class DarwinboxAdapterTest(unittest.TestCase):
    def test_fixture_jobs_are_parsed_with_title_url_and_location(self):
        fixture = os.path.join(
            os.path.dirname(__file__), "fixtures", "darwinbox_jobs.json"
        )
        with open(fixture, encoding="utf-8") as fh:
            payload = json.load(fh)

        with mock.patch.object(
            boards, "_request", return_value=(200, payload, None)
        ) as request:
            result = boards._darwinbox("example")

        self.assertEqual(result.status, 200)
        self.assertIsNone(result.error)
        self.assertEqual(result.count, 2)
        self.assertEqual(
            [
                (posting.title, posting.url, posting.location)
                for posting in result.postings
            ],
            [
                (
                    "Platform Engineer",
                    "https://example.darwinbox.in/ms/candidatev2/main/careers/jobDetails/db-101",
                    "Bengaluru, India",
                ),
                (
                    "Product Analyst",
                    "https://example.darwinbox.in/ms/candidatev2/main/careers/jobDetails/db-102",
                    "Remote",
                ),
            ],
        )
        request.assert_called_once_with(
            "https://example.darwinbox.in/ms/candidateapi/job/alljobs?companyId=main",
            body=b'{"page":1,"limit":100}',
        )


if __name__ == "__main__":
    unittest.main()
