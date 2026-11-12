import json
import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline import export_d1  # noqa: E402


def job(i, **kw):
    r = {"platform": "greenhouse", "token": "acme", "job_id": str(i), "title": "Software Engineer %d" % i,
         "company_name": "Acme", "url": "https://boards.greenhouse.io/acme/jobs/%d" % i,
         "is_live": True, "last_seen": "2026-11-12T08:00:00+00:00", "location": "Bengaluru",
         "level": "intern", "workplace": "hybrid"}
    r.update(kw)
    return r


def prog(**kw):
    r = {"record_type": "programme", "category": "fellowship", "programme_id": "f1",
         "programme_name": "Test Fellowship", "organizer": "Test Foundation",
         "official_url": "https://test.org/f", "application_url": "https://test.org/apply",
         "is_live": True, "last_checked_at": "2026-11-12T08:00:00+00:00"}
    r.update(kw)
    return r


class ExportD1Test(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.shards = os.path.join(self.tmp.name, "shards")
        self.out = os.path.join(self.tmp.name, "out")
        os.makedirs(self.shards)

    def write(self, name, rows):
        with open(os.path.join(self.shards, name + ".json"), "w") as f:
            json.dump(rows, f)

    def query(self, name, sql, args=()):
        con = sqlite3.connect(os.path.join(self.out, name + ".db"))
        try:
            return con.execute(sql, args).fetchall()
        finally:
            con.close()

    def test_schema_creates(self):
        con = sqlite3.connect(":memory:")
        con.executescript(export_d1.SCHEMA)
        names = {r[0] for r in con.execute("select name from sqlite_master")}
        self.assertIn("opportunities", names)
        self.assertIn("opportunities_fts", names)

    def test_export_routing_and_exclusion(self):
        self.write("jobs-greenhouse", [job(1, level="senior"), job(2, is_live=False), job(3, level="entry")])
        self.write("fellowships", [prog()])
        rep = export_d1.export(self.shards, self.out, sqlite=True)
        self.assertEqual(rep["fellowships"]["rows"], 1)
        ids = [r[0] for r in self.query("jobs", "select title from opportunities")]
        self.assertNotIn("Software Engineer 2", ids)  # not serving
        self.assertTrue(os.path.exists(os.path.join(self.out, "fellowships.sql")))
        self.assertEqual(self.query("fellowships", "select type from opportunities"), [("fellowship",)])

    def test_internship_routes_to_internships(self):
        self.write("jobs-internships", [job(7)])
        rep = export_d1.export(self.shards, self.out, sqlite=True)
        self.assertEqual(rep["internships"]["rows"] + rep["jobs"]["rows"], 1)
        for r in export_d1.route([job(7)])["internships"]:
            self.assertEqual(r["type"], "internship")

    def test_escaping_unicode_and_fts(self):
        self.write("fellowships", [prog(programme_name="O'Brien \"Fellowship\" Zürich; DROP TABLE x;--")])
        export_d1.export(self.shards, self.out, sqlite=True)
        t = self.query("fellowships", "select title from opportunities")[0][0]
        self.assertIn("O'Brien", t)
        self.assertIn("Zürich", t)
        hit = self.query("fellowships", "select id from opportunities_fts where opportunities_fts match 'zurich'")
        self.assertEqual(len(hit), 1)

    def test_batches_and_dedupe(self):
        self.write("jobs-greenhouse", [job(i) for i in range(250)] + [job(5, last_seen="2026-11-13T00:00:00+00:00")])
        sql = export_d1.build_sql(export_d1.route(export_d1.load_rows(self.shards))["jobs"])
        self.assertEqual(sql.count("INSERT INTO opportunities ("), 3)
        rep = export_d1.export(self.shards, self.out, sqlite=True)
        self.assertEqual(rep["jobs"]["rows"], 250)



class StatementSizeTest(unittest.TestCase):
    def test_no_statement_exceeds_d1_limit(self):
        from pipeline import export_d1
        big = [{c: None for c in export_d1.COLUMNS} for _ in range(50)]
        for i, r in enumerate(big):
            r.update(id="hackathon:%d" % i, type="hackathon", title="T" * 5000,
                     url="https://x.test/%d" % i, status="open")
        sql = export_d1.build_sql(big)
        for stmt in sql.split(";\n"):
            self.assertLess(len(stmt.encode("utf-8")), 100_000)


if __name__ == "__main__":
    unittest.main()
