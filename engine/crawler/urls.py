"""URL helpers: normalise, host, registered domain, same-site."""

from __future__ import annotations

import json
import urllib.parse
from functools import lru_cache
from pathlib import Path
from typing import List

DATA = Path(__file__).resolve().parents[1] / "data" / "crawler"
_TRACKING = ("utm_", "ref", "fbclid", "gclid", "mc_cid", "mc_eid")


@lru_cache(maxsize=1)
def _suffixes() -> frozenset:
    return frozenset(json.loads((DATA / "suffixes.json").read_text()))


def normalise(url: str) -> str:
    """Strip fragment and tracking params; lowercase scheme/host; drop default ports."""
    p = urllib.parse.urlsplit((url or "").strip())
    query = [(k, v) for k, v in urllib.parse.parse_qsl(p.query, keep_blank_values=True)
             if not k.lower().startswith(_TRACKING[0]) and k.lower() not in _TRACKING[1:]]
    host = (p.hostname or "").lower()
    if p.port and p.port not in (80, 443):
        host += ":%d" % p.port
    path = p.path or "/"
    return urllib.parse.urlunsplit((p.scheme.lower(), host, path, urllib.parse.urlencode(query), ""))


def host(url: str) -> str:
    return (urllib.parse.urlsplit(url).hostname or "").lower()


def registered_domain(url_or_host: str) -> str:
    h = host(url_or_host) if "/" in url_or_host else url_or_host.lower()
    labels: List[str] = [x for x in h.split(".") if x]
    if len(labels) <= 2:
        return h
    if ".".join(labels[-2:]) in _suffixes():
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def same_site(a: str, b: str) -> bool:
    return registered_domain(a) == registered_domain(b)
