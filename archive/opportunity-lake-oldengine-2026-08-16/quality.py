"""Lake hygiene. Pure functions, no network, no AI.

`filters.py` decides whether a single posting is worth keeping. This file decides
whether the SET of kept postings is an honest picture, which is a different
question and needs to see all the rows at once.

Four problems, all measured on the real lake on 2026-07-31 rather than assumed:

  A2  Staffing agencies post for unnamed clients. The project's own rules ban
      rows without a named employer, so an agency row is unactionable by
      construction: a student cannot research the company, cannot check
      eligibility, and cannot tell whether the role exists.

  A5  Keka returns location as a concatenated blob, not a field:
      "Bangalore Bengaluru KA Hyderabad HYD". Unparsed, a city filter on the
      website cannot work, and the same city appears two or three times in one
      string.

  A6  One company appears under several board tokens. greenhouse:alphasense and
      greenhouse:alphasenseindia are one employer, so per-company arithmetic and
      per-company caps are both wrong until identity is resolved.

  A1  One company was 25.6% of the entire lake. workable:kiavets posted 311
      near-identical roles.

      IMPORTANT, and the opposite of what the issue list assumed: those 311 rows
      carry 310 DISTINCT titles, because the dealership name is baked into each
      one ("Automotive Apprenticeship for Military Veterans - Flow Kia of
      Charlottesville"). Exact-title collapse removes 1 row of 311. Across the
      whole lake, exact duplicate-title-per-company accounts for only 54 rows.
      Collapsing this needs title NORMALISATION — strip the trailing branch or
      location segment — plus a per-company cap as a backstop.

NOTHING IS DELETED. Every function here annotates. A row that fails hygiene gets
a flag and is excluded from surfaced counts, never dropped from jobs.json. That
keeps the arithmetic auditable and honours the project's own no-delete rule: if a
cap or a recruiter heuristic is wrong, the evidence is still on disk.
"""

from __future__ import annotations

import collections
import re
from typing import Dict, Iterable, List, Optional, Tuple

import filters

# --------------------------------------------------------------------------- #
# A2. Staffing agencies and recruitment firms
# --------------------------------------------------------------------------- #
# Detected from the board token and the title, because those are the only two
# fields available before a description download.
#
# The named tokens are the ones actually observed polluting this lake. They are
# listed explicitly rather than left to the patterns because several of them
# (classet, peoplelogic, alkujobs) contain no recruitment word at all and no
# general pattern would ever catch them.
KNOWN_RECRUITERS = frozenset({
    "mediix-recruitment",
    "cesna-group", "cesna-group-2", "cesna",
    "alkujobs", "alku",
    "classet",
    "peoplelogic",
    "americanchase",
})

# Token-shaped signals: a board whose name says it sells hiring services.
#
# Deliberately conservative. An earlier version matched `jobs$`, which flagged
# `hi-jobs` (Humanity & Inclusion, an NGO using that board token) as a staffing
# agency. A false positive here silently deletes a real opportunity, which is
# worse than letting an agency through — an agency row that slips past is at
# least visible and can be argued with.
RECRUITER_TOKEN = re.compile(
    r"(recruit\w*|staffing|staff\w*-solutions|manpower|placement\w*|"
    r"talent[\s-]?(?:acquisition|solutions|partners|hunt\w*)|"
    r"hr[\s-]?(?:solutions|services|consult\w*)|"
    r"headhunt\w*|"
    r"outsourc\w*|payroll[\s-]?service\w*|"
    r"resourc\w*[\s-]?(?:solutions|services|consult\w*))",
    re.I,
)

# Title-shaped signals. These must indicate the AGENCY BUSINESS MODEL, not the
# recruiting profession. "Intern - Technical Recruitment" at Vyapar is a named
# employer hiring a recruiting intern — a real, checkable posting that simply is
# not technical, and the discipline classifier already handles that. What the
# project's rules actually ban is a posting whose employer is unnamed, so only
# bench/client-side staffing language belongs here.
RECRUITER_TITLE = re.compile(
    r"\b(us\s+it\s+recruit\w*|us[\s-]?staffing|bench\s+sales|"
    r"c2c|corp[\s-]?to[\s-]?corp|w2\s+recruit\w*|"
    r"for\s+our\s+client|on\s+behalf\s+of\s+(?:our\s+)?client|"
    r"client\s+of\s+ours|multiple\s+clients|our\s+client\s+is)\b",
    re.I,
)


