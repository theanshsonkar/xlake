"""Raw response cache. Every byte we fetch is written to disk on first sight.

The measured reason this exists: Keka was swept four times in one day for four
different analyses — roughly 2,500 requests that had already been made and whose
answers had been thrown away. The bytes were free the first time and rude the
second.

The semantics matter, and they are NOT a read-through HTTP cache:

    WRITING is always on.  Every response is recorded.
    READING is opt-in.     A sweep must fetch live, or the liveness diff is
                           comparing a snapshot against itself and every board
                           looks unchanged forever.

So the cache is a recording, not a shortcut. Analysis, backfills, filter tuning
and tests read from it; the 12-hourly sweep does not.

    python3 sweep.py                 live fetch, records everything
    LAKE_MAX_AGE=86400 python3 ...   reuse anything under a day old
    LAKE_OFFLINE=1 python3 ...       never touch the network; cache or nothing

`raw/` is gitignored. It holds full job descriptions, and the project's rules say
raw snapshots stay private and are never republished.

No AI in this file.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import urllib.parse
from typing import Dict, Optional, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
RAW_DIR = os.environ.get("LAKE_RAW_DIR") or os.path.join(HERE, "raw")

# Read anything younger than this many seconds instead of fetching. 0 = always
# fetch (the default, because liveness depends on it).
MAX_AGE = float(os.environ.get("LAKE_MAX_AGE", "0"))

# Refuse to make any network request. Turns a sweep into a replay of what is
# already on disk. Used by tests and by any re-analysis of a past run.
OFFLINE = os.environ.get("LAKE_OFFLINE") == "1"

# Set to 0 to stop recording. There is no good reason to during a sweep; it
# exists so a one-off debugging run does not litter the directory.
RECORD = os.environ.get("LAKE_RECORD", "1") != "0"

_stats: Dict[str, int] = {"hit": 0, "miss": 0, "write": 0, "bytes": 0}
_stats_lock = threading.Lock()


def _bump(key: str, n: int = 1) -> None:
    with _stats_lock:
        _stats[key] = _stats.get(key, 0) + n


def stats() -> Dict[str, int]:
    with _stats_lock:
        return dict(_stats)


def reset_stats() -> None:
    with _stats_lock:
        for k in list(_stats):
            _stats[k] = 0


# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #
def key_for(url: str, body: Optional[bytes] = None) -> str:
    """Identity of a request. The POST body is part of it.

    Workday pages by POST body, so `{"offset": 0}` and `{"offset": 20}` hit the
    same URL and are different requests. Keying on URL alone would collapse a
    2,000-posting board into whichever page was fetched last — a quieter version
    of the truncation bug that made Nvidia look like a 200-job company.
    """
    h = hashlib.sha256()
    h.update(url.encode("utf-8"))
    if body:
        h.update(b"\x00")
        h.update(body)
    return h.hexdigest()


def _path_for(url: str, body: Optional[bytes] = None) -> str:
    host = urllib.parse.urlsplit(url).netloc.lower() or "nohost"
    # Sharded by host then by the first byte of the digest. A flat directory with
    # 45,000 files in it is slow to list and unpleasant to inspect by hand.
    digest = key_for(url, body)
    return os.path.join(RAW_DIR, host, digest[:2], digest + ".json")


# --------------------------------------------------------------------------- #
# Read / write
# --------------------------------------------------------------------------- #
def get(url: str, body: Optional[bytes] = None,
        max_age: Optional[float] = None) -> Optional[Tuple[int, str, float]]:
    """Return (status, text, age_seconds) if a fresh-enough copy exists.

    Returns None when reading is off (max_age 0), nothing is stored, or the
    stored copy is too old. In OFFLINE mode any age is acceptable — the point of
    offline is to replay, and refusing a stale record would just mean no data.
    """
    age_limit = MAX_AGE if max_age is None else max_age
    if age_limit <= 0 and not OFFLINE:
        return None
    p = _path_for(url, body)
    if not os.path.exists(p):
        _bump("miss")
        return None
    try:
        with open(p, "r") as fh:
            rec = json.load(fh)
    except Exception:  # noqa: BLE001  corrupt record: treat as absent
        _bump("miss")
        return None
    age = time.time() - float(rec.get("fetched_at") or 0)
    if not OFFLINE and age > age_limit:
        _bump("miss")
        return None
    _bump("hit")
    return int(rec.get("status") or 0), rec.get("text") or "", age


def put(url: str, status: Optional[int], text: str,
        body: Optional[bytes] = None) -> None:
    """Record a response. Never raises — a cache failure must not fail a sweep."""
    if not RECORD or status is None:
        return
    p = _path_for(url, body)
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        rec = {
            "url": url,
            "status": status,
            "fetched_at": time.time(),
            "fetched_at_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "request_body": body.decode("utf-8", "replace") if body else None,
            "content_hash": hashlib.sha256(text.encode("utf-8", "replace")).hexdigest(),
            "text": text,
        }
        tmp = p + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(rec, fh)
        os.replace(tmp, p)  # atomic: never a half-written record
        _bump("write")
        _bump("bytes", len(text))
    except Exception:  # noqa: BLE001
        pass


def content_hash(text: str) -> str:
    """The hash the page reader gates its AI calls on."""
    return hashlib.sha256((text or "").encode("utf-8", "replace")).hexdigest()


def previous_hash(url: str, body: Optional[bytes] = None) -> Optional[str]:
    """Hash of the last recorded copy, ignoring age.

    This is what makes mechanism 2 cheap: fetch the careers page daily for free,
    compare against this, and only pay a model when it differs.
    """
    p = _path_for(url, body)
    if not os.path.exists(p):
        return None
    try:
        with open(p, "r") as fh:
            return json.load(fh).get("content_hash")
    except Exception:  # noqa: BLE001
        return None


def disk_usage() -> Tuple[int, int]:
    """(files, bytes) currently recorded, for the run report."""
    files = total = 0
    for root, _dirs, names in os.walk(RAW_DIR):
        for n in names:
            if not n.endswith(".json"):
                continue
            files += 1
            try:
                total += os.path.getsize(os.path.join(root, n))
            except OSError:
                pass
    return files, total


if __name__ == "__main__":
    f, b = disk_usage()
    print("raw dir : {}".format(RAW_DIR))
    print("records : {}".format(f))
    print("size    : {:.1f} MB".format(b / 1_048_576))
    print("mode    : max_age={}s offline={} record={}".format(MAX_AGE, OFFLINE, RECORD))
