import json
import os
import tempfile
import unittest

from categories.programme_core import dedupe_within_category, merge_programmes
from core import linkcheck
from pipeline.publish_supabase import quality_reason


def prog(name, official, apply=None, **kw):
    return dict({"record_type": "programme", "category": "fellowship", "programme_name": name,
                 "official_url": official, "application_url": apply, "is_live": True}, **kw)


class FlagTests(unittest.TestCase):
    def test_homepage_other_row_deeper(self):
        a = prog("Some Programme", "https://example.org/en/")
        self.assertEqual(linkcheck.flags(a, {"example.org"}), ["link_homepage"])

    def test_homepage_name_not_in_host(self):
        self.assertEqual(linkcheck.flags(prog("Fulbright Nehru Fellowships", "https://www.usief.org.in/")), ["link_homepage"])

    def test_homepage_site_is_the_programme(self):
        self.assertEqual(linkcheck.flags(prog("Thiel Fellowship", "https://thielfellowship.org/")), [])

    def test_deep_apply_link_not_homepage(self):
        row = prog("Fulbright", "https://usief.org.in/", "https://usief.org.in/apply/now")
        self.assertEqual(linkcheck.flags(row), [])

    def test_aggregator(self):
        row = prog("X Grant", "https://www.unstop.com/p/x-grant")
        self.assertEqual(linkcheck.flags(row), ["link_aggregator"])

    def test_hackathon_on_aggregator_ok(self):
        row = {"record_type": "hackathon", "title": "HackIt", "url": "https://hackit.devpost.com/"}
        self.assertEqual(linkcheck.flags(row), [])
        row["url"] = "https://devfolio.co/hackathons/hackit"
        self.assertEqual(linkcheck.flags(row), [])

    def test_vacancy(self):
        self.assertEqual(linkcheck.flags(prog("Vacancy for Officer", "https://example.org/vacancies/1")), ["link_vacancy"])

    def test_dead_needs_two(self):
        base = prog("Thiel Fellowship", "https://thielfellowship.org/x")
        self.assertEqual(linkcheck.flags(dict(base, link_fail_count=1)), [])
        self.assertEqual(linkcheck.flags(dict(base, link_fail_count=2)), ["link_dead"])


class FailCountTests(unittest.TestCase):
    def merge(self, reason, state, rows):
        with tempfile.TemporaryDirectory() as d:
            lake, obs = os.path.join(d, "l.json"), os.path.join(d, "o.json")
            json.dump(rows, open(lake, "w"))
            o = {"official_url": "https://a.org/x", "programme_id": "p", "state": state, "reason": reason,
                 "result": "failed" if state == "failed" else "non_actionable", "checked_at": "2026-01-01T00:00:00+00:00"}
            return merge_programmes([], [o], lake, obs)[0]

    def row(self, n=0):
        return {"record_type": "programme", "category": "fellowship", "programme_id": "p",
                "official_url": "https://a.org/x", "is_live": True, "link_fail_count": n}

    def test_404_and_dns_count(self):
        self.assertEqual(self.merge("http_404", "dead", [self.row()])["link_fail_count"], 1)
        self.assertEqual(self.merge("dns", "dead", [self.row(1)])["link_fail_count"], 2)

    def test_unknown_failures_do_not_count(self):
        for reason in ("http_403", "http_429", "http_503", "timeout"):
            self.assertEqual(self.merge(reason, "failed", [self.row(1)])["link_fail_count"], 1)

    def test_success_resets(self):
        self.assertEqual(self.merge("ok", "non_actionable", [self.row(1)])["link_fail_count"], 0)


class IntegrationTests(unittest.TestCase):
    def test_quality_reason_link_dead(self):
        row = prog("Thiel Fellowship", "https://thielfellowship.org/x", link_quality=["link_dead"])
        self.assertEqual(quality_reason(row), "link_dead")
        self.assertNotEqual(quality_reason(dict(row, link_quality=["link_homepage"])), "link_dead")

    def test_homepage_twin_hidden(self):
        deep = "https://usief.org.in/fulbright-fellowships/fellowships-for-indian-citizen/"
        a = prog("USIEF Fulbright-Nehru Fellowships", "https://www.usief.org.in/", deep, programme_id="a")
        b = prog("Fulbright-Nehru Fellowships for Indian Citizens",
                 "https://www.usief.org.in/fulbright-fellowships/fellowships-for-indian-citizen/",
                 deep.replace("//", "//www."), programme_id="b")
        self.assertEqual(dedupe_within_category([a, b], "now"), 1)
        self.assertEqual(a["hidden_reason"], "duplicate_same_category")
        self.assertEqual(a["duplicate_of"], "b")
        self.assertNotIn("hidden_reason", b)

    def test_annotate_counts_and_jobs_untouched(self):
        rows = [prog("Thiel Fellowship", "https://thielfellowship.org/"),
                prog("X Grant", "https://unstop.com/p/x"),
                prog("Fulbright", "https://usief.org.in/"),
                prog("Dead One", "https://dead.org/p/1", link_fail_count=2),
                prog("Vacancy of Clerk", "https://z.org/p"),
                {"record_type": "job", "title": "Engineer", "url": "https://linkedin.com/jobs/1"}]
        counts = linkcheck.annotate(rows, "now")
        self.assertEqual(counts, {"ok": 1, "homepage": 1, "aggregator": 1, "dead": 1, "vacancy": 1, "checked": 5})
        self.assertEqual(rows[0]["link_quality"], "ok")
        self.assertEqual(rows[0]["link_checked_at"], "now")
        self.assertNotIn("link_quality", rows[5])


if __name__ == "__main__":
    unittest.main()
