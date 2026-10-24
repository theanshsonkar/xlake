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
  * ``grant_gate``      grants aimed at organisations / PIs / institutions or
                        pools >= 1M USD (audience is students and 0-2 yrs).
  * ``dedupe``          same normalised title + same organiser (or official
                        host), or the same normalised official URL, within a
                        category (and across programme categories) keeps one
                        row.
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
# Markdown-table rows / scraped blobs that ended up as a title.
_TITLE_MAX = 150
_BLOB_TITLE = re.compile(r"---|##|\u2705|\*\*")
# Database / list / forum pages (not a single programme).
_DATABASE_TITLE = re.compile(
    r"^(?:a\s+)?(?:\S+\s+){0,2}database\s+of\b|\bfunding\s+schemes\b|\bcommunity\s+forum\b", re.I)
_BAD_HOSTS = frozenset({"ecrcentral.org", "github.community"})
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


_BOLD_WRAPPED = re.compile(r"^\*\*([^*|#\[\]]+)\*\*$")


def clean_title(title: object) -> str:
    """Whitespace-normalised title; a title that is only ``**bold**`` loses the markers."""
    t = _norm_ws(title)
    m = _BOLD_WRAPPED.match(t)
    return m.group(1).strip() if m else t


def _bad_host(url: object) -> bool:
    try:
        host = (urlsplit(str(url or "")).hostname or "").casefold().rstrip(".")
    except ValueError:
        return False
    return any(host == h or host.endswith("." + h) for h in _BAD_HOSTS)


def title_gate(title: object, url: object = None) -> Optional[str]:
    t = clean_title(title)
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
    if t.count("|") >= 2 or _BLOB_TITLE.search(t) or len(t) > _TITLE_MAX:
        return "scrape_junk_title"
    if _DATABASE_TITLE.search(t):
        return "index_title"
    if _bad_host(url):
        return "index_host"
    u = str(url or "")
    if "**" in u or (u.rstrip().endswith(")") and "(" not in u):
        return "malformed_url"
    if is_github_list_url(u):
        return "github_list_url"
    return None


# --------------------------------------------------------------------------- #
# Recover a programme name from a scraped markdown-table row
# --------------------------------------------------------------------------- #
_US_STATES = frozenset(s.casefold() for s in (
    "Alabama Alaska Arizona Arkansas California Colorado Connecticut Delaware Florida Georgia Hawaii Idaho "
    "Illinois Indiana Iowa Kansas Kentucky Louisiana Maine Maryland Massachusetts Michigan Minnesota "
    "Mississippi Missouri Montana Nebraska Nevada Ohio Oklahoma Oregon Pennsylvania Tennessee Texas Utah "
    "Vermont Virginia Washington Wisconsin Wyoming").split()) | {
    "new hampshire", "new jersey", "new mexico", "new york", "north carolina", "north dakota",
    "rhode island", "south carolina", "south dakota", "west virginia", "district of columbia"}
_MONTH = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?"
_T_DATE = re.compile(r"^\s*(?:" + _MONTH + r"\s+\d{1,2}\b|\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{2,4})", re.I)
_T_STATUS = re.compile(
    r"^(?:rolling|fafsa|automatic|quarterly|monthly|annual|varies|deadline|new\s*\(|check\s+site)\b|"
    r"^(?:open|opens?\s+soon|closed|tbd|tba|multiple|remote|n/a|none|status|company|program|type|location|"
    r"fellowship|scholarship|grant|award|internship|rolling)$", re.I)
_T_DEADLINE_TAIL = re.compile(r"\s+[\u2014\u2013-]+\s+(?:deadline|incoming|cohort)\b.*$|\s+\(\s*deadline\b.*$", re.I)
_T_NOUN = re.compile(
    r"\b(?:scholarships?|fellowships?|fellows?|grants?|programs?|programmes?|awards?|prizes?|expert|leader|"
    r"promise|hope|tap|ignite|focus|scholars\w*|internships?|initiative|challenge|intensive)\b", re.I)
_T_ORG = re.compile(r"\b(?:universit(?:y|ies)|college|consortium|foundation|institute|/)\b|/", re.I)
_T_NOISE_CELL = re.compile(r"##|---|^>|:warning:|\bresident\b|\bup to\b|\bfafsa\b|\bpriority\b|\bpassed\b", re.I)
_T_EMOJI = re.compile("[\u2705\U0001F525\u23F3\u274C\u26A0\uFE0F\U0001F4A1\u2B50]")
_T_TAG = re.compile(r"\[(?:OPEN|CLOSED|OPENS?\s+SOON)\]", re.I)


