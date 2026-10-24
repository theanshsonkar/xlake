import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline import publish_supabase as pub  # noqa: E402


def job(**kw):
    r = {"platform": "greenhouse", "token": "acme", "job_id": "1", "title": "SWE Intern",
         "company_name": "Acme", "location": "Austin, TX", "url": "https://acme.io/jobs/1",
         "is_live": True, "is_internship": True, "location_bucket": "us_located"}
    r.update(kw)
    return r


class JobMapRowTest(unittest.TestCase):
    def test_new_extra_keys_description_and_logo(self):
        m = pub.map_row(job(
            description="<p>" + "Build great things. " * 40 + "</p>",
            employment_type="internship", workplace="hybrid", salary_min=40, salary_max=50,
            salary_currency="USD", salary_text="USD 40-50 per hour", salary_interval="hour",
            posted_at="2026-10-01T00:00:00+00:00", level="intern", team="Eng",
            company_domain="acme.io", company_display_name="Acme Inc", region="us",
            deadline="2026-12-01"))
        self.assertEqual(m["type"], "internship")
        self.assertLessEqual(len(m["description"]), 300)
        self.assertGreater(len(m["description"]), 250)
        self.assertNotIn("<", m["description"])
        self.assertEqual(m["deadline"], "2026-12-01")
        e = m["extra"]
        for k, v in (("employment_type", "internship"), ("workplace", "hybrid"), ("salary_min", 40),
                     ("salary_max", 50), ("salary_currency", "USD"), ("salary_text", "USD 40-50 per hour"),
                     ("posted_at", "2026-10-01T00:00:00+00:00"), ("level", "intern"), ("team", "Eng"),
                     ("company_domain", "acme.io"), ("company_display_name", "Acme Inc"), ("region", "us")):
            self.assertEqual(e[k], v, k)
        self.assertIn("acme.io", e["logo_url"])

    def test_explicit_logo_wins_and_no_domain_no_logo(self):
        self.assertEqual(pub.map_row(job(company_domain="a.io", logo_url="https://x/l.png"))["extra"]["logo_url"],
                         "https://x/l.png")
        self.assertNotIn("logo_url", pub.map_row(job())["extra"])

    def test_placeholders_become_null_and_empty_description_is_null(self):
        m = pub.map_row(job(eligibility="needs_confirmation", funding="not_stated", description=""))
        self.assertIsNone(m["eligibility"])
        self.assertIsNone(m["funding"])
        self.assertIsNone(m["description"])
        m = pub.map_row(job(employment_type="unknown", workplace="n/a"))
        self.assertNotIn("employment_type", m["extra"])
        self.assertNotIn("workplace", m["extra"])

    def test_job_only_keys_do_not_leak_to_other_types(self):
        m = pub.map_row({"record_type": "programme", "programme_id": "p", "title": "P", "is_live": True,
                         "employment_type": "full-time", "salary_min": 1, "level": "x", "team": "t"})
        for k in ("employment_type", "salary_min", "level", "team"):
            self.assertNotIn(k, m["extra"])

    def test_id_unchanged_by_url_params_and_duplicates_not_served(self):
        a = job(url="https://acme.io/jobs/1?utm_source=x")
        self.assertEqual(pub.stable_id(a), pub.stable_id(dict(a)))  # id = hash of the raw url, as before
        self.assertTrue(pub.stable_id(a).startswith("job:"))
        self.assertTrue(pub.is_serving(job()))
        self.assertFalse(pub.is_serving(job(is_duplicate=True)))
        self.assertTrue(pub.is_serving(job(is_duplicate=False)))
        self.assertFalse(pub.is_serving(job(is_live=False, needs_confirmation=False)))


class JobShardPublishTest(unittest.TestCase):
    def test_build_serving_scoped_to_job_shard(self):
        rows = [job(platform="workable", url="https://w/1"), job(platform="greenhouse", url="https://g/1"),
                job(platform="workable", url="https://w/2", is_duplicate=True)]
        m = pub.build_serving(rows, "jobs-workable")
        self.assertEqual([x["extra"]["platform"] for x in m], ["workable"])

    def test_scoped_retire_only_touches_job_ids(self):
        existing = {"job:aaa", "job:bbb", "hackathon:x"}
        retire, err = pub.plan_retire(existing, {"job:aaa"}, "jobs-workable", force=True)
        self.assertEqual(retire, ["job:bbb"])
        self.assertIsNone(err)

    def test_retire_guard_applies(self):
        existing = {"job:%d" % i for i in range(30)}
        _, err = pub.plan_retire(existing, set(), "jobs-lever")
        self.assertIsNotNone(err)

    def test_job_shard_ids_fetch_filters_by_platform(self):
        class Fake(pub.Supabase):
            def __init__(self):
                pass

            def _request(self, method, path, body=None, headers=None):
                import json
                rows = [{"id": "job:1", "platform": "workable"}, {"id": "job:2", "platform": "lever"},
                        {"id": "job:3", "platform": None}]
                return 200, {}, json.dumps(rows)
        self.assertEqual(Fake().fetch_job_ids("jobs-workable"), {"job:1"})
        self.assertEqual(Fake().fetch_job_ids("jobs-other"), {"job:3"})


if __name__ == "__main__":
    unittest.main()


class LiveOnlyAndRotationTest(unittest.TestCase):
    def test_fetchers_only_request_live_rows(self):
        seen = []

        class Fake(pub.Supabase):
            def __init__(self):
                pass

            def _request(self, method, path, body=None, headers=None):
                seen.append(path)
                return 200, {}, "[]"
        Fake().fetch_job_ids("jobs-lever")
        Fake().fetch_all_ids([("hackathon", None)])
        Fake().fetch_all_ids()
        self.assertEqual(len(seen), 3)
        self.assertTrue(all("or=(is_live.eq.true,needs_confirmation.eq.true)" in p for p in seen))  # serving rows: retired ones excluded

    def test_scoped_retire_only_own_shard_prefix(self):
        retire, _ = pub.plan_retire({"job:1", "hackathon:x"}, set(), "jobs-lever", True)
        self.assertEqual(retire, ["job:1"])

    def test_rotation_covers_all_and_unswept_rows_never_retire(self):
        from pipeline import sweep
        from core import retire
        entries = [{"platform": "workable", "token": "t%03d" % i} for i in range(10)]
        seen = set()
        for day in range(4):
            part = sweep.rotate_boards(entries, 4, day)
            self.assertEqual(len(part), 4)
            seen |= {e["token"] for e in part}
        self.assertEqual(len(seen), 10)
        self.assertEqual(sweep.rotate_boards(entries, 0, 5), entries)
        # rows of a board left out of this run (in registry, not attempted, not read)
        row = {"platform": "workable", "token": "t009", "is_live": True,
               "last_seen": "2020-01-01T00:00:00+00:00"}
        reg = {(e["platform"], e["token"]) for e in entries}
        stats = retire.apply([row], set(), {("workable", "t000")}, {("workable", "t000")},
                             reg, "2026-10-19T00:00:00+00:00")
        self.assertTrue(row["is_live"])
        self.assertEqual(sum(stats.values()), 0)
