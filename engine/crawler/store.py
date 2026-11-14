"""Local output: pages-<part>.jsonl records and summary.json."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional


class Store:
    def __init__(self, out: Path):
        self.out = out
        out.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def append(self, part: int, item: dict, result, page: Optional[Dict]) -> None:
        page = page or {}
        record = {
            "url": item["url"], "final_url": result.final_url, "host": item["host"],
            "part": part, "source": item["source"], "depth": item["depth"],
            "kind": item["kind"], "lead": item["lead"], "status_code": result.status,
            "outcome": result.outcome, "title": page.get("title"),
            "organiser": page.get("organiser"), "language": page.get("language"),
            "snippet": page.get("snippet"), "text": page.get("text"),
            "type_guess": page.get("type_guess"), "score": page.get("score"),
            "junk": page.get("junk"), "deadline": page.get("deadline"),
            "status": page.get("status"), "quote": page.get("quote"),
            "emails": page.get("emails", []), "out_links": len(page.get("links", [])),
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        with self._lock, open(self.out / "pages-{}.jsonl".format(part), "a") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    def write_summary(self, stats: Dict) -> None:
        (self.out / "summary.json").write_text(json.dumps(stats, indent=2, ensure_ascii=False))
