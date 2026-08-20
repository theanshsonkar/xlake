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