def is_recruiter(token: str, title: str = "", company: str = "") -> Tuple[bool, str]:
    """(is_agency, why). Why is kept so a wrong verdict can be argued with."""
    tok = (token or "").strip().lower()
    if tok in KNOWN_RECRUITERS:
        return True, "known_agency_token"
    m = RECRUITER_TOKEN.search(tok)
    if m:
        return True, "token_matches_{}".format(m.group(1)[:24])
    m = RECRUITER_TITLE.search(title or "")
    if m:
        return True, "title_matches_{}".format(m.group(1)[:24])
    m = RECRUITER_TOKEN.search((company or "").lower())
    if m:
        return True, "company_matches_{}".format(m.group(1)[:24])
    return False, ""


# --------------------------------------------------------------------------- #
# A5. Location blobs -> structured cities
# --------------------------------------------------------------------------- #
# Indian two-letter state codes as Keka emits them, plus the longer forms it
# mixes in. These are noise in a city list: "Bangalore Bengaluru KA" is one
# city, written three ways.
STATE_CODES = {
    "ka": "Karnataka", "mh": "Maharashtra", "tg": "Telangana", "ts": "Telangana",
    "tn": "Tamil Nadu", "dl": "Delhi", "hr": "Haryana", "up": "Uttar Pradesh",
    "gj": "Gujarat", "kl": "Kerala", "rj": "Rajasthan", "wb": "West Bengal",
    "pb": "Punjab", "mp": "Madhya Pradesh", "ap": "Andhra Pradesh",
    "or": "Odisha", "od": "Odisha", "br": "Bihar", "as": "Assam",
    "ch": "Chandigarh", "ga": "Goa", "jk": "Jammu and Kashmir",
    "hp": "Himachal Pradesh", "uk": "Uttarakhand", "cg": "Chhattisgarh",
    "jh": "Jharkhand",
}

# Spellings that are the same city. The canonical form is the one an Indian
# student would recognise, which is not always the official rename.
CITY_ALIASES = {
    "bangalore": "Bengaluru", "bengaluru": "Bengaluru", "blr": "Bengaluru",
    "bombay": "Mumbai", "mumbai": "Mumbai", "navi mumbai": "Navi Mumbai",
    "calcutta": "Kolkata", "kolkata": "Kolkata",
    "madras": "Chennai", "chennai": "Chennai", "maa": "Chennai",
    "gurgaon": "Gurugram", "gurugram": "Gurugram",
    "hyderabad": "Hyderabad", "hyd": "Hyderabad", "secunderabad": "Hyderabad",
    "new delhi": "New Delhi", "delhi": "New Delhi", "ncr": "Delhi-NCR",
    "noida": "Noida", "greater noida": "Noida",
    "pune": "Pune", "pimpri": "Pune",
    "trivandrum": "Thiruvananthapuram",
    "thiruvananthapuram": "Thiruvananthapuram",
    "cochin": "Kochi", "kochi": "Kochi", "ernakulam": "Kochi",
    "mysore": "Mysuru", "mysuru": "Mysuru",
    "mangalore": "Mangaluru", "mangaluru": "Mangaluru",
    "vizag": "Visakhapatnam", "visakhapatnam": "Visakhapatnam",
    "trichy": "Tiruchirappalli", "tiruchirappalli": "Tiruchirappalli",
    "baroda": "Vadodara", "vadodara": "Vadodara", "varoda": "Vadodara",
    "ahmedabad": "Ahmedabad", "surat": "Surat", "indore": "Indore",
    "jaipur": "Jaipur", "coimbatore": "Coimbatore", "lucknow": "Lucknow",
    "chandigarh": "Chandigarh", "mohali": "Mohali", "bhubaneswar": "Bhubaneswar",
    "nagpur": "Nagpur", "bhopal": "Bhopal", "kanpur": "Kanpur",
    "patna": "Patna", "guwahati": "Guwahati", "dehradun": "Dehradun",
    "goa": "Goa", "panaji": "Panaji", "verna": "Goa", "vellore": "Vellore",
    "madurai": "Madurai", "nashik": "Nashik", "thane": "Thane",
    "anand": "Anand", "matar": "Matar", "poicha": "Poicha",
    "ghatkesar": "Hyderabad", "andheri": "Mumbai", "dombivli": "Mumbai",
}

