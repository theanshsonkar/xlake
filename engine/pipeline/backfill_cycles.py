"""Read-only cycles backfill: python3 -m pipeline.backfill_cycles SHARD.json [--write OUT]

Reads the committed observation logs (data/operations/*observations*.json) for
ISO dates quoted in ``official_evidence`` (``deadline`` / ``last_deadline``
quotes, matched on ``programme_id``), applies ``core.cycles`` to each shard
row and prints how many rows gain history / get a prediction. ``--write`` saves
an updated copy to a local file only; the shard itself and S3 are never touched.
"""
from __future__ import annotations

import argparse
import copy
import glob
import json
import os
import re
import sys
from collections import defaultdict
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import cycles, lifecycle  # noqa: E402

OPS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "operations")
_ISO = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
_KEYS = ("deadline", "last_deadline")


def load_observed(ops_dir: str = OPS_DIR, today: date = None) -> dict:
    """programme_id -> sorted set of past ISO deadlines quoted in observations."""
    today = (today or date.today()).isoformat()
    out = defaultdict(set)
    for path in glob.glob(os.path.join(ops_dir, "*observations*.json")):
        for obs in json.load(open(path, encoding="utf-8")):
            ev = obs.get("official_evidence") or {}
            for k in _KEYS:
                q = (ev.get(k) or {}).get("quote") if isinstance(ev.get(k), dict) else None
                for d in _ISO.findall(q or ""):
                    if cycles._iso(d) and d < today:
                        out[obs.get("programme_id")].add(d)
    return {k: sorted(v) for k, v in out.items()}


def backfill(rows: list, observed: dict, today: date) -> dict:
    gained = predicted = 0
    new_rows = copy.deepcopy(rows)
    lifecycle.reconcile(new_rows, today, today.isoformat())  # as finalize does, on the copy
    for r in new_rows:
        had = bool(r.get("cycles"))
        cycles.record(r, today, observed.get(r.get("programme_id"), ()))
        if r.get("cycles") and not had:
            gained += 1
        if cycles.apply_prediction(r, today):
            predicted += 1
    return {"rows": len(rows), "gain_history": gained, "predicted": predicted, "new_rows": new_rows}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("shard")
    ap.add_argument("--write", metavar="OUT")
    a = ap.parse_args(argv)
    rows = json.load(open(a.shard, encoding="utf-8"))
    res = backfill(rows, load_observed(), date.today())
    print("%s: rows=%d gain_history=%d predicted=%d" % (
        os.path.basename(a.shard), res["rows"], res["gain_history"], res["predicted"]))
    if a.write:
        if os.path.abspath(a.write) == os.path.abspath(a.shard):
            print("refusing to overwrite the input shard", file=sys.stderr)
            return 2
        with open(a.write, "w", encoding="utf-8") as fh:
            json.dump(res["new_rows"], fh, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
