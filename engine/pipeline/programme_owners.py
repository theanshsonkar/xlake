"""Measure cross-category duplicate programmes and write data/operations/programme_owners.json.

    python3 -m pipeline.programme_owners <shards_dir> [--write] [--out PATH]

The owners file maps normalised official URL -> owning category. Each category leg reads it
(categories.programme_core.hide_non_owned); no leg reads another category's shard.
"""
from __future__ import annotations

import argparse
import difflib
import glob
import json
import os
import sys
from collections import Counter, defaultdict
from itertools import combinations

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from categories import programme_core as core  # noqa: E402
from pipeline import publish_supabase as ps  # noqa: E402

NAME_SIMILARITY = 0.85
URL_NAME_SIMILARITY = 0.6
CROSS_HOST_NAME_SIMILARITY = 0.9
registrable_host = core.registrable_host


def load_serving(shards_dir: str) -> list:
    rows = []
    for path in sorted(glob.glob(os.path.join(shards_dir, "*.json"))):
        for row in json.load(open(path)):
            if row.get("record_type") == "programme" and ps.is_serving(row):
                rows.append(row)
    return rows


def find_groups(rows: list) -> list:
    """Groups (lists of rows) of the same programme spanning at least two categories."""
    parent = list(range(len(rows)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i, j):
        parent[find(i)] = find(j)

    keys = [core.programme_owner_key(r) for r in rows]
    names = [core._row_name_key(r) for r in rows]
    by_url, by_host = defaultdict(list), defaultdict(list)
    for i, key in enumerate(keys):
        if not key:
            continue
        host = registrable_host(key)
        if key.split("/", 1)[1].strip("/"):  # a bare host is not a programme identity
            by_url[key].append(i)
        by_host[host].append(i)
    for members in by_url.values():  # one URL can host several schemes: names must still agree loosely
        for i, j in combinations(members, 2):
            if names[i] and names[j] and difflib.SequenceMatcher(None, names[i], names[j]).ratio() >= URL_NAME_SIMILARITY:
                union(i, j)
    for members in by_host.values():
        for i, j in combinations(members, 2):
            if rows[i].get("category") != rows[j].get("category") and names[i] and names[j] and \
                    difflib.SequenceMatcher(None, names[i], names[j]).ratio() >= NAME_SIMILARITY:
                union(i, j)
    # Different site: sibling hosts (same second-level label) or same organiser, with a strong name match.
    orgs = [core._normalised_programme_name(r.get("organizer")) for r in rows]
    sims = [core.programme_similarity_name(r) for r in rows]
    for i, j in combinations(range(len(rows)), 2):
        if rows[i].get("category") == rows[j].get("category") or find(i) == find(j):
            continue
        if not (keys[i] and keys[j] and sims[i] and sims[j]) or \
                difflib.SequenceMatcher(None, sims[i], sims[j]).ratio() < CROSS_HOST_NAME_SIMILARITY or \
                core.variant_conflict(sims[i], sims[j]):
            continue
        siblings = core.host_label(keys[i]) == core.host_label(keys[j])
        same_org = orgs[i] and orgs[i] == orgs[j] and orgs[i] != "not stated" and "." not in orgs[i]
        if siblings or same_org:
            union(i, j)
    groups = defaultdict(list)
    for i in range(len(rows)):
        groups[find(i)].append(rows[i])
    return [g for g in groups.values() if len({r.get("category") for r in g}) > 1]


def build_owners(groups: list) -> dict:
    owners = {}
    for group in groups:
        owner = core.choose_owner(group)
        for row in group:
            key = core.programme_owner_key(row)
            if key:
                owners[key] = owner
    return dict(sorted(owners.items()))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("shards_dir")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--out", default=core.OWNERS_PATH)
    args = ap.parse_args(argv)
    groups = find_groups(load_serving(args.shards_dir))
    owners = build_owners(groups)
    pairs, hidden = Counter(), Counter()
    for group in groups:
        cats = sorted({r["category"] for r in group})
        for pair in combinations(cats, 2):
            pairs[pair] += 1
        for row in group:
            if owners.get(core.programme_owner_key(row)) not in (None, row["category"]):
                hidden[row["category"]] += 1
    print("groups={} owners_entries={}".format(len(groups), len(owners)))
    print("pairs", dict(pairs))
    print("would_hide", dict(hidden))
    for group in groups[:10]:
        print("-", [(r["category"], r.get("programme_name"), core.programme_owner_key(r)) for r in group],
              "->", core.choose_owner(group))
    if args.write:
        with open(args.out, "w") as handle:
            json.dump(owners, handle, indent=1, sort_keys=True)
            handle.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