# Words that are office furniture, not places. Keka puts branch names, floor
# labels and department names in the same field as the city.
LOCATION_NOISE = re.compile(
    r"\b(head\s+office|corporate\s+office|marketing\s+office|"
    r"branch|plant|factory|campus|office|onsite|on[\s-]?site|"
    r"house|square|tower|floor|building|centre|center|"
    r"private\s+limited|pvt\.?\s*ltd\.?|limited|ltd\.?|llc|inc\.?|"
    r"india\s+services|old|new|"
    r"\d+(?:\.\d+)?\s*mw|solar|o&m)\b",
    re.I,
)

SPLIT_RE = re.compile(r"[;,/|]|\s{2,}|\s+[-–]\s+")
REMOTE_WORDS = re.compile(r"\b(remote|wfh|work\s+from\s+home|hybrid|anywhere)\b", re.I)


def parse_locations(blob: str) -> Dict[str, object]:
    """Turn a published location string into something a filter can use.

    Returns cities (canonical, deduped, order preserved), states, remote flag,
    and whether anything was recognisable at all. Never invents a city: if
    nothing matches the known vocabulary, cities is empty and `parsed` is False,
    which is the honest answer for "Rukn Al Ufuq Pharmacy LLC Sharjah SH".

    >>> parse_locations("Bangalore Bengaluru KA Hyderabad HYD")["cities"]
    ['Bengaluru', 'Hyderabad']
    """
    raw = (blob or "").strip()
    out: Dict[str, object] = {
        "cities": [], "states": [], "remote": False, "parsed": False, "raw": raw,
    }
    if not raw:
        return out

    out["remote"] = bool(REMOTE_WORDS.search(raw))

    text = LOCATION_NOISE.sub(" ", raw)
    text = re.sub(r"[()\[\]]", " ", text)
    chunks = [c.strip() for c in SPLIT_RE.split(text) if c.strip()]
    if not chunks:
        chunks = [text]

    cities: List[str] = []
    states: List[str] = []
    for chunk in chunks:
        words = [w for w in re.split(r"[\s]+", chunk) if w]
        # Try two-word city names first ("New Delhi", "Navi Mumbai") so they are
        # not shredded into two unknown tokens.
        i = 0
        while i < len(words):
            two = " ".join(words[i:i + 2]).strip(".,-").lower()
            one = words[i].strip(".,-").lower()
            if two in CITY_ALIASES:
                c = CITY_ALIASES[two]
                if c not in cities:
                    cities.append(c)
                i += 2
                continue
            if one in CITY_ALIASES:
                c = CITY_ALIASES[one]
                if c not in cities:
                    cities.append(c)
            elif one in STATE_CODES:
                s = STATE_CODES[one]
                if s not in states:
                    states.append(s)
            i += 1

    # A state named in full ("Karnataka", "Tamil Nadu") is a state, not a city.
    for full in set(STATE_CODES.values()):
        if re.search(r"\b" + re.escape(full) + r"\b", raw, re.I) and full not in states:
            states.append(full)

    out["cities"] = cities
    out["states"] = states
    out["parsed"] = bool(cities or states)
    return out


# --------------------------------------------------------------------------- #
# A6. Company identity across tokens
# --------------------------------------------------------------------------- #
# Suffixes that a company adds to a second board without becoming a second
# company. Stripped longest-first so "-india-2" resolves fully.
TOKEN_SUFFIXES = (
    "indiaprivatelimited", "privatelimited", "technologies", "technology",
    "solutions", "software", "systems", "services", "consulting", "labs",
    "global", "group", "india", "inc", "llc", "ltd", "limited", "corp",
    "careers", "jobs", "hq", "hr",
)


