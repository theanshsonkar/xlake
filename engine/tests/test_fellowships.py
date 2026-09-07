import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from categories.programme_core import is_quality_evidence
from categories.fellowships import fellowships


class TestFellowshipRegistry(unittest.TestCase):
    def test_json_registry_has_canonical_unique_seeds(self):
        with open(fellowships.SEED_PATH, encoding="utf-8") as handle:
            raw = json.load(handle)
        self.assertEqual(len(raw), 79)
        required = set(fellowships.REQUIRED_SEED_FIELDS)
        self.assertEqual({key for seed in raw for key in seed}, required)
        self.assertEqual(len({seed["source_id"] for seed in raw}), len(raw))
        self.assertEqual(len({seed["programme_id"] for seed in raw}), len(raw))
        for seed in raw:
            self.assertTrue(all(seed[field] for field in fellowships.REQUIRED_SEED_FIELDS))
            self.assertTrue(seed["official_url"].startswith("https://"))
            self.assertIsInstance(seed["allowed_path_hints"], list)

    def test_evidence_quality_rejects_css_and_bare_titles_but_accepts_prose(self):
        self.assertFalse(is_quality_evidence("fellowship-faq h3,"))
        self.assertFalse(is_quality_evidence("Fellowships."))
        self.assertTrue(is_quality_evidence("Applications for the fellowship open in September."))

    def test_non_visible_markup_is_excluded_from_evidence(self):
        seed = fellowships.SOURCE_BY_ID["fellowship-thiel"]
        html = """<html><head><style>.fellowship-faq h3, { color: red; }</style><script>Fellowships.</script></head>
        <body><h1>Thiel Fellowship</h1><p>This fellowship programme supports founders.</p></body></html>"""
        record, observation = fellowships.parse_programme(seed, html, datetime(2026, 8, 16, tzinfo=timezone.utc))
        self.assertEqual(record["official_evidence"]["official_page"]["quote"], "This fellowship programme supports founders.")
        self.assertNotIn("fellowship-faq", observation["official_evidence"]["official_page"]["quote"])

    def test_collect_reads_json_registry_without_network(self):
        calls = []
        def fake_fetch(url):
            calls.append(url)
            return "<html><body>No current application information.</body></html>"
        with tempfile.TemporaryDirectory() as directory:
            result = fellowships.collect(fetch=fake_fetch, checked_at=datetime(2026, 8, 16, tzinfo=timezone.utc), lake_path=os.path.join(directory, "lake.json"), observations_path=os.path.join(directory, "observations.json"))
        expected = [seed["official_url"] for seed in fellowships._load_seed_registry()]
        self.assertEqual(calls, expected)
        self.assertEqual(len(result["observations"]), len(expected))
        self.assertEqual(len(fellowships.FELLOWSHIP_CONFIG.source_registry), len(expected))

    def test_successful_formal_unknown_page_emits_needs_confirmation(self):
        seed = fellowships.SOURCE_BY_ID["fellowship-thiel"]
        record, observation = fellowships.parse_programme(seed, "<html><body><h1>Thiel Fellowship</h1><p>This fellowship programme supports founders.</p></body></html>", datetime(2026, 8, 16, tzinfo=timezone.utc))
        self.assertIsNotNone(record)
        self.assertTrue(record["needs_confirmation"])
        self.assertFalse(record["is_live"])
        self.assertIsNone(record["programme_status"])
        self.assertIsNone(record["opening_date"])
        self.assertIsNone(record["deadline"])
        self.assertEqual(observation["state"], "needs_confirmation")
        self.assertTrue(observation["official_evidence"]["official_page"]["quote"])

    def test_uncertain_read_preserves_existing_live_row(self):
        seed = fellowships.SOURCE_BY_ID["fellowship-thiel"]
        record, _ = fellowships.parse_programme(seed, "<html><body><h1>Thiel Fellowship</h1><p>This fellowship programme exists.</p></body></html>", datetime(2026, 8, 16, tzinfo=timezone.utc))
        old = {"record_type": "programme", "programme_id": seed["programme_id"], "official_url": seed["official_url"], "programme_status": "open", "is_live": True}
        with tempfile.TemporaryDirectory() as directory:
            lake, obs = os.path.join(directory, "lake.json"), os.path.join(directory, "obs.json")
            with open(lake, "w") as handle: json.dump([old], handle)
            rows = fellowships.merge_programmes([record], [{"official_url": seed["official_url"], "programme_id": seed["programme_id"], "result": "non_actionable", "state": "needs_confirmation"}], lake, obs)
        row = next(item for item in rows if item.get("programme_id") == seed["programme_id"])
        self.assertEqual(row["programme_status"], "open")
        self.assertTrue(row["is_live"])
    def test_closed_read_retires_existing_live_row(self):
        seed = fellowships.SOURCE_BY_ID["fellowship-thiel"]
        html = "<html><body><h1>Thiel Fellowship</h1><p>Applications are accepted from June 1 to July 1, 2026.</p></body></html>"
        record, observation = fellowships.parse_programme(seed, html, datetime(2026, 8, 16, tzinfo=timezone.utc))
        self.assertIsNone(record)
        self.assertEqual(observation["state"], "closed")
        old = {"record_type": "programme", "programme_id": seed["programme_id"], "official_url": seed["official_url"], "programme_status": "open", "is_live": True}
        with tempfile.TemporaryDirectory() as directory:
            lake, obs = os.path.join(directory, "lake.json"), os.path.join(directory, "obs.json")
            with open(lake, "w") as handle: json.dump([old], handle)
            rows = fellowships.merge_programmes([], [observation], lake, obs, now="2026-08-16T00:00:00+00:00")
        row = next(item for item in rows if item.get("programme_id") == seed["programme_id"])
        self.assertFalse(row["is_live"])
        self.assertEqual(row["went_dead_at"], "2026-08-16T00:00:00+00:00")


    def test_fellowship_fetch_checks_robots_and_retries_once(self):
        responses = [(503, "https://example.test", "", "http_503"), (200, "https://example.test", "<html>ok</html>", None)]
        with mock.patch.object(fellowships.robots, "allowed", side_effect=[(True, "ok"), (True, "ok")]) as allowed, mock.patch.object(fellowships, "_fetch_page", side_effect=responses) as fetch, mock.patch.object(fellowships.time, "sleep") as sleep:
            self.assertEqual(fellowships._fellowship_fetch("https://example.test"), ("<html>ok</html>", "https://example.test"))
        self.assertEqual(fetch.call_count, 2)
        self.assertEqual(fetch.call_args_list[0].kwargs["user_agent"], fellowships.FELLOWSHIP_BROWSER_UA)
        self.assertEqual(allowed.call_count, 2)
        sleep.assert_called_once_with(1.0)

    def test_fellowship_fetch_checks_initial_url_only_on_cross_host_redirect(self):
        with mock.patch.object(fellowships.robots, "allowed", return_value=(True, "ok")) as allowed, mock.patch.object(fellowships, "_fetch_page", return_value=(200, "https://other.example/page", "<html>ok</html>", None)) as fetch:
            self.assertEqual(fellowships._fellowship_fetch("https://example.test/start"), ("<html>ok</html>", "https://other.example/page"))
        allowed.assert_called_once_with("https://example.test/start")
        fetch.assert_called_once_with("https://example.test/start", user_agent=fellowships.FELLOWSHIP_BROWSER_UA)

    def test_fellowship_fetch_fails_closed_before_http(self):
        with mock.patch.object(fellowships.robots, "allowed", return_value=(False, "robots_disallow")), mock.patch.object(fellowships, "_fetch_page") as fetch:
            with self.assertRaisesRegex(RuntimeError, "robots_disallowed:robots_disallow"):
                fellowships._fellowship_fetch("https://example.test")
        fetch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
