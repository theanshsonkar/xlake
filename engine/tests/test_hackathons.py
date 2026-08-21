import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from categories.hackathons.hackathons import (
    collect,
    merge_hackathons,
    normalize_mlh,
    parse_devpost_dates,
)


FIXTURE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fixtures", "hackathons")
CHECKED_AT = datetime(2026, 8, 21, tzinfo=timezone.utc)


def _fixture_json(name):
    with open(os.path.join(FIXTURE_DIR, name)) as handle:
        return json.load(handle)


def _fixture_html():
    with open(os.path.join(FIXTURE_DIR, "mlh.html")) as handle:
        return handle.read()


def _fixture_next_year_html():
    with open(os.path.join(FIXTURE_DIR, "mlh-next.html")) as handle:
        return handle.read()


def _fake_fetchers():
    unstop_items = _fixture_json("unstop.json")
    return (
        lambda: _fixture_json("devpost.json"),
        lambda _checked_at=None: [
            (_fixture_html(), "https://mlh.io/seasons/2026/events"),
            (_fixture_next_year_html(), "https://mlh.io/seasons/2027/events"),
        ],
        lambda: {"data": {"current_page": 1, "last_page": 1, "data": unstop_items}},
    )


class TestHackathonsCollector(unittest.TestCase):
    def test_merge_safety_preserves_all_non_hackathon_records(self):
        seeded = [
            {"title": "A job", "official_url": "https://jobs.example/1"},
            {"record_type": "programme", "programme_id": "programme-1"},
            {"record_type": "contribution", "contribution_id": "contribution-1"},
            {"record_type": "programme", "category": "research", "programme_id": "research-1"},
        ]
        devpost, mlh, unstop = _fake_fetchers()
        with tempfile.TemporaryDirectory() as td:
            lake_path = os.path.join(td, "lake.json")
            with open(lake_path, "w") as handle:
                json.dump(seeded, handle)
            result = collect(devpost, mlh, unstop, checked_at=CHECKED_AT, lake_path=lake_path)
            with open(lake_path) as handle:
                lake = json.load(handle)
        self.assertEqual(result["total_surfaced"], 8)
        for record in seeded:
            self.assertIn(record, lake)
        self.assertGreater(len([row for row in lake if row.get("record_type") == "hackathon"]), 0)

    def test_parse_devpost_dates_exact_cases(self):
        cases = {
            "Jul 31 - Oct 01, 2026": ("2026-07-31", "2026-10-01"),
            "Aug 04 - 31, 2026": ("2026-08-04", "2026-08-31"),
            "Aug 04, 2026": ("2026-08-04", "2026-08-04"),
            "Dec 15, 2025 - Jan 20, 2026": ("2025-12-15", "2026-01-20"),
            "Dec 15 - Jan 20, 2026": ("2025-12-15", "2026-01-20"),
            "": (None, None),
            "to be announced": (None, None),
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(parse_devpost_dates(text), expected)

    def test_freshness_sort_and_unparseable_devpost_date(self):
        devpost, mlh, unstop = _fake_fetchers()
        with tempfile.TemporaryDirectory() as td:
            lake_path = os.path.join(td, "lake.json")
            result = collect(devpost, mlh, unstop, checked_at=CHECKED_AT, lake_path=lake_path)
            with open(lake_path) as handle:
                rows = json.load(handle)
        hackathons = [row for row in rows if row.get("record_type") == "hackathon"]
        self.assertEqual(result["devpost"], 3)
        self.assertEqual(result["mlh"], 3)
        self.assertEqual(result["unstop"], 2)
        urls = {row["official_url"] for row in hackathons}
        self.assertNotIn("https://example.devpost.com/past-build", urls)
        self.assertNotIn("https://events.mlh.io/past", urls)
        self.assertIn("https://events.mlh.io/next-season", urls)
        self.assertNotIn("https://unstop.com/hackathon/past-hack", urls)
        sort_keys = [row.get("start_date") or row.get("registration_deadline") or row.get("end_date") or "9999" for row in hackathons]
        self.assertEqual(sort_keys, sorted(sort_keys))
        tba = next(row for row in hackathons if row["title"].startswith("Date To Be Announced"))
        self.assertIsNone(tba["start_date"])
        self.assertIsNone(tba["end_date"])
        self.assertEqual(tba["official_evidence"]["submission_period_dates"], "to be announced")

    def test_row_schema_has_hackathon_identity_and_official_url(self):
        devpost, mlh, unstop = _fake_fetchers()
        with tempfile.TemporaryDirectory() as td:
            lake_path = os.path.join(td, "lake.json")
            collect(devpost, mlh, unstop, checked_at=CHECKED_AT, lake_path=lake_path)
            with open(lake_path) as handle:
                rows = json.load(handle)
        hackathons = [row for row in rows if row.get("record_type") == "hackathon"]
        self.assertTrue(hackathons)
        for row in hackathons:
            self.assertEqual(row["record_type"], "hackathon")
            self.assertEqual(row["category"], "hackathons")
            self.assertEqual(row["opportunity_type"], "hackathon")
            self.assertEqual(row["hackathon_id"], row["official_url"])
            self.assertTrue(row["official_url"].startswith("http"))

    def test_mlh_strips_utm_parameters(self):
        html = _fixture_html()
        rows = normalize_mlh(html, CHECKED_AT, "https://mlh.io/seasons/2026/events")
        self.assertTrue(rows)
        for row in rows:
            self.assertNotIn("utm_", row["official_url"])
        self.assertTrue(any("ref=calendar" in row["official_url"] for row in rows))

    def test_mlh_normalizes_location_and_reads_digital_format(self):
        html = """
        <a itemscope itemtype="http://schema.org/Event" href="https://events.mlh.io/digital" data-format="digital">
          <h4 itemprop="name">MLH Digital Hack Day</h4>
          <meta itemprop="startDate" content="2026-09-01T09:00:00Z">
          <meta itemprop="endDate" content="2026-09-02T23:59:00Z">
          <span itemprop="location"></span>
        </a>
        <a itemscope itemtype="http://schema.org/Event" href="https://events.mlh.io/hyderabad">
          <h4 itemprop="name">MLH Hyderabad Hack Day</h4>
          <meta itemprop="startDate" content="2026-09-03T09:00:00Z">
          <meta itemprop="endDate" content="2026-09-04T23:59:00Z">
          <span itemprop="location"> Hyderabad ,   Telangana, IN </span>
        </a>
        """
        rows = normalize_mlh(html, CHECKED_AT)
        digital = next(row for row in rows if row["official_url"].endswith("/digital"))
        hyderabad = next(row for row in rows if row["official_url"].endswith("/hyderabad"))
        self.assertTrue(digital["is_online"])
        self.assertIsNone(digital["location"])
        self.assertEqual(hyderabad["location"], "Hyderabad, Telangana, IN")

    def test_closure_distinguishes_successful_source_and_failed_source(self):
        successful_old = {
            "record_type": "hackathon", "hackathon_id": "https://devpost.com/old",
            "official_url": "https://devpost.com/old", "source": "devpost", "is_live": True,
            "last_seen": "2026-08-20T00:00:00+00:00",
        }
        with tempfile.TemporaryDirectory() as td:
            successful_path = os.path.join(td, "successful.json")
            with open(successful_path, "w") as handle:
                json.dump([successful_old], handle)
            merged = merge_hackathons({}, {"devpost"}, successful_path, now="2026-08-21T00:00:00+00:00")
        self.assertFalse(merged[0]["is_live"])
        self.assertEqual(merged[0]["liveness_reason"], "ended_or_removed")

        failed_old = dict(successful_old, source="unstop", hackathon_id="https://unstop.com/old", official_url="https://unstop.com/old", last_seen="2026-08-18T00:00:00+00:00")
        with tempfile.TemporaryDirectory() as td:
            failed_path = os.path.join(td, "failed.json")
            with open(failed_path, "w") as handle:
                json.dump([failed_old], handle)
            within = merge_hackathons({}, set(), failed_path, now="2026-08-21T00:00:00+00:00")[0]
            self.assertTrue(within["is_live"])
            self.assertNotIn("liveness_reason", within)
            with open(failed_path, "w") as handle:
                json.dump([failed_old], handle)
            decayed = merge_hackathons({}, set(), failed_path, now="2026-08-27T00:00:00+00:00")[0]
        self.assertFalse(decayed["is_live"])
        self.assertTrue(decayed["needs_confirmation"])
        self.assertEqual(decayed["liveness_reason"], "not_reconfirmed")


if __name__ == "__main__":
    unittest.main()
