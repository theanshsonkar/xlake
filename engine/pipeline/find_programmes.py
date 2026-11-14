"""Find new official programme starting points on hosts we already trust.

Generic, not per-site: for each known official host (from served rows of a
category shard) read robots.txt, the sitemap(s) and a bounded Common Crawl URL
listing, keep URLs whose path looks like a programme page, and append them as
seeds to ``generated_seeds/finder_<category>.json``. The normal category run
then fetches each page and decides status/deadline/link quality. Nothing here
parses page content. Seeds are append-only so a partial finder run can never
cause rows to be retired.

Usage:
  python3 -m pipeline.find_programmes --shards DIR [--categories fellowships,research]
      [--max-hosts 200] [--per-host 10] [--max-new 100] [--max-requests 2000] [--dry-run]
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from typing import Callable, Dict, Iterable, List, Optional, Set, Tuple

ENGINE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ENGINE_ROOT not in sys.path:
    sys.path.insert(0, ENGINE_ROOT)

from categories.hub_seeds import _merge_seed_filter_reason, _clean_seed_name  # noqa: E402
from categories.stem import is_vacancy_text  # noqa: E402
from core import discovery, robots  # noqa: E402
from core.linkcheck import _is_aggregator, _is_landing  # noqa: E402
from pipeline import enumerate_boards  # noqa: E402
from pipeline.publish_supabase import is_serving, quality_reason  # noqa: E402

SEEDS_DIR = os.path.join(ENGINE_ROOT, "data", "operations", "generated_seeds")
# category (seed file stem) -> shard file stem
CATEGORIES = {
    "fellowships": "fellowships", "scholarships": "scholarships", "grants": "grants",
    "research": "research", "startup_founder": "startup", "community": "community",
    "open_source": "open_source",
}
GENERIC_HOSTS = (
    "github.com", "google.com", "medium.com", "linkedin.com", "youtube.com", "facebook.com",
    "twitter.com", "x.com", "instagram.com", "wikipedia.org", "reddit.com", "substack.com",
    "notion.so", "notion.site", "docs.google.com", "forms.gle", "bit.ly", "apple.com",
    "microsoft.com", "amazon.com", "t.me", "discord.com", "discord.gg", "gitlab.com",
)
# Keyword -> category, matched on lower-cased path text. Hackathons are skipped.
KEYWORDS: List[Tuple[str, "re.Pattern"]] = [
    ("scholarships", re.compile(r"scholarship|bursar|studentship")),
    ("fellowships", re.compile(r"fellowship")),
    ("open_source", re.compile(r"open-?source-?(?:program|fellow|mentor)|summer-of-code|gsoc")),
    ("research", re.compile(r"research-(?:program|experience|intern)|summer-research|(?:^|[/_-])reu(?:$|[/_-])|internship-program")),
    ("startup_founder", re.compile(r"accelerator|incubator|startup-program|founders?-program")),
    ("grants", re.compile(r"(?:^|[/_-])grants?(?:$|[/_-])|funding|(?:^|[/_-])awards?(?:$|[/_-])")),
    ("community", re.compile(r"ambassador|mentorship|community-program")),
]
HACKATHON = re.compile(r"hackathon")
EXCLUDED_SEGMENTS = frozenset({
    "news", "newsroom", "blog", "blogs", "event", "events", "people", "person", "profile", "profiles",
    "staff", "faculty", "team", "login", "signin", "sign-in", "search", "tag", "tags", "category",
    "categories", "feed", "rss", "press", "story", "stories", "article", "articles", "archive",
    "archives", "alumni", "directory", "calendar", "wp-content", "wp-json", "author", "podcast",
    "videos", "video", "drafts", "draft", "resources", "insights", "updates", "media", "publications",
    "newsletter", "newsletters", "stories", "testimonials", "jobs", "careers", "past", "winners", "recipients", "announcements",
    "product-page", "shop", "store", "merch", "post", "posts", "legal", "terms", "privacy", "dashboards", "gala", "venue",
    "registration", "faculty-awards", "roll-of-honour", "rankings", "leads", "experiences", "admin", "template", "templates",
    "handbook", "after-your-award", "reviewer", "reviewers", "collection", "collections", "board", "gifted-blog",
})
NOISE_SUBSTR = re.compile(r"product-page|faculty-awards|roll-of-honou?r|meet-the|after-your-award|gifted-blog|/fellows/")
LANGS = frozenset("ar bn cs da de el es fa fi fr he hi hu id it ja ko ms nl no pl pt ro ru sv sw th tr uk vi zh zh-cn zh-tw "
                  "pt-br es-mx fr-ca en-gb en-us de-de fr-fr".split())
EXTRA_AGGREGATORS = ("bigfuture.collegeboard.org",)
CATEGORY_TITLE = re.compile(r"fellowship|scholarship|bursar|grant|fund|award|prize|research program|summer research|\breu\b|"
                            r"internship|accelerator|incubator|startup program|mentorship|ambassador|gsoc|summer of code", re.I)
APPLICANT_CUE = re.compile(r"apply|application|eligib|deadline|nominat", re.I)
PAST_TITLE = re.compile(r"winners|recipients|announced|congratulations|meet our|story", re.I)
EXCLUDED_EXT = re.compile(r"\.(?:pdf|docx?|xlsx?|pptx?|jpe?g|png|gif|svg|webp|zip|mp4|mp3|xml|json|rss|atom|ics)$", re.I)
DATE_PATH = re.compile(r"/(?:19|20)\d{2}/\d{1,2}(?:/|$)|/(?:19|20)\d{2}-\d{2}-\d{2}")
LAST_SEGMENT_NOISE = re.compile(r"^(?:faqs?|fellows|alumni|contact|get-in-touch|about|eligibility|overview|apply)$|blog|reflection|focus|-old$|winners?|recipients?|announce|awarded|congratulat|results?|^page-?\d+$|^\d+$", re.I)
GENERIC_LAST = frozenset({"apply", "overview", "about", "eligibility", "faq", "faqs", "index", "how-to-apply",
                          "application", "applications", "details", "info", "program", "programs"})
MAX_SITEMAP_FILES, MAX_HOST_URLS = 5, 20000
MAX_SITEMAP_BYTES = 30_000_000
HOST_DELAY, GLOBAL_DELAY, CC_DELAY = 2.0, 0.5, 1.0


def host_of(url: str) -> str:
    try:
        host = (urllib.parse.urlsplit(url.strip()).hostname or "").lower().rstrip(".")
    except ValueError:
        return ""
    return host[4:] if host.startswith("www.") else host


def url_key(url: str) -> str:
    """scheme, www., fragment, query and trailing slash dropped."""
    try:
        p = urllib.parse.urlsplit(url.strip())
    except ValueError:
        return ""
    return host_of(url) + (p.path or "/").rstrip("/").lower()


def is_generic_host(host: str) -> bool:
    return (any(host == g or host.endswith("." + g) for g in GENERIC_HOSTS) or _is_aggregator(host)
            or any(host == g or host.endswith("." + g) for g in EXTRA_AGGREGATORS))


def split_lang(path: str) -> Tuple[str, str]:
    """(language prefix or "", path without it)."""
    segs = [x for x in path.lower().split("/") if x]
    if segs and segs[0] in LANGS:
        return segs[0], "/" + "/".join(segs[1:])
    if segs and segs[0] in ("en", "en-us", "en-gb"):
        return "", "/" + "/".join(segs[1:])
    return "", "/" + "/".join(segs)


def page_check(html: str, final_url: str = "") -> Tuple[Optional[str], str]:
    """(title or None, reject reason or "")."""
    from core import pagetext
    m = re.search(r"<title[^>]*>(.*?)</title>", html or "", re.I | re.S)
    title = m and re.sub(r"\s+", " ", pagetext.to_text(m.group(1))).strip()
    if not title:
        h = re.search(r"<h1[^>]*>(.*?)</h1>", html or "", re.I | re.S)
        title = h and re.sub(r"\s+", " ", pagetext.to_text(h.group(1))).strip()
    h1 = re.search(r"<h1[^>]*>(.*?)</h1>", html or "", re.I | re.S)
    h1t = re.sub(r"\s+", " ", pagetext.to_text(h1.group(1))).strip() if h1 else ""
    if not (title or h1t):
        return None, "no_title"
    if PAST_TITLE.search(title or "") or PAST_TITLE.search(h1t):
        return None, "past_or_news"
    if not (CATEGORY_TITLE.search(title or "") or CATEGORY_TITLE.search(h1t)):
        return None, "title_no_category"
    if not APPLICANT_CUE.search(pagetext.to_text(html)):
        return None, "no_applicant_cue"
    return title or h1t, ""


# -- path filter ------------------------------------------------------------ #
def classify_path(url: str) -> Optional[str]:
    """Category implied by the URL path, "" if ambiguous, None if not a candidate."""
    try:
        p = urllib.parse.urlsplit(url)
    except ValueError:
        return None
    path = (p.path or "/")
    low = path.lower()
    segs = [s for s in low.split("/") if s]
    if not segs or _is_landing(path) or EXCLUDED_EXT.search(low) or DATE_PATH.search(low):
        return None
    if any(s in EXCLUDED_SEGMENTS for s in segs) or LAST_SEGMENT_NOISE.search(segs[-1]):
        return None
    if NOISE_SUBSTR.search(low) or any(s in EXCLUDED_SEGMENTS for s in re.split(r"[-_]", segs[-1]) if s in ("shop", "store", "merch", "gala", "venue", "terms", "privacy")):
        return None
    if len(segs) >= 2 and segs[-2] == "page" and segs[-1].isdigit():
        return None
    if len(re.split(r"[-_]", segs[-1])) > 7:  # long slugs are articles, not programmes
        return None
    if HACKATHON.search(low) or is_vacancy_text(url):
        return None
    hits = [cat for cat, rx in KEYWORDS if rx.search(low)]
    if not hits:
        return None
    return hits[0] if len(hits) == 1 else ""


def provisional_name(url: str) -> str:
    segs = [s for s in urllib.parse.urlsplit(url).path.split("/") if s]
    segs = [EXCLUDED_EXT.sub("", re.sub(r"\.(?:html?|php|aspx?)$", "", s, flags=re.I)) for s in segs]
    chosen = next((s for s in reversed(segs) if s.lower() not in GENERIC_LAST), segs[-1] if segs else "")
    words = re.sub(r"[-_+]+|%20", " ", urllib.parse.unquote(chosen)).split()
    return " ".join(w.capitalize() if w.islower() else w for w in words)[:120]


# -- network ---------------------------------------------------------------- #
class Budget:
    def __init__(self, max_requests: int, sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.monotonic):
        self.left, self.sleep, self.clock = max_requests, sleep, clock
        self.last_any, self.last_host = 0.0, {}
        self.cc_down = False  # set after a failed index query; skip the rest of the run

    def take(self, host: str, delay: float = HOST_DELAY) -> bool:
        if self.left <= 0:
            return False
        now = self.clock()
        wait = max(self.last_any + GLOBAL_DELAY - now, self.last_host.get(host, -1e9) + delay - now, 0)
        if wait:
            self.sleep(wait)
        self.last_any = self.last_host[host] = self.clock()
        self.left -= 1
        return True


def http_get(url: str, timeout: int = 30) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": robots.UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(MAX_SITEMAP_BYTES)


def _decode(data: bytes) -> str:
    return discovery.decode_body(data, MAX_SITEMAP_BYTES)


parse_sitemap = discovery.parse_sitemap
robots_sitemaps = discovery.robots_sitemaps


def sitemap_urls(host: str, budget: Budget, get: Callable[[str], bytes],
                 allowed: Callable[[str], bool]) -> Tuple[List[str], bool]:
    """URLs from the host's sitemaps. Returns (urls, robots_blocked)."""
    origin = "https://" + host
    if not allowed(origin + "/"):
        return [], True
    listed: List[str] = []
    if budget.take(host):
        try:
            listed = robots_sitemaps(get(origin + "/robots.txt").decode("utf-8", "replace"))
        except Exception:  # noqa: BLE001
            listed = []
    queue = [u for u in listed if host_of(u) == host or host_of(u).endswith("." + host)] or [origin + "/sitemap.xml"]
    urls: List[str] = []
    files, seen = 0, set()
    while queue and files < MAX_SITEMAP_FILES and len(urls) < MAX_HOST_URLS:
        sm = queue.pop(0)
        if sm in seen or not allowed(sm) or not budget.take(host_of(sm) or host):
            continue
        seen.add(sm)
        files += 1
        try:
            is_index, locs = parse_sitemap(_decode(get(sm)))
        except Exception:  # noqa: BLE001
            continue
        if is_index:
            if len(seen) == 1:  # one level only
                queue.extend(locs)
        else:
            urls.extend(locs)
    return urls[:MAX_HOST_URLS], False


