"""Smart recheck schedule for programme seeds (pure, no I/O).

A daily run used to re-fetch every seed. Now each seed is fetched only when it
is "due", judged from its existing lake row:

* no row, or no readable ``last_checked_at``      -> due now ("new")
* open/unverified, deadline within 14 days or none -> check every day
* open/unverified, deadline more than 14 days away -> check every 7 days
* upcoming (next cycle)                            -> check every 7 days
* closed                                           -> check every 30 days

A seed is due once its age reaches the interval minus 2 hours, so a daily cron
that drifts a little earlier still counts. Set XLAKE_RECHECK_ALL=1 to fetch all.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Dict, Optional, Tuple

from core import lifecycle

NEAR_DEADLINE_DAYS = 14
INTERVAL_NEAR = timedelta(days=1)
INTERVAL_FAR = timedelta(days=7)
INTERVAL_UPCOMING = timedelta(days=7)
INTERVAL_CLOSED = timedelta(days=30)
TOLERANCE = timedelta(hours=2)


def _parse_ts(value) -> Optional[datetime]:
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def programme_due(row: Optional[Dict], now: datetime) -> Tuple[bool, str]:
    """Return (due, reason). Reasons: new, open_near, open_far, upcoming, closed."""
    last = _parse_ts(row.get("last_checked_at")) if row else None
    if last is None:
        return True, "new"
    state = row.get("lifecycle") or lifecycle.infer(row)
    if state == lifecycle.CLOSED:
        reason, interval = "closed", INTERVAL_CLOSED
    elif state == lifecycle.UPCOMING:
        reason, interval = "upcoming", INTERVAL_UPCOMING
    else:
        deadline = lifecycle._deadline(row)
        if deadline is None or (deadline - now.date()).days <= NEAR_DEADLINE_DAYS:
            reason, interval = "open_near", INTERVAL_NEAR
        else:
            reason, interval = "open_far", INTERVAL_FAR
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now - last >= interval - TOLERANCE, reason
