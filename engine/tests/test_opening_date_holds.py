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


if __name__ == "__main__":
    unittest.main()
