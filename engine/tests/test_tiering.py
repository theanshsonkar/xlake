"""Tests for tiering.py — pure functions over synthetic sweep history.

No network, no registry.json dependency (state is constructed in-memory).
"""

import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tiering import (  # noqa: E402
    BoardHistory,
    per_board_yield,
    tier_for,
    sweep_due,
    record_sweep,
)


class TestPerBoardYield(unittest.TestCase):
    def test_never_swept_is_none_not_zero(self):
        h = BoardHistory(platform="greenhouse", token="x", sweeps_run=0)
        self.assertIsNone(per_board_yield(h))

    def test_yield_is_total_over_sweeps(self):
        h = BoardHistory(platform="keka", token="x",
                          total_qualifying_ever=38, sweeps_run=1)
        self.assertAlmostEqual(per_board_yield(h), 38.0)

    def test_matches_readme_measured_keka_ratio(self):
        # README.md: 38 qualifying roles across the July sweep of 311 Keka
        # boards, i.e. a per-board average, not a per-sweep count for one
        # board. This test only checks the arithmetic primitive is sane; it
        # is NOT a claim that this new engine has reproduced that number.
        h = BoardHistory(platform="keka", token="aggregate",
                          total_qualifying_ever=38, sweeps_run=311)
        self.assertAlmostEqual(per_board_yield(h), 38 / 311, places=6)


class TestTierFor(unittest.TestCase):
    def test_unmeasured_board_is_cold_not_hot(self):
        h = BoardHistory(platform="workday", token="new", sweeps_run=0)
        self.assertEqual(tier_for(h), "cold")

    def test_recent_production_is_hot(self):
        h = BoardHistory(platform="keka", token="jupiter", sweeps_run=5,
                          total_qualifying_ever=3, qualifying_last_30d=1)
        self.assertEqual(tier_for(h), "hot")

    def test_past_but_not_recent_production_is_warm(self):
        h = BoardHistory(platform="greenhouse", token="druva", sweeps_run=10,
                          total_qualifying_ever=2, qualifying_last_30d=0)
        self.assertEqual(tier_for(h), "warm")

    def test_verified_but_zero_ever_is_cold_not_dead(self):
        # This is the Citadel bug from REGISTRY-PLAN.md section 2.1: a board
        # that works and returns 0 qualifying roles is EMPTY, not DEAD.
        # tier_for() must never return 'dead' — that's resolve.py's call.
        h = BoardHistory(platform="lever", token="citadel", sweeps_run=20,
                          total_qualifying_ever=0, qualifying_last_30d=0)
        self.assertEqual(tier_for(h), "cold")
        self.assertNotEqual(tier_for(h), "dead")


class TestSweepDue(unittest.TestCase):
    def test_never_swept_is_always_due(self):
        h = BoardHistory(platform="keka", token="x", sweeps_run=0)
        self.assertTrue(sweep_due(h))

    def test_hot_board_not_due_within_6_hours(self):
        now = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
        h = BoardHistory(platform="keka", token="x", sweeps_run=5,
                          total_qualifying_ever=3, qualifying_last_30d=1,
                          last_swept_at=(now - timedelta(hours=2)).isoformat(
                              timespec="seconds"))
        self.assertFalse(sweep_due(h, now=now))

    def test_hot_board_due_after_6_hours(self):
        now = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
        h = BoardHistory(platform="keka", token="x", sweeps_run=5,
                          total_qualifying_ever=3, qualifying_last_30d=1,
                          last_swept_at=(now - timedelta(hours=7)).isoformat(
                              timespec="seconds"))
        self.assertTrue(sweep_due(h, now=now))

    def test_cold_board_not_due_after_only_a_day(self):
        now = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
        h = BoardHistory(platform="lever", token="citadel", sweeps_run=20,
                          total_qualifying_ever=0,
                          last_swept_at=(now - timedelta(hours=25)).isoformat(
                              timespec="seconds"))
        self.assertFalse(sweep_due(h, now=now))

    def test_cold_board_due_after_a_week(self):
        now = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
        h = BoardHistory(platform="lever", token="citadel", sweeps_run=20,
                          total_qualifying_ever=0,
                          last_swept_at=(now - timedelta(days=8)).isoformat(
                              timespec="seconds"))
        self.assertTrue(sweep_due(h, now=now))


class TestRecordSweep(unittest.TestCase):
    def test_new_board_gets_created_on_first_record(self):
        state = {}
        record_sweep(state, "greenhouse", "vercel", qualifying_count=2)
        h = state["greenhouse|vercel"]
        self.assertEqual(h.sweeps_run, 1)
        self.assertEqual(h.total_qualifying_ever, 2)

    def test_repeated_sweeps_accumulate(self):
        state = {}
        record_sweep(state, "keka", "jupiter", qualifying_count=1)
        record_sweep(state, "keka", "jupiter", qualifying_count=3)
        h = state["keka|jupiter"]
        self.assertEqual(h.sweeps_run, 2)
        self.assertEqual(h.total_qualifying_ever, 4)


if __name__ == "__main__":
    unittest.main()
