"""Recognise ATS job boards in crawled URLs by reusing the resolver's URL parsing.

No host lists live here: pipeline.resolve already knows which ATS URLs map to which
(platform, token). The crawler only reports what it saw; admission is
pipeline.admit_boards, and the crawler never edits the board registry.
"""

from __future__ import annotations

from typing import Dict, Iterable, Optional

from pipeline.resolve import _scan  # private on purpose: reuse, never duplicate the patterns

# Not usable without extra context the crawler does not have (Eightfold needs the
# company's own domain; SuccessFactors is detected from page assets, not URLs).
_SKIP = {"eightfold", "successfactors"}


def board_of(url: str) -> Optional[Dict[str, str]]:
    """Return {platform, token, url} when `url` is a recognised ATS board URL."""
    if not url or not url.startswith(("http://", "https://")):
        return None
    platform, token, _ = _scan("", url)
    if not platform or not token or platform in _SKIP:
        return None
    return {"platform": platform, "token": token, "url": url}


class BoardCollector:
    """Dedupes boards by (platform, token); keeps the first source page and date."""

    def __init__(self, today):
        self.today = today.isoformat()
        self.found: Dict[tuple, Dict[str, str]] = {}

    def add(self, page_url: str, links: Iterable[str]) -> None:
        for target in [page_url, *links]:
            b = board_of(target)
            if b is None:
                continue
            key = (b["platform"], b["token"])
            if key not in self.found:
                self.found[key] = {"platform": b["platform"], "token": b["token"],
                                   "url": b["url"], "source_page": page_url,
                                   "first_seen": self.today}

    def rows(self):
        return sorted(self.found.values(), key=lambda r: (r["platform"], r["token"]))