def company_key(platform: str, token: str) -> str:
    """A stable identity for one employer, across tokens and platforms.

    Deliberately platform-independent: the same company on Greenhouse and Ashby
    is one employer, and counting it twice is the ClickHouse double-count bug
    recorded in LAKE.md §5.

    >>> company_key("greenhouse", "alphasenseindia") == company_key("greenhouse", "alphasense")
    True
    """
    t = re.sub(r"[^a-z0-9]", "", (token or "").lower())
    # Trailing board-instance counters: workable's "cesna-group-2".
    t = re.sub(r"\d+$", "", t)
    changed = True
    while changed and len(t) > 4:
        changed = False
        for suf in TOKEN_SUFFIXES:
            if t.endswith(suf) and len(t) - len(suf) >= 4:
                t = t[: -len(suf)]
                changed = True
                break
    return t or re.sub(r"[^a-z0-9]", "", (token or "").lower())


# --------------------------------------------------------------------------- #
# A1. Duplicate collapse and per-company cap
# --------------------------------------------------------------------------- #
# The branch/location suffix that makes 311 identical jobs look distinct.
# "Automotive Apprenticeship for Military Veterans - Flow Kia of Charlottesville"
# and "... - Century Kia of Tampa" are one job posted 311 times.
BRANCH_SUFFIX = re.compile(
    r"\s*[-–—|(]\s*[^-–—|()]{2,60}\s*\)?\s*$"
)
CITY_IN_TITLE = re.compile(
    r"\s*[-–—(]\s*(" + "|".join(re.escape(c) for c in sorted(CITY_ALIASES, key=len, reverse=True))
    + r")\s*\)?\s*$",
    re.I,
)


def normalise_title(title: str) -> str:
    """Strip the trailing branch/city segment so fan-out collapses.

    Conservative on purpose: only ONE trailing segment is removed, and only if
    what remains is still a substantial title. "Software Engineer - Backend"
    must not collapse to "Software Engineer", because backend and frontend are
    genuinely different jobs — so a segment is only stripped when it looks like
    a place or a branch, not when it looks like a specialism.
    """
    t = " ".join((title or "").split())
    if not t:
        return ""
    m = CITY_IN_TITLE.search(t)
    if m and len(t[: m.start()].strip()) >= 8:
        return t[: m.start()].strip().lower()
    # A trailing segment naming an organisation ("- Flow Kia of Charlottesville",
    # "- Fiesta Kia") is a branch. Detected by containing a capitalised
    # multi-word proper noun and no specialism keyword.
    m = BRANCH_SUFFIX.search(t)
    if m:
        seg = t[m.start():].strip(" -–—|()")
        head = t[: m.start()].strip()
        looks_specialism = re.search(
            r"\b(backend|back[\s-]?end|frontend|front[\s-]?end|full[\s-]?stack|"
            r"android|ios|mobile|web|data|ml|ai|qa|test\w*|devops|security|"
            r"cloud|platform|compiler|embedded|firmware|network\w*|"
            r"intern(?:ship)?|trainee|fresher|apprentice|graduate|"
            r"\d{4}|remote|part[\s-]?time|contract)\b", seg, re.I)
        if (len(head) >= 8 and not looks_specialism
                and len(seg.split()) >= 2 and seg[:1].isupper()):
            return head.lower()
    return t.lower()


