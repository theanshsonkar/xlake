import io
import os
import sqlite3
import sys
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline import export_d1 as ex  # noqa: E402
from pipeline import sync_d1  # noqa: E402

JSHARD = "jobs-greenhouse"
T0 = datetime(2026, 11, 12, 8, 0, tzinfo=timezone.utc)


class FakeClient:
    def __init__(self):
        self.dbs = {}
        self.fail = None

    def con(self, title):
        if title not in self.dbs:
            c = sqlite3.connect(":memory:")
            c.executescript(ex.SCHEMA)
            self.dbs[title] = c
        return self.dbs[title]

    def query(self, title, sql, params=None):
        if self.fail:
            raise sync_d1.D1Error(self.fail)
        c = self.con(title)
        before = c.total_changes
        try:
            if params is not None:
                cur = c.execute(sql, params)
                cols = [d[0] for d in cur.description or []]
                return [dict(zip(cols, r)) for r in cur.fetchall()], 0
            if sql.startswith("ALTER"):
                c.execute(sql)
            else:
                c.executescript(sql)
        except sqlite3.OperationalError as e:
            raise sync_d1.D1Error(str(e))
        c.commit()
        return [], c.total_changes - before

    def q(self, title, sql, args=()):
        return self.con(title).execute(sql, args).fetchall()


def job(i, last_seen=T0, **kw):
    r = {"platform": "greenhouse", "token": "acme", "job_id": str(i), "title": "Software Engineer %d" % i,
         "company_name": "Acme", "url": "https://boards.greenhouse.io/acme/jobs/%d" % i,
         "is_live": True, "last_seen": last_seen.isoformat(), "location": "Bengaluru",
         "level": "intern" if kw.pop("intern", False) else "entry", "workplace": "hybrid"}
    r.update(kw)
    return r


def prog(pid="f1", **kw):
    r = {"record_type": "programme", "category": "fellowship", "programme_id": pid,
         "programme_name": "Test Fellowship " + pid, "organizer": "Test Foundation",
         "official_url": "https://test.org/" + pid, "application_url": "https://test.org/apply",
         "is_live": True, "last_checked_at": T0.isoformat()}
    r.update(kw)
    return r


