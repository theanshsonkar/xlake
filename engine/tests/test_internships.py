import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import filters
from categories.internships.internships import list_internships


class TestInternshipsListing(unittest.TestCase):
    def test_accessibility_aware_listing(self):
        rows = [
            {
                "title": "India onsite internship",
                "location_bucket": filters.INDIA_LOCATED,
                "hidden_reason": None,
                "is_internship": True,
            },
            {
                "title": "India remote internship",
                "location_bucket": filters.INDIA_REMOTE,
                "hidden_reason": None,
                "is_internship": True,
            },
            {
                "title": "Global remote internship",
                "location_bucket": filters.REMOTE_GLOBAL,
                "hidden_reason": None,
                "is_internship": True,
            },
            {
                "title": "Foreign onsite internship",
                "location_bucket": filters.GLOBAL_HIRING,
                "hidden_reason": None,
                "is_internship": True,
            },
            {
                "title": "Senior India internship",
                "location_bucket": filters.INDIA_LOCATED,
                "hidden_reason": filters.HIDDEN_SENIOR,
                "is_internship": True,
            },
            {
                "record_type": "programme",
                "title": "Programme row",
                "location_bucket": filters.INDIA_LOCATED,
            },
            {
                "record_type": "contribution",
                "title": "Contribution row",
                "location_bucket": filters.INDIA_LOCATED,
            },
        ]

        with tempfile.TemporaryDirectory() as td:
            lake_path = os.path.join(td, "opportunities.json")
            with open(lake_path, "w") as handle:
                json.dump(rows, handle)
            with patch(
                "categories.internships.internships.OPPORTUNITIES_PATH",
                lake_path,
            ):
                default_rows = list_internships()
                surfaced_rows = list_internships(surfaced=True)
                india_rows = list_internships(india=True, surfaced=True)
                foreign_rows = list_internships(foreign=True)

        default_titles = [row["title"] for row in default_rows]
        surfaced_titles = {row["title"] for row in surfaced_rows}
        india_titles = {row["title"] for row in india_rows}
        foreign_titles = {row["title"] for row in foreign_rows}
        excluded_titles = {"Programme row", "Contribution row"}

        self.assertEqual(
            set(default_titles),
            {
                "India onsite internship",
                "India remote internship",
                "Global remote internship",
                "Foreign onsite internship",
                "Senior India internship",
            },
        )
        foreign_index = default_titles.index("Foreign onsite internship")
        for title in (
            "India onsite internship",
            "India remote internship",
            "Global remote internship",
        ):
            self.assertGreater(foreign_index, default_titles.index(title))

        self.assertNotIn("Senior India internship", surfaced_titles)
        self.assertIn("Global remote internship", surfaced_titles)
        self.assertIn("Foreign onsite internship", surfaced_titles)
        self.assertEqual(
            india_titles,
            {"India onsite internship", "India remote internship"},
        )
        self.assertEqual(foreign_titles, {"Foreign onsite internship"})
        self.assertTrue(excluded_titles.isdisjoint(set(default_titles)))
        self.assertTrue(excluded_titles.isdisjoint(surfaced_titles))
        self.assertTrue(excluded_titles.isdisjoint(india_titles))
        self.assertTrue(excluded_titles.isdisjoint(foreign_titles))


if __name__ == "__main__":
    unittest.main()
