import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from discover import portfolios  # noqa: E402


class TestPortfolios(unittest.TestCase):
    def test_registrable_domain(self):
        self.assertEqual(portfolios.registrable_domain("www.Foo.COM"), "foo.com")
        self.assertEqual(portfolios.registrable_domain("careers.foo.co.in"), "foo.co.in")
        self.assertEqual(portfolios.registrable_domain("a.b.foo.io"), "foo.io")
        self.assertEqual(portfolios.registrable_domain(""), "")

    def test_extract_links(self):
        html = '<a href="/one"> One\n Company </a><a href="https://two.example/x">Two</a><a href="mailto:x">Mail</a><a href="#">Skip</a>'
        self.assertEqual(
            portfolios.extract_links(html, "https://source.example/base/"),
            [("https://source.example/one", "One Company"), ("https://two.example/x", "Two")],
        )

    def test_extract_links_survives_unclosed_anchor(self):
        html = '<a href="https://one.example">One<a href="https://two.example">Two</a>'
        self.assertEqual(
            portfolios.extract_links(html, "https://source.example/"),
            [("https://one.example", "One"), ("https://two.example", "Two")],
        )

    def test_harvest_links_filters_and_deduplicates(self):
        html = ('<a href="https://linkedin.com/company/x">LinkedIn</a>'
                '<a href="https://source.example/about">Source</a>'
                '<a href="https://company.example/one"> </a>'
                '<a href="https://www.company.example/two">company</a>')
        self.assertEqual(
            portfolios.harvest_links(html, "https://source.example/", "source.example"),
            [{"company": "company", "company_name_source": "anchor_text", "website": "https://company.example/one", "domain": "company.example"}],
        )

    def test_harvest_links_extracts_name_metadata_in_order(self):
        html = (
            '<a href="https://img.example"><img alt="Image Name"></a>'
            '<a href="https://title.example" title="Title Name"></a>'
            '<a href="https://aria.example" aria-label="Aria Name"></a>'
            '<a href="https://domain-label.example"></a>'
        )
        self.assertEqual(
            portfolios.harvest_links(html, "https://source.example/", "source.example"),
            [
                {"company": "Image Name", "company_name_source": "img_alt", "website": "https://img.example", "domain": "img.example"},
                {"company": "Title Name", "company_name_source": "title", "website": "https://title.example", "domain": "title.example"},
                {"company": "Aria Name", "company_name_source": "aria_label", "website": "https://aria.example", "domain": "aria.example"},
                {"company": "Domain Label", "company_name_source": "domain_label", "website": "https://domain-label.example", "domain": "domain-label.example"},
            ],
        )

    def test_extract_json_nested_paths(self):
        payload = {"data": {"items": [{"meta": {"name": "Acme"}, "links": {"site": "https://acme.example"}}]}}
        self.assertEqual(
            portfolios.extract_json(payload, "data.items", "meta.name", "links.site"),
            [{"company": "Acme", "website": "https://acme.example", "domain": "acme.example"}],
        )

    def test_merge_preserves_and_retains(self):
        existing = [
            {"portfolio_slug": "p", "domain": "old.example", "company": "Old", "website": "https://old.example", "first_seen": "before", "last_seen": "before"},
            {"portfolio_slug": "p", "domain": "gone.example", "company": "Gone", "website": "https://gone.example", "first_seen": "before", "last_seen": "before"},
        ]
        found = [{"portfolio_slug": "p", "domain": "old.example", "company": "Updated", "website": "https://old.example/new"}]
        merged = portfolios.merge_companies(existing, found, "now")
        self.assertEqual(merged[0]["first_seen"], "before")
        self.assertEqual(merged[0]["last_seen"], "now")
        self.assertEqual(len(merged), 2)

    def test_read_portfolio_blocked(self):
        source = {"slug": "p", "url": "https://source.example/", "kind": "links", "min_expected": 2}
        original = portfolios.robots.allowed
        try:
            portfolios.robots.allowed = lambda url: (False, "disallowed")
            blocked = portfolios.read_portfolio(source, fetcher=lambda url: (200, "", None))
            self.assertEqual(blocked.read_outcome, "blocked")
            self.assertFalse(blocked.robots_allowed)
            self.assertFalse(blocked.yield_below_expected)
        finally:
            portfolios.robots.allowed = original

    def test_read_portfolio_low_yield_is_complete(self):
        source = {"slug": "p", "url": "https://source.example/", "kind": "links", "min_expected": 2}
        original = portfolios.robots.allowed
        try:
            portfolios.robots.allowed = lambda url: (True, "ok")
            result = portfolios.read_portfolio(
                source, fetcher=lambda url: (200, '<a href="https://acme.example">Acme</a>', None)
            )
            self.assertEqual(result.read_outcome, "complete")
            self.assertTrue(result.yield_below_expected)
            self.assertEqual(len(result.companies), 1)
        finally:
            portfolios.robots.allowed = original

    def test_read_portfolio_unexpected_status(self):
        source = {"slug": "p", "url": "https://source.example/", "kind": "links", "min_expected": 2}
        original = portfolios.robots.allowed
        try:
            portfolios.robots.allowed = lambda url: (True, "ok")
            result = portfolios.read_portfolio(
                source, fetcher=lambda url: (400, '<a href="https://acme.example">Acme</a>', None)
            )
            self.assertEqual(result.read_outcome, "errored")
            self.assertEqual(result.companies, [])
        finally:
            portfolios.robots.allowed = original

    def test_read_portfolio_json_branch(self):
        source = {
            "slug": "p", "url": "https://source.example/", "kind": "json",
            "items_path": "data.items", "name_key": "meta.name", "url_key": "links.site",
            "min_expected": 1,
        }
        payload = {"data": {"items": [{"meta": {"name": "Acme"}, "links": {"site": "https://acme.example"}}]}}
        original = portfolios.robots.allowed
        try:
            portfolios.robots.allowed = lambda url: (True, "ok")
            result_dict = portfolios.read_portfolio(source, fetcher=lambda url: (200, payload, None))
            result_string = portfolios.read_portfolio(source, fetcher=lambda url: (200, portfolios.json.dumps(payload), None))
            self.assertEqual(result_dict.read_outcome, "complete")
            self.assertEqual(result_string.read_outcome, "complete")
            self.assertEqual(result_dict.companies, result_string.companies)
            self.assertEqual(result_dict.companies, [{"company": "Acme", "website": "https://acme.example", "domain": "acme.example"}])
        finally:
            portfolios.robots.allowed = original

    def test_read_portfolio_json_items_path_mismatch(self):
        source = {
            "slug": "p", "url": "https://source.example/", "kind": "json",
            "items_path": "data.items", "name_key": "meta.name", "url_key": "links.site",
            "min_expected": 1,
        }
        original = portfolios.robots.allowed
        try:
            portfolios.robots.allowed = lambda url: (True, "ok")
            result = portfolios.read_portfolio(source, fetcher=lambda url: (200, {"data": {"items": {}}}, None))
            self.assertEqual(result.read_outcome, "partial")
            self.assertEqual(result.companies, [])
        finally:
            portfolios.robots.allowed = original


if __name__ == "__main__":
    unittest.main()
