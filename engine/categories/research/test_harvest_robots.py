import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from categories.research import harvest as research_harvest
from categories.startup_founder import harvest as startup_harvest
from core import robots


HARVESTERS = (research_harvest, startup_harvest)


class TestSharedRobotsForHarvesters(unittest.TestCase):
    def test_harvester_respects_disallow_for_requested_path(self):
        for harvester in HARVESTERS:
            with self.subTest(harvester=harvester.__name__):
                fetcher = harvester.Fetcher()
                with mock.patch.object(
                    harvester.robots,
                    "rules_for",
                    return_value=robots._parse(
                        "User-agent: *\nDisallow: /private\n"
                    ),
                ), mock.patch.object(fetcher, "_request_once") as request:
                    result = fetcher.fetch("https://example.test/private/page")

                self.assertEqual(result.state, "blocked")
                self.assertEqual(result.reason, "robots_disallow")
                request.assert_not_called()

    def test_harvester_uses_shared_orphan_rule_behavior(self):
        for harvester in HARVESTERS:
            with self.subTest(harvester=harvester.__name__):
                fetcher = harvester.Fetcher()
                response = harvester.FetchResult(
                    "live", status=200, final_url="https://example.test/private/page"
                )
                with mock.patch.object(
                    harvester.robots,
                    "rules_for",
                    return_value=robots._parse(
                        "Disallow: /private\n"
                        "User-agent: *\n"
                        "Allow: /private\n"
                    ),
                ), mock.patch.object(
                    fetcher, "_request_once", return_value=response
                ) as request:
                    result = fetcher.fetch("https://example.test/private/page")

                self.assertEqual(result.state, "live")
                request.assert_called_once()

    def test_robots_fetch_failure_remains_blocked_and_records_need_confirmation(self):
        for harvester in HARVESTERS:
            with self.subTest(harvester=harvester.__name__):
                fetcher = harvester.Fetcher()
                with mock.patch.object(
                    harvester.robots,
                    "allowed",
                    return_value=(False, "robots_unreachable_network"),
                ), mock.patch.object(fetcher, "_request_once") as request:
                    result = fetcher.fetch("https://example.test/program")

                self.assertEqual(result.state, "blocked")
                self.assertEqual(result.reason, "robots_unreachable_network")
                request.assert_not_called()

                hub = {
                    "hub_id": "hub",
                    "url": "https://directory.example/",
                    "category": (
                        "research" if harvester is research_harvest else "startup_founder"
                    ),
                }
                records = harvester.build_records(
                    [harvester.Candidate(
                        "https://official.example/program",
                        {"hub": (hub["url"], "Program")},
                    )],
                    [hub],
                    "2026-10-04T00:00:00Z",
                )
                self.assertEqual(records[0]["programme_status"], "needs_confirmation")
                self.assertEqual(records[0]["eligibility"], "needs_confirmation")


if __name__ == "__main__":
    unittest.main()
