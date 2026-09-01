import unittest
from copy import deepcopy
from urllib.parse import urljoin

from categories.startup_founder.harvest import (
    Candidate,
    FetchResult,
    Fetcher,
    build_records,
    candidate_from_link,
    discover_candidates,
    excluded_domain,
    fetch_hub,
    github_raw_url,
    github_readme_url,
    guarded_output_path,
    load_hubs,
    liveness_counts,
)


HUBS = [
    {
        "hub_id": "hub-one",
        "url": "https://directory.example/one",
        "category": "startup_founder",
        "type": "hub",
        "added_at": "2026-08-31T00:00:00Z",
    },
    {
        "hub_id": "hub-two",
        "url": "https://directory.example/two",
        "category": "startup_founder",
        "type": "hub",
        "added_at": "2026-08-31T00:00:00Z",
    },
    {
        "hub_id": "hub-three",
        "url": "https://directory.example/three",
        "category": "startup_founder",
        "type": "hub",
        "added_at": "2026-08-31T00:00:00Z",
    },
]


class MappingFetcher:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def fetch(self, url, headers=None):
        self.calls.append(url)
        return self.responses.get(
            url,
            FetchResult("failed", final_url=url, reason="not configured"),
        )


def github_test_hub():
    return {
        "hub_id": "test-github-hub",
        "url": "https://github.com/example/awesome-startups",
        "category": "startup_founder",
        "type": "hub",
        "added_at": "2026-08-31T00:00:00Z",
    }


