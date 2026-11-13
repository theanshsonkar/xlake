"""Link-quality check for served programme and hackathon rows.

Uses only what is already on the row: no extra crawling. Flags (never blocks, except
``link_dead``, which publish_supabase.quality_reason turns into "not served"):
  link_homepage   apply/official link is a bare homepage (path "/" or en, home, index.html...)
                  AND another row of the shard on the same host links a deeper page (the site
                  hosts several programmes). A programme's own site (thielfellowship.org,
                  apply.pif.gov) is never flagged.
  link_aggregator link host is a job board / aggregator (hackathons hosted on one by design are exempt)
  link_dead       ``link_fail_count`` >= 2: two consecutive definitive failures (HTTP 404 or DNS),
                  counted in programme_core.merge_programmes and reset on any successful read.
                  403/429/5xx/timeouts are unknown and never counted.
  link_vacancy    URL or title looks like a job vacancy / tender (stem.is_vacancy_text)
"""
import re
from typing import Dict, Iterable, List, Set
from urllib.parse import urlparse

from categories.stem import is_vacancy_text
from core.jobmeta import _AGGREGATOR_LOGO_HOSTS

AGGREGATOR_HOSTS = _AGGREGATOR_LOGO_HOSTS + ("unstop.com", "linkedin.com", "dorahacks.io", "dare2compete.com",
                                             "letsintern.com", "cutshort.io", "instahyre.com", "foundit.in",
                                             "ziprecruiter.com", "simplyhired.com", "joinhandshake.com",
                                             "freshersworld.com", "youthall.com", "unigo.com", "profellow.com",
                                             "niche.com", "buddy4study.com", "ioscholarships.com",
                                             "cirkledin.com", "insidesherpa.com", "opportunitiesforyouth.org",
                                             "techcrunch.com")
PROGRAMME_CATEGORIES = ("fellowship", "scholarship", "grant", "research", "startup-founder",
                        "community", "open-source-programmes")
_GENERIC = {"en", "home", "index.html", "index.htm", "index.php", "en-us", "en-gb"}
DEAD_AFTER = 2


def in_scope(row: Dict) -> bool:
    t = row.get("record_type")
    return t == "hackathon" or (t == "programme" and row.get("category") in PROGRAMME_CATEGORIES)


def _link(row: Dict) -> str:
    for k in ("application_url", "apply_url", "official_url", "url"):
        if row.get(k):
            return str(row[k])
    return ""


def _split(url: str):
    try:
        p = urlparse(url.strip())
        host = (p.hostname or "").lower().rstrip(".")
    except ValueError:
        return "", ""
    return (host[4:] if host.startswith("www.") else host), p.path


def _is_landing(path: str) -> bool:
    return all(s.lower() in _GENERIC for s in path.split("/") if s)


def _is_aggregator(host: str) -> bool:
    return any(host == h or host.endswith("." + h) for h in AGGREGATOR_HOSTS)


def deeper_hosts(rows: Iterable[Dict]) -> Set[str]:
    """Hosts that have at least one row linking to a deeper (non-landing) path."""
    out = set()
    for r in rows:
        if in_scope(r):
            host, path = _split(_link(r))
            if host and not _is_landing(path):
                out.add(host)
    return out


def flags(row: Dict, deeper: Set[str] = frozenset()) -> List[str]:
    out = []
    host, path = _split(_link(row))
    hackathon = row.get("record_type") == "hackathon"
    aggregator = _is_aggregator(host)
    if host and _is_landing(path) and not (hackathon and aggregator):
        if host in deeper:
            out.append("link_homepage")
    if aggregator and not hackathon:
        out.append("link_aggregator")
    if int(row.get("link_fail_count") or 0) >= DEAD_AFTER:
        out.append("link_dead")
    if is_vacancy_text(_link(row)) or is_vacancy_text(row.get("title") or row.get("programme_name")):
        out.append("link_vacancy")
    return sorted(out)


def annotate(rows: List[Dict], now: str) -> Dict[str, int]:
    deeper = deeper_hosts(rows)
    counts = {"ok": 0, "homepage": 0, "aggregator": 0, "dead": 0, "vacancy": 0, "checked": 0}
    for row in rows:
        if not in_scope(row):
            continue
        f = flags(row, deeper)
        row["link_quality"], row["link_checked_at"] = (f or "ok"), now
        counts["checked"] += 1
        counts["ok"] += not f
        for name in f:
            counts[name[5:]] += 1
    return counts
