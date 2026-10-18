import json
import os
import tempfile
import unittest

from core import shards
from pipeline import publish_supabase as pub
from pipeline import split_lake


def lake():
    rows = [
        {"record_type": "hackathon", "category": "hackathons", "hackathon_id": "h1", "is_live": True},
        {"record_type": "programme", "category": "fellowship", "programme_id": "f1", "is_live": True},
        {"record_type": "programme", "category": "open-source-programmes", "programme_id": "o1"},
        {"record_type": "contribution", "category": "open-source-contributions", "contribution_id": "c1"},
        {"record_type": "programme", "category": "mystery", "programme_id": "m1"},
        {"url": "https://x/job", "is_live": True},
        {"url": "https://x/intern", "is_internship": True},
    ]
    return rows


class SplitCombineTests(unittest.TestCase):
    def test_split_assigns_expected_shards(self):
        parts = shards.split_rows(lake())
        self.assertEqual(len(parts["hackathons"]), 1)
        self.assertEqual(len(parts["fellowships"]), 1)
        self.assertEqual(len(parts["open_source"]), 2)
        self.assertEqual(len(parts["main"]), 1)  # unknown programme only
        self.assertEqual(len(parts["jobs-other"]), 2)  # job rows have no platform here
        self.assertEqual(sum(len(v) for v in parts.values()), 7)

    def test_roundtrip_loses_nothing(self):
        rows = lake()
        parts = shards.split_rows(rows)
        back = shards.combine(parts.pop("main"), parts)
        key = lambda r: json.dumps(r, sort_keys=True)
        self.assertEqual(sorted(map(key, back)), sorted(map(key, rows)))

    def test_present_shard_overrides_stale_main_copy(self):
        stale = {"record_type": "hackathon", "category": "hackathons", "hackathon_id": "old"}
        fresh = {"record_type": "hackathon", "category": "hackathons", "hackathon_id": "new"}
        out = shards.combine([stale, {"url": "j"}], {"hackathons": [fresh]})
        self.assertEqual([r.get("hackathon_id") for r in out if r.get("record_type")], ["new"])
        self.assertEqual(len(out), 2)

    def test_split_cli_dry_run_then_execute(self):
        with tempfile.TemporaryDirectory() as d:
            lp = os.path.join(d, "opportunities.json")
            sd = os.path.join(d, "shards")
            json.dump(lake(), open(lp, "w"))
            self.assertEqual(split_lake.main(["--lake", lp, "--shards-dir", sd]), 0)
            self.assertFalse(os.path.exists(sd))
            self.assertEqual(split_lake.main(["--lake", lp, "--shards-dir", sd, "--execute"]), 0)
            self.assertEqual(len(shards.load_shard("hackathons", sd)), 1)
            self.assertEqual(len(shards.load_whole_lake(lp, sd)), 7)

    def test_unknown_shard_rejected(self):
        with self.assertRaises(ValueError):
            shards.shard_path("jobs")


class DropGuardTests(unittest.TestCase):
    def test_blocks_big_drop(self):
        self.assertIsNotNone(shards.drop_guard(100, 40))

    def test_allows_small_drop_forced_and_tiny_shards(self):
        self.assertIsNone(shards.drop_guard(100, 60))
        self.assertIsNone(shards.drop_guard(100, 1, forced=True))
        self.assertIsNone(shards.drop_guard(5, 0))


class ScopedPublishTests(unittest.TestCase):
    def test_build_serving_scoped(self):
        rows = [r for r in lake()]
        for r in rows:
            r["is_live"] = True
        m = pub.build_serving(rows, "hackathons")
        self.assertEqual([x["type"] for x in m], ["hackathon"])

    def test_retire_never_touches_other_categories(self):
        existing = {"hackathon:a", "hackathon:b", "programme:fellow1", "job:abc",
                    "contribution:z"}
        retire, err = pub.plan_retire(existing, {"hackathon:a"}, "hackathons", True)
        self.assertEqual(retire, ["hackathon:b"])
        retire, _ = pub.plan_retire(existing, set(), "open_source", True)
        self.assertEqual(retire, ["contribution:z", "programme:fellow1"])
        # jobs are never retirable by a category run
        self.assertNotIn("job:abc", retire)

    def test_scoped_fetch_filters_server_side(self):
        class C(pub.Supabase):
            paths = []
            def _request(self, m, path, body=None, headers=None):
                self.paths.append(path)
                return 200, {}, "[]"
        c = C("https://e.test", "k")
        c.fetch_all_ids(shards.SHARD_SCOPES["fellowships"])
        self.assertIn("type=eq.programme", c.paths[0])
        self.assertIn("category=eq.fellowship", c.paths[0])

    def test_full_publish_retire_guard(self):
        existing = {"x:%d" % i for i in range(100)}
        _, err = pub.plan_retire(existing, {"x:1"}, None, False)
        self.assertIsNotNone(err)
        _, err = pub.plan_retire(existing, {"x:1"}, None, True)
        self.assertIsNone(err)
