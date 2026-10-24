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


class QaRoundTwoGateTests(unittest.TestCase):
    def test_table_and_blob_titles_dropped(self):
        for t in ("| Rolling (FAFSA ASAP) | | \u2705 **[OPEN]** | Nevada | Governor Guinn Millennium Scholarship |",
                  "Jul 9, 2026 | --- ## Rising Freshmen & Class of 2030 Opportunities",
                  "Foo ## Bar", "A | B | C", "\u2705 Scholarship", "x" * 151):
            self.assertIsNotNone(Q.title_gate(t), t[:40])
        self.assertEqual(Q.title_gate("| a | b | Foo Scholarship"), "scrape_junk_title")
        self.assertIsNone(Q.title_gate("National Fellowship And Scholarship For Higher Education Of ST Students - Scholarship (Formally Top Class Education For Schedule Tribe Students)"))
        self.assertIsNone(Q.title_gate("Community | Fellowship"))  # a single pipe is not a table

    def test_bold_wrapped_title_is_cleaned_not_dropped(self):
        self.assertEqual(Q.clean_title("**Ethereum Protocol Fellowship**"), "Ethereum Protocol Fellowship")
        self.assertIsNone(Q.title_gate("**Ethereum Protocol Fellowship**"))
        self.assertEqual(Q.title_gate("**Ethereum** Fellowship **x**"), "scrape_junk_title")

    def test_database_forum_and_bad_hosts(self):
        for t in ("A database of ~700 funding schemes and fellowships for postdocs", "Database of fellowships",
                  "Funding schemes and travel grant opportunities for postdocs", "Community Forum | github.community",
                  "Community Forum"):
            self.assertIsNotNone(Q.title_gate(t), t)
        self.assertEqual(Q.title_gate("Some Fellowship", "https://www.ecrcentral.org/fundings"), "index_host")
        self.assertEqual(Q.title_gate("Some Fellowship", "https://github.community/t/x"), "index_host")
        self.assertIsNone(Q.title_gate("Some Fellowship", "https://example.org/x"))

    def test_senior_titles(self):
        for t in ("Burroughs Wellcome Fund Career Awards", "MIT METEOR Postdoctoral Fellowship Program",
                  "DOE Visiting Faculty Program", "Microsoft Research Faculty Fellowship Program",
                  "Helen Hay Whitney Foundation Postdoctoral Fellowship", "Marie Sk\u0142odowska-Curie Postdoctoral Fellowships",
                  "HFSP Postdoctoral Fellowships", "Early Career Awards", "HHMI Investigator Program"):
            self.assertEqual(Q.senior_gate({}, t, None, None), "senior_only", t)
        for t in ("Mitacs Accelerate", "Google PhD Fellowship", "Career Prep Program", "NSF Graduate Research Fellowship"):
            self.assertIsNone(Q.senior_gate({}, t, None, None), t)

    def test_grant_gate_organisations_and_pools(self):
        g = Q.grant_gate
        self.assertEqual(g("Amazon Research Awards", None, None, 250000), "grant_for_organisations")
        self.assertEqual(g("Simons Foundation Grants", None, "mathematical sciences", 600000), "grant_for_organisations")
        self.assertEqual(g("Kauffman Foundation Grants", None, None), "grant_for_organisations")
        self.assertEqual(g("BIRAC Calls", None, None), "grant_for_organisations")
        self.assertEqual(g("Innovate UK Smart Grants", None, "business-led innovation"), "grant_for_organisations")
        self.assertEqual(g("EIC Big Scheme", None, "ambitious companies", 30_000_000), "grant_pool_too_large")
        self.assertEqual(g("DOE SBIR/STTR", None, "small business"), "grant_for_organisations")
        self.assertEqual(g("X Grant", "Applicants must be a registered organisation.", None), "grant_for_organisations")
        self.assertEqual(g("X Grant", "Open to universities and research institutions only", None), "grant_for_organisations")
        self.assertEqual(g("X Grant", "Principal investigators may apply", None), "grant_for_organisations")
        self.assertEqual(g("X Fund", None, None, 5_000_000), "grant_pool_too_large")

    def test_grant_gate_keeps_individuals_and_students(self):
        g = Q.grant_gate
        self.assertIsNone(g("Z Fellows", "$10k for early-stage founders", None))
        self.assertIsNone(g("Big Fund", "students and organisations may apply", None, 5_000_000))
        self.assertIsNone(g("Thiel Fellowship", None, "young people who want to build new things", 250000))
        self.assertIsNone(g("Mitacs Globalink Research Award", None, "international research collaboration", 6000))
        self.assertIsNone(g("Open Philanthropy Career Development and Transition Funding", None, None))
        self.assertIsNone(g("Wikimedia Rapid Fund", None, None, 5000))

    def test_grant_gate_only_applies_to_grants_in_publisher(self):
        row = prog("g1", "Amazon Research Awards", "grant", "https://amazon.science/x")
        self.assertEqual(quality_reason(row), "grant_for_organisations")
        row2 = prog("f1", "Amazon Research Awards", "fellowship", "https://amazon.science/x")
        self.assertIsNone(quality_reason(row2))

    def test_high_school_hackathons(self):
        g = Q.hackathon_gate
        self.assertEqual(g("Redshifted Cortex - AI built by High Schoolers", "Redshifted", None), "high_school_only")
        self.assertEqual(g("Haven Princeton Game Jam - High School", "Hack Club", None), "high_school_only")
        self.assertEqual(g("ONHacks", "ONHack Organization", "High School Students who applied"), "high_school_only")
        self.assertEqual(g("Teens Hack Houston", "HackClub", None), "high_school_only")
        self.assertIsNone(g("GeauxHack 2026", "SASE-LSU", "USA Students (Highschool, Undergraduate, Graduate)"))
        self.assertIsNone(g("Sierra Hacks 2026", "CodeCatalyst", None))  # no high-school signal in our data
        self.assertIsNone(g("College Hackathon", "ACM", "High school and university students"))


