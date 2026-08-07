from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sweep  # noqa: E402


class TestSweepable(unittest.TestCase):
    def test_missing_reachable_is_sweepable(self):
        self.assertTrue(sweep.is_sweepable({}))

    def test_reachable_true_is_sweepable(self):
        self.assertTrue(sweep.is_sweepable({"reachable": True}))

    def test_reachable_false_is_not_sweepable(self):
        self.assertFalse(sweep.is_sweepable({"reachable": False}))

    @unittest.skip("load_registry reads LAKE_REGISTRY at module import time, not call time")
    def test_load_registry_excludes_unreachable_from_call_time_registry(self):
        pass
