import copy
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline import admit_boards as admit


class RefreshNamesTest(unittest.TestCase):
    def test_replaces_token_with_resolved_name(self):
        registry = [{
            "platform": "greenhouse", "token": "10alabs", "company": "10alabs",
            "segment": "unclassified", "source": "discovery", "evidence": "e",
        }]

        def fake(platform, token):
            self.assertEqual((platform, token), ("greenhouse", "10alabs"))
            return "10a Labs", "greenhouse-api"

        admit.refresh_display_names(registry, resolve_fn=fake)
        self.assertEqual(registry[0]["company"], "10a Labs")
        self.assertEqual(registry[0]["token"], "10alabs")
        self.assertEqual(registry[0]["segment"], "unclassified")
        self.assertEqual(registry[0]["source"], "discovery")
        self.assertEqual(registry[0]["evidence"], "e")

    def test_non_discovery_untouched(self):
        registry = [{
            "platform": "greenhouse", "token": "wipro", "company": "Wipro",
            "segment": "x", "source": "resolver", "evidence": "e",
        }]

        def fake(_platform, _token):
            raise AssertionError("non-discovery entries must be skipped")

        before = copy.deepcopy(registry)
        rows = admit.refresh_display_names(registry, resolve_fn=fake)
        self.assertEqual(registry, before)
        self.assertEqual(rows, [])

    def test_idempotent(self):
        registry = [{
            "platform": "keka", "token": "100", "company": "100",
            "segment": "unclassified", "source": "discovery", "evidence": "e",
        }]

        def fake(_platform, token):
            return {"100": "Bright Future"}[token], "keka-title"

        admit.refresh_display_names(registry, resolve_fn=fake)
        after_first = copy.deepcopy(registry)
        admit.refresh_display_names(registry, resolve_fn=fake)
        self.assertEqual(registry, after_first)
        self.assertEqual(registry[0]["company"], "Bright Future")
        self.assertEqual(len(registry), 1)

    def test_fallback_kind_updates_and_reports(self):
        registry = [{
            "platform": "keka", "token": "kpgroup", "company": "kpgroup",
            "segment": "unclassified", "source": "discovery", "evidence": "e",
        }]

        def fake(_platform, _token):
            return "Kpgroup", "fallback-token"

        rows = admit.refresh_display_names(registry, resolve_fn=fake)
        self.assertEqual(registry[0]["company"], "Kpgroup")
        self.assertEqual(rows[0]["kind"], "fallback-token")

    def test_unresolved_leaves_company(self):
        registry = [{
            "platform": "greenhouse", "token": "unknown", "company": "Unknown",
            "segment": "unclassified", "source": "discovery", "evidence": "e",
        }]

        def fake(_platform, _token):
            return None, "unresolved"

        rows = admit.refresh_display_names(registry, resolve_fn=fake)
        self.assertEqual(registry[0]["company"], "Unknown")
        self.assertEqual(rows[0]["kind"], "unresolved")
        self.assertEqual(rows[0]["new_company"], "Unknown")

    def test_parse_keka_title(self):
        self.assertEqual(
            admit.parse_keka_title("<title>Careers at Bright Future</title>"),
            "Bright Future",
        )
        self.assertEqual(
            admit.parse_keka_title(
                "<html><head><title>Brewbay Innovations - Careers</title></head>"
            ),
            "Brewbay Innovations",
        )
        self.assertIsNone(admit.parse_keka_title("<title>Some Random Page</title>"))
        self.assertIsNone(admit.parse_keka_title("<html>no title</html>"))

    def test_x_careers_title_pattern(self):
        self.assertEqual(
            admit.parse_keka_title("<title>Entropik Careers</title>"),
            "Entropik",
        )
        self.assertEqual(
            admit.parse_keka_title("<title>Careers at Foo</title>"),
            "Foo",
        )
        self.assertEqual(
            admit.parse_keka_title("<title>Bar - Careers</title>"),
            "Bar",
        )

    def test_clean_token(self):
        self.assertEqual(admit.clean_token("kp-group"), "Kp Group")
        self.assertEqual(admit.clean_token("kpgroup"), "Kpgroup")


class KekaNameParsingTest(unittest.TestCase):
    def _fetch(self, token, html, status=200):
        def fake(url, want_json=True):
            return status, html, None

        return admit._fetch_keka_name(token, request_fn=fake)

    def test_og_title_used_when_title_generic(self):
        html = ('<html><head><title>Keka Hire</title>'
                '<meta property="og:title" content="Careers at Entropik">'
                '</head></html>')
        self.assertEqual(
            self._fetch("entropik", html),
            ("Entropik", "keka-og-title"),
        )

    def test_fetch_keka_x_careers_is_keka_title(self):
        def fake(url, want_json=True):
            return 200, "<title>Entropik Careers</title>", None

        self.assertEqual(
            admit._fetch_keka_name("entropik", request_fn=fake),
            ("Entropik", "keka-title"),
        )

    def test_title_preferred_over_og_title(self):
        html = ('<title>Careers at Foo</title>'
                '<meta property="og:title" content="Careers at Bar">')
        self.assertEqual(
            self._fetch("foo", html),
            ("Foo", "keka-title"),
        )

    def test_fallback_labeled_when_no_name(self):
        html = "<title>Keka Hire</title>"
        self.assertEqual(
            self._fetch("aitmc", html),
            (admit.clean_token("aitmc"), "fallback-token"),
        )

    def test_unresolved_on_failed_read(self):
        def fake(url, want_json=True):
            return None, None, "timeout"

        self.assertEqual(
            admit._fetch_keka_name("x", request_fn=fake),
            (None, "unresolved"),
        )

    def test_parse_keka_og_title_direct(self):
        self.assertEqual(
            admit.parse_keka_og_title(
                '<meta property="og:title" content="Careers at Entropik">'
            ),
            "Entropik",
        )
        self.assertEqual(
            admit.parse_keka_og_title(
                '<meta content="Jobs at Acme" property="og:title">'
            ),
            "Acme",
        )
        self.assertIsNone(
            admit.parse_keka_og_title("<title>no og</title>")
        )


if __name__ == "__main__":
    unittest.main()
