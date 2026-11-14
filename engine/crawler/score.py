"""Type guess, 0..100 score, junk test and name/domain matching. Word lists live in data/."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from typing import Dict, List

from crawler import urls

_NAME_NOISE = {"inc", "ltd", "llc", "labs", "technologies", "tech", "ai", "hq", "the", "co",
               "corp", "pvt", "private", "limited"}
_LABEL_PREFIXES = ("get", "try", "use", "join", "hello", "go")
_LABEL_SUFFIXES = ("hq", "app", "labs", "ai", "inc", "tech", "io")


@lru_cache(maxsize=1)
def load_types() -> Dict:
    return json.loads((urls.DATA / "types.json").read_text())


@lru_cache(maxsize=1)
def deny_domains() -> frozenset:
    return frozenset(json.loads((urls.DATA / "deny_domains.json").read_text()))


def is_denied(url: str) -> bool:
    return urls.registered_domain(url) in deny_domains()


def _tokens(text: str) -> List[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def is_junk(page: Dict) -> bool:
    junk = set(load_types()["junk"])
    path = urls.normalise(page.get("url", "")).split("//", 1)[-1].partition("/")[2]
    return bool(junk & set(_tokens(path)) or junk & set(_tokens(page.get("title") or "")))


def _hits(words: List[str], haystack: str) -> int:
    return sum(1 for w in words if w in haystack)


def _by_type(page: Dict) -> Dict[str, float]:
    head = ((page.get("title") or "") + " " + page.get("url", "")).lower()
    body = (page.get("text") or "").lower()
    return {name: 3 * _hits(words, head) + min(_hits(words, body), 5)
            for name, words in load_types()["types"].items()}


def type_guess(page: Dict) -> str:
    weights = _by_type(page)
    best = max(weights, key=weights.get)
    return best if weights[best] > 0 else "unknown"


def score(page: Dict) -> float:
    value = min(100.0, 20 * max(_by_type(page).values()))
    if is_junk(page):
        value *= 0.3
    if len((page.get("text") or "").split()) < 80:
        value *= 0.5
    if page.get("status_code") != 200:
        value *= 0.5
    return round(value, 1)


def link_is_opportunity(text: str, url: str) -> bool:
    words = load_types()["link_words"]
    haystack = (text or "").lower() + " " + urls.normalise(url).lower()
    return any(w in haystack for w in words)


def _compact(text: str) -> str:
    return "".join(t for t in _tokens(text) if t not in _NAME_NOISE)


def name_matches_domain(name: str, url: str) -> bool:
    compact = _compact(name or "")
    if len(compact) < 3:
        return False
    label = urls.registered_domain(url).split(".")[0]
    variants = {label}
    for p in _LABEL_PREFIXES:
        if label.startswith(p):
            variants.add(label[len(p):])
    for v in list(variants):
        for s in _LABEL_SUFFIXES:
            if v.endswith(s):
                variants.add(v[:-len(s)])
    return compact in {v for v in variants if v}
