"""Publish crawler starting-point pages to the separate D1 database `xlake-pages`.

    python3 -m pipeline.sync_pages_d1 --in <crawl-result dir> [--dry-run] [--max-writes 4000] [--db xlake-pages]

Incremental: only this run's rows are read/written (never a full replace). Always exits 0.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawler import pagerow  # noqa: E402
from pipeline import export_d1 as ex  # noqa: E402
from pipeline.sync_d1 import API, COST, TOUCH_AFTER, Client, D1Error, _pack, _parse, clean_token  # noqa: E402

COLUMNS = ("id", "url", "site", "title", "org", "kind", "tags", "status", "status_quote", "deadline",
           "summary", "language", "funding_date", "funding_quote", "funding_proof",
           "first_seen", "last_checked", "h")
HASH_COLS = tuple(c for c in COLUMNS if c not in ("last_checked", "first_seen", "h"))
FTS_COLS = ("title", "org", "summary", "kind", "tags")
CHUNK = 90  # D1 allows 100 bound parameters per statement

SCHEMA = [
    "CREATE TABLE IF NOT EXISTS pages (id TEXT PRIMARY KEY, url TEXT NOT NULL, site TEXT, title TEXT NOT NULL, "
    "org TEXT, kind TEXT NOT NULL, tags TEXT, status TEXT NOT NULL, status_quote TEXT, deadline TEXT, "
    "summary TEXT, language TEXT, funding_date TEXT, funding_quote TEXT, funding_proof TEXT, "
    "first_seen TEXT, last_checked TEXT, h TEXT);",
    "CREATE INDEX IF NOT EXISTS ix_pages_kind_status ON pages(kind, status);",
    "CREATE INDEX IF NOT EXISTS ix_pages_site ON pages(site);",
    "CREATE INDEX IF NOT EXISTS ix_pages_checked ON pages(last_checked);",
    "CREATE INDEX IF NOT EXISTS ix_pages_funding ON pages(funding_date);",
    "CREATE VIRTUAL TABLE IF NOT EXISTS pages_fts USING fts5(id UNINDEXED, title, org, summary, kind, tags, "
    "tokenize='unicode61 remove_diacritics 2');",
]


def to_db(row: Dict[str, Any]) -> Dict[str, Any]:
    r = dict(row)
    r["tags"] = json.dumps(row.get("tags") or [], ensure_ascii=False) if row.get("tags") else None
    r.pop("recheck_dead", None)
    return r


def row_hash(rec: Dict[str, Any]) -> str:
    vals = [rec.get(c) for c in HASH_COLS]
    return hashlib.sha1(json.dumps(vals, ensure_ascii=False, separators=(",", ":"),
                                   default=str).encode("utf-8")).hexdigest()


class Stats:
    def __init__(self):
        self.rows = 0
        self.c = dict(insert=0, update=0, touch=0, delete=0, deferred=0)
        self.writes = 0
        self.reported = 0

    def line(self, dry: bool) -> str:
        return "pages sync: rows=%d insert=%d update=%d touch=%d delete=%d deferred=%d writes=%d dry_run=%s" % (
            self.rows, self.c["insert"], self.c["update"], self.c["touch"], self.c["delete"],
            self.c["deferred"], self.writes, str(bool(dry)).lower())


def _fts_insert(r: Dict[str, Any]) -> str:
    return "INSERT INTO pages_fts (id, %s) VALUES (%s, %s);" % (
        ", ".join(FTS_COLS), ex.lit(r["id"]), ", ".join(ex.lit(r.get(c)) for c in FTS_COLS))


def _sql(kind: str, r: Dict[str, Any], h: str = "") -> List[str]:
    lit, i = ex.lit, ex.lit(r["id"])
    if kind == "delete":
        return ["DELETE FROM pages WHERE id = %s;" % i, "DELETE FROM pages_fts WHERE id = %s;" % i]
    if kind == "touch":
        return ["UPDATE pages SET last_checked = %s WHERE id = %s;" % (lit(r["last_checked"]), i)]
    if kind == "update":
        cols = [c for c in COLUMNS if c not in ("id", "first_seen", "h")]
        sets = ", ".join("%s = %s" % (c, lit(r.get(c))) for c in cols) + ", h = %s" % lit(h)
        out = ["UPDATE pages SET %s WHERE id = %s;" % (sets, i)]
        if r.get("_fts"):
            out += ["DELETE FROM pages_fts WHERE id = %s;" % i, _fts_insert(r)]
        return out
    full = dict(r, first_seen=r["last_checked"], h=h)
    return ["INSERT INTO pages (%s) VALUES (%s);" % (", ".join(COLUMNS), ", ".join(lit(full.get(c)) for c in COLUMNS)),
            _fts_insert(r)]


def _read_existing(client, db: str, ids: List[str]) -> Dict[str, dict]:
    out: Dict[str, dict] = {}
    cols = "id, h, last_checked, " + ", ".join(FTS_COLS)
    for k in range(0, len(ids), CHUNK):
        part = ids[k:k + CHUNK]
        rows, _ = client.query(db, "SELECT %s FROM pages WHERE id IN (%s)" % (cols, ",".join("?" * len(part))), part)
        for r in rows:
            out[r["id"]] = r
    return out


def plan(rows: List[dict], dead_ids: List[str], existing: Dict[str, dict],
         max_writes: int) -> Tuple[List[Tuple[str, dict, str]], Stats]:
    st = Stats()
    st.rows = len(rows)
    items: List[Tuple[str, dict, str]] = []
    for id_ in dead_ids:
        if id_ in existing:
            items.append(("delete", {"id": id_}, ""))
    dead = set(dead_ids)
    ins, upd, touch = [], [], []
    for row in rows:
        if row["id"] in dead:
            continue
        r = to_db(row)
        h = row_hash(r)
        old = existing.get(r["id"])
        if old is None:
            ins.append(("insert", r, h))
        elif old.get("h") != h:
            r["_fts"] = any(r.get(c) != old.get(c) for c in FTS_COLS)
            upd.append(("update", r, h))
        else:
            new, was = _parse(r.get("last_checked")), _parse(old.get("last_checked"))
            if (new and was and new - was >= TOUCH_AFTER) or (new and not was):
                touch.append(("touch", r, h))
    items += upd + touch + ins
    kept: List[Tuple[str, dict, str]] = []
    cost_total = 0
    for kind, r, h in items:
        cost = 3 if (kind == "update" and not r.get("_fts")) else COST[kind]
        if cost_total + cost > max_writes:
            st.c["deferred"] += 1
            continue
        cost_total += cost
        st.c[kind] += 1
        kept.append((kind, r, h))
    st.writes = cost_total
    return kept, st


def ensure_db(client, name: str) -> None:
    try:
        client.db_id(name)
    except D1Error as e:
        if "not found" not in str(e):
            raise
        p = client._call("POST", "%s/accounts/%s/d1/database" % (API, client.account), {"name": name})
        client._ids[name] = (p.get("result") or {})["uuid"]
        print("pages sync: created D1 database %s" % name)


def sync(rows: List[dict], dead_ids: List[str], client, db: str = "xlake-pages", dry_run: bool = False,
         max_writes: int = 4000, log=print) -> Stats:
    if not rows:
        log("pages sync: 0 rows, treating as failed read; nothing synced")
        return Stats()
    if client is None:
        st = Stats()
        st.rows = len(rows)
        log("pages sync: no token: plan only, %d rows ready" % len(rows))
        return st
    existing: Dict[str, dict] = {}
    ids = [r["id"] for r in rows] + list(dead_ids)
    if not dry_run:
        ensure_db(client, db)
        for stmt in SCHEMA:
            client.query(db, stmt)
        existing = _read_existing(client, db, ids)
    else:
        try:
            existing = _read_existing(client, db, ids)
        except D1Error as e:  # db or table not created yet: everything is new
            log("pages sync: dry-run could not read %s (%s); assuming empty" % (db, str(e)[:80]))
    items, st = plan(rows, dead_ids, existing, max_writes)
    if not dry_run:
        pending: List[str] = []
        for kind, r, h in items:
            pending.extend(_sql(kind, r, h))
        for chunk in _pack(pending):
            _, w = client.query(db, chunk)
            st.reported += w
    return st


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--max-writes", type=int, default=4000)
    ap.add_argument("--db", default="xlake-pages")
    a = ap.parse_args(argv)
    st = Stats()
    try:
        rows, dead = pagerow.rows_from_merged(Path(a.inp) / "pages-merged.jsonl")
        token = clean_token(os.environ.get("CLOUDFLARE_API_TOKEN", ""))
        client = Client(token, os.environ.get("CLOUDFLARE_ACCOUNT_ID", "")) if token else None
        st = sync(rows, dead, client, a.db, a.dry_run, a.max_writes)
    except Exception as e:  # never fail the workflow
        print("::warning::pages sync aborted: %s" % e)
    print(st.line(a.dry_run))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
