"""Markdown table of the top crawled pages by score: python3 -m pipeline.crawl_review"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from crawler import urls


def source_domains(seeds: Path) -> frozenset:
    return frozenset(urls.registered_domain(s["url"]) for s in json.loads(seeds.read_text()))


def top_pages(out_dir: Path, top: int, exclude=frozenset()):
    rows = []
    for path in sorted(out_dir.glob("pages-*.jsonl")):
        for line in path.read_text().splitlines():
            row = json.loads(line)
            if row["outcome"] == "ok" and not row["junk"] and row["kind"] != "feed" \
                    and urls.registered_domain(row["host"]) not in exclude:
                rows.append(row)
    rows.sort(key=lambda r: r["score"] or 0, reverse=True)
    return rows[:top]


def render(rows) -> str:
    cell = lambda v: str(v or "").replace("|", "/").replace("\n", " ")
    lines = ["| title | link | type | score | startup | lead source | snippet |", "|---|---|---|---|---|---|---|"]
    for r in rows:
        lead = r["lead"] or {}
        startup = " ".join(x for x in (lead.get("name"), lead.get("domain")) if x)
        lines.append("| {} | {} | {} | {} | {} | {} | {} |".format(
            cell(r["title"]), r["final_url"], r["type_guess"], r["score"], cell(startup),
            cell(lead.get("source")), cell(r["snippet"])))
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--in", dest="src", type=Path, default=urls.DATA / "out")
    ap.add_argument("--seeds", type=Path, default=urls.DATA / "seeds.json")
    ap.add_argument("--keep-sources", action="store_true", help="keep pages on seed/feed domains")
    ap.add_argument("--top", type=int, default=200)
    ap.add_argument("--out", type=Path, default=urls.DATA / "out" / "review.md")
    args = ap.parse_args(argv)
    args.out.write_text(render(top_pages(args.src, args.top,
                                         frozenset() if args.keep_sources else source_domains(args.seeds))))
    print("wrote", args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
