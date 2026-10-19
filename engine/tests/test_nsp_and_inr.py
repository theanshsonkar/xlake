import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from categories import programme_enrich as enrich
from categories.scholarships import nsp

PAGE = """
<div class="row mb-4 border-1 border-bottom"><div class="col-md-10">
<h6> AICTE - Pragati Scholarship Scheme For Girl Students ( Technical Degree) (Merit Based Scheme)</h6><br>
<span>Scheme  Open from : 01-06-2026 </span><span>Student Application  Open till : 31-10-2026 </span>
<a href="https://scholarships.gov.in/public/schemeGuidelines/AICTE/AICTE_2010_G.pdf" class="x">Specifications</a>
<a href="https://scholarships.gov.in/public/schemeGuidelines/AICTE/AICTE_2010_F.pdf" class="x">FAQ</a></div></div>
<div class="row mb-4 border-1 border-bottom"><div class="col-md-10">
<h6>Some Other Scheme (Welfare Based Scheme)</h6>
<a href="https://scholarships.gov.in/public/schemeGuidelines/not_available.pdf">Specifications</a></div></div>
"""
PDF = ("2) Family income from all sources should not be more than Rs. 8 lakh per annum during the year. "
       "4.0 AMOUNT OF SCHOLARSHIP: 1) Rs. 50,000/- per annum for every year of study i.e. maximum 4 years.")


class InrParsing(unittest.TestCase):
    def f(self, text):
        return enrich.extract_funding(text)[0]

    def test_indian_grouping_and_per_annum(self):
        self.assertEqual(self.f("Scholarship of Rs. 50,000.00 per annum for every year."), "₹50,000 scholarship per year")
        self.assertEqual(self.f("A grant of Rs. 1,00,000 /- p.a. is paid."), "₹1,00,000 grant per year")

    def test_lakh_crore_and_up_to(self):
        self.assertEqual(self.f("Stipend up to ₹1.5 lakh per annum."), "Up to ₹1,50,000 stipend per year")
        self.assertEqual(self.f("Award of ₹2 crore for the fellowship."), "₹2,00,00,000 award")
        self.assertEqual(self.f("Scholarship of Rs 2 lacs per year."), "₹2,00,000 scholarship per year")

    def test_range_and_month(self):
        text = "Scholarship of Rs. 10,000 - Rs. 20,000 per month."
        self.assertEqual(self.f(text), "₹10,000–₹20,000 scholarship per month")
        self.assertEqual(enrich.normalise_funding(self.f(text)),
                         {"funding_amount": 10000, "funding_amount_max": 20000, "funding_currency": "INR", "funding_period": "month"})

    def test_fee_not_funding_and_format(self):
        self.assertIsNone(self.f("An application fee of ₹5000 applies."))
        self.assertEqual([enrich.format_inr(n) for n in (999, 50000, 100000, 12000000)], ["999", "50,000", "1,00,000", "1,20,00,000"])


class NspAdapter(unittest.TestCase):
    def test_parse_schemes(self):
        schemes = nsp.parse_schemes(PAGE)
        self.assertEqual(len(schemes), 2)
        self.assertTrue(schemes[0]["guideline_url"].endswith("AICTE_2010_G.pdf"))
        self.assertEqual((schemes[0]["opens"], schemes[0]["deadline"]), ("2026-06-01", "2026-10-31"))
        self.assertIsNone(schemes[1]["guideline_url"])

    def test_amount_ignores_income_limit_and_ambiguous(self):
        funding, quote = nsp.amount_from_text(PDF)
        self.assertEqual(funding, "₹50,000 scholarship per year")
        self.assertIn("50,000", quote)
        self.assertEqual(nsp.amount_from_text("The rate of scholarship is Rs.12,000 per annum at UG and Rs. 20,000 per annum at PG."), (None, None))
        self.assertEqual(nsp.amount_from_text("Family income should be below Rs. 8 lakh per annum."), (None, None))

    def test_enrich_rows_end_to_end(self):
        row = {"record_type": "programme", "programme_id": "p", "title": "AICTE - Pragati Scholarship Scheme For Girl Students ( Technical Degree)",
               "official_url": "https://scholarships.gov.in/All-Scholarships", "funding": None}
        other = {"record_type": "programme", "title": "Unrelated", "official_url": "https://x.org/"}
        calls = []
        with tempfile.TemporaryDirectory() as td:
            cache = os.path.join(td, "c.json")
            out = nsp.enrich_rows([row, other], lambda url: PAGE, lambda url: calls.append(url) or PDF, cache,
                                  datetime(2026, 10, 20, tzinfo=timezone.utc))
            nsp.enrich_rows([dict(row)], lambda url: PAGE, lambda url: calls.append(url) or PDF, cache,
                            datetime(2026, 10, 21, tzinfo=timezone.utc))
            self.assertTrue(os.path.exists(cache))
        self.assertEqual(len(calls), 1)  # second run served from cache
        self.assertEqual(out[0]["funding"], "₹50,000 scholarship per year")
        self.assertEqual(out[0]["funding_currency"], "INR")
        self.assertEqual(out[0]["official_evidence"]["funding"]["url"].rsplit("/", 1)[1], "AICTE_2010_G.pdf")
        self.assertNotIn("funding", out[1])

    def test_unreadable_pdf_leaves_row_untouched(self):
        row = {"record_type": "programme", "title": "AICTE - Pragati Scholarship Scheme For Girl Students ( Technical Degree)",
               "official_url": "https://scholarships.gov.in/All-Scholarships", "funding": None}
        with tempfile.TemporaryDirectory() as td:
            out = nsp.enrich_rows([row], lambda u: PAGE, lambda u: None, os.path.join(td, "c.json"))
        self.assertIsNone(out[0]["funding"])


if __name__ == "__main__":
    unittest.main()
