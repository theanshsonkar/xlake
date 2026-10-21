import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from categories.programme_core import programme_title_ok
from categories.stem import is_junk_title, is_stem_programme


class TestStemProgrammes(unittest.TestCase):
    def test_stem_titles(self):
        for title in ("Google PhD Fellowship in Machine Learning", "Fulbright Program",
                      "Physics Research Grant", "Quantitative Finance Research Fellowship"):
            self.assertTrue(is_stem_programme({"title": title}), title)

    def test_non_stem_titles(self):
        for title in ("Poetry Fellowship", "Language Learning Scholarship",
                      "Public Policy Fellowship", "Merit Scholarship"):
            self.assertFalse(is_stem_programme({"title": title}), title)

    def test_summary_can_decide(self):
        row = {"title": "Excellence Award", "summary": "For students of engineering and physics."}
        self.assertTrue(is_stem_programme(row))

    def test_markdown_junk_title_rejected(self):
        ok, reason = programme_title_ok("> :warning: State aid rules change frequently",
                                        "https://example.org/grants", "fellowship")
        self.assertFalse(ok)
        self.assertEqual(reason, "malformed_title")

    def test_junk_titles(self):
        for title in ("| Rolling (FAFSA ASAP) | | OPEN", "Jul 9, 2026 | --- ## Rising", "Apply / details \u2192",
                      "Read blog post", "AI startup raises | TechCrunch \u203a", "## Heading"):
            self.assertTrue(is_junk_title(title), title)
            self.assertFalse(programme_title_ok(title, "https://example.org/x", "grant")[0], title)
        self.assertFalse(is_junk_title("Google PhD Fellowship"))

    def test_defaults_and_known_stem(self):
        self.assertTrue(is_stem_programme({"title": "Cohort", "category": "open-source-programmes"}))
        self.assertFalse(is_stem_programme({"title": "Poetry Prize", "category": "research"}))
        for t in ("Hertz Fellowship", "NOAA Hollings Scholarship", "Wellcome Discovery Awards",
                  "Icar National Talent Scholarship", "AICTE - Pragati Scholarship Scheme"):
            self.assertTrue(is_stem_programme({"title": t}), t)


if __name__ == "__main__":
    unittest.main()
