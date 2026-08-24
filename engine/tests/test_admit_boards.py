import os
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline import admit_boards


def fake_result(platform, token, count=0, error=None, location="", postings=None):
    if postings is None:
        postings = [SimpleNamespace(location=location) for _ in range(count)] if count else []
    return SimpleNamespace(platform=platform, token=token, count=count,
                           error=error, postings=postings)


class FakeVerifier:
    def __init__(self, mapping):
        self.mapping = mapping
        self.calls = []

    def __call__(self, platform, token):
        self.calls.append((platform, token))
        spec = self.mapping.get((platform, token), {"count": 0})
        return fake_result(platform, token,
                           count=spec.get("count", 0),
                           error=spec.get("error"),
                           location=spec.get("location", ""),
                           postings=spec.get("postings"))


class AdmitBoardsTest(unittest.TestCase):
    def _run(self, caches, registry, mapping):
        v = FakeVerifier(mapping)
        res = admit_boards.run_admission(caches, registry, list_board_fn=v)
        return res, v

    def test_clean_verified_admitted(self):
        caches = {"keka": ["alpha"]}
        mapping = {("keka", "alpha"): {"count": 12, "location": "Bengaluru"}}
        res, _ = self._run(caches, [], mapping)
        self.assertEqual(len(res["admit_entries"]), 1)
        e = res["admit_entries"][0]
        self.assertEqual(set(e), {"platform", "token", "company", "segment", "source", "evidence"})
        self.assertEqual(e["platform"], "keka")
        self.assertEqual(e["token"], "alpha")
        self.assertEqual(e["source"], "discovery")
        self.assertEqual(res["report"]["keka"]["admit"], 1)
        self.assertEqual(res["review_rows"], [])

    def test_empty_and_dead_dropped(self):
        caches = {"greenhouse": ["emptyco", "deadco"]}
        mapping = {
            ("greenhouse", "emptyco"): {"count": 0},
            ("greenhouse", "deadco"): {"error": "http_404"},
        }
        res, _ = self._run(caches, [], mapping)
        self.assertEqual(res["admit_entries"], [])
        r = res["report"]["greenhouse"]
        self.assertEqual((r["empty"], r["dead"], r["admit"]), (1, 1, 0))

    def test_outlier_count_flagged_not_admitted(self):
        caches = {"greenhouse": ["bigco"]}
        mapping = {("greenhouse", "bigco"): {"count": 500}}
        res, _ = self._run(caches, [], mapping)
        self.assertEqual(res["admit_entries"], [])
        self.assertEqual(len(res["review_rows"]), 1)
        self.assertIn("outlier", res["review_rows"][0]["reason"])
        self.assertEqual(res["report"]["greenhouse"]["flagged"], 1)

    def test_agency_name_flagged_not_admitted(self):
        caches = {"keka": ["brightwave-staffing"]}
        mapping = {("keka", "brightwave-staffing"): {"count": 10}}
        res, _ = self._run(caches, [], mapping)
        self.assertEqual(res["admit_entries"], [])
        self.assertEqual(len(res["review_rows"]), 1)
        self.assertIn("agency", res["review_rows"][0]["reason"])

    def test_workable_admits_and_custom_enrich_goes_to_pending(self):
        caches = {"workable": ["foo", "bar"]}
        mapping = {
            ("workable", "foo"): {"count": 2},
            ("workable", "bar"): {"count": 1},
        }
        res, v = self._run(caches, [], mapping)
        self.assertEqual([e["token"] for e in res["admit_entries"]], ["foo", "bar"])
        self.assertEqual(res["report"]["workable"]["policy"], "admit")
        self.assertEqual(res["pending_rows"], [])
        self.assertEqual(v.calls, [("workable", "foo"), ("workable", "bar")])

        enrich = admit_boards.run_admission(
            caches={"dummyx": ["t1"]}, registry=[], list_board_fn=v,
            policy={"dummyx": "enrich"},
        )
        self.assertEqual(enrich["admit_entries"], [])
        self.assertEqual(enrich["report"]["dummyx"]["pending"], 1)
        self.assertEqual(enrich["pending_rows"][0]["new_tokens"], 1)
        self.assertIn("lacks fields required for admission",
                      enrich["pending_rows"][0]["note"])

    def test_workable_empty_and_dead_dropped(self):
        caches = {"workable": ["emptyco", "deadco"]}
        mapping = {
            ("workable", "emptyco"): {"count": 0},
            ("workable", "deadco"): {"error": "http_404"},
        }
        res, _ = self._run(caches, [], mapping)
        self.assertEqual(res["admit_entries"], [])
        r = res["report"]["workable"]
        self.assertEqual((r["empty"], r["dead"], r["admit"]), (1, 1, 0))

    def test_workable_outlier_and_agency_flagged_not_admitted(self):
        caches = {"workable": ["hugeco", "brightwave-staffing"]}
        mapping = {
            ("workable", "hugeco"): {"count": admit_boards.OUTLIER_COUNT},
            ("workable", "brightwave-staffing"): {"count": 4},
        }
        res, _ = self._run(caches, [], mapping)
        self.assertEqual(res["admit_entries"], [])
        self.assertEqual(res["report"]["workable"]["flagged"], 2)
        reasons = {row["token"]: row["reason"] for row in res["review_rows"]}
        self.assertIn("outlier", reasons["hugeco"])
        self.assertIn("agency", reasons["brightwave-staffing"])

    def test_workable_idempotent_rerun(self):
        caches = {"workable": ["acme"]}
        mapping = {("workable", "acme"): {"count": 7}}
        res1, _ = self._run(caches, [], mapping)
        merged = admit_boards.merge_registry([], res1["admit_entries"])
        res2, v2 = self._run(caches, merged, mapping)
        self.assertEqual(res2["admit_entries"], [])
        self.assertNotIn(("workable", "acme"), v2.calls)
        merged2 = admit_boards.merge_registry(merged, res2["admit_entries"])
        self.assertEqual(len(merged2), 1)

    def test_page_reader_skipped(self):
        caches = {"zohorecruit": ["a", "b", "c"]}
        res, v = self._run(caches, [], {})
        self.assertEqual(res["admit_entries"], [])
        self.assertEqual(res["report"]["zohorecruit"]["policy"], "page_reader")
        self.assertEqual(v.calls, [])
        self.assertEqual(res["report"]["zohorecruit"]["read"], 3)

    def test_existing_registry_tokens_skipped(self):
        caches = {"keka": ["alpha", "beta"]}
        registry = [{"platform": "keka", "token": "alpha", "company": "Alpha",
                     "segment": "x", "source": "manual", "evidence": "e"}]
        mapping = {("keka", "beta"): {"count": 5}}
        res, v = self._run(caches, registry, mapping)
        self.assertNotIn(("keka", "alpha"), v.calls)
        self.assertEqual(res["report"]["keka"]["deduped"], 1)
        self.assertEqual([e["token"] for e in res["admit_entries"]], ["beta"])

    def test_idempotent_rerun(self):
        caches = {"keka": ["alpha"]}
        mapping = {("keka", "alpha"): {"count": 7}}
        res1, _ = self._run(caches, [], mapping)
        merged = admit_boards.merge_registry([], res1["admit_entries"])
        res2, v2 = self._run(caches, merged, mapping)
        self.assertEqual(res2["admit_entries"], [])
        self.assertNotIn(("keka", "alpha"), v2.calls)
        merged2 = admit_boards.merge_registry(merged, res2["admit_entries"])
        self.assertEqual(len(merged2), 1)

    def test_existing_entries_preserved_on_merge(self):
        existing = [{"platform": "lever", "token": "palantir", "company": "Palantir",
                     "segment": "big_tech", "source": "resolver", "evidence": "x"}]
        new = [admit_boards.build_entry("keka", "alpha", "alpha", 9)]
        merged = admit_boards.merge_registry(existing, new)
        self.assertEqual(merged[0], existing[0])
        self.assertEqual(len(merged), 2)


