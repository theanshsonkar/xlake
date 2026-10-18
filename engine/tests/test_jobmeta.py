import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import jobmeta as jm  # noqa: E402


class CanonicalUrlTest(unittest.TestCase):
    def test_strips_tracking_and_normalises(self):
        base = "https://jobs.lever.co/acme/123"
        for u in (base + "?lever-source=LinkedIn", base + "/?utm_source=x&utm_medium=y",
                  base + "/apply", "HTTPS://Jobs.Lever.co/acme/123/#frag",
                  base + "?ref=abc&source=twitter&gh_src=zz"):
            self.assertEqual(jm.canonical_url(u), base)

    def test_keeps_identity_params_sorted(self):
        self.assertEqual(jm.canonical_url("https://x.com/c?gh_jid=9&utm_x=1&b=2"),
                         "https://x.com/c?b=2&gh_jid=9")
        self.assertNotEqual(jm.canonical_url("https://x.com/c?gh_jid=9"),
                            jm.canonical_url("https://x.com/c?gh_jid=10"))

    def test_empty(self):
        self.assertEqual(jm.canonical_url(None), "")
        self.assertEqual(jm.canonical_url(""), "")


class FieldNormalisationTest(unittest.TestCase):
    def test_employment(self):
        for raw, want in (("FullTime", "full-time"), ("Full time", "full-time"), ("Part-time", "part-time"),
                          ("Intern", "internship"), ("Contractor", "contract"), ("Temporary", "temporary"),
                          ("Apprenticeship", "apprenticeship"), ("Other", None), (None, None)):
            self.assertEqual(jm.norm_employment_type(raw), want, raw)

    def test_workplace(self):
        self.assertEqual(jm.norm_workplace("Hybrid"), "hybrid")
        self.assertEqual(jm.norm_workplace("OnSite"), "onsite")
        self.assertEqual(jm.norm_workplace("on-site"), "onsite")
        self.assertEqual(jm.norm_workplace("remote"), "remote")
        self.assertIsNone(jm.norm_workplace("unspecified"))
        self.assertEqual(jm.workplace_from_text("Engineer", "Hybrid - London"), "hybrid")
        self.assertEqual(jm.workplace_from_text("Remote (US)"), "remote")

    def test_level(self):
        self.assertEqual(jm.detect_level("Software Engineering Intern"), "intern")
        self.assertEqual(jm.detect_level("Data Scientist", "internship"), "intern")
        self.assertEqual(jm.detect_level("New Grad Software Engineer"), "new_grad")
        self.assertEqual(jm.detect_level("Entry-Level Analyst"), "entry")
        self.assertEqual(jm.detect_level("Junior Developer"), "junior")
        self.assertIsNone(jm.detect_level("Staff Engineer"))
        self.assertEqual(jm.employment_from_title("Summer 2027 Interns"), "internship")

    def test_region(self):
        self.assertEqual(jm.region_of("us_located"), "us")
        self.assertEqual(jm.region_of("india_remote"), "india")
        self.assertEqual(jm.region_of("remote_global"), "global")
        self.assertEqual(jm.region_of("excluded"), "other")

    def test_to_iso(self):
        from datetime import datetime, timezone
        now = datetime(2026, 10, 18, tzinfo=timezone.utc)
        self.assertEqual(jm.to_iso(1791566108174), "2026-10-09T17:15:08+00:00")
        self.assertEqual(jm.to_iso("Posted 3 Days Ago", now), "2026-10-15")
        self.assertEqual(jm.to_iso("Posted Today", now), "2026-10-18")
        self.assertIsNone(jm.to_iso("Posted 30+ Days Ago", now))
        self.assertEqual(jm.to_iso("2026-08-06T12:50:10-04:00"), "2026-08-06T12:50:10-04:00")
        self.assertIsNone(jm.to_iso(""))


