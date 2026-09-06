"""Focused offline tests for resolver-origin company domains."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline import resolve  # noqa: E402
from pipeline import resolve_companies  # noqa: E402


class TestNormalizeCompanyDomain(unittest.TestCase):
    def test_full_url_is_normalized(self):
        self.assertEqual(
            resolve.normalize_company_domain(
                "https://www.Example.com:443/careers?x=1#f"
            ),
            "example.com",
        )

    def test_bare_host_trailing_dot_is_normalized(self):
        self.assertEqual(resolve.normalize_company_domain("example.com."), "example.com")

    def test_ats_base_and_subdomain_are_rejected(self):
        for value in (
            "greenhouse.io",
            "https://jobs.greenhouse.io/acme",
            "careers.myworkdayjobs.com",
            "boards.smartrecruiters.com.",
            "recruitee.com",
            "jobs.recruitee.com/acme",
            "personio.de",
            "jobs.personio.de/acme",
            "eightfold.ai",
            "acme.eightfold.ai/jobs",
            "freshteam.com",
            "acme.freshteam.com/jobs",
        ):
            self.assertIsNone(resolve.normalize_company_domain(value))

    def test_real_domain_passes_without_stripping_jobs_or_careers(self):
        self.assertEqual(
            resolve.normalize_company_domain("https://careers.example.com/jobs"),
            "careers.example.com",
        )
        self.assertEqual(
            resolve.normalize_company_domain("jobs.example.com"),
            "jobs.example.com",
        )

    def test_resolution_registry_entry_has_domain_only_when_valid(self):
        valid = resolve.Resolution(
            company="Example", domain="https://www.Example.com/careers",
            platform="greenhouse", token="example", readable=True,
        ).as_registry_entry()
        self.assertEqual(valid["company_domain"], "example.com")

        vendor = resolve.Resolution(
            company="Example", domain="https://jobs.greenhouse.io/example",
            platform="greenhouse", token="example", readable=True,
        ).as_registry_entry()
        self.assertNotIn("company_domain", vendor)

    def test_writer_registry_entry_has_domain_only_when_valid(self):
        row = {
            "platform": "greenhouse", "token": "example", "company": "Example",
            "segment": "india", "evidence": "test", "domain": "example.com",
        }
        self.assertEqual(
            resolve_companies._resolver_registry_entry(row)["company_domain"],
            "example.com",
        )
        row["domain"] = "boards.greenhouse.io/example"
        self.assertNotIn(
            "company_domain", resolve_companies._resolver_registry_entry(row)
        )


if __name__ == "__main__":
    unittest.main()
