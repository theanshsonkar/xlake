"""Company -> board token, by reading the company's own careers page.

This is the most reused code in the project. Every other layer depends on it:
adding boards, correcting wrong ones, and growing the registry from company
names alone.

Why it exists: guessing tokens is how you get silent failures. Two Workday
entries in the old registry were dead because the token was guessed. Worse,
`ashby:vercel` returned HTTP 200 with an empty list forever because Vercel had
moved to Greenhouse — a guessed token that *works* and returns nothing is
indistinguishable from a company that is not hiring. Reading the careers page
removes the guess.

Method:
  1. Try a handful of conventional careers paths on the company domain.
  2. Follow redirects; the final URL is often the board itself.
  3. Otherwise scan the returned HTML for any known ATS URL, including iframe
     and embed-script forms.
  4. Report what was found AND the evidence, so a wrong answer is debuggable.

Detects platforms we can read (the 8 JSON ones) and also platforms we cannot
yet read (Keka, Darwinbox, Zoho Recruit, Freshteam, bespoke pages). Knowing a
company is on Keka is useful even before we can parse Keka.

No AI in this file.
"""

from __future__ import annotations

import re
import urllib.parse
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from fetch import UA, _request, _throttle, _release  # reuse politeness + UA

import urllib.error
import urllib.request

CAREERS_PATHS = (
    "/careers",
    "/jobs",
    "/career",
    "/company/careers",
)

# Careers pages are not APIs; a slow one is usually a dead one. 9 paths at a
# 25s timeout meant a single unreachable company could burn 3+ minutes.
PAGE_TIMEOUT = 8

# Platforms we can enumerate today.
READABLE = {
    "greenhouse",
    "lever",
    "ashby",
    "smartrecruiters",
    "workable",
    "workday",
    "personio",
    "recruitee",
}

# Platforms we can detect but not yet enumerate. Worth recording: these are
# where Indian companies actually are, and the count is the whole question.
UNREADABLE = {"keka", "darwinbox", "zohorecruit", "freshteam", "bespoke"}

# Ordered: more specific patterns first. Order matters — the embed form
# `boards.greenhouse.io/embed/job_board?for=cloudsek` also matches the generic
# board pattern and yields the token "embed", so it must be tested first.
PATTERNS: Tuple[Tuple[str, str], ...] = (
    ("greenhouse", r"greenhouse\.io/embed/job_board(?:/js)?\?for=([a-zA-Z0-9_-]+)"),
    ("greenhouse", r"boards-api\.greenhouse\.io/v1/boards/([a-zA-Z0-9_-]+)"),
    ("greenhouse", r"(?:job-boards|boards)\.greenhouse\.io/([a-zA-Z0-9_-]+)"),
    ("lever", r"jobs\.(?:eu\.)?lever\.co/([a-zA-Z0-9_-]+)"),
    ("lever", r"api\.lever\.co/v0/postings/([a-zA-Z0-9_-]+)"),
    ("ashby", r"jobs\.ashbyhq\.com/([a-zA-Z0-9_.-]+?)(?=[/\"'?#\s]|$)"),
    ("ashby", r"api\.ashbyhq\.com/posting-api/job-board/([a-zA-Z0-9_.-]+)"),
    ("smartrecruiters", r"jobs\.smartrecruiters\.com/([a-zA-Z0-9_-]+)"),
    ("smartrecruiters", r"careers\.smartrecruiters\.com/([a-zA-Z0-9_-]+)"),
    ("workable", r"apply\.workable\.com/([a-zA-Z0-9_-]+)"),
    ("recruitee", r"([a-zA-Z0-9_-]+)\.recruitee\.com"),
    ("personio", r"([a-zA-Z0-9_-]+)\.jobs\.personio\.(?:de|com)"),
    # Unreadable-but-worth-knowing
    ("keka", r"([a-zA-Z0-9_-]+)\.keka(?:hire)?\.com"),
    ("darwinbox", r"([a-zA-Z0-9_-]+)\.darwinbox\.(?:in|com)"),
    ("zohorecruit", r"([a-zA-Z0-9_-]+)\.zohorecruit\.(?:com|in)"),
    ("freshteam", r"([a-zA-Z0-9_-]+)\.freshteam\.com"),
)

# Tokens that are really URL path words, not company slugs.
NOT_TOKENS = {
    "www", "api", "jobs", "careers", "career", "app", "help", "docs", "embed",
    "job_board", "job-boards", "boards", "posting-api", "static", "assets",
    "images", "cdn", "en", "search", "job", "openings", "v1", "v0", "share",
}

# Workday needs host|tenant|site, so it gets its own extractor.
WORKDAY_RE = re.compile(
    r"https?://([a-zA-Z0-9_.-]*\.myworkday(?:jobs|site)\.com)/(?:([a-z]{2}-[A-Z]{2})/)?([a-zA-Z0-9_-]+)"
)


@dataclass
class Resolution:
    company: str
    domain: str
    platform: Optional[str] = None
    token: Optional[str] = None
    readable: bool = False
    evidence: str = ""
    careers_url: str = ""
    tried: List[str] = field(default_factory=list)
    error: Optional[str] = None
    # Filled by resolve_and_verify()
    state: Optional[str] = None  # verified | empty | dead
    verify_status: Optional[int] = None
    verify_jobs: Optional[int] = None
    verify_error: Optional[str] = None

    def as_registry_entry(self) -> Optional[Dict[str, str]]:
        if not (self.platform and self.token and self.readable):
            return None
        return {
            "platform": self.platform,
            "token": self.token,
            "company": self.company,
            "source": "resolver",
            "evidence": self.evidence,
        }