class WorkableNameResolutionTest(unittest.TestCase):
    def test_widget_name_is_authoritative(self):
        calls = []

        def fake(url, want_json=True, **kw):
            calls.append(url)
            self.assertTrue(url.startswith("https://apply.workable.com/api/v1/widget/accounts/"))
            return 200, {"name": "Acme Corp"}, None

        self.assertEqual(
            admit_boards.resolve_display_name("workable", "acme", request_fn=fake),
            ("Acme Corp", "workable-widget"),
        )
        self.assertEqual(len(calls), 1)

    def test_accounts_endpoint_is_fallback(self):
        calls = []

        def fake(url, want_json=True, **kw):
            calls.append(url)
            if "api/v1/widget/accounts/" in url:
                return 503, None, "http_503"
            self.assertTrue(url.startswith("https://www.workable.com/api/accounts/"))
            return 200, {"name": "Beta Inc"}, None

        self.assertEqual(
            admit_boards.resolve_display_name("workable", "beta", request_fn=fake),
            ("Beta Inc", "workable-accounts"),
        )
        self.assertEqual(len(calls), 2)

    def test_failed_name_requests_only_use_clean_token_fallback(self):
        calls = []

        def fake(url, want_json=True, **kw):
            calls.append(url)
            return 404, None, "http_404"

        self.assertEqual(
            admit_boards.resolve_display_name(
                "workable", "mystery-company", request_fn=fake
            ),
            ("Mystery Company", "fallback-token"),
        )
        self.assertEqual(len(calls), 2)

    def test_refresh_display_names_resolves_workable_entry(self):
        token = "acme"
        registry = [admit_boards.build_entry("workable", token, token, 1)]
        calls = []

        def fake(platform, resolved_token):
            calls.append((platform, resolved_token))
            return "Acme Corp", "workable-widget"

        rows = admit_boards.refresh_display_names(registry, resolve_fn=fake)

        self.assertEqual(calls, [("workable", token)])
        self.assertEqual(registry[0]["company"], "Acme Corp")
        self.assertEqual(rows[0]["kind"], "workable-widget")


if __name__ == "__main__":
    unittest.main()