def commoncrawl_urls(host: str, budget: Budget, cc_get: Callable[[str], str] = None,
                     crawl: Optional[str] = None, limit: int = 5000) -> List[str]:
    """One CDX page of status-200 URLs for the host (matchType=prefix)."""
    if budget.cc_down or not budget.take("index.commoncrawl.org", CC_DELAY):
        return []
    cc_get = cc_get or (lambda u: enumerate_boards._cc_get(u, 120))
    try:
        crawl = crawl or enumerate_boards._latest_crawl()
        return discovery.cc_host_urls(host, crawl, cc_get, limit)
    except Exception:  # noqa: BLE001
        budget.cc_down = True
        return []


# -- data ------------------------------------------------------------------- #
def known_hosts(rows: Iterable[dict]) -> Tuple[Dict[str, dict], Set[str]]:
    """host -> {organizer, count} from served programme rows; plus every known URL key."""
    hosts: Dict[str, dict] = {}
    keys: Set[str] = set()
    for r in rows:
        for f in ("official_url", "application_url"):
            if r.get(f):
                keys.add(url_key(str(r[f])))
        if not r.get("official_url") or not is_serving(r) or quality_reason(r):
            continue
        h = host_of(str(r["official_url"]))
        if not h or is_generic_host(h):
            continue
        d = hosts.setdefault(h, {"orgs": Counter(), "n": 0})
        d["orgs"][str(r.get("organizer") or h)] += 1
        d["n"] += 1
    return {h: {"organizer": d["orgs"].most_common(1)[0][0], "n": d["n"]} for h, d in hosts.items()}, keys


