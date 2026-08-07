"""Tests for sweep.py's tier freshness gate."""

import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sweep  # noqa: E402
import tiering  # noqa: E402


class TestTieringDue(unittest.TestCase):
    def test_empty_state_is_due(self):
        self.assertTrue(sweep.is_due(
            {"platform": "keka", "token": "x"}, {}, ignore=False))

    def test_recently_swept_is_not_due(self):
        now = datetime.now(timezone.utc)
        history = tiering.BoardHistory(
            platform="keka", token="x", qualifying_last_30d=1,
            sweeps_run=1,
            last_swept_at=(now - timedelta(hours=1)).isoformat())
        state = {"keka|x": history}
        self.assertFalse(sweep.is_due(
            {"platform": "keka", "token": "x"}, state,
            now=now, ignore=False))

    def test_aged_state_is_due(self):
        now = datetime.now(timezone.utc)
        history = tiering.BoardHistory(
            platform="keka", token="x", qualifying_last_30d=1,
            sweeps_run=1,
            last_swept_at=(now - timedelta(hours=200)).isoformat())
        state = {"keka|x": history}
        self.assertTrue(sweep.is_due(
            {"platform": "keka", "token": "x"}, state,
            now=now, ignore=False))

    def test_ignore_tiers_forces_due(self):
        now = datetime.now(timezone.utc)
        history = tiering.BoardHistory(
            platform="keka", token="x", qualifying_last_30d=1,
            sweeps_run=1,
            last_swept_at=(now - timedelta(hours=1)).isoformat())
        state = {"keka|x": history}
        self.assertTrue(sweep.is_due(
            {"platform": "keka", "token": "x"}, state,
            now=now, ignore=True))


if __name__ == "__main__":
    unittest.main()
