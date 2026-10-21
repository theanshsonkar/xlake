"""Deterministic STEM classifier for programme rows (no LLM, stdlib only)."""
from __future__ import annotations

import re
from typing import Dict

_STEM = re.compile(
    r"\b(stem|computer science|computing|software|programming|coding|developers?|"
    r"artificial intelligence|machine learning|deep learning|ai|data science|data|"
    r"cyber ?security|security research|blockchain|cryptograph\w*|quantum|robotics|"
    r"engineering|engineers?|technolog\w*|tech|digital|open[- ]source|"
    r"physics|physicists?|chemistry|chemical|maths?|mathematics|mathematical|statistics|"
    r"biology|biological|biotech\w*|bioinformatics|life sciences?|genomics?|neuroscience|"
    r"medicine|biomedical|materials?|nanotech\w*|geoscience|earth science|astronomy|"
    r"astrophysics|space|climate science|sciences?|scientists?|scientific|"
    r"quantitative|quant|startups?|deep ?tech|hardware|semiconductors?|"
    r"research(?:ers)? in (?:science|engineering)|"
    r"reu|surf|urop|iit|iiser|iisc|iiit|institute of technology|polytechni\w*|embl|embo|riken|"
    r"laborator\w*|observatory|mitacs|kaust|caltech|nvidia|microsoft|ibm|cohere|hackny|"
    r"y combinator|8vc|entrepreneur first|vector institute|kde|dissertation|sigkdd|ieee|acm|"
    r"google|two sigma|citadel|mlh|major league hacking|mongodb|gnome|linux|github|aws|docker|"
    r"matplotlib|kubernetes|ethereum|rust|outreachy|lfx|risc-v|sktime|numfocus|openssf|eic|"
    r"cifar|amgen|eth zurich|epfl|snap|norton|cnie?o|ipam|icts|hzdr|esrf|max planck|mpi|"
    r"fulbright|marie (?:sk[lł]odowska[- ])?curie|msca|erc|nsf|nih|cern|nasa|esa)\b",
    re.I,
)

_NON_STEM_TITLE = re.compile(
    r"\b(language|languages|arts?|humanities|poetry|literature|music|film|journalism|"
    r"theatre|theater|history|policy|public service|diplomacy|law|legal|"
    r"religio\w*|theology|dance|photography|writing|writers?)\b",
    re.I,
)

_JUNK = re.compile(
    r"^\s*(?:[|>#]|:\w+:|apply\b|read\b|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.? \d)"
    r"|\|\s*-{3}|## |\u2192|:warning:|\|\s*(?:TechCrunch|The Verge|Wired|Forbes|Reuters|Bloomberg|"
    r"VentureBeat|Medium|[A-Z][A-Za-z ]{2,20}) ?\u203a?\s*$",
    re.I,
)
# Categories whose rows are tech/science by definition.
_STEM_CATEGORIES = ("research", "open-source")
# Programmes that are STEM although the title has no keyword.
_STEM_TITLE_EXTRA = re.compile(
    r"\b(hertz|isternship|renewable|hollings|noaa|wellcome|icar|aicte|agricultur\w*|ebpf|women techmakers|"
    r"mit graduate|google research)\b", re.I)


def is_junk_title(title: str) -> bool:
    return bool(_JUNK.search(str(title or "")))


def is_stem_programme(row: Dict) -> bool:
    """True when title, stored text and organiser point to a STEM field."""
    title = " ".join(str(row.get(k) or "") for k in ("title", "programme_name"))
    if is_junk_title(title):
        return False
    if _STEM.search(title) or _STEM_TITLE_EXTRA.search(title):
        return True
    if _NON_STEM_TITLE.search(title):
        return False
    if str(row.get("category") or "").startswith(_STEM_CATEGORIES):
        return True
    body = " ".join(str(row.get(k) or "") for k in (
        "summary", "description", "organizer", "company", "requirements", "eligibility", "covers"))
    return len(_STEM.findall(body)) >= 2
