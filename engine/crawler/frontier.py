"""URL queue: dedupe by normalised URL, priority heap per part, JSONL per part."""

from __future__ import annotations

import hashlib
import heapq
import json
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from crawler import urls

STATES = ("queued", "fetched", "failed", "skipped")
KINDS = ("seed", "feed", "page", "startup_home", "careers_link", "sitemap", "cc")


def part_of(url: str, parts: int) -> int:
    digest = hashlib.sha1(urls.registered_domain(url).encode()).hexdigest()
    return int(digest, 16) % parts


class Frontier:
    def __init__(self, parts: int = 1):
        self.parts = parts
        self.items: Dict[str, dict] = {}
        self._keys: set = set()
        self._heaps: List[list] = [[] for _ in range(parts)]
        self._n = 0  # tie-breaker keeps pops in insertion order

    def push(self, url: str, source: str = "", depth: int = 0, priority: float = 0,
             kind: str = "page", parent: Optional[str] = None, lead: Optional[dict] = None, hop: int = 0) -> bool:
        url = urls.normalise(url)
        if not url.startswith(("http://", "https://")) or urls.key(url) in self._keys:
            return False
        self._keys.add(urls.key(url))
        item = {"url": url, "host": urls.host(url), "source": source, "depth": depth,
                "priority": priority, "state": "queued", "parent": parent, "lead": lead,
                "kind": kind, "hop": hop}
        self.items[url] = item
        self._enqueue(item)
        return True

    def _enqueue(self, item: dict) -> None:
        self._n += 1
        part = part_of(item["url"], self.parts)
        heapq.heappush(self._heaps[part], (-item["priority"], self._n, item["url"]))

    def pop(self, part: int) -> Optional[dict]:
        heap = self._heaps[part]
        while heap:
            _, _, url = heapq.heappop(heap)
            item = self.items[url]
            if item["state"] == "queued":
                return item
        return None

    def has_queued(self, part: int) -> bool:
        return bool(self._heaps[part])

    def mark(self, url: str, state: str) -> None:
        assert state in STATES
        self.items[url]["state"] = state

    def parts_of(self) -> Iterable[int]:
        return range(self.parts)

    def save(self, out: Path) -> None:
        out.mkdir(parents=True, exist_ok=True)
        by_part: List[List[dict]] = [[] for _ in range(self.parts)]
        for item in self.items.values():
            by_part[part_of(item["url"], self.parts)].append(item)
        for part, items in enumerate(by_part):
            with open(out / "frontier-{}.jsonl".format(part), "w") as fh:
                for item in items:
                    fh.write(json.dumps(item, ensure_ascii=False) + "\n")

    def load(self, out: Path) -> None:
        for part in range(self.parts):
            path = out / "frontier-{}.jsonl".format(part)
            if not path.exists():
                continue
            for line in path.read_text().splitlines():
                item = json.loads(line)
                self.items[item["url"]] = item
                self._keys.add(urls.key(item["url"]))
                if item["state"] == "queued":
                    self._enqueue(item)