class SyncD1Test(unittest.TestCase):
    def setUp(self):
        self.c = FakeClient()

    def run_sync(self, rows, shard=JSHARD, now=T0, **kw):
        return sync_d1.sync(shard, self.c, rows=rows, now=now, log=lambda *_: None, **kw)

    def jobs(self, sql="SELECT COUNT(*) FROM opportunities"):
        return self.c.q("xlake-jobs", sql)

    def test_first_sync_inserts_second_is_noop(self):
        rows = [job(1), job(2)]
        s = self.run_sync(rows)
        self.assertEqual(s.c["inserted"], 2)
        self.assertEqual(self.jobs(), [(2,)])
        self.assertEqual(self.jobs("SELECT COUNT(*) FROM opportunities_fts"), [(2,)])
        self.assertEqual(self.jobs("SELECT DISTINCT src FROM opportunities"), [(JSHARD,)])
        self.assertGreater(s.reported, 0)
        s2 = self.run_sync(rows)
        self.assertEqual((s2.est, s2.reported), (0, 0))

    def test_changed_title_updates_fts(self):
        self.run_sync([job(1)])
        self.run_sync([job(1, title="Platform Engineer")])
        self.assertEqual(self.jobs("SELECT title FROM opportunities"), [("Platform Engineer",)])
        self.assertEqual(self.jobs("SELECT COUNT(*) FROM opportunities_fts WHERE opportunities_fts MATCH 'Platform'"), [(1,)])
        self.assertEqual(self.jobs("SELECT COUNT(*) FROM opportunities_fts"), [(1,)])

    def test_non_fts_change_skips_fts(self):
        self.run_sync([job(1)])
        s = self.run_sync([job(1, workplace="remote")])
        self.assertEqual(s.c["updated"], 1)
        self.assertEqual(self.jobs("SELECT workplace FROM opportunities"), [("remote",)])
        self.assertEqual(s.est, 3)

    def test_last_checked_touch_threshold(self):
        self.run_sync([job(1)])
        s = self.run_sync([job(1, last_seen=T0 + timedelta(hours=13))])
        self.assertEqual(s.est, 0)  # jobs: moved < 72h -> no write
        s = self.run_sync([job(1, last_seen=T0 + timedelta(hours=73))])
        self.assertEqual((s.c["touched"], s.c["updated"]), (1, 0))  # moved > 72h: 1 cheap write
        self.assertEqual(self.jobs("SELECT last_checked FROM opportunities")[0][0], (T0 + timedelta(hours=73)).isoformat())

    def test_removed_owned_row_deleted_foreign_kept(self):
        self.run_sync([job(1), job(2)])
        self.c.con("xlake-jobs").execute("UPDATE opportunities SET src='jobs-lever' WHERE id=(SELECT id FROM opportunities LIMIT 1)")
        foreign = self.jobs("SELECT id FROM opportunities WHERE src='jobs-lever'")[0][0]
        s = self.run_sync([job(3)])
        self.assertEqual(s.c["deleted"], 1)
        ids = {r[0] for r in self.jobs("SELECT id FROM opportunities")}
        self.assertIn(foreign, ids)
        self.assertEqual(len(ids), 2)
        self.assertEqual(self.jobs("SELECT COUNT(*) FROM opportunities_fts"), [(2,)])

    def _bulk(self, db, rows, shard):
        self.c.con(db)
        self.run_sync(rows, shard=shard)
        c = self.c.con(db)
        c.execute("UPDATE opportunities SET src=NULL, h=NULL")
        c.commit()

    def test_null_src_single_source_claim_and_delete(self):
        self._bulk("xlake-fellowships", [prog("a"), prog("b")], "fellowships")
        s = self.run_sync([prog("a")], shard="fellowships")
        self.assertEqual((s.c["claimed"], s.c["deleted"]), (1, 1))
        self.assertEqual(self.c.q("xlake-fellowships", "SELECT src FROM opportunities"), [("fellowships",)])

    def test_null_src_multi_source_deletes_only_old(self):
        self._bulk("xlake-jobs", [job(1), job(2), job(3)], JSHARD)
        c = self.c.con("xlake-jobs")
        ids = [r[0] for r in c.execute("SELECT id FROM opportunities ORDER BY id")]
        c.execute("UPDATE opportunities SET last_checked=? WHERE id=?", ((T0 - timedelta(days=10)).isoformat(), ids[0]))
        c.execute("UPDATE opportunities SET last_checked=? WHERE id=?", ((T0 - timedelta(days=2)).isoformat(), ids[1]))
        c.commit()
        rows = [job(i) for i in (1, 2, 3)]
        cur = {r["id"] for r in ex.route(rows)["jobs"]}
        self.assertEqual(cur, set(ids))
        # only job 3 is still served by this shard; 1 (old) deleted, 2 (recent) kept
        s = self.run_sync([job(3)])
        self.assertEqual(s.c["deleted"], 1)
        left = {r[0] for r in c.execute("SELECT id FROM opportunities")}
        self.assertEqual(left, {ids[1], ids[2]})

    def test_foreign_id_skipped(self):
        self.run_sync([job(1)])
        s = self.run_sync([job(1)], shard="jobs-lever")
        self.assertEqual((s.c["foreign"], s.c["inserted"]), (1, 0))
        self.assertEqual(self.jobs("SELECT src FROM opportunities"), [(JSHARD,)])
        self.assertEqual(self.jobs("SELECT COUNT(*) FROM opportunities_fts"), [(1,)])

    def test_budget_stops_and_resumes(self):
        rows = [job(i) for i in range(5)]
        s = self.run_sync(rows, max_writes=20)
        self.assertEqual(s.c["inserted"], 2)
        self.assertEqual(s.c["skipped_budget"], 3)
        s = self.run_sync(rows, max_writes=20)
        self.assertEqual(s.c["inserted"], 2)
        s = self.run_sync(rows, max_writes=100)
        self.assertEqual(self.jobs(), [(5,)])

    def test_missing_token_skips(self):
        out = io.StringIO()
        with mock.patch.dict(os.environ, {}, clear=True), redirect_stdout(out):
            self.assertEqual(sync_d1.main(["--shard", JSHARD]), 0)
        self.assertIn("skipped: no CLOUDFLARE_API_TOKEN", out.getvalue())

    def test_api_error_exits_zero(self):
        out = io.StringIO()
        self.c.fail = "daily limit"
        env = {"CLOUDFLARE_API_TOKEN": "t" * 40, "CLOUDFLARE_ACCOUNT_ID": "a"}
        with mock.patch.dict(os.environ, env), \
                mock.patch.object(sync_d1, "Client", lambda *a: self.c), \
                mock.patch.object(sync_d1.shards, "load_shard", lambda n: [job(1)]), \
                redirect_stdout(out):
            self.assertEqual(sync_d1.main(["--shard", JSHARD]), 0)
        self.assertIn("daily limit", out.getvalue())

    def test_dry_run_writes_nothing(self):
        s = self.run_sync([job(1)], dry_run=True)
        self.assertEqual(s.c["inserted"], 1)
        self.assertEqual(self.jobs(), [(0,)])



