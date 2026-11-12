"""Diff-based sync of one finalized shard into the Cloudflare D1 databases.

    python3 -m pipeline.sync_d1 --shard <shard_name> [--dry-run] [--max-writes 10000]

Writes only changes (D1 free plan: 100k rows written/day, indexes + FTS count),
only touches rows this shard owns (column ``src``), and never fails the leg.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import shards  # noqa: E402
from pipeline import export_d1 as ex  # noqa: E402

API = "https://api.cloudflare.com/client/v4"
MULTI_SOURCE = ("jobs", "internships")
TOUCH_AFTER = timedelta(days=3)
NULL_SRC_MAX_AGE = timedelta(days=7)
COST = {"insert": 9, "update": 4, "touch": 1, "delete": 9, "claim": 4}
FTS_SRC = ("title", "org", "location", "skills")
READ_COLS = ("id", "h", "src", "last_checked") + FTS_SRC
PAGE = 2000
# Never trust a sharp drop: if one run would remove more than this share of the
# rows a leg owns (and more than DELETE_GUARD_MIN rows), skip all removals.
DELETE_GUARD_RATIO = 0.30
DELETE_GUARD_MIN = 20


class D1Error(Exception):
    pass


def db_title(name: str) -> str:
    return "xlake-" + name.replace("_", "-")


def rec_hash(rec: Dict[str, Any]) -> str:
    vals = [rec.get(c) for c in ex.COLUMNS if c != "last_checked"]
    return hashlib.sha1(json.dumps(vals, ensure_ascii=False, separators=(",", ":"),
                                   default=str).encode("utf-8")).hexdigest()


def _parse(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        d = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


class Client:
    """Cloudflare D1 REST client. query() -> (rows, rows_written)."""

    def __init__(self, token: str, account_id: str):
        self.token, self.account = token, account_id
        self._ids: Dict[str, str] = {}

    def _call(self, method: str, url: str, body: Optional[dict] = None) -> dict:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        last = ""
        for attempt in range(3):
            req = urllib.request.Request(url, data=data, method=method, headers={
                "Authorization": "Bearer " + self.token, "Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    payload = json.loads(r.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                text = e.read().decode("utf-8", "replace")[:500]
                last = "HTTP %d %s" % (e.code, text)
                if e.code >= 500 and attempt < 2:
                    time.sleep(2 * (attempt + 1))
                    continue
                raise D1Error(last)
            except (urllib.error.URLError, TimeoutError) as e:
                last = "network error: %s" % e
                if attempt < 2:
                    time.sleep(2 * (attempt + 1))
                    continue
                raise D1Error(last)
            if not payload.get("success", True):
                raise D1Error("; ".join(str(e.get("message", e)) for e in payload.get("errors", [])) or "unknown error")
            return payload
        raise D1Error(last)

    def db_id(self, title: str) -> str:
        if title in self._ids:
            return self._ids[title]
        page = 1
        while True:
            url = "%s/accounts/%s/d1/database?name=%s&per_page=100&page=%d" % (
                API, self.account, urllib.parse.quote(title), page)
            p = self._call("GET", url)
            res = p.get("result") or []
            for d in res:
                if d.get("name") == title:
                    self._ids[title] = d["uuid"]
                    return d["uuid"]
            info = p.get("result_info") or {}
            if len(res) < 100 or page * 100 >= info.get("total_count", 0):
                raise D1Error("database %s not found" % title)
            page += 1

    def query(self, db: str, sql: str, params: Optional[list] = None) -> Tuple[List[dict], int]:
        body: Dict[str, Any] = {"sql": sql}
        if params is not None:
            body["params"] = params
        url = "%s/accounts/%s/d1/database/%s/query" % (API, self.account, self.db_id(db))
        p = self._call("POST", url, body)
        rows: List[dict] = []
        written = 0
        for r in p.get("result") or []:
            rows.extend(r.get("results") or [])
            written += int((r.get("meta") or {}).get("rows_written") or 0)
        return rows, written


class Stats:
    def __init__(self):
        self.c = dict(inserted=0, updated=0, touched=0, deleted=0, claimed=0, foreign=0, skipped_budget=0)
        self.plan: List[dict] = []
        self.est = 0
        self.reported = 0

    def line(self, shard: str) -> str:
        return "d1 sync %s: %s est_writes=%d reported_writes=%d" % (
            shard, " ".join("%s=%d" % kv for kv in self.c.items()), self.est, self.reported)


def _pack(stmts: List[str]) -> List[str]:
    out, cur, size = [], [], 0
    for s in stmts:
        n = len(s.encode("utf-8")) + 1
        if cur and size + n > ex.MAX_STMT_BYTES:
            out.append("\n".join(cur))
            cur, size = [], 0
        cur.append(s)
        size += n
    if cur:
        out.append("\n".join(cur))
    return out


def _read_existing(client, db: str, shard: str, dry: bool) -> Dict[str, dict]:
    out: Dict[str, dict] = {}
    last = ""
    cols = ", ".join(READ_COLS)
    while True:
        sql = ("SELECT %s FROM opportunities WHERE (src = ? OR src IS NULL) AND id > ? "
               "ORDER BY id LIMIT %d" % (cols, PAGE))
        try:
            rows, _ = client.query(db, sql, [shard, last])
        except D1Error as e:
            if dry and "no such column" in str(e):
                rows, _ = client.query(
                    db, "SELECT id, last_checked, title, org, location, skills FROM opportunities "
                        "WHERE id > ? ORDER BY id LIMIT %d" % PAGE, [last])
            else:
                raise
        for r in rows:
            out[r["id"]] = r
        if len(rows) < PAGE:
            return out
        last = rows[-1]["id"]


def _read_all_ids(client, db: str) -> set:
    out: set = set()
    last = ""
    while True:
        rows, _ = client.query(
            db, "SELECT id FROM opportunities WHERE id > ? ORDER BY id LIMIT %d" % PAGE, [last])
        out.update(r["id"] for r in rows)
        if len(rows) < PAGE:
            return out
        last = rows[-1]["id"]


def _plan(db: str, shard: str, recs: List[dict], existing: Dict[str, dict],
          now: datetime, foreign: Optional[set] = None, st: Optional["Stats"] = None) -> List[Tuple[str, dict, dict]]:
    """-> ordered [(kind, rec_or_row, ctx)] : deletes, updates, claims, touches, inserts."""
    cur = {r["id"]: r for r in recs}
    dels, upds, claims, touches, ins = [], [], [], [], []
    for id_, row in existing.items():
        if id_ in cur:
            continue
        if row.get("src") == shard:
            dels.append(("delete", row, {}))
        elif row.get("src") is None:
            if db not in MULTI_SOURCE:
                dels.append(("delete", row, {}))
            else:
                lc = _parse(row.get("last_checked"))
                if lc is not None and now - lc > NULL_SRC_MAX_AGE:
                    dels.append(("delete", row, {}))
    for id_, rec in cur.items():
        h = rec_hash(rec)
        row = existing.get(id_)
        if row is None:
            if foreign and id_ in foreign:
                if st:
                    st.c["foreign"] += 1
                continue
            ins.append((rec.get("last_checked") or "", "insert", rec, {"h": h}))
            continue
        if row.get("src") is None and row.get("h") is None:
            claims.append(("claim", rec, {"h": h}))
        elif row.get("h") != h:
            fts = any(rec.get(c) != row.get(c) for c in FTS_SRC)
            upds.append(("update", rec, {"h": h, "fts": fts}))
        else:
            new, old = _parse(rec.get("last_checked")), _parse(row.get("last_checked"))
            if (new and old and new - old >= TOUCH_AFTER) or (new and not old):
                touches.append(("touch", rec, {}))
    ins.sort(key=lambda t: t[0])
    owned = sum(1 for r in existing.values()
                if r.get("src") == shard or (r.get("src") is None and db not in MULTI_SOURCE))
    if len(dels) > DELETE_GUARD_MIN and len(dels) > DELETE_GUARD_RATIO * max(owned, 1):
        print("::warning::d1 sync %s/%s: would remove %d of %d owned rows (>%d%%) - treating as a bad read, "
            "skipping all removals" % (shard, db, len(dels), owned, int(DELETE_GUARD_RATIO * 100)))
        if st:
            st.c["guarded_deletes"] = st.c.get("guarded_deletes", 0) + len(dels)
        dels = []
    if st is not None:
        st.plan.append(dict(db=db, existing=len(existing), current=len(cur), owned=owned,
                            insert=len(ins), update=len(upds), claim=len(claims),
                            touch=len(touches), delete=len(dels)))
    return dels + upds + claims + touches + [(k, r, c) for _, k, r, c in ins]


def _sql_for(kind: str, shard: str, item: dict, ctx: dict) -> List[str]:
    lit = ex.lit
    if kind == "delete":
        i = lit(item["id"])
        return ["DELETE FROM opportunities WHERE id = %s AND (src = %s OR src IS NULL);" % (i, lit(shard)),
                "DELETE FROM opportunities_fts WHERE id = %s;" % i]
    i = lit(item["id"])
    if kind == "touch":
        return ["UPDATE opportunities SET last_checked = %s WHERE id = %s;" % (lit(item["last_checked"]), i)]
    if kind in ("update", "claim"):
        sets = ", ".join("%s = %s" % (c, lit(item[c])) for c in ex.COLUMNS if c != "id")
        sets += ", src = %s, h = %s" % (lit(shard), lit(ctx["h"]))
        out = ["UPDATE opportunities SET %s WHERE id = %s;" % (sets, i)]
        if kind == "update" and ctx.get("fts"):
            out.append("DELETE FROM opportunities_fts WHERE id = %s;" % i)
            out.append(_fts_insert(item))
        return out
    cols = ", ".join(ex.COLUMNS) + ", src, h"
    vals = ", ".join(lit(item[c]) for c in ex.COLUMNS) + ", %s, %s" % (lit(shard), lit(ctx["h"]))
    return ["INSERT INTO opportunities (%s) VALUES (%s);" % (cols, vals), _fts_insert(item)]


def _fts_insert(rec: dict) -> str:
    return "INSERT INTO opportunities_fts (%s) VALUES (%s);" % (
        ", ".join(ex.FTS_COLUMNS),
        ", ".join(ex.lit(rec["id"] if c == "id" else ex._fts_text(rec, c)) for c in ex.FTS_COLUMNS))


def sync(shard: str, client, dry_run: bool = False, max_writes: int = 10000,
         now: Optional[datetime] = None, rows: Optional[List[dict]] = None,
         stats: Optional[Stats] = None, log=print) -> Stats:
    st = stats or Stats()
    now = now or datetime.now(timezone.utc)
    if rows is None:
        rows = shards.load_shard(shard)
        if rows is None:
            raise D1Error("shard %s not found" % shard)
    routed = ex.route(rows)
    targets = [n for n in ex.DB_NAMES if routed[n]]
    if shards.is_job_shard(shard):
        targets = [n for n in ("jobs", "internships")]
    elif shard in ex.DB_NAMES and shard not in targets:
        targets.append(shard)
    if not any(routed[n] for n in targets):
        log("d1 sync %s: shard serves 0 rows, treating as failed read; nothing synced" % shard)
        return st
    plans = []
    for db in targets:
        title = db_title(db)
        if client is not None:
            if not dry_run:
                try:
                    client.query(title, "ALTER TABLE opportunities ADD COLUMN src TEXT;")
                except D1Error as e:
                    if "duplicate column" not in str(e).lower():
                        raise
                try:
                    client.query(title, "ALTER TABLE opportunities ADD COLUMN h TEXT;")
                except D1Error as e:
                    if "duplicate column" not in str(e).lower():
                        raise
            existing = _read_existing(client, title, shard, dry_run)
            foreign = _read_all_ids(client, title) - set(existing)
        else:
            existing, foreign = {}, set()
        plans.append((db, title, _plan(db, shard, routed[db], existing, now, foreign, st)))
    for db, title, plan in plans:
        pending: List[str] = []
        names = {"delete": "deleted", "update": "updated", "touch": "touched",
                 "insert": "inserted", "claim": "claimed"}
        for kind, item, ctx in plan:
            cost = COST[kind] if not (kind == "update" and not ctx.get("fts")) else 3
            if st.est + cost > max_writes:
                st.c["skipped_budget"] += 1
                continue
            st.est += cost
            st.c[names[kind]] += 1
            if not dry_run:
                pending.extend(_sql_for(kind, shard, item, ctx))
        if not dry_run and pending:
            for chunk in _pack(pending):
                _, w = client.query(title, chunk)
                st.reported += w
        for pl in st.plan:
            if pl["db"] == db:
                log("d1 plan %s/%s: existing=%d current=%d owned=%d -> insert=%d update=%d claim=%d touch=%d delete=%d"
                    % (shard, db, pl["existing"], pl["current"], pl["owned"], pl["insert"], pl["update"],
                       pl["claim"], pl["touch"], pl["delete"]))
    return st


def clean_token(raw: str) -> str:
    """A pasted secret can carry stray whitespace, extra lines, or even the whole
    "curl ... -H 'Authorization: Bearer <token>'" test command Cloudflare shows
    next to a new token. Prefer the value after "Bearer", else the first long
    token-like word. Never print it."""
    text = raw or ""
    m = re.search(r"Bearer\s+([A-Za-z0-9_-]{30,})", text)
    if m:
        return m.group(1)
    for word in re.findall(r"[A-Za-z0-9_-]{30,}", text):
        return word
    return ""


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--shard", required=True)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--max-writes", type=int, default=10000)
    a = ap.parse_args(argv)
    raw = os.environ.get("CLOUDFLARE_API_TOKEN", "")
    token = clean_token(raw)
    if raw and not token:
        # Shape only, never the value: helps fix a badly pasted secret.
        print("::warning::CLOUDFLARE_API_TOKEN is set but not usable (lines=%d, line lengths=%s; "
              "expected one line of ~40 letters/digits)" % (len(raw.splitlines()), [len(x) for x in raw.splitlines()]))
    if not token and a.dry_run:
        print("d1 sync %s: no usable token - cannot read D1, so no plan (nothing written)" % a.shard)
        return 0
    if not token and not a.dry_run:
        print("d1 sync skipped: no CLOUDFLARE_API_TOKEN")
        return 0
    client = Client(token, os.environ.get("CLOUDFLARE_ACCOUNT_ID", "")) if token else None
    st = Stats()
    try:
        sync(a.shard, client, a.dry_run, a.max_writes, stats=st)
    except Exception as e:  # never fail the leg
        print("::warning::d1 sync %s aborted: %s" % (a.shard, e))
    print(st.line(a.shard))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
