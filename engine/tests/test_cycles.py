import os
import sys
import unittest
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import cycles  # noqa: E402
from pipeline import backfill_cycles, rowshape  # noqa: E402

TODAY = date(2026, 11, 12)


def prog(**kw):
    r = {"record_type": "programme", "programme_id": "p1", "is_live": True}
    r.update(kw)
    return r


class RecordTest(unittest.TestCase):
    def test_basic_and_idempotent(self):
        r = prog(deadline="2026-12-01", opening_date="2026-10-01", last_deadline="2025-12-01")
        self.assertTrue(cycles.record(r, TODAY))
        self.assertEqual([c["deadline"] for c in r["cycles"]], ["2025-12-01", "2026-12-01"])
        self.assertEqual(r["cycles"][1]["opens"], "2026-10-01")
        self.assertFalse(cycles.record(r, TODAY))

    def test_merge_fills_opens_keeps_first_seen(self):
        r = prog(deadline="2026-12-01")
        cycles.record(r, date(2026, 11, 1))
        r["opening_date"] = "2026-10-01"
        self.assertTrue(cycles.record(r, TODAY))
        self.assertEqual(len(r["cycles"]), 1)
        self.assertEqual(r["cycles"][0]["opens"], "2026-10-01")
        self.assertEqual(r["cycles"][0]["first_seen"], "2026-11-01")

    def test_cap_and_non_iso(self):
        r = prog(deadline="March 5")
        self.assertFalse(cycles.record(r, TODAY))
        r = prog(cycles=[{"opens": None, "deadline": "%d-03-01" % y, "first_seen": "2026-01-01"}
                         for y in range(2010, 2022)], deadline="2026-12-01")
        cycles.record(r, TODAY)
        self.assertEqual(len(r["cycles"]), 10)
        self.assertEqual(r["cycles"][-1]["deadline"], "2026-12-01")

    def test_non_programme_untouched(self):
        for rt in ("job", "internship", "contribution"):
            r = {"record_type": rt, "deadline": "2026-12-01"}
            self.assertFalse(cycles.record(r, TODAY))
            self.assertNotIn("cycles", r)


class PredictTest(unittest.TestCase):
    def test_annual_roll_forward(self):
        r = prog(cycles=[{"opens": "2024-02-01", "deadline": "2024-03-15", "first_seen": "x"},
                         {"opens": "2025-02-01", "deadline": "2025-03-15", "first_seen": "x"}])
        p = cycles.predict_next(r, TODAY)
        # opening is never shifted from last year's date; only opens_pattern sets it
        self.assertEqual(p, {"expected_opens": None, "expected_opens_precision": None,
                             "expected_deadline": "2027-03-15", "basis": "annual", "cycles_seen": 2})
        self.assertEqual(cycles.next_cycle_text(p), "Usually closes around 15 March (based on 2 past cycles)")

    def test_expected_opens_from_pattern(self):
        cyc = [{"opens": None, "deadline": "2024-03-15", "first_seen": "x"},
               {"opens": None, "deadline": "2025-03-15", "first_seen": "x"}]
        r = prog(cycles=cyc, opens_pattern={"month": 9, "day": None, "quote": "q", "url": "u"})
        p = cycles.predict_next(r, TODAY)
        self.assertEqual((p["expected_opens"], p["expected_opens_precision"]), ("2027-09-01", "month"))
        r = prog(cycles=cyc, opens_pattern={"month": 3, "day": 1, "quote": "q", "url": "u"})
        p = cycles.predict_next(r, TODAY)
        self.assertEqual((p["expected_opens"], p["expected_opens_precision"]), ("2027-03-01", None))
        r = prog(cycles=cyc, opens_pattern={"month": 12, "day": None, "quote": "q", "url": "u"}, lifecycle="upcoming")
        cycles.apply_prediction(r, TODAY)
        self.assertEqual((r["expected_opens"], r["expected_opens_precision"]), ("2026-12-01", "month"))

    def test_cycle_keeps_opens_quote(self):
        r = prog(opening_date="2026-10-01", deadline="2026-12-01",
                 official_evidence={"opening_date": {"quote": "Opens 1 October 2026", "url": "http://x"}})
        cycles.record(r, TODAY)
        c = r["cycles"][0]
        self.assertEqual((c["opens"], c["opens_quote"], c["opens_url"]), ("2026-10-01", "Opens 1 October 2026", "http://x"))
        old = prog(deadline="2026-12-01")  # legacy entries without quote still work
        cycles.record(old, TODAY)
        self.assertNotIn("opens_quote", old["cycles"][0])

    def test_opens_unknown_text(self):
        r = prog(lifecycle="upcoming", cycles=[{"opens": None, "deadline": "2026-03-15", "first_seen": "x"}])
        p = cycles.predict_next(r, TODAY)
        self.assertEqual(p["expected_deadline"], "2027-03-15")
        self.assertIsNone(p["expected_opens"])
        self.assertEqual(cycles.next_cycle_text(p),
                         "Last cycle suggests it closes around 15 March (based on 1 past cycle)")

    def test_no_guess_from_one_cycle_or_for_hackathons(self):
        one = [{"opens": None, "deadline": "2026-03-15", "first_seen": "x"}]
        self.assertIsNone(cycles.predict_next(prog(lifecycle="closed", cycles=one), TODAY))
        two = [{"opens": None, "deadline": "2025-03-15", "first_seen": "x"},
               {"opens": None, "deadline": "2026-03-15", "first_seen": "x"}]
        self.assertIsNone(cycles.predict_next({"record_type": "hackathon", "lifecycle": "upcoming",
                                               "cycles": two}, TODAY))
        self.assertIsNotNone(cycles.predict_next(prog(lifecycle="closed", cycles=two), TODAY))

    def test_non_annual_and_future(self):
        r = prog(cycles=[{"opens": None, "deadline": "2024-03-15", "first_seen": "x"},
                         {"opens": None, "deadline": "2025-09-15", "first_seen": "x"}])
        self.assertIsNone(cycles.predict_next(r, TODAY))
        r = prog(deadline="2026-12-01", cycles=[{"opens": None, "deadline": "2025-12-01", "first_seen": "x"}])
        self.assertIsNone(cycles.predict_next(r, TODAY))

    def test_apply_prediction(self):
        r = prog(lifecycle="upcoming", deadline="2026-03-15", next_cycle_hint="",
                 cycles=[{"opens": None, "deadline": "2026-03-15", "first_seen": "x"}])
        self.assertTrue(cycles.apply_prediction(r, TODAY))
        self.assertEqual(r["expected_deadline"], "2027-03-15")
        self.assertTrue(r["next_cycle_hint"])
        r2 = prog(lifecycle="open", expected_deadline="x", next_cycle_hint="Keep me")
        self.assertFalse(cycles.apply_prediction(r2, TODAY))
        self.assertNotIn("expected_deadline", r2)
        self.assertEqual(r2["next_cycle_hint"], "Keep me")


