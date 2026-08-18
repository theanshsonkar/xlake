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

from adapters.boards import UA, _request, _throttle, _release  # reuse politeness + UA

import urllib.error
import urllib.request

CAREERS_PATHS = (
    "/careers",
    "/jobs",
    "/career",
    "/company/careers",
    # Added after measuring against the known-company list on 2026-07-31. The
    # four paths above found a page for Jump Trading and IMC, but both REDIRECT
    # to the marketing homepage, which carries no board link — so both were
    # recorded as "bespoke, no ATS" while their real Greenhouse boards
    # (job-boards.greenhouse.io/jumptrading, job-boards.eu.greenhouse.io/imc)
    # were sitting one click away. These are the shapes that actually occur.
    "/careers/jobs",
    "/careers/open-positions",
    "/careers/students",
    "/join-us",
    "/about/careers",
    "/en/careers",
    "/in/careers",
    "/company/jobs",
    "/work-with-us",
)

# Anchor text / href fragments that lead from a careers marketing page to the
# actual listing. Used for ONE extra hop — see _follow_links. This is what a
# person does when a careers page is all photographs and values statements.
LINK_HINTS = re.compile(
    r"(open[\s-]?(?:role|position|job)|current[\s-]?(?:opening|vacanc)|"
    r"view[\s-]?(?:all[\s-]?)?(?:job|role|opening)|search[\s-]?job|"
    r"job[\s-]?(?:board|search|opening|listing)|all[\s-]?(?:job|role)|"
    r"apply|vacanc|opening|students|university|campus|graduate|intern)",
    re.I,
)

# How many candidate links to follow per company. Kept small: this multiplies
# requests, and the per-host delay means each one costs real time.
MAX_FOLLOW = 3

# Careers pages are not APIs; a slow one is usually a dead one. 9 paths at a
# 25s timeout meant a single unreachable company could burn 3+ minutes.
PAGE_TIMEOUT = 8

# Platforms we can enumerate today. Kept in step with fetch._ADAPTERS — a
# platform listed here but not implemented there produces a "verified" company
# that never yields a posting, which is the silent failure this module exists to
# prevent.
#
# Changes from the previous version, both measured on 2026-07-31:
#   + keka             the adapter works now; the real endpoint has two extra
#                      path segments (/careers/api/embedjobs/{portal}/active/{guid})
#   + eightfold        /api/pcsx/search, robots-allowed
#   + successfactors   sitemap.xml, one request for the whole board
#   - smartrecruiters  MOVED OUT. Its API is robots-disallowed to everyone except
#                      LinkedInBot, so it is not something we may read.
READABLE = {
    "greenhouse",
    "lever",
    "ashby",
    "workable",
    "workday",
    "personio",
    "recruitee",
    "keka",
    "eightfold",
    "successfactors",
}

# Detected, but we may not or cannot read the listing. Worth recording either
# way: knowing a company is on Darwinbox is what routes it to the page reader
# instead of leaving it as an unexplained blank.
#
# smartrecruiters is here for a legal/consent reason rather than a technical one
# — see fetch.SMARTRECRUITERS_NOTE. The public HTML board is readable, so it is a
# page-reader target.
UNREADABLE = {
    "smartrecruiters",
    "darwinbox",
    "zohorecruit",
    "freshteam",
    "bespoke",
}

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
    # Eightfold. The token needs a domain as well as a tenant, so _scan patches
    # it up afterwards — see EIGHTFOLD_RE.
    ("eightfold", r"([a-zA-Z0-9_-]+)\.eightfold\.ai"),
    # Unreadable-but-worth-knowing
    ("keka", r"([a-zA-Z0-9_-]+)\.keka(?:hire)?\.com"),
    ("darwinbox", r"([a-zA-Z0-9_-]+)\.darwinbox\.(?:in|com)"),
    ("zohorecruit", r"([a-zA-Z0-9_-]+)\.zohorecruit\.(?:com|in)"),
    ("freshteam", r"([a-zA-Z0-9_-]+)\.freshteam\.com"),
)

# Eightfold's board token is "tenant|domain"; the tenant is in the hostname but
# the domain is a separate query parameter the site passes to its own API.
EIGHTFOLD_RE = re.compile(r"([a-zA-Z0-9_-]+)\.eightfold\.ai")

