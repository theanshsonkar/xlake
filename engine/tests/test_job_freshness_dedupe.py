import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from adapters import boards  # noqa: E402
from core import dedupe, retire, shards  # noqa: E402
from pipeline import sweep  # noqa: E402

NOW = "2026-10-18T00:00:00+00:00"


def row(url, title="Software Engineer", loc="Austin, TX", platform="greenhouse", token="acme",
        last_seen="2026-10-17T00:00:00+00:00", **kw):
    r = {"platform": platform, "token": token, "job_id": url[-4:], "title": title, "location": loc,
         "url": url, "is_live": True, "last_seen": last_seen, "first_seen": last_seen}
    r.update(kw)
    return r


class RetireGuardTest(unittest.TestCase):
    def go(self, rows, read=(), attempted=(), registry=None):
        return retire.apply(rows, set(), set(read), set(attempted), registry, NOW)

    def test_absent_from_clean_board_retires_and_clears_needs_confirmation(self):
        r = row("https://a/1", needs_confirmation=True)
        st = self.go([r], read=[("greenhouse", "acme")])
        self.assertEqual(st["absent_from_board"], 1)
        self.assertFalse(r["is_live"])
        self.assertFalse(r["needs_confirmation"])

    def test_failed_board_never_retires_even_when_ancient(self):
        r = row("https://a/1", last_seen="2025-01-01T00:00:00+00:00")
        st = self.go([r], attempted=[("greenhouse", "acme")], registry={("greenhouse", "acme")})
        self.assertTrue(r["is_live"])
        self.assertEqual(st["blocked_failed_board"], 1)

    def test_orphan_board_retires_only_after_21_days(self):
        old = row("https://a/1", token="gone", last_seen="2026-09-01T00:00:00+00:00")
        fresh = row("https://a/2", token="gone", last_seen="2026-10-10T00:00:00+00:00")
        undated = row("https://a/3", token="gone", last_seen="")
        reg = {("greenhouse", "acme")}
        self.go([old, fresh, undated], registry=reg)
        self.assertFalse(old["is_live"])
        self.assertEqual(old["liveness_reason"], "board_gone_unconfirmed_21d")
        self.assertTrue(fresh["is_live"])
        self.assertTrue(undated["is_live"])

    def test_unknown_registry_never_orphans_and_self_managed_kept(self):
        r = row("https://a/1", token="gone", last_seen="2025-01-01T00:00:00+00:00")
        self.go([r], registry=None)
        self.assertTrue(r["is_live"])
        z = row("https://a/2", platform="zshah101-list", token="us-tech-internships",
                last_seen="2025-01-01T00:00:00+00:00")
        self.go([z], registry={("greenhouse", "acme")})
        self.assertTrue(z["is_live"])

    def test_confirmed_rows_untouched(self):
        r = row("https://a/1")
        retire.apply([r], {id(r)}, {("greenhouse", "acme")}, set(), None, NOW)
        self.assertTrue(r["is_live"])


class DedupeTest(unittest.TestCase):
    def test_same_canonical_url_and_same_company_title_location(self):
        a = row("https://jobs.lever.co/acme/123?lever-source=x", last_seen="2026-10-01")
        b = row("https://jobs.lever.co/acme/123/apply", last_seen="2026-10-05")
        c = row("https://x/job/9", title="Software Engineer", loc="Austin, TX", last_seen="2026-10-17")
        d = row("https://x/job/10", title="Software Engineer", loc="Denver, CO", last_seen="2026-10-17")
        rows = [a, b, c, d]
        st = dedupe.mark_duplicates(rows)
        self.assertEqual(st["by_url"], 1)
        self.assertTrue(a["is_duplicate"])          # older twin of the same URL
        self.assertFalse(c["is_duplicate"])         # freshest of the Austin group
        self.assertTrue(b["is_duplicate"])          # b ~ c by company/title/location, c fresher
        self.assertEqual(b["duplicate_of"], c["url"])
        self.assertFalse(d["is_duplicate"])         # different location is not a duplicate

    def test_ids_untouched_and_idempotent_and_unmarks(self):
        a = row("https://x/1"); b = row("https://x/2", last_seen="2026-10-18")
        dedupe.mark_duplicates([a, b])
        self.assertTrue(a["is_duplicate"])
        self.assertEqual(a["url"], "https://x/1")
        dedupe.mark_duplicates([a])  # twin gone: no longer a duplicate
        self.assertFalse(a["is_duplicate"])
        self.assertIsNone(a["duplicate_of"])

    def test_dead_and_non_job_rows_ignored(self):
        dead = row("https://x/1", is_live=False)
        live = row("https://x/2")
        prog = {"record_type": "programme", "title": "Software Engineer"}
        dedupe.mark_duplicates([dead, live, prog])
        self.assertFalse(live["is_duplicate"])
        self.assertNotIn("is_duplicate", prog)

    def test_company_domain_groups_across_tokens(self):
        a = row("https://x/1", token="acme-a", company_domain="acme.com", last_seen="2026-10-01")
        b = row("https://x/2", token="acme-b", company_domain="acme.com", last_seen="2026-10-09")
        dedupe.mark_duplicates([a, b])
        self.assertTrue(a["is_duplicate"])
        self.assertFalse(b["is_duplicate"])


