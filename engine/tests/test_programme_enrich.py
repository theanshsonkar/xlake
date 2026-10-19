import json
import os
import sys
import unittest
from datetime import date, datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from categories import programme_core as core
from categories import programme_enrich as enrich
from categories.fellowships import fellowships
from pipeline import publish_supabase as pub

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "programme_enrich")
TODAY = date(2026, 10, 18)
CHECKED = datetime(2026, 10, 18, tzinfo=timezone.utc)


def fixture(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as handle:
        return handle.read()


def windows(text):
    return core.detect_applicant_windows(text, TODAY)


class TestDeadlineParsing(unittest.TestCase):
    def check(self, text, expected):
        found = windows(text)
        self.assertTrue(found, text)
        self.assertEqual(found[0]["end"], expected, text)
        self.assertTrue(found[0]["quote"])

    def test_month_name_variants(self):
        self.check("Application deadline: January 15, 2027.", date(2027, 1, 15))
        self.check("Applications close on 15 January 2027.", date(2027, 1, 15))
        self.check("Apply by Jan 15, 2027 to be considered.", date(2027, 1, 15))
        self.check("Submission deadline: Sept. 3rd, 2027", date(2027, 9, 3))
        self.check("The last date to apply is 3rd March 2027.", date(2027, 3, 3))
        self.check("Applications are due 1/15/2027 at noon.", date(2027, 1, 15))
        self.check("Deadline 15.01.2027", date(2027, 1, 15))
        self.check("Open until December 1, 2026.", date(2026, 12, 1))

    def test_is_due_and_malformed_titles(self):
        self.check("The statement of purpose is due Monday, March 29, 2027.", date(2027, 3, 29))
        ok, reason = core.programme_title_ok("Oct 13, 2026 | | \u2705 [OPEN] | Durham | Laidlaw Research Programme", "https://x.org/p", "fellowship")
        self.assertEqual((ok, reason), (False, "malformed_title"))

    def test_table_cells_split_cue_and_date(self):
        self.check("Application deadline. January 15, 2027. Notification in March.", date(2027, 1, 15))

    def test_year_inference_next_occurrence(self):
        self.check("Application deadline: January 15.", date(2027, 1, 15))
        self.check("Application deadline: December 1.", date(2026, 12, 1))
        # past tense text resolves to the most recent occurrence
        self.check("Applications closed on March 3.", date(2026, 3, 3))
        self.assertEqual(core.parse_dates("March 3", None), [])

    def test_exclusions_still_hold(self):
        self.assertEqual(windows("Recommendation letters are due December 1, 2026."), [])
        self.assertEqual(windows("Applicants will be notified by March 1, 2027."), [])

    def test_status_cues(self):
        seed = fellowships.SEEDS[0]
        cases = {
            "<p>Our fellowship applications are now open. Apply by January 15, 2027.</p>": "open",
            "<p>Fellowship applications are accepted on a rolling basis.</p><a href='/apply'>Apply now</a>": "rolling",
            "<p>Fellowship applications closed on March 3, 2024.</p>": "closed",
            "<p>Fellowship applications open in November 2026.</p>": "opening_soon",
        }
        for body, status in cases.items():
            html = "<html><body><h1>Fellowship program</h1>{}</body></html>".format(body)
            record, observation = fellowships.parse_programme(seed, html, CHECKED)
            if status == "closed":
                self.assertIsNone(record)
                self.assertEqual(observation["state"], "closed")
            else:
                self.assertEqual(record["programme_status"], status, body)

    def test_bare_open_has_no_date_and_needs_confirmation(self):
        html = "<html><body><h1>Fellowship program</h1><p>Fellowship applications are now open to all.</p></body></html>"
        record, _ = fellowships.parse_programme(fellowships.SEEDS[0], html, CHECKED)
        self.assertEqual(record["programme_status"], "open")
        self.assertTrue(record["needs_confirmation"])
        self.assertIsNone(record["deadline"])


class TestStructuredData(unittest.TestCase):
    def test_jsonld_fields_beat_regex(self):
        html = fixture("jsonld_fellowship.html")
        structured = enrich.parse_structured(html, "https://example.edu/fellowship")
        self.assertEqual(structured["deadline"], "2027-01-15")
        self.assertEqual(structured["start_date"], "2027-09-01")
        self.assertEqual(structured["funding"], "$30,000")
        self.assertEqual(structured["organizer"], "Example University")
        record, observation = fellowships.parse_programme(
            fellowships.SEEDS[0], html, CHECKED, "https://example.edu/fellowship")
        self.assertEqual(record["deadline"], "2027-01-15")
        self.assertEqual(record["deadline_basis"], "structured_data")
        self.assertEqual(record["programme_status"], "open")
        self.assertIn("structured data", record["official_evidence"]["deadline"]["quote"])
        self.assertEqual(record["funding_amount_usd"], 30000)
        self.assertIs(record["intl_eligible"], True)
        self.assertIn("phd", record["levels"])
        self.assertEqual(record["region"], "US")
        self.assertEqual(record["organizer_domain"], "example.edu")
        self.assertEqual(record["application_url"], "https://example.edu/apply-now")
        self.assertTrue(record["description"].startswith("A year-long fellowship"))
        self.assertLessEqual(len(record["description"]), 300)

    def test_microdata_deadline(self):
        html = '<div itemscope><meta itemprop="applicationDeadline" content="2027-02-01"></div>'
        self.assertEqual(enrich.parse_structured(html)["deadline"], "2027-02-01")

    def test_bad_json_is_ignored(self):
        html = '<script type="application/ld+json">{not json</script><title>x</title>'
        self.assertNotIn("deadline", enrich.parse_structured(html))


class TestDescription(unittest.TestCase):
    def test_meta_then_paragraph_skipping_nav_and_cookies(self):
        html = ("<html><body><nav><p>Home About Contact us today for much more</p></nav>"
                "<div class='cookie-banner'><p>We use cookies to improve your experience on this website today.</p></div>"
                "<main><p>Short.</p><p>The Example Fellowship funds early-career researchers to spend a year "
                "working on open problems in climate science at partner labs.</p></main></body></html>")
        description = enrich.extract_description(html)
        self.assertTrue(description.startswith("The Example Fellowship funds"))
        long = "<meta name='description' content='%s'>" % ("word " * 120)
        self.assertLessEqual(len(enrich.extract_description(long)), 300)


class TestFunding(unittest.TestCase):
    def test_amounts(self):
        self.assertEqual(enrich.extract_funding("Fellows receive a stipend of $8,110 per month.")[:2], ("$8,110 stipend per month", 8110))
        self.assertEqual(enrich.extract_funding("The grant provides up to EUR 50,000 for projects.")[:2], ("Up to €50,000 grant", None))
        self.assertEqual(enrich.extract_funding("Awards of £1,500 are made each year.")[0], "£1,500 award per year")
        self.assertEqual(enrich.extract_funding("A scholarship of ₹50,000 is awarded.")[0], "₹50,000 scholarship")
        self.assertEqual(enrich.extract_funding("The grant is worth $2.5 million.")[:2], ("$2.5M grant", 2500000))

    def test_qualitative(self):
        self.assertEqual(enrich.extract_funding("This is a fully funded programme.")[0], "Fully funded")
        self.assertEqual(enrich.extract_funding("Tuition is covered for all scholars.")[0], "Tuition covered")
        self.assertEqual(enrich.extract_funding("Scholars get a monthly allowance for living costs.")[0], "Monthly allowance")

    def test_fees_are_not_funding(self):
        self.assertEqual(enrich.extract_funding("The application fee of $75 applies to this grant."), (None, None, None))
        self.assertEqual(enrich.extract_funding("We raised $5 million in funding from investors."), (None, None, None))


class TestEligibility(unittest.TestCase):
    def test_sentence_and_heading(self):
        text = "Menu. Eligibility. Applicants must be enrolled in a PhD program at an accredited university. Apply now."
        sentence, _ = enrich.extract_eligibility(text)
        self.assertEqual(sentence, "Applicants must be enrolled in a PhD program at an accredited university.")
        self.assertLessEqual(len(enrich.extract_eligibility("You must be a student " + "x " * 200 + ".")[0] or ""), 200)

    def test_flags(self):
        self.assertEqual(enrich.eligibility_flags("Open to U.S. citizens or permanent residents only."), (False, []))
        self.assertEqual(enrich.eligibility_flags("International students are welcome to apply. Undergraduate and master's students.")[0], True)
        self.assertEqual(enrich.eligibility_flags("International students are not eligible.")[0], False)
        self.assertIsNone(enrich.eligibility_flags("Applicants must be 18.")[0])
        _, levels = enrich.eligibility_flags("For high school seniors, undergraduates, graduate students, PhD candidates, postdocs and early-career researchers")
        self.assertEqual(levels, ["high school", "undergraduate", "graduate", "phd", "postdoc", "early-career"])


class TestRegionLocationLogo(unittest.TestCase):
    def test_region_by_tld(self):
        cases = {
            "https://www.mit.edu/x": "US", "https://nasa.gov/x": "US", "https://ox.ac.uk/x": "UK",
            "https://www.tum.de/x": "Europe", "https://epfl.ch/x": "Europe", "https://uva.nl/x": "Europe",
            "https://iisc.ac.in/x": "India", "https://mitacs.ca/x": "Canada",
        }
        for url, region in cases.items():
            self.assertEqual(enrich.infer_region(url, ""), region, url)
        self.assertIsNone(enrich.infer_region("https://example.com/x", "A programme."))
        self.assertEqual(enrich.infer_region("https://example.com/x", "Open to applicants from any country."), "Global")
        self.assertEqual(enrich.infer_region("https://example.com", "Open to U.S. citizens only.", None, False), "US")

    def test_junk_location_rejected(self):
        for junk in ("our program was designed to be", "Our program was designed to be remote from the beginning.",
                     "x" * 41, "Learn from wherever you are", "not_stated", "Applications are open now"):
            self.assertIsNone(enrich.clean_location(junk), junk)
        for good in ("Remote", "Washington, DC", "United States of America", "Zürich, Switzerland"):
            self.assertEqual(enrich.clean_location(good), good)

    def test_logo_prefers_square_icons_and_https(self):
        html = fixture("jsonld_fellowship.html")
        structured = enrich.parse_structured(html, "https://example.edu/f")
        self.assertEqual(enrich.pick_logo(structured, "https://example.edu/f"), "https://example.edu/logo.svg")
        plain = ('<head><meta property="og:image" content="//cdn.x.org/banner.jpg">'
                 '<link rel="icon" href="/f.ico"><link rel="apple-touch-icon" sizes="152x152" href="/a.png"></head>')
        self.assertEqual(enrich.pick_logo(enrich.parse_structured(plain), "http://x.org/p"), "https://x.org/a.png")
        og_only = '<meta property="og:image" content="http://x.org/banner.jpg">'
        self.assertEqual(enrich.pick_logo(enrich.parse_structured(og_only), "https://x.org"), "https://x.org/banner.jpg")
        self.assertIsNone(enrich.pick_logo(enrich.parse_structured('<link rel="icon" href="data:image/png;base64,xx">'), "https://x.org"))

    def test_registrable_domain(self):
        self.assertEqual(enrich.registrable_domain("https://www.cs.ox.ac.uk/x"), "ox.ac.uk")
        self.assertEqual(enrich.registrable_domain("https://sub.example.org/x"), "example.org")

    def test_apply_link_detection(self):
        links = [("How to apply tips", "/tips"), ("Apply Now", "https://apply.smapply.io/x"),
                 ("Apply", "/apply"), ("Apply", "https://evil.example.net/apply")]
        label, url = enrich.find_application_link(links, "https://example.org/prog")
        self.assertEqual(url, "https://example.org/apply")
        self.assertIsNone(enrich.find_application_link([("Apply", "https://evil.example.net/a")], "https://example.org/p"))


class TestPublishMapping(unittest.TestCase):
    def programme(self, **kw):
        row = {"record_type": "programme", "category": "fellowship", "programme_id": "p1",
               "programme_name": "X Fellowship", "organizer": "X", "official_url": "https://x.org/f",
               "is_live": True, "location": "not_stated", "funding": "not_stated",
               "eligibility": "needs_confirmation", "international_eligibility": "needs_confirmation",
               "programme_status": None, "needs_confirmation": True}
        row.update(kw)
        return row

    def test_placeholders_become_null_and_defaults_set(self):
        mapped = pub.map_row(self.programme())
        self.assertIsNone(mapped["eligibility"])
        self.assertIsNone(mapped["funding"])
        self.assertIsNone(mapped["location"])
        self.assertEqual(mapped["extra"]["programme_status"], "unknown")
        self.assertEqual(mapped["extra"]["deadline_basis"], "unknown")
        self.assertNotIn("international_eligibility", mapped["extra"])

    def test_real_values_and_new_extra_keys(self):
        mapped = pub.map_row(self.programme(
            description="d" * 500, funding="$8,110 stipend", eligibility="Applicants must be PhD students.",
            location="Remote", region="US", logo_url="https://x.org/l.png", organizer_domain="x.org",
            funding_amount_usd=8110, intl_eligible=False, levels=["phd"], deadline_basis="structured_data",
            programme_status="open", location_junk="x"))
        self.assertEqual(len(mapped["description"]), 300)
        self.assertEqual(mapped["funding"], "$8,110 stipend")
        extra = mapped["extra"]
        for key, value in (("region", "US"), ("logo_url", "https://x.org/l.png"), ("organizer_domain", "x.org"),
                           ("funding_amount_usd", 8110), ("intl_eligible", False), ("levels", ["phd"]),
                           ("deadline_basis", "structured_data"), ("programme_status", "open")):
            self.assertEqual(extra[key], value)

    def test_junk_location_nulled_and_jobs_unchanged(self):
        self.assertIsNone(pub.map_row(self.programme(location="Our program was designed to be remote"))["location"])
        job = {"url": "https://j.example/1", "title": "Eng", "company": "Co", "is_live": True,
               "region": "US", "logo_url": "https://x/l.png", "levels": ["phd"], "description": "d" * 250}
        mapped = pub.map_row(job)
        self.assertEqual(mapped["extra"]["region"], "US")
        self.assertNotIn("levels", mapped["extra"])
        self.assertEqual(len(mapped["description"]), 250)

    def test_closed_past_deadline_not_serving(self):
        self.assertFalse(pub.is_serving(self.programme(programme_status="closed", deadline="2020-01-01")))
        self.assertTrue(pub.is_serving(self.programme(programme_status="closed", deadline="2999-01-01")))


class TestRetirement(unittest.TestCase):
    def test_retire_closed(self):
        rows = [
            {"record_type": "programme", "category": "fellowship", "programme_status": "closed",
             "deadline": "2026-01-01", "is_live": True, "needs_confirmation": True},
            {"record_type": "programme", "category": "fellowship", "programme_status": "closed",
             "deadline": "2027-01-01", "is_live": True},
            {"record_type": "programme", "category": "grant", "programme_status": "closed",
             "deadline": "2026-01-01", "is_live": True},
        ]
        self.assertEqual(core.retire_closed("fellowship", rows, TODAY, "now"), 1)
        self.assertFalse(rows[0]["is_live"])
        self.assertFalse(rows[0]["needs_confirmation"])
        self.assertTrue(rows[1]["is_live"])
        self.assertTrue(rows[2]["is_live"])


if __name__ == "__main__":
    unittest.main()
