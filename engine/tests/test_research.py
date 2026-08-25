import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from categories import programme_core
from categories.open_source.programmes import SOURCE_REGISTRY as OPEN_SOURCE_SOURCE_REGISTRY
from categories.research import research

ENGINE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURE = os.path.join(ENGINE_ROOT, "fixtures", "research", "mitacs.html")
CHECKED_AT = datetime(2026, 8, 21, tzinfo=timezone.utc)


class TestResearchProgrammeCategory(unittest.TestCase):
    def fixture(self):
        with open(FIXTURE) as fh:
            return fh.read()

    def test_parse_mitacs_fixture_extracts_research_record_and_evidence(self):
        seed = research.SOURCE_REGISTRY[0]
        record, observation = research.parse_programme(seed, self.fixture(), CHECKED_AT)
        self.assertEqual(observation["result"], "actionable")
        self.assertIsNotNone(record)
        self.assertEqual(record["record_type"], "programme")
        self.assertEqual(record["category"], "research")
        self.assertEqual(record["opportunity_type"], "research_programme")
        self.assertEqual(record["programme_status"], "opening_soon")
        self.assertEqual(record["deadline"], "2026-09-16")
        self.assertIn("deadline", record["official_evidence"])
        self.assertIn("application", record["official_evidence"])

    def test_registry_has_ten_worldwide_separate_seeds(self):
        self.assertEqual(len(research.SOURCE_REGISTRY), 10)
        self.assertTrue(all(seed["programme_id"].startswith("research-") for seed in research.SOURCE_REGISTRY))
        self.assertTrue(
            {seed["programme_id"] for seed in research.SOURCE_REGISTRY}.isdisjoint(
                {seed["programme_id"] for seed in OPEN_SOURCE_SOURCE_REGISTRY}
            )
        )
        self.assertTrue(
            {seed["official_url"] for seed in research.SOURCE_REGISTRY}.isdisjoint(
                {seed["official_url"] for seed in OPEN_SOURCE_SOURCE_REGISTRY}
            )
        )

    def test_merge_preserves_open_source_rows_and_adds_research(self):
        seed = research.SOURCE_REGISTRY[0]
        record, observation = research.parse_programme(seed, self.fixture(), CHECKED_AT)
        old = {
            "record_type": "programme",
            "category": "open-source-programmes",
            "programme_id": "mlh-fellowship-open-source",
            "official_url": "https://example-oss/x",
            "is_live": True,
        }
        with tempfile.TemporaryDirectory() as td:
            lake_path = os.path.join(td, "lake.json")
            observations_path = os.path.join(td, "observations.json")
            with open(lake_path, "w") as fh:
                json.dump([old], fh)
            rows = programme_core.merge_programmes(
                [record], [observation], lake_path=lake_path,
                observations_path=observations_path, now="2026-08-21T00:00:00+00:00",
            )
        oss = next(row for row in rows if row["programme_id"] == old["programme_id"])
        self.assertEqual(oss, old)
        research_row = next(row for row in rows if row["programme_id"] == seed["programme_id"])
        self.assertEqual(research_row["category"], "research")

    def test_mitacs_verification_is_valid_and_loaded(self):
        verifications = research.load_verifications(research.RESEARCH_CONFIG.verifications_path)
        self.assertEqual(len(verifications), 9)
        verification = verifications[0]
        self.assertEqual(verification["programme_id"], "research-mitacs-globalink-research-internship")
        self.assertEqual(programme_core.validate_verification(verification), (True, ""))

    def test_manual_verification_creates_research_row(self):
        verifications = research.load_verifications(research.RESEARCH_CONFIG.verifications_path)
        rows = research.apply_verifications([], verifications, CHECKED_AT)
        self.assertEqual(len(rows), 9)
        row = rows[0]
        self.assertEqual(row["programme_id"], "research-mitacs-globalink-research-internship")
        self.assertEqual(row["category"], "research")
        self.assertEqual(row["opportunity_type"], "research_programme")
        self.assertEqual(row["programme_status"], "open")
        self.assertEqual(row["deadline"], "2026-09-16")
        self.assertEqual(row["source_mechanism"], "manual-verification")


if __name__ == "__main__":
    unittest.main()
