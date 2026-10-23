import unittest

from core import serving_quality as Q
from pipeline.publish_supabase import build_serving, quality_reason


def prog(pid, title, category="fellowship", url="https://example.org/p", **kw):
    r = {"record_type": "programme", "programme_id": pid, "category": category,
         "programme_name": title, "title": title, "official_url": url, "url": url,
         "is_live": True, "organizer": kw.pop("organizer", "Example Org")}
    r.update(kw)
    return r


class TitleGateTests(unittest.TestCase):
    def test_bare_url_and_path_titles_dropped(self):
        for t in ("yashisrani.github.io/List-of-OpenSource-Programs/", "https://example.org/apply",
                  "www.example.com", "example.org/programs"):
            self.assertEqual(Q.title_gate(t), "title_is_url", t)

    def test_index_and_generic_titles_dropped(self):
        for t in ("NSF REU Overview", "Overview", "Home", "FAQ", "Opportunities", "Apply / details →",
                  "List of Open Source Programs", "Awesome Internships", "Programs list",
                  "MRSEC Undergraduate Opportunities", "Resources for Underclassmen These resources help"):
            self.assertIsNotNone(Q.title_gate(t), t)

    def test_real_titles_kept(self):
        for t in ("Google Summer of Code", "MLH Fellowship", "Outreachy", "Summer Research Opportunities Program",
                  "Summer Undergraduate Research in Engineering/Sciences", "DOE SBIR/STTR", "Awesome Foundation Grant",
                  "Linux Foundation Mentorship Program", "UKRI Future Leaders Fellowships", "Simons Foundation Grants"):
            self.assertIsNone(Q.title_gate(t), t)

    def test_github_list_urls(self):
        self.assertEqual(Q.title_gate("Open Source Programs", "https://yashisrani.github.io/List-of-OpenSource-Programs"),
                         "github_list_url")
        self.assertEqual(Q.title_gate("Programs", "https://github.com/foo/awesome-programs/blob/main/README.md"), "generic_title")
        self.assertEqual(Q.title_gate("Open Source Programs X", "https://github.com/foo/awesome-programs"), "github_list_url")
        self.assertIsNone(Q.title_gate("Rails Girls Summer of Code", "https://railsgirlssummerofcode.org/"))
        self.assertIsNone(Q.title_gate("Some Project Fellowship", "https://someproject.github.io/fellowship/"))

    def test_malformed_url_dropped(self):
        self.assertEqual(Q.title_gate("A Fellowship", "https://x.org/a-b/)**"), "malformed_url")


class SeniorGateTests(unittest.TestCase):
    def gate(self, title, elig=None, desc=None, **kw):
        return Q.senior_gate(kw, title, elig, desc)

    def test_postdoc_only_dropped(self):
        self.assertEqual(self.gate("EMBO Postdoctoral Fellowships"), "senior_only")
        self.assertEqual(self.gate("Simons Society of Fellows"), "senior_only")
        self.assertEqual(self.gate("Royal Society Dorothy Hodgkin Fellowship", None,
                                   "a first step for researchers to develop an independent research career"), "senior_only")
        self.assertEqual(self.gate("Hanna Gray", None, "supports postdoctoral scientists as they launch careers"), "senior_only")

    def test_open_to_students_kept(self):
        self.assertIsNone(self.gate("Mitacs Globalink", "Open to undergraduates, graduate students and postdocs"))
        self.assertIsNone(self.gate("PhD Fellowship", "Open to PhD students", "for doctoral students"))
        self.assertIsNone(self.gate("Swiss Government Excellence Scholarships", "Early-career researchers who hold a master's degree"))
        self.assertIsNone(self.gate("Build for Bharat Fellowship", None, "early-career design, AI and engineering talent"))
        self.assertIsNone(self.gate("Google Summer of Code"))

    def test_years_of_experience(self):
        self.assertEqual(self.gate("Leaders Program", "Applicants need at least 5 years of professional experience"),
                         "requires_3plus_years")
        self.assertEqual(self.gate("Fellows", None, "3+ years experience required"), "requires_3plus_years")
        self.assertIsNone(self.gate("Junior Fellows", "0-2 years of experience"))
        self.assertIsNone(self.gate("Apprentice", "1 year of experience preferred"))


class HackathonGateTests(unittest.TestCase):
    def test_world_hackathon_federation_matches_dropped(self):
        self.assertEqual(Q.hackathon_gate("United Arab Emirates vs Germany", "World Hackathon Federation",
                                          "UAE TEAM AND GERMANY NATIONAL TEAM"), "closed_team_match")
        self.assertEqual(Q.hackathon_gate("United Arab Emirates vs France", "World Hackathon Federation", None),
                         "closed_team_match")

    def test_other_vs_titles_kept(self):
        self.assertIsNone(Q.hackathon_gate("Humans vs AI Hackathon", "Some Club", "Open to everyone"))
        self.assertIsNone(Q.hackathon_gate("Smart India Hackathon", "MoE", None))


