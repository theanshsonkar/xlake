import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from adapters.boards import Posting, _unstop_company
from core import filters


class TestUnstopCompany(unittest.TestCase):
    def test_company_extraction(self):
        cases = (
            ({"organisation": {"name": "Aalteon"}}, "Aalteon"),
            ({}, ""),
            ({"organisation": "Aalteon"}, ""),
            ({"organisation": {}}, ""),
            ({"organisation": {"name": None}}, ""),
            ({"organisation": {"name": "  Aalteon  "}}, "Aalteon"),
        )
        for record, expected in cases:
            with self.subTest(record=record):
                self.assertEqual(_unstop_company(record), expected)
        self.assertEqual(_unstop_company(None), "")

    def test_posting_company_field(self):
        posting = Posting("unstop", "token", "1", "Title", company="Acme")
        self.assertEqual(posting.company, "Acme")
        self.assertEqual(Posting("unstop", "token", "2", "Title").company, "")


class TestInternshipHiddenReason(unittest.TestCase):
    def test_technical_internships_surface(self):
        for title in (
            "Full Stack Developer Internship",
            "Data Analyst Internship",
            "Artificial Intelligence Internship",
            "Backend Developer Internship",
            "Machine Learning Internship",
        ):
            with self.subTest(title=title):
                verdict = filters.classify(title, india_source=True)
                self.assertNotEqual(verdict.stage, "senior")
                self.assertIsNone(
                    filters.hidden_reason(
                        verdict.stage, verdict.bucket, verdict.technical,
                        None, verdict.discipline, verdict.is_internship),
                    msg="classify=(technical={!r}, discipline={!r}, is_internship={!r})".format(
                        verdict.technical, verdict.discipline, verdict.is_internship),
                )

    def test_non_technical_internships_are_hidden(self):
        for title in (
            "Campus Ambassador Internship",
            "Community Management Internship",
            "Marketing Internship",
            "HR Internship",
            "Video Editor Internship",
            "Civil Engineer Internship",
            "Mechanical Engineer Internship",
        ):
            with self.subTest(title=title):
                verdict = filters.classify(title, india_source=True)
                self.assertNotEqual(verdict.stage, "senior")
                self.assertEqual(
                    filters.hidden_reason(
                        verdict.stage, verdict.bucket, verdict.technical,
                        None, verdict.discipline, verdict.is_internship),
                    filters.HIDDEN_NON_TECHNICAL,
                    msg="classify=(technical={!r}, discipline={!r}, is_internship={!r})".format(
                        verdict.technical, verdict.discipline, verdict.is_internship),
                )

    def test_job_no_signal_is_not_hidden(self):
        self.assertIsNone(
            filters.hidden_reason(
                "unknown", filters.INDIA_LOCATED, None,
                discipline="unknown", is_internship=False)
        )
        self.assertEqual(
            filters.hidden_reason(
                "unknown", filters.INDIA_LOCATED, False,
                discipline=filters.NON_TECH, is_internship=False),
            filters.HIDDEN_NON_TECHNICAL,
        )


if __name__ == "__main__":
    unittest.main()


class TestUnstopInternshipFacts(unittest.TestCase):
    def setUp(self):
        import json
        from adapters import boards
        path = os.path.join(os.path.dirname(__file__), "fixtures", "unstop_internship.json")
        self.item = json.load(open(path))["data"]["data"][0]
        self.boards = boards

    def test_meta(self):
        from adapters.boards import _unstop_job_meta
        m = _unstop_job_meta(self.item, {}, "", self.item["end_date"])
        self.assertEqual(m["company_display_name"], "7 Codearena Private Limited")
        self.assertTrue(m["logo_url"].startswith("https://"))
        self.assertEqual(m["employment_type"], "internship")
        self.assertEqual(m["gender"], "Female")
        self.assertEqual(m["source_kind"], "aggregator")
        self.assertNotIn("unstop.com", m.get("company_domain", ""))
        self.assertIn("₹", m["funding"])
        self.assertTrue(m["funding"].endswith("/month"))
        self.assertLessEqual(len(m["description"]), 300)
        self.assertRegex(m["deadline"], r"^\d{4}-\d{2}-\d{2}$")

    def test_aggregator_guard(self):
        from core import jobmeta
        for n in ("Unstop", "internshala", "Devpost ", ""):
            self.assertEqual(jobmeta.real_company(n), "")
        self.assertEqual(jobmeta.real_company("Acme"), "Acme")
        self.assertEqual(_unstop_company({"organisation": {"name": "Unstop"}}), "")

    def test_prizes(self):
        from core import unstop_facts
        out = unstop_facts.prizes_breakdown([{"rank": "1st", "cash": 10000, "currency": "fa-rupee"}, {"rank": "x", "cash": 0}])
        self.assertEqual(out, [{"rank": "1st", "amount": 10000, "currency": "INR"}])
