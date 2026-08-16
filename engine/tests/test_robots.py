"""robots.py against RFC 9309's own worked examples, plus the two real files
this project's coverage depends on.

Pure parsing — no network. The live-fetch behaviour is checked by hand with
`python3 robots.py <url>`; what matters here is that the matching rules cannot
regress, because both regressions are silent:

  - get longest-match wrong and Keka reads as forbidden, removing the source of
    38 of the 40 confident India roles;
  - get the 4xx rule wrong and Ashby reads as forbidden on its gateway's 401.

Run: python3 -m unittest discover -s tests
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import robots  # noqa: E402


def rules(text: str) -> robots.Rules:
    return robots._parse(text)


class TestLongestMatch(unittest.TestCase):
    """RFC 9309 §2.2.2 — the most specific (most octets) match wins."""

    # RFC 9309 §5.2, quoted verbatim.
    RFC_LONGEST = """
User-Agent: *
Disallow: /example/page/
Allow: /example/page/disallowed.gif
"""

    def test_rfc_longest_match_example(self):
        r = rules(self.RFC_LONGEST)
        # The RFC states this exact expectation: the longer Allow wins.
        self.assertTrue(r.allows("/example/page/disallowed.gif"))
        self.assertFalse(r.allows("/example/page/index.html"))

    def test_allow_wins_equivalent_rules(self):
        # §2.2.2: "If an allow rule and a disallow rule are equivalent, then the
        # allow rule SHOULD be used."
        r = rules("User-agent: *\nDisallow: /x\nAllow: /x\n")
        self.assertTrue(r.allows("/x"))

    def test_no_matching_rule_is_allowed(self):
        # §2.2.2: "If no match is found ... the URI is allowed."
        r = rules("User-agent: *\nDisallow: /private\n")
        self.assertTrue(r.allows("/public"))
        self.assertFalse(r.allows("/private/x"))


class TestKeka(unittest.TestCase):
    """The single most important file in the project.

    Fetched live from blackfigtech.keka.com/robots.txt on 2026-07-31 and pasted
    byte-for-byte, including the absent trailing newline.
    """

    KEKA = "User-agent: *\nDisallow: /\nAllow: /careers\nAllow: /careers/"

    def test_careers_is_allowed_despite_disallow_all(self):
        r = rules(self.KEKA)
        self.assertTrue(r.allows("/careers"))
        self.assertTrue(r.allows("/careers/"))

    def test_the_api_path_we_actually_use_is_allowed(self):
        # /careers/api/embedjobs/{portal}/active/{guid} is the endpoint the whole
        # Keka adapter depends on. `Allow: /careers` is a prefix of it, and at 9
        # octets it beats `Disallow: /` at 1.
        r = rules(self.KEKA)
        self.assertTrue(
            r.allows("/careers/api/embedjobs/default/active/"
                     "0f8c1d2e-3a4b-5c6d-7e8f-9a0b1c2d3e4f")
        )

    def test_rest_of_the_site_is_still_disallowed(self):
        r = rules(self.KEKA)
        for path in ("/", "/admin", "/api/employees", "/login"):
            self.assertFalse(r.allows(path), path)

    def test_custom_parser_uses_longest_match(self):
        # The production parser must retain RFC 9309 longest-match semantics
        # regardless of how urllib.robotparser behaves on this Python version.
        r = rules(self.KEKA)
        self.assertTrue(r.allows("/careers/"))


class TestWildcards(unittest.TestCase):
    """§2.2.3 — `*` and `$` MUST be supported."""

    # RFC 9309 §5.1, quoted verbatim.
    RFC_SIMPLE = """
User-Agent: *
Disallow: *.gif$
Disallow: /example/
Allow: /publications/

User-Agent: foobot
Disallow:/
Allow:/example/page.html
Allow:/example/allowed.gif

User-Agent: barbot
User-Agent: bazbot
Disallow: /example/page.html

User-Agent: quxbot

