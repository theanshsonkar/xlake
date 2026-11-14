import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import date

from crawler import extract

HTML = """<html lang="en"><head><title>Acme Fellowship | Acme Labs</title>
<meta property="og:site_name" content="Acme Labs">
<script type="application/ld+json">{"@type": "Organization", "name": "LD Name"}</script></head>
<body><h1>Fellowship</h1>
<p>The Acme fellowship supports early founders building tools for the world of education with funding.</p>
<p>Applications close on 30 November 2026 for the next cohort of fellows.</p>
<a href="/careers?utm_source=x">Careers</a><a href="https://other.com/a#b">Other</a>
<a href="mailto:careers@acme.com">mail</a><a href="mailto:jane@acme.com">jane</a>
<a href="tel:123">call</a><a href="javascript:void(0)">js</a>
<p>Write to hello@acme.com or bob@acme.com or hello@elsewhere.org. Call 555-123-4567.</p>
</body></html>"""


class TestExtract(unittest.TestCase):
    def setUp(self):
        self.p = extract.extract(HTML, "https://www.acme.com/fellowship", date(2026, 11, 1))

    def test_title_and_organiser(self):
        self.assertEqual(self.p["title"], "Acme Fellowship | Acme Labs")
        self.assertEqual(self.p["organiser"], "Acme Labs")

    def test_links_skip_mailto_tel_js(self):
        self.assertEqual([l["url"] for l in self.p["links"]],
                         ["https://www.acme.com/careers", "https://other.com/a"])

    def test_only_generic_same_domain_emails(self):
        self.assertEqual(self.p["emails"], ["careers@acme.com", "hello@acme.com"])

    def test_deadline(self):
        self.assertEqual(self.p["deadline"], "2026-11-30")

    def test_language(self):
        self.assertEqual(self.p["language"], "en")
        self.assertEqual(extract.detect_language("", "", "नमस्ते दुनिया यह एक परीक्षण है"), "hi")
        self.assertEqual(extract.detect_language("", "", "xyz qrs tuv"), "und")

    def test_text_cut_to_2000_words(self):
        page = extract.extract("<p>%s</p>" % ("word " * 3000), "https://a.com/")
        self.assertEqual(len(page["text"].split()), 2000)

    def test_parse_feed_rss_and_atom(self):
        rss = ("<rss><channel><item><title>A raises $5M</title><link>https://x.com/a</link>"
               "<pubDate>Mon, 02 Nov 2026 10:00:00 GMT</pubDate></item></channel></rss>")
        atom = ('<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>B</title>'
                '<link href="https://x.com/b"/><updated>2026-10-01T00:00:00Z</updated></entry></feed>')
        self.assertEqual(extract.parse_feed(rss),
                         [{"title": "A raises $5M", "link": "https://x.com/a", "date": "2026-11-02"}])
        self.assertEqual(extract.parse_feed(atom)[0]["date"], "2026-10-01")
        self.assertEqual(extract.parse_feed("not xml"), [])


if __name__ == "__main__":
    unittest.main()
