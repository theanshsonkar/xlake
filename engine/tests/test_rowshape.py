import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline import rowshape  # noqa: E402
from pipeline.rowshape import FIELDS, to_standard  # noqa: E402


def job(**kw):
    r = {"platform": "greenhouse", "token": "acme", "job_id": "1", "title": "Software Engineer",
         "company_name": "Acme", "url": "https://boards.greenhouse.io/acme/jobs/1",
         "is_live": True, "last_seen": "2026-11-12T08:00:00+00:00", "location": "Bengaluru",
         "location_bucket": "india_located", "workplace": "hybrid", "posted_at": "2026-11-01T10:00:00Z",
         "salary_min": 1000, "salary_max": 2000, "salary_currency": "USD", "salary_text": "USD 1,000-2,000",
         "description": "x" * 5000}
    r.update(kw)
    return r


def prog(**kw):
    r = {"record_type": "programme", "category": "fellowship", "programme_id": "f1",
         "programme_name": "Test Fellowship", "organizer": "Test Foundation",
         "official_url": "https://test.org/f", "application_url": "https://test.org/apply",
         "deadline": "2027-03-12", "is_live": True, "programme_status": "open",
         "last_checked_at": "2026-11-12T10:00:00+00:00", "levels": ["undergraduate"],
         "funding": "$100,000 stipend", "funding_amount": 100000, "funding_currency": "USD",
         "duration": "12 months", "location": "Berlin, Germany",
         "official_evidence": {"status": {"quote": "Applications open", "url": "https://test.org/s"}}}
    r.update(kw)
    return r


class RowShapeTest(unittest.TestCase):
    def test_every_output_has_exactly_fields(self):
        rows = [job(), prog(), {"record_type": "hackathon", "hackathon_id": "h"},
                {"record_type": "contribution", "contribution_id": "c"}, {}]
        for r in rows:
            self.assertEqual(tuple(to_standard(r)), FIELDS)
        self.assertEqual(len(FIELDS), 26)

    def test_job(self):
        s = to_standard(job())
        self.assertEqual(s["type"], "job")
        self.assertTrue(s["id"].startswith("job:"))
        self.assertEqual(s["org"], "Acme")
        self.assertEqual(s["status"], "open")
        self.assertEqual(s["posted_at"], "2026-11-01")
        self.assertEqual(s["workplace"], "hybrid")
        self.assertEqual(s["country"], "IN")
        self.assertEqual((s["funding_amount"], s["currency"]), (1000, "USD"))
        self.assertEqual(s["proof"], {"quote": "Software Engineer", "url": job()["url"]})
        self.assertEqual(s["last_checked"], "2026-11-12T08:00:00+00:00")
        self.assertNotIn("x" * 400, repr(s))

    def test_internship(self):
        s = to_standard(job(is_internship=True, enrolled_required=True, level="intern"))
        self.assertEqual((s["type"], s["level"]), ("internship", ["undergrad"]))

    def test_programme_statuses(self):
        self.assertEqual(to_standard(prog())["status"], "open")
        self.assertEqual(to_standard(prog(programme_status="upcoming"))["status"], "upcoming")
        self.assertEqual(to_standard(prog(is_live=False))["status"], "closed")
        self.assertEqual(to_standard(prog(is_live=False, needs_confirmation=True))["status"], "unverified")
        self.assertEqual(to_standard(prog(lifecycle="closed"))["status"], "closed")

    def test_programme_multiple_levels_kept(self):
        s = to_standard(prog(levels=["undergraduate", "graduate", "phd"]))
        self.assertEqual(s["level"], ["undergrad", "grad"])

    def test_programme_fields(self):
        s = to_standard(prog(last_deadline="2026-03-01", next_cycle_hint="Next cycle expected March"))
        self.assertEqual(s["type"], "fellowship")
        self.assertEqual(s["level"], ["undergrad"])
        self.assertEqual(s["country"], "DE")
        self.assertEqual(s["apply_url"], "https://test.org/apply")
        self.assertEqual(s["proof"], {"quote": "Applications open", "url": "https://test.org/s"})
        self.assertEqual(s["last_deadline"], "2026-03-01")
        self.assertEqual(s["next_cycle"], "Next cycle expected March")
        self.assertEqual(to_standard(prog(category="startup-founder"))["type"], "startup")
        self.assertEqual(to_standard(prog(category="open-source-programmes"))["type"], "open_source")

    def test_hackathon(self):
        s = to_standard({
            "record_type": "hackathon", "hackathon_id": "h1", "title": "Hack It", "organizer": "nill",
            "official_url": "https://hack.example/", "registration_deadline": "2027-01-15T00:00:00Z",
            "is_online": True, "prize_pool_usd": 5000, "status": "open", "is_live": True,
            "official_evidence": {"source": "devpost", "submission_period_dates": "Jul 16 - Jan 15"},
            "last_checked_at": "2026-11-12T15:00:00+00:00"})
        self.assertEqual((s["type"], s["id"]), ("hackathon", "hackathon:h1"))
        self.assertIsNone(s["org"])
        self.assertEqual(s["deadline"], "2027-01-15")
        self.assertEqual(s["workplace"], "remote")
        self.assertEqual((s["funding_amount"], s["currency"]), (5000, "USD"))
        self.assertEqual(s["proof"]["quote"], "Jul 16 - Jan 15")

    def test_contribution(self):
        s = to_standard({
            "record_type": "contribution", "contribution_id": "c1", "title": "Fix bug", "repo": "a/b",
            "organizer": "a/b", "official_url": "https://github.com/a/b/issues/1", "language": "Python",
            "created_at": "2022-11-29T10:03:48Z", "mode": "online", "is_live": True,
            "official_evidence": {"title": {"quote": "Fix bug", "url": "https://github.com/a/b/issues/1"}}})
        self.assertEqual((s["type"], s["id"]), ("open_source", "contribution:c1"))
        self.assertEqual(s["skills"], ["Python"])
        self.assertEqual(s["posted_at"], "2022-11-29")
        self.assertEqual(s["proof"]["quote"], "Fix bug")

    def test_aggregator_org_and_logo_null(self):
        s = to_standard(job(company_name="Unstop", logo_url="https://cdn.unstop.com/logo.png"))
        self.assertIsNone(s["org"])
        s = to_standard(prog(organizer="Devpost", logo_url="https://devpost.com/logo.png"))
        self.assertIsNone(s["org"])
        self.assertIsNone(s["logo"])
        self.assertIsNone(to_standard(job(company_name="LinkedIn", company_display_name="LinkedIn"))["org"])
        self.assertEqual(to_standard(prog(logo_url="https://test.org/logo.png"))["logo"], "https://test.org/logo.png")

    def test_email_and_phone_scrub(self):
        s = to_standard(prog(eligibility="Contact jane.doe@example.com or +1 (415) 555-0100 for details",
                             funding="Email me@x.org"))
        self.assertNotIn("@", repr(s))
        self.assertNotIn("555", repr(s))
        self.assertEqual(s["eligibility"]["other"], "Contact or for details")
        self.assertEqual(s["funding"], "Email")
        self.assertEqual(rowshape.scrub("Deadline 2026-11-12"), "Deadline 2026-11-12")

    def test_dates_normalised(self):
        s = to_standard(prog(deadline="2027-03-12T23:59:00Z", opening_date="2027-01-01", opens_quote_dated=True, last_deadline="March 2026"))
        self.assertEqual((s["deadline"], s["opens"], s["last_deadline"]), ("2027-03-12", "2027-01-01", None))
        self.assertIsNone(to_standard(prog(deadline="rolling"))["deadline"])

    def test_unknown_is_null(self):
        s = to_standard({})
        self.assertIsNone(s["org"])
        self.assertEqual(s["skills"], [])
        self.assertEqual(s["eligibility"]["countries"], [])
        self.assertIsNone(s["cost_to_apply"])


