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


class SameCategoryAndCrossHostTests(unittest.TestCase):
    def test_same_category_same_host_similar_name_hidden(self):
        a = row("fellowship", "fellowship-thiel-fellowship", "https://thielfellowship.org/", "Thiel Fellowship")
        a["deadline"] = "2027-01-01"
        b = row("fellowship", "fellowship-thiel", "https://thielfellowship.org/apply", "The Thiel Fellowship Program")
        self.assertEqual(core.dedupe_within_category([a, b], NOW), 1)
        self.assertEqual(b["hidden_reason"], "duplicate_same_category")
        self.assertFalse(b["is_live"])
        self.assertFalse(ps.is_serving(b))
        self.assertTrue(ps.is_serving(a))

    def test_same_category_prefers_hand_listed_over_hub(self):
        hub = row("grant", "grants-hub-x-aaa", "https://x.org/", "X Grant")
        seed = row("grant", "grant-x", "https://x.org/", "X Grant")
        core.dedupe_within_category([hub, seed], NOW)
        self.assertEqual(hub["hidden_reason"], "duplicate_same_category")
        self.assertFalse(seed.get("hidden_reason"))

    def test_near_name_same_host_not_merged(self):
        a = row("fellowship", "f-1", "https://research.google/phd-fellowship", "Google PhD Fellowship")
        b = row("fellowship", "f-2", "https://research.google/research-fellowship", "Google Research Fellowship")
        self.assertEqual(core.dedupe_within_category([a, b], NOW), 0)

    def test_level_variants_on_shared_page_not_merged(self):
        url = "https://scholarships.gov.in/All-Scholarships"
        a = row("scholarship", "s-1", url, "AICTE Pragati Scholarship (Technical Degree)")
        b = row("scholarship", "s-2", url, "AICTE Pragati Scholarship (Technical Diploma)")
        self.assertEqual(core.dedupe_within_category([a, b], NOW), 0)

    def test_sibling_hosts_group_across_categories(self):
        a = row("fellowship", "f-mlh", "https://fellowship.mlh.io/", "MLH Fellowship")
        b = row("grant", "g-mlh", "https://fellowship.mlh.com/", "MLH Fellowship")
        self.assertEqual(len(owners_mod.find_groups([a, b])), 1)

    def test_different_host_same_name_different_organiser_not_grouped(self):
        a = row("fellowship", "f-gem", "https://gemfellowship.org/", "GEM Fellowship Program")
        a["organizer"] = "GEM Consortium"
        b = row("grant", "g-gem", "https://gem.coop/fellowship", "Gem Fellowship")
        b["organizer"] = "gem.coop"
        self.assertEqual(owners_mod.find_groups([a, b]), [])

    def test_different_host_same_organiser_strong_name_grouped(self):
        a = row("fellowship", "f-1", "https://a.example.org/x", "Aga Khan International Scholarship Programme")
        b = row("scholarship", "s-1", "https://b.example.com/y", "Aga Khan International Scholarship")
        a["organizer"] = b["organizer"] = "Aga Khan Foundation"
        self.assertEqual(len(owners_mod.find_groups([a, b])), 1)


if __name__ == "__main__":
    unittest.main()
