"""robots.txt, actually honoured — including Crawl-delay.

The old engine's README claimed robots.txt was respected. It was not: nothing
ever fetched a robots.txt file, and Lever asks for `Crawl-delay: 1` while the CI
sweep ran at `LAKE_HOST_DELAY=0.3`. This module exists so that claim becomes
true, and so the per-host delay is the site's number rather than ours.

Why not `urllib.robotparser`: it gets the one case this project depends on
WRONG. Python's RobotFileParser returns the FIRST matching rule in file order.
Keka's robots.txt is:

    User-agent: *
    Disallow: /
    Allow: /careers
    Allow: /careers/

`Disallow: /` appears first and matches everything, so RobotFileParser answers
False for `/careers/` and the single best India job source in this project would
be silently skipped as forbidden. RFC 9309 §2.2.2 says the MOST SPECIFIC
(longest) matching path wins, and on a tie Allow wins. That is what this
implements, so Keka reads as allowed and `Disallow: /` still blocks the rest of
the site.

Fail-closed vs fail-open, decided per status code exactly as RFC 9309 §2.3.1
requires rather than by our own instinct:

    200 + rules     obey them                              (§2.3.1.1)
    3xx             follow up to 5 redirects               (§2.3.1.2)
    4xx             "unavailable" -> the crawler MAY access any resource.
                    This INCLUDES 401 and 403.             (§2.3.1.3)
    5xx / timeout   "unreachable" -> MUST assume complete disallow. (§2.3.1.4)

The 4xx rule is worth spelling out because the first version of this file got it
wrong in the direction that feels safer. `api.ashbyhq.com/robots.txt` answers
**401**, not 404 — it is an API gateway rejecting an unknown path, not a site
refusing to publish rules. Treating 401 as "stay out" is stricter than the
standard and would have silently disabled a working adapter, which is precisely
the class of quiet failure this project keeps having to dig out. The status is
recorded either way so the decision is visible in a run report instead of
inferred.

No AI in this file.
"""

from __future__ import annotations

import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Dict, List, Optional, Tuple

# Kept in one place so fetch.py, resolve.py and the page reader all present the
# same identity. A contact address is what makes good faith checkable by a
# sysadmin reading their logs.
UA = (
    "xlake/1.0 (+https://github.com/theanshsonkar/xlake; "
    "contact: anshsonkar@users.noreply.github.com)"
)

# The token we match User-agent lines against, lowercased.
UA_TOKEN = "xlake"

ROBOTS_TIMEOUT = 10

# Used when a site states no Crawl-delay. Not zero: the project's own rule is one
# request at a time per host with a delay, whether or not we are asked.
DEFAULT_DELAY = float(os.environ.get("LAKE_HOST_DELAY", "1.0"))

# A site asking for a very long delay effectively asks us not to sweep it in
# bulk. Cap what we will wait inline, and report the site as too-slow instead of
# stalling a whole sweep for an hour on one host.
MAX_HONOURED_DELAY = float(os.environ.get("LAKE_MAX_CRAWL_DELAY", "10.0"))

# How long a fetched robots.txt is trusted before refetching.
TTL_SECONDS = 6 * 3600


class Rules:
    """Parsed robots.txt for one origin."""

    __slots__ = ("allow", "disallow", "delay", "fetched_at", "status", "blanket_deny")

    def __init__(self) -> None:
        self.allow: List[str] = []
        self.disallow: List[str] = []
        self.delay: Optional[float] = None
        self.fetched_at: float = 0.0
        self.status: Optional[int] = None
        # Set when robots.txt could not be read in a way that means "stay out"
        # (401/403/5xx). Distinct from an empty ruleset, which means "no rules".
        self.blanket_deny: bool = False

    # -- RFC 9309 path matching ------------------------------------------- #
    @staticmethod
    def _match_len(pattern: str, path: str) -> int:
        """Length of `pattern` if it matches `path`, else -1.

        Supports the two wildcards every major crawler implements: `*` for any
        run of characters and `$` anchoring the end. Specificity is measured by
        the pattern's own length, per the RFC, not by how much of the path was
        consumed.
        """
        if pattern == "":
            return -1
        if "*" not in pattern and "$" not in pattern:
            return len(pattern) if path.startswith(pattern) else -1

        anchored = pattern.endswith("$")
        body = pattern[:-1] if anchored else pattern
        regex = "".join(
            ".*" if ch == "*" else re.escape(ch) for ch in body
        )
        regex = "^" + regex + ("$" if anchored else "")
        try:
            return len(pattern) if re.match(regex, path) else -1
        except re.error:
            return -1

    def allows(self, path: str) -> bool:
        if self.blanket_deny:
            return False
        if not path.startswith("/"):
            path = "/" + path
        best_allow = max([self._match_len(p, path) for p in self.allow] or [-1])
        best_deny = max([self._match_len(p, path) for p in self.disallow] or [-1])
        if best_deny < 0:
            return True
        # Longest match wins; Allow wins ties. This is the line that makes
        # Keka's `Allow: /careers` beat its `Disallow: /`.
        return best_allow >= best_deny


