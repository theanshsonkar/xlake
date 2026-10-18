"""Polite, browser-compatible page fetch for programme categories.

Stdlib only. One entry point, `fetch_page(url)`, returning
(status, final_url, html, error) like pipeline.resolve._fetch_page, plus
`fetch_html(url)` returning (html, final_url) and raising on failure (the shape
programme_core.collect expects).

Behaviour:
  - honest-but-compatible UA (Chrome-like, with an XlakeBot contact token);
  - on 403 with that UA, one retry with a plain browser UA, only if robots.txt
    allows the path for `*`;
  - redirects 301/302/303/307/308 followed manually (max 5), final URL kept;
  - 429/503: honour Retry-After (capped at 20s), up to 2 retries with backoff;
  - non-ASCII URL parts percent-encoded; seeds containing "…" or ")(" rejected;
  - TLS errors: retry once on the www./non-www variant. Verification is never
    disabled;
  - per-host politeness delay via adapters.boards._throttle.
"""

from __future__ import annotations

import gzip
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from typing import Callable, Optional, Tuple

from core import robots

CHROME = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
BOT_UA = CHROME + " (compatible; XlakeBot/1.0; +https://xlake.site/about)"
BROWSER_UA = CHROME

MAX_REDIRECTS = 5
MAX_RETRIES = 2
RETRY_AFTER_CAP = 20.0
TIMEOUT = 15
MAX_BYTES = 4_000_000
REDIRECT_CODES = (301, 302, 303, 307, 308)


class InvalidSeedURL(ValueError):
    pass


def headers(user_agent: str = BOT_UA) -> dict:
    return {
        "User-Agent": user_agent,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip",
        "Upgrade-Insecure-Requests": "1",
    }


def normalize_url(url: str) -> str:
    """Percent-encode non-ASCII characters; reject garbage seeds."""
    if not isinstance(url, str) or not url.strip():
        raise InvalidSeedURL("invalid_seed_url: empty")
    url = url.strip()
    if "…" in url or ")(" in url or "..." in url:
        raise InvalidSeedURL("invalid_seed_url: truncated or malformed")
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise InvalidSeedURL("invalid_seed_url: not http(s)")
    netloc = parts.netloc
    try:
        netloc.encode("ascii")
    except UnicodeEncodeError:
        try:
            netloc = netloc.encode("idna").decode("ascii")
        except UnicodeError:
            raise InvalidSeedURL("invalid_seed_url: bad host")
    safe = "/%:@!$&'()*+,;=~-._"
    path = urllib.parse.quote(parts.path, safe=safe)
    query = urllib.parse.quote(parts.query, safe=safe + "?")
    return urllib.parse.urlunsplit((parts.scheme, netloc, path, query, ""))


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):  # noqa: D401
        return None


def _default_opener(req, timeout):
    return urllib.request.build_opener(_NoRedirect).open(req, timeout=timeout)


def _decode(raw: bytes, enc: str) -> bytes:
    enc = (enc or "").lower()
    try:
        if "gzip" in enc:
            return gzip.decompress(raw)
        if "deflate" in enc:
            try:
                return zlib.decompress(raw)
            except zlib.error:
                return zlib.decompress(raw, -zlib.MAX_WBITS)
    except Exception:  # noqa: BLE001
        pass
    return raw


def _read(resp) -> str:
    raw = resp.read(MAX_BYTES)
    hdrs = getattr(resp, "headers", None) or getattr(resp, "info", lambda: {})()
    raw = _decode(raw, hdrs.get("Content-Encoding", "") if hdrs else "")
    return raw.decode("utf-8", errors="replace")


def _retry_after(hdrs, attempt: int) -> float:
    value = hdrs.get("Retry-After") if hdrs else None
    try:
        wait = float(str(value).strip())
    except (TypeError, ValueError):
        wait = 2.0 * (attempt + 1)
    return max(0.0, min(wait, RETRY_AFTER_CAP))


def _is_tls(exc: BaseException) -> bool:
    reason = getattr(exc, "reason", exc)
    if isinstance(reason, ssl.SSLError):
        return True
    text = str(reason).lower()
    return any(t in text for t in ("hostname mismatch", "certificate", "ssl", "tls",
                                   "unexpected eof", "handshake"))


