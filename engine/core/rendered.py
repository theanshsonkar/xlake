"""Read pages rendered by render/render_pages.mjs (headless Chromium, weekly CI).

`lookup(url)` returns (html, final_url) when a fresh, status-ok cache entry
exists for that URL, else None (caller falls back to urllib). Blocked,
challenge, robots-disallowed, timeout and empty renders are never used.
"""
from __future__ import annotations

import html as _html
import json
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional, Tuple

from core.paths import OPERATIONS_DIR

MAX_AGE = timedelta(days=10)
TARGETS_PATH = os.path.join(OPERATIONS_DIR, "rendered_pages.json")
CACHE_DIR = os.path.join(OPERATIONS_DIR, "rendered_cache")


def _norm(url: str) -> str:
    return re.sub(r"^https?://(www\.)?", "", (url or "").strip().lower()).rstrip("/")


def _targets(path: Optional[str] = None) -> Dict[str, str]:
    try:
        with open(path or os.environ.get("XLAKE_RENDERED_TARGETS") or TARGETS_PATH, encoding="utf-8") as fh:
            rows = json.load(fh)
    except (OSError, ValueError):
        return {}
    return {_norm(r["url"]): r["id"] for r in rows if isinstance(r, dict) and r.get("url") and r.get("id")}


def _parse_ts(value) -> Optional[datetime]:
    try:
        ts = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def to_html(entry: Dict) -> str:
    """Visible text plus links as simple HTML the programme parser understands."""
    parts = ["<html><head><title>{}</title></head><body><main>".format(_html.escape(entry.get("title") or ""))]
    for para in re.split(r"\n+", entry.get("text") or ""):
        para = para.strip()
        if para:
            parts.append("<p>{}</p>".format(_html.escape(para)))
    for link in entry.get("links") or []:
        href = link.get("href")
        if href:
            parts.append('<a href="{}">{}</a>'.format(_html.escape(href, quote=True),
                                                     _html.escape(link.get("text") or "")))
    parts.append("</main></body></html>")
    return "".join(parts)


def lookup(url: str, now: Optional[datetime] = None, cache_dir: Optional[str] = None,
           targets_path: Optional[str] = None) -> Optional[Tuple[str, str]]:
    rid = _targets(targets_path).get(_norm(url))
    if not rid:
        return None
    path = os.path.join(cache_dir or os.environ.get("XLAKE_RENDERED_CACHE") or CACHE_DIR, rid + ".json")
    try:
        with open(path, encoding="utf-8") as fh:
            entry = json.load(fh)
    except (OSError, ValueError):
        return None
    if entry.get("status") != "ok" or not (entry.get("text") or "").strip():
        return None
    fetched = _parse_ts(entry.get("fetched_at"))
    if fetched is None or (now or datetime.now(timezone.utc)) - fetched > MAX_AGE:
        return None
    return to_html(entry), entry.get("final_url") or url
