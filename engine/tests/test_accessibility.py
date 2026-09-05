import os
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

    def test_blank_defaults(self):
        self.assertEqual(filters.location_bucket(""), filters.GLOBAL_HIRING)
        self.assertEqual(filters.location_bucket("", india_source=True), filters.US_REMOTE)

    def test_generic_remote_india_source_is_primary_region_remote(self):
        self.assertEqual(filters.location_bucket("Remote", india_source=True), filters.US_REMOTE)

    def test_worldwide_is_generic_remote(self):
        self.assertEqual(filters.location_bucket("Work from anywhere"), filters.REMOTE_GLOBAL)

    def test_us_onsite_and_remote(self):
        self.assertEqual(filters.location_bucket("San Francisco, CA"), filters.US_LOCATED)
        self.assertEqual(filters.location_bucket("Remote - US only"), filters.US_REMOTE)

    def test_us_only_remote_is_not_excluded(self):
        self.assertEqual(filters.location_bucket("Remote - US residents only"), filters.US_REMOTE)
        self.assertEqual(filters.location_bucket("Must be located in the United States"), filters.US_LOCATED)

    def test_us_barred_remote_is_excluded(self):
        for location in (
            "Remote - non-US",
            "Remote - worldwide (excluding US)",
            "Remote - outside the US",
            "Remote - not eligible for US applicants",
            "Remote - not available to US residents",
        ):
            verdict = filters.classify("Software Engineer", location)
            self.assertFalse(verdict.keep, location)
            self.assertEqual(verdict.bucket, filters.EXCLUDED, location)
            self.assertEqual(filters.access_rank(verdict.bucket), 3)

    def test_india_stays_located(self):
        self.assertEqual(filters.location_bucket("Bengaluru, India"), filters.INDIA_LOCATED)

    def test_state_codes_require_context_and_avoid_word_false_positives(self):
        self.assertEqual(filters.location_bucket("Austin, TX"), filters.US_LOCATED)
        self.assertEqual(filters.location_bucket("IN"), filters.GLOBAL_HIRING)
        self.assertEqual(filters.location_bucket("OR"), filters.GLOBAL_HIRING)
        self.assertFalse(filters.US_RE.search("Software Engineer in IN or OR"))


class TestAccessibilityTiers(unittest.TestCase):
    def test_mapping(self):
        self.assertEqual(filters.accessibility(filters.INDIA_LOCATED), filters.ACCESS_INDIA)
        self.assertEqual(filters.accessibility(filters.INDIA_REMOTE), filters.ACCESS_INDIA_REMOTE)
        self.assertEqual(filters.accessibility(filters.REMOTE_GLOBAL), filters.ACCESS_REMOTE_GLOBAL)
        self.assertEqual(filters.accessibility(filters.GLOBAL_HIRING), filters.ACCESS_FOREIGN_ONSITE)
        self.assertEqual(filters.accessibility(filters.EXCLUDED), filters.ACCESS_EXCLUDED)

    def test_primary_region_mapping(self):
        self.assertEqual(filters.accessibility(filters.US_LOCATED), filters.ACCESS_US)
        self.assertEqual(filters.accessibility(filters.US_REMOTE), filters.ACCESS_US_REMOTE)
        self.assertEqual(filters.access_rank(filters.US_LOCATED), 0)
        self.assertEqual(filters.access_rank(filters.US_REMOTE), 0)
        self.assertEqual(filters.access_rank(filters.REMOTE_GLOBAL), 1)
        self.assertEqual(filters.access_rank(filters.INDIA_LOCATED), 2)
        self.assertEqual(filters.access_rank(filters.INDIA_REMOTE), 2)
        self.assertEqual(filters.access_rank(filters.GLOBAL_HIRING), 2)
        self.assertEqual(filters.access_rank(filters.EXCLUDED), 3)

    def test_default_feed_tiers(self):
        self.assertEqual(filters.DEFAULT_FEED_TIERS,
                         (filters.ACCESS_US, filters.ACCESS_US_REMOTE,
                          filters.ACCESS_REMOTE_GLOBAL))
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
        verdict = filters.classify("Software Engineer", "Berlin")
        self.assertTrue(verdict.keep)
        self.assertEqual(verdict.bucket, filters.GLOBAL_HIRING)
        self.assertIsNone(filters.hidden_reason("unknown", verdict.bucket, verdict.technical))

    def test_region_excluded_routed_out(self):
        verdict = filters.classify("Software Engineer", "Remote - India only")
        self.assertFalse(verdict.keep)
        self.assertEqual(verdict.bucket, filters.EXCLUDED)
        self.assertEqual(filters.canonical_reason(verdict.reason), filters.HIDDEN_REGION_EXCLUDED)

    def test_india_compatibility(self):
        old = filters.PRIMARY_REGION
        try:
            filters.PRIMARY_REGION = "IN"
            self.assertEqual(filters.location_bucket("Bengaluru, India"), filters.INDIA_LOCATED)
            self.assertEqual(filters.location_bucket("Remote", india_source=True), filters.INDIA_REMOTE)
            self.assertEqual(filters.location_bucket("Remote - US only"), filters.EXCLUDED)
            self.assertEqual(filters.access_rank(filters.INDIA_LOCATED), 0)
            self.assertEqual(filters.access_rank(filters.INDIA_REMOTE), 0)
        finally:
            filters.PRIMARY_REGION = old


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