def _www_variant(url: str) -> Optional[str]:
    p = urllib.parse.urlsplit(url)
    host = p.hostname or ""
    if not host or host.replace(".", "").isdigit():
        return None
    new = host[4:] if host.startswith("www.") else "www." + host
    netloc = new + (":%d" % p.port if p.port else "")
    return urllib.parse.urlunsplit(p._replace(netloc=netloc))


def _throttle_pair(url):
    try:
        from adapters.boards import _throttle, _release
        return _throttle(url), _release
    except Exception:  # noqa: BLE001
        return None, None


def _robots_ok(url: str) -> bool:
    try:
        return robots.allowed(url)[0]
    except Exception:  # noqa: BLE001
        return True


def _one(url, user_agent, opener, sleep, polite):
    """GET one URL following redirects and 429/503 retries.

    Returns (status, final_url, html, error, tls_exc)."""
    current = url
    redirects = 0
    attempt = 0
    while True:
        lock, release = _throttle_pair(current) if polite else (None, None)
        try:
            req = urllib.request.Request(current, headers=headers(user_agent))
            try:
                with opener(req, TIMEOUT) as resp:
                    return resp.getcode(), current, _read(resp), None, None
            except urllib.error.HTTPError as e:
                code = e.code
                if code in REDIRECT_CODES:
                    loc = e.headers.get("Location") if e.headers else None
                    if not loc:
                        return code, current, "", "http_{}".format(code), None
                    redirects += 1
                    if redirects > MAX_REDIRECTS:
                        return code, current, "", "too_many_redirects", None
                    try:
                        current = normalize_url(urllib.parse.urljoin(current, loc))
                    except InvalidSeedURL:
                        return code, current, "", "bad_redirect_location", None
                    continue
                if code in (429, 503) and attempt < MAX_RETRIES:
                    wait = _retry_after(e.headers, attempt)
                    attempt += 1
                    sleep(wait)
                    continue
                body = ""
                try:
                    body = _read(e)
                except Exception:  # noqa: BLE001
                    pass
                return code, current, body, "http_{}".format(code), None
            except Exception as e:  # noqa: BLE001
                if _is_tls(e):
                    return None, current, "", "tls: {}".format(str(e)[:120]), e
                return None, current, "", "{}: {}".format(type(e).__name__, str(e)[:120]), None
        finally:
            if release and lock:
                release(current, lock)


def fetch_page(url: str, opener: Optional[Callable] = None,
               sleep: Callable[[float], None] = time.sleep,
               polite: Optional[bool] = None
               ) -> Tuple[Optional[int], str, str, Optional[str]]:
    opener = opener or _default_opener
    if polite is None:
        polite = opener is _default_opener
    try:
        url = normalize_url(url)
    except InvalidSeedURL as exc:
        return None, str(url), "", str(exc)
    ok, why = robots.allowed(url) if polite else (True, "ok")
    if not ok:
        return None, url, "", why

    status, final, html, err, tls = _one(url, BOT_UA, opener, sleep, polite)
    if tls is not None:
        alt = _www_variant(url)
        if alt:
            status, final, html, err, _ = _one(alt, BOT_UA, opener, sleep, polite)
    if status == 403 and (not polite or _robots_ok(final)):
        s2, f2, h2, e2, _ = _one(final, BROWSER_UA, opener, sleep, polite)
        if s2 is not None and s2 < 400:
            return s2, f2, h2, e2
        if s2 == 403:
            # Some WAFs flag a Chrome UA without a Chrome TLS fingerprint but
            # accept the plain, honest bot UA. Last try, same robots gate.
            s3, f3, h3, e3, _ = _one(final, robots.UA, opener, sleep, polite)
            if s3 is not None and s3 < 400:
                return s3, f3, h3, e3
    return status, final, html, err


def fetch_html(url: str, **kw) -> Tuple[str, str]:
    status, final, html, err = fetch_page(url, **kw)
    if err or status is None or status >= 400:
        raise RuntimeError(err or "http_{}".format(status))
    return html, final