def annotate(rows: Iterable[Dict], cap: int = 10) -> List[Dict]:
    """Add hygiene fields to every row. Mutates and returns the same list.

    Fields added:
      company            identity key, shared across tokens (A6)
      is_recruiter       agency posting for an unnamed client (A2)
      recruiter_reason   why, so a false positive is arguable
      cities/states      parsed location (A5)
      title_norm         branch-stripped title (A1)
      dup_of             set when an earlier row has the same company+title_norm
      over_cap           set when a company exceeds `cap` surfaced rows (A1)
      surfaced           the single boolean the website should filter on

    `surfaced` is the whole point: it is False for agency rows, duplicates and
    over-cap rows, and the row still exists on disk with the reason attached.
    """
    rows = list(rows)

    for r in rows:
        r["company"] = company_key(r.get("platform", ""), r.get("token", ""))
        rec, why = is_recruiter(r.get("token", ""), r.get("title", ""))
        r["is_recruiter"] = rec
        r["recruiter_reason"] = why
        loc = parse_locations(r.get("location", ""))
        r["cities"] = loc["cities"]
        r["states"] = loc["states"]
        r["location_parsed"] = loc["parsed"]
        r["title_norm"] = normalise_title(r.get("title", ""))

    # Duplicate collapse: first occurrence of company+normalised title wins.
    # Ordered by first_seen so the oldest row is the survivor and the surviving
    # URL does not churn between sweeps.
    #
    # The location bucket is part of the key. Without it, "Jr. Software Project
    # Coordinator - Goa" and "- Sylhet" collapse into one row, silently merging
    # an India-located job with a Bangladesh one. The India/non-India split is
    # the single most important fact about a row here, so two rows that differ
    # in bucket are never the same opportunity.
    seen: Dict[Tuple[str, str, str], str] = {}
    for r in sorted(rows, key=lambda x: (x.get("first_seen") or "", x.get("url") or "")):
        k = (r["company"], r["title_norm"], r.get("location_bucket") or "")
        if k in seen:
            r["dup_of"] = seen[k]
        else:
            seen[k] = r.get("url") or r.get("job_id") or ""
            r["dup_of"] = None

    # Per-company cap, applied only to rows that survived the steps above, so a
    # company is not penalised for duplicates that were already collapsed.
    per_company: collections.Counter = collections.Counter()
    for r in sorted(rows, key=lambda x: (x.get("first_seen") or "", x.get("url") or "")):
        eligible = not r["is_recruiter"] and not r["dup_of"]
        if not eligible:
            r["over_cap"] = False
            continue
        per_company[r["company"]] += 1
        r["over_cap"] = per_company[r["company"]] > cap

    for r in rows:
        r["surfaced"] = bool(
            not r["is_recruiter"] and not r["dup_of"] and not r["over_cap"]
        )
    return rows


def report(rows: List[Dict]) -> Dict:
    """The numbers a run should print. Every figure here is countable."""
    n = len(rows)
    surfaced = [r for r in rows if r.get("surfaced")]

    def bucket_india(rs):
        return [r for r in rs if r.get("location_bucket") in
                (filters.INDIA_LOCATED, filters.INDIA_REMOTE)]

    india = bucket_india(surfaced)
    cse = [r for r in india if r.get("discipline") == filters.CSE]
    return {
        "rows_total": n,
        "removed_recruiter": sum(1 for r in rows if r.get("is_recruiter")),
        "removed_duplicate": sum(1 for r in rows if r.get("dup_of")),
        "removed_over_cap": sum(1 for r in rows if r.get("over_cap")),
        "surfaced": len(surfaced),
        "surfaced_by_discipline": dict(collections.Counter(
            r.get("discipline") or "unset" for r in surfaced)),
        "surfaced_india": len(india),
        "india_by_discipline": dict(collections.Counter(
            r.get("discipline") or "unset" for r in india)),
        "INDIA_CSE_EARLY_CAREER_OPEN": len(cse),
        "india_needs_description": sum(1 for r in india if r.get("needs_description")),
        "companies_surfaced": len({r["company"] for r in surfaced}),
        "locations_unparsed": sum(
            1 for r in surfaced
            if r.get("location") and not r.get("location_parsed")),
    }