class UrlDedupeTests(unittest.TestCase):
    def cand(self, pid, title, cat, url, org="x", **kw):
        row = {"category": cat, "source_kind": "official"}
        row.update(kw)
        return Q.candidate(row, pid, title, org, url)

    def test_norm_url(self):
        self.assertEqual(Q.norm_url("HTTPS://www.Example.org/Path/?a=1#x"), "example.org/path")
        self.assertEqual(Q.norm_url("http://example.org/path/"), Q.norm_url("https://www.example.org/path"))
        self.assertEqual(Q.norm_url("https://example.org/"), "")  # bare homepage never keys a merge

    def test_title_plural_and_dots_normalised(self):
        self.assertEqual(Q.norm_title("NVIDIA Graduate Fellowship(s)"), Q.norm_title("NVIDIA Graduate Fellowships"))
        self.assertEqual(Q.norm_title("IBM Ph.D. Fellowship"), Q.norm_title("IBM PhD Fellowship"))

    def test_same_url_cross_category_with_near_title(self):
        a = self.cand("a", "NVIDIA Graduate Fellowship", "fellowship", "https://www.nvidia.com/en-us/research/graduate-fellowships/", org="NVIDIA")
        b = self.cand("b", "NVIDIA Graduate Fellowships", "research", "http://nvidia.com/en-us/research/graduate-fellowships?x=1", org="research.nvidia.com")
        c = self.cand("c", "NVIDIA Graduate Fellowship Program", "scholarship", "https://nvidia.com/en-us/research/graduate-fellowships", org="nv")
        losers = Q.dedupe([a, b, c])
        self.assertEqual(len(losers), 2)
        self.assertNotIn("a", losers)

    def test_shared_listing_url_does_not_merge_distinct_schemes(self):
        url = "https://scholarships.gov.in/All-Scholarships"
        a = self.cand("a", "AICTE Saksham Scholarship Scheme", "scholarship", url, org="NSP")
        b = self.cand("b", "AICTE Pragati Scholarship Scheme", "scholarship", url, org="NSP")
        c = self.cand("c", "Pre Matric Scholarship For Students With Disabilities", "scholarship", url, org="NSP")
        d = self.cand("d", "Post Matric Scholarship For Students With Disabilities", "scholarship", url, org="NSP")
        self.assertEqual(Q.dedupe([a, b, c, d]), {})

    def test_foreign_rows_dedupe_by_url(self):
        mine = self.cand("m", "Thiel Fellowship", "grant", "https://thielfellowship.org/apply", org="a")
        foreign = self.cand("f", "Thiel Fellowship", "fellowship", "https://www.thielfellowship.org/apply/", org="b", verified=True)
        self.assertEqual(Q.dedupe([mine], [foreign]), {"m": "f"})


class MapRowCompanyTests(unittest.TestCase):
    def test_hostname_company_prefers_real_organiser(self):
        from pipeline.publish_supabase import map_row
        r = prog("h1", "Some Fellowship", organizer="cis.mpg.de", company="cis.mpg.de",
                 organizer_name="Max Planck Institute for Intelligent Systems")
        self.assertEqual(map_row(r)["company"], "Max Planck Institute for Intelligent Systems")
        r2 = prog("h2", "Some Fellowship", organizer="cis.mpg.de")
        self.assertEqual(map_row(r2)["company"], "cis.mpg.de")  # nothing better: left as is
        r3 = prog("h3", "Some Fellowship", organizer="NVIDIA", company="research.nvidia.com")
        self.assertEqual(map_row(r3)["company"], "NVIDIA")
        r4 = prog("h4", "**Ethereum Protocol Fellowship**")
        self.assertEqual(map_row(r4)["title"], "Ethereum Protocol Fellowship")


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


