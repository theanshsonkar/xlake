import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
from datetime import date

from crawler import funding

TODAY = date(2026, 11, 14)


class TestFunding(unittest.TestCase):
    def test_batch_long_short_cohort_and_future(self):
        labels = funding.batch_labels("Batch: Winter 2026 and S25, plus Class of 2024. Apply for Winter 2027", TODAY)
        starts = {l[0]: l[2] for l in labels}
        self.assertEqual(starts, {"2026-01-01": "month", "2025-06-01": "month", "2024-01-01": "year"})

    def test_short_form_case_sensitive_and_dedup(self):
        self.assertEqual(funding.batch_labels("w26 and f25", TODAY), [])
        self.assertEqual(len(funding.batch_labels("Winter 2026 W26", TODAY)), 1)
        self.assertEqual(funding.batch_labels("2025 cohort", TODAY)[0][0], "2025-01-01")

    def test_published_date(self):
        self.assertEqual(funding.published_date({"datepublished": "2026-10-01T10:00:00Z"}, [], [], TODAY), "2026-10-01")
        ld = [json.dumps({"@graph": [{"@type": "Article", "datePublished": "2026-09-02"}]})]
        self.assertEqual(funding.published_date({}, ld, [], TODAY), "2026-09-02")
        self.assertEqual(funding.published_date({}, [], ["2026-08-03T00:00"], TODAY), "2026-08-03")
        self.assertIsNone(funding.published_date({"date": "2027-01-01"}, [], [], TODAY))
        self.assertIsNone(funding.published_date({}, [], [], TODAY))

    def test_funding_quote(self):
        q = funding.funding_quote("Hello there. Beta Co raised a $5M seed round. Bye")
        self.assertEqual(q, "Beta Co raised a $5M seed round")
        self.assertIsNone(funding.funding_quote("Nothing here."))

    def test_from_page(self):
        page = {"title": "News", "text": "Beta Co raised a seed round.", "published": "2026-10-01"}
        ev = funding.from_page(page, "https://n.test/a", "news", TODAY)
        self.assertEqual((ev["date"], ev["precision"], ev["source_kind"]), ("2026-10-01", "day", "news"))
        page = {"title": "Acme", "text": "Batch: Winter 2026 Apply for Winter 2027", "published": None}
        self.assertIsNone(funding.from_page(page, "https://y.test/acme", "own_site", TODAY))
        ev = funding.from_page(page, "https://y.test/acme", "accelerator", TODAY)
        self.assertEqual((ev["date"], ev["source_kind"]), ("2026-01-01", "accelerator"))
        self.assertIn("Winter 2026", ev["quote"])
        self.assertIsNone(funding.from_page({"title": "x", "text": "hi", "published": None}, "u", "page", TODAY))

    def test_from_anchor(self):
        ev = funding.from_anchor("Acme W26", "https://y.test/", TODAY)
        self.assertEqual(ev["date"], "2026-01-01")
        self.assertIsNone(funding.from_anchor("Acme", "https://y.test/", TODAY))

    def test_mentions(self):
        ev = {"date": "2026-10-01", "quote": "Beta Co raised money", "source_kind": "news"}
        self.assertTrue(funding.mentions(ev, {}, "Beta"))
        self.assertFalse(funding.mentions(ev, {"title": "Othercorp"}, "Othercorp"))
        acc = dict(ev, source_kind="accelerator", quote="Winter 2026")
        self.assertTrue(funding.mentions(acc, {"title": "Othercorp", "h1": ""}, "Othercorp"))

    def test_is_recent_and_best(self):
        self.assertTrue(funding.is_recent({"date": "2026-01-01"}, TODAY))
        self.assertFalse(funding.is_recent({"date": "2025-01-01"}, TODAY))
        self.assertFalse(funding.is_recent({"date": "2027-01-01"}, TODAY))
        self.assertFalse(funding.is_recent(None, TODAY))
        a, b = {"date": "2026-01-01", "k": 1}, {"date": "2026-01-01", "k": 2}
        self.assertIs(funding.best(None, a, b), a)
        self.assertEqual(funding.best(a, {"date": "2026-05-01"})["date"], "2026-05-01")


if __name__ == "__main__":
    unittest.main()


class TestFundingPrecision(unittest.TestCase):
    def test_quote_needs_event(self):
        for t in ("Born and raised in South Mississippi", "Output jumped, led by CFI",
                  "AI Interviewer closes it same-day", "Learn how ZTNA secures every user"):
            self.assertIsNone(funding.funding_quote(t), t)
        self.assertTrue(funding.funding_quote("Foo bags Rs 40 crore in Series A"))
        self.assertTrue(funding.funding_quote("Acme raised $5.2M led by X"))

    def test_homepage_date_is_not_announcement(self):
        page = {"title": "Acme", "text": "Acme raised $5M in seed funding.", "published": "2026-10-01"}
        self.assertIsNone(funding.from_page(page, "https://acme.com/", "own_site", TODAY))
        self.assertTrue(funding.from_page(page, "https://acme.com/blog/seed", "own_site", TODAY))

    def test_accelerator_title_must_start_with_name(self):
        ev = {"source_kind": "accelerator", "quote": "Fall 2026 cohort"}
        self.assertTrue(funding.mentions(ev, {"title": "Acme: robots for farms"}, "Acme"))
        self.assertFalse(funding.mentions(ev, {"title": "Techstars is No. 1 on TIME list"}, "Time"))