def _parse(text: str) -> Rules:
    """Parse robots.txt, taking the most specific User-agent group that applies.

    A group naming us explicitly beats the `*` group and is used alone, which is
    what the RFC requires — the groups are not merged.
    """
    groups: Dict[str, Rules] = {}
    current: List[str] = []
    # A blank line ends a group's user-agent list, so consecutive User-agent
    # lines share one rule block but `UA: a / Disallow / UA: b` do not.
    expect_new_group = True

    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            expect_new_group = True
            continue
        field, sep, value = line.partition(":")
        if not sep:
            continue
        field = field.strip().lower()
        value = value.strip()

        if field == "user-agent":
            if expect_new_group:
                current = []
                expect_new_group = False
            agent = value.lower()
            current.append(agent)
            groups.setdefault(agent, Rules())
            continue

        if not current:
            continue  # a directive before any User-agent line: ignore
        expect_new_group = False

        for agent in current:
            r = groups[agent]
            if field == "disallow":
                # `Disallow:` with an empty value means "allow everything".
                if value:
                    r.disallow.append(urllib.parse.unquote(value))
            elif field == "allow":
                if value:
                    r.allow.append(urllib.parse.unquote(value))
            elif field == "crawl-delay":
                try:
                    r.delay = float(value)
                except ValueError:
                    pass

    # §2.2.1: a group naming our product token is used alone; the `*` group is
    # consulted only when no group matches us. Groups repeating the same
    # user-agent line were already merged above by `setdefault`, which is the
    # merge behaviour §2.2.1 mandates. Matching is case-insensitive and exact on
    # the product token — the RFC's rule is that the robots.txt token is a
    # substring of our User-Agent *header*, not that our name is a substring of
    # theirs, so a group for "notxlakebot" must not capture us.
    for key in (UA_TOKEN, "*"):
        r = groups.get(key)
        if r is not None:
            return r
    return Rules()


# --------------------------------------------------------------------------- #
# Cache + public API
# --------------------------------------------------------------------------- #
_cache: Dict[str, Rules] = {}
_cache_lock = threading.Lock()
# Set when a host answers 429. Nothing may be requested from it until the clock
# runs out — see fetch.py. Kept here because robots and rate limits are the same
# kind of signal: the site telling us to stop.
_penalty_until: Dict[str, float] = {}
_penalty_lock = threading.Lock()


def _origin(url: str) -> str:
    parts = urllib.parse.urlsplit(url)
    return "{}://{}".format(parts.scheme or "https", parts.netloc.lower())


def _fetch_rules(origin: str) -> Rules:
    r = Rules()
    req = urllib.request.Request(
        origin + "/robots.txt",
        headers={"User-Agent": UA, "Accept": "text/plain,*/*;q=0.5"},
    )
    try:
        with urllib.request.urlopen(req, timeout=ROBOTS_TIMEOUT) as resp:
            body = resp.read(1_000_000).decode("utf-8", errors="replace")
            r = _parse(body)
            r.status = resp.getcode()
    except urllib.error.HTTPError as e:
        r.status = e.code
        # RFC 9309 §2.3.1.3: any 4xx means robots.txt is "unavailable" and the
        # crawler MAY access any resource. 401 and 403 are included — see the
        # module docstring for why that is not a loophole.
        if e.code >= 500:
            r.blanket_deny = True  # §2.3.1.4 "unreachable" -> complete disallow
    except Exception:  # noqa: BLE001  (timeout, DNS, TLS)
        r.status = None
        r.blanket_deny = True  # network failure is also "unreachable"
    r.fetched_at = time.monotonic()
    return r


