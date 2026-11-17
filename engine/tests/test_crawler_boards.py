import json
import os
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawler.boards import BoardCollector, board_of
from crawler.fetch import Fetcher
from crawler.frontier import Frontier
from crawler.run import Crawler
from crawler.store import Store
from pipeline import admit_boards, crawl_merge
from test_admit_boards import FakeVerifier


class TestBoardOf(unittest.TestCase):
    def test_platforms(self):
        cases = {
            "https://job-boards.greenhouse.io/acme/jobs/1": ("greenhouse", "acme"),
            "https://jobs.lever.co/foo": ("lever", "foo"),
            "https://jobs.ashbyhq.com/bar/abc": ("ashby", "bar"),
            "https://apply.workable.com/baz/": ("workable", "baz"),
            "https://qux.recruitee.com/o/x": ("recruitee", "qux"),
            "https://acme.keka.com/careers": ("keka", "acme"),
            "https://jobs.smartrecruiters.com/Corp": ("smartrecruiters", "Corp"),
        }
        for url, (plat, tok) in cases.items():
            b = board_of(url)
            self.assertEqual((b["platform"], b["token"]), (plat, tok), url)
            self.assertEqual(b["url"], url)

    def test_workday(self):
        b = board_of("https://acme.wd1.myworkdayjobs.com/en-US/Careers")
        self.assertEqual(b["token"], "acme.wd1.myworkdayjobs.com|acme|Careers")

    def test_none(self):
        self.assertIsNone(board_of("https://example.com/careers"))
        self.assertIsNone(board_of("https://boards.greenhouse.io/embed/job_board.js"))
        self.assertIsNone(board_of(""))


HOME = ("<html><head><title>Acme</title></head><body>"
        "<a href='https://jobs.lever.co/acme'>Jobs</a>"
        "<a href='https://boards.greenhouse.io/acme'>More</a></body></html>")


class TestCollect(unittest.TestCase):
    def test_crawler_collects_from_links_and_dedupes(self):
        def fake(url, polite=True):
            return (200, url, HOME, None) if url == "https://acme.test/" else (404, url, "", "http_404")
        with tempfile.TemporaryDirectory() as tmp:
            c = Crawler(Frontier(1), Fetcher(10, 10, fake), Store(Path(tmp)), 1,
                        today=date(2026, 11, 14), sitemaps=False, commoncrawl=False)
            c.add_seeds([{"url": "https://acme.test/", "kind": "seed", "label": "x"}])
            c.run([0])
            rows = [json.loads(l) for l in (Path(tmp) / "boards.jsonl").read_text().splitlines()]
        self.assertEqual([(r["platform"], r["token"]) for r in rows],
                         [("greenhouse", "acme"), ("lever", "acme")])
        self.assertEqual(rows[0]["source_page"], "https://acme.test/")
        self.assertEqual(rows[0]["first_seen"], "2026-11-14")

    def test_collector_dedupes(self):
        c = BoardCollector(date(2026, 1, 1))
        c.add("https://a.test/", ["https://jobs.lever.co/x"])
        c.add("https://b.test/", ["https://jobs.lever.co/x/1"])
        self.assertEqual(len(c.rows()), 1)
        self.assertEqual(c.rows()[0]["source_page"], "https://a.test/")


class TestMergeAndAdmit(unittest.TestCase):
    def test_merge_dedupes_boards(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name, day in (("a", "2026-11-02"), ("b", "2026-11-01")):
                d = root / name
                d.mkdir()
                (d / "boards.jsonl").write_text(json.dumps(
                    {"platform": "lever", "token": "x", "first_seen": day}) + "\n")
            s = crawl_merge.merge([root / "a", root / "b"], root / "out", date(2026, 11, 14))
            rows = [json.loads(l) for l in (root / "out" / "boards.jsonl").read_text().splitlines()]
        self.assertEqual(s["merged_boards"], 1)
        self.assertEqual(rows[0]["first_seen"], "2026-11-01")

    def test_admit_reads_extra_candidates(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "b.jsonl")
            with open(path, "w") as fh:
                fh.write(json.dumps({"platform": "lever", "token": "newco"}) + "\n")
                fh.write(json.dumps({"platform": "personio", "token": "ignored"}) + "\n")
                fh.write("torn line\n")
            caches = {}
            self.assertEqual(admit_boards.load_extra_candidates(path, caches), 1)
        v = FakeVerifier({("lever", "newco"): {"count": 3, "location": "X",
                                               "postings": [type("P", (), {"title": "Software Intern", "meta": {}, "location": "X"})()]}})
        res = admit_boards.run_admission(caches, [], list_board_fn=v)
        self.assertEqual([e["token"] for e in res["admit_entries"]], ["newco"])
        self.assertEqual(v.calls, [("lever", "newco")])


if __name__ == "__main__":
    unittest.main()
