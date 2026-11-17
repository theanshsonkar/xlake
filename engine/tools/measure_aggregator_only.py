"""Read-only: count rows per shard that have ONLY aggregator links (url/apply_url/official_url).

Usage: python3 tools/measure_aggregator_only.py [dir-or-json ...]   (default: tests/fixtures, fixtures)
Never writes. Local lake shards are not committed, so this falls back to fixtures.
"""
import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pipeline import publish_supabase as ps  # noqa: E402


def rows_of(path):
    for root, _, files in os.walk(path) if os.path.isdir(path) else [(os.path.dirname(path), 0, [os.path.basename(path)])]:
        for f in files:
            if not f.endswith(".json"):
                continue
            try:
                data = json.load(open(os.path.join(root, f)))
            except (OSError, ValueError):
                continue
            items = data if isinstance(data, list) else next((v for v in data.values() if isinstance(v, list)), []) if isinstance(data, dict) else []
            for r in items:
                if isinstance(r, dict):
                    yield r


def main(argv):
    total, hit = Counter(), Counter()
    for p in argv or ["tests/fixtures", "fixtures"]:
        for r in rows_of(p):
            if not (r.get("url") or r.get("official_url") or r.get("application_url")):
                continue
            k = ps.record_type(r) + ("/" + str(r.get("category")) if r.get("category") else "")
            total[k] += 1
            hit[k] += ps.aggregator_only(r)
    for k in sorted(total):
        print("{:28s} {:5d} rows  {:5d} aggregator-only ({:.0%})".format(k, total[k], hit[k], hit[k] / total[k]))


if __name__ == "__main__":
    main(sys.argv[1:])
