"""Daily data-health report over the served Supabase ``opportunities`` table.

Read-only. Per category it computes the live count, field coverage
(deadline/description/funding/logo/region), rows closing within 7 days,
past-deadline rows still served, duplicates and stale ``last_checked``.

It compares live counts with the previous snapshot in
``data/operations/health_history.json`` and checks, through the GitHub Actions
API, that every category workflow has succeeded recently. Exit code 1 (so the
workflow fails and GitHub notifies the owner) when:

* a category's live count dropped more than 30% against the previous report,
* any past-deadline row is still served,
* a category workflow has no successful run in the last 48 hours.

Environment: ``SUPABASE_URL``, ``SUPABASE_ANON_KEY`` (or a read key), and for
the freshness check ``GITHUB_TOKEN`` + ``GITHUB_REPOSITORY``.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone

from core.paths import OPERATIONS_DIR

HISTORY_PATH = os.path.join(OPERATIONS_DIR, "health_history.json")
HISTORY_KEEP = 60
DROP_THRESHOLD = 0.30
DROP_MIN_PREVIOUS = 10  # ignore noise on tiny categories
CLOSING_DAYS = 7
STALE_CHECK_DAYS = 14
RUN_MAX_AGE_HOURS = 48
PAGE = 1000
UA = "Mozilla/5.0 (xlake-health-report)"

# Category group -> workflow file whose success is expected within 48h.
CATEGORY_WORKFLOWS = {
    "job": "sweep.yml",
    "internship": "sweep.yml",
    "hackathon": "hackathons.yml",
    "contribution": "open-source.yml",
    "open-source-programmes": "open-source.yml",
    "fellowship": "fellowships.yml",
    "scholarship": "scholarships.yml",
    "grant": "grants.yml",
    "research": "research.yml",
    "startup-founder": "startup.yml",
    "community": "community.yml",
}
# Fields that do not apply to a group are reported as n/a rather than 0%.
NOT_APPLICABLE = {
    "job": {"deadline", "funding"},
    "internship": {"deadline", "funding"},
    "contribution": {"deadline", "funding"},
}
FIELDS = ("deadline", "description", "funding", "logo", "region")
SELECT = ("id,type,category,title,url,deadline,description,funding,last_checked,"
          "is_live,needs_confirmation,logo:extra->>logo_url,region:extra->>region")


def group_of(row):
    """Report bucket: programmes by category, everything else by type."""
    if row.get("type") == "programme":
        return row.get("category") or "programme"
    return row.get("type") or "unknown"


def _present(value):
    return isinstance(value, str) and value.strip() != "" or (
        value is not None and not isinstance(value, str) and value != [])


def _parse_date(value):
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _parse_ts(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _dup_key(row):
    url = (row.get("url") or "").strip().casefold().rstrip("/")
    title = " ".join((row.get("title") or "").casefold().split())
    return (url, title) if url and title else None


def compute_metrics(rows, today=None, now=None):
    """Per-group metrics from served rows (is_live or needs_confirmation)."""
    today = today or date.today()
    now = now or datetime.now(timezone.utc)
    stale_cutoff = now - timedelta(days=STALE_CHECK_DAYS)
    closing_end = today + timedelta(days=CLOSING_DAYS)
    groups = {}
    for row in rows:
        g = groups.setdefault(group_of(row), {
            "served": 0, "live": 0, "needs_confirmation": 0, "present": dict.fromkeys(FIELDS, 0),
            "closing_7d": 0, "past_deadline_served": 0, "stale_last_checked": 0,
            "_dups": {}, })
        if not (row.get("is_live") is True or row.get("needs_confirmation") is True):
            continue
        g["served"] += 1
        if row.get("is_live") is True:
            g["live"] += 1
        else:
            g["needs_confirmation"] += 1
        for field in FIELDS:
            if _present(row.get(field)):
                g["present"][field] += 1
        deadline = _parse_date(row.get("deadline"))
        if deadline is not None:
            if deadline < today:
                g["past_deadline_served"] += 1
            elif deadline <= closing_end:
                g["closing_7d"] += 1
        checked = _parse_ts(row.get("last_checked"))
        if checked is None or checked < stale_cutoff:
            g["stale_last_checked"] += 1
        key = _dup_key(row)
        if key:
            g["_dups"][key] = g["_dups"].get(key, 0) + 1
    out = {}
    for name, g in groups.items():
        served = g["served"]
        na = NOT_APPLICABLE.get(name, set())
        out[name] = {
            "served": served,
            "live": g["live"],
            "needs_confirmation": g["needs_confirmation"],
            "pct": {f: (None if f in na else (round(100.0 * g["present"][f] / served, 1) if served else 0.0))
                    for f in FIELDS},
            "closing_7d": g["closing_7d"],
            "past_deadline_served": g["past_deadline_served"],
            "duplicates": sum(c - 1 for c in g["_dups"].values() if c > 1),
            "stale_last_checked": g["stale_last_checked"],
        }
    return out


def detect_drops(current, previous, threshold=DROP_THRESHOLD, min_previous=DROP_MIN_PREVIOUS):
    """Groups whose live count fell by more than ``threshold`` vs the last report."""
    drops = []
    for name, prev_live in (previous or {}).items():
        if not isinstance(prev_live, int) or prev_live < min_previous:
            continue
        now_live = (current.get(name) or {}).get("live", 0)
        if now_live < prev_live * (1 - threshold):
            drops.append({"category": name, "previous": prev_live, "current": now_live,
                          "drop_pct": round(100.0 * (prev_live - now_live) / prev_live, 1)})
    return drops


def check_workflow_freshness(runs_by_workflow, now=None, max_age_hours=RUN_MAX_AGE_HOURS):
    """``runs_by_workflow``: workflow file -> ISO time of last success (or None)."""
    now = now or datetime.now(timezone.utc)
    stale = []
    for workflow, finished in sorted(runs_by_workflow.items()):
        ts = _parse_ts(finished) if finished else None
        if ts is None or now - ts > timedelta(hours=max_age_hours):
            stale.append({"workflow": workflow, "last_success": finished})
    return stale


def evaluate(metrics, previous_live, workflow_runs, now=None):
    problems = []
    for drop in detect_drops(metrics, previous_live):
        problems.append("live count drop {category}: {previous} -> {current} (-{drop_pct}%)".format(**drop))
    for name, m in sorted(metrics.items()):
        if m["past_deadline_served"] > 0:
            problems.append("past-deadline rows served in {}: {}".format(name, m["past_deadline_served"]))
    for item in check_workflow_freshness(workflow_runs, now):
        problems.append("workflow {workflow} has no success in {h}h (last: {last_success})".format(
            h=RUN_MAX_AGE_HOURS, **item))
    return problems


def render_markdown(metrics, problems, generated_at):
    def pct(v):
        return "n/a" if v is None else "{:.0f}%".format(v)
    lines = ["# Data health", "", "Generated {}".format(generated_at), ""]
    lines.append("**Status: {}**".format("FAIL" if problems else "OK"))
    for p in problems:
        lines.append("- {}".format(p))
    lines += ["", "| category | live | needs-conf | deadline | desc | funding | logo | region "
              "| closing 7d | past-deadline | dupes | stale >14d |",
              "|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|"]
    for name in sorted(metrics):
        m = metrics[name]
        p = m["pct"]
        lines.append("| {} | {} | {} | {} | {} | {} | {} | {} | {} | {} | {} | {} |".format(
            name, m["live"], m["needs_confirmation"], pct(p["deadline"]), pct(p["description"]),
            pct(p["funding"]), pct(p["logo"]), pct(p["region"]), m["closing_7d"],
            m["past_deadline_served"], m["duplicates"], m["stale_last_checked"]))
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- #
# IO
# --------------------------------------------------------------------------- #
def _http_json(url, headers):
    req = urllib.request.Request(url, headers=dict(headers, **{"User-Agent": UA}))
    with urllib.request.urlopen(req, timeout=60) as response:
        return json.load(response)


def fetch_served_rows(base_url, key, fetch=_http_json):
    base = base_url.rstrip("/") + "/rest/v1/opportunities"
    headers = {"apikey": key, "Authorization": "Bearer " + key}
    rows, offset = [], 0
    flt = urllib.parse.quote("(is_live.eq.true,needs_confirmation.eq.true)", safe="(),.=")
    while True:
        url = "{}?select={}&or={}&order=id&limit={}&offset={}".format(
            base, urllib.parse.quote(SELECT, safe=",:>-_"), flt, PAGE, offset)
        batch = fetch(url, headers)
        rows.extend(batch)
        if len(batch) < PAGE:
            return rows
        offset += PAGE


def fetch_workflow_runs(repo, token, workflows, fetch=_http_json):
    """workflow file -> ISO ``updated_at`` of the latest successful run on main."""
    headers = {"Accept": "application/vnd.github+json", "Authorization": "Bearer " + token}
    result = {}
    for workflow in sorted(set(workflows)):
        url = ("https://api.github.com/repos/{}/actions/workflows/{}/runs"
               "?status=success&branch=main&per_page=1").format(repo, workflow)
        try:
            runs = fetch(url, headers).get("workflow_runs") or []
            result[workflow] = runs[0].get("updated_at") if runs else None
        except Exception as error:  # noqa: BLE001 - an unreadable run is a failed check
            print("warning: could not read runs for {}: {}".format(workflow, error), file=sys.stderr)
            result[workflow] = None
    return result


def load_history(path=HISTORY_PATH):
    try:
        with open(path) as handle:
            data = json.load(handle)
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def save_history(history, snapshot, path=HISTORY_PATH):
    history = (history + [snapshot])[-HISTORY_KEEP:]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as handle:
        json.dump(history, handle, indent=1)
        handle.write("\n")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--json-out", default="health_report.json")
    ap.add_argument("--summary-out", default=os.environ.get("GITHUB_STEP_SUMMARY"))
    ap.add_argument("--history", default=HISTORY_PATH)
    ap.add_argument("--no-history-write", action="store_true")
    ap.add_argument("--skip-workflows", action="store_true",
                    help="skip the GitHub Actions freshness check (local runs)")
    args = ap.parse_args(argv)

    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_ANON_KEY") or os.environ.get("SUPABASE_KEY")
    if not (url and key):
        print("ERROR: SUPABASE_URL and SUPABASE_ANON_KEY are required", file=sys.stderr)
        return 2
    rows = fetch_served_rows(url, key)
    now = datetime.now(timezone.utc)
    metrics = compute_metrics(rows, now=now)

    history = load_history(args.history)
    previous = history[-1]["live"] if history else {}
    token, repo = os.environ.get("GITHUB_TOKEN"), os.environ.get("GITHUB_REPOSITORY")
    if args.skip_workflows or not (token and repo):
        runs = {}
        print("note: workflow freshness check skipped", file=sys.stderr)
    else:
        runs = fetch_workflow_runs(repo, token, CATEGORY_WORKFLOWS.values())
    problems = evaluate(metrics, previous, runs, now)

    generated = now.isoformat(timespec="seconds")
    report = {"generated_at": generated, "problems": problems, "metrics": metrics,
              "workflow_last_success": runs}
    with open(args.json_out, "w") as handle:
        json.dump(report, handle, indent=1)
    markdown = render_markdown(metrics, problems, generated)
    print(markdown)
    if args.summary_out:
        with open(args.summary_out, "a") as handle:
            handle.write(markdown)
    if not args.no_history_write:
        save_history(history, {"ts": generated, "live": {k: v["live"] for k, v in metrics.items()}},
                     args.history)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
