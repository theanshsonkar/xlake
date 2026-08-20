import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import filters, quality


class TestLocationBucketSplit(unittest.TestCase):
    def test_india_located(self):
        self.assertEqual(filters.location_bucket("Bengaluru, India"), filters.INDIA_LOCATED)

    def test_generic_remote_non_india_is_remote_global(self):
        self.assertEqual(filters.location_bucket("Remote"), filters.REMOTE_GLOBAL)

    def test_generic_remote_india_source_is_india_remote(self):
        self.assertEqual(filters.location_bucket("Remote", india_source=True), filters.INDIA_REMOTE)

    def test_worldwide_is_india_remote(self):
        self.assertEqual(filters.location_bucket("Work from anywhere"), filters.INDIA_REMOTE)

    def test_foreign_onsite_is_global_hiring(self):
        self.assertEqual(filters.location_bucket("San Francisco, CA"), filters.GLOBAL_HIRING)

    def test_region_excluded_is_excluded(self):
        self.assertEqual(filters.location_bucket("Remote - US only"), filters.EXCLUDED)

    def test_blank_defaults(self):
        self.assertEqual(filters.location_bucket(""), filters.GLOBAL_HIRING)
        self.assertEqual(filters.location_bucket("", india_source=True), filters.INDIA_REMOTE)


class TestAccessibilityTiers(unittest.TestCase):
    def test_mapping(self):
        self.assertEqual(filters.accessibility(filters.INDIA_LOCATED), filters.ACCESS_INDIA)
        self.assertEqual(filters.accessibility(filters.INDIA_REMOTE), filters.ACCESS_REMOTE_GLOBAL)
        self.assertEqual(filters.accessibility(filters.REMOTE_GLOBAL), filters.ACCESS_REMOTE_GLOBAL)
        self.assertEqual(filters.accessibility(filters.GLOBAL_HIRING), filters.ACCESS_FOREIGN_ONSITE)
        self.assertEqual(filters.accessibility(filters.EXCLUDED), filters.ACCESS_EXCLUDED)

    def test_rank_order(self):
        self.assertLess(filters.access_rank(filters.INDIA_LOCATED), filters.access_rank(filters.REMOTE_GLOBAL))
        self.assertLess(filters.access_rank(filters.REMOTE_GLOBAL), filters.access_rank(filters.GLOBAL_HIRING))
        self.assertLess(filters.access_rank(filters.GLOBAL_HIRING), filters.access_rank(filters.EXCLUDED))

    def test_default_feed_tiers(self):
        self.assertEqual(filters.DEFAULT_FEED_TIERS, (filters.ACCESS_INDIA, filters.ACCESS_REMOTE_GLOBAL))
        self.assertNotIn(filters.ACCESS_FOREIGN_ONSITE, filters.DEFAULT_FEED_TIERS)


class TestForeignNoLongerHidden(unittest.TestCase):
    def test_foreign_onsite_not_hidden(self):
        self.assertIsNone(filters.hidden_reason("unknown", filters.GLOBAL_HIRING, True))

    def test_remote_global_not_hidden(self):
        self.assertIsNone(filters.hidden_reason("unknown", filters.REMOTE_GLOBAL, True))

    def test_senior_still_hidden(self):
        self.assertEqual(filters.hidden_reason("senior", filters.INDIA_LOCATED, True), filters.HIDDEN_SENIOR)

    def test_experience_still_hidden(self):
        self.assertEqual(filters.hidden_reason("unknown", filters.GLOBAL_HIRING, True, experience_min=5), filters.HIDDEN_EXPERIENCE)

    def test_non_technical_still_hidden(self):
        self.assertEqual(filters.hidden_reason("unknown", filters.INDIA_LOCATED, False, discipline=filters.NON_TECH), filters.HIDDEN_NON_TECHNICAL)

    def test_not_india_no_longer_produced(self):
        for bucket in (filters.INDIA_LOCATED, filters.INDIA_REMOTE, filters.REMOTE_GLOBAL,
                       filters.GLOBAL_HIRING, filters.EXCLUDED):
            self.assertNotEqual(filters.hidden_reason("unknown", bucket, True), filters.HIDDEN_NOT_INDIA)


class TestHonestExcludedLabel(unittest.TestCase):
    def test_canonical_reason(self):
        self.assertEqual(filters.canonical_reason("remote_region_excludes_india"), filters.HIDDEN_REGION_EXCLUDED)
        self.assertEqual(filters.HIDDEN_REGION_EXCLUDED, "region_excludes_india")


class TestClassifyForeignKept(unittest.TestCase):
    def test_foreign_onsite_kept_not_hidden(self):
        verdict = filters.classify("Software Engineer", "San Francisco, CA")
        self.assertTrue(verdict.keep)
        self.assertEqual(verdict.bucket, filters.GLOBAL_HIRING)
        self.assertIsNone(filters.hidden_reason("unknown", verdict.bucket, verdict.technical))

    def test_region_excluded_routed_out(self):
        verdict = filters.classify("Software Engineer", "Remote - US only")
        self.assertFalse(verdict.keep)
        self.assertEqual(verdict.bucket, filters.EXCLUDED)
        self.assertEqual(filters.canonical_reason(verdict.reason), filters.HIDDEN_REGION_EXCLUDED)


class TestQualityAccessibility(unittest.TestCase):
    def test_job_rows_are_stamped_non_job_rows_are_not(self):
        job = {
            "url": "https://jobs.example/job",
            "token": "acme",
            "platform": "greenhouse",
            "title": "Software Engineer",
            "location_bucket": filters.GLOBAL_HIRING,
            "first_seen": "2026-08-01",
        }
        programme = {
            "record_type": "programme",
            "programme_id": "acme-programme",
            "url": "https://acme.example/programme",
            "organizer": "Acme",
            "token": "acme",
            "platform": "greenhouse",
            "title": "Software Engineer",
            "location_bucket": filters.GLOBAL_HIRING,
            "posted_on": "2020-01-01",
            "first_seen": "2026-08-02",
        }

        rows = quality.annotate([job, programme])

        self.assertEqual(rows[0]["accessibility"], filters.ACCESS_FOREIGN_ONSITE)
        self.assertEqual(rows[0]["access_rank"], 2)
        self.assertNotIn("accessibility", rows[1])


if __name__ == "__main__":
    unittest.main()
