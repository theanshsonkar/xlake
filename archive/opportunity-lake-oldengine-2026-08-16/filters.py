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
from dataclasses import dataclass
from typing import Optional

# --------------------------------------------------------------------------- #
# Seniority: reject on title alone
# --------------------------------------------------------------------------- #
# Word-boundary anchored so "Senior" is caught but "Internship" is not damaged.
SENIOR = re.compile(
    r"\b("
    r"senior|sr\.?|staff|principal|lead|leader|head|manager|mgr|director|"
    r"architect|vp|vice\s+president|chief|cto|ceo|cfo|coo|"
    r"specialist\s+iv|expert|fellow\s+engineer|distinguished|"
    r"sde\s*(?:ii|iii|iv|2|3|4)|"
    r"engineer\s*(?:ii|iii|iv|2|3|4)\b|"
    r"level\s*(?:ii|iii|iv|3|4|5)"
    r")\b",
    re.I,
)

# "Manager" inside "Product Manager, Intern" would wrongly reject; these win.
EARLY_OVERRIDE = re.compile(r"\b(intern|internship|trainee|apprentice)\b", re.I)

# --------------------------------------------------------------------------- #
# Career stage: is this for someone with no real experience?
# --------------------------------------------------------------------------- #
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

# Junior/Associate are ambiguous — often 1-3 years. Kept separate so the caller
# can decide whether to include them, rather than silently mixing them in.
MAYBE_EARLY = re.compile(r"\b(junior|jr\.?|associate|analyst\s*i\b|engineer\s*i\b)\b", re.I)

# "Associate" alone is a seniority word in sales and ops, not a career stage:
# Sales Associate, Account Associate, Operations Associate. Left unqualified it
# made Sales/BD 27% of a sweep aimed at engineering students. So a bare
# "associate" only counts as early-career when the title is also technical.
ASSOCIATE_ONLY = re.compile(r"\bassociate\b", re.I)
JUNIOR_STRICT = re.compile(r"\b(junior|jr\.?|analyst\s*i\b|engineer\s*i\b)\b", re.I)

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
REMOTE_ANY = re.compile(r"\b(remote|wfh|work\s+from\s+home|hybrid)\b", re.I)

# Remote restricted to a region that excludes India -> not actionable.
REMOTE_EXCLUDES_INDIA = re.compile(
    r"\b(remote\s*[-–,(]?\s*(us|usa|united\s+states|uk|emea|eu|europe|latam|"
    r"noram|dach|iberia|apac\s+excl|canada|australia|argentina|brazil|mexico|"
    r"south\s+america|north\s+america))\b",
    re.I,
)

INDIA_LOCATED = "india_located"
INDIA_REMOTE = "india_remote"
GLOBAL_HIRING = "global_hiring"
EXCLUDED = "excluded"


def location_bucket(location: str) -> str:
    """Which of the three applicability buckets a posting falls into."""
    loc = (location or "").strip()
    if not loc:
        return GLOBAL_HIRING  # unknown location; needs one confirmation
    if INDIA_RE.search(loc):
        return INDIA_LOCATED
    if REMOTE_OPEN.search(loc):
        return INDIA_REMOTE
    if REMOTE_EXCLUDES_INDIA.search(loc):
        return EXCLUDED
    if REMOTE_ANY.search(loc):
        return GLOBAL_HIRING  # remote, region unstated
    return GLOBAL_HIRING  # overseas onsite; no authorisation bar stated


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
    r"programmer|coder|"
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
    r"network\s+engineer\w*|system\s*s?\s+(?:engineer\w*|administrator|admin)|"
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
    r"sales|business\s+development|growth\s+associate|"
    r"recruit\w*|talent|"
    r"artist"
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
                     r"skincare|lab|pharma\w*|cdmo|medical|clinical)\b", t, re.I):
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
# Verdict
# --------------------------------------------------------------------------- #
@dataclass
class Verdict:
    keep: bool
    stage: str          # early | maybe_early | senior | unknown
    technical: Optional[bool]
    bucket: str
    reason: str = ""
    # True when the title alone cannot decide relevance and the description is
    # required. Distinct from technical=None: None means "no signal found",
    # needs_description means "we know why there is no signal".
    needs_description: bool = False
    # cse | other_eng | non_tech | unknown — what the beta filters on.
    discipline: str = UNKNOWN_D


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


def classify(title: str, location: str = "", include_maybe: bool = True) -> Verdict:
    """Decide from title + location alone. Cheap, deterministic, explainable."""
    t = (title or "").strip()
    bucket = location_bucket(location)

    if not t:
        return Verdict(False, "unknown", None, bucket, "no_title")

    is_early = bool(EARLY.search(t))
    # An explicit intern/trainee word beats a seniority word: "Intern Manager,
    # Growth" is an internship, and "Senior" never co-occurs legitimately.
    if SENIOR.search(t) and not (is_early and EARLY_OVERRIDE.search(t)):
        return Verdict(False, "senior", None, bucket, "senior_title")

    tech = technical_of(t)
    bare = bool(BARE_TITLE.match(t))
    disc = discipline_of(t)

    if is_early:
        stage = "early"
    elif JUNIOR_STRICT.search(t):
        stage = "maybe_early"
    elif ASSOCIATE_ONLY.search(t) and tech is True:
        # "Associate Software Engineer" is plausibly early-career.
        # "Sales Associate" is not a career stage at all.
        stage = "maybe_early"
    else:
        return Verdict(False, "unknown", tech, bucket, "no_early_career_signal",
                       discipline=disc)

    if stage == "maybe_early" and not include_maybe:
        return Verdict(False, stage, tech, bucket, "ambiguous_stage_excluded",
                       discipline=disc)

    if bucket == EXCLUDED:
        return Verdict(False, stage, tech, bucket, "remote_region_excludes_india",
                       discipline=disc)

    # A bare title is kept — it may well be an engineering internship — but it is
    # flagged so it can never be counted as confirmed-technical, and so the
    # description pass knows this row is the reason it exists. A discipline of
    # "unknown" is the same signal from the other direction.
    return Verdict(True, stage, tech, bucket, "ok",
                   needs_description=bare or disc == UNKNOWN_D,
                   discipline=disc)


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
        ("Software Engineer - Synthetic Monitoring", "Sweden (Remote)", False, N, False),
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
    ]
    dfails = 0
    for title, want in disc_cases:
        got = discipline_of(title)
        ok = got == want
        dfails += 0 if ok else 1
        print("{} {:<58} {:<10} (want {})".format(
            "PASS" if ok else "FAIL", title[:58], got, want))
    print("\n{} / {} passed".format(len(disc_cases) - dfails, len(disc_cases)))

    raise SystemExit(1 if (fails or dfails) else 0)