class SchoolLevelTitleTests(unittest.TestCase):
    def test_pre_matric_dropped(self):
        from core import serving_quality as sq
        self.assertEqual(sq.senior_gate({}, "Financial Assistance For Education To The Wards Of Beedi Workers - Pre Matric", "", ""), "school_level")
        self.assertEqual(sq.senior_gate({}, "Scholarship for Class 9 to 10 students", "", ""), "school_level")

    def test_post_matric_and_college_kept(self):
        from core import serving_quality as sq
        self.assertIsNone(sq.senior_gate({}, "Post Matric Scholarship for SC Students", "", ""))
        self.assertIsNone(sq.senior_gate({}, "Icar Post Graduate Scholarship(Pgs)", "", ""))
        self.assertIsNone(sq.senior_gate({}, "Scholarship for Class 12 pass-outs entering college", "", ""))


class GrantMaintainerTests(unittest.TestCase):
    def test_oss_maintainer_fund_kept_despite_pool(self):
        self.assertIsNone(Q.grant_gate("GitHub Secure Open Source Fund", "", "Funding for open source maintainers to improve security.", 1_250_000))

    def test_big_pool_without_individuals_dropped(self):
        self.assertEqual(Q.grant_gate("Big Science Pool", "", "Supports ambitious research.", 30_000_000), "grant_pool_too_large")


class RecoverTableTitleTests(unittest.TestCase):
    def test_recovers_programme_names(self):
        cases = {
            "| Rolling (FAFSA ASAP) | | ✅ **[OPEN]** | Nevada | Governor Guinn Millennium Scholarship | Up to $10,000":
                "Governor Guinn Millennium Scholarship",
            "| Rolling (FAFSA ASAP) | | ✅ **[OPEN]** | New York | Tuition Assistance Program (TAP) | $500–$5,665 | NY resident":
                "Tuition Assistance Program (TAP)",
            "| Jun 17, 2026 | | ✅ **[OPEN]** | Handshake | AI Fellowship Program — Deadline: Check site | Fellowship | Remote |":
                "AI Fellowship Program",
            "| Aug 9, 2026 | | ✅ **[OPEN]** | Jane Street | FOCUS — Deadline: Rolling (Sign Up to Be Notified) | Multi-Day Program (S":
                "FOCUS",
            "Oct 13, 2026 | | ✅ [OPEN] | Penn State / NASA Pennsylvania Space Grant Consortium | Undergraduate Research Internship Program | x":
                "Undergraduate Research Internship Program",
            "| Jul 5, 2026 | | ⏳ [OPENS SOON] | GitHub | Campus Expert — Deadline: Annual Window |": "Campus Expert",
        }
        for raw, want in cases.items():
            self.assertEqual(Q.recover_table_title(raw), want, raw)

    def test_noise_returns_none(self):
        for raw in ("> :warning: State aid rules change frequently. Always verify eligibility and deadlines",
                    "Jul 9, 2026 | --- ## Rising Freshmen & Class of 2030 Opportunities Opportunities open",
                    "Oct 13, 2026 | | ✅ [OPEN] | Lander U", "Gates Cambridge Scholarship"):
            self.assertIsNone(Q.recover_table_title(raw), raw)

    def test_publisher_recovers_and_keeps_stable_id(self):
        raw = "| Rolling (FAFSA ASAP) | | ✅ **[OPEN]** | Hawaii | Hawaii Promise Scholarship | Last-dollar aid | HI resident"
        r = prog("scraped-1", raw, category="scholarship")
        self.assertIsNone(quality_reason(r))
        out = build_serving([r])
        self.assertEqual(out[0]["title"], "Hawaii Promise Scholarship")
        self.assertEqual(out[0]["id"], "programme:scraped-1")
        junk = prog("scraped-2", "> :warning: State aid rules change frequently ** x |", category="scholarship")
        self.assertEqual(quality_reason(junk), "scrape_junk_title")


class GrantFellowKeepTests(unittest.TestCase):
    def test_fellowships_and_keep_ids_not_dropped(self):
        g = Q.grant_gate
        self.assertIsNone(g("eBPF Fellowship", "", "grants for organisations and institutions"))
        self.assertIsNone(g("Mozilla Foundation Fellowships and Awards", "", "supports universities"))
        self.assertIsNone(g("GitHub Fund", "", "invests in startups companies", row_id="programme:grant-github-fund"))
        for t in ("Ford Foundation Grants", "Wellcome Discovery Awards", "NSF Seed Fund (SBIR/STTR)"):
            self.assertEqual(g(t, "", ""), "grant_for_organisations", t)


class GradeRangeTitleTests(unittest.TestCase):
    def test_grades_only_dropped_college_kept(self):
        self.assertEqual(Q.senior_gate({}, "No Sweat Scholarship (Age 13+; Grades 8–12 or Homeschooled; No Essay)", "", ""), "school_level")
        self.assertIsNone(Q.senior_gate({}, "$2,000 No-Essay Scholarship (Age 16+; HS Jr/Sr or College)", "", ""))
        self.assertIsNone(Q.senior_gate({}, "Scholarship for grades 11-12 entering college", "", ""))
