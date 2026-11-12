import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline import coverage  # noqa: E402

CHEV = {"name": "Chevening Scholarships", "domain": "chevening.org", "aliases": ["Chevening"]}
GSOC = {"name": "Google Summer of Code", "domain": "google.com", "aliases": ["GSoC"]}


def row(name, url, **kw):
    r = {"programme_name": name, "official_url": url}
    r.update(kw)
    return r


class MatchTest(unittest.TestCase):
    def test_domain_and_name(self):
        r = row("Chevening Scholarships 2027", "https://www.chevening.org/scholarships/")
        self.assertEqual(coverage.match(CHEV, [r]), [r])

    def test_subdomain_and_specific_domain(self):
        r = row("Something unrelated", "https://apply.chevening.org/x")
        self.assertEqual(coverage.match(CHEV, [r]), [r])

    def test_alias(self):
        item = {"name": "Google Summer of Code", "domain": "summerofcode.withgoogle.com",
                "aliases": ["GSoC"]}
        self.assertEqual(len(coverage.match(item, [row("GSoC", "https://summerofcode.withgoogle.com/")])), 1)
        shared = dict(GSOC)
        self.assertEqual(len(coverage.match(shared, [row("GSoC", "https://g.google.com/x")])), 1)

    def test_no_false_match_on_shared_domain(self):
        r = row("Google Cloud Skills Boost", "https://cloud.google.com/learn")
        self.assertEqual(coverage.match(GSOC, [r]), [])

    def test_wrong_domain(self):
        self.assertEqual(coverage.match(CHEV, [row("Chevening", "https://notchevening.org/")]), [])

    def test_coverage_counts_and_junk(self):
        rows = [row("Chevening", "https://chevening.org/", is_live=True),
                row("Gone", "https://x.org/", hidden_reason="source_removed")]
        items = [CHEV, {"name": "Gone", "domain": "x.org", "aliases": []}]
        t, s, miss = coverage.coverage(items, rows)
        self.assertEqual((t, s, [m["name"] for m in miss]), (1, 1, ["Gone"]))


if __name__ == "__main__":
    unittest.main()
