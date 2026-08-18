import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from categories.open_source.programmes import (
    apply_verifications,
    merge_programmes,
    validate_verification,
)


class TestProgrammeManualVerifications(unittest.TestCase):
    def test_validate_rejects_asserted_status_or_deadline_without_evidence(self):
        status = {"programme_id": "status-test", "programme_status": "open", "official_evidence": {}}
        ok, reason = validate_verification(status)
        self.assertFalse(ok)
        self.assertIn("programme_status", reason)

        deadline = {
            "programme_id": "deadline-test",
            "deadline": "2026-08-31",
            "official_evidence": {"deadline": {"quote": "", "url": "https://official.example"}},
        }
        ok, reason = validate_verification(deadline)
        self.assertFalse(ok)
        self.assertIn("deadline", reason)

    def test_validate_accepts_well_formed_record(self):
        record = {
            "programme_id": "well-formed",
            "programme_status": "opening_soon",
            "opening_date": "2026-08-24",
            "official_evidence": {
                "status": {"quote": "Applications open soon", "url": "https://official.example"}
            },
        }
        self.assertEqual(validate_verification(record), (True, ""))

    def test_apply_overlays_and_sets_liveness_for_opening_and_closed(self):
        rows = [
            {"record_type": "programme", "programme_id": "outreachy", "official_evidence": {"old": {"quote": "old", "url": "https://old.example"}}, "is_live": False},
            {"record_type": "programme", "programme_id": "igalia-coding-experience", "last_checked_at": "2026-08-19T00:00:00Z", "is_live": True},
            {"record_type": "job", "url": "https://jobs.example/1"},
        ]
        verifications = [
            {
                "programme_id": "outreachy",
                "verified_at": "2026-08-18T00:00:00Z",
                "verified_by": "tester",
                "programme_status": "opening_soon",
                "opening_date": "2026-08-24",
                "remote": True,
                "official_evidence": {
                    "status": {"quote": "Applications open soon", "url": "https://official.example"},
                    "opening_date": {"quote": "Applications open soon", "url": "https://official.example"},
                },
            },
            {
                "programme_id": "igalia-coding-experience",
                "verified_at": "2026-08-18T00:00:00Z",
                "verified_by": "tester",
                "programme_status": "closed",
                "official_evidence": {"status": {"quote": "Selection is closed", "url": "https://official.example"}},
            },
        ]
        applied = apply_verifications(rows, verifications, "2026-08-18T12:00:00Z")
        outreachy = next(row for row in applied if row.get("programme_id") == "outreachy")
        igalia = next(row for row in applied if row.get("programme_id") == "igalia-coding-experience")
        self.assertTrue(outreachy["is_live"])
        self.assertTrue(outreachy["manually_verified"])
        self.assertTrue(outreachy["remote"])
        self.assertIn("old", outreachy["official_evidence"])
        self.assertFalse(igalia["is_live"])
        self.assertEqual(igalia["went_dead_at"], "2026-08-18T12:00:00Z")
        self.assertEqual(igalia["last_checked_at"], "2026-08-19T00:00:00Z")

    def test_apply_creates_missing_programme_row(self):
        verification = {
            "programme_id": "hacktoberfest",
            "verified_at": "2026-08-18T00:00:00Z",
            "verified_by": "tester",
            "programme_status": "opening_soon",
            "official_evidence": {"status": {"quote": "Applications open soon", "url": "https://hacktoberfest.com/"}},
            "opportunity_type": "community_event",
        }
        applied = apply_verifications([], [verification], "2026-08-18T12:00:00Z")
        self.assertEqual(len(applied), 1)
        row = applied[0]
        self.assertEqual(row["record_type"], "programme")
        self.assertEqual(row["programme_id"], "hacktoberfest")
        self.assertEqual(row["programme_name"], "Hacktoberfest")
        self.assertEqual(row["opportunity_type"], "community_event")
        self.assertTrue(row["is_live"])
        self.assertEqual(row["source_mechanism"], "manual-verification")

    def test_manual_facts_take_precedence_after_deterministic_merge(self):
        with tempfile.TemporaryDirectory() as directory:
            lake_path = os.path.join(directory, "lake.json")
            observations_path = os.path.join(directory, "observations.json")
            deterministic = {
                "record_type": "programme",
                "programme_id": "outreachy",
                "programme_name": "Outreachy",
                "official_url": "https://www.outreachy.org/",
                "programme_status": "closed",
                "opening_date": "2026-01-01",
                "deadline": "2026-01-31",
                "official_evidence": {"status": {"quote": "deterministic", "url": "https://www.outreachy.org/"}},
            }
            with open(lake_path, "w") as handle:
                handle.write("[]")
            merge_programmes([deterministic], [], lake_path, observations_path, now="2026-08-18T12:00:00Z")
            manual = {
                "programme_id": "outreachy",
                "verified_at": "2026-08-18T00:00:00Z",
                "verified_by": "manual-ai",
                "programme_status": "opening_soon",
                "opening_date": "2026-08-24",
                "deadline": "2026-08-31",
                "official_evidence": {
                    "status": {"quote": "manual status", "url": "https://www.outreachy.org/docs/applicant/"},
                    "opening_date": {"quote": "manual opening", "url": "https://www.outreachy.org/docs/applicant/"},
                    "deadline": {"quote": "manual deadline", "url": "https://www.outreachy.org/docs/applicant/"},
                },
            }
            with open(lake_path) as handle:
                deterministic_rows = json.load(handle)
            applied = apply_verifications(deterministic_rows, [manual], "2026-08-18T12:00:00Z")
            row = applied[0]
            self.assertEqual(row["programme_status"], "opening_soon")
            self.assertEqual(row["opening_date"], "2026-08-24")
            self.assertEqual(row["deadline"], "2026-08-31")
            self.assertEqual(row["official_evidence"]["status"]["quote"], "manual status")
            self.assertTrue(row["is_live"])


if __name__ == "__main__":
    unittest.main()