def make_seed(cat: str, url: str, organizer: str, source: str, now: str, title: str = "") -> Optional[dict]:
    name = (_clean_seed_name(title) if title else "") or provisional_name(url)
    if len(name) < 4 or _merge_seed_filter_reason(cat, _clean_seed_name(name), url):
        return None
    p = urllib.parse.urlsplit(url)
    host = host_of(url)
    slug = re.sub(r"[^a-z0-9]+", "-", host).strip("-")[:40]
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:6]
    path = (p.path or "/").strip("/")
    return {
        "source_id": "find-{}-{}-{}".format(cat, slug, digest),
        "programme_id": "{}-find-{}-{}".format(cat, slug, digest),
        "programme_name": name,
        "organizer": organizer,
        "official_url": url,
        "allowed_path_hints": [path],
        "check_cadence": "monthly",
        "source_kind": "official",
        "discovered_from": source,
        "first_seen": now,
        "last_seen": now,
    }


def candidates_for_host(host: str, urls: Dict[str, str], default_cat: str, organizer: str,
                        known: Set[str], per_host: int,
                        accept: Optional[Callable[[str], bool]] = None) -> List[Tuple[str, str, str, str]]:
    """[(category, url, organizer, source)] after the path filter, language dedupe and cap.

    ``accept`` (page check) is called lazily so only needed pages are fetched."""
    all_paths = {split_lang(urllib.parse.urlsplit(u).path) for u in urls}
    base_paths = {b for lang, b in all_paths if not lang}
    seen, found, lang_seen = set(known), [], set()
    for url in sorted(urls, key=lambda u: (len(urllib.parse.urlsplit(u).path), u)):
        cat = classify_path(url)
        if cat is None:
            continue
        lang, base = split_lang(urllib.parse.urlsplit(url).path)
        if lang and (base in base_paths or base in lang_seen):
            continue
        key = url_key(url)
        if key in seen:
            continue
        seen.add(key)
        if lang:
            lang_seen.add(base)
        norm = "https://{}{}".format(urllib.parse.urlsplit(url).netloc.lower(), urllib.parse.urlsplit(url).path)
        if accept and not accept(norm):
            continue
        found.append((cat or default_cat, norm, organizer, urls[url]))
        if len(found) >= per_host:
            break
    return found