def _t_cell(c: str) -> str:
    c = _T_EMOJI.sub("", c)
    c = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", c)  # [text](url) -> text
    c = _T_TAG.sub("", c).replace("**", "").replace("__", "")
    c = _T_DEADLINE_TAIL.sub("", _norm_ws(c))
    return c.strip(" -\u2014\u2013:;,")


_T_COMPLETE = ("Scholarship", "Fellowship", "Program", "Grant", "Award", "Prize")


def _t_repair_truncated(c: str) -> str:
    """Last cell of a title cut at the length cap: drop dangling bits, complete a partial noun."""
    c = re.sub(r"\s*\([^)]*$", "", c)  # unclosed paren
    if re.search(r"\s[\u2014\u2013]\s", c):
        c = re.split(r"\s[\u2014\u2013]\s", c)[:-1]
        c = " \u2014 ".join(c)  # the last segment is the cut-off one
    else:
        m = re.search(r"(\S+)$", c)
        if m and not c.endswith(")"):
            w = m.group(1)
            full = next((n for n in _T_COMPLETE if n.casefold().startswith(w.casefold())), None)
            if full and (len(w) >= 2 or len(c.split()) > 1):
                return c[:m.start()] + full
            if len(c.split()) > 1:
                c = c[:m.start()]
    c = re.sub(r"(?:\s+(?:for|and|of|in|the|at|to|&|a|an|with|on))+$", "", c.strip(), flags=re.I)
    return c.strip(" -\u2014\u2013:;,")


def recover_table_title(title: object) -> Optional[str]:
    """Programme name hidden in a scraped markdown-table row, or None when only noise remains."""
    raw = _norm_ws(title)
    if "|" not in raw and not _T_TAG.search(raw) and not _T_EMOJI.search(raw):
        return None
    parts = raw.split("|")
    truncated = len(raw) >= 119 and not raw.endswith("|")
    cells, tcells = [], []
    for i, c in enumerate(parts):
        if re.search(r"##|---|^\s*>|:warning:", c):
            continue
        last = truncated and i == len(parts) - 1
        c0 = c
        c = _t_cell(c)
        if last and not _T_DEADLINE_TAIL.search(_norm_ws(_T_EMOJI.sub("", c0))):
            c = _t_repair_truncated(c)
        low = c.casefold()
        if (not c or _T_DATE.match(c) or _T_STATUS.match(c) or low in _US_STATES
                or len(re.findall(r"[A-Za-z]", c)) < 4 or len(c) > 100
                or (re.match(r"^(?:\d|\$)", c) and not _T_NOUN.search(c)) or _T_NOISE_CELL.search(c)):
            continue
        (tcells if last else cells).append(c)
    named = [c for c in cells if _T_NOUN.search(c)] + [c for c in tcells if _T_NOUN.search(c)]
    if named:
        plain = [c for c in named if not _T_ORG.search(c)]
        pick = (plain or named)[0]
    else:
        # no programme noun: org cell then programme cell; a lone cell is just an organiser name
        allc = cells + tcells
        pick = allc[1] if len(allc) >= 2 else None
    if not pick or title_gate(pick) or len(pick) < 4:
        return None
    return pick


# --------------------------------------------------------------------------- #
# Too-senior programmes (audience: students, 0-2 years experience)
# --------------------------------------------------------------------------- #
_SENIOR_TITLE = re.compile(
    r"\bpost-?\s?doc(?:toral|s)?\b|\bsociety\s+of\s+fellows\b|\bjunior\s+(?:fellow|faculty)\b|"
    r"\bearly[- ]career\s+(?:awards?|faculty|investigators?|fellows?)\b|\bstarting\s+grants?\b|"
    r"\bconsolidator\s+grants?\b|\badvanced\s+grants?\b|\bfaculty\s+(?:fellow|award|early)|"
    r"\bvisiting\s+faculty\b|\bfaculty\s+(?:research\s+)?(?:fellowships?|scholars?|programs?|programmes?)\b|"
    r"\bcareer\s+awards?\b|\binvestigators?\b|\bhfsp\b|\bhuman\s+frontier\s+science\b", re.I)
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


# School-level schemes (e.g. India's "Pre Matric" scholarships for classes 1-10): audience is college students.
_SCHOOL_TITLE = re.compile(r"\bgrades?\s+(?:[1-9]|1[0-2])\s*(?:[-–]|to)\s*(?:[1-9]|1[0-2])\b(?!.*\b(?:college|universit|undergrad))|\bpre[- ]?matric\b|\bclass(?:es)?\s+(?:[1-9]|10)(?:\s*(?:-|to|and)\s*(?:[1-9]|10))?\b(?!\s*\+)|\bschool\s+students?\b", re.I)


