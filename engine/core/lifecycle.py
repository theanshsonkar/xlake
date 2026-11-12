"""Single definition of an opportunity's lifecycle (pure, no I/O).

``lifecycle`` is derived from the legacy liveness flags (``is_live``,
``needs_confirmation``, ``programme_status``/``status``), which stay the source
of truth in phase 1. It is deliberately NOT called ``status`` (hackathons and
the Supabase table already use that name).

States:
  open        live and accepting applications (or no known deadline)
  upcoming    live next-cycle row (programme_status/status == "upcoming")
  unverified  needs_confirmation: shown only as "check the source"
  closed      not live; carries ``closed_reason`` and ``closed_at``

``reconcile`` runs once per shard at finalize, so every crawl leg ends with
consistent flags: dead stamps are removed from live rows, and open/unverified
rows whose ISO deadline has passed are closed (even if the page fetch failed).
"""
from __future__ import annotations

from datetime import date
from typing import Dict, Iterable, Optional

OPEN, UPCOMING, UNVERIFIED, CLOSED = "open", "upcoming", "unverified", "closed"
_DEAD_STAMPS = ("went_dead_at", "liveness_reason", "closed_reason", "closed_at")
# hidden_reason values that only describe liveness (set by retire steps). On a row
# that is live again they are stale; quality reasons are left alone.
_LIVENESS_HIDDEN = ("closed_deadline_passed", "stale_needs_confirmation")


def infer(row: Dict) -> str:
    """Lifecycle from legacy flags. A row with no ``is_live`` key counts as live
    (same default as core.retire) unless it needs confirmation."""
    if row.get("needs_confirmation") is True and row.get("is_live") is not True:
        return UNVERIFIED
    if row.get("is_live", True) is True:
        if row.get("programme_status") == "upcoming" or row.get("status") == "upcoming":
            return UPCOMING
        return OPEN
    return CLOSED


def _deadline(row: Dict) -> Optional[date]:
    for key in ("deadline", "registration_deadline"):
        v = row.get(key)
        if isinstance(v, str) and len(v) >= 10:
            try:
                return date.fromisoformat(v[:10])
            except ValueError:
                continue
    return None


def deadline_passed(row: Dict, today: Optional[date] = None) -> bool:
    """True when the row has an ISO deadline strictly before ``today`` (UTC)
    and is not an upcoming (next-cycle) row."""
    if row.get("programme_status") == "upcoming" or row.get("status") == "upcoming":
        return False
    d = _deadline(row)
    if d is None:
        return False
    return d < (today or date.today())


def close(row: Dict, now: str, reason: str) -> None:
    was_closed = row.get("is_live") is False and row.get("needs_confirmation") is not True
    dead_at = (row.get("went_dead_at") if was_closed and row.get("went_dead_at") else now)
    if reason == "deadline_passed" and _deadline(row):
        # Stable: the row died on its deadline, so re-closing it after a
        # collector re-opens it never moves the timestamp.
        dead_at = _deadline(row).isoformat()
    row["is_live"] = False
    row["needs_confirmation"] = False
    row["went_dead_at"] = dead_at
    row["liveness_reason"] = reason
    row["lifecycle"] = CLOSED
    row["closed_reason"] = reason
    row["closed_at"] = dead_at
    if row.get("record_type") == "programme" and row.get("programme_status") != "upcoming":
        row["programme_status"] = "closed"
        if reason == "deadline_passed" and not row.get("hidden_reason"):
            row["hidden_reason"] = "closed_deadline_passed"  # as retire_closed does


def reconcile(rows: Iterable[Dict], today: date, now: str) -> Dict[str, int]:
    stats = {OPEN: 0, UPCOMING: 0, UNVERIFIED: 0, CLOSED: 0,
             "revived_cleaned": 0, "deadline_closed": 0, "deadline_unparsed": 0}
    for row in rows:
        state = infer(row)
        row["lifecycle"] = state
        if state != CLOSED:
            if any(k in row for k in _DEAD_STAMPS):
                stats["revived_cleaned"] += 1
            for k in _DEAD_STAMPS:
                row.pop(k, None)
            if row.get("hidden_reason") in _LIVENESS_HIDDEN:
                row["hidden_reason"] = None
            if state in (OPEN, UNVERIFIED):
                if deadline_passed(row, today):
                    close(row, now, "deadline_passed")
                    state = CLOSED
                    stats["deadline_closed"] += 1
                elif _deadline(row) is None and any(
                        isinstance(row.get(k), str) and row.get(k).strip()
                        for k in ("deadline", "registration_deadline")):
                    stats["deadline_unparsed"] += 1
        if state == CLOSED:
            if not row.get("closed_reason"):
                row["closed_reason"] = (row.get("liveness_reason")
                                        or row.get("hidden_reason") or "unknown")
            if not row.get("closed_at") and row.get("went_dead_at"):
                row["closed_at"] = row["went_dead_at"]
        stats[state] += 1
    return stats