def load_shard(path: str) -> List[dict]:
    with open(path, encoding="utf-8") as h:
        data = json.load(h)
    return data if isinstance(data, list) else []


def _read(path: str) -> List[dict]:
    try:
        with open(path, encoding="utf-8") as h:
            v = json.load(h)
        return v if isinstance(v, list) else []
    except (OSError, ValueError):
        return []


def append_seeds(path: str, seeds: List[dict]) -> int:
    """Append-only: existing entries are untouched; new ones skipped if URL/id present."""
    existing = _read(path)
    have_urls = {url_key(str(s.get("official_url"))) for s in existing if isinstance(s, dict)}
    have_ids = {s.get("source_id") for s in existing if isinstance(s, dict)}
    added = [s for s in seeds if url_key(s["official_url"]) not in have_urls and s["source_id"] not in have_ids]
    if added:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as h:
            json.dump(existing + added, h, indent=1)
        os.replace(tmp, path)
    return len(added)


def run(shards_dir: str, categories: List[str], max_hosts: int = 200, per_host: int = 10, max_new: int = 100,
        max_requests: int = 2000, dry_run: bool = False, seeds_dir: str = SEEDS_DIR, use_cc: bool = True,
        get: Callable[[str], bytes] = http_get, allowed: Optional[Callable[[str], bool]] = None,
        cc_get: Optional[Callable[[str], str]] = None, sleep: Callable[[float], None] = time.sleep,
        out=print, fetch: Optional[Callable[[str], tuple]] = None) -> Dict[str, list]:
    allowed = allowed or (lambda u: robots.allowed(u)[0])
    budget = Budget(max_requests, sleep)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    # Every URL already known or seeded anywhere is excluded, across categories.
    all_keys: Set[str] = set()
    per_cat: Dict[str, Tuple[Dict[str, dict], List[dict]]] = {}
    for cat in categories:
        rows = load_shard(os.path.join(shards_dir, CATEGORIES[cat] + ".json")) if os.path.isfile(
            os.path.join(shards_dir, CATEGORIES[cat] + ".json")) else []
        hosts, keys = known_hosts(rows)
        all_keys |= keys
        per_cat[cat] = (hosts, rows)
    for cat in CATEGORIES:
        for name in (cat, "finder_" + cat):
            all_keys |= {url_key(str(s.get("official_url"))) for s in _read(os.path.join(seeds_dir, name + ".json"))
                         if isinstance(s, dict)}
    host_cache: Dict[str, Tuple[Dict[str, str], bool, int, int]] = {}
    results: Dict[str, list] = {}
    pending: Dict[str, List[dict]] = {c: [] for c in categories}
    rejects: Counter = Counter()
    titles: Dict[str, str] = {}

    def accept(url: str) -> bool:
        if fetch is None:
            return True
        if not budget.take(host_of(url)):
            rejects["budget"] += 1
            return False
        try:
            html = fetch(url)[0]
        except Exception:  # noqa: BLE001
            rejects["fetch_failed"] += 1
            return False
        title, why = page_check(html)
        if why:
            rejects[why] += 1
            return False
        titles[url] = title
        return True
    for cat in categories:
        hosts = sorted(per_cat[cat][0])[:max_hosts]
        blocked = sm_total = cc_total = 0
        for host in hosts:
            if host not in host_cache:
                urls: Dict[str, str] = {}
                sm, was_blocked = sitemap_urls(host, budget, get, allowed)
                for u in sm:
                    urls.setdefault(u, "finder:sitemap")
                n_cc = 0
                if use_cc and not was_blocked:
                    for u in commoncrawl_urls(host, budget, cc_get):
                        if allowed(u):
                            n_cc += 1
                            urls.setdefault(u, "finder:commoncrawl")
                host_cache[host] = (urls, was_blocked, len(sm), n_cc)
            urls, was_blocked, n_sm, n_cc = host_cache[host]
            blocked += was_blocked
            sm_total += n_sm
            cc_total += n_cc
            allowed_urls = {u: s for u, s in urls.items() if allowed(u)} if not was_blocked else {}
            for c, url, org, src in candidates_for_host(host, allowed_urls, cat, per_cat[cat][0][host]["organizer"],
                                                        all_keys, per_host, accept):
                seed = make_seed(c, url, org, src, now, titles.get(url, ""))
                if seed and url_key(url) not in all_keys:
                    all_keys.add(url_key(url))
                    pending.setdefault(c, []).append(seed)
        results[cat] = []
    new_counts: Dict[str, int] = {}
    for c, seeds in pending.items():
        seeds = seeds[:max_new]
        results[c] = seeds
        new_counts[c] = len(seeds) if dry_run else append_seeds(os.path.join(seeds_dir, "finder_{}.json".format(c)), seeds)
    for cat in categories:
        hosts = sorted(per_cat[cat][0])[:max_hosts]
        cached = [host_cache[h] for h in hosts if h in host_cache]
        out("finder {}: hosts={} robots_blocked={} sitemap_urls={} cc_urls={} candidates={} new={} rejects={}".format(
            cat, len(hosts), sum(c[1] for c in cached), sum(c[2] for c in cached), sum(c[3] for c in cached),
            len(results.get(cat, [])), new_counts.get(cat, 0), dict(rejects)))
    return results


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--shards", required=True, help="directory with <shard>.json files")
    ap.add_argument("--categories", default=",".join(CATEGORIES))
    ap.add_argument("--max-hosts", type=int, default=200)
    ap.add_argument("--per-host", type=int, default=10)
    ap.add_argument("--max-new", type=int, default=100)
    ap.add_argument("--max-requests", type=int, default=2000)
    ap.add_argument("--no-commoncrawl", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--samples", type=int, default=0, help="print N sample candidates")
    a = ap.parse_args(argv)
    cats = [c.strip() for c in a.categories.split(",") if c.strip()]
    bad = [c for c in cats if c not in CATEGORIES]
    if bad:
        ap.error("unknown categories: {}".format(", ".join(bad)))
    from categories.programme_core import _default_fetch as _fetch
    res = run(a.shards, cats, a.max_hosts, a.per_host, a.max_new, a.max_requests, a.dry_run,
              use_cc=not a.no_commoncrawl, fetch=_fetch)
    shown = 0
    for c, seeds in res.items():
        for s in seeds:
            if shown < a.samples:
                print("  [{}] {} | {} | {}".format(c, s["official_url"], s["programme_name"], s["discovered_from"]))
                shown += 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
