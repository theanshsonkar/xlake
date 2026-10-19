import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from categories.hackathons import hackathons as hk

PAGE = """
<a href="https://devpost.team">x</a><a href="https://discord.com/invite/abc">d</a>
<a href="https://www.youtube.com/watch?v=1">v</a><a href="https://github.com/someone">g</a>
<a href="https://developer.paypal.com?utm_source=Devpost&amp;utm_medium=LP">PayPal Developer</a>
"""


class FindOfficialSite(unittest.TestCase):
    def test_matches_organiser_name_and_strips_tracking(self):
        self.assertEqual(hk.find_official_site(PAGE, "PayPal"), "https://developer.paypal.com")

    def test_ignores_platforms_and_unrelated(self):
        self.assertIsNone(hk.find_official_site(PAGE, "Amazon"))
        self.assertIsNone(hk.find_official_site('<a href="https://luma.com/x">l</a>', "Luma"))
        self.assertIsNone(hk.find_official_site(None, "PayPal"))

    def test_declared_organiser_domain(self):
        html = '<a href="https://hack.iiitb.ac.in/2026">site</a>'
        self.assertEqual(hk.find_official_site(html, "Placement Cell", "iiitb.ac.in"), "https://hack.iiitb.ac.in/2026")
        self.assertIsNone(hk.find_official_site(html, "Placement Cell", "gmail.com"))

    def test_unstop_details_link_becomes_official_url(self):
        item = {"seo_url": "https://unstop.com/hackathons/x-1", "title": "X Hack", "status": "open",
                "regnRequirements": {"end_regn_dt": "2099-01-01 00:00:00"}, "end_date": "2099-02-01",
                "details": '<p>Register at <a href="https://acme.dev/hack">our site</a></p>',
                "organisation": {"name": "Acme", "official_email_domains": "acme.dev"}}
        rows = hk.normalize_unstop([item], "2026-10-20T00:00:00+00:00")
        self.assertEqual(rows[0]["official_url"], "https://acme.dev/hack")
        self.assertEqual(rows[0]["source_kind"], "official")
        self.assertEqual(rows[0]["application_url"], "https://unstop.com/hackathons/x-1")


class ResolveSites(unittest.TestCase):
    def row(self, **kw):
        base = {"source": "devpost", "source_kind": "aggregator", "organizer": "PayPal",
                "official_url": "https://pp.devpost.com/", "application_url": "https://pp.devpost.com/"}
        base.update(kw)
        return base

    def test_resolves_caps_and_does_not_refetch(self):
        rows = [self.row(), self.row(official_url="https://b.devpost.com/", application_url="https://b.devpost.com/")]
        calls = []
        fetched = hk.resolve_official_sites(rows, fetch=lambda u: calls.append(u) or PAGE, limit=1, delay=0)
        self.assertEqual((fetched, len(calls)), (1, 1))
        self.assertEqual(rows[0]["official_url"], "https://developer.paypal.com")
        self.assertEqual(rows[0]["source_kind"], "official")
        self.assertEqual(rows[0]["application_url"], "https://pp.devpost.com/")
        hk.resolve_official_sites(rows, fetch=lambda u: calls.append(u) or PAGE, limit=5, delay=0)
        self.assertEqual(len(calls), 2)  # only the second row was fetched; first is cached

    def test_cached_site_reapplied_and_failed_fetch_retried(self):
        cached = self.row(official_site="https://developer.paypal.com")
        failed = self.row()
        hk.resolve_official_sites([cached, failed], fetch=lambda u: None, delay=0)
        self.assertEqual(cached["official_url"], "https://developer.paypal.com")
        self.assertNotIn("site_checked", failed)


if __name__ == "__main__":
    unittest.main()
