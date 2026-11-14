import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tempfile
from pathlib import Path

from crawler.frontier import Frontier, part_of


class TestFrontier(unittest.TestCase):
    def test_dedupe_and_priority(self):
        f = Frontier(1)
        self.assertTrue(f.push("https://a.com/x?utm_medium=1", priority=1))
        self.assertFalse(f.push("https://a.com/x#frag", priority=9))
        f.push("https://a.com/y", priority=5)
        self.assertEqual(f.pop(0)["url"], "https://a.com/y")
        self.assertEqual(f.pop(0)["url"], "https://a.com/x")
        self.assertIsNone(f.pop(0))

    def test_part_is_stable_and_by_domain(self):
        self.assertEqual(part_of("https://a.acme.com/", 4), part_of("https://www.acme.com/z", 4))

    def test_save_load_keeps_queued_only(self):
        f = Frontier(2)
        f.push("https://a.com/1")
        f.push("https://b.com/2")
        f.mark("https://a.com/1", "fetched")
        with tempfile.TemporaryDirectory() as d:
            f.save(Path(d))
            g = Frontier(2)
            g.load(Path(d))
        popped = [g.pop(p) for p in (0, 1)]
        self.assertEqual([i["url"] for i in popped if i], ["https://b.com/2"])
        self.assertEqual(g.items["https://a.com/1"]["state"], "fetched")


if __name__ == "__main__":
    unittest.main()