def senior_gate(row: Dict, title: object, eligibility: object, description: object) -> Optional[str]:
    """Reason when the programme is postdoc/faculty only or needs >=3 years' experience.

    Looks at the title and the source's own eligibility/description text; the
    derived ``levels``/``summary`` fields are NOT trusted (they list
    "undergraduate" for postdoc schemes).
    """
    if _SENIOR_TITLE.search(_norm_ws(title)):
        return "senior_only"
    if _SCHOOL_TITLE.search(_norm_ws(title)):
        return "school_level"
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


_HIGH_SCHOOL = re.compile(
    r"\bhigh[- ]?school(?:ers?|\s+students?)?\b|\bmiddle[- ]school(?:ers?)?\b|\bsecondary[- ]school\b|"
    r"\bk-?12\b|\bteen(?:s|agers?)?\b|\bgrades?\s+(?:6|7|8|9|10|11|12)\b", re.I)
_COLLEGE = re.compile(
    r"\bcollege\b|\buniversit(?:y|ies)\b|\bundergrad\w*\b|\bgraduate\b|\bpost-?secondary\b|"
    r"\bbachelor'?s?\b|\buni\s+students?\b", re.I)


def hackathon_gate(title: object, organizer: object, eligibility: object) -> Optional[str]:
    org, elig, ttl = _norm_ws(organizer), _norm_ws(eligibility), _norm_ws(title)
    if _VS_TITLE.search(ttl):
        if "world hackathon federation" in org.casefold() or _CLOSED_MATCH.search(elig):
            return "closed_team_match"
    # High-school / middle-school only events (audience is college students).
    own = " ".join((ttl, org, elig))
    if _HIGH_SCHOOL.search(own) and not _COLLEGE.search(own):
        return "high_school_only"
    return None


# --------------------------------------------------------------------------- #
# Grants aimed at organisations / PIs (audience: students, 0-2 years)
# --------------------------------------------------------------------------- #
_ORG_NOUN = (r"(?:institutions?|organi[sz]ations?|compan(?:y|ies)|smes?|universit(?:y|ies)|"
             r"principal\s+investigators?|pis|faculty|research\s+(?:teams?|groups?|centres?|centers?)|"
             r"consorti(?:um|a)|start-?ups?\s+compan(?:y|ies)|non-?profits?|ngos?|"
             r"businesses|firms|enterprises|laborator(?:y|ies)|hospitals?|public\s+bodies)")
_GRANT_ORG_TEXT = re.compile(
    r"\b(?:open|available|eligible|restricted|limited|aimed|targeted|designed|intended)\s+(?:only\s+)?(?:to|for|at)\s+(?:\w+[\s-]+){0,3}" + _ORG_NOUN + r"\b|"
    r"\bapplicants?\s+(?:must|should|need\s+to|have\s+to|are|can\s+be)\s+(?:be\s+)?(?:an?\s+|the\s+|registered\s+|legally\s+|eligible\s+)*(?:\w+[\s-]+){0,3}" + _ORG_NOUN + r"\b|"
    r"\b(?:organi[sz]ations?|institutions?|compan(?:y|ies)|universit(?:y|ies)|smes?|consorti(?:um|a)|"
    r"principal\s+investigators?|faculty(?:\s+members?)?)\s+(?:can|may|must|should)\s+(?:apply|submit)\b|"
    r"\bsupports?\s+(?:\w+\s+){0,2}(?:universit(?:y|ies)|institutions|organi[sz]ations|researchers?\s+at\s+(?:universit|institut)|smes?)\b|"
    r"\bprincipal\s+investigators?\b|\bsmall\s+and\s+medium(?:-sized)?\s+(?:enterprises|businesses)\b|\bsmes\b|"
    r"\bfaculty\s+members?\b|\bconsorti(?:um|a)\b|\bsbir\b|\bsttr\b|\bcalls?\s+for\s+proposals\b|"
    r"\bacademic\s+institutions?\b|\bbusiness-led\b|\bgrowth[- ]stage\s+startups?\b|"
    r"\binvests?\s+in\s+(?:\w+[- ]){0,2}(?:startups|companies)\b|\bestablished\s+researchers\b|\bregistered\s+(?:legal\s+)?(?:entit|compan|organi)", re.I)
# Titles that name an institution/PI-facing scheme even when the page text is thin.
_GRANT_ORG_TITLE = re.compile(
    r"\b(?:simons|kauffman|mellon|macarthur|rockefeller|ford|gates|moore|open\s+society)\s+foundations?\b|"
    r"\bsmart\s+grants?\b|\bcalls?\s*$|(?<!transition\s)\bfunding(?:\s+opportunities)?\s*$|\bdiscovery\s+(?:grants?|awards?)\b|"
    r"\bextramural\b|\bcore\s+research\b|(?<!globalink\s)\bresearch\s+(?:awards?|grants?)\b|"
    r"\bpathfinder\b|\bresearch\s+scholar\b|\bsbir\b|\bsttr\b", re.I)