# SAP SuccessFactors career sites sit on the company's OWN hostname
# (careers.wipro.com, jobs.mahindracareers.com), so there is no tenant to
# extract from a vendor domain. What gives it away is the asset CDN every CSB
# site loads from, and the platform paths it serves.
#
# The token is therefore the careers HOST itself, taken from the final URL after
# redirects, because that is what the sitemap adapter needs.
SUCCESSFACTORS_HINT = re.compile(
    r"rmkcdn\.successfactors\.com|"
    r"\.successfactors\.com/[a-z0-9]+/|"
    r"/platform/js/search/search\.js|"
    r"careersite[A-Za-z]*\.js|"
    r"data-careersite-propertyid",
    re.I,
)

# Tokens that are really URL path words, not company slugs.
NOT_TOKENS = {
    # "j" is here because apply.workable.com/j/<shortcode> is a JOB url, not a
    # board url, and the board regex happily returned the token "j" for
    # Innovaccer — a resolution that verified as http_404 and would otherwise
    # have been recorded as a dead company.
    "j", "o", "view", "widget", "accounts",
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
    # True when the board was only found by following a link off the careers
    # page, rather than on the careers page itself. Worth recording: it says the
    # company's /careers path is marketing copy, which matters for the reader.
    found_via_hop: bool = False
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


def _scan(text: str, final_url: str,
          eightfold_domain: str = "") -> Tuple[Optional[str], Optional[str], str]:
    """Find an ATS reference in a page. Returns (platform, token, evidence).

    `eightfold_domain` is the company's own domain, needed because Eightfold's
    board token is "tenant|domain" and only the tenant is in the URL.
    """
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
            if platform == "eightfold":
                # The adapter needs "tenant|domain". The domain is the company's
                # own, which is the host we started from, so it is passed in by
                # the caller rather than guessed from the tenant name — Nvidia's
                # tenant is "nvidia" and its domain is "nvidia.com", but that
                # coincidence does not hold in general.
                token = "{}|{}".format(token, eightfold_domain or (token + ".com"))
            return platform, token, m.group(0)[:160]

    # SuccessFactors last: its signal is an asset host rather than a board URL,
    # so a page that ALSO carries a real board link should resolve to that board
    # instead. Checked here so it never shadows a more specific match.
    if SUCCESSFACTORS_HINT.search(haystack):
        host = urllib.parse.urlsplit(final_url).netloc.lower()
        if host:
            m = SUCCESSFACTORS_HINT.search(haystack)
            return "successfactors", host, (m.group(0) if m else "")[:160]

    return None, None, ""


def _candidate_links(html: str, base_url: str) -> List[str]:
    """Same-site links that look like they lead to the real job listing.

    Ordered by how promising the anchor text is, deduped, and restricted to the
    company's own host so this never wanders onto an aggregator.
    """
    base = urllib.parse.urlsplit(base_url)
    scored: List[Tuple[int, str]] = []
    seen = set()
    for m in re.finditer(r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.{0,120}?)</a>',
                         html, re.I | re.S):
        href, text = m.group(1), re.sub(r"<[^>]+>", " ", m.group(2))
        if href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        full = urllib.parse.urljoin(base_url, href)
        parts = urllib.parse.urlsplit(full)
        if parts.scheme not in ("http", "https"):
            continue
        # Same registrable-ish host only. An off-site link here is either an ATS
        # (already caught by _scan) or an aggregator, which the rules forbid.
        if parts.netloc.lower().lstrip("www.") != base.netloc.lower().lstrip("www."):
            continue
        norm = full.split("#")[0].rstrip("/")
        if norm in seen or norm.rstrip("/") == base_url.split("#")[0].rstrip("/"):
            continue
        seen.add(norm)
        score = 0
        if LINK_HINTS.search(text):
            score += 2
        if LINK_HINTS.search(parts.path):
            score += 1
        if score:
            scored.append((score, norm))
    scored.sort(key=lambda x: -x[0])
    return [u for _s, u in scored[:MAX_FOLLOW]]


