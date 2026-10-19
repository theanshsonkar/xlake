import os
import sys
import unittest
from datetime import date, datetime, timezone
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from categories import programme_core as core
from categories import programme_enrich as enrich
from categories.scholarships import scholarships
from categories.fellowships import fellowships
from categories.open_source import contributions

CFG = scholarships.SCHOLARSHIP_CONFIG
EV = {"quote": "Applications close on 2026-12-01", "url": "https://official.example/apply"}
NOW = "2026-10-20T00:00:00Z"


def record(**kw):
    rec = {
        "programme_id": "hand-1", "title": "Hand Programme", "organizer": "Org",
        "official_url": "https://official.example/prog", "verified_by": "manual",
        "verified_at": "2026-10-19T00:00:00Z", "recheck_after": "2026-11-18",
        "programme_status": "open", "deadline": "2026-12-01", "funding": "$1,000",
        "official_evidence": {"status": EV, "deadline": EV, "funding": EV},
    }
    rec.update(kw)
    return rec


class VerifiedCreateTests(unittest.TestCase):
    def test_creates_full_row(self):
        row = core.apply_verifications([], [record()], NOW, config=CFG)[0]
        self.assertEqual(row["programme_name"], "Hand Programme")
        self.assertEqual(row["category"], CFG.category)
        self.assertEqual(row["source_kind"], "official")
        self.assertIn("official.example", row["logo_url"])
        self.assertTrue(row["is_live"])

    def test_matches_existing_by_url_no_duplicate(self):
        existing = {"record_type": "programme", "category": CFG.category, "programme_id": "seed-x",
                    "programme_name": "Other", "official_url": "https://www.official.example/prog/"}
        out = core.apply_verifications([existing], [record()], NOW, config=CFG)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["programme_id"], "seed-x")
        self.assertTrue(out[0]["manually_verified"])

    def test_matches_existing_by_title_and_org(self):
        existing = {"record_type": "programme", "category": CFG.category, "programme_id": "seed-y",
                    "programme_name": "Hand Programme", "organizer": "Org", "official_url": "https://elsewhere.example/"}
        out = core.apply_verifications([existing], [record(official_url="https://official.example/new")], NOW, config=CFG)
        self.assertEqual(len(out), 1)

    def test_unretires_and_stays_subject_to_expiry(self):
        existing = {"record_type": "programme", "category": CFG.category, "programme_id": "hand-1",
                    "official_url": "https://official.example/prog", "hidden_reason": "source_removed", "is_live": False}
        out = core.apply_verifications([existing], [record()], NOW, config=CFG)
        self.assertIsNone(out[0]["hidden_reason"])
        out = core.apply_verifications([existing], [record()], "2026-12-30T00:00:00Z", config=CFG)
        self.assertEqual(out[0]["programme_status"], "needs_confirmation")


class RegionTests(unittest.TestCase):
    def test_tld_fallbacks(self):
        for url, region in (("https://x.ac.in/a", "India"), ("https://x.gov.in", "India"), ("https://x.res.in", "India"),
                            ("https://x.ac.uk", "UK"), ("https://x.edu", "US"), ("https://x.de", "Europe"),
                            ("https://x.ca", "Canada"), ("https://x.com.au", "Australia"), ("https://x.jp", "Asia")):
            self.assertEqual(enrich.fallback_region({"official_url": url}), region, url)

    def test_worldwide_and_country_text(self):
        self.assertEqual(enrich.fallback_region({"official_url": "https://x.org/", "description": "Open to applicants worldwide."}), "Global")
        self.assertEqual(enrich.fallback_region({"official_url": "https://x.org/", "eligibility": "Eligibility: applicants must live in Germany."}), "Europe")
        self.assertIsNone(enrich.fallback_region({"official_url": "https://x.org/", "description": "A fellowship."}))

    def test_known_org(self):
        self.assertEqual(enrich.fallback_region({"official_url": "https://fellowship.mlh.io/"}), "Global")


