import unittest
from datetime import date, datetime, timezone

from categories import programme_enrich as enrich
from categories.fellowships import fellowships
from categories.research import research

NOW = datetime(2026, 10, 19, tzinfo=timezone.utc)


def page(body):
    return "<html><body><h1>Summer Research Program</h1>{}</body></html>".format(body)


class NextCycleTests(unittest.TestCase):
    def test_recent_past_deadline_becomes_upcoming_with_hint(self):
        seed = research.SEEDS[0]
        record, obs = research.parse_programme(seed, page("<p>Applications deadline: February 1, 2026. Program applications.</p>"), NOW)
        self.assertEqual(record["programme_status"], "upcoming")
        self.assertIsNone(record["deadline"])
        self.assertEqual(record["last_deadline"], "2026-02-01")
        self.assertIn("February 2027", record["next_cycle_hint"])
        self.assertTrue(record["summary"])

    def test_old_or_discontinued_stays_closed(self):
        seed = research.SEEDS[0]
        record, obs = research.parse_programme(seed, page("<p>Application deadline: February 1, 2024. Program applications.</p>"), NOW)
        self.assertIsNone(record)
        self.assertEqual(obs["state"], "closed")
        record, obs = research.parse_programme(seed, page("<p>Application deadline: February 1, 2026. This program has been discontinued.</p>"), NOW)
        self.assertIsNone(record)

    def test_explicit_next_cycle_text(self):
        hint = enrich.next_cycle_hint("Applications will reopen in January 2027.", date(2026, 2, 1), date(2026, 10, 19))
        self.assertIn("January 2027", hint)

    def test_pdf_deadline_link_is_application_url(self):
        links = [("Application deadlines (PDF)", "/files/deadlines.pdf")]
        self.assertEqual(enrich.find_pdf_application_doc(links, "https://x.edu/a")[1], "https://x.edu/files/deadlines.pdf")


class DetailExtractorTests(unittest.TestCase):
    def test_details(self):
        text = ("Participants receive a $7,000 stipend, housing and travel support for this 10-week program. "
                "Applicants must submit a personal statement, two letters of recommendation and an unofficial transcript. "
                "This program is open to women who are first-generation students. Applicants must be under 30 years of age. "
                "The program runs June 2 - August 8, 2027.")
        d = enrich.extract_details(text)
        self.assertEqual(d["duration"], "10 weeks")
        self.assertIn("housing", d["covers"]); self.assertIn("travel", d["covers"])
        self.assertEqual(d["requirements"][:2], ["personal statement", "recommendation letters"])
        self.assertEqual(d["gender"], "women"); self.assertTrue(d["underrepresented"])
        self.assertEqual(d["age_limit"], "up to 30 years")
        self.assertEqual((d["start_date"], d["end_date"]), ("2027-06-02", "2027-08-08"))

    def test_funding_normalised(self):
        self.assertEqual(enrich.normalise_funding("₹10,000 stipend per month"),
                         {"funding_amount": 10000, "funding_currency": "INR", "funding_period": "month"})
        self.assertEqual(enrich.normalise_funding("$7,000 stipend")["funding_currency"], "USD")

    def test_source_kind_and_abbrev_split(self):
        self.assertEqual(enrich.source_kind("https://www.buddy4study.com/page/x"), "aggregator")
        self.assertEqual(enrich.source_kind("https://amgenscholars.com/"), "official")
        sents = enrich._sentence_split("Open to Indian nationals enrolled in B.Tech or MBA programmes. Ph.D. students too.")
        self.assertEqual(len(sents), 2)

    def test_not_covered_is_ignored(self):
        self.assertEqual(enrich.extract_covers("Participants must arrange their own housing; the program does not cover travel."), [])


if __name__ == "__main__":
    unittest.main()
