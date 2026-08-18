"""Build page-reader fixtures from real careers pages.

    python3 build_fixtures.py fetch <url> [<url> ...]   save the page + its text
    python3 build_fixtures.py show <url>                print the text to read
    python3 build_fixtures.py check                     run every fixture

The workflow is deliberately manual, because the fixtures are the ground truth
and ground truth is not something to generate. Fetch the page, READ the text,
write what a correct extractor should return into
fixtures/extract_<key>.json by hand.

Half the fixtures should be pages with NO jobs on them. Those are the ones that
matter: a model handed a JavaScript shell invents plausible postings, and the
negative fixtures are the only test that catches it.

Saved pages live in fixtures/pages/ and are committed, so the suite is
reproducible offline and a page changing under us cannot silently alter a test.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Optional

from adapters import extractors
from core import pagetext, robots
from core.paths import FIXTURES_DIR
from pipeline.resolve import _fetch_page

FIXTURES = FIXTURES_DIR
PAGES = os.path.join(FIXTURES, "pages")


def page_path(url: str) -> str:
    return os.path.join(PAGES, "page_{}.html".format(extractors.fixture_key(url)))


def meta_path(url: str) -> str:
    return os.path.join(PAGES, "page_{}.meta.json".format(extractors.fixture_key(url)))


def fetch(url: str) -> Optional[str]:
    allowed, why = robots.allowed(url)
    if not allowed:
        print("  SKIP {}  robots: {}".format(url, why))
        return None
    status, final_url, html, err = _fetch_page(url)
    if not html:
        print("  FAIL {}  status={} err={}".format(url, status, err))
        return None
    os.makedirs(PAGES, exist_ok=True)
    with open(page_path(url), "w") as fh:
        fh.write(html)
    text = pagetext.to_text(html)
    with open(meta_path(url), "w") as fh:
        json.dump({
            "url": url,
            "final_url": final_url,
            "status": status,
            "raw_chars": len(html),
            "text_chars": len(text),
            "content_hash": pagetext.content_hash(html),
            "key": extractors.fixture_key(url),
        }, fh, indent=1)
    print("  OK   {}\n       key={} raw={:,} text={:,}".format(
        url, extractors.fixture_key(url), len(html), len(text)))
    return html


def show(url: str, limit: int = 6000) -> None:
    p = page_path(url)
    if not os.path.exists(p):
        print("not fetched yet: {}".format(url))
        return
    html = open(p, encoding="utf-8", errors="replace").read()
    text = pagetext.to_text(html)
    print("=" * 78)
    print("{}\nkey={}  raw={:,}  text={:,}".format(
        url, extractors.fixture_key(url), len(html), len(text)))
    print("=" * 78)
    print(text[:limit])


def check() -> int:
    """Run FixtureExtractor over every saved page and enforce the quote rule."""
    if not os.path.isdir(PAGES):
        print("no fixtures yet")
        return 0
    ex = extractors.FixtureExtractor()
    failures = 0
    metas = sorted(f for f in os.listdir(PAGES) if f.endswith(".meta.json"))
    print("{:<52} {:>6} {:>6} {:>9}".format("url", "roles", "drop", "verdict"))
    print("-" * 78)
    for m in metas:
        meta = json.load(open(os.path.join(PAGES, m)))
        url = meta["url"]
        html = open(page_path(url), encoding="utf-8", errors="replace").read()
        text = pagetext.to_text(html)
        res = ex.extract(html, url)
        if res.error:
            print("{:<52} {:>6} {:>6} {:>9}  {}".format(
                url[:52], "-", "-", "ERROR", res.error))
            failures += 1
            continue
        before = len(res.roles)
        extractors.enforce_quotes(res, text)
        verdict = "ok" if len(res.roles) == before else "UNQUOTED"
        if len(res.roles) != before:
            failures += 1
        print("{:<52} {:>6} {:>6} {:>9}".format(
            url[:52], len(res.roles), res.discarded_unquoted, verdict))
    print()
    print("{} fixture(s), {} failure(s)".format(len(metas), failures))
    return failures


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(2)
    cmd = sys.argv[1]
    if cmd == "fetch":
        for u in sys.argv[2:]:
            fetch(u)
    elif cmd == "show":
        show(sys.argv[2])
    elif cmd == "check":
        raise SystemExit(1 if check() else 0)
    else:
        print(__doc__)
        raise SystemExit(2)
