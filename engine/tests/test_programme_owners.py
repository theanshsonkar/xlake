import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from categories import programme_core as core
from pipeline import publish_supabase as ps
from pipeline import programme_owners as owners_mod

NOW = "2026-10-20T00:00:00Z"


def row(category, pid, url="https://gemfellowship.org/", name="GEM Fellowship Program"):
    return {"record_type": "programme", "category": category, "programme_id": pid, "programme_name": name,
            "official_url": url, "is_live": True, "needs_confirmation": False}


class OwnerTests(unittest.TestCase):
    def test_owner_file_hides_other_category_row(self):
        rows = [row("scholarship", "scholarship-hub-gem-aaa")]
        n = core.hide_non_owned(rows, "scholarship", {"gemfellowship.org/": "fellowship"}, NOW)
        self.assertEqual(n, 1)
        self.assertEqual(rows[0]["hidden_reason"], "duplicate_other_category")
        self.assertFalse(rows[0]["is_live"])

    def test_owner_row_and_unlisted_rows_kept(self):
        rows = [row("fellowship", "fellowship-gem"), row("scholarship", "s-other", url="https://x.org/y")]
        self.assertEqual(core.hide_non_owned(rows, "fellowship", {"gemfellowship.org/": "fellowship"}, NOW), 0)
        self.assertEqual(core.hide_non_owned(rows, "scholarship", {"gemfellowship.org/": "fellowship"}, NOW), 0)

    def test_default_priority(self):
        pick = core.choose_owner([row("grant", "g-1"), row("scholarship", "s-1"), row("research", "r-1")])
        self.assertEqual(pick, "scholarship")
        self.assertEqual(core.choose_owner([row("open-source-programmes", "o-1"), row("community", "c-1")]), "community")

    def test_hand_seed_beats_hub_seed(self):
        n = "Fulbright Foreign Student Program"  # name states no category
        pick = core.choose_owner([row("fellowship", "fellowship-x", name=n), row("scholarship", "scholarship-hub-x-abc123", name=n)])
        self.assertEqual(pick, "fellowship")

    def test_own_name_decides_first(self):
        n = "Knight-Hennessy Scholars"
        self.assertEqual(core.choose_owner([row("fellowship", "fellowship-kh", name=n), row("scholarship", "scholarship-hub-kh-1", name=n)]), "scholarship")
        g = "GEM Fellowship Program"
        self.assertEqual(core.choose_owner([row("scholarship", "scholarship-gem", name=g), row("fellowship", "fellowship-hub-gem-1", name=g)]), "fellowship")

    def test_ambiguous_name_prefers_scholarship(self):
        n = "Fulbright Foreign Student Program"
        self.assertEqual(core.choose_owner([row("fellowship", "f-1", name=n), row("scholarship", "s-1", name=n)]), "scholarship")

    def test_hidden_row_not_served(self):
        rows = [row("scholarship", "s-1")]
        self.assertTrue(ps.is_serving(rows[0]))
        core.hide_non_owned(rows, "scholarship", {"gemfellowship.org/": "fellowship"}, NOW)
        self.assertFalse(ps.is_serving(rows[0]))
        self.assertFalse(ps.is_serving({**row("scholarship", "s-2"), "hidden_reason": "duplicate_other_category"}))

    def test_generator_groups_cross_category_only(self):
        rows = [row("scholarship", "s-1"), row("fellowship", "f-1"), row("grant", "g-1", url="https://z.org/a", name="Other")]
        groups = owners_mod.find_groups(rows)
        self.assertEqual(len(groups), 1)
        self.assertEqual(owners_mod.build_owners(groups), {"gemfellowship.org/": "fellowship"})


if __name__ == "__main__":
    unittest.main()
