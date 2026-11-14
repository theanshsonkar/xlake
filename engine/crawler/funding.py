"""Funding door: dated, proven funding evidence for a company. Pure functions."""

from __future__ import annotations

import json
import re
from datetime import date
from typing import Dict, List, Optional, Tuple

from crawler import score

_SEASONS = {"winter": 1, "spring": 4, "summer": 6, "fall": 9, "autumn": 9}
_LONG = re.compile(r"\b(winter|spring|summer|fall|autumn)\s+(20\d{2})\b", re.I)
_SHORT = re.compile(r"\b([WSFX])(\d{2})\b")
_SHORT_MONTH = {"W": 1, "X": 4, "S": 6, "F": 9}
_META_KEYS = ("article:published_time", "og:published_time", "datepublished", "date", "publish-date")
_ISO = re.compile(r"\d{4}-\d{2}-\d{2}")


def batch_labels(text: str, today: date) -> List[Tuple[str, str, str]]:
    found: Dict[str, Tuple[str, str, str]] = {}
    text = text or ""

    def add(year: int, month: int, label: str, precision: str) -> None:
        try:
            start = date(year, month, 1)
        except ValueError:
            return
        if start <= today:
            found.setdefault(start.isoformat(), (start.isoformat(), label, precision))

    for m in _LONG.finditer(text):
        add(int(m.group(2)), _SEASONS[m.group(1).lower()], m.group(0), "month")
    for m in _SHORT.finditer(text):
        add(2000 + int(m.group(2)), _SHORT_MONTH[m.group(1)], m.group(0), "month")
    for w in score.load_types()["batch_words"]:
        pat = r"\b{0}\s+(?:of\s+)?(20\d{{2}})\b|\b(20\d{{2}})\s+{0}\b".format(re.escape(w))
        for m in re.finditer(pat, text, re.I):
            add(int(m.group(1) or m.group(2)), 1, m.group(0), "year")
    return sorted(found.values())


def _walk(node):
    if isinstance(node, list):
        for n in node:
            yield from _walk(n)
    elif isinstance(node, dict):
        yield node
        yield from _walk(node.get("@graph", []))


def _iso(value, today: date) -> Optional[str]:
    m = _ISO.match(str(value or "").strip())
    if not m:
        return None
    try:
        d = date.fromisoformat(m.group(0))
    except ValueError:
        return None
    return d.isoformat() if d <= today else None


def published_date(meta: dict, ld_blobs: List[str], time_values: List[str], today: date) -> Optional[str]:
    candidates = [meta.get(k) for k in _META_KEYS]
    for blob in ld_blobs or []:
        try:
            data = json.loads(blob)
        except ValueError:
            continue
        candidates.extend(n.get("datePublished") for n in _walk(data))
    if time_values:
        candidates.append(time_values[0])
    for c in candidates:
        found = _iso(c, today) if c else None
        if found:
            return found
    return None


def funding_quote(text: str) -> Optional[str]:
    phrases = score.load_types()["funding_proof"]
    for sentence in re.split(r"[.!?\n]", text or ""):
        s = sentence.strip()
        if s and any(p in s.lower() for p in phrases):
            return s[:300]
    return None


def from_anchor(anchor_text: str, page_url: str, today: date) -> Optional[Dict]:
    labels = batch_labels(anchor_text, today)
    if len(labels) != 1:
        return None
    start, _, precision = labels[0]
    return {"date": start, "precision": precision, "proof": page_url,
            "source_kind": "accelerator", "quote": (anchor_text or "")[:300]}


def from_page(page: dict, page_url: str, source_kind: str, today: date) -> Optional[Dict]:
    text = page.get("text") or ""
    title = page.get("title") or ""
    if page.get("published"):
        q = funding_quote(text)
        if q:
            return {"date": page["published"], "precision": "day", "proof": page_url,
                    "source_kind": source_kind, "quote": q}
    if source_kind != "accelerator":  # batch words elsewhere are intern cohorts, not funding
        return None
    labels = batch_labels(title + " " + text, today)
    if len({l[0] for l in labels}) != 1:
        return None
    start, label, precision = labels[0]
    i = text.lower().find(label.lower())
    if i >= 0:
        quote = text[max(0, i - 80):i + len(label) + 80].strip()
    else:
        quote = title
    return {"date": start, "precision": precision, "proof": page_url,
            "source_kind": "accelerator", "quote": quote[:300]}


def mentions(evidence: Optional[Dict], page: dict, name: str) -> bool:
    if not evidence:
        return False
    key = score._compact(name or "")
    if not key:
        return False
    if key in score._compact(evidence.get("quote") or ""):
        return True
    if evidence.get("source_kind") == "accelerator":
        return key in score._compact(page.get("title") or "") or key in score._compact(page.get("h1") or "")
    return False


def is_recent(ev: Optional[Dict], today: date, days: int = 365) -> bool:
    if not ev:
        return False
    try:
        d = date.fromisoformat(ev["date"])
    except (KeyError, ValueError, TypeError):
        return False
    return 0 <= (today - d).days <= days


def best(*evs: Optional[Dict]) -> Optional[Dict]:
    out = None
    for ev in evs:
        if ev and (out is None or ev["date"] > out["date"]):
            out = ev
    return out