class FormalTokenTests(unittest.TestCase):
    def test_tokens_present(self):
        for token in ("scholarship", "grant", "fellowship", "award", "prize", "competition",
                      "accelerator", "incubator", "cohort", "ambassador"):
            self.assertIn(token, core.FORMAL_PROGRAMME_TOKENS)

    def test_junk_still_rejected(self):
        for title, url in (("How to win a scholarship", "https://x.org/s"),
                           ("Scholarship tips", "https://x.org/blog/tips"),
                           ("Software Engineer", "https://boards.greenhouse.io/x"),
                           ("Contact us", "https://x.org/contact"),
                           ("Scholarship Jobs | Apply", "https://x.org/j")):
            self.assertFalse(core.programme_title_ok(title, url, "scholarship")[0], title)

    def test_valid_scholarship_page_parses_as_formal(self):
        html = "<html><body><h1>Merit Scholarship</h1><p>Scholarship applications are accepted on a rolling basis.</p><a href='/apply'>Apply</a></body></html>"
        seed = {"source_id": "s", "programme_id": "s", "programme_name": "Merit Scholarship", "organizer": "O",
                "official_url": "https://o.example/s", "allowed_path_hints": [], "check_cadence": "daily"}
        rec, _obs = core.parse_programme(seed, html, datetime(2026, 10, 20, tzinfo=timezone.utc), config=CFG)
        self.assertEqual(rec["programme_status"], "rolling")


class RetireDedupeTests(unittest.TestCase):
    def test_stale_needs_confirmation_retired(self):
        old = {"record_type": "programme", "category": "grant", "programme_status": "needs_confirmation",
               "needs_confirmation": True, "first_seen": "2026-01-01T00:00:00+00:00", "official_evidence": {}}
        fresh = dict(old, first_seen="2026-10-01T00:00:00+00:00")
        evid = dict(old, official_evidence={"status": {"quote": "q", "url": "u"}})
        rows = [old, fresh, evid]
        self.assertEqual(core.retire_stale_needs_confirmation("grant", rows, date(2026, 10, 20), NOW), 1)
        self.assertEqual(old["hidden_reason"], "stale_needs_confirmation")
        self.assertNotIn("hidden_reason", fresh)
        self.assertNotIn("hidden_reason", evid)

    def test_cross_category_dedupe_keeps_primary(self):
        a = {"record_type": "programme", "category": "fellowship", "programme_id": "a", "programme_name": "X Fellowship",
             "official_url": "https://o.org/x", "is_live": True}
        b = {"record_type": "programme", "category": "scholarship", "programme_id": "b", "programme_name": "X Fellowship",
             "official_url": "https://www.o.org/x/", "is_live": True}
        self.assertEqual(core.dedupe_across_categories([a, b], NOW), 1)
        self.assertEqual(b["hidden_reason"], "duplicate_category")
        self.assertNotIn("hidden_reason", a)


class ConcurrencyTests(unittest.TestCase):
    def test_collect_order_deterministic_with_workers(self):
        import tempfile, time, random
        seeds = tuple({"source_id": "s%d" % i, "programme_id": "s%d" % i, "programme_name": "Prog %d Fellowship" % i,
                       "organizer": "O%d" % i, "official_url": "https://h%d.example/p" % i,
                       "allowed_path_hints": [], "check_cadence": "daily"} for i in range(12))
        cfg = core.ProgrammeConfig("fellowship", "fellowship", seeds, "", "")
        def fetch(url):
            time.sleep(random.random() * 0.02)
            return "<html><body>Fellowship applications are accepted on a rolling basis. <a href='/apply'>Apply</a></body></html>", url
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {core.WORKERS_ENV: "8"}), \
                mock.patch.object(core, "load_verifications", return_value=[]), \
                mock.patch.object(core, "recheck_official_urls", return_value={}):
            result = core.collect(cfg, fetch=fetch, lake_path=os.path.join(d, "l.json"),
                                  observations_path=os.path.join(d, "o.json"))
        self.assertEqual([o["programme_id"] for o in result["observations"]], ["s%d" % i for i in range(12)])


class GithubTokenTests(unittest.TestCase):
    def test_gh_pat_preferred(self):
        with mock.patch.dict(os.environ, {"GH_PAT": "pat", "GITHUB_TOKEN": "gt"}):
            self.assertEqual(contributions._github_token(), "pat")
        with mock.patch.dict(os.environ, {"GITHUB_TOKEN": "gt"}, clear=True):
            self.assertEqual(contributions._github_token(), "gt")

    def test_search_error_logged(self):
        from urllib.error import HTTPError
        import io
        def boom(query, token):
            raise HTTPError("u", 403, "Forbidden", {"X-RateLimit-Remaining": "0"}, io.BytesIO(b'{"message":"API rate limit exceeded"}'))
        with mock.patch("builtins.print") as pr, mock.patch.object(contributions, "_discovery_sleep"):
            self.assertEqual(contributions.discover_repos("t", "2026-10-20T00:00:00+00:00", search_fetch=boom), [])
        self.assertIn("HTTP 403", str(pr.call_args_list[0]))


if __name__ == "__main__":
    unittest.main()
