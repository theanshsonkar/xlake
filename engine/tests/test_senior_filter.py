import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline.publish_supabase import is_serving  # noqa: E402


def job(**kw):
    r = {"url": "https://boards.test/j/1", "title": "Engineer", "is_live": True}
    r.update(kw)
    return r


class SeniorFilterTest(unittest.TestCase):
    def test_senior_jobs_not_served(self):
        self.assertFalse(is_serving(job(level="senior")))
        self.assertFalse(is_serving(job(stage_resolved="senior")))

    def test_early_and_unknown_jobs_still_served(self):
        self.assertTrue(is_serving(job()))
        self.assertTrue(is_serving(job(level="entry", stage_resolved="early")))

    def test_internships_and_programmes_never_filtered(self):
        self.assertTrue(is_serving(job(is_internship=True, level="senior")))
        self.assertTrue(is_serving(job(record_type="programme", level="senior")))


if __name__ == "__main__":
    unittest.main()
