import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawler import pagerow  # noqa: E402


def rec(**kw):
    r = {"url": "https://acme.org/apply", "final_url": "https://www.acme.org/apply", "outcome": "ok",
         "title": "Acme Fellowship 2027", "organiser": "Acme Foundation", "language": "en",
         "snippet": "Apply by email jo@acme.org or call +91 98765 43210 for the fellowship.",
         "type_guess": "fellowship", "junk": False, "status": "open", "quote": "Applications are open",
         "deadline": "2027-01-31", "tags": ["startup", "b"], "recheck": False, "status_code": 200,
         "fetched_at": "2026-11-15T10:00:00+00:00", "company_funding": None}
    r.update(kw)
    return r


class T(unittest.TestCase):
    def test_basic(self):
        r = pagerow.to_row(rec())
        self.assertTrue(r["id"].startswith("page:") and len(r["id"]) == 25)
        self.assertEqual((r["site"], r["status"], r["deadline"], r["org"]), ("acme.org", "open", "2027-01-31", "Acme Foundation"))
        self.assertEqual(r["tags"], ["b", "startup"])
        self.assertNotIn("@", r["summary"])
        self.assertNotIn("98765", r["summary"])

    def test_drops(self):
        for kw in ({"junk": True}, {"type_guess": None}, {"type_guess": "unknown"},
                   {"outcome": "failed"}, {"title": ""}):
            self.assertIsNone(pagerow.to_row(rec(**kw)), kw)

    def test_status_needs_quote(self):
        for s, want in (("open", "open"), ("opening_soon", "upcoming"), ("closed", "closed"), ("weird", "unverified")):
            self.assertEqual(pagerow.to_row(rec(status=s))["status"], want)
        r = pagerow.to_row(rec(quote=None))
        self.assertEqual((r["status"], r["deadline"], r["status_quote"]), ("unverified", None, None))

    def test_org_aggregator_rejected(self):
        self.assertIsNone(pagerow.to_row(rec(organiser="Unstop"))["org"])
        self.assertIsNone(pagerow.to_row(rec(organiser=None))["org"])

    def test_funding(self):
        cf = {"date": "2026-10-01", "quote": "raised $5M, write jo@x.com", "proof": "https://news.example/a"}
        r = pagerow.to_row(rec(company_funding=cf))
        self.assertEqual((r["funding_date"], r["funding_proof"]), ("2026-10-01", "https://news.example/a"))
        self.assertNotIn("@", r["funding_quote"])
        self.assertIsNone(pagerow.to_row(rec())["funding_date"])

    def test_rows_from_merged_dedupe_and_dead(self):
        dead = rec(final_url="https://gone.org/x", outcome="failed", status_code=404, recheck=True)
        did = pagerow.page_id("https://gone.org/x")
        lines = [rec(fetched_at="2026-11-15T09:00:00+00:00", title="Old"),
                 rec(fetched_at="2026-11-15T11:00:00+00:00", title="New"), dead,
                 rec(final_url="https://net.org/x", outcome="failed", status_code=None, recheck=True)]
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "pages-merged.jsonl")
            open(p, "w").write("\n".join(json.dumps(x) for x in lines) + "\nnot json\n")
            rows, dead_ids = pagerow.rows_from_merged(p)
        self.assertEqual([r["title"] for r in rows], ["New"])
        self.assertEqual(dead_ids, [did])

    def test_recheck_404_ok_record_is_dead(self):
        r = pagerow.to_row(rec(recheck=True, status_code=410))
        self.assertTrue(r["recheck_dead"])
        self.assertFalse(pagerow.to_row(rec(recheck=True, status_code=200))["recheck_dead"])


if __name__ == "__main__":
    unittest.main()
