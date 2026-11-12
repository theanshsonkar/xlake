import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from categories import programme_core as core
from core.recheck import programme_due

NOW = datetime(2026, 11, 12, 12, 0, tzinfo=timezone.utc)


def row(lifecycle=None, deadline=None, age=timedelta(0), **extra):
    r = {"is_live": True, "last_checked_at": (NOW - age).isoformat(), "deadline": deadline}
    if lifecycle:
        r["lifecycle"] = lifecycle
    r.update(extra)
    return r


class DueRules(unittest.TestCase):
    def test_new(self):
        self.assertEqual(programme_due(None, NOW), (True, "new"))
        self.assertEqual(programme_due({"is_live": True}, NOW), (True, "new"))
        self.assertEqual(programme_due({"last_checked_at": "garbage"}, NOW), (True, "new"))

    def test_open_near_daily(self):
        self.assertEqual(programme_due(row("open", "2026-11-20", timedelta(hours=23)), NOW), (True, "open_near"))
        self.assertEqual(programme_due(row("open", None, timedelta(hours=21)), NOW), (False, "open_near"))
        self.assertTrue(programme_due(row("unverified", "2026-11-26", timedelta(hours=22)), NOW)[0])

    def test_open_far_weekly(self):
        self.assertEqual(programme_due(row("open", "2027-02-01", timedelta(days=3)), NOW), (False, "open_far"))
        self.assertEqual(programme_due(row("open", "2027-02-01", timedelta(days=7)), NOW), (True, "open_far"))

    def test_upcoming_weekly(self):
        self.assertEqual(programme_due(row("upcoming", None, timedelta(days=6)), NOW), (False, "upcoming"))
        self.assertEqual(programme_due(row("upcoming", None, timedelta(days=7)), NOW), (True, "upcoming"))

    def test_closed_monthly(self):
        self.assertEqual(programme_due(row("closed", None, timedelta(days=29)), NOW), (False, "closed"))
        self.assertEqual(programme_due(row("closed", None, timedelta(days=30)), NOW), (True, "closed"))

    def test_lifecycle_inferred(self):
        r = row(None, None, timedelta(days=5), is_live=False)
        self.assertEqual(programme_due(r, NOW), (False, "closed"))


def _seed(i):
    return {"source_id": "s%d" % i, "programme_id": "s%d" % i, "programme_name": "Prog %d Fellowship" % i,
            "organizer": "O%d" % i, "official_url": "https://h%d.example/p" % i,
            "allowed_path_hints": [], "check_cadence": "daily"}


class CollectRecheck(unittest.TestCase):
    def _run(self, env=None):
        seeds = (_seed(1), _seed(2))
        cfg = core.ProgrammeConfig("fellowship", "fellowship", seeds, "", "")
        recent = datetime.now(timezone.utc).isoformat(timespec="seconds")
        skipped = {"record_type": "programme", "category": "fellowship", "programme_id": "s1",
                   "programme_name": "Prog 1 Fellowship", "official_url": "https://h1.example/p",
                   "is_live": False, "lifecycle": "closed", "programme_status": "closed",
                   "last_checked_at": recent, "first_seen": "2026-01-01T00:00:00+00:00"}
        fetched = []

        def fetch(url):
            if url.endswith("/p"):  # ignore hop fetches
                fetched.append(url)
            return "<html><body>Fellowship applications are accepted on a rolling basis. <a href='/apply'>Apply</a></body></html>", url

        with tempfile.TemporaryDirectory() as d, \
                mock.patch.dict(os.environ, env or {}), \
                mock.patch.object(core, "load_verifications", return_value=[]), \
                mock.patch.object(core, "recheck_official_urls", return_value={}):
            lake = os.path.join(d, "l.json")
            with open(lake, "w") as f:
                json.dump([skipped], f)
            core.collect(cfg, fetch=fetch, lake_path=lake, observations_path=os.path.join(d, "o.json"))
            with open(lake) as f:
                after = {r["programme_id"]: r for r in json.load(f)}
        return skipped, after, fetched

    def test_skipped_seed_untouched_and_not_retired(self):
        skipped, after, fetched = self._run()
        self.assertEqual(fetched, ["https://h2.example/p"])
        self.assertEqual(after["s1"], skipped)
        self.assertNotEqual(after["s1"].get("hidden_reason"), "source_removed")
        self.assertIn("s2", after)

    def test_recheck_all_fetches_everything(self):
        _, _, fetched = self._run({"XLAKE_RECHECK_ALL": "1"})
        self.assertEqual(sorted(fetched), ["https://h1.example/p", "https://h2.example/p"])


if __name__ == "__main__":
    unittest.main()