if __name__ == "__main__":
    # Cases are real strings from the lake, including the ones that disproved
    # the original diagnosis.
    print("--- A2 recruiter detection ---")
    rec_cases = [
        ("americanchase", "Associate System Engineer", True),
        ("mediix-recruitment", "Any", True),
        ("cesna-group-2", "Any", True),
        ("classet", "Any", True),
        ("peoplelogic", "Any", True),
        ("alkujobs", "Sales Internship Program", True),
        ("someco", "Associate Trainee - US IT Recruiter", True),
        ("someco", "Hiring for our client - Software Engineer", True),
        # A named employer hiring a recruiting intern is NOT an agency. These
        # were false positives in the first version of this rule.
        ("vyaparapp", "Intern - Technical Recruitment", False),
        ("arcsen", "Technical Recruitment Intern", False),
        ("hi-jobs", "Institutional Funding Trainee - Belgium", False),
        ("manilarecruitment", "Junior Business Analyst (Onsite - Taguig)", True),
        ("blackfigtech", "SDE-Intern", False),
        ("analyticsvidhya", "Data Science Intern", False),
        ("smartdocs", "Jr. Software Developer", False),
    ]
    fails = 0
    for tok, title, want in rec_cases:
        got, why = is_recruiter(tok, title)
        ok = got == want
        fails += 0 if ok else 1
        print("{} {:<20} {:<42} {} {}".format(
            "PASS" if ok else "FAIL", tok, title[:42], got, why))

    print("\n--- A5 location parsing ---")
    loc_cases = [
        ("Bangalore Bengaluru KA Hyderabad HYD", ["Bengaluru", "Hyderabad"]),
        ("Bangalore Bengaluru KA", ["Bengaluru"]),
        ("Corporate Office Anand, Gujarat GJ", ["Anand"]),
        ("Gurgaon Gurgaon HR", ["Gurugram"]),
        ("Delhi New Delhi DL", ["New Delhi"]),
        ("Bengaluru - Head Office (Old) Bengaluru KA Bangalore - Head Office Bengaluru KA",
         ["Bengaluru"]),
        ("Mangaluru Mangaluru KA Bangalore Bangalore KA", ["Mangaluru", "Bengaluru"]),
        ("BLR - First Answer India Services Private Limited Bengaluru KA", ["Bengaluru"]),
        ("Poicha - Plant-460/1, Poicha ,Vadodara VARODA", ["Poicha", "Vadodara"]),
        ("Atlanta; Boston; Charlotte; Chicago", []),          # not India: honest empty
        ("Sweden (Remote)", []),
    ]
    for blob, want in loc_cases:
        got = parse_locations(blob)["cities"]
        ok = got == want
        fails += 0 if ok else 1
        print("{} {:<62} -> {}".format("PASS" if ok else "FAIL", blob[:62], got))

    print("\n--- A6 company identity ---")
    id_cases = [
        (("greenhouse", "alphasense"), ("greenhouse", "alphasenseindia"), True),
        (("workable", "cesna-group"), ("workable", "cesna-group-2"), True),
        (("greenhouse", "alku"), ("greenhouse", "alkujobs"), True),
        (("greenhouse", "clickhouse"), ("ashby", "clickhouse"), True),
        (("keka", "smartdocs"), ("keka", "softmason"), False),
    ]
    for a, b, want in id_cases:
        got = company_key(*a) == company_key(*b)
        ok = got == want
        fails += 0 if ok else 1
        print("{} {:<26} {:<26} same={} ({} / {})".format(
            "PASS" if ok else "FAIL", a[1], b[1], got,
            company_key(*a), company_key(*b)))

    print("\n--- A1 title normalisation (the 311-row fan-out) ---")
    t_cases = [
        ("Automotive Apprenticeship for Military Veterans - Flow Kia of Charlottesville",
         "Automotive Apprenticeship for Military Veterans - Century Kia of Tampa", True),
        # Goa and Sylhet are different countries. normalise_title strips a known
        # city but not an unknown one, and that asymmetry is deliberate: rows
        # that differ by country must never collapse, so annotate() also keys
        # the dedupe on location_bucket.
        ("Jr. Software Project Coordinator - Goa",
         "Jr. Software Project Coordinator - Sylhet", False),
        # These must NOT collapse: a specialism is not a branch.
        ("Software Engineer - Backend", "Software Engineer - Frontend", False),
        ("Digital Media Buyer Trainee 2026 Q1", "Digital Media Buyer Trainee 2026 Q2", False),
    ]
    for a, b, want in t_cases:
        got = normalise_title(a) == normalise_title(b)
        ok = got == want
        fails += 0 if ok else 1
        print("{} collapse={:<5} {!r}".format(
            "PASS" if ok else "FAIL", got, normalise_title(a)[:52]))

    print("\n{} failures".format(fails))
    raise SystemExit(1 if fails else 0)
