"""Markdown review of crawled pages: python3 -m pipeline.crawl_review"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Dict, List

from crawler import urls


def source_domains(seeds: Path) -> frozenset:
    return frozenset(urls.registered_domain(s["url"]) for s in json.loads(seeds.read_text()))


def read_rows(out_dir: Path) -> List[Dict]:
    return [json.loads(line) for path in sorted(out_dir.glob("pages-*.jsonl"))
            for line in path.read_text().splitlines()]


def stats(rows: List[Dict]) -> Dict:
    out = Counter(r["outcome"] for r in rows)
    keys: set = set()
    duplicates = 0
    for r in rows:
        k = urls.key(r["final_url"])
        duplicates += r["outcome"] == "ok" and k in keys
        keys.add(k)
    led = [r for r in rows if r["outcome"] == "ok" and (r["lead"] or {}).get("domain")]
    careers = {r["url"]: r["lead"]["domain"] for r in led if r["type_guess"] == "careers"}
    return {
        "pages fetched": len(rows), "ok": out["ok"], "robots": out["robots"],
        "errors": out["http_error"] + out["network_error"] + out["parse_error"],
        "hosts": len({r["host"] for r in rows}),
        "unique startups": len({r["lead"]["domain"] for r in led if r["kind"] == "startup_home"}),
        "careers pages": len(careers), "careers startups": len(set(careers.values())),
        "junk": dict(Counter(r.get("junk_reason") for r in rows
                             if r["outcome"] == "ok" and r.get("junk_reason"))),
        "duplicates": duplicates,
    }


def _lead_match(r: Dict) -> bool:
    domain = (r["lead"] or {}).get("domain")
    return bool(domain) and urls.registered_domain(r["final_url"]) == domain


def top_pages(rows: List[Dict], top: int, exclude=frozenset()) -> List[Dict]:
    seen: set = set()
    kept = []
    for r in rows:
        k = urls.key(r["final_url"])
        if (r["outcome"] != "ok" or r["kind"] == "feed" or k in seen
                or urls.registered_domain(r["host"]) in exclude):
            continue
        seen.add(k)
        kept.append(r)
    kept.sort(key=lambda r: (bool(r.get("junk_reason") or r["junk"]), r["status"] == "closed",
                             -(r["score"] or 0), not _lead_match(r)))
    return kept[:top]


def render(rows: List[Dict], all_rows: List[Dict], title: str = "Crawl review") -> str:
    cell = lambda v, n=None: str(v or "").replace("|", "/").replace("\n", " ")[:n]
    st = stats(all_rows)
    lines = ["# " + title, "", "; ".join("{}: {}".format(k, v) for k, v in st.items()), "",
             "| rank | url | title | organiser | type | score | status | startup | snippet | real/junk |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for i, r in enumerate(rows, 1):
        lead = r["lead"] or {}
        startup = " ".join(x for x in (lead.get("name"), lead.get("domain")) if x)
        lines.append("| {} | {} | {} | {} | {} | {} | {} | {} | {} |  |".format(
            i, r["final_url"], cell(r["title"]), cell(r["organiser"]), r["type_guess"], r["score"],
            cell(r["status"]), cell(startup), cell(r["snippet"], 160)))
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--in", dest="src", type=Path, default=urls.DATA / "out")
    ap.add_argument("--seeds", type=Path, default=urls.DATA / "seeds.json")
    ap.add_argument("--keep-sources", action="store_true", help="keep pages on seed/feed domains")
    ap.add_argument("--top", type=int, default=200)
    ap.add_argument("--title", default="Crawl review")
    ap.add_argument("--out", type=Path, default=urls.DATA / "out" / "review.md")
    args = ap.parse_args(argv)
    rows = read_rows(args.src)
    exclude = frozenset() if args.keep_sources else source_domains(args.seeds)
    args.out.write_text(render(top_pages(rows, args.top, exclude), rows, args.title))
    print("wrote", args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
