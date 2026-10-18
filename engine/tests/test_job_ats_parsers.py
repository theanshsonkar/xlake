"""ATS parsers extract structured fields (offline fixtures in tests/fixtures/jobs)."""
import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from adapters import boards  # noqa: E402

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "jobs")


def load(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as fh:
        return json.load(fh)


def run(fn, token, data):
    with mock.patch.object(boards, "_request", return_value=(200, data, None)):
        return fn(token)


class GreenhouseTest(unittest.TestCase):
    def test_fields(self):
        r = run(boards._greenhouse, "vercel", load("greenhouse.json"))
        self.assertIsNone(r.error)
        p = r.postings[0]
        self.assertTrue(p.description and "Vercel" in p.description)
        self.assertNotIn("&lt;", p.description)  # double-escaped HTML cleaned
        self.assertEqual(p.meta["company_display_name"], "Vercel")
        self.assertEqual(p.meta["posted_at"], "2026-08-06T12:50:10-04:00")
        self.assertEqual(p.meta["workplace"], "hybrid")  # from "Hybrid - London"
        self.assertEqual(p.meta["team"], "Account Executive")

    def test_deadline_and_metadata_employment_type(self):
        data = {"jobs": [{
            "id": 1, "title": "Software Engineer Intern", "absolute_url": "https://careers.acme.io/jobs?gh_jid=1",
            "location": {"name": "Remote - US"}, "updated_at": "2026-09-01T00:00:00-04:00",
            "application_deadline": "2026-12-31T00:00:00Z",
            "metadata": [{"name": "Employment Type", "value": "Intern", "value_type": "single_select"}],
            "content": "Pay range $40 - $50 per hour. Join us.", "company_name": "Acme"}]}
        p = run(boards._greenhouse, "acme", data).postings[0]
        self.assertEqual(p.meta["employment_type"], "internship")
        self.assertEqual(p.meta["deadline"], "2026-12-31")
        self.assertEqual(p.meta["level"], "intern")
        self.assertEqual(p.meta["company_domain"], "acme.io")  # company-hosted job URL
        self.assertEqual(p.meta["workplace"], "remote")
        self.assertEqual((p.meta["salary_min"], p.meta["salary_max"], p.meta["salary_interval"]),
                         (40, 50, "hour"))


class LeverTest(unittest.TestCase):
    def test_fields(self):
        r = run(boards._lever, "spotify", load("lever.json"))
        a, b = r.postings
        self.assertEqual(a.meta["employment_type"], "full-time")
        self.assertEqual(a.meta["workplace"], "hybrid")
        self.assertEqual(a.meta["team"], "Marketing")
        self.assertTrue(a.meta["posted_at"].startswith("2026-10-09"))
        self.assertEqual(b.meta["employment_type"], "contract")
        self.assertTrue(a.description)

    def test_salary_range(self):
        data = [{"id": "x", "text": "New Grad Engineer", "hostedUrl": "https://jobs.lever.co/a/x",
                 "categories": {"commitment": "Full-time", "location": "NYC"},
                 "salaryRange": {"currency": "USD", "interval": "per-year-salary", "min": 120000, "max": 150000},
                 "descriptionPlain": "desc", "createdAt": 1791566108174}]
        p = run(boards._lever, "a", data).postings[0]
        self.assertEqual(p.meta["salary_currency"], "USD")
        self.assertEqual(p.meta["salary_interval"], "year")
        self.assertEqual(p.meta["salary_text"], "USD 120,000-150,000 per year")
        self.assertEqual(p.meta["level"], "new_grad")


class AshbyTest(unittest.TestCase):
    def test_compensation_and_fields(self):
        r = run(boards._ashby, "openai", load("ashby.json"))
        p = r.postings[0]
        self.assertEqual(p.meta["employment_type"], "full-time")
        self.assertEqual((p.meta["salary_min"], p.meta["salary_max"]), (257000, 335000))
        self.assertEqual(p.meta["salary_currency"], "USD")
        self.assertEqual(p.meta["team"], "Technical Program Management")
        self.assertTrue(p.meta["posted_at"].startswith("2026-03-12"))
        self.assertTrue(p.description)

    def test_remote_flag_and_unlisted(self):
        data = {"jobs": [
            {"id": "1", "title": "Intern", "employmentType": "Intern", "isRemote": True,
             "jobUrl": "https://jobs.ashbyhq.com/a/1", "descriptionPlain": "x"},
            {"id": "2", "title": "Hidden", "isListed": False, "jobUrl": "https://jobs.ashbyhq.com/a/2"}]}
        ps = run(boards._ashby, "a", data).postings
        self.assertEqual(len(ps), 1)
        self.assertEqual(ps[0].meta["employment_type"], "internship")
        self.assertEqual(ps[0].meta["workplace"], "remote")


class WorkableTest(unittest.TestCase):
    def test_account_record_gives_domain_and_logo(self):
        widget = {"name": "Acme Labs", "description": "x", "jobs": [
            {"shortcode": "A", "title": "Dev", "url": "https://apply.workable.com/j/A", "city": "Rome"}]}
        acct = {"name": "Acme Labs", "url": "https://www.acmelabs.io/", "logo": "https://workablehr.s3.amazonaws.com/l.png"}
        with mock.patch.object(boards, "_request", side_effect=[(200, widget, None), (200, acct, None)]):
            r = boards._workable("acme")
        self.assertEqual(r.postings[0].meta["company_domain"], "acmelabs.io")
        self.assertEqual(r.postings[0].meta["logo_url"], "https://workablehr.s3.amazonaws.com/l.png")

    def test_account_record_failure_does_not_fail_board(self):
        widget = {"name": "Acme", "jobs": [{"shortcode": "A", "title": "Dev", "url": "u"}]}
        with mock.patch.object(boards, "_request", side_effect=[(200, widget, None), (404, None, "http_404")]):
            r = boards._workable("acme")
        self.assertIsNone(r.error)
        self.assertEqual(len(r.postings), 1)

    def test_description_and_fields(self):
        r = run(boards._workable, "1kosmos", load("workable.json"))
        p = r.postings[0]
        self.assertTrue(p.description and len(p.description) > 100)  # was always empty before
        self.assertEqual(p.meta["employment_type"], "full-time")
        self.assertEqual(p.meta["posted_at"], "2026-10-07")
        self.assertEqual(p.meta["company_display_name"], "1Kosmos")
        self.assertEqual(p.meta["team"], "Engineering")
        self.assertEqual(p.meta["workplace"], "onsite")

    def test_account_domain_from_description_needs_name_match(self):
        data = {"name": "Acme Labs", "description": "Visit https://www.acmelabs.io or https://partner.com",
                "jobs": [{"shortcode": "A", "title": "Dev", "telecommuting": True, "url": "https://apply.workable.com/j/A"}]}
        r = run(boards._workable, "acme", data)
        self.assertEqual(r.postings[0].meta["company_domain"], "acmelabs.io")
        self.assertEqual(r.postings[0].meta["workplace"], "remote")
        data["description"] = "Partners: https://unrelated.com"
        self.assertNotIn("company_domain", run(boards._workable, "acme", data).postings[0].meta)


class WorkdayTest(unittest.TestCase):
    TOKEN = "nvidia.wd5.myworkdayjobs.com|nvidia|NVIDIAExternalCareerSite"

    def test_list_and_detail(self):
        r = run(boards._workday, self.TOKEN, load("workday_list.json"))
        p = r.postings[0]
        self.assertRegex(p.meta["posted_at"], r"^\d{4}-\d{2}-\d{2}$")
        self.assertTrue(p.meta["_path"].startswith("/job/"))
        self.assertNotIn("company_domain", p.meta)  # myworkdayjobs.com is not the employer
        with mock.patch.object(boards, "_request", return_value=(200, load("workday_detail.json"), None)):
            det = boards.workday_detail(self.TOKEN, p.meta["_path"])
        self.assertIn("Ignite", det["description"])
        self.assertEqual(det["deadline"], "2026-10-19")
        p.description = det.pop("description")
        p.meta.update(det)
        boards.refinish_meta(p)
        self.assertEqual(p.meta["employment_type"], "internship")  # title beats "Full time"
        self.assertEqual(p.meta["level"], "intern")

    def test_custom_host_gives_company_domain(self):
        data = {"total": 1, "jobPostings": [{"title": "Engineer", "externalPath": "/job/x_1",
                                             "locationsText": "Pune", "postedOn": "Posted Yesterday",
                                             "bulletFields": ["1"]}]}
        p = run(boards._workday, "careers.wipro.com|wipro|ext", data).postings[0]
        self.assertEqual(p.meta["company_domain"], "wipro.com")

    def test_detail_failure_is_empty(self):
        with mock.patch.object(boards, "_request", return_value=(500, None, "http_500")):
            self.assertEqual(boards.workday_detail(self.TOKEN, "/job/x"), {})


class SmartRecruitersTest(unittest.TestCase):
    def test_fields(self):
        data = {"totalFound": 1, "content": [{
            "id": "1", "name": "Junior Data Analyst", "releasedDate": "2026-10-01T10:00:00.000Z",
            "location": {"city": "Berlin", "country": "de", "remote": False, "hybrid": True},
            "typeOfEmployment": {"label": "Full-time"}, "experienceLevel": {"label": "Entry Level"},
            "department": {"label": "Data"}, "company": {"name": "Acme"}}]}
        r = run(boards._smartrecruiters, "acme", data)
        self.assertIsNone(r.error)
        m = r.postings[0].meta
        self.assertEqual((m["employment_type"], m["workplace"], m["team"], m["level"]),
                         ("full-time", "hybrid", "Data", "junior"))
        self.assertEqual(m["company_display_name"], "Acme")


if __name__ == "__main__":
    unittest.main()
