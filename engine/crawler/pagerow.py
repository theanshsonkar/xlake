"""Convert one merged crawler page record into a slim row for the D1 `pages` table."""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawler import urls  # noqa: E402
from pipeline import rowshape as rs  # noqa: E402

_STATUS = {"open": "open", "opening_soon": "upcoming", "closed": "closed"}


def page_id(final_url: str) -> str:
    return "page:" + hashlib.sha1(urls.key(final_url).encode("utf-8")).hexdigest()[:20]


def to_row(rec: Dict) -> Optional[Dict]:
    final_url = rec.get("final_url")
    kind = rec.get("type_guess")
    if (not final_url or rec.get("outcome") != "ok" or rec.get("junk")
            or not kind or kind == "unknown"):
        return None
    title = rs.scrub(rec.get("title"))
    if not title:
        return None
    quote = rs.scrub(rec.get("quote"))
    status = _STATUS.get(rec.get("status"), "unverified")
    if status != "unverified" and not quote:
        status = "unverified"
    deadline = rs.to_date(rec.get("deadline")) if quote else None
    row = {
        "id": page_id(final_url), "url": final_url,
        "site": urls.registered_domain(final_url) or None,
        "title": title, "org": rs.real_org(rec.get("organiser")),
        "kind": str(kind), "tags": sorted(str(t) for t in (rec.get("tags") or [])),
        "status": status, "status_quote": quote, "deadline": deadline,
        "summary": rs.scrub(rec.get("snippet")), "language": rs.scrub(rec.get("language"), 20),
        "funding_date": None, "funding_quote": None, "funding_proof": None,
        "last_checked": rec.get("fetched_at"),
        "recheck_dead": bool(rec.get("recheck")) and rec.get("status_code") in (404, 410),
    }
    cf = rec.get("company_funding")
    if isinstance(cf, dict) and cf.get("date"):
        row["funding_date"] = rs.to_date(cf.get("date"))
        row["funding_quote"] = rs.scrub(cf.get("quote"))
        row["funding_proof"] = cf.get("proof")
    return row


def rows_from_merged(path) -> Tuple[List[Dict], List[str]]:
    """-> (rows, dead_ids), deduped by id (newest last_checked wins)."""
    rows: Dict[str, Dict] = {}
    dead: Dict[str, str] = {}
    try:
        text = Path(path).read_text()
    except OSError:
        return [], []
    for line in text.splitlines():
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if not isinstance(rec, dict):
            continue
        row = to_row(rec)
        if row is None:
            # a recheck that hit 404/410 returns no page content; still mark dead
            if (rec.get("recheck") and rec.get("status_code") in (404, 410)
                    and (rec.get("final_url") or rec.get("url"))):
                dead[page_id(rec.get("final_url") or rec["url"])] = rec.get("fetched_at") or ""
            continue
        cur = rows.get(row["id"])
        if cur is None or (row["last_checked"] or "") >= (cur["last_checked"] or ""):
            rows[row["id"]] = row
    for id_, row in list(rows.items()):
        if row.pop("recheck_dead", False):
            dead[id_] = row["last_checked"] or ""
            del rows[id_]
    return sorted(rows.values(), key=lambda r: r["id"]), sorted(dead)
