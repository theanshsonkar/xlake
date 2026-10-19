import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from categories import programme_core
from categories.community import programmes as community
from categories.open_source import programmes as open_source
from categories.startup_founder import programmes as startup

OPS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "operations")


class CuratedVerificationTests(unittest.TestCase):
    def _check(self, module, filename):
        with open(os.path.join(OPS, filename), encoding="utf-8") as handle:
            records = json.load(handle)
        self.assertTrue(records)
        for rec in records:
            if not rec.get("recheck_after"):  # hand-verified expiring records may be standalone
                self.assertIn(rec["programme_id"], module.SOURCE_BY_ID)
            self.assertTrue(programme_core.validate_verification(rec)[0], rec["programme_id"])

    def test_startup_verifications_match_seeds(self):
        self.assertGreaterEqual(len(startup.STATIC_SOURCE_REGISTRY), 6)
        self._check(startup, "startup_founder_programme_verifications.json")

    def test_community_verifications_match_seeds(self):
        self._check(community, "community_programme_verifications.json")

    def test_open_source_verifications_match_seeds(self):
        self._check(open_source, "programme_verifications.json")


if __name__ == "__main__":
    unittest.main()
