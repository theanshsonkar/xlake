"""Run the general crawler: python3 -m pipeline.crawl --max-pages 5000"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from crawler import urls
from crawler.fetch import Fetcher
from crawler.frontier import Frontier
from crawler.run import Crawler
from crawler.store import Store

ENGINE = Path(__file__).resolve().parents[1]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--max-pages", type=int, default=5000)
    ap.add_argument("--parts", type=int, default=1)
    ap.add_argument("--part", default="all", help="all or a part number")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--seeds", type=Path, default=urls.DATA / "seeds.json")
    ap.add_argument("--out", type=Path, default=urls.DATA / "out")
    ap.add_argument("--per-host", type=int, default=25)
    args = ap.parse_args(argv)

    frontier = Frontier(args.parts)
    frontier.load(args.out)
    crawler = Crawler(frontier, Fetcher(args.max_pages, args.per_host), Store(args.out), args.workers)
    crawler.add_seeds(json.loads(args.seeds.read_text()))
    parts = list(range(args.parts)) if args.part == "all" else [int(args.part)]
    stats = crawler.run(parts)
    for key, value in stats.items():
        print("{:>20}: {}".format(key, value))
    failed = [i["url"] for i in frontier.items.values()
              if i["kind"] in ("seed", "feed") and i["state"] == "failed"]
    for url in failed:
        print("seed failed:", url)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
