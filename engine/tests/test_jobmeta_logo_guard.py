import unittest

from core import jobmeta


class FaviconLogoGuardTests(unittest.TestCase):
    def test_company_domain_gets_favicon(self):
        self.assertIn("domain=stripe.com", jobmeta.favicon_logo("stripe.com"))

    def test_aggregator_domains_get_no_logo(self):
        for d in ("unstop.com", "www.unstop.com", "devpost.com", "jobs.lever.co", "internshala.com", "", None):
            self.assertIsNone(jobmeta.favicon_logo(d), d)


if __name__ == "__main__":
    unittest.main()
