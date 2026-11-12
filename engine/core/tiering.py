"""Board tiering — how often each (platform, token) gets swept.

REGISTRY-PLAN.md section 3.1 defines four tiers by what a board has actually
PRODUCED, not by platform reputation:

    hot   sweep every  6h   a sweep saw a qualifying early-career role (any
                             country) in the last 30 days (last_qualifying_at)
    warm  sweep every 3 days produced one at some point, just not recently
    cold  sweep weekly      verified/live, never produced one
    dead  never             token is wrong (404/422) — resolve.py's job, not
                             this file's; a dead token should never reach here

"Qualifying" means it passed filters.classify() (career-stage-eligible,
technical), anywhere in the world — plain job count is not the measure. A board
with 500 senior roles and 0 early-career roles is COLD, not hot, no matter how
big it looks.

THE NUMBER THAT MUST NOT BE ASSUMED: historical measurements in
`engine/data/measure/` describe the board set preserved in
`archive/opportunity-lake-oldengine-2026-08-16/`, not the current company-scoped
registry at `data/operations/registry.json`.
This module refuses to fabricate that number: per_board_yield() computes it
from whatever history is actually passed in, and tier_for() falls back to
'cold' — never 'hot' — for a board with no measurement yet, so an unmeasured
board is swept least often until it proves itself, not most often on a guess.

No AI, no network. Pure functions over already-computed sweep history.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from core.paths import REGISTRY_PATH, TIER_STATE_PATH

REGISTRY = REGISTRY_PATH
TIER_STATE = TIER_STATE_PATH

RECENT_WINDOW_DAYS = 30

TIER_SWEEP_HOURS = {
    "hot": 6,
    "warm": 72,  # produced before, not in 30 days: every 3 days is enough
    "cold": 24 * 7,
    "dead": None,  # never
}


@dataclass
class BoardHistory:
    """What one (platform, token) board has produced across all sweeps so far.

    total_qualifying_ever: count of rows that ever passed both filters.classify
        and the quality gate on this board, across every sweep.
    qualifying_last_30d: same, but only rows first_seen within the last 30
        days — this is what separates hot from warm.
    sweeps_run: how many times this board has actually been fetched. Needed so
        a board fetched once with 0 qualifying roles (genuinely cold so far)
        is distinguishable from a board that has literally never been swept
        (no measurement at all, must not be scored as if it were proven cold).
    """

    platform: str
    token: str
    total_qualifying_ever: int = 0
    qualifying_last_30d: int = 0
    sweeps_run: int = 0
    last_swept_at: Optional[str] = None
    # When a sweep last saw at least one qualifying role on this board. This is
    # what "hot" is measured from (a date decays on its own; a counter did not).
    last_qualifying_at: Optional[str] = None


def per_board_yield(history: BoardHistory) -> Optional[float]:
    """Qualifying roles per sweep. None if there is no measurement at all —
    this is what stops a never-swept board from being silently scored as 0."""
    if history.sweeps_run == 0:
        return None
    return history.total_qualifying_ever / history.sweeps_run


def _ts(value: Optional[str]) -> Optional[datetime]:
    try:
        d = datetime.fromisoformat(value) if value else None
    except (TypeError, ValueError):
        return None
    if d is not None and d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d


def _recently_qualifying(history: BoardHistory, now: Optional[datetime]) -> bool:
    """A qualifying role seen within RECENT_WINDOW_DAYS. Old state files have
    no ``last_qualifying_at``; for them a positive legacy counter counts from
    ``last_swept_at`` (or as recent when no date is known at all)."""
    when = _ts(history.last_qualifying_at)
    if when is None and history.qualifying_last_30d > 0:
        when = _ts(history.last_swept_at)
        if when is None:
            return True
    if when is None:
        return False
    now = now or datetime.now(timezone.utc)
    return now - when <= timedelta(days=RECENT_WINDOW_DAYS)


def tier_for(history: BoardHistory, now: Optional[datetime] = None) -> str:
    """The tier a single board earns from its own history.

    Never 'hot' without recent production. Never 'dead' from here — dead is a
    token-validity fact owned by resolve.py, and this function is not shown
    that signal on purpose: mixing "board doesn't work" into "board is low
    yield" is exactly the A2/Citadel bug REGISTRY-PLAN.md section 2.1 exists
    to fix (a board with zero qualifying jobs is EMPTY-but-alive, not dead).
    """
    if history.sweeps_run == 0:
        # No measurement yet. Treat like cold — sweep it, but not eagerly,
        # until it has a real number. This is the deliberate fallback: an
        # unmeasured board must not default to 'hot'.
        return "cold"
    if _recently_qualifying(history, now):
        return "hot"
    if history.total_qualifying_ever > 0:
        return "warm"
    return "cold"


def sweep_due(history: BoardHistory, now: Optional[datetime] = None) -> bool:
    """Whether this board's tier says it should be swept right now."""
    tier = tier_for(history, now)
    hours = TIER_SWEEP_HOURS[tier]
    if hours is None:
        return False
    if not history.last_swept_at:
        return True
    now = now or datetime.now(timezone.utc)
    try:
        last = datetime.fromisoformat(history.last_swept_at)
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return True  # unknown last-swept time: never skip
    return now - last >= timedelta(hours=hours)


