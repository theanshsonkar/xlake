import io
import os
import sqlite3
import sys
import tempfile
import json
import unittest
from contextlib import redirect_stdout
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline import sync_pages_d1 as sp  # noqa: E402
from pipeline.sync_d1 import D1Error  # noqa: E402


class Fake:
    def __init__(self):
        self.con = sqlite3.connect(":memory:")
        self.calls = []

    def db_id(self, name):
        return "x"

    def query(self, db, sql, params=None):
        self.calls.append(sql)
        before = self.con.total_changes
        if params is not None:
            try:
                cur = self.con.execute(sql, params)
            except sqlite3.OperationalError as e:
                raise D1Error(str(e))
            cols = [d[0] for d in cur.description or []]
            return [dict(zip(cols, r)) for r in cur.fetchall()], 0
        try:
            self.con.executescript(sql)
        except sqlite3.OperationalError as e:
            raise D1Error(str(e))
        return [], self.con.total_changes - before

    def writes(self):
        return [c for c in self.calls if c.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE", "CREATE"))]


def row(i, **kw):
    r = {"id": "page:%03d" % i, "url": "https://a.org/%d" % i, "site": "a.org", "title": "Fellowship %d" % i,
         "org": "Acme", "kind": "fellowship", "tags": ["startup"], "status": "open", "status_quote": "open now",
         "deadline": "2027-01-01", "summary": "s", "language": "en", "funding_date": None,
         "funding_quote": None, "funding_proof": None, "last_checked": "2026-11-15T00:00:00+00:00"}
    r.update(kw)
    return r


def q(f, sql, a=()):
    return f.con.execute(sql, a).fetchall()


class T(unittest.TestCase):
    def run_sync(self, f, rows, dead=(), **kw):
        return sp.sync(rows, list(dead), f, log=lambda *_: None, **kw)

    def test_insert_update_touch_delete(self):
        f = Fake()
        st = self.run_sync(f, [row(1), row(2), row(3)])
        self.assertEqual(st.c["insert"], 3)
        self.assertEqual(q(f, "SELECT count(*) FROM pages_fts")[0][0], 3)
        self.assertEqual(q(f, "SELECT first_seen FROM pages WHERE id='page:001'")[0][0], "2026-11-15T00:00:00+00:00")
        later = "2026-11-16T00:00:00+00:00"
        st = self.run_sync(f, [row(1, last_checked=later), row(2, title="Changed", last_checked=later),
                               row(3, status="closed", last_checked=later)], dead=["page:003"][:0])
        self.assertEqual((st.c["touch"], st.c["update"], st.c["insert"]), (1, 2, 0))
        self.assertEqual(q(f, "SELECT count(*) FROM pages_fts WHERE pages_fts MATCH 'Changed'")[0][0], 1)
        self.assertEqual(q(f, "SELECT first_seen FROM pages WHERE id='page:002'")[0][0], "2026-11-15T00:00:00+00:00")
        st = self.run_sync(f, [row(1, last_checked=later)], dead=["page:002", "page:999"])
        self.assertEqual(st.c["delete"], 1)
        self.assertEqual(q(f, "SELECT count(*) FROM pages")[0][0], 2)
        self.assertEqual(q(f, "SELECT count(*) FROM pages_fts")[0][0], 2)

    def test_unchanged_recent_not_touched(self):
        f = Fake()
        self.run_sync(f, [row(1)])
        st = self.run_sync(f, [row(1, last_checked="2026-11-15T05:00:00+00:00")])
        self.assertEqual(sum(st.c.values()), 0)

    def test_budget_deferral(self):
        f = Fake()
        st = self.run_sync(f, [row(i) for i in range(10)], max_writes=45)
        self.assertEqual((st.c["insert"], st.c["deferred"], st.writes), (5, 5, 45))
        self.assertEqual(q(f, "SELECT count(*) FROM pages")[0][0], 5)

    def test_pending_merge_and_deferral(self):
        merged = sp.merge_pending([row(1, title="New")], ["page:002"],
                                  [row(1, title="Old"), row(2), row(3)])
        by = {r["id"]: r for r in merged}
        self.assertEqual(by["page:001"]["title"], "New")
        self.assertNotIn("page:002", by)
        self.assertIn("page:003", by)

    def test_deferred_in_pending_written_not(self):
        f = Fake()
        st = self.run_sync(f, [row(i) for i in range(10)], max_writes=45)
        self.assertEqual(len(st.pending), 5)
        written = {r[0] for r in q(f, "SELECT id FROM pages")}
        self.assertFalse(written & {r["id"] for r in st.pending})
        self.assertIn("pending=5", st.line(False))

    def test_pending_rows_flow_into_sync(self):
        f = Fake()
        st = self.run_sync(f, [row(1)], pending_rows=[row(2), row(3)])
        self.assertEqual(st.c["insert"], 3)
        self.assertEqual(st.pending, [])

    def test_value_order(self):
        rows = [row(1, kind="other", status_quote=None), row(2, kind="grant", status_quote=None),
                row(3, kind="other", status_quote=None, funding_date="2026-01-01"),
                row(4, kind="other", status_quote="open")]
        f = Fake()
        self.run_sync(f, rows, max_writes=27)
        got = sorted(r[0] for r in q(f, "SELECT id FROM pages"))
        self.assertEqual(len(got), 3)
        self.assertNotIn("page:001", got)
        self.assertEqual([r["id"] for r in sp.value_sort(rows)],
                         ["page:004", "page:003", "page:002", "page:001"])

    def test_main_pending_file(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as pd:
            fake = Fake()
            open(os.path.join(d, "pages-merged.jsonl"), "w").write("".join(json.dumps(
                {"final_url": "https://a.org/%d" % i, "outcome": "ok", "title": "T%d" % i, "type_guess": "grant",
                 "fetched_at": "2026-11-15T00:00:00+00:00"}) + "\n" for i in range(6)))
            env = {"CLOUDFLARE_API_TOKEN": "t" * 40, "CLOUDFLARE_ACCOUNT_ID": "a"}
            with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(sp, "Client", lambda *a: fake), \
                    redirect_stdout(io.StringIO()):
                sp.main(["--in", d, "--pending", pd, "--dry-run", "--max-writes", "27"])
                self.assertFalse(os.path.exists(os.path.join(pd, "pages-pending.jsonl")))
                sp.main(["--in", d, "--pending", pd, "--dry-run", "--write-pending", "--max-writes", "27"])
                self.assertEqual(len(open(os.path.join(pd, "pages-pending.jsonl")).read().splitlines()), 3)

    def test_zero_rows(self):
        f = Fake()
        st = self.run_sync(f, [])
        self.assertEqual(f.calls, [])
        self.assertEqual(st.rows, 0)

    def test_dry_run_no_writes(self):
        f = Fake()
        st = self.run_sync(f, [row(1), row(2)], dry_run=True)
        self.assertEqual(st.c["insert"], 2)
        self.assertEqual(f.writes(), [])

    def test_main_no_token_plan_only(self):
        with tempfile.TemporaryDirectory() as d:
            open(os.path.join(d, "pages-merged.jsonl"), "w").write(json.dumps(
                {"final_url": "https://a.org/x", "outcome": "ok", "title": "T", "type_guess": "grant",
                 "fetched_at": "2026-11-15T00:00:00+00:00"}) + "\n")
            buf = io.StringIO()
            with mock.patch.dict(os.environ, {}, clear=True), redirect_stdout(buf):
                rc = sp.main(["--in", d])
        self.assertEqual(rc, 0)
        self.assertIn("no token: plan only, 1 rows ready", buf.getvalue())
        self.assertIn("pages sync: rows=1", buf.getvalue())

    def test_main_missing_file_exit_0(self):
        buf = io.StringIO()
        with mock.patch.dict(os.environ, {}, clear=True), redirect_stdout(buf):
            self.assertEqual(sp.main(["--in", "/nonexistent"]), 0)
        self.assertIn("rows=0", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
