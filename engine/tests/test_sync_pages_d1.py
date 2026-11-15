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
