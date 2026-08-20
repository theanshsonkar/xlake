"""Title and location filters. Pure functions, no network, no AI.

This file decides what a B.Tech student can apply to, using only the title and
location string that every board returns. It runs before any description is
downloaded, which is what keeps the sweep cheap: most postings are rejected here
for free.

Everything in this file is deliberately NOT AI. Seniority, career stage,
technical relevance and location bucketing are pattern problems. A model here
would cost money per posting and could hallucinate a verdict.

The gates that genuinely need reading the full posting text — graduation year
windows, experience ceilings, degree requirements, institution restrictions —
are not here. Those come later, from the description.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

# NOTE: Never classify a posting using the source platform's own category or
# discipline metadata. Amazon filed an SDE internship under "Administrative
# Support". Classify from title and description text only.
#
# --------------------------------------------------------------------------- #
# Seniority and career stage: title signals only
# --------------------------------------------------------------------------- #
# Word-boundary anchored so "Senior" is caught but "Internship" is not damaged.
# `staff` is intentionally absent here: it is senior only when it is visibly a
# level, such as "Staff Engineer". In particular, Member(s) of Technical Staff
# is a normal India fresher/IC title and is explicitly exempt below.
SENIOR = re.compile(
    r"\b("
    r"senior|sr\.?|principal|lead|leader|head|manager|mgr|director|"
    r"architect|vp|vice\s+president|chief|cto|ceo|cfo|coo|"
    r"specialist\s+iv|expert|fellow|distinguished|"
    r"staff\s+(?:[a-z0-9./&+-]+\s+){0,3}?(?:engineer|engineering|sde|swe|scientist|developer|programmer|architect|researcher|analyst|designer|manager)\b|"
    r"(?:sde|swe|software\s+development\s+engineer|engineer|analyst)"
    r"\s*[- ]?\s*(?:ii|iii|iv|2|3|4)\b|"
    r"level\s*[- ]?\s*(?:ii|iii|iv|2|3|4|5)\b|"
    r"l[2-4]\b|"
    r"(?:5|[6-9]|\d{2,})\s*\+\s*years?\b|"
    r"(?:4|5|[6-9]|\d{2,})\s+(?:to|-)\s+\d{1,2}\s+years?\b|"
    r"(?:5|[6-9]|\d{2,})\s+years?\b"
    r")\b",
    re.I,
)

MEMBER_TECHNICAL_STAFF = re.compile(
    r"\bmembers?\s+of\s+technical\s+staff\b", re.I
)
MTS_SENIOR_LEVEL = re.compile(
    r"\bmembers?\s+of\s+technical\s+staff\s*[-\u2013\u2014,]?\s*"
    r"(?:ii|iii|iv|[2-4])\b", re.I
)

# "Manager" inside "Product Manager, Intern" would wrongly reject; these win.
EARLY_OVERRIDE = re.compile(r"\b(intern|internship|trainee|apprentice)\b", re.I)

# Existing early-career vocabulary.
EARLY = re.compile(
    r"\b("
    r"intern|interns|internship|"
    r"trainee|traineeship|"
    r"fresher|freshers|"
    r"apprentice|apprenticeship|"
    r"graduate\s+engineer|graduate\s+trainee|graduate\s+programme|graduate\s+program|"
    r"graduate\s+scheme|campus|"
    r"new\s+grad|new\s+graduate|entry[\s-]?level|early\s+career|"
    r"placement\s+year|industrial\s+placement|"
    r"emerging\s+talent|explore\s+program|"
    # Non-English markets. Miss these and SAP, Zalando, Rakuten look empty.
    r"praktikum|praktikant|werkstudent|absolvent|"
    r"stagiaire|alternance|"
    r"新卒|インターン"
    r")\b",
    re.I | re.UNICODE,
)

# Explicit junior markers and level-one markers. The roman numeral I is part of
# a role-specific expression with a trailing word boundary, so it cannot match
# inside words or the prefix of II/III.
EARLY_LEVEL = re.compile(
    r"(?:\b(?:associate|junior|jr\.?|trainee)\b|"
    r"\b(?:sde|swe)\s*(?:-?\s*1|i)\b|"
    r"\b(?:software\s+development\s+engineer|engineer|analyst)"
    r"\s*(?:-?\s*1|i)\b|"
    r"\bl1\b|\blevel\s*[- ]?\s*1\b)",
    re.I,
)

# Kept as compatibility aliases for callers that imported the old patterns.
MAYBE_EARLY = EARLY_LEVEL
ASSOCIATE_ONLY = re.compile(r"\bassociate\b", re.I)
JUNIOR_STRICT = EARLY_LEVEL

# --------------------------------------------------------------------------- #
# Technical relevance for a B.Tech student
# --------------------------------------------------------------------------- #
# Measured against the real lake on 2026-07-31: 659 of 1,215 rows (54%) came
# back technical=None. Reading them showed the diagnosis in the issue list was
# backwards. They were not unrecognised engineering titles. They were chefs,
# plumbers, nurses, sommeliers, animators, recruiters, accountants and 311 car
# dealership apprenticeships. The missing vocabulary was almost entirely
# NON_TECHNICAL, not TECHNICAL.
#
# Two genuine TECHNICAL gaps did exist, both stemming bugs rather than missing
# words: `\btest\b` does not match "Testing" (so "Intern - Quality and Testing"
# was unclassified) and there was no bare "technical" (so "Technical Trainee"
# was too). Those are fixed with \w* suffixes below.

# Role nouns that decide what the job IS, whatever technical words surround it.
# Checked BEFORE TECHNICAL, because "Intern - Technical Recruitment" and
# "Technical Trainer Intern-2026" are recruitment and training jobs that happen
# to contain the word "technical". Without this precedence, adding "technical"
# to TECHNICAL would have mislabelled both as engineering roles.
STRONG_NON_TECHNICAL = re.compile(
    r"\b("
    # People / hiring — the most common false positive in this lake
    r"recruit\w*|recruiter|talent\s+acquisition|staffing|sourcer|"
    r"escalation\s+engineer|business\s+application|solutions?\s+engineer|"
    r"risk\s+management|"
    r"trainer|training\s+operations|"
    # Selling
    r"sales|telecall\w*|telecalling|sdr|bdr|lead\s+generation|"
    r"business\s+development|go[\s-]?to[\s-]?market|gtm|"
    r"account\s+executive|account\s+manager|"
    # Money and law
    r"accountant|accounting|book\s?keep\w*|taxation|treasury|payroll|"
    r"kyc|aml|anti[\s-]?money|money\s+laundering|financial\s+crime|"
    r"litigation|counsel|paralegal|company\s+secretary|icwa|"
    r"actuar\w*|underwrit\w*|"
    # Trades and manual work
    r"chef|sommelier|culinary|butcher|fishmonger|barista|waiter|"
    r"plumb\w*|electrician|hvac|welder|fitter|woodworker|carpenter|"
    r"mechanic|automotive|installer|technician\s*-?\s*install|"
    r"warehouse|forklift|"
    # Health
    r"nurse|nursing|physiotherap\w*|pharmac\w*|dental|dentist|"
    r"echocardiograph\w*|therapist|radiograph\w*|phlebotom\w*|"
    r"behavio(?:u)?r\s+technician|"
    # Teaching and social
    r"teacher|teaching|preschool|curriculum|ministry|casework|"
    r"social\s+work|counsellor|counselor|nutrition\w*|"
    # Green and physical estate
    r"horticultur\w*|landscap\w*|agronom\w*|gardener|facilities|"
    # Creative
    r"animator|animation|motion\s+design\w*|fx\s+artist|cfx|vfx|"
    r"concept\s+artist|videograph\w*|photograph\w*|copywriter|"
    r"sommelier|"
    # Admin and ops
    r"executive\s+assistant|personal\s+assistant|receptionist|"
    r"housekeep\w*|guest\s+(?:operations|relations)|front\s+office|"
    r"travel\s+consultant|"
    r"customer\s+service|customer\s+care|"
    r"data\s+entry|mis\b"
    r")\b",
    re.I,
)

TECHNICAL = re.compile(
    r"\b("
    r"software|developer|develop\w*|dev|engineer|engineering|sde|swe|"
    r"programm\w*|programmer|technical|"
    r"backend|back[\s-]?end|frontend|front[\s-]?end|full[\s-]?stack|"
    r"data|database|analytics|analytic|analyst|"
    r"ml|machine\s+learning|ai|artificial\s+intelligence|deep\s+learning|"
    r"nlp|computer\s+vision|llm|generative|"
    r"devops|sre|site\s+reliability|platform|infrastructure|cloud|"
    r"qa|quality\s+assurance|quality\s+and\s+testing|sdet|"
    r"test\w*|automation|automat\w*|"
    r"android|ios|mobile|web|"
    r"python|java|golang|rust|react|node|salesforce|oracle|sap|"
    r"security|cyber|network\w*|embedded|firmware|hardware|vlsi|"
    r"compiler|systems|system\s+admin\w*|robotics|research|"
    r"cad|cae|mechatronic\w*|electrical|electronic\w*|instrumentation|"
    r"scrum|sysadmin|it\s+support|technology"
    r")\b",
    re.I,
)

# Explicitly non-technical, so we can report the split honestly rather than
# quietly counting a video-editing internship as an engineering opportunity.
NON_TECHNICAL = re.compile(
    r"\b("
    r"hr|human\s+resource|payroll|"
    r"inside\s+sales|bd|"
    r"marketing|seo|smm|social\s+media|influencer|brand|"
    r"content|copy\s+writer|writer|editor|blog|"
    r"video|graphic|design(?:er)?\s|photoshop|illustrator|"
    r"finance|financial|accounts|audit|billing|procurement|"
    r"supply\s+chain|logistics|"
    r"customer\s+support|customer\s+success|customer\s+experience|"
    r"operations\s+executive|merchant\s+operations|"
    r"legal|admin|office|reception|"
    r"communication|public\s+relations|\bpr\b|event\s+management|"
    r"fundraising|investor\s+relations|monitoring\s*&\s*evaluation|"
    r"partnership\w*|strategy|consulting|m&a|"
    r"apprenticeship\s+for\s+military\s+veterans"
    r")\b",
    re.I,
)

# --------------------------------------------------------------------------- #
# Bare titles — no signal at all, only the description can classify them
# --------------------------------------------------------------------------- #
# "Intern", "Trainee", "Campus Hiring 2025", "Internship" carry a career stage
# and nothing else: no function, no discipline. Guessing technical=False on
# these throws away real engineering internships; guessing True pollutes the
# lake. The honest answer is that the title is insufficient and the description
# is required. 21 such rows exist in the lake today, 14 of them in India.
BARE_TITLE = re.compile(
    r"^\W*("
    r"intern|interns|internship|internships|"
    r"trainee|trainees|traineeship|"
    r"apprentice|apprenticeship|"
    r"fresher|freshers|graduate\s+trainee|management\s+trainee|"
    r"associate\s+trainee|officer\s+trainee|"
    r"campus\s+hiring(?:\s+\d{4})?|campus\s+program(?:me)?|"
    r"internship\s+program(?:me)?|"
    r"junior\s+executive|jr\.?\s+executive"
    r")\W*(\d{4})?\W*$",
    re.I,
)

# --------------------------------------------------------------------------- #
# Location
# --------------------------------------------------------------------------- #
INDIA_CITIES = (
    "india", "bengaluru", "bangalore", "hyderabad", "pune", "delhi", "new delhi",
    "ncr", "noida", "gurugram", "gurgaon", "mumbai", "navi mumbai", "thane",
    "chennai", "kolkata", "ahmedabad", "kochi", "cochin", "indore", "jaipur",
    "coimbatore", "lucknow", "chandigarh", "mohali", "bhubaneswar", "nagpur",
    "surat", "vadodara", "thiruvananthapuram", "trivandrum", "mysore", "mysuru",
    "nashik", "visakhapatnam", "mangaluru", "mangalore", "bhopal", "kanpur",
    "patna", "guwahati", "dehradun", "goa", "vellore", "madurai", "trichy",
    "karnataka", "maharashtra", "telangana", "tamil nadu", "gujarat", "kerala",
    "haryana", "uttar pradesh", "rajasthan", "west bengal", "punjab",
)
INDIA_RE = re.compile(r"\b(" + "|".join(re.escape(c) for c in INDIA_CITIES) + r")\b", re.I)

# Remote that genuinely includes India.
REMOTE_OPEN = re.compile(
    r"\b(worldwide|world\s?wide|global(?:ly)?\s*remote|remote\s*[-–,]?\s*global|"
    r"work\s+from\s+anywhere|anywhere|any\s+location|fully\s+remote|remote\s*\(global\))\b",
    re.I,
)
REMOTE_ANY = re.compile(r"\b(remote|wfh|work\s+from\s+home|hybrid|online|virtual)\b", re.I)

# Remote restricted to a region that excludes India -> not actionable.
REMOTE_EXCLUDES_INDIA = re.compile(
    r"\b(remote\s*[-–,(]?\s*(us|usa|united\s+states|uk|emea|eu|europe|latam|"
    r"noram|dach|iberia|apac\s+excl|canada|australia|argentina|brazil|mexico|"
    r"south\s+america|north\s+america))\b",
    re.I,
)

INDIA_LOCATED = "india_located"
INDIA_REMOTE = "india_remote"          # remote/worldwide that explicitly includes India
REMOTE_GLOBAL = "remote_global"        # generic remote, no region bar: reachable from India
GLOBAL_HIRING = "global_hiring"        # overseas on-site / unknown location: needs relocation
EXCLUDED = "excluded"                  # remote restricted to a region that bars India


def location_bucket(location: str, india_source: bool = False) -> str:
    """Which applicability bucket a posting falls into.

    ``india_source`` treats blank or otherwise unspecified remote locations from
    India-first sources as India-remote. Explicit foreign locations still retain
    their normal global or excluded classification.
    """
    loc = (location or "").strip()
    if not loc:
        return INDIA_REMOTE if india_source else GLOBAL_HIRING
    if INDIA_RE.search(loc):
        return INDIA_LOCATED
    if REMOTE_OPEN.search(loc):
        return INDIA_REMOTE
    if REMOTE_EXCLUDES_INDIA.search(loc):
        return EXCLUDED
    if REMOTE_ANY.search(loc):
        return INDIA_REMOTE if india_source else REMOTE_GLOBAL
    return GLOBAL_HIRING  # overseas on-site; retained and searchable, ranked lower


# --- Accessibility: how reachable an opportunity is for an India-based user. ---
# The index stays comprehensive (nothing trustworthy is dropped for being
# foreign); accessibility is what the default feed ranks by.
ACCESS_INDIA = "india_located"           # physically in India
ACCESS_REMOTE_GLOBAL = "remote_global"   # remote / open worldwide: reachable from India
ACCESS_FOREIGN_ONSITE = "foreign_onsite" # on-site abroad: needs relocation/visa
ACCESS_EXCLUDED = "excluded"             # source explicitly bars India: not eligible

_ACCESS_BY_BUCKET = {
    INDIA_LOCATED: ACCESS_INDIA,
    INDIA_REMOTE: ACCESS_REMOTE_GLOBAL,
    REMOTE_GLOBAL: ACCESS_REMOTE_GLOBAL,
    GLOBAL_HIRING: ACCESS_FOREIGN_ONSITE,
    EXCLUDED: ACCESS_EXCLUDED,
}

# Lower rank = surfaced higher in the default feed.
ACCESS_RANK = {ACCESS_INDIA: 0, ACCESS_REMOTE_GLOBAL: 1,
               ACCESS_FOREIGN_ONSITE: 2, ACCESS_EXCLUDED: 3}

# The default (non-noisy) feed surfaces these tiers; foreign on-site sits behind a filter.
DEFAULT_FEED_TIERS = (ACCESS_INDIA, ACCESS_REMOTE_GLOBAL)


def accessibility(bucket: Optional[str]) -> str:
    """Accessibility tier for an India-based user, derived from a location bucket."""
    return _ACCESS_BY_BUCKET.get(bucket, ACCESS_FOREIGN_ONSITE)


def access_rank(bucket: Optional[str]) -> int:
    """Default-feed sort key (0 = highest priority)."""
    return ACCESS_RANK[accessibility(bucket)]


# --------------------------------------------------------------------------- #
# Discipline — is this a B.Tech CSE role specifically?
# --------------------------------------------------------------------------- #
# `technical` is too coarse for the beta. Measured on the real lake: of the 76
# India rows marked technical=True, the set included "AI Prompt Associate -
# Brand Content", "Gen AI Creative Marketing Manager", "AI Video Editor &
# Content Creator", "Skincare Research & Development (Lab) Associate",
# "Associate Financial Analyst", "Junior Research Scientist CDMO" and
# "Associate Hardware Design Engineer". All technical-adjacent. None of them a
# CSE job.
#
# The cause is that "AI" and "data" are now marketing adjectives, and the old
# TECHNICAL regex matched adjectives as readily as role nouns. So discipline is
# decided by the ROLE NOUN, and an adjective on its own decides nothing.
#
# Four outcomes:
#   cse        a B.Tech CSE graduate is the intended applicant
#   other_eng  real engineering, wrong branch (mechanical, civil, VLSI, chem)
#   non_tech   not an engineering role at all
#   unknown    the title genuinely cannot say — send it to the description pass
#
# "unknown" is a feature, not a failure. "Graduate Engineer Trainee" is the most
# common early-career title in India and it is discipline-blind by design; 8 of
# them sit on one board in this lake. Guessing CSE would put solar-plant jobs in
# front of a CSE student. Guessing not-CSE would drop real software roles.

# Role nouns that make it a CSE job.
CSE_ROLE = re.compile(
    r"\b("
    r"software\s+(?:engineer\w*|developer|development|dev)|"
    r"sde|swe|sdet|"
    r"web\s+developer|"
    r"(?:back|front)[\s-]?end\s+(?:engineer\w*|developer|dev)|"
    r"full[\s-]?stack|"
    r"(?:android|ios|mobile)\s+(?:engineer\w*|developer|dev)|"
    r"app(?:lication)?\s+developer|"
    r"programmer|coder|low[\s-]?latency\s+developer|"
    r"data\s+(?:engineer\w*|scientist|analyst|analysis|science)|"
    r"(?:ml|ai|machine\s+learning|deep\s+learning|nlp|computer\s+vision|llm)\s+"
    r"(?:engineer\w*|developer|dev|scientist|research(?:er)?|intern(?:ship)?)|"
    # Unambiguously CSE fields. Unlike a bare "AI", naming one of these as the
    # subject of an internship does identify the discipline.
    r"generative\s+ai|machine\s+learning|deep\s+learning|"
    r"computer\s+vision|natural\s+language|"
    r"devops|devsecops|sre|site\s+reliability|"
    r"platform\s+engineer\w*|cloud\s+engineer\w*|infrastructure\s+engineer\w*|"
    # QA needs a role noun or a known QA phrase. A bare "test" would otherwise
    # pull in "Hybrid Tester" from an automotive board.
    r"qa|quality\s+assurance|quality\s+and\s+testing|"
    r"test\s+automation|automation\s+test\w*|test(?:ing)?\s+"
    r"(?:engineer\w*|analyst|intern|specialist)|"
    r"(?:security|appsec|cyber)\s*"
    r"(?:engineer\w*|analyst|researcher|investigator)|"
    r"application\s+security|penetration\s+test\w*|"
    r"network\s+engineer\w*|system\s+(?:engineer\w*|administrator|admin)|"
    r"sysadmin|it\s+support|"
    r"compiler|"
    r"quantitative\s+(?:developer|research\w*|trad\w*)|"
    r"embedded\s+(?:engineer\w*|developer|software)|firmware|"
    r"technical\s+(?:trainee|intern)|"
    r"support\s+engineer\w*|implementation\s+engineer\w*|solutions?\s+engineer\w*"
    r")\b",
    re.I,
)

# Language-prefixed developer titles. Kept out of CSE_ROLE because a leading
# `\b` cannot match before the "." in ".NET" — "Junior .NET developer" silently
# fell through to unknown until this was split out.
CSE_LANG = re.compile(
    r"(?:\.net|dotnet|java|python|golang|node(?:\.js)?|react|php|ruby|rust|c\+\+|c#)"
    r"\s+(?:developer|engineer|dev|programmer)",
    re.I,
)

# A non-CSE role noun beats any technical adjective in front of it. This is what
# stops "AI Prompt Associate - Brand Content" and "Gen AI Designer" from
# counting as software jobs.
CSE_VETO = re.compile(
    r"\b("
    r"marketing|brand|content|creative|copywrit\w*|writer|editor|"
    r"video|prompt\s+associate|social\s+media|"
    r"graphic|visual\s+design\w*|ux\s+design\w*|ui\s+design\w*|designer|"
    r"lab|laboratory|skincare|pharma\w*|cdmo|formulation|"
    r"medical|clinical|provider\s+network|"
    r"financial\s+analyst|finance|accounting|ca/cma|"
    r"compliance|"
    r"annotation|data\s+entry|"
    r"escalation\s+engineer|business\s+application\s+engineer|"
    r"solutions?\s+engineer|analyst\s+risk\s+management|"
    r"sales|business\s+development|growth\s+associate|"
    r"recruit\w*|talent|"
    r"artist|"
    r"fraud\s+(?:risk\s+)?analyst|"
    r"credit\s+risk\s+analyst|"
    r"voc\s*[-–—]\s*research\s+executive|"
    r"research\s+executive"
    r")\b",
    re.I,
)

# Real engineering, wrong branch. A CSE student is not the intended applicant.
OTHER_ENG = re.compile(
    r"\b("
    r"mechanical|civil|structural|chemical|metallurg\w*|"
    r"electrical|electronic\w*|instrumentation|"
    r"vlsi|analog|rf\s+design|pcb|semiconductor|asic|fpga\s+(?:layout|physical)|"
    r"hardware\s+design|harness|cad|cae|"
    r"hydraulic|thermal|hvac|automotive|"
    r"solar|plant|production|maintenance|manufactur\w*|"
    r"physicist|photonics|"
    r"process\s+engineer|design\s+engineer\s*-?\s*(?:mech|elec)"
    r")\b",
    re.I,
)

# Titles that name a discipline-blind engineering trainee programme. Extremely
# common in India, and unresolvable from the title alone.
AMBIGUOUS_ENG = re.compile(
    r"^\W*("
    r"(?:graduate|post\s+graduate)\s+engineer\s+trainee|"
    r"engineer(?:ing)?\s+trainee|trainee\s+engineer|"
    r"(?:jr\.?|junior|associate)\s+engineer|"
    r"engineer|graduate\s+engineer|"
    r"management\s+trainee\s*-?\s*(?:technical|engineering)?"
    r")\W*(\d{4})?\W*$",
    re.I,
)

CSE = "cse"
OTHER_ENG_D = "other_eng"
NON_TECH = "non_tech"
UNKNOWN_D = "unknown"


def discipline_of(title: str) -> str:
    """cse | other_eng | non_tech | unknown, from the title alone.

    Order is the whole design:
      1. a discipline-blind engineer title is unknown, never guessed
      2. a non-CSE role noun vetoes, however technical the adjectives
      3. a CSE role noun decides
      4. another engineering branch decides
      5. a clearly non-technical role decides
      6. anything left is unknown and goes to the description pass
    """
    t = (title or "").strip()
    if not t:
        return UNKNOWN_D
    if AMBIGUOUS_ENG.match(t) or BARE_TITLE.match(t):
        return UNKNOWN_D
    if CSE_VETO.search(t):
        # A veto word plus a hard CSE role noun is still CSE: "Security Analyst"
        # inside "Application Security (AppSec) - Security Analyst (Freshers)"
        # should survive the word "compliance" appearing elsewhere. Only give
        # the veto up when the CSE role noun is unmistakable.
        if not CSE_ROLE.search(t) and not CSE_LANG.search(t):
            return NON_TECH
        if re.search(r"\b(marketing|brand|content|video|artist|prompt|"
                     r"skincare|lab|pharma\w*|cdmo|medical|clinical|"
                     r"escalation\s+engineer|business\s+application\s+engineer|"
                     r"solutions?\s+engineer|analyst\s+risk\s+management)\b", t, re.I):
            return NON_TECH
    if CSE_ROLE.search(t) or CSE_LANG.search(t):
        return CSE
    if OTHER_ENG.search(t):
        return OTHER_ENG_D
    if STRONG_NON_TECHNICAL.search(t) or NON_TECHNICAL.search(t):
        return NON_TECH
    if TECHNICAL.search(t):
        # technical-ish but no role noun matched: "Intern - Product",
        # "Associate Business Analyst". Not confidently CSE either way.
        return UNKNOWN_D
    return UNKNOWN_D


# --------------------------------------------------------------------------- #
# Description experience resolution — stage remains the title verdict
# --------------------------------------------------------------------------- #
# These patterns run only after whitespace normalisation so board formatting
# cannot hide a requirement, while quotes are recovered from the source text.
EXP_RANGE = re.compile(
    r"\b(\d{1,2})\s*(?:-|\u2013|\u2014|to|~)\s*(\d{1,2})\s*\+?\s*"
    r"(?:years?|yrs?)\b", re.I
)
EXP_PLUS = re.compile(r"\b(\d{1,2})\s*\+\s*(?:years?|yrs?)\b", re.I)
EXP_MIN_WORDS = re.compile(
    r"\b(?:minimum|min\.?|at\s+least|atleast|over|more\s+than)\s+"
    r"(?:of\s+)?(\d{1,2})\s*\+?\s*(?:years?|yrs?)\b", re.I
)
EXP_BARE = re.compile(r"\b(\d{1,2})\s*(?:years?|yrs?)\b", re.I)
EXP_ANCHOR = re.compile(
    r"experien|exp\.|hands[\s-]?on|background|professional|industry|relevant|"
    r"work(?:ing)?\s+history|track\s+record", re.I
)
EXP_HISTORY_NEG = re.compile(
    r"(?:in\s+the\s+)?(?:last|past)|over\s+the\s+past|since|founded|"
    r"for\s+the\s+past|ago", re.I
)
EXP_FRESHER = re.compile(
    r"\b(?:freshers?|fresh\s+graduates?|"
    r"no\s+(?:(?:prior|previous)(?:\s*/\s*|\s+)?(?:work\s+)?|work\s+)?"
    r"experience\s+(?:required|necessary)|"
    r"0\s*(?:-|to)\s*[12]\s*(?:years?|yrs?)|"
    r"entry[\s-]?level|campus\s+h(?:ire|iring)|"
    r"final[\s-]?year\s+students?|recent\s+graduates?)\b", re.I
)


def _normalise_with_map(text: str) -> Tuple[str, List[int]]:
    """Collapse whitespace and retain source offsets for evidence quotes."""
    chars = []
    offsets = []
    in_space = False
    for index, char in enumerate(text):
        if char.isspace():
            if not in_space:
                chars.append(" ")
                offsets.append(index)
            in_space = True
        else:
            chars.append(char)
            offsets.append(index)
            in_space = False
    return "".join(chars), offsets


def _source_quote(text: str, offsets: List[int], start: int, end: int) -> str:
    if not offsets or start >= end:
        return ""
    original_start = offsets[start]
    original_end = offsets[min(end, len(offsets)) - 1] + 1
    return text[original_start:original_end].strip()[:160]


def experience_signals(
    text: str,
) -> Tuple[
    List[Tuple[float, Optional[float], str]],
    List[Tuple[float, Optional[float], str]],
    Optional[str],
]:
    """Separate anchored requirements from unanchored numeric noise.

    Specific forms consume their spans before the bare form runs so a range is
    never counted again as two independent years signals.
    """
    normalised, offsets = _normalise_with_map(text)
    remaining = list(normalised)
    requirements: List[Tuple[float, Optional[float], str]] = []
    generics: List[Tuple[float, Optional[float], str]] = []

    def collect(pattern) -> None:
        current = "".join(remaining)
        for match in pattern.finditer(current):
            before = current[max(0, match.start() - 30):match.start()]
            context = current[max(0, match.start() - 80):
                              min(len(current), match.end() + 80)]
            minimum = float(match.group(1))
            maximum = (float(match.group(2))
                       if match.lastindex and match.lastindex >= 2 else None)
            quote = _source_quote(text, offsets, match.start(), match.end())
            signal = (minimum, maximum, quote)
            if EXP_ANCHOR.search(context) and not EXP_HISTORY_NEG.search(before):
                requirements.append(signal)
            else:
                generics.append(signal)
            for index in range(match.start(), match.end()):
                remaining[index] = " "
            current = "".join(remaining)

    collect(EXP_RANGE)
    collect(EXP_PLUS)
    collect(EXP_MIN_WORDS)
    collect(EXP_BARE)

    fresher_quote = None
    fresher_match = EXP_FRESHER.search(normalised)
    if fresher_match:
        fresher_quote = _source_quote(
            text, offsets, fresher_match.start(), fresher_match.end())
    return requirements, generics, fresher_quote


# Description eligibility gates. These are the single source of truth for both
# sweep.py and read_url.py. Every extractor returns source wording as evidence.
_YEAR = r"20(?:2[0-9]|3[0-5])"
BATCH_YEAR = re.compile(r"(?:"
    r"(?P<year_list>" + _YEAR + r"(?:\s*(?:/|&|and|,)\s*" + _YEAR + r")*)\s*batch\b|"
    r"(?P<range_start>" + _YEAR + r")\s*[-–—]\s*(?P<range_end>" + _YEAR + r")\s*batch\b|"
    r"batch\s+of\s+(?P<batch_of>" + _YEAR + r")\b|"
    r"(?:year\s+of\s+graduation|yop|graduating\s+in|pass(?:out|ing\s+out)(?:\s+in)?)\s*[:#-]?\s*(?P<label_year>" + _YEAR + r")\b"
    r")", re.I)
DEGREE = re.compile(r"(?<![A-Za-z0-9])(?:B\.?\s*Tech|B\.?\s*E\.?|BCA|MCA|B\.?Sc\.?|M\.?Tech|MBA|Ph\.?D\.?|Bachelor[’']?s|Master[’']?s)(?![A-Za-z0-9])", re.I)
ENROLLED = re.compile(r"\b(?:currently\s+enrolled|must\s+be\s+a\s+student|final\s+year\s+student(?:s)?|currently\s+pursuing|pursuing|in\s+your\s+final\s+year)\b", re.I)


def batch_years_of(text: str) -> Tuple[List[int], str]:
    years, quotes = [], []
    for match in BATCH_YEAR.finditer(text or ""):
        start, end = match.group("range_start"), match.group("range_end")
        if start and end:
            values = range(int(start), int(end) + 1) if int(start) <= int(end) else ()
        elif match.group("year_list"):
            values = (int(y) for y in re.findall(_YEAR, match.group("year_list")))
        else:
            value = match.group("batch_of") or match.group("label_year")
            values = (int(value),) if value else ()
        for year in values:
            if 2020 <= year <= 2035 and year not in years:
                years.append(year)
        quotes.append(match.group(0))
    return sorted(years), "; ".join(quotes)


def _normalise_degree(value: str) -> str:
    key = re.sub(r"\s+", "", value.lower().replace("’", "'"))
    return {"b.tech": "B.Tech", "btech": "B.Tech", "b.e.": "B.E.", "be": "B.E.", "bca": "BCA", "mca": "MCA", "b.sc": "B.Sc", "bsc": "B.Sc", "m.tech": "M.Tech", "mtech": "M.Tech", "mba": "MBA", "ph.d.": "PhD", "phd": "PhD", "bachelor's": "Bachelor's", "bachelors": "Bachelor's", "master's": "Master's", "masters": "Master's"}.get(key, value)


def degrees_of(text: str) -> Tuple[List[str], str]:
    values, quotes = [], []
    for match in DEGREE.finditer(text or ""):
        if match.group(0) == "be":
            continue
        value = _normalise_degree(match.group(0))
        if value not in values:
            values.append(value)
        quotes.append(match.group(0))
    return values, "; ".join(quotes)


degree_of = degrees_of


def enrolled_of(text: str) -> Tuple[bool, str]:
    match = ENROLLED.search(text or "")
    return bool(match), match.group(0) if match else ""


@dataclass
class Resolution:
    stage_resolved: str
    experience_min: Optional[float]
    experience_max: Optional[float]
    experience_conflict: bool
    evidence: Dict[str, str]
    source: str
    batch_years: List[int] = field(default_factory=list)
    degree_required: List[str] = field(default_factory=list)
    enrolled_required: Optional[bool] = None


def resolve_stage(stage_title: str, description: Optional[str],
                  title: str = "") -> Resolution:
    """Enrich the title stage without ever mutating the title-only verdict."""
    if not description or not description.strip():
        return Resolution(stage_title, None, None, False, {}, "no_description")

    batch_years, batch_quote = batch_years_of(description)
    degree_required, degree_quote = degrees_of(description)
    enrolled_required, enrolled_quote = enrolled_of(description)
    requirements, generics, fresher_quote = experience_signals(description)
    evidence: Dict[str, str] = {}
    if batch_quote:
        evidence["batch_years"] = batch_quote
    if degree_quote:
        evidence["degree"] = degree_quote
    if enrolled_quote:
        evidence["enrolled"] = enrolled_quote
    for index, signal in enumerate(requirements, 1):
        key = "experience_requirement" if index == 1 else \
            "experience_requirement_{}".format(index)
        evidence[key] = signal[2]
    for index, signal in enumerate(generics, 1):
        key = "experience_generic" if index == 1 else \
            "experience_generic_{}".format(index)
        evidence[key] = signal[2]
    if fresher_quote:
        evidence["fresher"] = fresher_quote

    req_mins = [signal[0] for signal in requirements]
    req_maxes = [signal[1] for signal in requirements
                 if signal[1] is not None]
    # A single requirement is one unambiguous signal, even when its range
    # crosses the three-year boundary. Conflict requires either a fresher
    # signal alongside a 3+ minimum, or multiple distinct requirements whose
    # minima straddle that boundary.
    mixed_requirement_mins = bool(
        len(requirements) >= 2 and
        min(req_mins) < 3 <= max(req_mins)
    )
    conflict = bool(
        fresher_quote and req_mins and max(req_mins) >= 3
    ) or mixed_requirement_mins

    senior_signal = bool(req_mins) and min(req_mins) >= 3 and not conflict and not fresher_quote
    early_signal = (
        (bool(fresher_quote) and not conflict) or
        (bool(req_mins) and not conflict and max(req_mins) <= 1 and
         not any(maximum is not None and maximum >= 3
                 for maximum in req_maxes))
    )

    if conflict:
        experience_min = experience_max = None
    else:
        experience_min = min(req_mins) if req_mins else None
        experience_max = max(req_maxes) if req_maxes else None

    if stage_title == "senior":
        resolved = "senior"
    elif senior_signal and not EARLY_OVERRIDE.search(title or ""):
        resolved = "senior"
    elif stage_title == "early":
        resolved = "early"
    elif early_signal:
        resolved = "early"
    else:
        resolved = "unknown"

    source = "description" if (requirements or generics or fresher_quote or
                                batch_years or degree_required or enrolled_quote) else "no_signal"
    return Resolution(resolved, experience_min, experience_max, conflict,
                      evidence, source, batch_years, degree_required,
                      enrolled_required if enrolled_quote else None)


# Canonical hidden reasons keep the report stable when classifier wording changes.
HIDDEN_SENIOR = "senior"
HIDDEN_EXPERIENCE = "experience_3plus"
HIDDEN_NOT_INDIA = "not_india"            # retained for back-compat; no longer produced
HIDDEN_REGION_EXCLUDED = "region_excludes_india"
HIDDEN_NON_TECHNICAL = "non_technical"
HIDDEN_NO_TITLE = "no_title"

# Eligibility status describes whether the POSTING STATES ITS RULES. It has
# nothing to do with whether we trust the source; trust stays a separate axis.
ELIG_CONFIRMED = "confirmed"
ELIG_RULES_UNCLEAR = "rules_unclear"
ELIG_HIDDEN = "hidden"

ELIGIBILITY_GATES = [
    "experience", "fresher", "stage_early", "batch_years", "degree", "enrolled",
]


def eligibility_status(hidden_reason_value, gates_found) -> str:
    """Classify whether a kept posting states any eligibility rules."""
    if hidden_reason_value is not None:
        return ELIG_HIDDEN
    if gates_found:
        return ELIG_CONFIRMED
    return ELIG_RULES_UNCLEAR


def gates_of(resolution, stage_title, title) -> Tuple[List[str], List[str]]:
    """Return stated eligibility gates and the gates not yet found."""
    del title  # Reserved for later title-based eligibility gates.
    found: List[str] = []
    if (resolution.experience_min is not None or
            resolution.experience_max is not None):
        found.append("experience")
    if "fresher" in resolution.evidence:
        found.append("fresher")
    if stage_title == "early":
        found.append("stage_early")
    if resolution.batch_years:
        found.append("batch_years")
    if resolution.degree_required:
        found.append("degree")
    if resolution.enrolled_required is True:
        found.append("enrolled")
    missing = [gate for gate in ELIGIBILITY_GATES if gate not in found]
    return found, missing


def hidden_reason(stage_resolved: str, bucket: str, technical: Optional[bool],
                  experience_min: Optional[float] = None,
                  discipline: Optional[str] = None,
                  is_internship: bool = False) -> Optional[str]:
    # Location no longer hides a row: non-India roles are kept in the index and
    # ranked by accessibility() instead. Region-excluded remote is handled
    # upstream in classify() and routed out of the default feed there.
    if stage_resolved == "senior":
        return HIDDEN_SENIOR
    if experience_min is not None and experience_min >= 3:
        return HIDDEN_EXPERIENCE
    if is_internship:
        # Internships launch targets a software/CS/data audience. Surface a
        # row only when the title is affirmatively technical and not another
        # engineering branch. Marketing, ambassador, ops, civil/mechanical,
        # or no technical signal at all are retained but not surfaced.
        if not (technical is True and discipline not in (OTHER_ENG_D, NON_TECH)):
            return HIDDEN_NON_TECHNICAL
        return None
    if technical is False and discipline == NON_TECH:
        return HIDDEN_NON_TECHNICAL
    return None


def canonical_reason(verdict_reason: str) -> str:
    return {
        "senior_title": HIDDEN_SENIOR,
        "remote_region_excludes_india": HIDDEN_REGION_EXCLUDED,
        "no_title": HIDDEN_NO_TITLE,
    }.get(verdict_reason, verdict_reason)


# --------------------------------------------------------------------------- #
# Verdict
# --------------------------------------------------------------------------- #
@dataclass
class Verdict:
    keep: bool
    stage: str          # early | senior | unknown
    technical: Optional[bool]
    bucket: str
    reason: str = ""
    # True when the title alone cannot decide relevance and the description is
    # required. Distinct from technical=None: None means "no signal found",
    # needs_description means "we know why there is no signal".
    needs_description: bool = False
    # cse | other_eng | non_tech | unknown — what the beta filters on.
    discipline: str = UNKNOWN_D
    is_internship: bool = False


def technical_of(title: str) -> Optional[bool]:
    """True / False / None for 'is this relevant to a B.Tech student'.

    Order matters. A role noun like "recruiter" or "chef" decides the job even
    when a technical adjective sits in front of it, so STRONG_NON_TECHNICAL is
    checked first. Without that, "Intern - Technical Recruitment" reads as
    engineering.
    """
    t = title or ""
    if STRONG_NON_TECHNICAL.search(t):
        return False
    if TECHNICAL.search(t):
        return True
    if NON_TECHNICAL.search(t):
        return False
    return None


def stage_of(title: str) -> str:
    """Return early, unknown, or senior from the title alone."""
    t = (title or "").strip()
    if MEMBER_TECHNICAL_STAFF.search(t):
        # Exempt the bare India IC title, but still honour an explicit level or
        # senior marker outside the phrase; the phrase itself must not imply it.
        if MTS_SENIOR_LEVEL.search(t):
            return "senior"
        remainder = MEMBER_TECHNICAL_STAFF.sub(" ", t)
        if SENIOR.search(remainder) and not EARLY_OVERRIDE.search(t):
            return "senior"
        return "early" if EARLY.search(t) or EARLY_LEVEL.search(t) else "unknown"

    is_early = bool(EARLY.search(t) or EARLY_LEVEL.search(t))
    # An explicit intern/trainee word beats a seniority word: "Intern Manager,
    # Growth" is an internship, and "Senior" never co-occurs legitimately.
    if SENIOR.search(t) and not EARLY_OVERRIDE.search(t):
        return "senior"
    return "early" if is_early else "unknown"


def classify(title: str, location: str = "", include_maybe: bool = True,
             india_source: bool = False) -> Verdict:
    """Decide from title + location alone. Cheap, deterministic, explainable.

    ``include_maybe`` remains accepted for callers of the old API. Junior and
    associate markers are now explicit early-stage signals, so there is no
    separate maybe stage to exclude. ``india_source`` enables India-first
    handling for unspecified locations from sources such as Unstop and Keka.
    """
    del include_maybe
    t = (title or "").strip()
    bucket = location_bucket(location, india_source)
    internship = bool(EARLY_OVERRIDE.search(t))

    if not t:
        return Verdict(False, "unknown", None, bucket, "no_title",
                       is_internship=internship)

    stage = stage_of(t)
    if stage == "senior":
        return Verdict(False, stage, None, bucket, "senior_title",
                       is_internship=internship)

    tech = technical_of(t)
    bare = bool(BARE_TITLE.match(t))
    disc = discipline_of(t)
    if disc == NON_TECH and tech is True:
        tech = False

    if bucket == EXCLUDED:
        return Verdict(False, stage, tech, bucket, "remote_region_excludes_india",
                       discipline=disc, is_internship=internship)

    # Unknown-stage technical titles are deliberately kept: a plain "Software
    # Engineer" is exactly the India fresher case this classifier must recover.
    return Verdict(True, stage, tech, bucket, "ok",
                   needs_description=bare or disc == UNKNOWN_D,
                   discipline=disc, is_internship=internship)


if __name__ == "__main__":
    # The test set is the real rejection log plus real finds from the sweeps,
    # extended on 2026-07-31 with the titles that the 54%-unclassified audit
    # turned up. Each case asserts (keep, technical, needs_description) so a
    # regression in the technical split fails the run, not just a keep/reject
    # flip — the previous 22-case set only checked keep, which is exactly why
    # 659 unclassified rows went unnoticed.
    N = None
    cases = [
        # (title, location, keep, technical, needs_description)
        # --- career stage + technical, the target of the whole product ---
        ("SDE-Intern", "Bangalore", True, True, False),
        ("Software Development Engineer- Trainee (Compilers)", "Bangalore", True, True, False),
        # Discipline-blind: TECHNICAL matches "engineer", but which branch is
        # unknowable from the title, so the row is flagged for the description
        # pass rather than shown to a CSE student as a match.
        ("Graduate Engineer Trainee", "Bengaluru", True, True, True),
        ("Fresher - Software Development Engineer", "Mumbai", True, True, False),
        ("Software Engineering Intern", "Pune", True, True, False),
        ("Intern - Generative AI", "Gurugram", True, True, False),
        ("Werkstudent Software Engineering", "Berlin", True, True, False),
        # --- the two real TECHNICAL stemming gaps found in the audit ---
        ("Intern - Quality and Testing", "Noida Uttar Pradesh UP", True, True, False),
        ("Technical Trainee", "Bengaluru, KA, IN Bengaluru KA", True, True, False),
        # --- technical adjective, non-technical job: STRONG_NON_TECHNICAL wins ---
        ("Intern - Technical Recruitment", "Bengaluru", True, False, False),
        ("Technical Trainer Intern-2026", "Bengaluru", True, False, False),
        ("Associate Trainee - US IT Recruiter", "Indore Indore MP", True, False, False),
        ("Internship Position - Technical Customer Service", "Remote", True, False, False),
        # --- non-technical roles that were unclassified before ---
        ("Junior Chef - Sushi - 5-Star Luxury Hotel", "Athens", True, False, False),
        ("Plumbing Apprentice", "Texas", True, False, False),
        ("New Graduate Physiotherapist", "Sydney", True, False, False),
        ("Junior Accountant", "Softobiz Mohali Mohali PB", True, False, False),
        ("Telecalling Intern", "Bhopal Bhopal MP", True, False, False),
        ("Junior Executive - Horticulture", "NCR GURUGRAM HR", True, False, False),
        ("Jr Motion Designer", "Bengaluru Bengaluru KA", True, False, False),
        ("Automotive Apprenticeship for Military Veterans - Flow Kia", "NC", True, False, False),
        ("Trainee Pharmacist", "London", True, False, False),
        ("Junior FX Artist", "Bangalore", True, False, False),
        # --- bare titles: kept, but flagged, never counted as technical ---
        ("Intern", "Gurgaon Gurgaon HR", True, N, True),
        ("Trainee", "Corporate Office Anand, Gujarat GJ", True, N, True),
        ("Internship", "Mumbai MH", True, N, True),
        ("Campus Hiring 2025", "Bangalore Bangalore", True, N, True),
        ("Junior Executive", "Mumbai Maharashtra", True, N, True),
        ("Management Trainee", "Kolkata Kolkata WB", True, N, True),
        # --- seniority rejections ---
        ("Senior Software Engineer II", "Bangalore", False, N, False),
        ("SDE III - Data Engineering", "Bangalore", False, N, False),
        ("Staff Fullstack Engineer", "Bangalore", False, N, False),
        ("Managing Counsel, Commercial - Partnerships", "Remote-Iberia", False, N, False),
        ("Payroll Specialist Lead - Belgium", "Remote-DACH", False, N, False),
        ("Ecosystem Sales Manager: Scale", "Remote", False, N, False),
        ("Site Reliability Engineer (4 to 8 Years)", "Bangalore", False, N, False),
        ("Software Engineer - Synthetic Monitoring", "Sweden (Remote)", True, True, False),
        ("Product Manager", "Bengaluru", False, N, False),
    ]
    fails = 0
    for title, loc, want_keep, want_tech, want_nd in cases:
        v = classify(title, loc)
        # technical is only asserted on rows we keep; a rejected row's technical
        # value is deliberately not meaningful.
        ok = v.keep == want_keep and v.needs_description == want_nd
        if want_keep:
            ok = ok and v.technical == want_tech
        fails += 0 if ok else 1
        print(
            "{} {:<58} keep={:<5} tech={:<5} bare={:<5} {}".format(
                "PASS" if ok else "FAIL",
                title[:58],
                str(v.keep),
                str(v.technical),
                str(v.needs_description),
                v.reason,
            )
        )
    print("\n{} / {} passed".format(len(cases) - fails, len(cases)))

    # ---------------------------------------------------------------------- #
    # Three-way stage classifier test set. Every case is explicitly India so
    # the location gate cannot mask a stage regression.
    # ---------------------------------------------------------------------- #
    print("\n--- stage (India) ---")
    stage_cases = [
        ("Associate Software Engineer", "early"),
        ("Graduate Engineer Trainee", "early"),
        ("Trainee Engineer", "early"),
        ("SDE-1", "early"),
        ("SDE I", "early"),
        ("Software Development Engineer I", "early"),
        ("Software Engineer I", "early"),
        ("Junior Backend Developer", "early"),
        ("SDE I Intern , Amazon University Talent Acquisition", "early"),
        ("Software Engineer", "unknown"),
        ("Software Development Engineer", "unknown"),
        ("Backend Engineer", "unknown"),
        ("Member of Technical Staff", "unknown"),
        ("Staff Data Privacy Engineer", "senior"),
        ("Staff Machine Learning Engineer", "senior"),
        ("Senior Member of Technical Staff", "senior"),
        ("Member of Technical Staff - 2", "senior"),
        ("Kitchen Staff", "unknown"),
        ("Escalation Engineer", "unknown"),
        ("Solutions Engineer", "unknown"),
        ("Systems Engineer", "unknown"),
        ("IT Business Application Engineer", "unknown"),
        ("Analyst Risk Management", "unknown"),
        ("Full Stack Builder", "unknown"),
        ("Low Latency Developer", "unknown"),
        ("Analyst - Technology", "unknown"),
        ("Software Engineer (0-2 years)", "unknown"),
        ("Senior Software Engineer", "senior"),
        ("Staff Engineer", "senior"),
        ("SDE II", "senior"),
        ("Engineering Manager", "senior"),
        ("Principal Architect", "senior"),
        ("Software Engineer III", "senior"),
    ]
    sfails = 0
    for title, want in stage_cases:
        v = classify(title, "India")
        ok = v.stage == want and v.keep == (want != "senior")
        sfails += 0 if ok else 1
        print("{} {:<58} stage={:<7} keep={}".format(
            "PASS" if ok else "FAIL", title[:58], v.stage, v.keep))
    print("\n{} / {} passed".format(len(stage_cases) - sfails, len(stage_cases)))

    # ---------------------------------------------------------------------- #
    # Discipline test set. Every title below is a real row from the lake.
    # ---------------------------------------------------------------------- #
    print("\n--- discipline (B.Tech CSE beta scope) ---")
    disc_cases = [
        # real CSE
        ("SDE-Intern", CSE),
        ("Software Development Engineer- Trainee (Compilers)", CSE),
        ("Jr Mobile Developer iOS", CSE),
        ("Junior Data Engineer", CSE),
        ("Jr. DevOps Engineer", CSE),
        ("Data Science Intern", CSE),
        ("Intern Network Engineer (Onsite) – Goa", CSE),
        ("Application Security (AppSec) – Security Analyst (Freshers)", CSE),
        ("DevSecOps Associate - Source Code Review Security", CSE),
        ("Quantitative Developer Intern", CSE),
        ("Junior .NET developer", CSE),
        ("Associate System Engineer", CSE),
        ("Quality Assurance (QA) Intern - WIP", CSE),
        ("Technical Trainee", CSE),
        ("Software Development Engineer I, Backend", CSE),
        # "AI"/"technical" as a marketing adjective — the biggest false positive
        ("AI Prompt Associate – Brand Content", NON_TECH),
        ("Gen AI Creative Marketing Manager -Intern", NON_TECH),
        ("Gen AI  Designer- Intern", NON_TECH),
        ("AI Video Editor & Content Creator Intern - WIP", NON_TECH),
        ("Associate Technical Artist - Intern", NON_TECH),
        ("Intern – Content Writer (Technical) - Goa", NON_TECH),
        ("Data Annotation Intern", NON_TECH),
        # technical-adjacent but a different profession entirely
        ("Skincare Research & Development (Lab) Associate", NON_TECH),
        ("Junior Research Scientist CDMO", NON_TECH),
        ("Associate Financial Analyst", NON_TECH),
        ("Consultant - Jr. Oracle EBS Finance CA/CMA", NON_TECH),
        ("Medical Intern – Health & Technology Internship", NON_TECH),
        ("Compliance Associate / Analyst", NON_TECH),
        # right kind of work, wrong branch
        ("Associate Hardware Design Engineer", OTHER_ENG_D),
        ("0169 Ingeniero Jr CAE - Análisis Estructural y Fatiga", OTHER_ENG_D),
        ("Junior AMO Physicist", OTHER_ENG_D),
        ("Integrated Photonics Summer PhD Intern", OTHER_ENG_D),
        ("Trainee - Production", OTHER_ENG_D),
        # genuinely undecidable from the title — must go to the description pass
        ("Graduate Engineer Trainee", UNKNOWN_D),
        ("Jr. Engineer", UNKNOWN_D),
        ("Junior Engineer", UNKNOWN_D),
        ("Intern", UNKNOWN_D),
        ("Campus Hiring 2025", UNKNOWN_D),
        ("Intern - Product", UNKNOWN_D),
        ("Associate Business Analyst", UNKNOWN_D),
        ("Fraud Analyst", NON_TECH),
        ("Fraud Risk Analyst", NON_TECH),
        ("Fraud Analyst - Customer Experience", NON_TECH),
        ("Credit Risk Analyst", NON_TECH),
        ("VOC - Research Executive", NON_TECH),
        ("Research Executive", NON_TECH),
        ("Escalation Engineer", NON_TECH),
        ("IT Business Application Engineer", NON_TECH),
        ("Solutions Engineer", NON_TECH),
        ("Analyst Risk Management", NON_TECH),
        ("Systems Engineer", UNKNOWN_D),
        ("Full Stack Builder", CSE),
        ("Low Latency Developer", CSE),
    ]
    dfails = 0
    for title, want in disc_cases:
        got = discipline_of(title)
        ok = got == want
        dfails += 0 if ok else 1
        print("{} {:<58} {:<10} (want {})".format(
            "PASS" if ok else "FAIL", title[:58], got, want))
    print("\n{} / {} passed".format(len(disc_cases) - dfails, len(disc_cases)))

    # ---------------------------------------------------------------------- #
    # Description experience resolver. It enriches rows but never mutates the
    # title-only stage used by the cheap filter.
    # ---------------------------------------------------------------------- #
    print("\n--- experience resolver ---")
    experience_cases = [
        # (description, stage title, posting title, resolved, min, conflict)
        ("5+ years of experience required", "unknown", "", "senior", 5, False),
        ("Minimum 3 years of experience with Java.", "unknown", "", "senior", 3, False),
        ("Experience: 2-4 years", "unknown", "", "unknown", 2, False),
        ("Requires 1-3 years of experience", "unknown", "", "unknown", 1, False),
        ("Requires 6-10 years of experience", "unknown", "", "senior", 6, False),
        ("0-2 years of experience", "unknown", "", "early", 0, False),
        ("We welcome freshers and final-year students.", "unknown", "", "early", None, False),
        ("We build reliable software for customers.", "unknown", "", "unknown", None, False),
        (None, "unknown", "", "unknown", None, False),
        ("8+ years of experience required", "early", "", "senior", 8, False),
        ("8+ years of hands-on experience", "early", "Software Engineer I", "senior", 8, False),
        ("8+ years of hands-on experience", "early", "Software Engineering Intern", "early", 8, False),
        ("We welcome freshers", "senior", "", "senior", None, False),
        ("Our company has grown a lot over the past 5 years.", "unknown", "", "unknown", None, False),
        ("We support 5 years of product warranty", "unknown", "", "unknown", None, False),
        ("Open to freshers; senior track requires 6+ years of experience", "unknown", "", "unknown", None, True),
        ("At least 1 year of experience", "unknown", "", "early", 1, False),
        ("3+ years experience", "unknown", "", "senior", 3, False),
    ]
    rfails = 0
    for description, stage_in, title_in, want_stage, want_min, want_conflict in experience_cases:
        resolution = resolve_stage(stage_in, description, title_in)
        ok = (resolution.stage_resolved == want_stage and
              resolution.experience_min == want_min and
              resolution.experience_conflict == want_conflict)
        rfails += 0 if ok else 1
        print("{} {:<58} resolved={:<7} min={} conflict={}".format(
            "PASS" if ok else "FAIL",
            str(description)[:58], resolution.stage_resolved,
            resolution.experience_min, resolution.experience_conflict))
    print("\n{} / {} passed".format(len(experience_cases) - rfails,
                                  len(experience_cases)))

    # ---------------------------------------------------------------------- #
    # Eligibility status: stated rules are separate from source trust.
    # ---------------------------------------------------------------------- #
    print("\n--- eligibility status ---")
    eligibility_cases = [
        # (title, location, description, wanted gates, wanted status, reason)
        ("Full Stack Builder", "India", None, [], ELIG_RULES_UNCLEAR, None),
        ("SDE-1", "India", None, ["stage_early"], ELIG_CONFIRMED, None),
        ("Software Engineer", "India", "0-2 years of experience",
         ["experience"], ELIG_CONFIRMED, None),
        ("Software Engineer", "India", "We welcome freshers",
         ["fresher"], ELIG_CONFIRMED, None),
        ("Software Engineer", "India", "Requires 8+ years of experience",
         ["experience"], ELIG_HIDDEN, HIDDEN_SENIOR),
        ("Senior Software Engineer", "India", None,
         [], ELIG_HIDDEN, HIDDEN_SENIOR),
        ("Software Engineer", "Germany", None,
         [], ELIG_HIDDEN, HIDDEN_NOT_INDIA),
    ]
    efails = 0
    for title, location, description, want_gates, want_status, want_reason in eligibility_cases:
        verdict = classify(title, location)
        resolution = resolve_stage(verdict.stage, description, title)
        gates_found, gates_missing = gates_of(resolution, verdict.stage, title)
        reason = hidden_reason(
            resolution.stage_resolved, verdict.bucket, verdict.technical,
            resolution.experience_min, verdict.discipline)
        got_status = eligibility_status(reason, gates_found)
        gates_ok = (gates_found == want_gates if not want_gates else
                    all(gate in gates_found for gate in want_gates))
        ok = (gates_ok and got_status == want_status and
              reason == want_reason and
              gates_missing == [gate for gate in ELIGIBILITY_GATES
                                if gate not in gates_found])
        efails += 0 if ok else 1
        print("{} {:<58} gates={} status={} reason={}".format(
            "PASS" if ok else "FAIL", title[:58], gates_found,
            got_status, reason))
    print("\n{} / {} passed".format(len(eligibility_cases) - efails,
                                  len(eligibility_cases)))

    # ---------------------------------------------------------------------- #
    # Description gate extraction. Quotes are verbatim evidence and ranges
    # expand only within the guarded 2020..2035 year window.
    # ---------------------------------------------------------------------- #
    print("\n--- eligibility gate extraction ---")
    gate_cases = [
        ("2027 batch", [2027], [], False),
        ("Year of Graduation: 2027", [2027], [], False),
        ("2025-2027 batch", [2025, 2026, 2027], [], False),
        ("passout 2026", [2026], [], False),
        ("B.Tech/B.E. in Computer Science", [], ["B.Tech", "B.E."], False),
        ("must be currently enrolled", [], [], True),
        ("No graduation window is stated", [], [], False),
    ]
    gfails = 0
    for text, want_years, want_degrees, want_enrolled in gate_cases:
        years, _ = batch_years_of(text)
        degrees, _ = degrees_of(text)
        enrolled, _ = enrolled_of(text)
        ok = years == want_years and degrees == want_degrees and enrolled == want_enrolled
        gfails += 0 if ok else 1
        print("{} {:<58} years={} degrees={} enrolled={}".format(
            "PASS" if ok else "FAIL", text[:58], years, degrees, enrolled))
    print("\n{} / {} passed".format(len(gate_cases) - gfails, len(gate_cases)))

    raise SystemExit(1 if (fails or sfails or dfails or rfails or efails or gfails) else 0)
