"""core.rendered: fresh/stale/blocked cache handling and extraction from rendered text."""
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import rendered  # noqa: E402
from categories import programme_core  # noqa: E402

URL = "https://example.org/fellowship"
NOW = datetime(2026, 10, 20, tzinfo=timezone.utc)
TEXT = ("Example Fellowship 2027\nApplications are open. The application deadline is 30 November 2026.\n"
        "Open to students of any nationality. Full tuition scholarship provided.")


class RenderedCache(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.targets = os.path.join(self.tmp.name, "targets.json")
        with open(self.targets, "w") as fh:
            json.dump([{"id": "ex", "category": "fellowships", "url": URL}], fh)

    def write(self, **kw):
        entry = {"id": "ex", "url": URL, "final_url": URL + "/", "status": "ok", "title": "Example",
                 "text": TEXT, "links": [{"href": "https://example.org/apply", "text": "Apply now"}],
                 "fetched_at": (NOW - timedelta(days=2)).isoformat()}
        entry.update(kw)
        with open(os.path.join(self.tmp.name, "ex.json"), "w") as fh:
            json.dump(entry, fh)

    def lookup(self, url=URL):
        return rendered.lookup(url, now=NOW, cache_dir=self.tmp.name, targets_path=self.targets)

    def test_fresh_ok_used(self):
        self.write()
        html, final = self.lookup("https://www.example.org/fellowship/")
        self.assertEqual(final, URL + "/")
        self.assertIn("30 November 2026", html)
        self.assertIn('href="https://example.org/apply"', html)

    def test_stale_ignored(self):
        self.write(fetched_at=(NOW - timedelta(days=11)).isoformat())
        self.assertIsNone(self.lookup())

    def test_non_ok_statuses_ignored(self):
        for status in ("blocked", "challenge", "robots_disallowed", "timeout", "empty", "error"):
            self.write(status=status)
            self.assertIsNone(self.lookup(), status)

    def test_untargeted_url_ignored(self):
        self.write()
        self.assertIsNone(self.lookup("https://other.org/x"))

    def test_missing_cache_file(self):
        self.assertIsNone(self.lookup())

    def test_default_fetch_prefers_cache_then_falls_back(self):
        with mock.patch.object(rendered, "lookup", return_value=("<html>c</html>", "u")):
            self.assertEqual(programme_core._default_fetch(URL), ("<html>c</html>", "u"))
        with mock.patch.object(rendered, "lookup", return_value=None), \
                mock.patch("core.webfetch.fetch_html", return_value=("<html>w</html>", "w")):
            self.assertEqual(programme_core._default_fetch(URL), ("<html>w</html>", "w"))

    def test_extraction_deadline_from_rendered_text(self):
        self.write()
        html, final = self.lookup()
        text, _links = programme_core._text(html)
        windows = programme_core.detect_applicant_windows(text, today=NOW.date())
        self.assertTrue(any(str(w.get("end")) == "2026-11-30" and w.get("basis") == "applicant_deadline" for w in windows), windows)


class RenderedPatterns(unittest.TestCase):
    today = datetime(2026, 10, 20).date()

    def end(self, text):
        return [(str(w["start"]), str(w["end"])) for w in programme_core.detect_applicant_windows(text, today=self.today)]

    def test_real_snippets(self):
        # Snippets copied from rendered official pages (Oct 2026).
        self.assertEqual(self.end("Final Notice (Extended): Last date for startups to apply under SISFS \u2013 31 May 2026"),
                         [("2026-05-31", "2026-05-31")])
        self.assertEqual(self.end("Applications for the Summer Fellowship close on September 29th, 2026."),
                         [("2026-09-29", "2026-09-29")])

    def test_new_date_shapes(self):
        self.assertEqual(self.end("Last date to apply: 30-11-2026"), [("2026-11-30", "2026-11-30")])
        self.assertEqual(self.end("Registration ends on 15 November 2026 11:59 PM IST"), [("2026-11-15", "2026-11-15")])
        self.assertEqual(self.end("Registration deadline: 5 Dec 2026"), [("2026-12-05", "2026-12-05")])
        self.assertEqual(self.end("Round 1 registration closes 5 Dec 2026"), [("2026-12-05", "2026-12-05")])
        self.assertEqual(self.end("Applications open Nov 15 \u2013 Dec 20, 2026"), [("2026-11-15", "2026-12-20")])
        self.assertEqual(self.end("Page generated 2026-11-30 and build 26-11-30"), [])

    def test_next_cycle_for_past_deadline(self):
        cfg = programme_core.ProgrammeConfig(category="open-source-programmes", opportunity_type="open_source_programme",
                                             source_registry=(), observations_path="", verifications_path="",
                                             next_cycle=True)
        seed = {"source_id": "x", "programme_id": "x", "programme_name": "Example Summer Programme",
                "organizer": "Example Org", "official_url": "https://example.org/p",
                "allowed_path_hints": [], "check_cadence": "weekly"}
        html = ("<html><body><main><h1>Example Summer Programme</h1><p>The application deadline was 17 March 2026."
                " Apply to this summer programme for students and fellows.</p></main></body></html>")
        rec, obs = programme_core.parse_programme(seed, html, datetime(2026, 10, 20, tzinfo=timezone.utc),
                                                  None, config=cfg)
        self.assertIsNotNone(rec, obs)
        self.assertEqual(rec["programme_status"], "upcoming")
        self.assertEqual(rec["last_deadline"], "2026-03-17")


if __name__ == "__main__":
    unittest.main()