"""

    def test_star_group_for_an_unnamed_crawler(self):
        r = rules(self.RFC_SIMPLE)
        self.assertTrue(r.allows("/publications/x"))
        self.assertFalse(r.allows("/example/anything"))
        self.assertFalse(r.allows("/anywhere/logo.gif"))
        # $ anchors: a .gif rule must not block a path that merely contains it.
        self.assertTrue(r.allows("/img/logo.gif.html"))

    def test_dollar_anchor(self):
        r = rules("User-agent: *\nDisallow: /a$\n")
        self.assertFalse(r.allows("/a"))
        self.assertTrue(r.allows("/ab"))

    def test_named_group_beats_star_and_is_not_merged_with_it(self):
        saved = robots.UA_TOKEN
        try:
            robots.UA_TOKEN = "foobot"
            r = rules(self.RFC_SIMPLE)
            # foobot's own group: Disallow / with two narrow Allows. The `*`
            # group's `Allow: /publications/` must NOT leak in.
            self.assertTrue(r.allows("/example/page.html"))
            self.assertTrue(r.allows("/example/allowed.gif"))
            self.assertFalse(r.allows("/publications/x"))
            self.assertFalse(r.allows("/"))
        finally:
            robots.UA_TOKEN = saved

    def test_empty_group_allows_everything(self):
        saved = robots.UA_TOKEN
        try:
            robots.UA_TOKEN = "quxbot"
            r = rules(self.RFC_SIMPLE)
            self.assertTrue(r.allows("/"))
            self.assertTrue(r.allows("/example/page.html"))
        finally:
            robots.UA_TOKEN = saved

    def test_product_token_match_is_exact_not_substring(self):
        # A group for another bot whose name merely contains ours must not apply.
        r = rules("User-agent: notxlakebot\nDisallow: /\n"
                  "\nUser-agent: *\nAllow: /\n")
        self.assertTrue(r.allows("/anything"))


class TestGroupMerging(unittest.TestCase):
    """§2.2.1 — repeated user-agent lines MUST be merged into one group."""

    def test_repeated_groups_merge(self):
        r = rules(
            "User-agent: *\nDisallow: /foo\nDisallow: /bar\n"
            "\nUser-agent: *\nDisallow: /baz\n"
        )
        for p in ("/foo", "/bar", "/baz"):
            self.assertFalse(r.allows(p), p)

    def test_shared_group_covers_all_its_agents(self):
        saved = robots.UA_TOKEN
        try:
            for name in ("barbot", "bazbot"):
                robots.UA_TOKEN = name
                r = rules("User-agent: barbot\nUser-agent: bazbot\n"
                          "Disallow: /example/page.html\n")
                self.assertFalse(r.allows("/example/page.html"), name)
                self.assertTrue(r.allows("/other"), name)
        finally:
            robots.UA_TOKEN = saved

    def test_rule_before_any_user_agent_line_is_ignored(self):
        # §2.2.2: "The crawler SHOULD ignore disallow and allow rules that are
        # not in any group."
        r = rules("Disallow: /\nUser-agent: *\nAllow: /\n")
        self.assertTrue(r.allows("/anything"))

    def test_comments_and_empty_disallow(self):
        r = rules(
            "User-agent: *   # everyone\n"
            "Disallow:       # an empty Disallow means allow all\n"
        )
        self.assertTrue(r.allows("/anything"))

    def test_sitemap_does_not_terminate_a_group(self):
        # §2.2.4: "a Sitemaps record MUST NOT terminate a group."
        r = rules("User-agent: *\nSitemap: https://x/sitemap.xml\nDisallow: /p\n")
        self.assertFalse(r.allows("/p"))


class TestCrawlDelay(unittest.TestCase):
    def test_crawl_delay_is_parsed(self):
        # api.lever.co, live 2026-07-31: "Allow: / / Crawl-delay: 1".
        r = rules("User-agent: *\nAllow: /\nCrawl-delay: 1\n")
        self.assertEqual(r.delay, 1.0)
        self.assertTrue(r.allows("/v0/postings/palantir"))

    def test_junk_crawl_delay_is_ignored_not_fatal(self):
        r = rules("User-agent: *\nCrawl-delay: soon\n")
        self.assertIsNone(r.delay)


class TestAccessResults(unittest.TestCase):
    """§2.3.1 — the status-code rules, exercised without network access."""

    def test_4xx_including_401_allows_everything(self):
        # api.ashbyhq.com answers 401 on /robots.txt. Per §2.3.1.3 that is
        # "unavailable", so access is permitted. Getting this wrong silently
        # disables the Ashby adapter.
        for code in (401, 403, 404, 410, 429):
            r = robots.Rules()
            r.status = code
            self.assertFalse(r.blanket_deny)
            self.assertTrue(r.allows("/posting-api/job-board/notion"), code)

    def test_5xx_means_complete_disallow(self):
        r = robots.Rules()
        r.blanket_deny = True  # what _fetch_rules sets for 5xx / network error
        r.status = 503
        self.assertFalse(r.allows("/"))
        self.assertFalse(r.allows("/anything"))


class TestRateLimitBackoff(unittest.TestCase):
    def setUp(self):
        robots.reset_for_tests()

    tearDown = setUp

    def test_429_puts_a_host_in_backoff(self):
        url = "https://apply.workable.com/api/v1/widget/accounts/x"
        self.assertFalse(robots.is_rate_limited(url))
        robots.note_rate_limited(url)
        self.assertTrue(robots.is_rate_limited(url))
        # Scoped to the host, not the whole platform or the whole run.
        self.assertFalse(robots.is_rate_limited("https://api.lever.co/v0/postings/x"))

    def test_retry_after_can_only_extend_the_wait(self):
        url = "https://example.com/x"
        base = robots.note_rate_limited(url)
        robots.reset_for_tests()
        longer = robots.note_rate_limited(url, retry_after="99999")
        self.assertGreater(longer, base)
        robots.reset_for_tests()
        shorter = robots.note_rate_limited(url, retry_after="1")
        # A site asking for LESS than our own back-off does not get hammered.
        self.assertAlmostEqual(shorter, base, delta=5)

    def test_penalty_report_lists_the_host(self):
        robots.note_rate_limited("https://apply.workable.com/x")
        self.assertIn("apply.workable.com", robots.penalty_report())


if __name__ == "__main__":
    unittest.main(verbosity=2)
