import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from categories.internships.internships import list_internships


class TestInternshipsListing(unittest.TestCase):
    def test_list_internships_filters_canonical_lake(self):
        rows = [
            {
                "title": "India Unstop internship",
                "company": "Acme",
                "platform": "Unstop",
                "location": "Bengaluru",
                "location_bucket": "india_located",
                "is_internship": True,
                "hidden_reason": None,
                "official_url": "https://unstop.example/1",
            },
            {
                "title": "Hidden India internship",
                "company": "Acme",
                "platform": "unstop",
                "location_bucket": "india_remote",
                "is_internship": True,
                "hidden_reason": "eligibility_unclear",
                "official_url": "https://unstop.example/2",
            },
            {
                "title": "Global ATS internship",
                "company": "Globex",
                "platform": "Greenhouse",
                "location_bucket": "remote",
                "is_internship": True,
                "hidden_reason": None,
                "official_url": "https://jobs.example/3",
            },
            {
                "title": "Global Unstop internship",
                "company": "Globex",
                "platform": "UNSTOP",
                "location_bucket": "global",
                "is_internship": True,
                "hidden_reason": None,
                "official_url": "https://unstop.example/4",
            },
            {
                "title": "Not an internship",
                "company": "Acme",
                "platform": "unstop",
                "location_bucket": "india_located",
                "is_internship": False,
                "hidden_reason": None,
            },
            {
                "record_type": "job",
                "title": "Typed job internship is excluded",
                "company": "Acme",
                "platform": "unstop",
                "location_bucket": "india_located",
                "is_internship": True,
                "hidden_reason": None,
            },
            {
                "record_type": "programme",
                "title": "Programme is excluded",
                "is_internship": True,
            },
            {
                "record_type": "contribution",
                "title": "Contribution is excluded",
                "is_internship": True,
            },
        ]

        with tempfile.TemporaryDirectory() as td:
            lake_path = os.path.join(td, "lake.json")
            with open(lake_path, "w") as handle:
                json.dump(rows, handle)
            with patch(
                "categories.internships.internships.OPPORTUNITIES_PATH",
                lake_path,
            ):
                all_internships = list_internships()
                india = list_internships(india=True)
                surfaced = list_internships(surfaced=True)
                unstop = list_internships(platform="uNsToP")
                acme = list_internships(company="aCmE")

        self.assertEqual(
            {row["title"] for row in all_internships},
            {
                "India Unstop internship",
                "Hidden India internship",
                "Global ATS internship",
                "Global Unstop internship",
            },
        )
        self.assertEqual(
            {row["title"] for row in india},
            {"India Unstop internship", "Hidden India internship"},
        )
        self.assertEqual(
            {row["title"] for row in surfaced},
            {
                "India Unstop internship",
                "Global ATS internship",
                "Global Unstop internship",
            },
        )
        self.assertEqual(
            {row["title"] for row in unstop},
            {
                "India Unstop internship",
                "Hidden India internship",
                "Global Unstop internship",
            },
        )
        self.assertEqual(
            {row["title"] for row in acme},
            {"India Unstop internship", "Hidden India internship"},
        )
        self.assertFalse(any(row.get("record_type") for row in all_internships))
        self.assertFalse(any("Programme" in row["title"] for row in all_internships))
        self.assertFalse(any("Contribution" in row["title"] for row in all_internships))


if __name__ == "__main__":
    unittest.main()
