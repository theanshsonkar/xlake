import unittest
from datetime import date, datetime, timezone

from categories import programme_core
from categories.research import research
from core import lifecycle

NOW = datetime(2026, 10, 19, tzinfo=timezone.utc)
BODY = "<html><body><h1>Summer Research Program</h1><p>Applications open on December 1, 2026. Program applications.</p></body></html>"


class OpeningDateHoldTests(unittest.TestCase):
    def test_held_programme_opening_is_not_dated(self):
        seed = dict(research.SEEDS[0])
        record, _ = research.parse_programme(seed, BODY, NOW)
        self.assertTrue(record["opens_quote_dated"])
        seed["programme_id"] = "research-hub-www-mitacs-ca-en-programs-de62ed"
        self.assertIn(seed["programme_id"], programme_core.opening_date_holds())
        record, _ = research.parse_programme(seed, BODY, NOW)
        self.assertEqual(record["opening_date"], "2026-12-01")
        self.assertFalse(record["opens_quote_dated"])
        record["is_live"] = True
        self.assertEqual(lifecycle.infer(record, date(2026, 10, 19)), "open")

    def test_stored_row_without_flag_is_held(self):
        # a row stored before the hold existed: flag absent, quote passes on its own
        row = {"record_type": "programme", "is_live": True, "opening_date": "2027-08-03",
               "programme_id": "research-hub-www-mitacs-ca-en-programs-de62ed",
               "official_evidence": {"opening_date": {"quote": "Applications open on August 3, 2027."}}}
        self.assertEqual(lifecycle.infer(row, date(2026, 11, 13)), "open")
        from pipeline.rowshape import _dated_opens
        self.assertIsNone(_dated_opens(row))
        row["programme_id"] = "research-other"
        self.assertEqual(lifecycle.infer(row, date(2026, 11, 13)), "upcoming")


if __name__ == "__main__":
    unittest.main()