_GRANT_STUDENT = re.compile(
    r"\bstudents?\b|\bundergrad\w*\b|\bindividual\s+(?:founders?|applicants?|developers?|creators?)\b|"
    r"\bearly[- ]stage\s+founders?\b|\bsolo\s+founders?\b|\bindividuals?\b|\byoung\s+(?:people|founders|entrepreneurs)\b|"
    r"\bfirst[- ]time\s+founders?\b|\bmaintainers?\b|\bopen[- ]source\s+(?:projects?|developers?|contributors?)\b|\bbuilders?\b", re.I)
_GRANT_POOL_USD = 1_000_000
_FELLOW_TITLE = re.compile(r"\bfellow(?:s|ship|ships)?\b", re.I)
# Curated exceptions that the grant gate would wrongly drop.
KEEP_IDS = frozenset({"programme:grant-github-fund"})


def grant_gate(title: object, eligibility: object, description: object,
               funding_usd: object = None, requirements: object = None,
               row_id: object = None) -> Optional[str]:
    """Reason when a grant targets institutions/PIs/companies or is a >=1M pool,
    unless the source text names students / individual or early-stage founders."""
    if row_id in KEEP_IDS or _FELLOW_TITLE.search(_norm_ws(title)):
        return None  # curated fund / individual fellowship (senior_gate handles postdoc ones)
    reqs = " ".join(requirements) if isinstance(requirements, list) else _norm_ws(requirements)
    own = " ".join(_norm_ws(x) for x in (title, eligibility, description, reqs) if x)
    if _GRANT_ORG_TITLE.search(_norm_ws(title)):
        return "grant_for_organisations"
    if _GRANT_STUDENT.search(own):
        return None
    try:
        usd = float(funding_usd) if funding_usd not in (None, "") else 0.0
    except (TypeError, ValueError):
        usd = 0.0
    if usd >= _GRANT_POOL_USD:
        return "grant_pool_too_large"
    if _GRANT_ORG_TEXT.search(own):
        return "grant_for_organisations"
    return None


# --------------------------------------------------------------------------- #
# Dedupe
# --------------------------------------------------------------------------- #
_MULTI_SUFFIX = {"co.uk", "ac.uk", "gov.uk", "org.uk", "co.in", "ac.in", "gov.in", "org.in",
                 "com.au", "edu.au", "co.jp", "ac.jp", "com.br", "edu.cn"}
_GENERIC_ORG = frozenset({"", "unknown", "n/a", "none"})


_PLURAL_WORDS = re.compile(r"\b(fellowship|scholarship|grant|award|program|programme|internship|prize|challenge)s\b")


def norm_title(v: object) -> str:
    s = unicodedata.normalize("NFKC", str(v or "")).casefold()
    s = re.sub(r"^the\s+", "", s)
    s = re.sub(r"['’]s\b", "", s)
    s = re.sub(r"\(s\)", "", s)  # "Fellowship(s)" -> "Fellowship"
    s = re.sub(r"(?<=\w)\.(?=\w)", "", s)  # "Ph.D." -> "PhD"
    s = re.sub(r"[^\w\s]", " ", s, flags=re.UNICODE)
    s = _PLURAL_WORDS.sub(r"\1", s)
    return re.sub(r"\s+", " ", s).strip()


def norm_url(url: object) -> str:
    """host (no www) + path without trailing slash; scheme/query/fragment dropped.
    Empty for a bare homepage (many programmes share an organiser's root URL)."""
    try:
        parts = urlsplit(str(url or "").strip())
    except ValueError:
        return ""
    host = (parts.hostname or "").casefold().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    path = re.sub(r"/+$", "", parts.path or "").casefold()
    if not host or not path:
        return ""
    return host + path


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


def _similar_title(a: str, b: str) -> bool:
    """Equal, or one title's words are all inside the other's (>= 2 words)."""
    if not a or not b:
        return False
    ta, tb = set(a.split()), set(b.split())
    if ta == tb:
        return True
    small, big = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    return len(small) >= 2 and small <= big


def same_programme(a: Dict, b: Dict) -> bool:
    """Same normalised title and same official host or same organiser name; or the
    same normalised official URL with a near-identical title (an aggregator page
    such as scholarships.gov.in/All-Scholarships lists many distinct schemes, so
    a shared URL alone never merges rows)."""
    if a.get("url") and a.get("url") == b.get("url") and _similar_title(a["title"], b["title"]):
        return True
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
        "url": norm_url(url) or norm_url(row.get("official_url")),
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
