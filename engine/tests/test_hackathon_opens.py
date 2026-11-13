import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline import rowshape  # noqa: E402
from pipeline.rowshape import to_standard  # noqa: E402

QUOTE = "Registration opens on 15 December 2026 for all teams."


def hack(**kw):
    r = {"record_type": "hackathon", "hackathon_id": "https://h.example/", "title": "H",
         "organizer": "Org", "official_url": "https://h.example/", "status": "upcoming",
         "start_date": "2027-02-01", "end_date": "2027-02-03", "deadline": "2027-01-20",
         "is_live": True, "lifecycle": "upcoming", "official_evidence": {}}
    r.update(kw)
    return r


def at(day):
    return mock.patch.object(rowshape, "_today_utc", return_value=day)


class HackathonOpensTest(unittest.TestCase):
    def test_quote_dated_opens_is_upcoming(self):
        row = hack(opening_date="2026-12-15",
                   official_evidence={"opening_date": {"quote": QUOTE, "url": "https://h.example/"}})
        with at("2026-11-13"):
            s = to_standard(row)
        self.assertEqual(s["opens"], "2026-12-15")
        self.assertEqual(s["status"], "upcoming")

    def test_deadline_before_open_not_served(self):
        row = hack(opening_date="2026-12-15", deadline="2026-12-01",
                   official_evidence={"opening_date": {"quote": QUOTE}})
        with at("2026-11-13"):
            self.assertIsNone(to_standard(row)["deadline"])

    def test_event_start_only_has_no_opens(self):
        with at("2026-11-13"):
            s = to_standard(hack())
        self.assertIsNone(s["opens"])
        self.assertEqual(s["status"], "upcoming")  # unchanged from the row's own status
        with at("2026-11-13"):
            self.assertEqual(to_standard(hack(lifecycle="open"))["status"], "open")

    def test_non_opening_quote_rejected(self):
        row = hack(opening_date="2026-12-15", lifecycle="open",
                   official_evidence={"opening_date": {"quote": "Registration closes on 15 December 2026."}})
        with at("2026-11-13"):
            s = to_standard(row)
        self.assertIsNone(s["opens"])
        self.assertEqual(s["status"], "open")

    def test_unstop_registration_start_field(self):
        row = hack(registration_start="2026-12-01",
                   official_evidence={"start_regn_dt": "2026-12-01T00:00:00+05:30"})
        with at("2026-11-13"):
            s = to_standard(row)
        self.assertEqual((s["opens"], s["status"]), ("2026-12-01", "upcoming"))

    def test_registration_start_without_explicit_field_ignored(self):
        with at("2026-11-13"):
            self.assertIsNone(to_standard(hack(registration_start="2026-12-01"))["opens"])

    def test_flips_to_open_after_date(self):
        row = hack(opening_date="2026-12-15", official_evidence={"opening_date": {"quote": QUOTE}})
        row["lifecycle"] = "open"
        with at("2026-12-15"):
            self.assertEqual(to_standard(row)["status"], "open")
        with at("2026-12-14"):
            self.assertEqual(to_standard(row)["status"], "upcoming")

    def test_closed_stays_closed(self):
        with at("2026-11-13"):
            self.assertEqual(to_standard(hack(lifecycle="closed", is_live=False))["status"], "closed")


if __name__ == "__main__":
    unittest.main()
