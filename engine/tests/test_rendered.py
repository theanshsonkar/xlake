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


if __name__ == "__main__":
    unittest.main()