def hack(**kw):
    r = {"record_type": "hackathon", "category": "hackathons", "hackathon_id": "h1", "title": "Hack",
         "official_url": "https://example.org/h", "source": "unstop", "organizer": "Some Univ"}
    r.update(kw)
    return r


class HackathonTrustTests(unittest.TestCase):
    def test_unstop_registration_quote(self):
        ev = {"start_regn_dt": "2026-03-04T00:00:00+05:30", "end_regn_dt": "2026-11-30T00:59:00+05:30"}
        p = to_standard(hack(official_evidence=ev))["proof"]
        self.assertEqual(p["quote"], "Registration: 2026-03-04T00:00:00+05:30 \u2013 2026-11-30T00:59:00+05:30")
        self.assertEqual((p["url"], p["kind"]), ("https://example.org/h", "source_fields"))

    def test_devfolio_and_mlh_quotes(self):
        d = to_standard(hack(official_evidence={"starts_at": "A", "reg_ends_at": "B"}))["proof"]
        self.assertEqual(d["quote"], "Starts: A; registration ends: B")
        m = to_standard(hack(official_evidence={"start": "A", "end": "B"}))["proof"]
        self.assertEqual(m["quote"], "Event: A \u2013 B")

    def test_dates_text_preferred_no_kind(self):
        p = to_standard(hack(official_evidence={"submission_period_dates": "Jul 16 - Aug 1, 2026"}))["proof"]
        self.assertEqual(p, {"quote": "Jul 16 - Aug 1, 2026", "url": "https://example.org/h"})

    def test_no_evidence_no_quote(self):
        self.assertIsNone(to_standard(hack())["proof"]["quote"])
        self.assertIsNone(to_standard(hack(official_evidence={"start_regn_dt": "x"}))["proof"]["quote"])

    def test_junk_and_aggregator_org(self):
        for junk in ("nill", "na", "n/a", "-", "Devpost", "MLH"):
            self.assertIsNone(to_standard(hack(organizer=junk))["org"], junk)
        self.assertEqual(to_standard(hack())["org"], "Some Univ")


if __name__ == "__main__":
    unittest.main()


class DatedOpensTest(unittest.TestCase):
    def test_opens_only_with_dated_quote(self):
        from pipeline.rowshape import _dated_opens
        base = {"opening_date": "2027-01-10"}
        self.assertEqual(_dated_opens(dict(base, opens_quote_dated=True)), "2027-01-10")
        self.assertIsNone(_dated_opens(dict(base, opens_quote_dated=False)))
        self.assertIsNone(_dated_opens(dict(base, official_evidence={"opening_date": {"quote": "General Application Period."}})))
        self.assertEqual(_dated_opens(dict(base, official_evidence={"opening_date": {"quote": "Opens 10 January 2027"}})), "2027-01-10")
