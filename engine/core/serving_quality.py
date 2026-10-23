"""Deterministic serving-side quality gate shared by the Supabase publisher.

Applied to NON-job rows (programmes, hackathons) in ``build_serving`` so a
bad row is simply not served; the normal soft-retire then sets it
``is_live=false`` (rows are never deleted and stay in the lake).

Rules (each returns a short reason string, or None to keep the row):
  * ``title_gate``      bare URL/domain/path titles, generic/index/overview/list
                        page titles, scrape junk, malformed URLs, GitHub-Pages /
                        README list aggregations.
  * ``senior_gate``     postdoc / faculty / early-career-with-PhD-only programmes
                        and ones demanding >=3 years of experience.
  * ``hackathon_gate``  closed "X vs Y" national-team matches (World Hackathon
                        Federation) that students cannot join.
  * ``dedupe``          same normalised title + same organiser (or official
                        host) within a category (and across programme
                        categories) keeps one row.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Dict, Iterable, List, Optional
from urllib.parse import urlsplit

# --------------------------------------------------------------------------- #
# Title / URL gate
# --------------------------------------------------------------------------- #
_BARE_URL = re.compile(r"^(?:https?://)?(?:www\.)?[a-z0-9][a-z0-9-]*(?:\.[a-z0-9-]+)*\.[a-z]{2,}(?::\d+)?(?:/\S*)?$", re.I)
_GENERIC_TITLES = frozenset({
    "overview", "home", "homepage", "home page", "faq", "faqs", "opportunities",
    "programs", "programmes", "program list", "programs list", "programme list",
    "programmes list", "apply", "apply now", "apply / details", "details", "learn more",
    "read more", "more", "click here", "here", "link", "website", "about", "about us",
    "contact", "contact us", "resources", "directory", "welcome", "index", "login",
    "log in", "sign up", "register", "info", "information", "untitled", "n/a",
})
_INDEX_TITLE = re.compile(
    r"^(?:(?:the\s+)?(?:complete\s+|ultimate\s+|curated\s+)?list\s+of\b"
    r"|awesome[\s-](?!foundation)"
    r"|resources\s+for\b"
    r"|(?:a\s+)?(?:directory|database|collection)\s+of\b)", re.I)
_INDEX_SUFFIX = re.compile(
    r"(?:\boverview|\bprograms?\s+list|\bprogrammes?\s+list|\bfaqs?|\bhome(?:\s?page)?)\s*$", re.I)
# "... Opportunities" is an index page unless it names a real scheme.
_OPPORTUNITIES_SUFFIX = re.compile(r"\bopportunities\s*$", re.I)
_SCHEME_WORDS = re.compile(
    r"\b(?:program|programme|fellowship|scholarship|award|grant|internship|"
    r"experience|initiative|challenge|competition)s?\b", re.I)
_JUNK_TITLE = re.compile(r"\*\*|\]\(|[a-z]{3}\.\s+[A-Z][a-z]+\s+[a-z]+|not application listings", re.I)
_LIST_WORDS = re.compile(
    r"(?:^|[-_/.])(?:list|lists|awesome|programs?|programmes?|resources|collection|"
    r"directory|opportunities)(?:[-_/.]|$)|list-?of", re.I)


def _norm_ws(v: object) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", str(v or ""))).strip()


def is_github_list_url(url: object) -> bool:
    """GitHub Pages site or README/repo that aggregates other programmes."""
    try:
        parts = urlsplit(str(url or ""))
        host = (parts.hostname or "").casefold().rstrip(".")
        path = (parts.path or "").casefold()
    except ValueError:
        return False
    if host.endswith(".github.io"):
        return bool(_LIST_WORDS.search(host[:-len(".github.io")] + path)) or path.strip("/") == ""
    if host in ("github.com", "raw.githubusercontent.com", "gist.github.com"):
        segs = [s for s in path.split("/") if s]
        if len(segs) >= 2:
            return bool(_LIST_WORDS.search("/".join(segs[1:]))) or "readme" in path or "awesome" in path
    return False


def title_gate(title: object, url: object = None) -> Optional[str]:
    t = _norm_ws(title)
    if not t:
        return "empty_title"
    low = t.casefold().strip(" .:-–—→>")
    if _BARE_URL.match(t) or (" " not in t and "/" in t):
        return "title_is_url"
    if low in _GENERIC_TITLES:
        return "generic_title"
    if _INDEX_TITLE.match(t) or _INDEX_SUFFIX.search(t):
        return "index_title"
    if _OPPORTUNITIES_SUFFIX.search(t) and not _SCHEME_WORDS.search(t):
        return "index_title"
    if _JUNK_TITLE.search(t):
        return "scrape_junk_title"
    u = str(url or "")
    if "**" in u or (u.rstrip().endswith(")") and "(" not in u):
        return "malformed_url"
    if is_github_list_url(u):
        return "github_list_url"
    return None


# --------------------------------------------------------------------------- #
# Too-senior programmes (audience: students, 0-2 years experience)
# --------------------------------------------------------------------------- #
_SENIOR_TITLE = re.compile(
    r"\bpost-?\s?doc(?:toral|s)?\b|\bsociety\s+of\s+fellows\b|\bjunior\s+(?:fellow|faculty)\b|"
    r"\bearly[- ]career\s+(?:awards?|faculty|investigators?|fellows?)\b|\bstarting\s+grants?\b|"
    r"\bconsolidator\s+grants?\b|\badvanced\s+grants?\b|\bfaculty\s+(?:fellow|award|early)", re.I)
_SENIOR_TEXT = re.compile(
    r"\bsupports?\s+post-?\s?doctoral\b|\bpost-?\s?doctoral\s+(?:and\s+senior\s+)?(?:scientists|researchers|scholars|fellows)\b|"
    r"\bfor\s+post-?\s?doctoral\b|\bpostdoctoral\s+positions?\b|"
    r"\bearly[- ]career\s+faculty\b|\btenure[- ]track\b|\bassistant\s+professors?\b|"
    r"\bindependent\s+(?:research\s+)?(?:career|investigators?)\b|"
    r"\binvites\s+[^.]{0,80}\bfaculty\b[^.]{0,80}\bnominations?\b|"
    r"\b(?:phd|ph\.d\.?|doctorate)\s+(?:holders?|graduates?)\b|"
    r"\bwithin\s+\w+\s+years\s+of\s+(?:\w+\s+)?(?:phd|ph\.d|doctora)", re.I)
_STUDENT_POSITIVE = re.compile(
    r"\b(?:undergraduates?|graduate\s+students?|phd\s+students?|doctoral\s+students?|"
    r"master'?s\s+students?|masters?\s+students?|college\s+students?|students?)\b", re.I)
_YEARS_EXPERIENCE = re.compile(
    r"\b(?:at\s+least|minimum(?:\s+of)?|min\.?|over|more\s+than)?\s*(\d{1,2})\s*\+?\s*(?:or\s+more\s+)?years?"
    r"['’]?\s+(?:of\s+)?(?:relevant\s+|professional\s+|work(?:ing)?\s+|industry\s+|research\s+|full-time\s+)?experience", re.I)


def senior_gate(row: Dict, title: object, eligibility: object, description: object) -> Optional[str]:
    """Reason when the programme is postdoc/faculty only or needs >=3 years' experience.

    Looks at the title and the source's own eligibility/description text; the
    derived ``levels``/``summary`` fields are NOT trusted (they list
    "undergraduate" for postdoc schemes).
    """
    if _SENIOR_TITLE.search(_norm_ws(title)):
        return "senior_only"
    own = " ".join(_norm_ws(x) for x in (eligibility, description) if x)
    req = " ".join(_norm_ws(x) for x in (row.get("requirements") if isinstance(row.get("requirements"), str) else "", own))
    for m in _YEARS_EXPERIENCE.finditer(req):
        if int(m.group(1)) >= 3 and not re.search(r"\b0\s*-\s*$", req[max(0, m.start() - 3):m.start()]):
            return "requires_3plus_years"
    if _SENIOR_TEXT.search(own) and not _STUDENT_POSITIVE.search(own):
        return "senior_only"
    return None


# --------------------------------------------------------------------------- #
# Hackathons that students cannot join
# --------------------------------------------------------------------------- #
_VS_TITLE = re.compile(r"\S\s+vs\.?\s+\S", re.I)
_CLOSED_MATCH = re.compile(r"national\s+team|invitation|invite[- ]only|team\s+only", re.I)


def hackathon_gate(title: object, organizer: object, eligibility: object) -> Optional[str]:
    if not _VS_TITLE.search(_norm_ws(title)):
        return None
    if "world hackathon federation" in _norm_ws(organizer).casefold() or _CLOSED_MATCH.search(_norm_ws(eligibility)):
        return "closed_team_match"
    return None


# --------------------------------------------------------------------------- #
# Dedupe
# --------------------------------------------------------------------------- #
_MULTI_SUFFIX = {"co.uk", "ac.uk", "gov.uk", "org.uk", "co.in", "ac.in", "gov.in", "org.in",
                 "com.au", "edu.au", "co.jp", "ac.jp", "com.br", "edu.cn"}
_GENERIC_ORG = frozenset({"", "unknown", "n/a", "none"})


def norm_title(v: object) -> str:
    s = unicodedata.normalize("NFKC", str(v or "")).casefold()
    s = re.sub(r"^the\s+", "", s)
    s = re.sub(r"['’]s\b", "", s)
    s = re.sub(r"[^\w\s]", " ", s, flags=re.UNICODE)
    return re.sub(r"\s+", " ", s).strip()


def host_key(url: object) -> str:
    """Second-level label of the host (``fellowship.mlh.io`` and ``.com`` -> ``mlh``)."""
    try:
        host = (urlsplit(str(url or "")).hostname or "").casefold().rstrip(".")
    except ValueError:
        return ""
    labels = [x for x in host.split(".") if x]
    if len(labels) < 2:
        return ""
    if ".".join(labels[-2:]) in _MULTI_SUFFIX and len(labels) >= 3:
        return labels[-3]
    return labels[-2]


def _org_key(v: object) -> str:
    return re.sub(r"[^a-z0-9]+", "", unicodedata.normalize("NFKC", str(v or "")).casefold())


def same_programme(a: Dict, b: Dict) -> bool:
    """Same normalised title and same official host or same organiser name."""
    if not a["title"] or a["title"] != b["title"]:
        return False
    if a["host"] and a["host"] == b["host"]:
        return True
    return bool(a["org"] and a["org"] == b["org"] and a["org"] not in _GENERIC_ORG)


_CATEGORY_PRIORITY = ["open-source-programmes", "fellowship", "research", "scholarship",
                      "grant", "startup-founder", "community"]


def _cat_rank(cat: object) -> int:
    try:
        return len(_CATEGORY_PRIORITY) - _CATEGORY_PRIORITY.index(cat)
    except ValueError:
        return 0


def _curated(c: Dict) -> int:
    return int("-hub-" not in c["id"])  # hand-curated seed beats an auto-discovered hub row


def _rank_within(c: Dict):
    return (c["official"], c["verified"], _curated(c), c["checked"], c["has_deadline"], c["id"])


def _rank_cross(c: Dict):
    # last_checked / deadline excluded: separate scoped runs must agree on one winner.
    return (c["verified"], c["official"], _curated(c), _cat_rank(c["category"]), c["id"])


def candidate(row: Dict, row_id: str, title: object, company: object, url: object) -> Dict:
    return {
        "id": row_id, "category": row.get("category"), "title": norm_title(title),
        "host": host_key(url) or host_key(row.get("official_url")),
        "org": _org_key(company or row.get("organizer")),
        "official": int(str(row.get("source_kind") or "") == "official"),
        "verified": int(bool(row.get("manually_verified") or row.get("verified_by") or row.get("verified") is True)),
        "checked": str(row.get("last_checked_at") or row.get("last_seen") or ""),
        "has_deadline": int(bool(row.get("deadline"))),
    }


def dedupe(cands: List[Dict], foreign: Iterable[Dict] = ()) -> Dict[str, str]:
    """Return {loser_id: winner_id}. ``cands`` are this run's serving rows;
    ``foreign`` are live rows of OTHER programme categories (already published),
    used only to decide cross-category losers among ``cands``."""
    losers: Dict[str, str] = {}
    by_cat: Dict[object, List[Dict]] = {}
    for c in cands:
        by_cat.setdefault(c["category"], []).append(c)
    for rows in by_cat.values():
        keep: List[Dict] = []
        for c in sorted(rows, key=_rank_within, reverse=True):
            twin = next((k for k in keep if same_programme(k, c)), None)
            if twin is None:
                keep.append(c)
            else:
                losers[c["id"]] = twin["id"]
    survivors = [c for c in cands if c["id"] not in losers]
    pool = survivors + list(foreign)
    for c in survivors:
        for o in pool:
            if o["id"] == c["id"] or o["category"] == c["category"] or not same_programme(o, c):
                continue
            if _rank_cross(o) > _rank_cross(c):
                losers[c["id"]] = o["id"]
                break
    return losers
