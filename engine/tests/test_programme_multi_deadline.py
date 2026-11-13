import unittest
from datetime import datetime, timezone

from categories.fellowships import fellowships

NOW = datetime(2026, 11, 13, tzinfo=timezone.utc)
SEED = {"programme_id": "mlt-career-prep", "programme_name": "MLT Career Prep", "organizer": "Management Leadership for Tomorrow",
        "official_url": "https://mlt.org/career-prep/", "source_id": "t"}


def page(body):
    return "<html><body><h1>MLT Career Prep Program</h1><p>Fellowship programme for students.</p>{}</body></html>".format(body)


MLT = """<h2>Ready to Apply?</h2><p>The Career Prep Application is now open!</p><a href="/apply">Apply Today</a>
<h3>Priority Application Deadlines</h3><p>August 1, 2026 &ndash; Finance Track</p><p>September 1, 2026 &ndash; Consulting Track</p>
<p>November 1, 2026 &ndash; SWE / Technology &amp; Corporate Management Track</p>
<h3>General Application Deadlines</h3><p>December 1, 2026 &ndash; General</p><p>January 15, 2027 &ndash; Final</p>"""


class MultiDeadlineTests(unittest.TestCase):
    def parse(self, body):
        return fellowships.parse_programme(dict(SEED), page(body), NOW)

    def test_mlt_like_picks_earliest_future_deadline(self):
        record, _ = self.parse(MLT)
        self.assertEqual(record["programme_status"], "open")
        self.assertEqual(record["deadline"], "2026-12-01")
        self.assertIn("December 1, 2026", record["official_evidence"]["deadline"]["quote"])

    def test_single_past_deadline_unchanged(self):
        record, _ = self.parse("<p>Application deadline: August 1, 2026. Program applications.</p>")
        self.assertNotEqual(record["programme_status"], "open")
        self.assertIsNone(record["deadline"])

    def test_future_non_deadline_date_ignored(self):
        record, _ = self.parse("<p>Application deadline: August 1, 2026. Program applications.</p><p>The programme starts on January 10, 2027.</p>")
        self.assertNotEqual(record["programme_status"], "open")
        self.assertIsNone(record["deadline"])


if __name__ == "__main__":
    unittest.main()