class OverdueTest(unittest.TestCase):
    def test_grace_boundary(self):
        # expected_opens 2026-10-13 -> exactly 30 days before TODAY: not yet overdue
        r = prog(lifecycle="upcoming", expected_opens="2026-10-13")
        self.assertFalse(cycles.overdue(r, TODAY))
        r["expected_opens"] = "2026-10-12"
        self.assertTrue(cycles.overdue(r, TODAY))

    def test_deadline_fallback(self):
        r = prog(lifecycle="closed", expected_deadline="2026-10-01")  # opens ~09-01
        self.assertTrue(cycles.overdue(r, TODAY))

    def test_open_or_no_prediction_never(self):
        self.assertFalse(cycles.overdue(prog(lifecycle="open", expected_opens="2026-01-01"), TODAY))
        self.assertFalse(cycles.overdue(prog(lifecycle="closed"), TODAY))
        self.assertFalse(cycles.overdue(
            prog(lifecycle="upcoming", expected_opens="2026-01-01", deadline="2026-12-01"), TODAY))

    def test_list_sorted_and_finalize_flag(self):
        a = prog(lifecycle="upcoming", title="A", official_url="u1", expected_opens="2026-06-01",
                 cycles=[{"deadline": "2025-07-01", "opens": "2025-06-01", "first_seen": "x"},
                         {"deadline": "2024-07-01", "opens": "2024-06-01", "first_seen": "x"}])
        self.assertEqual(cycles.overdue_list([a], TODAY), [("A", "u1", "2026-06-01")])
        rows = [dict(a, overdue=True, lifecycle="open", deadline="2027-01-01")]
        s = cycles.finalize(rows, TODAY)
        self.assertNotIn("overdue", rows[0])
        self.assertEqual(s["overdue"], 0)
        b = prog(lifecycle="upcoming", title="B", official_url="u2",
                 cycles=[{"deadline": "2025-03-01", "opens": "2025-02-01", "first_seen": "x"},
                         {"deadline": "2024-03-01", "opens": "2024-02-01", "first_seen": "x"}])
        s = cycles.finalize([b], TODAY)
        self.assertNotIn("overdue", b)  # prediction rolls forward, so not overdue


class IntegrationTest(unittest.TestCase):
    def test_finalize(self):
        rows = [prog(lifecycle="upcoming", deadline="2026-03-15"), {"record_type": "job"}]
        s = cycles.finalize(rows, TODAY)
        self.assertEqual(s, {"rows_with_history": 1, "changed": 1, "predicted": 1,
                                 "overdue": 0, "overdue_lines": []})
        self.assertNotIn("cycles", rows[1])

    def test_rowshape(self):
        r = prog(lifecycle="upcoming", category="fellowship", title="X Fellowship",
                 cycles=[{"opens": None, "deadline": "2025-03-15", "first_seen": "x"}])
        out = rowshape.to_standard(r)
        self.assertEqual(out["last_deadline"], "2025-03-15")
        self.assertTrue(out["next_cycle"].startswith("Last cycle suggests it closes around 15 March"))
        self.assertEqual(len(out), 26)

    def test_backfill(self):
        rows = [prog(programme_id="a", lifecycle="closed", deadline="2026-03-15"), prog(programme_id="b")]
        res = backfill_cycles.backfill(rows, {"b": ["2026-04-01"]}, TODAY)
        self.assertEqual((res["gain_history"], res["predicted"]), (2, 0))  # one closed cycle: no guess
        self.assertNotIn("cycles", rows[0])


if __name__ == "__main__":
    unittest.main()


class PatternOnlyTest(unittest.TestCase):
    def test_pattern_without_history(self):
        r = prog(lifecycle="upcoming", opens_pattern={"month": 9, "day": 1, "quote": "q", "url": "u"})
        self.assertTrue(cycles.apply_prediction(r, TODAY))
        self.assertEqual((r["expected_opens"], r["expected_deadline"]), ("2027-09-01", None))
        self.assertEqual(r["next_cycle_hint"], "Opens around September each year (official page)")
