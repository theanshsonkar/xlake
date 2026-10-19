import os
import sys
import unittest
from datetime import date, datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pipeline import health_report as hr

TODAY = date(2026, 10, 20)
NOW = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)


def row(**kw):
    base = {"id": "x", "type": "programme", "category": "fellowship", "title": "T", "url": "https://a.org/t",
            "deadline": None, "description": "d", "funding": None, "last_checked": "2026-10-19T00:00:00Z",
            "is_live": True, "needs_confirmation": False, "logo": "https://l/x.png", "region": "Global"}
    base.update(kw)
    return base


class TestMetrics(unittest.TestCase):
    def test_grouping_and_counts(self):
        rows = [
            row(url="https://a.org/1"),
            row(url="https://a.org/2", is_live=False, needs_confirmation=True),
            row(url="https://a.org/3", is_live=False, needs_confirmation=False),  # not served
            row(type="hackathon", category=None, url="https://h/1"),
        ]
        m = hr.compute_metrics(rows, TODAY, NOW)
        self.assertEqual(set(m), {"fellowship", "hackathon"})
        self.assertEqual((m["fellowship"]["served"], m["fellowship"]["live"], m["fellowship"]["needs_confirmation"]), (2, 1, 1))

    def test_coverage_percentages(self):
        rows = [row(url="u1", deadline="2026-12-01", funding="$5k", logo=None),
                row(url="u2", description="", region=None)]
        p = hr.compute_metrics(rows, TODAY, NOW)["fellowship"]["pct"]
        self.assertEqual((p["deadline"], p["description"], p["funding"], p["logo"], p["region"]),
                         (50.0, 50.0, 50.0, 50.0, 50.0))

    def test_not_applicable_fields_for_jobs(self):
        p = hr.compute_metrics([row(type="job", category=None)], TODAY, NOW)["job"]["pct"]
        self.assertIsNone(p["deadline"])
        self.assertIsNone(p["funding"])

    def test_closing_and_past_deadline(self):
        rows = [row(url="a", deadline="2026-10-27"), row(url="b", deadline="2026-10-28"),
                row(url="c", deadline="2026-10-19"), row(url="d", deadline="2026-10-20")]
        m = hr.compute_metrics(rows, TODAY, NOW)["fellowship"]
        self.assertEqual((m["closing_7d"], m["past_deadline_served"]), (2, 1))

    def test_duplicates_and_stale(self):
        rows = [row(url="https://a.org/x/", title="Same  Title"), row(url="https://a.org/x", title="same title"),
                row(url="https://a.org/y", last_checked="2026-09-01T00:00:00Z"),
                row(url="https://a.org/z", last_checked=None)]
        m = hr.compute_metrics(rows, TODAY, NOW)["fellowship"]
        self.assertEqual(m["duplicates"], 1)
        self.assertEqual(m["stale_last_checked"], 2)


class TestChecks(unittest.TestCase):
    def test_drop_over_30_percent(self):
        cur = {"a": {"live": 69}, "b": {"live": 70}, "tiny": {"live": 0}}
        drops = hr.detect_drops(cur, {"a": 100, "b": 100, "tiny": 5, "gone": 50})
        self.assertEqual({d["category"] for d in drops}, {"a", "gone"})

    def test_workflow_freshness(self):
        runs = {"ok.yml": "2026-10-19T13:00:00Z", "old.yml": "2026-10-18T11:00:00Z", "never.yml": None}
        stale = {s["workflow"] for s in hr.check_workflow_freshness(runs, NOW)}
        self.assertEqual(stale, {"old.yml", "never.yml"})

    def test_evaluate_collects_problems(self):
        metrics = hr.compute_metrics([row(deadline="2026-01-01")], TODAY, NOW)
        problems = hr.evaluate(metrics, {"fellowship": 100}, {"f.yml": None}, NOW)
        self.assertEqual(len(problems), 3)
        self.assertEqual(hr.evaluate({}, {}, {}, NOW), [])

    def test_fetch_paginates(self):
        pages = [[{"id": i} for i in range(hr.PAGE)], [{"id": "last"}]]
        calls = []
        out = hr.fetch_served_rows("https://s.example", "k", fetch=lambda url, h: calls.append(url) or pages[len(calls) - 1])
        self.assertEqual(len(out), hr.PAGE + 1)
        self.assertIn("offset=1000", calls[1])

    def test_history_roundtrip(self):
        import tempfile
        path = os.path.join(tempfile.mkdtemp(), "h.json")
        hr.save_history(hr.load_history(path), {"ts": "t", "live": {"a": 1}}, path)
        self.assertEqual(hr.load_history(path)[-1]["live"], {"a": 1})


if __name__ == "__main__":
    unittest.main()