class DedupeTests(unittest.TestCase):
    def ids(self, rows, **kw):
        return {m["id"] for m in build_serving(rows, **kw)}

    def test_same_title_same_host_keeps_one_prefers_official_verified(self):
        a = prog("hub-mlh-1", "MLH Fellowship", "open-source-programmes", "https://fellowship.mlh.io/",
                 organizer="fellowship.mlh.io", last_checked_at="2026-10-23")
        b = prog("mlh-fellowship", "MLH Fellowship", "open-source-programmes", "https://fellowship.mlh.io/",
                 organizer="Major League Hacking", manually_verified=True, source_kind="official",
                 last_checked_at="2026-10-01")
        self.assertEqual(self.ids([a, b]), {"programme:mlh-fellowship"})
        self.assertEqual(self.ids([b, a]), {"programme:mlh-fellowship"})

    def test_newest_checked_breaks_tie(self):
        a = prog("a", "Same Prog", url="https://x.org/a", last_checked_at="2026-10-01")
        b = prog("b", "Same Prog", url="https://x.org/b", last_checked_at="2026-10-20")
        self.assertEqual(self.ids([a, b]), {"programme:b"})

    def test_same_title_different_org_kept(self):
        a = prog("a", "Summer Fellowship", url="https://one.org/", organizer="One")
        b = prog("b", "Summer Fellowship", url="https://two.org/", organizer="Two")
        self.assertEqual(self.ids([a, b]), {"programme:a", "programme:b"})

    def test_same_org_different_tld_is_same_host(self):
        a = prog("a", "MLH Fellowship", url="https://fellowship.mlh.io/", organizer="x")
        b = prog("b", "MLH Fellowship", url="https://fellowship.mlh.com/", organizer="y")
        self.assertEqual(len(self.ids([a, b])), 1)

    def test_cross_category_whole_lake_and_foreign(self):
        a = prog("a", "Boren Awards", "scholarship", "https://www.borenawards.org/")
        b = prog("b", "Boren Awards", "fellowship", "https://www.borenawards.org/")
        self.assertEqual(len(self.ids([a, b])), 1)
        # scoped run: the other category's live row is only known as `foreign`
        foreign = [Q.candidate(a, "programme:a", "Boren Awards", "Example Org", a["url"])]
        got = self.ids([b], category="fellowships", foreign=foreign)
        winner_is_a = Q._rank_cross(foreign[0]) > Q._rank_cross(
            Q.candidate(b, "programme:b", "Boren Awards", "Example Org", b["url"]))
        self.assertEqual(got, set() if winner_is_a else {"programme:b"})
        # and the scholarship run reaches the opposite (consistent) verdict
        got_a = self.ids([a], category="scholarships", foreign=[
            Q.candidate(b, "programme:b", "Boren Awards", "Example Org", b["url"])])
        self.assertEqual(len(got) + len(got_a), 1)


class BuildServingGateTests(unittest.TestCase):
    def test_bad_rows_not_served_and_reasons_reported(self):
        rows = [
            prog("ok", "Google Summer of Code", "open-source-programmes", "https://summerofcode.withgoogle.com/"),
            prog("ov", "NSF REU Overview", "research", "https://new.nsf.gov/funding/initiatives/reu"),
            prog("gh", "yashisrani.github.io/List-of-OpenSource-Programs/", "open-source-programmes",
                 "https://yashisrani.github.io/List-of-OpenSource-Programs"),
            prog("pd", "Royal Society Dorothy Hodgkin Fellowship", "fellowship", "https://royalsociety.org/x",
                 description="independent research career"),
            {"record_type": "hackathon", "hackathon_id": "https://aevsge.devpost.com/", "category": "hackathons",
             "title": "United Arab Emirates vs Germany", "organizer": "World Hackathon Federation",
             "url": "https://aevsge.devpost.com/", "is_live": True, "eligibility": "UAE TEAM AND GERMANY NATIONAL TEAM"},
        ]
        report = {}
        served = {m["id"] for m in build_serving(rows, report=report)}
        self.assertEqual(served, {"programme:ok"})
        self.assertEqual(set(report), {"programme:ov", "programme:gh", "programme:pd",
                                       "hackathon:https://aevsge.devpost.com/"})
        self.assertIsNone(quality_reason(rows[0]))

    def test_jobs_and_contributions_untouched(self):
        job = {"url": "https://x.org/j/1", "title": "Overview Engineer", "is_live": True, "is_internship": False}
        con = {"record_type": "contribution", "contribution_id": "c1", "title": "Home", "is_live": True,
               "url": "https://github.com/a/b/issues/1"}
        self.assertEqual(len(build_serving([job, con])), 2)


if __name__ == "__main__":
    unittest.main()
