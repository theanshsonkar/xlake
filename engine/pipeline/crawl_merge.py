"""Merge crawl legs: python3 -m pipeline.crawl_merge --in out/seeds out/legs/* --out out/result"""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional

from crawler import funding, urls


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


def merge(dirs: List[Path], out: Path, today: Optional[date] = None) -> Dict:
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
    (out / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    return summary


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--in", dest="inputs", nargs="+", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    dirs = [d for d in args.inputs if d.is_dir()]
    skipped = [str(d) for d in args.inputs if not d.is_dir()]
    summary = merge(dirs, args.out)
    summary["legs_missing"] += skipped
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