def _is_real_careers_page(status: Optional[int], final_url: str, html: str) -> bool:
    """Did we actually land on a careers page, or get bounced to the homepage?

    `/careers` returning 200 after redirecting to `https://www.imc.com/in/` is
    not a careers page. Counting it as one is what produced a confident
    "bespoke, no ATS reference" for two companies with live Greenhouse boards.
    """
    if not (status and 200 <= status < 300 and len(html) > 2000):
        return False
    path = urllib.parse.urlsplit(final_url).path.strip("/")
    return bool(path)


def resolve(company: str, domain: str) -> Resolution:
    """Find the board for one company."""
    res = Resolution(company=company, domain=domain)
    domain = domain.replace("https://", "").replace("http://", "").strip("/")

    # Pages that were reachable but held no board link, kept so the second hop
    # has somewhere to start. A redirect to the homepage still belongs here: it
    # is a bad careers page but a fine place to look for a link to the real one.
    landed: List[Tuple[str, str]] = []  # (final_url, html)
    saw_real_careers_page = False

    for path in CAREERS_PATHS:
        url = "https://{}{}".format(domain, path)
        status, final_url, html, err = _fetch_page(url)
        res.tried.append("{} -> {}".format(path, status or err))
        if not html:
            continue

        platform, token, evidence = _scan(html, final_url, domain)
        if platform:
            res.platform = platform
            res.token = token
            res.readable = platform in READABLE
            res.evidence = evidence
            res.careers_url = final_url
            return res

        if status and 200 <= status < 300 and len(html) > 2000:
            if _is_real_careers_page(status, final_url, html):
                saw_real_careers_page = True
                landed.append((final_url, html))
                # Two REAL careers pages is plenty to hunt through. Counting
                # homepage bounces here stopped Jump Trading after /careers and
                # /jobs, so the deeper paths that might have worked were never
                # tried.
                if sum(1 for _ in landed) >= 2:
                    break
            elif len(landed) < 4:
                # A homepage bounce is a poor careers page but a fine place to
                # look for a link to the real one.
                landed.append((final_url, html))

    # Second hop: follow the most promising in-site links from the pages that did
    # load. This is the step that turns "bespoke" into a real board for companies
    # whose /careers page is marketing copy with a "View open roles" button.
    for final_url, html in landed:
        for link in _candidate_links(html, final_url):
            status, f2, h2, err = _fetch_page(link)
            res.tried.append("hop {} -> {}".format(
                urllib.parse.urlsplit(link).path[:40], status or err))
            if not h2:
                continue
            platform, token, evidence = _scan(h2, f2, domain)
            if platform:
                res.platform = platform
                res.token = token
                res.readable = platform in READABLE
                res.evidence = evidence
                res.careers_url = f2
                res.found_via_hop = True
                return res

    if saw_real_careers_page:
        # Reached a real careers page and still found no known ATS after a hop:
        # genuinely bespoke or JS-only. A page-reader target.
        res.platform = "bespoke"
        res.token = None
        res.readable = False
        res.careers_url = landed[0][0]
        res.evidence = "careers page reachable, no known ATS reference after {} hops".format(
            MAX_FOLLOW)
        return res

    if landed:
        # Every careers path bounced to the homepage and no link off it led to a
        # board. Named separately from "no careers page" because the site is up
        # and something is there — it just is not reachable by convention.
        res.platform = None
        res.error = "careers_path_redirects_to_homepage"
        res.careers_url = landed[0][0]
        return res

    # Nothing loaded at all. Distinguish blocked from absent: a 403 on every path
    # is bot protection, which is a different problem from a company having no
    # careers page, and the two need different handling.
    statuses = [t.rsplit(" -> ", 1)[-1] for t in res.tried]
    if statuses and all("nodename nor servname" in s or "Name or service not known" in s
                        or "getaddrinfo" in s for s in statuses):
        # Every path failed DNS: the domain itself does not exist. That is a
        # defect in data/operations/companies.txt, not a fact about the employer, and
        # conflating them would quietly under-report coverage.
        res.error = "domain_does_not_resolve"
    elif any(s in ("403", "406", "429") for s in statuses):
        res.error = "bot_blocked"
    else:
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
    from adapters.boards import list_board

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
