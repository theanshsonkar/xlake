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

    def test_clean_token(self):
        self.assertEqual(admit.clean_token("kp-group"), "Kp Group")
        self.assertEqual(admit.clean_token("kpgroup"), "Kpgroup")


if __name__ == "__main__":
    unittest.main()
