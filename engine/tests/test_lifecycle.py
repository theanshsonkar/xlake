import json
import os
import sys
import tempfile
import unittest
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import lifecycle, retire  # noqa: E402
from pipeline import publish_supabase, sweep  # noqa: E402
from tests.test_sweep_passthrough import TestSweepPassthrough  # noqa: E402

TODAY = date(2026, 11, 12)
NOW = "2026-11-12T10:00:00+00:00"
YESTERDAY = "2026-11-11"
TOMORROW = "2026-11-13"


def prog(**kw):
    r = {"record_type": "programme", "programme_id": "p1", "is_live": True,
         "programme_status": "open", "deadline": None}
    r.update(kw)
    return r


class InferTest(unittest.TestCase):
    def test_states(self):
        self.assertEqual(lifecycle.infer({"is_live": True}), "open")
        self.assertEqual(lifecycle.infer({}), "open")
        self.assertEqual(lifecycle.infer({"is_live": True, "programme_status": "upcoming"}), "upcoming")
        self.assertEqual(lifecycle.infer({"is_live": True, "status": "upcoming"}), "upcoming")
        self.assertEqual(lifecycle.infer({"is_live": False, "needs_confirmation": True}), "unverified")
        self.assertEqual(lifecycle.infer({"is_live": False}), "closed")


class ReconcileTest(unittest.TestCase):
    def test_bug_a_revived_row_loses_dead_stamps(self):
        r = {"is_live": True, "went_dead_at": "2026-10-01", "liveness_reason": "absent_from_board"}
        st = lifecycle.reconcile([r], TODAY, NOW)
        self.assertNotIn("went_dead_at", r)
        self.assertNotIn("liveness_reason", r)
        self.assertEqual(r["lifecycle"], "open")
        self.assertEqual(st["revived_cleaned"], 1)

    def test_live_row_drops_stale_liveness_hidden_reason_only(self):
        r = {"is_live": True, "hidden_reason": "closed_deadline_passed"}
        q = {"is_live": True, "hidden_reason": "not_an_opportunity"}
        lifecycle.reconcile([r, q], TODAY, NOW)
        self.assertIsNone(r["hidden_reason"])
        self.assertEqual(q["hidden_reason"], "not_an_opportunity")

    def test_sweep_merge_revival_clears_stamps(self):
        job = TestSweepPassthrough._job("https://jobs.example/acme/old", "T")
        job["is_live"] = True
        retire._retire(job, NOW, "absent_from_board")
        self.assertEqual(job["lifecycle"], "closed")
        fresh = TestSweepPassthrough._job("https://jobs.example/acme/old", "T")
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "o.json")
            json.dump([job], open(path, "w"))
            sweep._merge_store(path, [fresh], {("greenhouse", "acme")})
            merged = json.load(open(path))[0]
        self.assertTrue(merged["is_live"])
        for k in ("went_dead_at", "liveness_reason", "needs_confirmation"):
            self.assertNotIn(k, merged)

    def test_bug_b_open_programme_past_deadline_closes(self):
        r = prog(deadline=YESTERDAY)
        st = lifecycle.reconcile([r], TODAY, NOW)
        self.assertFalse(r["is_live"])
        self.assertEqual(r["lifecycle"], "closed")
        self.assertEqual(r["closed_reason"], "deadline_passed")
        self.assertEqual(r["programme_status"], "closed")
        self.assertEqual(r["hidden_reason"], "closed_deadline_passed")
        self.assertEqual(st["deadline_closed"], 1)

    def test_upcoming_with_past_deadline_stays(self):
        r = prog(programme_status="upcoming", deadline=YESTERDAY)
        lifecycle.reconcile([r], TODAY, NOW)
        self.assertEqual(r["lifecycle"], "upcoming")
        self.assertTrue(r["is_live"])

    def test_unverified_past_deadline_closes(self):
        r = prog(is_live=False, needs_confirmation=True, deadline=YESTERDAY)
        lifecycle.reconcile([r], TODAY, NOW)
        self.assertEqual(r["lifecycle"], "closed")
        self.assertFalse(r["needs_confirmation"])

    def test_future_deadline_and_datetime_form(self):
        a = prog(deadline=TOMORROW)
        b = prog(deadline=YESTERDAY + "T10:00:00Z")
        lifecycle.reconcile([a, b], TODAY, NOW)
        self.assertEqual(a["lifecycle"], "open")
        self.assertEqual(b["lifecycle"], "closed")

    def test_non_iso_deadline_unparsed_and_untouched(self):
        r = prog(deadline="rolling, see site")
        st = lifecycle.reconcile([r], TODAY, NOW)
        self.assertTrue(r["is_live"])
        self.assertEqual(st["deadline_unparsed"], 1)

    def test_closed_keeps_original_went_dead_at(self):
        r = {"is_live": False, "went_dead_at": "2026-09-01", "liveness_reason": "absent_from_board"}
        lifecycle.reconcile([r], TODAY, NOW)
        self.assertEqual(r["went_dead_at"], "2026-09-01")
        self.assertEqual(r["closed_at"], "2026-09-01")
        self.assertEqual(r["closed_reason"], "absent_from_board")
        lifecycle.close(r, NOW, "deadline_passed")
        self.assertEqual(r["went_dead_at"], "2026-09-01")


