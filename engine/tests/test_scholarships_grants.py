import json
import os
import unittest
from datetime import datetime, timezone

from categories import programme_enrich as enrich
from categories.grants import grants
from categories.scholarships import scholarships

NOW = datetime(2026, 10, 19, tzinfo=timezone.utc)
SEED = {"source_id": "scholarship-test", "programme_id": "scholarship-test", "programme_name": "Test Merit Scholarship",
        "organizer": "Test Foundation", "official_url": "https://tf.example.org/scholarship", "allowed_path_hints": [""],
        "check_cadence": "monthly", "region_hint": "India"}


def page(body):
    return "<html><body><h1>Test Merit Scholarship</h1>{}</body></html>".format(body)


class ScholarshipParsingTests(unittest.TestCase):
    def test_inr_per_annum_and_flags(self):
        html = page("<p>Eligibility: Indian nationals studying undergraduate degrees are eligible to apply. "
                    "The scholarship program award is ₹50,000 per annum. Application deadline: December 15, 2026. Apply now.</p>")
        record, obs = scholarships.parse_programme(SEED, html, NOW)
        self.assertIsNotNone(record)
        self.assertEqual(record["deadline"], "2026-12-15")
        self.assertIn("50,000", record["funding"])
        self.assertEqual(record.get("funding_currency"), "INR")
        self.assertIn("undergraduate", record["levels"])
        self.assertEqual(record["intl_eligible"], False)

    def test_full_tuition_and_international(self):
        html = page("<p>International students from any country are eligible. The scholarship program covers full tuition. "
                    "Application deadline: January 10, 2027.</p>")
        record, _ = scholarships.parse_programme(SEED, html, NOW)
        self.assertEqual(record["funding"], "Tuition covered")
        self.assertTrue(record["intl_eligible"])

    def test_past_deadline_recurring_is_upcoming_not_open(self):
        html = page("<p>Applications are held annually. Application deadline: November 1, 2025. Scholarship program applications.</p>")
        record, _ = scholarships.parse_programme(SEED, html, NOW)
        self.assertEqual(record["programme_status"], "upcoming")
        self.assertIsNone(record["deadline"])
        self.assertTrue(record["next_cycle_hint"])

    def test_curated_cycle_hint_on_undated_page(self):
        seed = dict(SEED, cycle_hint="Typically opens in August; deadline around October 31")
        html = page("<p>The Test Merit Scholarship supports students. Learn about the scholarship program.</p>")
        record, obs = scholarships.parse_programme(seed, html, NOW)
        self.assertEqual(record["programme_status"], "upcoming")
        self.assertIn("October 31", record["next_cycle_hint"])
        self.assertNotIn("needs_confirmation", record)
        self.assertTrue(record["is_live"])
        self.assertEqual(record["region"], "India")

    def test_undated_without_hint_stays_unconfirmed(self):
        html = page("<p>The Test Merit Scholarship supports students. Learn about the scholarship program.</p>")
        record, _ = scholarships.parse_programme(SEED, html, NOW)
        self.assertTrue(record["needs_confirmation"])
        self.assertFalse(record["is_live"])

    def test_postprocess_keeps_parser_facts_and_upcoming_live(self):
        pid = scholarships.SEEDS[0]["programme_id"]
        rows = [{"record_type": "programme", "programme_id": pid, "programme_status": "upcoming",
                 "deadline": None, "eligibility": "Students", "funding": "$1,000 award", "is_live": False}]
        out = scholarships._postprocess(rows, [])
        self.assertTrue(out[0]["is_live"])
        self.assertEqual(out[0]["funding"], "$1,000 award")
        self.assertEqual(out[0]["eligibility"], "Students")
        pid = grants.SEEDS[0]["programme_id"]
        rows[0]["programme_id"] = pid
        self.assertTrue(grants._postprocess(rows, [])[0]["is_live"])


class SeedFileTests(unittest.TestCase):
    def _check(self, registry, floor):
        ids, urls = set(), set()
        for seed in registry:
            self.assertTrue(seed["official_url"].startswith("https://") or seed["official_url"].startswith("http://"))
            self.assertNotIn(seed["programme_id"], ids)
            self.assertNotIn(seed["official_url"], urls)
            ids.add(seed["programme_id"])
            urls.add(seed["official_url"])
            self.assertEqual(seed.get("source_kind", "official"), "official")
        self.assertGreaterEqual(len(registry), floor)

    def test_scholarship_seeds(self):
        self._check(scholarships.STATIC_SOURCE_REGISTRY, 140)

    def test_grant_seeds(self):
        self._check(grants.STATIC_SOURCE_REGISTRY, 90)

    def test_region_hints_are_known(self):
        for registry in (scholarships.STATIC_SOURCE_REGISTRY, grants.STATIC_SOURCE_REGISTRY):
            for seed in registry:
                if "region_hint" in seed:
                    self.assertIn(seed["region_hint"], {"US", "India", "Global", "UK", "Europe", "Canada", "Australia",
                                                        "Asia", "Africa", "Latin America", "New Zealand"})


if __name__ == "__main__":
    unittest.main()
