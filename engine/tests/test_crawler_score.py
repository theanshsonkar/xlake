import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawler import score


class TestScore(unittest.TestCase):
    def test_type_guess_and_score(self):
        page = {"url": "https://acme.com/careers", "title": "Careers at Acme", "status_code": 200,
                "text": "we are hiring " + "engineers " * 100}
        self.assertEqual(score.type_guess(page), "careers")
        self.assertGreater(score.score(page), 40)

    def test_junk_and_unknown_score_low(self):
        page = {"url": "https://acme.com/privacy", "title": "Privacy", "status_code": 200, "text": "x"}
        self.assertTrue(score.is_junk(page))
        self.assertEqual(score.type_guess(page), "unknown")
        self.assertEqual(score.score(page), 0)

    def test_non_200_lowers(self):
        base = {"url": "https://a.com/jobs", "title": "Jobs", "text": "hiring " * 100}
        self.assertLess(score.score({**base, "status_code": 500}), score.score({**base, "status_code": 200}))

    def test_link_is_opportunity(self):
        self.assertTrue(score.link_is_opportunity("Join us", "https://a.com/x"))
        self.assertTrue(score.link_is_opportunity("", "https://a.com/careers"))
        self.assertFalse(score.link_is_opportunity("About", "https://a.com/about"))

    def test_name_matches_domain(self):
        self.assertTrue(score.name_matches_domain("Acme Labs Inc", "https://acme.com"))
        self.assertTrue(score.name_matches_domain("Acme", "https://getacme.io"))
        self.assertTrue(score.name_matches_domain("Acme", "https://acmehq.com"))
        self.assertFalse(score.name_matches_domain("Acme", "https://other.com"))
        self.assertFalse(score.name_matches_domain("", "https://other.com"))

    def test_denied(self):
        self.assertTrue(score.is_denied("https://www.linkedin.com/company/x"))
        self.assertFalse(score.is_denied("https://acme.com"))


if __name__ == "__main__":
    unittest.main()