class ShardRoutingTest(unittest.TestCase):
    def test_job_rows_route_by_platform(self):
        self.assertEqual(shards.shard_of({"platform": "workable"}), "jobs-workable")
        self.assertEqual(shards.shard_of({"platform": "unstop", "is_internship": True}), "jobs-internships")
        self.assertEqual(shards.shard_of({"platform": "zshah101-list"}), "jobs-internships")
        self.assertEqual(shards.shard_of({"platform": "successfactors"}), "jobs-other")
        self.assertEqual(shards.shard_of({"record_type": "hackathon"}), "hackathons")

    def test_roundtrip_with_job_shards(self):
        rows = [{"platform": p, "url": "u" + p} for p in
                ("workable", "greenhouse", "lever", "ashby", "workday", "keka", "unstop", "eightfold")]
        parts = shards.split_rows(rows)
        back = shards.combine(parts.pop("main"), parts)
        self.assertEqual(sorted(r["url"] for r in back), sorted(r["url"] for r in rows))


class SweepIntegrationTest(unittest.TestCase):
    """Sweep a mocked board end to end: meta, gating, retire guard, dedupe."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = self.tmp.name
        self.paths = {"OUT_JOBS": os.path.join(d, "opps.json"), "OUT_HIDDEN": os.path.join(d, "hidden.json"),
                      "OUT_RUNS": os.path.join(d, "runs.jsonl"), "DATA": d,
                      "REGISTRY": os.path.join(d, "registry.json")}
        self.patches = [mock.patch.object(sweep, k, v) for k, v in self.paths.items()]
        for p in self.patches:
            p.start()
        json.dump([{"platform": "workable", "token": "good", "company": "Good Co"},
                   {"platform": "workable", "token": "bad", "company": "Bad Co"}],
                  open(self.paths["REGISTRY"], "w"))
        self.tier = mock.patch.object(sweep.tiering, "save_tier_state").start()

    def tearDown(self):
        mock.patch.stopall()
        self.tmp.cleanup()

    @staticmethod
    def board(token, postings, error=None):
        r = boards.BoardResult("workable", token, error=error)
        r.postings = postings
        return r

    @staticmethod
    def posting(token, jid, title, desc, **meta):
        return boards.Posting("workable", token, jid, title, "Austin, TX, United States",
                              "https://apply.workable.com/j/" + jid, "2026-10-10",
                              description=desc, meta=meta)

    def run_sweep(self, results):
        with mock.patch.object(sweep, "list_board", side_effect=lambda p, t: results[t]):
            return sweep.sweep(sweep.load_registry(), workers=1)

    def test_meta_flows_thin_posting_gated_and_duplicates_marked(self):
        long_desc = "We build things and pay $100,000 - $120,000 per year. " * 5
        results = {
            "good": self.board("good", [
                self.posting("good", "A1", "Software Engineer Intern", long_desc, employment_type="internship",
                             posted_at="2026-10-10", company_domain="good.co", company_display_name="Good Co"),
                self.posting("good", "A2", "Software Engineer Intern", long_desc, employment_type="internship",
                             posted_at="2026-10-11"),
                self.posting("good", "A3", "Backend Developer Intern", "short"),  # thin: gated
            ]),
            "bad": self.board("bad", []),
        }
        self.run_sweep(results)
        rows = json.load(open(self.paths["OUT_JOBS"]))
        hidden = json.load(open(self.paths["OUT_HIDDEN"]))
        by_id = {r["job_id"]: r for r in rows}
        self.assertEqual(set(by_id), {"A1", "A2"})
        self.assertTrue(any(h["hidden_reason"] == "thin_posting" and h["job_id"] == "A3" for h in hidden))
        r = by_id["A1"]
        self.assertEqual(r["employment_type"], "internship")
        self.assertEqual(r["company_domain"], "good.co")
        self.assertEqual(r["region"], "us")
        self.assertTrue(r["is_internship"])
        self.assertEqual(sum(1 for x in rows if x.get("is_duplicate")), 1)
        cov = sweep.coverage(rows)
        self.assertEqual(cov["live"], 2)
        self.assertEqual(cov["duplicates"], 1)

    def test_failed_board_keeps_rows_and_clean_board_retires_absent(self):
        desc = "x" * 200
        first = {"good": self.board("good", [self.posting("good", "A1", "Software Intern", desc)]),
                 "bad": self.board("bad", [self.posting("bad", "B1", "Data Intern", desc)])}
        self.run_sweep(first)
        second = {"good": self.board("good", [self.posting("good", "A9", "ML Intern", desc)]),
                  "bad": self.board("bad", [], error="http_503")}
        self.run_sweep(second)
        live = {r["job_id"]: r["is_live"] for r in json.load(open(self.paths["OUT_JOBS"]))}
        self.assertFalse(live["A1"])   # absent from a clean read: retired
        self.assertTrue(live["A9"])
        self.assertTrue(live["B1"])    # board fetch failed: never retired


if __name__ == "__main__":
    unittest.main()
