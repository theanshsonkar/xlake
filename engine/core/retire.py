"""Freshness / retirement guard for the job lake (pure, offline-testable).

Rules (the "never retire on a failed fetch" invariant is the first one):

* a row on a board that was attempted but NOT read cleanly (failed, partial,
  truncated) is never retired, however old it is;
* a row absent from a board that WAS read cleanly is retired at once;
* a row whose board is no longer in the registry (and is not a self-managed
  source) and that has not been confirmed for ``days`` days is retired.

Retiring sets ``is_live=False`` and ``needs_confirmation=False`` so the row
stops serving; it is kept in the lake with the reason.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable, Optional, Set, Tuple

RETIRE_DAYS = 21
# Platforms whose rows are refreshed by their own collector, not by board sweeps.
SELF_MANAGED_PLATFORMS = frozenset({"zshah101-list"})


def _parse(ts) -> Optional[datetime]:
    if not isinstance(ts, str) or not ts:
        return None
    try:
        d = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _retire(r: Dict, now: str, reason: str) -> None:
    r["is_live"] = False
    r["needs_confirmation"] = False
    r["went_dead_at"] = now
    r["liveness_reason"] = reason


def apply(rows: Iterable[Dict], found_keys_of: Set[int], boards_read: Set[Tuple[str, str]],
          attempted: Optional[Set[Tuple[str, str]]], registry_boards: Optional[Set[Tuple[str, str]]],
          now: str, days: int = RETIRE_DAYS) -> Dict[str, int]:
    """``found_keys_of`` holds id(row) of rows confirmed this run."""
    attempted = attempted or set()
    stats = {"absent_from_board": 0, "board_gone_unconfirmed": 0,
             "blocked_failed_board": 0}
    now_dt = _parse(now) or datetime.now(timezone.utc)
    cutoff = now_dt - timedelta(days=days)
    for r in rows:
        if id(r) in found_keys_of or not r.get("is_live", True):
            continue
        board = (r.get("platform"), r.get("token"))
        if board in boards_read:
            _retire(r, now, "absent_from_board")
            stats["absent_from_board"] += 1
        elif board in attempted:
            stats["blocked_failed_board"] += 1  # failed read never retires
        elif (registry_boards is not None and board not in registry_boards
              and board[0] not in SELF_MANAGED_PLATFORMS):
            seen = _parse(r.get("last_seen"))
            if seen is not None and seen < cutoff:
                _retire(r, now, "board_gone_unconfirmed_{}d".format(days))
                stats["board_gone_unconfirmed"] += 1
    return stats
