"""Export serving rows to one D1-compatible SQL file (and optional SQLite db) per category.

    python3 -m pipeline.export_d1 <shards_dir> <out_dir> [--sqlite]
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import cycles, lifecycle  # noqa: E402
from pipeline import publish_supabase as ps  # noqa: E402
from pipeline.rowshape import to_standard  # noqa: E402

SCHEMA = """CREATE TABLE IF NOT EXISTS opportunities (
  id TEXT PRIMARY KEY, type TEXT NOT NULL, title TEXT NOT NULL, org TEXT, logo TEXT,
  url TEXT NOT NULL, apply_url TEXT, status TEXT NOT NULL,
  deadline TEXT, opens TEXT, posted_at TEXT, last_deadline TEXT, next_cycle TEXT,
  expected_opens TEXT, expected_deadline TEXT,
  eligibility TEXT,
  level TEXT,
  skills TEXT,
  location TEXT, country TEXT, workplace TEXT,
  funding TEXT, funding_amount REAL, currency TEXT, duration TEXT, cost_to_apply TEXT,
  proof_quote TEXT, proof_url TEXT, proof_kind TEXT,
  first_seen TEXT, last_checked TEXT
);
CREATE INDEX IF NOT EXISTS ix_status_deadline ON opportunities(status, deadline);
CREATE INDEX IF NOT EXISTS ix_type_status ON opportunities(type, status);
CREATE INDEX IF NOT EXISTS ix_country ON opportunities(country);
CREATE INDEX IF NOT EXISTS ix_expected_opens ON opportunities(expected_opens);
CREATE INDEX IF NOT EXISTS ix_first_seen ON opportunities(first_seen);
CREATE VIRTUAL TABLE IF NOT EXISTS opportunities_fts USING fts5(id UNINDEXED, title, org, location, skills, tokenize='unicode61 remove_diacritics 2');
"""

COLUMNS = (
    "id", "type", "title", "org", "logo", "url", "apply_url", "status",
    "deadline", "opens", "posted_at", "last_deadline", "next_cycle",
    "expected_opens", "expected_deadline", "eligibility", "level", "skills",
    "location", "country", "workplace", "funding", "funding_amount", "currency",
    "duration", "cost_to_apply", "proof_quote", "proof_url", "proof_kind",
    "first_seen", "last_checked",
)
FTS_COLUMNS = ("id", "title", "org", "location", "skills")
BATCH = 100
MAX_STMT_BYTES = 90_000

DB_NAMES = ("jobs", "internships", "fellowships", "scholarships", "grants", "research",
            "hackathons", "open_source", "startup", "community")
_TYPE_DB = {"job": "jobs", "internship": "internships", "fellowship": "fellowships",
            "scholarship": "scholarships", "grant": "grants", "research": "research",
            "hackathon": "hackathons", "open_source": "open_source",
            "startup": "startup", "community": "community"}


def _json(v: Any) -> str:
    return json.dumps(v, ensure_ascii=False, separators=(",", ":"))


def to_record(row: dict) -> Optional[Dict[str, Any]]:
    s = to_standard(row)
    if not s.get("type") or not s.get("id") or not s.get("title") or not s.get("url"):
        return None
    proof = s.get("proof") or {}
    rec = {k: s.get(k) for k in COLUMNS if k in s}
    rec.update({
        "eligibility": _json(s.get("eligibility") or {}),
        "level": _json(s.get("level") or []),
        "skills": _json(s.get("skills") or []),
        "proof_quote": proof.get("quote"), "proof_url": proof.get("url"),
        "proof_kind": proof.get("kind"),
        "expected_opens": row.get("expected_opens"),
        "expected_deadline": row.get("expected_deadline"),
        "first_seen": row.get("first_seen"),
    })
    return {k: rec.get(k) for k in COLUMNS}


def route(rows: Iterable[dict], today=None) -> Dict[str, List[Dict[str, Any]]]:
    """Serving rows -> {db_name: [records]}, deduped by id (latest last_checked wins)."""
    today = today or datetime.now(timezone.utc).date()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    rows = [dict(r) for r in rows if isinstance(r, dict)]
    stale = [r for r in rows if "lifecycle" not in r]
    if stale:
        lifecycle.reconcile(stale, today, now)
        cycles.finalize(stale, today)
    best: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        if not ps.is_serving(r):
            continue
        rec = to_record(r)
        if rec is None:
            continue
        old = best.get(rec["id"])
        if old is None or (rec["last_checked"] or "") >= (old["last_checked"] or ""):
            best[rec["id"]] = rec
    out: Dict[str, List[Dict[str, Any]]] = {n: [] for n in DB_NAMES}
    for rec in best.values():
        name = _TYPE_DB.get(rec["type"])
        if name:
            out[name].append(rec)
    for recs in out.values():
        recs.sort(key=lambda r: r["id"])
    return out


def lit(v: Any) -> str:
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, (int, float)):
        return repr(v)
    return "'" + str(v).replace("'", "''").replace("\x00", "") + "'"


def _fts_text(rec: Dict[str, Any], col: str) -> Optional[str]:
    v = rec.get(col)
    if col == "skills" and v:
        try:
            v = " ".join(json.loads(v))
        except ValueError:
            pass
    return v


def _chunks(values: List[str], head: str) -> List[str]:
    """Group VALUES tuples into INSERT statements of at most MAX_STMT_BYTES
    (D1 rejects statements over ~100 KB with SQLITE_TOOBIG) and BATCH rows."""
    out, cur, size = [], [], len(head)
    for v in values:
        n = len(v.encode("utf-8")) + 2
        if cur and (size + n > MAX_STMT_BYTES or len(cur) >= BATCH):
            out.append(head + ",\n".join(cur) + ";")
            cur, size = [], len(head)
        cur.append(v)
        size += n
    if cur:
        out.append(head + ",\n".join(cur) + ";")
    return out


def build_sql(recs: List[Dict[str, Any]]) -> str:
    parts = [SCHEMA, "DELETE FROM opportunities;", "DELETE FROM opportunities_fts;"]
    parts += _chunks(["(%s)" % ", ".join(lit(r[c]) for c in COLUMNS) for r in recs],
                     "INSERT INTO opportunities (%s) VALUES\n" % ", ".join(COLUMNS))
    parts += _chunks(["(%s)" % ", ".join(lit(r["id"] if c == "id" else _fts_text(r, c))
                                         for c in FTS_COLUMNS) for r in recs],
                     "INSERT INTO opportunities_fts (%s) VALUES\n" % ", ".join(FTS_COLUMNS))
    return "\n".join(parts) + "\n"


def load_rows(shards_dir: str) -> List[dict]:
    rows: List[dict] = []
    for fn in sorted(os.listdir(shards_dir)):
        if not fn.endswith(".json"):
            continue
        with open(os.path.join(shards_dir, fn), encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            data = data.get("rows") or data.get("opportunities") or []
        rows.extend(x for x in data if isinstance(x, dict))
    return rows


def export(shards_dir: str, out_dir: str, sqlite: bool = False) -> Dict[str, Dict[str, Any]]:
    os.makedirs(out_dir, exist_ok=True)
    routed = route(load_rows(shards_dir))
    report: Dict[str, Dict[str, Any]] = {}
    for name, recs in routed.items():
        sql = build_sql(recs)
        path = os.path.join(out_dir, name + ".sql")
        with open(path, "w", encoding="utf-8") as f:
            f.write(sql)
        if sqlite:
            dbp = os.path.join(out_dir, name + ".db")
            if os.path.exists(dbp):
                os.remove(dbp)
            con = sqlite3.connect(dbp)
            con.executescript(sql)
            con.commit()
            con.close()
        report[name] = {"rows": len(recs), "bytes": os.path.getsize(path),
                        "status": dict(Counter(r["status"] for r in recs))}
    return report


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("shards_dir")
    ap.add_argument("out_dir")
    ap.add_argument("--sqlite", action="store_true", help="also write <out>/<name>.db")
    a = ap.parse_args(argv)
    for name, r in export(a.shards_dir, a.out_dir, a.sqlite).items():
        print("%-12s rows=%-6d size=%-9d status=%s" % (name, r["rows"], r["bytes"], r["status"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
