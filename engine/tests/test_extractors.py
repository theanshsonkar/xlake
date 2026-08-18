"""Tests for the anti-hallucination rule and the fixture extractor.

Two layers are tested separately:
  - enforce_quotes(): the rule itself, with synthetic pages, so it is pinned
    independent of any real fixture ever changing.
  - FixtureExtractor against the 6 real saved pages in fixtures/pages/, so a
    regression in the real fixtures is caught by CI, not by hand.
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from adapters import extractors  # noqa: E402
from core import pagetext  # noqa: E402
from pipeline.build_fixtures import PAGES, page_path  # noqa: E402


class TestQuoteMatching(unittest.TestCase):
    def test_exact_quote_matches(self):
        page = "Some text. Software Engineer Intern, Bengaluru. More text."
        self.assertTrue(
            extractors.quote_is_in_page("Software Engineer Intern, Bengaluru", page)
        )

    def test_curly_quotes_and_whitespace_are_forgiven(self):
        page = "The role requires   graduating in 2027 for eligibility."
        quote = "graduating in 2027"
        self.assertTrue(extractors.quote_is_in_page(quote, page))

    def test_different_words_do_not_match(self):
        page = "Senior Software Engineer, 5+ years required."
        quote = "Software Engineer Intern, no experience required"
        self.assertFalse(extractors.quote_is_in_page(quote, page))

    def test_short_quotes_are_rejected_regardless_of_match(self):
        # A quote must be substantial to count as evidence. "Intern" appearing
        # somewhere on the page proves nothing about a SPECIFIC role.
        page = "Internship opportunities across engineering."
        self.assertFalse(extractors.quote_is_in_page("Intern", page))

    def test_empty_quote_never_matches(self):
        self.assertFalse(extractors.quote_is_in_page("", "anything at all here"))


class TestEnforceQuotes(unittest.TestCase):
    """The rule that makes a hallucinated posting impossible to keep."""

    def _result(self, roles):
        r = extractors.ExtractionResult(url="https://example.test/careers")
        r.roles = roles
        return r

    def test_role_with_real_quote_survives(self):
        page = "Now hiring: Software Engineer Intern (Summer 2027), Bengaluru."
        role = extractors.ExtractedRole(
            title="Software Engineer Intern",
            quote="Software Engineer Intern (Summer 2027), Bengaluru",
        )
        res = extractors.enforce_quotes(self._result([role]), page)
        self.assertEqual(len(res.roles), 1)
        self.assertEqual(res.discarded_unquoted, 0)

    def test_invented_role_is_discarded(self):
        # This is the case: a JS-shell page with almost no text, and a model
        # returning a plausible-looking posting that is not actually on it.
        page = "Loading application... please wait."
        role = extractors.ExtractedRole(
            title="Software Engineer Intern",
            quote="Software Engineer Intern (Summer 2027), Bengaluru, apply by March",
        )
        res = extractors.enforce_quotes(self._result([role]), page)
        self.assertEqual(len(res.roles), 0)
        self.assertEqual(res.discarded_unquoted, 1)
        self.assertIn("Software Engineer Intern", res.discarded_titles[0])

    def test_one_bad_role_does_not_sink_a_good_one(self):
        page = "Data Analyst Intern, Mumbai. Full details on request."
        good = extractors.ExtractedRole(title="Data Analyst Intern",
                                        quote="Data Analyst Intern, Mumbai")
        bad = extractors.ExtractedRole(title="Fake Role",
                                       quote="This sentence does not exist anywhere")
        res = extractors.enforce_quotes(self._result([good, bad]), page)
        self.assertEqual(len(res.roles), 1)
        self.assertEqual(res.roles[0].title, "Data Analyst Intern")
        self.assertEqual(res.discarded_unquoted, 1)

    def test_a_hallucinated_evidence_line_is_stripped_not_the_whole_role(self):
        # The primary quote is real; one gate's evidence is invented. The role
        # is real, so it survives — but loses the unsupported gate.
        page = "Graduate Software Engineer, London. Apply via our careers site."
        role = extractors.ExtractedRole(
            title="Graduate Software Engineer",
            quote="Graduate Software Engineer, London",
            degree_ceiling="Master's required",
            evidence={
                "degree_ceiling": "candidates must hold a completed Master's degree",
            },
        )
        res = extractors.enforce_quotes(self._result([role]), page)
        self.assertEqual(len(res.roles), 1)
        self.assertNotIn("degree_ceiling", res.roles[0].evidence)

    def test_all_roles_can_be_legitimately_empty(self):
        # An empty list is a correct, common, and NON-failing outcome.
        res = extractors.enforce_quotes(self._result([]), "Sign in to continue.")
        self.assertEqual(len(res.roles), 0)
        self.assertEqual(res.discarded_unquoted, 0)


class TestFixtureExtractor(unittest.TestCase):
    """The self-built fixtures, exercised through the real extractor interface."""

    def setUp(self):
        self.ex = extractors.FixtureExtractor()

    def _html(self, key: str) -> str:
        return open(page_path("dummy") if False else
                    os.path.join(PAGES, "page_{}.html".format(key)),
                    encoding="utf-8", errors="replace").read()

    def test_zerodha_js_shell_yields_nothing(self):
        url = "https://zerodha.com/careers/"
        html = self._html(extractors.fixture_key(url))
        res = self.ex.extract(html, url)
        self.assertTrue(res.ok)
        self.assertEqual(res.roles, [])

    def test_swiggy_js_shell_yields_nothing(self):
        url = "https://www.swiggy.com/careers"
        html = self._html(extractors.fixture_key(url))
        res = self.ex.extract(html, url)
        self.assertTrue(res.ok)
        self.assertEqual(res.roles, [])

    def test_zoho_recruit_portal_yields_nothing_despite_having_some_text(self):
        # The subtle negative case: 438 characters of JSON residue, not zero.
        url = "https://busigence.zohorecruit.com/jobs/Careers"
        html = self._html(extractors.fixture_key(url))
        res = self.ex.extract(html, url)
        self.assertTrue(res.ok)
        self.assertEqual(res.roles, [])

    def test_cern_closed_programme_yields_no_current_roles(self):
        url = "https://careers.cern/programmes/technical-studentship"
        html = self._html(extractors.fixture_key(url))
        res = self.ex.extract(html, url)
        self.assertTrue(res.ok)
        self.assertEqual(res.roles, [])

    def test_optiver_yields_only_the_early_career_rows(self):
        url = "https://www.optiver.com/working-at-optiver/career-opportunities/"
        html = self._html(extractors.fixture_key(url))
        res = self.ex.extract(html, url)
        self.assertTrue(res.ok)
        self.assertEqual(len(res.roles), 2)
        stages = {r.stage for r in res.roles}
        self.assertEqual(stages, {"intern", "fresher_newgrad"})
        # None of the "Experienced" rows (Senior Technical Recruiter, etc.)
        # leaked in.
        titles = " ".join(r.title for r in res.roles)
        self.assertNotIn("Senior", titles)
        self.assertNotIn("Recruiter", titles)

    def test_iith_ccs_yields_only_the_intern_row(self):
        url = "https://ccs.iith.ac.in/careers"
        html = self._html(extractors.fixture_key(url))
        res = self.ex.extract(html, url)
        self.assertTrue(res.ok)
        self.assertEqual(len(res.roles), 1)
        self.assertEqual(res.roles[0].title, "Interns")
        # The other six listed positions (Postdoc, PhD, M.Tech RA, Predoc,
        # Scientific Officer x3, Systems Engineer) must not appear.
        self.assertNotIn("Postdoctoral", res.roles[0].title)

    def test_every_real_fixture_passes_the_quote_rule_against_its_own_page(self):
        # Belt-and-braces: even though the fixtures were hand-verified with
        # build_fixtures.py check, pin it here so CI catches drift if a fixture
        # is edited without re-running that check.
        for fname in sorted(os.listdir(PAGES)):
            if not fname.endswith(".html"):
                continue
            key = fname[len("page_"):-len(".html")]
            meta_path = os.path.join(PAGES, "page_{}.meta.json".format(key))
            if not os.path.exists(meta_path):
                continue
            import json

            url = json.load(open(meta_path))["url"]
            html = self._html(key)
            text = pagetext.to_text(html)
            res = self.ex.extract(html, url)
            before = len(res.roles)
            extractors.enforce_quotes(res, text)
            self.assertEqual(
                len(res.roles), before,
                "fixture for {} contains a quote not found in its own saved page"
                .format(url),
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
