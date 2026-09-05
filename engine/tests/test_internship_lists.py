import copy
import json
import os
import sys
import tempfile
import unittest
from urllib.parse import urlsplit

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from categories.internships import lists  # noqa: E402
from core import filters  # noqa: E402
from pipeline import sweep  # noqa: E402


CHECKED_AT = "2026-08-22T00:00:00+00:00"


class TestInternshipLists(unittest.TestCase):
    @staticmethod
    def _entry(listing_id, url, title="Software Engineering Intern", **extra):
        entry = {
            "id": listing_id,
            "title": title,
            "company": "Example Labs",
            "location": "New York, NY, USA",
            "posted_at": "2026-08-20T12:00:00Z",
            "source": "greenhouse",
            "season": "Fall 2026",
            "category": "software",
            "program": "Internship",
            "skills": ["Python"],
            "url": url,
        }
        entry.update(extra)
        return entry

    @staticmethod
    def _read(path):
        with open(path) as handle:
            return json.load(handle)

    def test_deduplicates_against_lake_and_within_list(self):
        board = {
            "platform": "greenhouse",
            "token": "x",
            "job_id": "1",
            "title": "Board job",
            "url": "https://boards.greenhouse.io/x/jobs/1",
        }
        unstop = {
            "platform": "unstop",
            "token": "internships",
            "title": "Unstop internship",
            "url": "https://unstop.com/i/2",
            "is_internship": True,
        }
        entries = [
            self._entry("dup-board", board["url"]),
            self._entry("dup-unstop", unstop["url"]),
            self._entry("unique-1", "https://jobs.example.com/acme/1"),
            self._entry("unique-2", "https://boards.greenhouse.io/acme/jobs/2"),
            self._entry("unique-2-copy", "https://boards.greenhouse.io/acme/jobs/2/"),
        ]

        with tempfile.TemporaryDirectory() as td:
            lake_path = os.path.join(td, "opportunities.json")
            with open(lake_path, "w") as handle:
                json.dump([board, unstop], handle)
            result = lists.collect(
                fetch=lambda: {"jobs": entries},
                checked_at=CHECKED_AT,
                lake_path=lake_path,
            )
            merged = self._read(lake_path)

        self.assertEqual(result["added_or_updated"], 2)
        self.assertEqual(result["skipped_dup_lake"], 2)
        self.assertEqual(result["skipped_dup_within"], 1)
        self.assertEqual(len([
            row for row in merged
            if row.get("source_mechanism") == "community-list"
        ]), 2)
        self.assertIn(board, merged)
        self.assertIn(unstop, merged)

    def test_source_authority_marks_coop_as_internship_and_preserves_accessibility(self):
        coop = lists.build_row(
            self._entry(
                "coop-1",
                "https://careers.example.com/jobs/coop-1",
                title="Graduate Level Co-op - Data Scientist",
            ),
            CHECKED_AT,
        )
        remote = lists.build_row(
            self._entry(
                "remote-1",
                "https://careers.example.com/jobs/remote-1",
                location="",
                remote=True,
            ),
            CHECKED_AT,
        )

        self.assertTrue(coop["is_internship"])
        self.assertTrue(coop["technical"])
        self.assertEqual(coop["location_bucket"], filters.US_LOCATED)
        self.assertEqual(
            filters.accessibility(coop["location_bucket"]),
            filters.ACCESS_US,
        )
        self.assertEqual(remote["location_bucket"], filters.REMOTE_GLOBAL)

    def test_rejects_non_official_links(self):
        entries = [
            self._entry("github", "https://github.com/acme/jobs/1"),
            self._entry("dreamwork", "https://www.dreamworkhq.com/jobs/2"),
            self._entry("ats", "https://jobs.example.com/acme/3"),
        ]

        self.assertIsNone(lists.build_row(entries[0], CHECKED_AT))
        self.assertIsNone(lists.build_row(entries[1], CHECKED_AT))
        self.assertIsNotNone(lists.build_row(entries[2], CHECKED_AT))

        with tempfile.TemporaryDirectory() as td:
            lake_path = os.path.join(td, "opportunities.json")
            result = lists.collect(
                fetch=lambda: {"jobs": entries},
                checked_at=CHECKED_AT,
                lake_path=lake_path,
            )
            merged = self._read(lake_path)

        added = [
            row for row in merged
            if row.get("source_mechanism") == "community-list"
        ]
        self.assertEqual(result["built"], 1)
        self.assertEqual(len(added), 1)
        for row in added:
            host = (urlsplit(row["url"]).hostname or "").casefold()
            self.assertTrue(row["url"].startswith("http"))
            self.assertNotIn(host, {"github.com", "github.io", "dreamworkhq.com"})

    def test_survives_sweep_merge_with_no_boards_read(self):
        programme = {
            "record_type": "programme",
            "programme_id": "fellowship-1",
            "title": "Fellowship",
            "official_url": "https://programme.example/fellowship",
            "is_live": True,
        }
        contribution = {
            "record_type": "contribution",
            "contribution_id": "repo-1",
            "title": "Good first issue",
            "official_url": "https://github.com/example/repo/issues/1",
        }
        hackathon = {
            "record_type": "hackathon",
            "hackathon_id": "hack-1",
            "title": "Hackathon",
            "official_url": "https://hack.example/hack-1",
        }
        research = {
            "record_type": "programme",
            "category": "research",
            "programme_id": "research-1",
            "title": "Research programme",
            "official_url": "https://research.example/programme",
        }
        board = {
            "platform": "greenhouse",
            "token": "acme",
            "job_id": "board-1",
            "title": "Existing board role",
            "location": "Bengaluru, India",
            "url": "https://boards.greenhouse.io/acme/jobs/board-1",
            "record_type": None,
        }
        unstop = {
            "platform": "unstop",
            "token": "internships",
            "title": "Unstop role",
            "location": "Remote",
            "url": "https://unstop.com/i/2",
            "record_type": None,
            "is_internship": True,
        }
        seed = [programme, contribution, hackathon, research, board, unstop]
        entries = [
            self._entry("list-1", "https://jobs.example.com/acme/list-1"),
            self._entry(
                "list-2",
                "https://jobs.example.com/acme/list-2",
                location="Remote",
                remote=True,
            ),
        ]

        with tempfile.TemporaryDirectory() as td:
            lake_path = os.path.join(td, "opportunities.json")
            with open(lake_path, "w") as handle:
                json.dump(seed, handle)
            lists.collect(
                fetch=lambda: {"jobs": entries},
                checked_at=CHECKED_AT,
                lake_path=lake_path,
            )
            sweep._merge_store(lake_path, [], set())
            merged = self._read(lake_path)

        list_rows = [
            row for row in merged
            if row.get("platform") == lists.PLATFORM
        ]
        self.assertEqual(len(list_rows), 2)
        for row in list_rows:
            self.assertTrue(row["is_live"])
            self.assertTrue(row["is_internship"])
            self.assertIn(row["location_bucket"], {
                filters.US_LOCATED,
                filters.GLOBAL_HIRING,
                filters.REMOTE_GLOBAL,
            })
            self.assertIn("company", row)
            self.assertIn("surfaced", row)

        by_type = {row.get("record_type"): [] for row in merged if row.get("record_type")}
        for row in merged:
            if row.get("record_type"):
                by_type[row["record_type"]].append(row)
        self.assertEqual(by_type["programme"], [programme, research])
        self.assertEqual(by_type["contribution"], [contribution])
        self.assertEqual(by_type["hackathon"], [hackathon])
        self.assertEqual(
            [row for row in merged if row.get("url") == unstop["url"]][0].get("record_type"),
            None,
        )


if __name__ == "__main__":
    unittest.main()
