import json
import json
import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch
from datetime import date, datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from categories.grants import grants
from categories.open_source import programmes as open_source_programmes
from categories.open_source.programmes import (
    APPLICANT_ACTION_TOKENS, SOURCE_REGISTRY, SEEDS, classify_status,
    collect, detect_applicant_windows, merge_programmes, parse_date, parse_programme,
)
from categories.research import research
from categories.scholarships import scholarships
from categories.programme_core import (
    ProgrammeConfig, _hop_links, _hop_page_matches_seed, _text, collect as core_collect,
    programme_title_ok, should_route_research_seed,
)

FIXTURES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fixtures", "programmes")
TODAY = date(2026, 8, 16)


class TestGenericProgrammePipeline(unittest.TestCase):
    def fixture(self, name):
        with open(os.path.join(FIXTURES, name)) as fh:
            return fh.read()

    def test_generated_programme_title_gate_rejects_junk_and_accepts_good_examples(self):
        rejected = (
            ("How to Find, Apply to, and Win a Fellowship During Your PhD or Postdoc", "https://pfforphds.com/article"),
            ("Preparing a Fellowship Application", "https://funding.yale.edu/advice/fellowship"),
            ("Finding & Applying to Fellowships", "https://gograd.org/guide/fellowships"),
            ("Writing a Research Statement for Graduate School and Fellowships", "https://h2r.cs.brown.edu/writing"),
            ("Cornell", "https://www.cs.cornell.edu/"),
            ("McKelvey School of Engineering", "https://engineering.wustl.edu/"),
            ("Hanzilla Jobs (Canada)", "https://jobs.hanzilla.co/search"),
            ("Internship At CMI", "https://cmi.example/internship"),
        )
        accepted = (
            "Citadel PhD Fellowship",
            "Graduate Fellowships for STEM Diversity (GFSD)",
            "IISER Bhopal Summer Student Research Fellowship",
            "Summer Undergraduate Research fellowship program",
            "Schlumberger Foundation Faculty for the Future Fellowship",
            "IISc Bangalore Summer Research Program",
            "Amgen Scholars Program",
            "NSF Graduate Research Fellowship Program",
            "Siebel Scholars Program",
            "Quad Fellowship",
            "Santa Fe Institute Summer Research Experience",
            "Sandia National Labs Postdoctoral Fellowships",
            "Korean American Scholarship Foundation",
            "GitHub Secure Open Source Fund",
            "Google Summer of Code",
            "Season of KDE",
            "fal Research Grants",
        )
        for title, url in rejected:
            with self.subTest(title=title):
                self.assertFalse(programme_title_ok(title, url, "fellowship")[0])
        for title in accepted:
            with self.subTest(title=title):
                self.assertTrue(programme_title_ok(title, "https://official.example/program", "fellowship")[0])
        self.assertFalse(programme_title_ok("Research Foundation", "https://official.example/program", "fellowship")[0])
        self.assertTrue(programme_title_ok("Research Foundation", "https://official.example/program", "scholarship")[0])

    def test_category_aware_programme_title_nouns(self):
        for title in ("Y Combinator Startup School", "AWS Activate"):
            with self.subTest(category="startup-founder", title=title):
                self.assertTrue(programme_title_ok(title, "https://official.example/program", "startup-founder")[0])
                self.assertTrue(programme_title_ok(title, "https://official.example/program", "startup_founder")[0])
        for title in ("Google Developer Groups", "Microsoft Learn Student Ambassadors"):
            with self.subTest(category="community", title=title):
                self.assertTrue(programme_title_ok(title, "https://official.example/program", "community")[0])
        self.assertFalse(programme_title_ok("AWS Activate", "https://official.example/program", "grants")[0])
        self.assertFalse(programme_title_ok("Microsoft Learn Student Ambassadors", "https://official.example/program", "fellowships")[0])

    def test_generated_programme_title_gate_rejects_stale_years(self):
        self.assertEqual(
            programme_title_ok(
                "Summer Research Fellowship Programme 2021",
                "https://official.example/program",
                "fellowship",
            ),
            (False, "stale_year"),
        )
        self.assertTrue(
            programme_title_ok(
                "Summer Research Fellowship Programme 2026",
                "https://official.example/program",
                "fellowship",
            )[0]
        )
        self.assertTrue(
            programme_title_ok(
                "Summer Research Fellowship Programme 2025-2026",
                "https://official.example/program",
                "fellowship",
            )[0]
        )

    def test_registry_is_data_only_and_keeps_six_seed_urls(self):
        self.assertGreaterEqual(len(SOURCE_REGISTRY), 6)

    def test_parser_accepts_boolean_aria_hidden_attribute(self):
        html = (
            "<html><body><div aria-hidden></div>"
            "<h1>Open Source Fellowship</h1>"
            "<p>Official fellowship programme information.</p>"
            "</body></html>"
        )
        record, observation = parse_programme(
            SEEDS[0], html, datetime(2026, 8, 16, tzinfo=timezone.utc)
        )
        self.assertIsNotNone(record)
        self.assertEqual(observation["state"], "needs_confirmation")
        seed_urls = {
            "https://fellowship.mlh.io/programs/open-source",
            "https://summerofcode.withgoogle.com/",
            "https://www.outreachy.org/",
            "https://lfx.linuxfoundation.org/tools/mentorship",
            "https://riscv.org/community/mentorship/",
            "https://season.kde.org/",
        }
        self.assertTrue(seed_urls <= {s["official_url"] for s in SOURCE_REGISTRY})
        allowed = {"source_id", "programme_id", "programme_name", "organizer", "official_url", "allowed_path_hints", "check_cadence"}
        for source in SOURCE_REGISTRY:
            self.assertTrue(set(source) <= allowed)
            self.assertFalse(any(callable(value) for value in source.values()))
            self.assertTrue(source["source_id"])
            self.assertTrue(source["organizer"])
            self.assertTrue(source["official_url"])

    def test_visible_text_does_not_stick_after_void_embed(self):
        text, _ = _text(
            "<head><embed src='video'><meta charset='utf-8'><link rel='stylesheet'></head>"
            "<body><p>Visible programme information.</p></body>"
        )
        self.assertIn("Visible programme information.", text)

    def test_visible_text_keeps_explicit_hidden_content_hidden(self):
        text, _ = _text(
            "<div hidden>secret hidden text</div>"
            "<div aria-hidden='true'>secret aria text</div>"

            "<p>Visible programme information.</p>"
        )
        self.assertNotIn("secret hidden text", text)
        self.assertNotIn("secret aria text", text)
        self.assertIn("Visible programme information.", text)

    def test_academic_internship_missing_noun_routes_to_research_registry(self):
        cases = (
            ("MITACS Globalink", "https://www.mitacs.ca/program", True),
            ("IIT Ropar Summer Internship", "https://onlineportal.iitrpr.ac.in/intern", True),
            ("UX Research Internship, Red Hat", "https://us-redhat.icims.com/jobs/1", False),
            ("Allen Institute for AI, Research and Engineering Internships", "https://allenai.org/internships", False),
        )
        for title, url, expected in cases:
            with self.subTest(title=title):
                ok, reason = programme_title_ok(title, url, "fellowship")
                self.assertFalse(ok)
                self.assertEqual(
                    should_route_research_seed(
                        {"programme_name": title, "official_url": url}, "fellowship", reason,
                    ),
                    expected,
                )

        seed = {
            "source_id": "hub-fellowships-test",
            "programme_id": "fellowships-hub-test",
            "programme_name": "MITACS Globalink",
            "organizer": "mitacs.ca",
            "official_url": "https://www.mitacs.ca/program",
            "allowed_path_hints": ["program"],
            "check_cadence": "monthly",
        }
        config = ProgrammeConfig(
            category="fellowship", opportunity_type="fellowship", source_registry=(seed,),
            observations_path="", verifications_path="", needs_confirmation_floor=True,
        )
        with tempfile.TemporaryDirectory() as td, patch.dict(
            os.environ, {"XLAKE_GENERATED_SEEDS_DIR": td}, clear=False,
        ):
            result = core_collect(
                config, fetch=lambda _url: "should not fetch",
                lake_path=os.path.join(td, "lake.json"),
                observations_path=os.path.join(td, "observations.json"),
            )
            with open(os.path.join(td, "research.json"), encoding="utf-8") as handle:
                routed = json.load(handle)
        self.assertEqual(result["routed_research"], 1)
        self.assertEqual(len(routed), 1)
        self.assertEqual(routed[0]["official_url"], seed["official_url"])

    def test_visible_text_closes_omitted_head_at_body(self):
        text, _ = _text(
            "<html><head><meta charset='utf-8'><title>Title</title>"
            "<body><p>Visible programme information.</p></body></html>"
        )
        self.assertIn("Visible programme information.", text)

    def test_visible_text_excludes_script_style_and_unclosed_iframe(self):
        text, _ = _text(
            "<script>script secret</script><style>.secret { display: none }</style>"
            "<iframe>iframe secret<p>also hidden</p>"
            "<p>Visible programme information.</p>"
        )
        self.assertNotIn("script secret", text)
        self.assertNotIn("secret", text)
        self.assertNotIn("also hidden", text)
        self.assertNotIn("Visible programme information.", text)

    def test_date_parser_supports_iso_months_ranges_and_year_inheritance(self):
        self.assertEqual(parse_date("2026-01-14")["start"], date(2026, 1, 14))
        self.assertEqual(parse_date("September 15, 2026")["start"], date(2026, 9, 15))
        self.assertEqual(parse_date("July 15 – August 5", 2026)["end"], date(2026, 8, 5))
        self.assertEqual(parse_date("May 28 to June 30, 2026")["start"], date(2026, 5, 28))
        spanning = parse_date("August 1 – August 31", 2026)
        self.assertLess(spanning["start"], TODAY)
        self.assertLess(TODAY, spanning["end"])
        self.assertEqual(classify_status("applications open", [spanning], TODAY, True, None), "open")
        self.assertIsNone(parse_date("early August to mid August", 2026))

    def test_window_detection_rejects_organizer_and_accepts_applicant_events(self):
        text = "Fall 2026 Session. Applications open: July 15 – August 5. Accepting proposals for mentorships May 28 – June 30."
        windows = detect_applicant_windows(text)
        self.assertEqual(len(windows), 1)
        self.assertEqual(windows[0]["start"], date(2026, 7, 15))
        self.assertNotIn("proposals", windows[0]["quote"].lower())
        self.assertEqual(detect_applicant_windows("Accepting proposals for mentorships May 28 – June 30, 2026."), [])

    def test_status_boundaries_and_rolling_requirements(self):
        self.assertEqual(classify_status("applications open", [{"start": TODAY, "end": TODAY, "exact": True}], TODAY, True, None), "open")
        self.assertEqual(classify_status("applications open", [{"start": date(2026, 9, 1), "end": date(2026, 9, 15), "exact": True}], TODAY, True, None), "opening_soon")
        self.assertEqual(classify_status("application deadline", [{"start": date(2026, 7, 1), "end": date(2026, 8, 5), "exact": True}], TODAY, True, None), "closed")
        self.assertEqual(classify_status("applications open", [{"start": date(2026, 9, 1), "end": date(2026, 9, 15), "exact": False}], TODAY, True, None), "non_actionable")
        self.assertEqual(classify_status("processed on a rolling basis", [], TODAY, True, "https://example.test/apply"), "rolling")
        self.assertEqual(classify_status("processed on a rolling basis", [], TODAY, True, None), "non_actionable")

    def test_all_six_fixture_contract_outcomes(self):
        expected = ["actionable", "non_actionable", "non_actionable", "non_actionable", "non_actionable", "non_actionable"]
        fixtures = ["mlh.html", "gsoc.html", "outreachy.html", "lfx.html", "riscv.html", "kde.html"]
        for seed, fixture, result in zip(SEEDS, fixtures, expected):
            record, observation = parse_programme(seed, self.fixture(fixture), datetime(2026, 8, 16, tzinfo=timezone.utc))
            self.assertEqual(observation["result"], result, seed["source_id"])
            if fixture in ("riscv.html", "kde.html"):
                self.assertEqual(observation["state"], "closed")
            if result == "actionable":
                self.assertIsNotNone(record)
                self.assertEqual(record["programme_status"], "rolling")
                self.assertEqual(record["application_url"], "https://fellowship.mlh.io/apply")
                for field in ("programme_status", "application", "funding", "location", "eligibility"):
                    self.assertTrue(record["official_evidence"][field])
            elif fixture in ("gsoc.html", "outreachy.html", "lfx.html"):
                self.assertIsNotNone(record)
                self.assertTrue(record["needs_confirmation"])
                self.assertFalse(record["is_live"])
                self.assertIsNone(record["programme_status"])
                self.assertIsNone(record["deadline"])
                self.assertEqual(record["official_url"], seed["official_url"])
            else:
                self.assertIsNone(record)
        self.assertEqual(parse_programme(SEEDS[4], self.fixture("riscv.html"), datetime(2026, 8, 16, tzinfo=timezone.utc))[1]["official_evidence"]["application_window"]["quote"], "Applications open: July 15 – August 5.")
        self.assertEqual(parse_programme(SEEDS[5], self.fixture("kde.html"), datetime(2026, 8, 16, tzinfo=timezone.utc))[1]["official_evidence"]["deadline"]["quote"], "Deadline for the contributors applications 2026-01-14.")

    def test_formal_unknown_pages_emit_needs_confirmation_for_all_categories(self):
        categories = (
            ("research", research),
            ("scholarships", scholarships),
            ("grants", grants),
            ("open_source", open_source_programmes),
        )
        checked = datetime(2026, 8, 16, tzinfo=timezone.utc)
        for category, module in categories:
            with self.subTest(category=category):
                seed = module.SOURCE_REGISTRY[0]

                def fake_fetch(url):
                    self.assertEqual(url, seed["official_url"])
                    return (
                        "<html><body><h1>{}</h1><p>This official programme page provides information.</p></body></html>".format(seed["programme_name"]),
                        url,
                    )

                html, final_url = fake_fetch(seed["official_url"])
                record, observation = module.parse_programme(seed, html, checked, final_url)
                self.assertIsNotNone(record)
                self.assertTrue(record["needs_confirmation"])
                self.assertIsNone(record["programme_status"])
                self.assertIsNone(record["deadline"])
                self.assertFalse(record["is_live"])
                self.assertEqual(record["official_url"], seed["official_url"])
                self.assertEqual(observation["state"], "needs_confirmation")

    def test_deadline_cues_extract_applicant_dates_and_reject_exclusions(self):
        seed = SEEDS[0]
        checked = datetime(2026, 8, 16, tzinfo=timezone.utc)
        cases = (
            ("Applicant deadlines October 16, 2026 by 8:00 p.m. Eastern time", "2026-10-16"),
            ("next cutoff date - hard deadline: Friday 22 January 2027, 14:00 CET", "2027-01-22"),
            ("Nominations due September 10, 2026, 11:59pm (-7 GMT) No Late Nominations Accepted", "2026-09-10"),
            ("Student applications are due November 13, 2026.* Recommendation letters are due December 1, 2026.*", "2026-11-13"),
            ("Applications Close Applications closed at 12:00pm ET on September 25.", "2026-09-25"),
            ("The application closes on October 6, 2026, at 1 pm, Pacific Time.", "2026-10-06"),
        )
        for phrase, expected in cases:
            with self.subTest(phrase=phrase):
                context = "2026 fellowship application. " if phrase.startswith("Applications Close") else "fellowship application. "
                html = "<html><body><h1>{}</h1><p>{}{}</p></body></html>".format(seed["programme_name"], context, phrase)
                record, _ = parse_programme(seed, html, checked)
                self.assertIsNotNone(record)
                self.assertEqual(record["deadline"], expected)

        negative_cases = (
            "Recommendation letters are due December 1, 2026.",
            "mentoring organization sign-up opens February 26, 2026 at 4 pm UTC",
            "Recommendation letter deadline is Thursday, December 3, 2026 at noon ET",
            "We welcome applications on a rolling basis.",
            "deadline (September 19)",
        )
        for phrase in negative_cases:
            with self.subTest(phrase=phrase):
                link = '<a href="/apply">Apply</a>' if "rolling basis" in phrase else ""
                html = "<html><body><h1>{}</h1><p>fellowship application. {} {}</p></body></html>".format(seed["programme_name"], phrase, link)
                record, _ = parse_programme(seed, html, checked)
                if "rolling basis" in phrase:
                    self.assertIsNotNone(record)
                    self.assertEqual(record["programme_status"], "rolling")
                else:
                    self.assertIsNotNone(record)
                    self.assertIsNone(record["deadline"])

    def test_lexical_closed_and_future_opening_statuses(self):
        seed = SEEDS[2]
        checked = datetime(2026, 8, 16, tzinfo=timezone.utc)
        record, observation = parse_programme(
            seed, "<html><body><h1>Outreachy Fellowship</h1><p>Applications for the 2026 Fellowship are now closed.</p></body></html>", checked)
        self.assertIsNone(record)
        self.assertEqual(observation["state"], "closed")
        self.assertEqual(observation["official_evidence"]["programme_status"]["quote"], "Applications for the 2026 Fellowship are now closed.")
        for phrase in ("Applications open in September 2026.", "Applications will open soon.", "Check back for fellowship applications."):
            record, opening = parse_programme(seed, "<html><body><h1>Outreachy Fellowship</h1><p>{}</p></body></html>".format(phrase), checked)
            self.assertIsNotNone(record, phrase)
            self.assertEqual(record["programme_status"], "opening_soon")
            self.assertIsNone(record["opening_date"])
            self.assertEqual(record["official_evidence"]["programme_status"]["quote"], phrase)

    def test_generic_closed_requires_application_context(self):
        seed = SEEDS[2]
        checked = datetime(2026, 8, 16, tzinfo=timezone.utc)
        for phrase in ("The fellowship office is now closed.", "The programme is now closed for maintenance."):
            record, observation = parse_programme(
                seed, "<html><body><h1>Outreachy Fellowship</h1><p>{}</p></body></html>".format(phrase), checked)
            self.assertIsNotNone(record, phrase)
            self.assertTrue(record["needs_confirmation"], phrase)
            self.assertFalse(record["is_live"], phrase)
            self.assertIsNone(record["programme_status"], phrase)
            self.assertEqual(observation["state"], "needs_confirmation", phrase)
            self.assertNotIn("programme_status", observation.get("official_evidence", {}), phrase)

    def test_collect_logs_one_line_per_seed_and_summary(self):
        seeds = tuple(SEEDS[:3])
        config = ProgrammeConfig(
            category="programme", opportunity_type="programme", source_registry=seeds,
            observations_path="", verifications_path="",
        )

        def fake_fetch(url):
            if url == seeds[1]["official_url"]:
                raise RuntimeError("HTTP Error 403")
            if url == seeds[2]["official_url"]:
                return ""
            return "<html><body><p>Programme information.</p></body></html>", "https://final.example/page"

        with tempfile.TemporaryDirectory() as td:
            captured = io.StringIO()
            with redirect_stdout(captured):
                result = core_collect(
                    config, fetch=fake_fetch, checked_at=datetime(2026, 8, 16, tzinfo=timezone.utc),
                    lake_path=os.path.join(td, "lake.json"), observations_path=os.path.join(td, "observations.json"),
                )
        lines = [line for line in captured.getvalue().splitlines() if "programme_fetch seed=" in line]
        self.assertEqual(len(lines), len(seeds))
        self.assertIn("url=https://final.example/page outcome=ok state=non_actionable", lines[0])
        self.assertIn("outcome=http_403", lines[1])
        self.assertIn("outcome=empty", lines[2])
        summary = next(line for line in captured.getvalue().splitlines() if "programme_fetch_summary" in line)
        self.assertIn("total=3 successes=1", summary)
        self.assertIn("empty=1", summary)
        self.assertIn("http_403=1", summary)
        self.assertEqual(len(result["observations"]), len(seeds))

    def test_collect_treats_request_cap_as_capped_skip(self):
        seed = SEEDS[0]
        config = ProgrammeConfig(
            category="startup-founder", opportunity_type="programme", source_registry=(seed,),
            observations_path="", verifications_path="",
        )

        def capped_fetch(_url):
            raise RuntimeError("HTTP request cap of 150 reached")

        with tempfile.TemporaryDirectory() as td:
            captured = io.StringIO()
            with redirect_stdout(captured):
                core_collect(
                    config, fetch=capped_fetch,
                    checked_at=datetime(2026, 8, 16, tzinfo=timezone.utc),
                    lake_path=os.path.join(td, "lake.json"),
                    observations_path=os.path.join(td, "observations.json"),
                )
        summary = next(line for line in captured.getvalue().splitlines() if "programme_fetch_summary" in line)
        self.assertIn("capped=1", summary)
        self.assertNotIn("exception[RuntimeError]", summary)

    def test_evidence_prefers_application_sentence_over_earlier_generic_prose(self):
        seed = SEEDS[2]
        html = "<html><body><h1>Outreachy Fellowship</h1><p>This fellowship supports contributors.</p><p>Applications are closed for 2026.</p></body></html>"
        _, observation = parse_programme(seed, html, datetime(2026, 8, 16, tzinfo=timezone.utc))
        self.assertEqual(observation["official_evidence"]["programme_status"]["quote"], "Applications are closed for 2026.")

        checked = datetime(2026, 8, 16, tzinfo=timezone.utc)
        record, observation = parse_programme(SEEDS[2], self.fixture("outreachy-actionable.html"), checked)
        self.assertEqual(observation["result"], "actionable")
        self.assertIsNotNone(record)
        self.assertEqual(record["programme_status"], "opening_soon")
        self.assertEqual(record["opening_date"], "2026-09-15")
        self.assertEqual(record["official_evidence"]["programme_status"]["quote"], "Applications open on September 15, 2026.")
        self.assertIsNone(record["application_url"])
        self.assertEqual(record["official_url"], SEEDS[2]["official_url"])

        record, observation = parse_programme(SEEDS[2], self.fixture("past-deadline.html"), checked)
        self.assertIsNone(record)
        self.assertEqual(observation["state"], "closed")

        record, observation = parse_programme(SEEDS[2], self.fixture("sparse-actionable.html"), checked)
        self.assertIsNotNone(record)
        self.assertEqual(record["funding"], "not_stated")
        self.assertEqual(record["international_eligibility"], "needs_confirmation")
        self.assertEqual(record["official_evidence"]["funding"], {})
        self.assertEqual(record["official_evidence"]["international_eligibility"], {})

        record, observation = parse_programme(SEEDS[2], self.fixture("formal-token-missing.html"), checked)
        self.assertIsNone(record)
        self.assertEqual(observation["result"], "non_actionable")

    def test_failed_parser_read_does_not_deactivate_prior_row(self):
        old = {"record_type": "programme", "programme_id": SEEDS[0]["programme_id"], "official_url": SEEDS[0]["official_url"], "is_live": True}
        with tempfile.TemporaryDirectory() as td:
            lake, obs = os.path.join(td, "lake.json"), os.path.join(td, "obs.json")
            with open(lake, "w") as fh:
                json.dump([old], fh)
            def failed_fetch(_url):
                raise RuntimeError("fixture parser failure")
            result = collect(
                fetch=failed_fetch, checked_at=datetime(2026, 8, 16, tzinfo=timezone.utc),
                lake_path=lake, observations_path=obs)
            self.assertEqual(len(result["records"]), 0)
            self.assertTrue(all(item["state"] == "failed" for item in result["observations"]))
            with open(lake) as fh:
                self.assertTrue(json.load(fh)[0]["is_live"])

    def test_absolute_apply_url_is_restricted_to_seed_or_final_origin(self):
        html = self.fixture("mlh.html").replace('href="https://fellowship.mlh.io/apply"', 'href="/apply"')
        record, _ = parse_programme(SEEDS[0], html, final_url="https://fellowship.mlh.io/programs/open-source/")
        self.assertEqual(record["application_url"], "https://fellowship.mlh.io/apply")
        external = self.fixture("mlh.html").replace('href="https://fellowship.mlh.io/apply"', 'href="https://evil.example/apply"')
        record, _ = parse_programme(SEEDS[0], external)
        self.assertIsNotNone(record)
        self.assertIsNone(record["application_url"])
        self.assertTrue(record["needs_confirmation"])

    def test_merge_preserves_jobs_and_source_scoped_liveness(self):
        job = {"record_type": "job", "url": "https://jobs.example/1", "custom": {"x": 1}}
        first = {"record_type": "programme", "programme_id": "old", "official_url": SEEDS[0]["official_url"], "is_live": True}
        second = {"record_type": "programme", "programme_id": "other", "official_url": "https://other.example", "is_live": True}
        with tempfile.TemporaryDirectory() as td:
            lake, obs = os.path.join(td, "lake.json"), os.path.join(td, "obs.json")
            with open(lake, "w") as fh: json.dump([job, first, second], fh)
            rows = merge_programmes([], [{"official_url": first["official_url"], "programme_id": "old", "result": "non_actionable"}], lake, obs)
            self.assertEqual(next(r for r in rows if r["record_type"] == "job")["custom"], {"x": 1})
            rows = {r["programme_id"]: r for r in rows if r.get("record_type") == "programme"}
            self.assertFalse(rows["old"]["is_live"])
            self.assertTrue(rows["other"]["is_live"])

    def test_failed_read_retention_and_malformed_lake_fail_closed(self):
        old = {"record_type": "programme", "programme_id": "old", "official_url": SEEDS[0]["official_url"], "is_live": True}
        with tempfile.TemporaryDirectory() as td:
            lake, obs = os.path.join(td, "lake.json"), os.path.join(td, "obs.json")
            with open(lake, "w") as fh: json.dump([old], fh)
            merge_programmes([], [{"official_url": old["official_url"], "result": "failed"}], lake, obs)
            with open(lake) as fh: self.assertTrue(json.load(fh)[0]["is_live"])
            with open(lake, "w") as fh: fh.write("not valid json")
            with self.assertRaises(json.JSONDecodeError): merge_programmes([], [], lake, obs)
            with open(lake) as fh: self.assertEqual(fh.read(), "not valid json")
            with open(lake, "w") as fh: json.dump({"records": []}, fh)
            with self.assertRaises(ValueError): merge_programmes([], [], lake, obs)
            with open(lake) as fh: self.assertEqual(json.load(fh), {"records": []})


    def _run_identity_hop(self, seed, hop_url, hop_html):
        first_html = (
            "<h1>{}</h1><p>Official programme information.</p>"
            "<a href='{}'>Apply</a>"
        ).format(seed["programme_name"], hop_url.replace("https://example.test", ""))
        config = ProgrammeConfig(
            category="test", opportunity_type="test", source_registry=(seed,),
            observations_path="", verifications_path="", needs_confirmation_floor=True,
        )

        def fake_fetch(url):
            if url == seed["official_url"]:
                return first_html, url
            if url == hop_url:
                return hop_html, url
            raise AssertionError(url)

        with tempfile.TemporaryDirectory() as td, patch(
                "categories.programme_core.robots.allowed", return_value=(True, "ok")):
            return core_collect(
                config, fetch=fake_fetch,
                checked_at=datetime(2026, 8, 16, tzinfo=timezone.utc),
                lake_path=os.path.join(td, "lake.json"),
                observations_path=os.path.join(td, "observations.json"),
            )

    def test_second_hop_different_programme_date_is_not_promoted(self):
        seed = dict(SEEDS[0], programme_name="Alpha Beta Fellowship", official_url="https://example.test/programme")
        hop_url = "https://example.test/how-to-apply"
        result = self._run_identity_hop(
            seed, hop_url,
            "<h1>Gamma Delta Fellowship</h1><p>Applications are due January 14, 2026.</p>",
        )
        record = result["records"][0]
        self.assertIsNone(record["programme_status"])
        self.assertIsNone(record["deadline"])
        self.assertTrue(record["needs_confirmation"])
        self.assertEqual(record["official_url"], seed["official_url"])
        self.assertNotIn("second-hop", result["observations"][0]["reason"])

    def test_second_hop_matching_programme_name_is_promoted(self):
        seed = dict(SEEDS[0], programme_name="Alpha Beta Fellowship", official_url="https://example.test/programme")
        hop_url = "https://example.test/how-to-apply"
        result = self._run_identity_hop(
            seed, hop_url,
            "<h1>Alpha Beta Fellowship</h1><p>Applications are due October 6, 2026.</p>",
        )
        record = result["records"][0]
        self.assertEqual(record["deadline"], "2026-10-06")
        self.assertFalse(record["needs_confirmation"])
        self.assertIn("second-hop", result["observations"][0]["reason"])

    def test_second_hop_seed_path_prefix_is_promoted_without_name(self):
        seed = dict(SEEDS[0], programme_name="Alpha Beta Fellowship", official_url="https://example.test/programme")
        hop_url = "https://example.test/programme/apply"
        result = self._run_identity_hop(
            seed, hop_url,
            "<h1>Fellowship programme</h1><p>Applications are due October 6, 2026.</p>",
        )
        self.assertEqual(result["records"][0]["deadline"], "2026-10-06")
        self.assertIn("second-hop", result["observations"][0]["reason"])

    def test_second_hop_root_seed_path_requires_name(self):
        seed = dict(SEEDS[0], programme_name="Alpha Beta Fellowship", official_url="https://example.test/")
        hop_url = "https://example.test/apply"
        result = self._run_identity_hop(
            seed, hop_url,
            "<h1>Gamma Delta Fellowship</h1><p>Applications are due October 6, 2026.</p>",
        )
        record = result["records"][0]
        self.assertIsNone(record["deadline"])
        self.assertTrue(record["needs_confirmation"])
        self.assertNotIn("second-hop", result["observations"][0]["reason"])

    def test_hop_page_matcher_tokens_whole_words_stopwords_and_paths(self):
        seed = {"programme_name": "Alpha Beta Fellowship", "official_url": "https://example.test/programme"}
        self.assertTrue(_hop_page_matches_seed(seed, "https://other.test/x", "Alpha beta fellowship details"))
        self.assertFalse(_hop_page_matches_seed(seed, "https://other.test/x", "Alphabet beta fellowship details"))
        self.assertTrue(_hop_page_matches_seed(seed, "https://example.test/programme/updates", "No programme name"))
        self.assertFalse(_hop_page_matches_seed(seed, "https://example.test/programmes/updates", "No programme name"))
        stopword_seed = {"programme_name": "The Fellowship", "official_url": "https://example.test/programme"}
        self.assertTrue(_hop_page_matches_seed(stopword_seed, "https://other.test/x", "The fellowship opportunity"))
        self.assertFalse(_hop_page_matches_seed(stopword_seed, "https://other.test/x", "A scholarship opportunity"))


    def _hop_config(self, seeds):
        return ProgrammeConfig(
            category="test", opportunity_type="test", source_registry=tuple(seeds),
            observations_path="", verifications_path="", needs_confirmation_floor=True,
        )

    def _run_hop_collect(self, seeds, fake_fetch):
        with tempfile.TemporaryDirectory() as td:
            return core_collect(
                self._hop_config(seeds), fetch=fake_fetch,
                checked_at=datetime(2026, 8, 16, tzinfo=timezone.utc),
                lake_path=os.path.join(td, "lake.json"),
                observations_path=os.path.join(td, "observations.json"),
            )

    def test_second_hop_promotes_dated_deadline_and_keeps_seed_url(self):
        seed = dict(SEEDS[0], official_url="https://example.test/programme")
        hop_url = "https://example.test/how-to-apply"
        calls = []

        def fake_fetch(url):
            calls.append(url)
            if url == seed["official_url"]:
                return "<h1>Fellowship programme</h1><p>This official programme page provides information.</p><a href='/how-to-apply'>How to apply</a>", url
            if url == hop_url:
                return "<h1>MLH Fellowship Open Source Track</h1><p>Applications are due October 6, 2026.</p>", url
            raise AssertionError(url)

        with patch("categories.programme_core.robots.allowed", return_value=(True, "ok")):
            result = self._run_hop_collect((seed,), fake_fetch)
        record = result["records"][0]
        self.assertEqual(record["deadline"], "2026-10-06")
        self.assertEqual(record["official_url"], seed["official_url"])
        self.assertEqual(record["official_evidence"]["deadline"]["url"], hop_url)
        self.assertFalse(record["needs_confirmation"])
        self.assertIn("second-hop", result["observations"][0]["reason"])
        self.assertEqual(calls, [seed["official_url"], hop_url])

    def test_second_hop_rejects_other_host(self):
        seed = dict(SEEDS[0], official_url="https://example.test/programme")
        calls = []

        def fake_fetch(url):
            calls.append(url)
            if url == seed["official_url"]:
                return "<h1>Fellowship programme</h1><p>Official programme information.</p><a href='https://other.test/how-to-apply'>Apply</a>", url
            raise AssertionError(url)

        with patch("categories.programme_core.robots.allowed", return_value=(True, "ok")):
            result = self._run_hop_collect((seed,), fake_fetch)
        self.assertEqual(calls, [seed["official_url"]])
        self.assertTrue(result["records"][0]["needs_confirmation"])

    def test_second_hop_rejects_subdomain(self):
        seed = dict(SEEDS[0], official_url="https://example.test/programme")
        calls = []

        def fake_fetch(url):
            calls.append(url)
            if url == seed["official_url"]:
                return "<h1>Fellowship programme</h1><p>Official programme information.</p><a href='https://apply.example.test/how-to-apply'>Apply</a>", url
            raise AssertionError(url)

        with patch("categories.programme_core.robots.allowed", return_value=(True, "ok")):
            result = self._run_hop_collect((seed,), fake_fetch)
        self.assertEqual(calls, [seed["official_url"]])
        self.assertTrue(result["records"][0]["needs_confirmation"])

    def test_second_hop_fetch_error_keeps_uncertain_result(self):
        seed = dict(SEEDS[0], official_url="https://example.test/programme")
        hop_url = "https://example.test/how-to-apply"

        def fake_fetch(url):
            if url == seed["official_url"]:
                return "<h1>Fellowship programme</h1><p>Official programme information.</p><a href='/how-to-apply'>How to apply</a>", url
            if url == hop_url:
                raise TimeoutError("hop timeout")
            raise AssertionError(url)

        with patch("categories.programme_core.robots.allowed", return_value=(True, "ok")):
            result = self._run_hop_collect((seed,), fake_fetch)
        record = result["records"][0]
        self.assertTrue(record["needs_confirmation"])
        self.assertIsNone(record["deadline"])
        self.assertNotIn("second-hop", result["observations"][0]["reason"])

    def test_second_hop_fetches_at_most_two_links_per_seed(self):
        seed = dict(SEEDS[0], official_url="https://example.test/programme")
        calls = []

        def fake_fetch(url):
            calls.append(url)
            if url == seed["official_url"]:
                return ("<h1>Fellowship programme</h1><p>Official programme information.</p>"
                        "<a href='/how-to-apply'>Apply</a><a href='/faq'>FAQ</a>"
                        "<a href='/admission'>Admission</a>"), url
            return "<h1>Fellowship programme</h1><p>Vague programme information.</p>", url

        with patch("categories.programme_core.robots.allowed", return_value=(True, "ok")):
            self._run_hop_collect((seed,), fake_fetch)
        self.assertEqual(len(calls), 3)
        self.assertEqual(calls[1:], ["https://example.test/faq", "https://example.test/admission"])
        self.assertNotIn("https://example.test/how-to-apply", calls)

    def test_second_hop_fetch_cap_is_enforced(self):
        seeds = tuple(dict(SEEDS[index], official_url="https://example.test/programme{}".format(index)) for index in range(2))
        calls = []

        def fake_fetch(url):
            calls.append(url)
            if url in {seed["official_url"] for seed in seeds}:
                return "<h1>Fellowship programme</h1><p>Official programme information.</p><a href='/how-to-apply'>Apply</a><a href='/faq'>FAQ</a>", url
            return "<h1>Fellowship programme</h1><p>Vague programme information.</p>", url

        with patch("categories.programme_core.robots.allowed", return_value=(True, "ok")), \
             patch("categories.programme_core.MAX_HOP_FETCHES", 1):
            self._run_hop_collect(seeds, fake_fetch)
        self.assertEqual(len([url for url in calls if "/programme" not in url]), 1)

    def test_hop_links_filters_origin_extensions_and_orders_shortest_path(self):
        html = ("<a href='/deep/how-to-apply'>Apply</a>"
                "<a href='/faq.pdf'>FAQ</a>"
                "<a href='https://evil.test/admission'>Admission</a>"
                "<a href='https://www.example.test/admission'>Admission</a>"
                "<a href='#dates'>Dates</a>"
                "<a href='mailto:a@example.test'>Application</a>"
                "<a href='/dates'>details</a>"
                "<a href='/x'>next-round</a>"
                "<a href='/programme'>Programme</a>")
        self.assertEqual(
            _hop_links(html, "https://example.test/programme", limit=3),
            ["https://example.test/x", "https://example.test/dates", "https://example.test/deep/how-to-apply"],
        )


    def test_merge_refreshes_existing_needs_confirmation_row_from_successful_observation(self):
        old = {
            "record_type": "programme", "programme_id": "needs-confirmation",
            "official_url": "https://example.test/programme", "is_live": False,
            "needs_confirmation": True, "last_checked_at": "2026-08-15T10:00:00+00:00",
            "custom": {"keep": True},
        }
        observation = {
            "programme_id": old["programme_id"], "official_url": old["official_url"],
            "state": "needs_confirmation", "result": "non_actionable",
            "checked_at": "2026-08-16T10:00:00+00:00",
        }
        with tempfile.TemporaryDirectory() as td:
            lake, obs = os.path.join(td, "lake.json"), os.path.join(td, "obs.json")
            with open(lake, "w") as fh:
                json.dump([old], fh)
            rows = merge_programmes([], [observation], lake, obs)
        self.assertEqual(rows[0]["last_checked_at"], observation["checked_at"])
        expected = dict(old)
        expected["last_checked_at"] = observation["checked_at"]
        self.assertEqual(rows[0], expected)

    def test_merge_does_not_refresh_existing_row_from_failed_http_observation(self):
        old = {
            "record_type": "programme", "programme_id": "failed-http",
            "official_url": "https://example.test/programme", "is_live": True,
            "last_checked_at": "2026-08-15T10:00:00+00:00",
        }
        observation = {
            "programme_id": old["programme_id"], "official_url": old["official_url"],
            "state": "failed", "result": "failed", "reason": "http error",
            "checked_at": "2026-08-16T10:00:00+00:00",
        }
        with tempfile.TemporaryDirectory() as td:
            lake, obs = os.path.join(td, "lake.json"), os.path.join(td, "obs.json")
            with open(lake, "w") as fh:
                json.dump([old], fh)
            rows = merge_programmes([], [observation], lake, obs)
        self.assertEqual(rows[0]["last_checked_at"], old["last_checked_at"])

    def test_merge_refreshes_and_deactivates_live_row_from_non_actionable_observation(self):
        old = {
            "record_type": "programme", "programme_id": "became-closed",
            "official_url": "https://example.test/programme", "is_live": True,
            "last_checked_at": "2026-08-15T10:00:00+00:00",
        }
        observation = {
            "programme_id": old["programme_id"], "official_url": old["official_url"],
            "state": "non_actionable", "result": "non_actionable",
            "checked_at": "2026-08-16T10:00:00+00:00",
        }
        now = "2026-08-16T11:00:00+00:00"
        with tempfile.TemporaryDirectory() as td:
            lake, obs = os.path.join(td, "lake.json"), os.path.join(td, "obs.json")
            with open(lake, "w") as fh:
                json.dump([old], fh)
            rows = merge_programmes([], [observation], lake, obs, now=now)
        self.assertFalse(rows[0]["is_live"])
        self.assertEqual(rows[0]["went_dead_at"], now)
        self.assertEqual(rows[0]["last_checked_at"], observation["checked_at"])

    def test_merge_does_not_lower_last_checked_at_for_older_observation(self):
        old = {
            "record_type": "programme", "programme_id": "older-check",
            "official_url": "https://example.test/programme", "is_live": True,
            "last_checked_at": "2026-08-16T10:00:00+00:00",
        }
        observation = {
            "programme_id": old["programme_id"], "official_url": old["official_url"],
            "state": "actionable", "result": "actionable",
            "checked_at": "2026-08-15T10:00:00+00:00",
        }
        with tempfile.TemporaryDirectory() as td:
            lake, obs = os.path.join(td, "lake.json"), os.path.join(td, "obs.json")
            with open(lake, "w") as fh:
                json.dump([old], fh)
            rows = merge_programmes([], [observation], lake, obs)
        self.assertEqual(rows[0]["last_checked_at"], old["last_checked_at"])

    def test_merge_does_not_create_row_for_observation_without_existing_programme(self):
        observation = {
            "programme_id": "missing", "official_url": "https://example.test/programme",
            "state": "closed", "result": "non_actionable",
            "checked_at": "2026-08-16T10:00:00+00:00",
        }
        with tempfile.TemporaryDirectory() as td:
            lake, obs = os.path.join(td, "lake.json"), os.path.join(td, "obs.json")
            rows = merge_programmes([], [observation], lake, obs)
        self.assertEqual(rows, [])


if __name__ == "__main__":
    unittest.main()
