"""Coverage benchmark: how many well-known must-have programmes do we track?

Read-only. Usage: python3 -m pipeline.coverage <shards_dir>
"""
import json
import os
import re
import sys
from urllib.parse import urlparse

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline import publish_supabase as ps  # noqa: E402

BENCH_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "data", "benchmarks")
CATEGORIES = ["fellowships", "scholarships", "grants", "research", "startup",
              "community", "open_source", "hackathons"]
# Domains hosting many unrelated programmes: a host match alone proves nothing.
SHARED_DOMAINS = {
    "google.com", "developers.google.com", "research.google", "github.com",
    "microsoft.com", "amazon.com", "aws.amazon.com", "mlh.io", "linuxfoundation.org",
    "mozilla.org", "foundation.mozilla.org", "daad.de", "nsf.gov", "ox.ac.uk",
    "mit.edu", "stanford.edu", "worldbank.org", "facebook.com", "meta.com",
    "devpost.com", "unstop.com", "devfolio.co", "nvidia.com", "figma.com",
    "notion.com", "postman.com", "wikimedia.org", "meta.wikimedia.org",
    "apache.org", "gnome.org", "cncf.io", "jetbrains.com", "docker.com",
    "gov.in", "europa.eu", "ec.europa.eu", "canada.ca", "gov.uk",
}
STOP = {"the", "of", "and", "for", "in", "on", "a", "an", "to", "program", "programme",
        "programs", "2024", "2025", "2026", "2027"}
JUNK_REASONS = {"source_removed", "not_an_opportunity", "junk", "duplicate_junk"}


def tokens(s):
    return {t for t in re.findall(r"[a-z0-9]+", (s or "").lower()) if t not in STOP}


def host(url):
    if not isinstance(url, str) or not url:
        return ""
    h = urlparse(url if "//" in url else "//" + url).hostname or ""
    return h.lower()


def host_matches(h, domain):
    domain = domain.lower().lstrip(".")
    return bool(h) and (h == domain or h.endswith("." + domain))


def row_name(r):
    return r.get("programme_name") or r.get("title") or r.get("name") or ""


def name_overlap(item, name):
    rt = tokens(name)
    best = 0.0
    for cand in [item.get("name")] + list(item.get("aliases") or []):
        ct = tokens(cand)
        if ct and rt:
            best = max(best, len(ct & rt) / len(ct))
    return best


def match(item, rows):
    """Rows matching a benchmark item (domain host match + name or specific domain)."""
    # A programme can have several official domains (e.g. Fulbright).
    domains = [item["domain"]] + list(item.get("extra_domains") or [])
    out = []
    for r in rows:
        hit = [d for d in domains if any(host_matches(host(r.get(k)), d)
                                         for k in ("official_url", "application_url", "url"))]
        if not hit:
            continue
        specific = any(d.lower() not in SHARED_DOMAINS for d in hit)
        if specific or name_overlap(item, row_name(r)) >= 0.5:
            out.append(r)
    return out


def is_junk(r):
    return r.get("hidden_reason") in JUNK_REASONS


def load_category(shards_dir, cat):
    for fn in (cat + ".json", cat.replace("_", "-") + ".json"):
        p = os.path.join(shards_dir, fn)
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                return json.load(f)
    return []


def load_benchmark(cat, bench_dir=BENCH_DIR):
    with open(os.path.join(bench_dir, cat + ".json"), encoding="utf-8") as f:
        return json.load(f)


def coverage(items, rows):
    rows = [r for r in rows if not is_junk(r)]
    tracked, served, missing = 0, 0, []
    for it in items:
        m = match(it, rows)
        if m:
            tracked += 1
            if any(ps.is_serving(r) for r in m):
                served += 1
        else:
            missing.append(it)
    return tracked, served, missing


def summary_line(shard, rows, bench_dir=BENCH_DIR):
    """One-line coverage for a shard, or None when it has no benchmark."""
    cat = shard.replace("-", "_")
    if not os.path.exists(os.path.join(bench_dir, cat + ".json")):
        return None
    items = load_benchmark(cat, bench_dir)
    n = len(items)
    if not n:
        return None
    t, s, miss = coverage(items, rows)
    return "coverage: tracked={}/{} ({:.0f}%) served={}/{} ({:.0f}%) missing={}".format(
        t, n, 100.0 * t / n, s, n, 100.0 * s / n, ", ".join(m["name"] for m in miss[:5]))


def main(argv):
    if len(argv) != 2:
        print("usage: python3 -m pipeline.coverage <shards_dir>", file=sys.stderr)
        return 2
    total_missing = 0
    lines = ["# Coverage benchmark", ""]
    for cat in CATEGORIES:
        items = load_benchmark(cat)
        t, s, miss = coverage(items, load_category(argv[1], cat))
        n = len(items)
        total_missing += len(miss)
        lines.append("## {}: {} benchmark, tracked {:.0f}% ({}/{}), served {:.0f}% ({}/{})".format(
            cat, n, 100.0 * t / n, t, n, 100.0 * s / n, s, n))
        for it in miss:
            lines.append("- missing: {} ({})".format(it["name"], it["domain"]))
        lines.append("")
    lines.append("Total missing: {}".format(total_missing))
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