class CleanTokenTest(unittest.TestCase):
    def test_extra_lines_and_spaces(self):
        from pipeline.sync_d1 import clean_token
        tok = "a" * 40
        self.assertEqual(clean_token(tok + "\n"), tok)
        self.assertEqual(clean_token("  %s  \ncurl -X GET https://x" % tok), tok)
        self.assertEqual(clean_token("Bearer\n" + tok), tok)
        self.assertEqual(clean_token("short\n"), "")
        cmd = 'curl "https://api.cloudflare.com/client/v4/user/tokens/verify" \\\n     -H "Authorization: Bearer %s"' % tok
        self.assertEqual(clean_token(cmd), tok)



class DeleteGuardTest(unittest.TestCase):
    def test_sharp_drop_never_removes_rows(self):
        from datetime import datetime, timezone
        from pipeline import sync_d1 as sd
        now = datetime(2026, 11, 13, tzinfo=timezone.utc)
        existing = {"p:%d" % i: {"id": "p:%d" % i, "src": "grants", "h": "x"} for i in range(100)}
        cur = [{"id": "p:%d" % i} for i in range(10)]  # 90% would vanish
        st = sd.Stats()
        plan = sd._plan("grants", "grants", cur, existing, now, set(), st)
        self.assertFalse([k for k, _, _ in plan if k == "delete"])
        self.assertEqual(st.c.get("guarded_deletes"), 90)

    def test_normal_churn_still_removes(self):
        from datetime import datetime, timezone
        from pipeline import sync_d1 as sd
        now = datetime(2026, 11, 13, tzinfo=timezone.utc)
        existing = {"p:%d" % i: {"id": "p:%d" % i, "src": "grants", "h": "x"} for i in range(100)}
        cur = [{"id": "p:%d" % i} for i in range(95)]
        plan = sd._plan("grants", "grants", cur, existing, now, set(), sd.Stats())
        self.assertEqual(len([k for k, _, _ in plan if k == "delete"]), 5)

    def _guarded(self, cleanup):
        from datetime import datetime, timezone
        from pipeline import sync_d1 as sd
        now = datetime(2026, 11, 13, tzinfo=timezone.utc)
        existing = {"p:%d" % i: {"id": "p:%d" % i, "src": "grants", "h": "x"} for i in range(100)}
        cur = [{"id": "p:%d" % i} for i in range(10)]
        explained = {"p:%d" % i: ("t", "grant_for_organisations") for i in range(10, 40)}
        st = sd.Stats()
        plan = sd._plan("grants", "grants", cur, existing, now, set(), st, cleanup, explained)
        return [i["id"] for k, i, _ in plan if k == "delete"], st

    def test_cleanup_deletes_only_explained_rows_when_guard_trips(self):
        ids, st = self._guarded(True)
        self.assertEqual(sorted(ids), sorted("p:%d" % i for i in range(10, 40)))
        self.assertEqual(st.c.get("guarded_deletes"), 60)

    def test_no_cleanup_deletes_nothing_when_guard_trips(self):
        ids, _ = self._guarded(False)
        self.assertEqual(ids, [])


if __name__ == "__main__":
    unittest.main()
