import json
import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date, datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from categories.open_source.programmes import (
    APPLICANT_ACTION_TOKENS, SOURCE_REGISTRY, SEEDS, classify_status,
    collect, detect_applicant_windows, merge_programmes, parse_date, parse_programme,
)
from categories.programme_core import ProgrammeConfig, collect as core_collect

FIXTURES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fixtures", "programmes")
TODAY = date(2026, 8, 16)


class TestGenericProgrammePipeline(unittest.TestCase):
    def fixture(self, name):
        with open(os.path.join(FIXTURES, name)) as fh:
            return fh.read()

    def test_registry_is_data_only_and_keeps_six_seed_urls(self):
        self.assertGreaterEqual(len(SOURCE_REGISTRY), 6)
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
            else:
                self.assertIsNone(record)
        self.assertEqual(parse_programme(SEEDS[4], self.fixture("riscv.html"), datetime(2026, 8, 16, tzinfo=timezone.utc))[1]["official_evidence"]["application_window"]["quote"], "Applications open: July 15 – August 5.")
        self.assertEqual(parse_programme(SEEDS[5], self.fixture("kde.html"), datetime(2026, 8, 16, tzinfo=timezone.utc))[1]["official_evidence"]["deadline"]["quote"], "Deadline for the contributors applications 2026-01-14.")

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
            self.assertIsNone(record, phrase)
            self.assertEqual(observation["state"], "non_actionable", phrase)
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
        self.assertIsNone(record)

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


if __name__ == "__main__":
    unittest.main()