def _fetch_page(url: str) -> Tuple[Optional[int], str, str, Optional[str]]:
    """GET with redirects, returning (status, final_url, html, error)."""
    lock = _throttle(url)
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": UA,
                # Careers pages are HTML; ask for it or some CDNs return JSON errors.
                "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=PAGE_TIMEOUT) as resp:
                # Read the whole page. A 400KB cap hid the Greenhouse link on
                # Vercel's careers page, which is a large Next.js bundle, and
                # made a resolvable company look bespoke.
                return (
                    resp.getcode(),
                    resp.geturl(),
                    resp.read(4_000_000).decode("utf-8", errors="replace"),
                    None,
                )
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read(4_000_000).decode("utf-8", errors="replace")
            except Exception:  # noqa: BLE001
                pass
            # A 403 still often contains the board link in the shell.
            return e.code, url, body, "http_{}".format(e.code)
        except Exception as e:  # noqa: BLE001
            return None, url, "", "{}: {}".format(type(e).__name__, str(e)[:120])
    finally:
        _release(url, lock)


def _scan(text: str, final_url: str) -> Tuple[Optional[str], Optional[str], str]:
    """Find an ATS reference in a page. Returns (platform, token, evidence)."""
    haystack = final_url + "\n" + text

    m = WORKDAY_RE.search(haystack)
    if m:
        host, _locale, site = m.group(1), m.group(2), m.group(3)
        tenant = host.split(".")[0]
        # wdN.myworkdaysite.com/<tenant>/<site> puts the tenant in the path.
        if tenant.startswith("wd") and tenant[2:].isdigit():
            parts = [p for p in urllib.parse.urlsplit(m.group(0)).path.split("/") if p]
            if len(parts) >= 2:
                tenant, site = parts[0], parts[1]
        return "workday", "{}|{}|{}".format(host, tenant, site), m.group(0)[:160]

    for platform, pat in PATTERNS:
        for m in re.finditer(pat, haystack):
            token = m.group(1)
            if token.lower() in NOT_TOKENS:
                continue
            return platform, token, m.group(0)[:160]
    return None, None, ""


def resolve(company: str, domain: str) -> Resolution:
    """Find the board for one company."""
    res = Resolution(company=company, domain=domain)
    domain = domain.replace("https://", "").replace("http://", "").strip("/")

    for path in CAREERS_PATHS:
        url = "https://{}{}".format(domain, path)
        status, final_url, html, err = _fetch_page(url)
        res.tried.append("{} -> {}".format(path, status or err))
        if not html:
            continue

        platform, token, evidence = _scan(html, final_url)
        if platform:
            res.platform = platform
            res.token = token
            res.readable = platform in READABLE
            res.evidence = evidence
            res.careers_url = final_url
            return res

        # Reached a real careers page but found no known ATS: bespoke or JS-only.
        if status and 200 <= status < 300 and len(html) > 2000:
            res.platform = "bespoke"
            res.token = None
            res.readable = False
            res.careers_url = final_url
            res.evidence = "careers page reachable, no known ATS reference"

    if not res.platform:
        res.error = "no_careers_page_found"
    return res


def resolve_and_verify(company: str, domain: str) -> Resolution:
    """Resolve, then prove the token works by actually calling the board.

    A resolution is a hypothesis. The Vercel bug happened because nobody ever
    checked whether the stored token returned anything. Verification collapses
    three outcomes that otherwise look alike:

      verified -> token answers, has postings
      empty    -> token answers, zero postings (real; company may be frozen)
      dead     -> token does not answer (404/422); the token is wrong
    """
    from fetch import list_board

    res = resolve(company, domain)
    if not (res.platform in READABLE and res.token):
        return res

    board = list_board(res.platform, res.token)
    res.verify_status = board.status
    res.verify_jobs = board.count
    res.verify_error = board.error
    if board.error:
        res.state = "dead"
    elif board.count == 0:
        res.state = "empty"
    else:
        res.state = "verified"
    return res


# --------------------------------------------------------------------------- #
# CLI: python3 resolve.py "Zepto" zepto.co.in
#      python3 resolve.py --file companies.txt      ("Name,domain" per line)
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    import sys

    pairs: List[Tuple[str, str]] = []
    if len(sys.argv) >= 3 and sys.argv[1] == "--file":
        for line in open(sys.argv[2]):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            name, _, dom = line.partition(",")
            pairs.append((name.strip(), dom.strip()))
    elif len(sys.argv) >= 3:
        pairs.append((sys.argv[1], sys.argv[2]))
    else:
        print('usage: python3 resolve.py "Company" company.com')
        print("       python3 resolve.py --file companies.txt")
        raise SystemExit(2)

    tally: Dict[str, int] = {}
    total_jobs = 0

    # Companies are different hosts, so resolving them concurrently is polite —
    # the per-host lock in fetch.py still serialises requests to any one site.
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda p: resolve_and_verify(*p), pairs))

    for (name, dom), r in zip(pairs, results):
        label = r.platform or "none"
        tally[label] = tally.get(label, 0) + 1
        total_jobs += r.verify_jobs or 0
        print(
            "{:<22} {:<24} {:<15} {:<32} {:<9} {}".format(
                name[:22],
                dom[:24],
                label,
                (r.token or "-")[:32],
                r.state or "",
                ("{} jobs".format(r.verify_jobs) if r.verify_jobs is not None else ""),
            )
        )

    if len(pairs) > 1:
        print("\n--- platform tally ---")
        readable_n = sum(v for k, v in tally.items() if k in READABLE)
        for k in sorted(tally, key=lambda x: -tally[x]):
            print("  {:<18} {}".format(k, tally[k]))
        print(
            "\n  on a platform we can read: {} / {}  ({:.0f}%)".format(
                readable_n, len(pairs), 100.0 * readable_n / len(pairs)
            )
        )
        print("  total postings reachable:  {}".format(total_jobs))
