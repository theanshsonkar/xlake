import ast
import os
import sys
import unittest
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import opportunity_text as ot

TODAY = date(2026, 11, 14)


class TestOpportunityText(unittest.TestCase):
    def test_date_with_year(self):
        dates = ot.parse_dates("Applications due October 16, 2026.")
        self.assertEqual(dates[0]["start"], date(2026, 10, 16))

    def test_date_without_year_needs_hint_or_today(self):
        self.assertEqual(ot.parse_dates("Deadline: October 16"), [])
        self.assertEqual(ot.parse_dates("Deadline: October 16", nearby_year=2027)[0]["start"], date(2027, 10, 16))
        self.assertEqual(ot.parse_dates("Deadline: October 16", today=TODAY)[0]["start"], date(2027, 10, 16))

    def test_past_hint_rolls_year_back(self):
        got = ot.parse_dates("Applications closed on October 16", today=TODAY)
        self.assertEqual(got[0]["start"], date(2026, 10, 16))

    def test_open_now_negation(self):
        self.assertTrue(ot._open_now("Applications are now open for the 2027 cohort."))
        self.assertFalse(ot._open_now("Applications are not open yet."))

    def test_closed_pattern(self):
        text = "Applications closed on October 16, 2026."
        windows = ot.detect_applicant_windows(text, TODAY)
        self.assertEqual(ot.classify_status(text, windows, TODAY, True, "https://example.org/apply"), "closed")
        self.assertEqual(ot._lexical_status("Applications are closed.", TODAY)[0], "closed")

    def test_quote_has_date(self):
        self.assertTrue(ot.quote_has_date("Applications open on March 3, 2027.", "2027-03-03"))
        self.assertFalse(ot.quote_has_date("Applications open on March 4, 2027.", "2027-03-03"))

    def test_official_opening_quote(self):
        quote = "Applications open on March 3, 2027."
        self.assertEqual(ot.official_opening_quote(quote, "2027-03-03"), quote)
        self.assertIsNone(ot.official_opening_quote("Applications close on March 3, 2027.", "2027-03-03"))

    def test_no_category_import(self):
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "core", "opportunity_text.py")
        with open(path, encoding="utf-8") as handle:
            tree = ast.parse(handle.read())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                modules = [node.module or ""]
            else:
                continue
            for module in modules:
                self.assertNotEqual(module.split(".")[0], "categories", module)


if __name__ == "__main__":
    unittest.main()
