"""Tests for the Workday token extraction added to enumerate_boards.py.

These run fully offline against known-good URLs (the same shapes already
present in data/registry.json, resolved live by resolve.py in an earlier
session) — they do NOT touch Common Crawl. See enumerate_boards.py's module
docstring: the Common Crawl query itself has not been live-verified in this
sandbox because outbound network to index.commoncrawl.org is unreachable
here. This test only proves the URL -> token parser is correct; it cannot
prove Common Crawl actually returns Workday URLs in this format at scale.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from enumerate_boards import _workday_token_from_url  # noqa: E402


class TestWorkdayTokenFromUrl(unittest.TestCase):
    def test_site_only_no_locale(self):
        self.assertEqual(
            _workday_token_from_url("https://intel.wd1.myworkdayjobs.com/External"),
            "intel.wd1.myworkdayjobs.com|intel|External",
        )

    def test_matches_known_registry_entry_accenture(self):
        # This exact token is already live in data/registry.json, resolved by
        # resolve.py against the real careers page redirect.
        self.assertEqual(
            _workday_token_from_url(
                "https://accenture.wd103.myworkdayjobs.com/AccentureCareers"
            ),
            "accenture.wd103.myworkdayjobs.com|accenture|AccentureCareers",
        )

    def test_locale_prefix_is_dropped_from_site(self):
        self.assertEqual(
            _workday_token_from_url("https://citi.wd5.myworkdayjobs.com/en-US/2"),
            "citi.wd5.myworkdayjobs.com|citi|2",
        )

    def test_deep_job_posting_url_collapses_to_site_token(self):
        # A specific job posting URL must resolve to the SAME token as the
        # board root, or enumeration would mint one fake "board" per posting.
        deep = _workday_token_from_url(
            "https://redhat.wd5.myworkdayjobs.com/jobs/job/Pune---Tower-6/"
            "Site-Reliability-Engineering-Intern_R-058641"
        )
        root = _workday_token_from_url("https://redhat.wd5.myworkdayjobs.com/jobs")
        self.assertEqual(deep, root)
        self.assertEqual(deep, "redhat.wd5.myworkdayjobs.com|redhat|jobs")

    def test_non_workday_url_returns_empty(self):
        self.assertEqual(
            _workday_token_from_url("https://boards.greenhouse.io/vercel"), ""
        )

    def test_malformed_workday_domain_returns_empty(self):
        # No wdN segment -> not a real Workday tenant host.
        self.assertEqual(
            _workday_token_from_url("https://myworkdayjobs.com/jobs"), ""
        )


if __name__ == "__main__":
    unittest.main()