def rules_for(url: str) -> Rules:
    origin = _origin(url)
    with _cache_lock:
        cached = _cache.get(origin)
        if cached is not None and (time.monotonic() - cached.fetched_at) < TTL_SECONDS:
            return cached
    fresh = _fetch_rules(origin)
    with _cache_lock:
        _cache[origin] = fresh
    return fresh


def allowed(url: str) -> Tuple[bool, str]:
    """(may_we_fetch, reason). The reason is for the run report, not decoration.

    A skipped board must be recorded with WHY, or robots-blocked and broken look
    identical in the stats — the same conflation of "did not look" with "looked
    and found nothing" that this project keeps having to fix.
    """
    if os.environ.get("LAKE_IGNORE_ROBOTS") == "1":
        # Deliberately loud and deliberately not the default. Exists only so a
        # single URL can be checked by hand while debugging.
        return True, "robots_override"
    parts = urllib.parse.urlsplit(url)
    path = parts.path or "/"
    if parts.query:
        path += "?" + parts.query
    r = rules_for(url)
    if r.blanket_deny:
        # §2.3.1.4: unreachable, not forbidden. Named accurately so a run report
        # distinguishes "the site said no" from "the site was down".
        return False, "robots_unreachable_{}".format(r.status or "network")
    if not r.allows(path):
        return False, "robots_disallow"
    return True, "ok"


def crawl_delay(url: str) -> float:
    """Seconds to wait between requests to this host. The site's number wins."""
    r = rules_for(url)
    if r.delay is None:
        return DEFAULT_DELAY
    return max(DEFAULT_DELAY, min(r.delay, MAX_HONOURED_DELAY))


# --------------------------------------------------------------------------- #
# 429 back-off. A rate limit is consent being withdrawn, not an obstacle.
# --------------------------------------------------------------------------- #
BACKOFF_BASE = float(os.environ.get("LAKE_429_BACKOFF", "900"))  # 15 minutes


def note_rate_limited(url: str, retry_after: Optional[str] = None) -> float:
    """Record a 429 and return the epoch time the host may be touched again.

    Deliberately long, and deliberately not exponential-retry-with-jitter. 522
    of 1,755 Workable boards returned 429 on one sweep; retrying through that
    would be hammering a service that has explicitly said stop. The board is
    recorded as rate-limited and left for the next run.
    """
    wait = BACKOFF_BASE
    if retry_after:
        try:
            wait = max(wait, float(retry_after.strip()))
        except ValueError:
            pass  # HTTP-date form; the default is already longer than typical
    host = urllib.parse.urlsplit(url).netloc.lower()
    until = time.time() + wait
    with _penalty_lock:
        _penalty_until[host] = max(_penalty_until.get(host, 0.0), until)
    return until


def rate_limited_until(url: str) -> float:
    host = urllib.parse.urlsplit(url).netloc.lower()
    with _penalty_lock:
        return _penalty_until.get(host, 0.0)


def is_rate_limited(url: str) -> bool:
    return time.time() < rate_limited_until(url)


def penalty_report() -> Dict[str, float]:
    """Hosts currently in back-off, so a run can report them honestly."""
    now = time.time()
    with _penalty_lock:
        return {h: round(t - now, 1) for h, t in _penalty_until.items() if t > now}


def reset_for_tests() -> None:
    with _cache_lock:
        _cache.clear()
    with _penalty_lock:
        _penalty_until.clear()


# --------------------------------------------------------------------------- #
# CLI: python3 robots.py https://tenant.keka.com/careers/
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("usage: python3 robots.py <url> [url ...]")
        raise SystemExit(2)
    for u in sys.argv[1:]:
        ok, why = allowed(u)
        r = rules_for(u)
        print("{:<60} {:<8} {:<24} delay={}s".format(
            u[:60], "ALLOW" if ok else "DENY", why,
            crawl_delay(u)))
        print("     robots status={} allow={} disallow={} crawl-delay={}".format(
            r.status, r.allow[:4], r.disallow[:4], r.delay))
