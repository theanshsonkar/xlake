import unittest

from categories.programme_core import closing_from_opening_quote as closing


class ClosingFromOpeningQuoteTests(unittest.TestCase):
    def test_full_ranges(self):
        cases = [
            ("\u2192 Application Period: December 1st, 2026 \u2013 February 3rd, 2027.", "2026-12-01", "2027-02-03"),
            ("Application Period. Apply Between:. November 15, 2026-February 15, 2027.", "2026-11-15", "2027-02-15"),
            ("Online application. : November 15, 2026 \u2013 February 15, 2027.", "2026-11-15", "2027-02-15"),
            ("Applications accepted between 12/01/2026 - 02/15/2027.", "2026-12-01", "2027-02-15"),
        ]
        for quote, opening, end in cases:
            self.assertEqual(closing(quote, opening), end, quote)

    def test_year_only_from_start_date(self):
        self.assertEqual(closing("Applications: December 1, 2026 \u2013 December 20.", "2026-12-01"), "2026-12-20")
        self.assertIsNone(closing("Applications: December 1, 2026 \u2013 March 1.", "2026-12-01"))

    def test_no_year_or_single_date(self):
        self.assertIsNone(closing("Junior Application Period:. December 1 \u2013 March 1.", "2026-12-01"))
        self.assertIsNone(closing("Applications open December 1, 2026.", "2026-12-01"))

    def test_end_must_follow_opening(self):
        self.assertIsNone(closing("Period: December 1, 2026 \u2013 November 1, 2026.", "2026-12-01"))


if __name__ == "__main__":
    unittest.main()
