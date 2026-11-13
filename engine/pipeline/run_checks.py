"""Post-run checks: scheduler timeliness, live API expectations, optional D1 stats.

Each check prints PASS/FAIL/INFO with one line (also appended to
$GITHUB_STEP_SUMMARY when set). Exit status is 1 if any check FAILs.
"""
import argparse
import datetime as dt
import json
import os
import re
import sys
import urllib.error
import urllib.request

MCP_URL = "https://api.xlake.site/mcp"
WORKFLOW_FILES = ["fellowships", "scholarships", "grants", "research", "startup",
                  "community", "open-source", "hackathons", "sweep"]
GRACE_HOURS = 3
CF_API = "https://api.cloudflare.com/client/v4"

RESULTS = []


def record(level, msg):
    RESULTS.append((level, msg))
    line = f"{level}: {msg}"
    print(line)
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"- {line}\n")


def _request(url, data=None, headers=None):
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, headers={"User-Agent": "xlake-checks/1.0", **(headers or {})})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def _get(url, headers=None):
    return _request(url, None, headers)


def _post(url, data, headers=None):
    return _request(url, data, headers)


def now_utc():
    return dt.datetime.now(dt.timezone.utc)


def workflows_dir():
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(here, "..", "..", ".github", "workflows")


def cron_hours_today(text):
    """Expected (hour, minute) slots from cron lines that run every day."""
    slots = []
    for m in re.finditer(r'cron:\s*"([^"]+)"', text):
        f = m.group(1).split()
        if len(f) != 5 or f[2:] != ["*", "*", "*"] or not f[0].isdigit():
            continue
        minute = int(f[0])
        hf = f[1]
        if hf.isdigit():
            hours = [int(hf)]
        elif re.fullmatch(r"\*/\d+", hf):
            hours = list(range(0, 24, int(hf.split("/")[1])))
        else:
            continue
        slots += [(h, minute) for h in hours]
    return sorted(slots)


def check_scheduler(now=None):
    now = now or now_utc()
    token = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not token or not repo:
        record("INFO", "scheduler checks skipped (GITHUB_TOKEN/GITHUB_REPOSITORY not set)")
        return
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    today = now.date().isoformat()
    for name in WORKFLOW_FILES:
        try:
            with open(os.path.join(workflows_dir(), name + ".yml"), encoding="utf-8") as f:
                slots = cron_hours_today(f.read())
            url = (f"https://api.github.com/repos/{repo}/actions/workflows/{name}.yml/runs"
                   f"?event=schedule&per_page=30&created={today}")
            runs = _get(url, headers).get("workflow_runs", [])
        except Exception as e:
            record("FAIL", f"{name}: could not read schedule state ({e})")
            continue
        runs = [r for r in runs if str(r.get("run_started_at") or r.get("created_at", "")).startswith(today)]
        due = [s for s in slots if now >= now.replace(hour=s[0], minute=s[1], second=0, microsecond=0)
               + dt.timedelta(hours=GRACE_HOURS)]
        if len(runs) < len(due):
            record("FAIL", f"{name}: {len(runs)} scheduled run(s) started today, expected {len(due)}")
            continue
        bad = [r for r in runs if r.get("status") == "completed" and r.get("conclusion") != "success"]
        running = [r for r in runs if r.get("status") != "completed"]
        if bad:
            record("FAIL", f"{name}: scheduled run concluded {bad[0].get('conclusion')}")
        elif running:
            record("INFO", f"{name}: scheduled run still in progress")
        elif not runs:
            record("INFO", f"{name}: no scheduled run due yet today")
        else:
            record("PASS", f"{name}: {len(runs)} scheduled run(s) today, all success")


def call_tool(name, arguments):
    payload = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
               "params": {"name": name, "arguments": arguments}}
    headers = {"content-type": "application/json", "accept": "application/json, text/event-stream"}
    resp = _post(MCP_URL, payload, headers)
    text = resp["result"]["content"][0]["text"]
    return json.loads(text)


def _rows(data):
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for k in ("results", "rows", "items"):
            if isinstance(data.get(k), list):
                return data[k]
    return []


def check_status(ids, expected, today):
    for oid in ids:
        try:
            row = call_tool("get", {"id": oid})
            status = row.get("status")
        except Exception as e:
            record("FAIL", f"{oid}: get failed ({e})")
            continue
        if status == expected:
            record("PASS", f"{oid}: status {status} ({today})")
        else:
            record("FAIL", f"{oid}: status is {status!r}, expected {expected!r}")