class VerificationGuardTest(unittest.TestCase):
    def test_past_deadline_not_forced_live(self):
        from categories.scholarships import scholarships
        self.assertTrue(lifecycle.deadline_passed({"deadline": "2000-01-01", "programme_status": "open"}))
        self.assertFalse(lifecycle.deadline_passed({"deadline": "2000-01-01", "programme_status": "upcoming"}))
        self.assertFalse(lifecycle.deadline_passed({"deadline": "2999-01-01"}))
        self.assertTrue(hasattr(scholarships, "lifecycle"))


class ServingInvariantTest(unittest.TestCase):
    def test_serving_unchanged_by_reconcile(self):
        today = date.today()
        past = (today - timedelta(days=2)).isoformat()
        future = (today + timedelta(days=5)).isoformat()
        rows = [
            prog(deadline=past), prog(deadline=future), prog(deadline=None),
            prog(programme_status="upcoming", deadline=past),
            prog(is_live=False, needs_confirmation=True, deadline=past),
            prog(is_live=False, needs_confirmation=True, deadline=future),
            {"is_live": False}, {"is_live": True, "deadline": past},
            {"is_live": True, "went_dead_at": "x"},
        ]
        before = [publish_supabase.is_serving(r) for r in rows]
        lifecycle.reconcile(rows, today, NOW)
        self.assertEqual(before, [publish_supabase.is_serving(r) for r in rows])


if __name__ == "__main__":
    unittest.main()


class OpeningDateTest(unittest.TestCase):
    def _life(self, today, **kw):
        r = prog(programme_status="opening_soon", opening_date="2026-11-15", opens_quote_dated=True, **kw)
        lifecycle.reconcile([r], today, NOW)
        return r

    def test_future_opening_is_upcoming(self):
        self.assertEqual(self._life(date(2026, 11, 14))["lifecycle"], "upcoming")
        r = prog(programme_status="rolling", opening_date="2027-01-10", opens_quote_dated=True)
        lifecycle.reconcile([r], TODAY, NOW)
        self.assertEqual(r["lifecycle"], "upcoming")

    def test_flips_open_on_opening_day(self):
        self.assertEqual(self._life(date(2026, 11, 15))["lifecycle"], "open")

    def test_past_deadline_still_closes(self):
        r = prog(opening_date="2026-01-01", deadline="2026-02-01")
        lifecycle.reconcile([r], TODAY, NOW)
        self.assertEqual(r["lifecycle"], "closed")

    def test_future_opening_old_deadline_not_closed(self):
        r = prog(opening_date="2027-01-01", opens_quote_dated=True, deadline="2026-02-01")
        lifecycle.reconcile([r], TODAY, NOW)
        self.assertEqual(r["lifecycle"], "upcoming")

    def test_undated_future_opening_stays_open(self):
        r = prog(programme_status="rolling", opening_date="2027-01-10", opens_quote_dated=False,
                 deadline="2027-03-01")
        lifecycle.reconcile([r], TODAY, NOW)
        self.assertEqual(r["lifecycle"], "open")
        self.assertEqual(r["deadline"], "2027-03-01")

    def test_stale_deadline_dropped_when_not_after_opening(self):
        for dl in ("2026-12-01", "2027-01-10"):
            r = prog(opening_date="2027-01-10", opens_quote_dated=True, deadline=dl)
            st = lifecycle.reconcile([r], TODAY, NOW)
            self.assertEqual(r["lifecycle"], "upcoming")
            self.assertIsNone(r["deadline"])
            self.assertEqual(st["stale_deadline_dropped"], 1)

    def test_deadline_after_opening_kept(self):
        r = prog(opening_date="2027-01-10", opens_quote_dated=True, deadline="2027-03-01")
        st = lifecycle.reconcile([r], TODAY, NOW)
        self.assertEqual(r["deadline"], "2027-03-01")
        self.assertEqual(st["stale_deadline_dropped"], 0)