class SalaryTest(unittest.TestCase):
    def test_ranges(self):
        f = jm.parse_salary_text("The base salary range is $120,000 - $150,000 per year plus equity.")
        self.assertEqual((f["salary_min"], f["salary_max"], f["salary_currency"], f["salary_interval"]),
                         (120000, 150000, "USD", "year"))
        f = jm.parse_salary_text("Pay: $45 to $55 an hour")
        self.assertEqual((f["salary_min"], f["salary_max"], f["salary_interval"]), (45, 55, "hour"))
        f = jm.parse_salary_text("£60k - £80k depending on experience")
        self.assertEqual((f["salary_min"], f["salary_max"], f["salary_currency"]), (60000, 80000, "GBP"))
        f = jm.parse_salary_text("₹ 6,00,000 - 9,00,000") or {}
        self.assertEqual(f, {})  # Indian digit grouping: refuse rather than guess

    def test_not_salary(self):
        self.assertEqual(jm.parse_salary_text("We raised $10 - $20 million last year"), {})
        self.assertEqual(jm.parse_salary_text("Team of 5 to 10 people"), {})
        self.assertEqual(jm.parse_salary_text(None), {})

    def test_structured(self):
        f = jm.salary_fields(100, 200, "USD", "hour")
        self.assertEqual(f["salary_text"], "USD 100-200 per hour")
        self.assertEqual(jm.salary_fields(None, None, "USD", "year"), {})


class DomainTest(unittest.TestCase):
    def test_domain_from_url(self):
        self.assertEqual(jm.domain_from_url("https://careers.wipro.com/job/1"), "wipro.com")
        self.assertEqual(jm.domain_from_url("https://www.bbc.co.uk/jobs"), "bbc.co.uk")
        self.assertEqual(jm.domain_from_url("careers.acme.io"), "acme.io")
        self.assertIsNone(jm.domain_from_url("https://boards.greenhouse.io/acme/jobs/1"))
        self.assertIsNone(jm.domain_from_url("https://acme.wd5.myworkdayjobs.com/x"))
        self.assertIsNone(jm.domain_from_url(None))

    def test_domain_from_text_requires_name_match(self):
        self.assertEqual(jm.domain_from_text("See www.acmelabs.io/about", "Acme Labs"), "acmelabs.io")
        self.assertIsNone(jm.domain_from_text("See partner.com", "Acme Labs"))
        self.assertIsNone(jm.domain_from_text("See linkedin.com/company/acme", "Acme"))

    def test_logo(self):
        self.assertIn("domain=acme.io", jm.favicon_logo("acme.io"))
        self.assertIsNone(jm.favicon_logo(None))


class TextTest(unittest.TestCase):
    def test_clean_and_snippet(self):
        self.assertEqual(jm.clean_text("&lt;p&gt;Hello&lt;/p&gt;&lt;p&gt;World&amp;nbsp;!&lt;/p&gt;"), "Hello World !")
        s = jm.snippet("word " * 100, 300)
        self.assertLessEqual(len(s), 300)
        self.assertTrue(s.endswith("word"))
        self.assertIsNone(jm.snippet(""))


class JsonLdTest(unittest.TestCase):
    PAGE = """<html><script type="application/ld+json">{"@context":"https://schema.org","@graph":[
    {"@type":"JobPosting","title":"Intern","datePosted":"2026-09-01","validThrough":"2026-11-30T23:59",
     "employmentType":["INTERN"],"jobLocationType":"TELECOMMUTE",
     "baseSalary":{"@type":"MonetaryAmount","currency":"USD","value":{"@type":"QuantitativeValue","minValue":30,"maxValue":40,"unitText":"HOUR"}},
     "hiringOrganization":{"@type":"Organization","name":"Acme Inc","sameAs":"https://www.acme.com"}}]}</script></html>"""

    def test_jobposting(self):
        d = jm.parse_jsonld_job(self.PAGE)
        self.assertEqual(d["deadline"], "2026-11-30")
        self.assertEqual(d["posted_at"], "2026-09-01")
        self.assertEqual(d["employment_type"], "internship")
        self.assertEqual(d["workplace"], "remote")
        self.assertEqual((d["salary_min"], d["salary_max"], d["salary_interval"]), (30, 40, "hour"))
        self.assertEqual(d["company_domain"], "acme.com")
        self.assertEqual(d["company_display_name"], "Acme Inc")

    def test_no_jsonld(self):
        self.assertEqual(jm.parse_jsonld_job("<html></html>"), {})
        self.assertEqual(jm.parse_jsonld_job('<script type="application/ld+json">{bad</script>'), {})


if __name__ == "__main__":
    unittest.main()