class TestStartupFounderHarvester(unittest.TestCase):
    def test_config_loads_the_expanded_worldwide_hubs(self):
        self.assertEqual(load_hubs(), [
            {
                "hub_id": "ahmadnassri-awesome-accelerators",
                "url": "https://github.com/ahmadnassri/awesome-accelerators",
                "category": "startup_founder",
                "type": "hub",
                "authoritative": False,
                "added_at": "2026-09-01T00:00:00Z",
            },
            {
                "hub_id": "ahmadnassri-awesome-incubators",
                "url": "https://github.com/ahmadnassri/awesome-incubators",
                "category": "startup_founder",
                "type": "hub",
                "authoritative": False,
                "added_at": "2026-09-01T00:00:00Z",
            },
            {
                "hub_id": "selcuke-accelerators-incubators-list",
                "url": "https://github.com/selcuke/Accelerators-and-Incubators-list",
                "category": "startup_founder",
                "type": "hub",
                "authoritative": False,
                "added_at": "2026-09-01T00:00:00Z",
            },
            {
                "hub_id": "y-combinator-startup-programs",
                "url": "https://www.ycombinator.com/",
                "category": "startup_founder",
                "type": "hub",
                "authoritative": True,
                "added_at": "2026-09-01T00:00:00Z",
            },
            {
                "hub_id": "techstars-accelerators",
                "url": "https://www.techstars.com/accelerators",
                "category": "startup_founder",
                "type": "hub",
                "authoritative": True,
                "added_at": "2026-09-01T00:00:00Z",
            },
            {
                "hub_id": "antler-startup-programs",
                "url": "https://www.antler.co/locations",
                "category": "startup_founder",
                "type": "hub",
                "authoritative": True,
                "added_at": "2026-09-01T00:00:00Z",
            },
            {
                "hub_id": "entrepreneur-first-programs",
                "url": "https://www.joinef.com/",
                "category": "startup_founder",
                "type": "hub",
                "authoritative": True,
                "added_at": "2026-09-01T00:00:00Z",
            },
            {
                "hub_id": "avinash-awesome-startup-credits",
                "url": "https://github.com/avinashkranjan/awesome-startup-credits",
                "category": "startup_founder",
                "type": "hub",
                "authoritative": False,
                "added_at": "2026-09-01T00:00:00Z",
            },
            {
                "hub_id": "openvc-incubators-accelerators",
                "url": "https://www.openvc.app/incubators-accelerators",
                "category": "startup_founder",
                "type": "hub",
                "authoritative": False,
                "added_at": "2026-09-01T00:00:00Z",
            },
            {
                "hub_id": "startup-india-incubator-schemes",
                "url": "https://www.startupindia.gov.in/content/sih/en/incubator.html",
                "category": "startup_founder",
                "type": "hub",
                "authoritative": True,
                "added_at": "2026-09-01T00:00:00Z",
            },
            {
                "hub_id": "startup-india-seed-fund",
                "url": "https://seedfund.startupindia.gov.in/",
                "category": "startup_founder",
                "type": "hub",
                "authoritative": True,
                "added_at": "2026-09-01T00:00:00Z",
            },
            {
                "hub_id": "t-hub-programs",
                "url": "https://t-hub.co/programs/",
                "category": "startup_founder",
                "type": "hub",
                "authoritative": True,
                "added_at": "2026-09-01T00:00:00Z",
            },
        ])

    def test_raw_master_takes_precedence_and_reports_markdown_links(self):
        hub = github_test_hub()
        master = github_raw_url("example", "awesome-startups", "master", "README.md")
        api = github_readme_url(hub["url"])
        markdown = (
            "[Capital Factory](https://www.capitalfactory.com/programs)\n"
            "[Another programme](https://programme.example/apply)\n"
        )
        fetcher = MappingFetcher({
            master: FetchResult("live", status=200, final_url=master, body=markdown),
        })

        state, links, reason, base, method, raw_count = fetch_hub(
            fetcher, hub, include_stats=True
        )
        self.assertEqual(state, "processed")
        self.assertEqual(method, "raw-master")
        self.assertEqual(raw_count, 2)
        self.assertEqual(len(links), 2)
        self.assertNotIn(api, fetcher.calls)
        self.assertEqual(fetcher.calls, [master])
        self.assertIn("raw-master", reason)
        self.assertEqual(base, "https://github.com/example/awesome-startups/blob/master/README.md")

        candidates, states, reasons, counts, failures, blocks = discover_candidates(
            [hub], fetcher
        )
        self.assertEqual(states[hub["hub_id"]], "processed")
        self.assertEqual(counts[hub["hub_id"]], 2)
        self.assertEqual(failures, 0)
        self.assertEqual(blocks, 0)
        self.assertEqual(
            {candidate.url for candidate in candidates},
            {
                "https://www.capitalfactory.com/programs",
                "https://programme.example/apply",
            },
        )

    def test_raw_main_is_used_when_master_fails(self):
        hub = github_test_hub()
        master = github_raw_url("example", "awesome-startups", "master", "README.md")
        main = github_raw_url("example", "awesome-startups", "main", "README.md")
        api = github_readme_url(hub["url"])
        fetcher = MappingFetcher({
            master: FetchResult("dead", status=404, final_url=master, reason="missing"),
            main: FetchResult(
                "live", status=200, final_url=main,
                body="[Launch](https://launch.example/apply)",
            ),
        })

        _, _, reason, _, method, raw_count = fetch_hub(fetcher, hub, include_stats=True)
        self.assertEqual(method, "raw-main")
        self.assertEqual(raw_count, 1)
        self.assertIn("raw-main", reason)
        self.assertEqual(fetcher.calls, [master, main])
        self.assertNotIn(api, fetcher.calls)

    def test_api_is_used_only_after_both_raw_branches_fail(self):
        hub = github_test_hub()
        master = github_raw_url("example", "awesome-startups", "master", "README.md")
        main = github_raw_url("example", "awesome-startups", "main", "README.md")
        api = github_readme_url(hub["url"])
        fetcher = MappingFetcher({
            master: FetchResult("dead", status=404, final_url=master, reason="missing"),
            main: FetchResult("failed", final_url=main, reason="timeout"),
            api: FetchResult(
                "live", status=200, final_url=api,
                body="[API programme](https://api-programme.example/apply)",
                response_headers={"content-type": "text/plain"},
            ),
        })

        _, _, reason, _, method, raw_count = fetch_hub(fetcher, hub, include_stats=True)
        self.assertEqual(method, "api")
        self.assertEqual(raw_count, 0)
        self.assertIn("api", reason)
        self.assertEqual(fetcher.calls, [master, main, api])

    def test_two_hub_membership_is_corroborated_in_hub_order(self):
        candidate = Candidate(
            "https://official.example/program?b=2&a=1",
            {
                "hub-two": (HUBS[1]["url"], "Second listing"),
                "hub-one": (HUBS[0]["url"], "First listing"),
            },
        )

        record = build_records([candidate], HUBS, "2026-08-31T00:00:00Z")[0]
        evidence = record["official_evidence"]

        self.assertEqual(evidence["source_count"], 2)
        self.assertEqual(evidence["source_hub"], HUBS[0]["url"])
        self.assertEqual(evidence["anchor_text"], "First listing")
        self.assertEqual(
            [item["hub_id"] for item in evidence["corroborating_hubs"]],
            ["hub-one", "hub-two"],
        )
        self.assertEqual(
            [item["anchor_text"] for item in evidence["corroborating_hubs"]],
            ["First listing", "Second listing"],
        )

    def test_single_hub_membership_has_one_source(self):
        candidate = Candidate(
            "https://official.example/one-program",
            {"hub-two": (HUBS[1]["url"], "Only listing")},
        )

        record = build_records([candidate], HUBS, "2026-08-31T00:00:00Z")[0]
        evidence = record["official_evidence"]

        self.assertEqual(evidence["source_count"], 1)
        self.assertEqual(evidence["corroborating_hubs"][0]["hub_id"], "hub-two")

    def test_default_candidate_filtering_keeps_capital_factory(self):
        normalized = candidate_from_link(
            HUBS[0]["url"],
            "https://www.capitalfactory.com/programs?utm_source=hub#apply",
            "Capital Factory",
        )

        self.assertEqual(normalized, "https://www.capitalfactory.com/programs")
        self.assertIsNone(
            candidate_from_link(
                HUBS[0]["url"],
                "https://www.capitalfactory.com/programs",
                "Capital Factory",
                require_candidate_terms=True,
            )
        )

    def test_redirected_html_final_url_is_base_for_relative_links_and_exclusions(self):
        class StaticFetcher:
            def fetch(self, url, headers=None):
                return FetchResult(
                    "live",
                    status=200,
                    final_url="https://new.example/catalog/index.html",
                    body=(
                        '<a href="programs/launch">Launch programme</a>'
                        '<a href="https://new.example/privacy">Privacy</a>'
                    ),
                )

        state, links, reason, html_base = fetch_hub(StaticFetcher(), HUBS[0])
        self.assertEqual(state, "processed")
        self.assertEqual(reason, "HTML anchors; robots_allow")
        self.assertEqual(html_base, "https://new.example/catalog/index.html")
        self.assertEqual(
            urljoin(html_base, links[0][0]),
            "https://new.example/catalog/programs/launch",
        )

        candidates, states, reasons, counts, failures, blocks = discover_candidates(
            [HUBS[0]], StaticFetcher()
        )

        self.assertEqual(states, {"hub-one": "processed"})
        self.assertEqual(reasons["hub-one"], "HTML anchors; robots_allow")
        self.assertEqual(counts, {"hub-one": 0})
        self.assertEqual((failures, blocks), (0, 0))
        self.assertEqual(candidates, [])

    def test_excluded_domain_proxies_cover_subdomains_and_crunchbase(self):
        self.assertTrue(excluded_domain("jobs.linkedin.com"))
        self.assertTrue(excluded_domain("programs.crunchbase.com"))
        self.assertIsNone(
            candidate_from_link(
                HUBS[0]["url"],
                "https://programs.crunchbase.com/accelerators",
                "Accelerators",
            )
        )

    def test_robots_cross_origin_redirect_is_conservatively_blocked(self):
        class RobotsRedirectFetcher(Fetcher):
            def __init__(self):
                super().__init__()
                self.calls = []

            def _request_once(self, url, headers):
                self.calls.append(url)
                return FetchResult(
                    "dead",
                    status=302,
                    final_url=url,
                    reason="https://destination.example/robots.txt",
                )

        fetcher = RobotsRedirectFetcher()
        allowed, reason = fetcher._robots_allows("https://source.example/program")

        self.assertFalse(allowed)
        self.assertEqual(reason, "robots_cross_origin_redirect_blocked")
        self.assertEqual(fetcher.calls, ["https://source.example/robots.txt"])
        self.assertEqual(set(fetcher._robots_cache), {"https://source.example:443"})

    def test_liveness_sampling_does_not_modify_record_status_or_schema(self):
        candidate = Candidate(
            "https://official.example/program",
            {"hub-one": (HUBS[0]["url"], "Launch programme")},
        )
        records = build_records([candidate], HUBS, "2026-08-31T00:00:00Z")
        before = deepcopy(records)

        class StaticFetcher:
            def fetch(self, url, headers=None):
                return FetchResult("live", status=200, final_url=url)

        self.assertEqual(liveness_counts([candidate.url], StaticFetcher()), {
            "live": 1,
            "blocked": 0,
            "dead": 0,
            "failed": 0,
        })
        self.assertEqual(records, before)
        self.assertEqual(records[0]["programme_status"], "needs_confirmation")

    def test_record_schema_and_expected_output_fields(self):
        candidate = Candidate(
            "https://official.example/program",
            {"hub-one": (HUBS[0]["url"], "Launch programme")},
        )
        record = build_records([candidate], HUBS, "2026-08-31T00:00:00Z")[0]

        self.assertEqual(set(record), {
            "record_type", "category", "opportunity_type", "programme_id",
            "programme_name", "official_url", "programme_status", "deadline",
            "eligibility", "funding", "official_evidence", "last_checked_at",
        })
        self.assertEqual(set(record["official_evidence"]), {
            "source_hub", "anchor_text", "corroborating_hubs", "source_count",
        })
        self.assertEqual(record["record_type"], "programme")
        self.assertEqual(record["category"], "startup_founder")
        self.assertEqual(record["opportunity_type"], "startup_programme")
        self.assertEqual(record["deadline"], None)
        self.assertEqual(record["eligibility"], "needs_confirmation")
        self.assertEqual(record["funding"], "not_stated")
        self.assertEqual(record["last_checked_at"], "2026-08-31T00:00:00Z")

    def test_output_guard_accepts_tmp_and_rejects_lake_substring(self):
        self.assertEqual(
            guarded_output_path("/tmp/startup_founder_test.json"),
            guarded_output_path("/tmp/startup_founder_test.json"),
        )
        with self.assertRaises(ValueError):
            guarded_output_path("/tmp/lake-startup-founder.json")
        with self.assertRaises(ValueError):
            guarded_output_path("/tmp/STARTUP_LAKE_RESULT.json")


if __name__ == "__main__":
    unittest.main()
