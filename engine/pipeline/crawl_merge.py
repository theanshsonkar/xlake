"""Merge crawl legs: python3 -m pipeline.crawl_merge --in out/seeds out/legs/* --out out/result"""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional

from crawler import funding, urls
from crawler.frontier import part_of

_STATE_RANK = {"fetched": 3, "failed": 2, "skipped": 1, "queued": 0}


def _better(new: Dict, cur: Dict) -> bool:
    rn, rc = _STATE_RANK.get(new.get("state"), 0), _STATE_RANK.get(cur.get("state"), 0)
    return rn > rc or (rn == rc and (new.get("at") or "") > (cur.get("at") or ""))


def merge_frontiers(dirs: List[Path], out: Path, parts: int = 8) -> Dict[str, int]:
    items: Dict[str, Dict] = {}
    for d in dirs:
        for path in sorted(Path(d).glob("frontier-*.jsonl")):
            for it in _lines(path):
                url = it.get("url")
                if not url:
                    continue
                cur = items.get(url)
                if cur is None:
                    items[url] = it
                    continue
                win, lose = (it, cur) if _better(it, cur) else (cur, it)
                win["retries"] = max(win.get("retries", 0), lose.get("retries", 0))
                if not (win.get("lead") or {}).get("funding") and (lose.get("lead") or {}).get("funding"):
                    win["lead"] = lose["lead"]
                items[url] = win
    fdir = out / "frontier"
    fdir.mkdir(parents=True, exist_ok=True)
    by_part: List[List[Dict]] = [[] for _ in range(parts)]
    for it in items.values():
        by_part[part_of(it["url"], parts)].append(it)
    for p, rows in enumerate(by_part):
        with open(fdir / "frontier-{}.jsonl".format(p), "w") as fh:
            for it in rows:
                fh.write(json.dumps(it, ensure_ascii=False) + "\n")
    return {"frontier_items": len(items),
            "frontier_queued": sum(1 for i in items.values() if i.get("state") == "queued")}


def _lines(path: Path):
    try:
        text = path.read_text()
    except OSError:
        return
    for line in text.splitlines():
        try:
            yield json.loads(line)
        except ValueError:
            continue  # a leg killed mid-write may leave a torn last line


def _add(total: Dict, key: str, value) -> None:
    if isinstance(value, bool):
        total[key] = bool(total.get(key)) or value
    elif isinstance(value, (int, float)):
        total[key] = total.get(key, 0) + value
    elif isinstance(value, dict):
        sub = total.setdefault(key, {})
        for k, v in value.items():
            _add(sub, k, v)


def merge(dirs: List[Path], out: Path, today: Optional[date] = None, parts: int = 8) -> Dict:
    today = today or date.today()
    out.mkdir(parents=True, exist_ok=True)
    seen: set = set()
    startups: Dict[str, Dict] = {}
    summary: Dict = {}
    ok_dirs: List[str] = []
    missing: List[str] = []
    pages = dupes = 0
    with open(out / "pages-merged.jsonl", "w") as fh:
        for d in dirs:
            d = Path(d)
            try:
                stats = json.loads((d / "summary.json").read_text())
                ok_dirs.append(str(d))
                for k, v in stats.items():
                    _add(summary, k, v)
            except (OSError, ValueError):
                missing.append(str(d))
            for path in sorted(d.glob("pages-*.jsonl")):
                for rec in _lines(path):
                    if rec.get("outcome") == "ok":
                        k = urls.key(rec.get("final_url") or "")
                        if k in seen:
                            dupes += 1
                            continue
                        seen.add(k)
                    fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    pages += 1
            for row in _lines(d / "startups.jsonl"):
                dom = row.get("domain")
                if not dom:
                    continue
                cur = startups.get(dom)
                if cur is None:
                    startups[dom] = row
                    row["careers_urls"] = sorted(set(row.get("careers_urls") or ()))
                    continue
                cur["careers_urls"] = sorted(set(cur.get("careers_urls") or ()) | set(row.get("careers_urls") or ()))
                if not cur.get("name"):
                    cur["name"] = row.get("name")
                ev = funding.best(cur.get("funding"), row.get("funding"))
                cur["funding"] = ev
    rows = []
    for r in startups.values():
        r["startup"] = funding.is_recent(r.get("funding"), today)
        rows.append(r)
    rows.sort(key=lambda r: (r.get("funding") or {}).get("date", ""), reverse=True)
    with open(out / "startups.jsonl", "w") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    summary.update(legs_ok=ok_dirs, legs_missing=missing, merged_pages=pages,
                   merged_duplicates=dupes, merged_startups=len(rows))
    summary.update(merge_frontiers(dirs, out, parts))
    summary["dead_link_share"] = (summary.get("recheck_dead", 0) / summary["rechecked"]
                                 if summary.get("rechecked") else 0)
    (out / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    return summary


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--in", dest="inputs", nargs="+", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--parts", type=int, default=8)
    args = ap.parse_args(argv)
    dirs = [d for d in args.inputs if d.is_dir()]
    skipped = [str(d) for d in args.inputs if not d.is_dir()]
    summary = merge(dirs, args.out, parts=args.parts)
    summary["legs_missing"] += skipped
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