def load_tier_state(path: str = TIER_STATE) -> Dict[str, BoardHistory]:
    """(platform, token) -> BoardHistory, keyed 'platform|token'."""
    if not os.path.exists(path):
        return {}
    raw = json.load(open(path))
    out: Dict[str, BoardHistory] = {}
    for key, v in raw.items():
        out[key] = BoardHistory(
            platform=v["platform"], token=v["token"],
            total_qualifying_ever=v.get("total_qualifying_ever", 0),
            qualifying_last_30d=v.get("qualifying_last_30d", 0),
            sweeps_run=v.get("sweeps_run", 0),
            last_swept_at=v.get("last_swept_at"),
            last_qualifying_at=v.get("last_qualifying_at"),
        )
    return out


def save_tier_state(state: Dict[str, BoardHistory], path: str = TIER_STATE) -> None:
    raw = {
        key: {
            "platform": h.platform, "token": h.token,
            "total_qualifying_ever": h.total_qualifying_ever,
            "qualifying_last_30d": h.qualifying_last_30d,
            "sweeps_run": h.sweeps_run,
            "last_swept_at": h.last_swept_at,
            "last_qualifying_at": h.last_qualifying_at,
        }
        for key, h in state.items()
    }
    os.makedirs(os.path.dirname(path), exist_ok=True)
    json.dump(raw, open(path, "w"), indent=1)


def record_sweep(state: Dict[str, BoardHistory], platform: str, token: str,
                  qualifying_count: int,
                  swept_at: Optional[datetime] = None) -> None:
    """Update one board's history after a real sweep has fetched it.

    Call this from sweep.py (Task 10, not yet written) once per board per
    sweep, with the count of rows on that board that passed BOTH
    filters.classify() this run (any country).
    """
    swept_at = swept_at or datetime.now(timezone.utc)
    key = "{}|{}".format(platform, token)
    h = state.get(key) or BoardHistory(platform=platform, token=token)
    h.total_qualifying_ever += qualifying_count
    h.qualifying_last_30d = qualifying_count  # latest sweep's count (no longer cumulative)
    h.sweeps_run += 1
    h.last_swept_at = swept_at.isoformat(timespec="seconds")
    if qualifying_count > 0:
        h.last_qualifying_at = h.last_swept_at
    state[key] = h


def report(state: Dict[str, BoardHistory]) -> str:
    lines: List[str] = []
    by_tier: Dict[str, List[BoardHistory]] = {"hot": [], "warm": [], "cold": []}
    for h in state.values():
        by_tier[tier_for(h)].append(h)
    lines.append("{:<8} {:>6}   {:<28} {:>10} {:>12}".format(
        "tier", "boards", "example", "yield/swp", "qualifying"))
    lines.append("-" * 70)
    for tier in ("hot", "warm", "cold"):
        boards = by_tier[tier]
        example = boards[0].token if boards else "-"
        total_q = sum(b.total_qualifying_ever for b in boards)
        avg_yield = (
            sum(per_board_yield(b) or 0 for b in boards) / len(boards)
            if boards else 0.0
        )
        lines.append("{:<8} {:>6}   {:<28} {:>10.3f} {:>12}".format(
            tier, len(boards), example[:28], avg_yield, total_q))
    unmeasured = [h for h in state.values() if h.sweeps_run == 0]
    if unmeasured:
        lines.append("")
        lines.append("{} boards in registry.json have never been swept — "
                      "scored 'cold' by default, not measured.".format(
                          len(unmeasured)))
    return "\n".join(lines)


def load_registry(path: str = REGISTRY) -> List[Dict]:
    if not os.path.exists(path):
        return []
    return json.load(open(path))


if __name__ == "__main__":
    registry = load_registry()
    state = load_tier_state()
    # Seed history entries for any registry board that has none yet, so the
    # report is honest about "never swept" rather than silently omitting them.
    for row in registry:
        key = "{}|{}".format(row["platform"], row["token"])
        if key not in state:
            state[key] = BoardHistory(platform=row["platform"], token=row["token"])

    print("boards in registry.json: {}".format(len(registry)))
    print()
    print(report(state))
    print()
    print("NOTE: this engine has not run a sweep yet (sweep.py is Task 10, "
          "not written). Every board above is genuinely unmeasured — this is "
          "not a placeholder number, it is the honest current state.")
