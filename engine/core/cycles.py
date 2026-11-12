"""Per-cycle date history for recurring programmes (pure, no I/O).

``record`` keeps ``row["cycles"]``: up to 10 ``{opens, deadline, first_seen}``
entries sorted by deadline and deduped by deadline. ``predict_next`` guesses the
next cycle one year after the latest past one (only when spacing is ~annual).
"""
from __future__ import annotations

import re
from datetime import date
from typing import Dict, List, Optional

MAX_CYCLES = 10
PROGRAMME_TYPES = ("programme", "hackathon")
_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MONTHS = ["January", "February", "March", "April", "May", "June", "July",
           "August", "September", "October", "November", "December"]


def _iso(v) -> Optional[str]:
    if isinstance(v, str) and _ISO.match(v.strip()[:10]) and len(v.strip()) >= 10:
        s = v.strip()[:10]
        try:
            date.fromisoformat(s)
        except ValueError:
            return None
        return s
    return None


def _first_iso(row: dict, *keys) -> Optional[str]:
    for k in keys:
        d = _iso(row.get(k))
        if d:
            return d
    return None


def is_programme_like(row: dict) -> bool:
    return row.get("record_type") in PROGRAMME_TYPES


def merge_cycle(cycles: List[dict], deadline: str, opens: Optional[str], today: str) -> None:
    for c in cycles:
        if c.get("deadline") == deadline:
            if not c.get("opens") and opens:
                c["opens"] = opens
            if today < (c.get("first_seen") or today):
                c["first_seen"] = today
            return
    cycles.append({"opens": opens, "deadline": deadline, "first_seen": today})


def record(row: dict, today, extra_deadlines=()) -> bool:
    """Update ``row['cycles']`` from the row's dates. Returns True if changed.
    ``extra_deadlines``: additional past-cycle ISO deadlines (used by backfill)."""
    if not is_programme_like(row):
        return False
    t = today.isoformat() if isinstance(today, date) else str(today)[:10]
    old = row.get("cycles")
    cycles = [dict(c) for c in old if isinstance(c, dict) and _iso(c.get("deadline"))] \
        if isinstance(old, list) else []
    opens = _first_iso(row, "opening_date", "opens", "registration_start")
    dl = _first_iso(row, "deadline", "registration_deadline")
    if dl:
        merge_cycle(cycles, dl, opens, t)
    for key in ("last_deadline",):
        ld = _iso(row.get(key))
        if ld:
            merge_cycle(cycles, ld, None, t)
    for ld in extra_deadlines:
        if _iso(ld):
            merge_cycle(cycles, ld, None, t)
    cycles.sort(key=lambda c: c["deadline"])
    cycles = cycles[-MAX_CYCLES:]
    if cycles == old or (not cycles and old is None):
        return False
    row["cycles"] = cycles
    return True


def _shift(d: date, years: int) -> date:
    try:
        return d.replace(year=d.year + years)
    except ValueError:  # Feb 29
        return d.replace(year=d.year + years, day=28)


def _today(today) -> date:
    return today if isinstance(today, date) else date.fromisoformat(str(today)[:10])


def predict_next(row: dict, today) -> Optional[dict]:
    td = _today(today)
    cycles = row.get("cycles")
    if not isinstance(cycles, list):
        return None
    past = sorted((c for c in cycles if isinstance(c, dict) and _iso(c.get("deadline"))
                   and date.fromisoformat(c["deadline"]) < td), key=lambda c: c["deadline"])
    if not past:
        return None
    cur = _first_iso(row, "deadline", "registration_deadline")
    if cur and date.fromisoformat(cur) >= td:
        return None
    # Facts, not guesses: predict only for a programme the crawler already judged
    # recurring (upcoming), or one we have seen close at least twice a year apart.
    # Hackathons are often one-off events, so they keep history but get no guess.
    if row.get("record_type") != "programme":
        return None
    dls = [date.fromisoformat(c["deadline"]) for c in past]
    for a, b in zip(dls, dls[1:]):
        if not 330 <= (b - a).days <= 400:
            return None
    if len(past) < 2 and row.get("lifecycle") != "upcoming":
        return None
    last = past[-1]
    base = dls[-1]
    n = 1
    while _shift(base, n) < td:
        n += 1
    opens = _iso(last.get("opens"))
    return {
        "expected_opens": _shift(date.fromisoformat(opens), n).isoformat() if opens else None,
        "expected_deadline": _shift(base, n).isoformat(),
        "basis": "annual",
        "cycles_seen": len(past),
    }


def next_cycle_text(pred: Optional[dict]) -> Optional[str]:
    if not pred:
        return None
    n = pred.get("cycles_seen") or 0
    lead = "Usually" if n >= 2 else "Last cycle suggests it"
    if pred.get("expected_opens"):
        d = date.fromisoformat(pred["expected_opens"])
        return "%s opens around %s (based on %d past cycle%s)" % (
            lead, _MONTHS[d.month - 1], n, "" if n == 1 else "s")
    if pred.get("expected_deadline"):
        d = date.fromisoformat(pred["expected_deadline"])
        return "%s closes around %d %s (based on %d past cycle%s)" % (
            lead, d.day, _MONTHS[d.month - 1], n, "" if n == 1 else "s")
    return None


def apply_prediction(row: dict, today) -> bool:
    """Set/remove expected_* and fill an empty next_cycle_hint. True if a prediction exists."""
    pred = predict_next(row, today) if row.get("lifecycle") in ("upcoming", "closed") else None
    if pred:
        row["expected_opens"] = pred["expected_opens"]
        row["expected_deadline"] = pred["expected_deadline"]
        if not row.get("next_cycle_hint"):
            row["next_cycle_hint"] = next_cycle_text(pred)
        return True
    row.pop("expected_opens", None)
    row.pop("expected_deadline", None)
    return False


def finalize(rows: List[dict], today) -> Dict[str, int]:
    have = changed = predicted = 0
    for r in rows:
        if record(r, today):
            changed += 1
        if apply_prediction(r, today):
            predicted += 1
        if r.get("cycles"):
            have += 1
    return {"rows_with_history": have, "changed": changed, "predicted": predicted}
