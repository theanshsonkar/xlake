import unittest
from datetime import date, datetime, timezone

from categories.research import research
from core import lifecycle

NOW = datetime(2026, 11, 13, tzinfo=timezone.utc)
HTML = ("<html><body><h1>Scholarships</h1><p>Apply Now</p><p>Application Status</p>"
        "<p>Applications Open for 2027</p><p>Deadline:</p><p>15th November 2026, 11:59pm (IST)</p>"
        "<p>For any further questions, please reach out to</p></body></html>")


class DeadlineOnNextLineTests(unittest.TestCase):
    def setUp(self):
        self.record, _ = research.parse_programme(dict(research.SEEDS[0]), HTML, NOW)

    def test_deadline_extracted(self):
        self.assertEqual(self.record["deadline"], "2026-11-15")

    def test_open_before_and_closed_after(self):
        self.assertEqual(lifecycle.infer(self.record, date(2026, 11, 13)), "open")
        self.assertFalse(lifecycle.deadline_passed(self.record, date(2026, 11, 15)))
        self.assertTrue(lifecycle.deadline_passed(self.record, date(2026, 11, 16)))


if __name__ == "__main__":
    unittest.main()
