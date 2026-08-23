import os
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline import admit_boards


def fake_result(platform, token, count=0, error=None, location=""):
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
                           location=spec.get("location", ""))


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

    def test_enrich_platform_goes_to_pending_never_registry(self):
        caches = {"workable": ["foo", "bar"]}
        res, v = self._run(caches, [], {})
        self.assertEqual(res["admit_entries"], [])
        self.assertEqual(res["report"]["workable"]["pending"], 2)
        self.assertEqual(len(res["pending_rows"]), 1)
        self.assertEqual(res["pending_rows"][0]["new_tokens"], 2)
        self.assertEqual(v.calls, [])

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


if __name__ == "__main__":
    unittest.main()