def check_soon(days, minimum, today):
    try:
        rows = _rows(call_tool("opening_soon", {"days": days}))
    except Exception as e:
        record("FAIL", f"opening_soon {days}d: call failed ({e})")
        return
    past = [r.get("id") for r in rows if r.get("deadline") and r["deadline"] < today]
    if len(rows) < minimum:
        record("FAIL", f"opening_soon {days}d: {len(rows)} rows, expected at least {minimum}")
    elif past:
        record("FAIL", f"opening_soon {days}d: rows with past deadline: {', '.join(map(str, past))}")
    else:
        record("PASS", f"opening_soon {days}d: {len(rows)} rows (>= {minimum}), none past deadline")
    if rows:
        record("INFO", "opening soon: " + "; ".join(str(r.get("title")) for r in rows[:15]))


CATEGORIES = ["job", "internship", "fellowship", "scholarship", "grant", "research",
              "hackathon", "open-source", "startup", "community"]


def check_counts():
    parts = []
    for t in CATEGORIES:
        try:
            parts.append(f"{t}={len(_rows(call_tool('search', {'type': t, 'limit': 100})))}")
        except Exception as e:
            parts.append(f"{t}=err({type(e).__name__})")
    record("INFO", "served rows per type (capped at 100): " + " ".join(parts))


def check_d1(max_writes, now=None):
    now = now or now_utc()
    token = os.environ.get("CLOUDFLARE_API_TOKEN")
    acct = os.environ.get("CLOUDFLARE_ACCOUNT_ID")
    if not token or not acct:
        record("INFO", "D1 stats skipped (Cloudflare secrets not set)")
        return
    h = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    try:
        dbs = _get(f"{CF_API}/accounts/{acct}/d1/database", h).get("result", [])
    except Exception as e:
        record("INFO", f"D1 stats skipped (list failed: {e})")
        return
    ids = []
    for db in dbs:
        ids.append(db.get("uuid"))
        info = {}
        try:
            info = _get(f"{CF_API}/accounts/{acct}/d1/database/{db['uuid']}", h).get("result", {})
        except Exception:
            pass
        record("INFO", f"D1 {db.get('name')}: size={info.get('file_size')} tables={info.get('num_tables')}")
        if db.get("name") == "xlake-jobs":
            try:
                res = _post(f"{CF_API}/accounts/{acct}/d1/database/{db['uuid']}/query",
                            {"sql": "SELECT COUNT(*) AS n FROM opportunities"}, h)
                n = res["result"][0]["results"][0]["n"]
                record("INFO", f"D1 xlake-jobs opportunities rows: {n}")
            except Exception as e:
                record("INFO", f"D1 xlake-jobs count failed ({e})")
    day = now.date().isoformat()
    total = 0
    try:
        for uuid in ids:
            q = ("query($a:String!,$d:String!,$s:Time!,$e:Time!){viewer{accounts(filter:{accountTag:$a})"
                 "{d1AnalyticsAdaptiveGroups(limit:1,filter:{databaseId:$d,datetime_geq:$s,datetime_leq:$e})"
                 "{sum{rowsWritten}}}}}")
            v = {"a": acct, "d": uuid, "s": day + "T00:00:00Z", "e": now.strftime("%Y-%m-%dT%H:%M:%SZ")}
            res = _post(f"{CF_API}/graphql", {"query": q, "variables": v}, h)
            groups = res["data"]["viewer"]["accounts"][0]["d1AnalyticsAdaptiveGroups"]
            total += sum(g["sum"]["rowsWritten"] or 0 for g in groups)
    except Exception as e:
        record("INFO", f"D1 rows-written analytics unavailable ({e})")
        return
    if total > max_writes:
        record("FAIL", f"D1 rows written today {total} > {max_writes}")
    else:
        record("PASS", f"D1 rows written today {total} <= {max_writes}")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--expect-open", nargs="+", default=[], metavar="ID")
    ap.add_argument("--expect-status", nargs="+", default=[], metavar="ID=STATUS")
    ap.add_argument("--soon-min", nargs="+", default=[], metavar="DAYS=N")
    ap.add_argument("--max-writes", type=int, default=80000)
    a = ap.parse_args(argv)
    today = now_utc().date().isoformat()
    check_scheduler()
    if a.expect_open:
        check_status(a.expect_open, "open", today)
    for item in a.expect_status:
        oid, _, st = item.partition("=")
        check_status([oid], st, today)
    for item in a.soon_min:
        d, _, n = item.partition("=")
        check_soon(int(d), int(n), today)
    check_counts()
    check_d1(a.max_writes)
    return 1 if any(l == "FAIL" for l, _ in RESULTS) else 0


if __name__ == "__main__":
    sys.exit(main())
