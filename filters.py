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
TECHNICAL = re.compile(
    r"\b("
    r"software|developer|dev|engineer|engineering|sde|swe|programmer|"
    r"backend|back[\s-]?end|frontend|front[\s-]?end|full[\s-]?stack|"
    r"data|database|analytics|analyst|"
    r"ml|machine\s+learning|ai|artificial\s+intelligence|deep\s+learning|"
    r"nlp|computer\s+vision|llm|generative|"
    r"devops|sre|site\s+reliability|platform|infrastructure|cloud|"
    r"qa|quality\s+assurance|sdet|test|automation|"
    r"android|ios|mobile|web|"
    r"python|java|golang|rust|react|node|"
    r"security|cyber|network|embedded|firmware|hardware|vlsi|"
    r"compiler|systems|robotics|research"
    r")\b",
    re.I,
)

# Explicitly non-technical, so we can report the split honestly rather than
# quietly counting a video-editing internship as an engineering opportunity.
NON_TECHNICAL = re.compile(
    r"\b("
    r"hr|human\s+resource|recruit|talent\s+acquisition|payroll|"
    r"sales|business\s+development|bd|inside\s+sales|telecall|"
    r"marketing|seo|smm|social\s+media|influencer|brand|"
    r"content|copywriter|copy\s+writer|writer|editor|blog|"
    r"video|graphic|design(?:er)?\s|photoshop|illustrator|"
    r"finance|accounts|accounting|audit|taxation|billing|"
    r"customer\s+support|customer\s+success|operations\s+executive|"
    r"legal|counsel|admin|office|reception"
    r")\b",
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
# Verdict
# --------------------------------------------------------------------------- #
@dataclass
class Verdict:
    keep: bool
    stage: str          # early | maybe_early | senior | unknown
    technical: Optional[bool]
    bucket: str
    reason: str = ""


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

    tech: Optional[bool] = None
    if TECHNICAL.search(t):
        tech = True
    elif NON_TECHNICAL.search(t):
        tech = False

    if is_early:
        stage = "early"
    elif JUNIOR_STRICT.search(t):
        stage = "maybe_early"
    elif ASSOCIATE_ONLY.search(t) and tech is True:
        # "Associate Software Engineer" is plausibly early-career.
        # "Sales Associate" is not a career stage at all.
        stage = "maybe_early"
    else:
        return Verdict(False, "unknown", tech, bucket, "no_early_career_signal")

    if stage == "maybe_early" and not include_maybe:
        return Verdict(False, stage, tech, bucket, "ambiguous_stage_excluded")

    if bucket == EXCLUDED:
        return Verdict(False, stage, tech, bucket, "remote_region_excludes_india")

    return Verdict(True, stage, tech, bucket, "ok")


if __name__ == "__main__":
    # The test set is the real rejection log plus real finds from today's sweeps.
    cases = [
        ("SDE-Intern", "Bangalore", True),
        ("Software Development Engineer- Trainee (Compilers)", "Bangalore", True),
        ("Graduate Engineer Trainee", "Bengaluru", True),
        ("Fresher - Software Development Engineer", "Mumbai", True),
        ("Software Engineering Intern", "Pune", True),
        ("Intern - Generative AI", "Gurugram", True),
        ("Werkstudent Software Engineering", "Berlin", True),
        ("Senior Software Engineer II", "Bangalore", False),
        ("SDE III - Data Engineering", "Bangalore", False),
        ("Staff Fullstack Engineer", "Bangalore", False),
        ("Managing Counsel, Commercial - Partnerships", "Remote-Iberia", False),
        ("Payroll Specialist Lead - Belgium", "Remote-DACH", False),
        ("Ecosystem Sales Manager: Scale", "Remote", False),
        ("Site Reliability Engineer (4 to 8 Years)", "Bangalore", False),
        ("Software Engineer - Synthetic Monitoring", "Sweden (Remote)", False),
        ("Product Manager", "Bengaluru", False),
    ]
    fails = 0
    for title, loc, expect in cases:
        v = classify(title, loc)
        ok = v.keep == expect
        fails += 0 if ok else 1
        print(
            "{} {:<52} {:<18} keep={:<5} stage={:<11} tech={:<5} {}".format(
                "PASS" if ok else "FAIL",
                title[:52],
                loc[:18],
                str(v.keep),
                v.stage,
                str(v.technical),
                v.reason,
            )
        )
    print("\n{} / {} passed".format(len(cases) - fails, len(cases)))
    raise SystemExit(1 if fails else 0)
