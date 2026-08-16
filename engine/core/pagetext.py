"""HTML -> plain text, and the hash that decides whether to pay for a model.

Two jobs, and the second one is where the cost discipline lives:

  to_text(html)     flatten a page to the text a reader would see
  content_hash      hash of that text, NOT of the raw HTML

Hashing the text rather than the HTML is the entire saving. Careers pages embed a
build id, a CSRF token, a cache-busting query string and an analytics timestamp
that change on every single request. Hash the raw bytes and every page looks
changed every day, so every page gets sent to a model every day and the "only
when the hash changes" design saves nothing at all.

Stripping scripts, styles and the obvious volatile attributes first makes the
hash stable across fetches of an unchanged page, which is what turns ~80 daily
fetches into ~15-30 model calls a month.

No AI in this file, and no third-party parser — stdlib only, like the rest.
"""

from __future__ import annotations

import hashlib
import html as _html
import re
from typing import List

# Whole elements whose CONTENT is never page text.
_DROP_BLOCKS = re.compile(
    r"<(script|style|noscript|svg|template|iframe|head)\b[^>]*>.*?</\1\s*>",
    re.I | re.S,
)
# Self-closing / unclosed variants of the same, plus comments.
_DROP_TAGS = re.compile(r"<(script|style|noscript|svg|link|meta)\b[^>]*/?>", re.I)
_COMMENTS = re.compile(r"<!--.*?-->", re.S)

# Tags that imply a line break when flattened, so a job list does not collapse
# into one unreadable line and quotes stay sentence-shaped.
_BREAKS = re.compile(
    r"</?(p|div|br|li|tr|h[1-6]|section|article|header|footer|nav|ul|ol|table|"
    r"dt|dd|blockquote|option)\b[^>]*>",
    re.I,
)
_ANY_TAG = re.compile(r"<[^>]+>")

# Cookie banners and chrome that appear on every page and drown the signal. Only
# removed from the HASH input, never from the text a model reads — a rule that
# looks like boilerplate today may be the eligibility sentence tomorrow.
_NOISE_LINES = re.compile(
    r"^(accept( all)?( cookies)?|cookie (policy|settings|preferences)|"
    r"manage (cookies|preferences)|privacy policy|terms of (use|service)|"
    r"skip to (main )?content|we use cookies.*|sign in|log in|menu|search)$",
    re.I,
)


def to_text(html: str) -> str:
    """Flatten HTML to the text a person would read."""
    if not html:
        return ""
    s = _COMMENTS.sub(" ", html)
    s = _DROP_BLOCKS.sub(" ", s)
    s = _DROP_TAGS.sub(" ", s)
    s = _BREAKS.sub("\n", s)
    s = _ANY_TAG.sub(" ", s)
    s = _html.unescape(s)
    # Normalise per line so line structure survives but runs of space do not.
    lines = [" ".join(ln.split()) for ln in s.split("\n")]
    out: List[str] = [ln for ln in lines if ln]
    return "\n".join(out)


# Values that change on every request and mean nothing. Removed before hashing.
_VOLATILE = (
    re.compile(r"\b[0-9a-f]{32,64}\b", re.I),                  # build ids, csrf
    re.compile(r"\b\d{10,13}\b"),                              # epoch timestamps
    re.compile(r"\b\d{4}-\d{2}-\d{2}T[\d:.]+Z?\b"),            # iso timestamps
    re.compile(r"\?(?:v|t|ts|cb|_)=[\w.-]+", re.I),            # cache busters
    re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
               r"[0-9a-f]{4}-[0-9a-f]{12}\b", re.I),           # uuids
)


def stable_text(html: str) -> str:
    """The text used for change detection: flattened, de-noised, de-volatilised."""
    text = to_text(html)
    kept = [ln for ln in text.split("\n") if not _NOISE_LINES.match(ln.strip())]
    s = "\n".join(kept)
    for pat in _VOLATILE:
        s = pat.sub("", s)
    return " ".join(s.split())


def content_hash(html: str) -> str:
    """Hash of the stable text. Equal hashes mean: do not pay for a model."""
    return hashlib.sha256(stable_text(html).encode("utf-8", "replace")).hexdigest()


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("usage: python3 pagetext.py <file.html>")
        raise SystemExit(2)
    raw = open(sys.argv[1], encoding="utf-8", errors="replace").read()
    txt = to_text(raw)
    print("raw html   : {:>9,} chars".format(len(raw)))
    print("page text  : {:>9,} chars".format(len(txt)))
    print("stable text: {:>9,} chars".format(len(stable_text(raw))))
    print("hash       : {}".format(content_hash(raw)))
    print("-" * 60)
    print(txt[:1500])
