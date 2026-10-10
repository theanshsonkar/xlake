import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

try:
    from engine.categories.hub_seeds import (
        _capped_candidates, _default_hubs_path, _policy, _static_seeds,
        admit_candidate, candidates_to_seeds, merge_generated_seeds,
    )
    from engine.categories.research.harvest import Candidate, parse_bare_urls
except ImportError:
    from categories.hub_seeds import (
        _capped_candidates, _default_hubs_path, _policy, _static_seeds,
        admit_candidate, candidates_to_seeds, merge_generated_seeds,
    )
    from categories.research.harvest import Candidate, parse_bare_urls


class HubSeedsTests(unittest.TestCase):
    def candidate(self, name, url, count=1, anchor=None):
        return {
            "programme_name": name,
            "official_url": url,
            "official_evidence": {
                "source_hub": "https://hub.example/list",
                "anchor_text": anchor if anchor is not None else name,
                "corroborating_hubs": [],
                "source_count": count,
            },
        }

    def _seed(self, url, **extra):
        seed = {
            "source_id": "source-" + url.rsplit("/", 1)[-1],
            "programme_id": "programme-" + url.rsplit("/", 1)[-1],
            "programme_name": "Useful Fellowship",
            "organizer": "example.org",
            "official_url": url,
            "allowed_path_hints": ["program"],
            "check_cadence": "monthly",
        }
        seed.update(extra)
        return seed

    def test_static_fellowship_seeds_load_without_network(self):
        seeds = _static_seeds("fellowships")
        self.assertTrue(seeds)
        self.assertTrue(all(seed.get("official_url", "").startswith(("http://", "https://")) for seed in seeds))

    def test_merge_new_seed_keeps_existing_entries(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fellowships.json"
            existing = [self._seed("https://example.org/old-{}".format(index)) for index in range(3)]
            path.write_text(json.dumps(existing), encoding="utf-8")
            merged, stats = merge_generated_seeds(
                "fellowships", [self._seed("https://example.org/new")], path,
                raw_links=1, admitted=1, now="2026-10-10T00:00:00Z",
            )
            self.assertEqual(len(merged), 4)
            self.assertEqual(stats["new"], 1)
            self.assertEqual(stats["kept"], 3)

    def test_merge_refreshes_last_seen_and_preserves_first_seen(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fellowships.json"
            url = "https://example.org/program"
            path.write_text(json.dumps([self._seed(
                url, first_seen="2026-01-01T00:00:00Z", last_seen="2026-09-01T00:00:00Z",
            )]), encoding="utf-8")
            merged, stats = merge_generated_seeds(
                "fellowships", [self._seed(url, programme_name="Updated Fellowship")], path,
                now="2026-10-10T00:00:00Z",
            )
            self.assertEqual(merged[0]["first_seen"], "2026-01-01T00:00:00Z")
            self.assertEqual(merged[0]["last_seen"], "2026-10-10T00:00:00Z")
            self.assertEqual(stats["refreshed"], 1)

    def test_generated_seed_is_refreshed_when_re_found_with_env_enabled(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "community.json"
            url = "https://refresh.example/community"
            path.write_text(json.dumps([self._seed(
                url, programme_name="Refresh Community", first_seen="2026-01-01T00:00:00Z",
                last_seen="2026-09-01T00:00:00Z",
            )]), encoding="utf-8")
            candidate = self.candidate("Refresh Community", url)
            with patch.dict("os.environ", {"XLAKE_GENERATED_SEEDS_DIR": directory}, clear=False):
                static = _static_seeds("community")
                produced = candidates_to_seeds("community", [candidate], static)
                merged, stats = merge_generated_seeds(
                    "community", produced, path, now="2026-10-10T00:00:00Z",
                )
            self.assertNotIn(url, {seed["official_url"] for seed in static})
            self.assertEqual(stats["admitted"], 1)
            self.assertEqual(stats["refreshed"], 1)
            self.assertEqual(merged[0]["last_seen"], "2026-10-10T00:00:00Z")

    def test_community_admission_rejects_generic_fellowship_signal(self):
        html = "<title>Dalberg Fellowship</title><h1>Dalberg Fellowship</h1><p>Apply for this fellowship in technology.</p>"
        ok, reason, _ = admit_candidate(html, "https://dalberg.example/fellowship", "community")
        self.assertFalse(ok)
        self.assertIn(reason, {"no_programme_signal", "no_name"})

    def test_merge_expires_seed_older_than_56_days(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fellowships.json"
            now = datetime(2026, 10, 10, tzinfo=timezone.utc)
            old = (now - timedelta(days=60)).isoformat().replace("+00:00", "Z")
            path.write_text(json.dumps([self._seed("https://example.org/old", last_seen=old)]), encoding="utf-8")
            merged, stats = merge_generated_seeds(
                "fellowships", [], path, now=now,
            )
            self.assertEqual(merged, [])
            self.assertEqual(stats["expired"], 1)

    def test_merge_zero_successful_fetch_does_not_expire(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fellowships.json"
            now = datetime(2026, 10, 10, tzinfo=timezone.utc)
            old = (now - timedelta(days=60)).isoformat().replace("+00:00", "Z")
            path.write_text(json.dumps([self._seed("https://example.org/old", last_seen=old)]), encoding="utf-8")
            merged, stats = merge_generated_seeds(
                "fellowships", [], path, successful_fetches=0, now=now,
            )
            self.assertEqual(len(merged), 1)
            self.assertEqual(stats["expired"], 0)

    def test_csv_bare_url_extraction(self):
        links = parse_bare_urls(
            'Name, Link\n"Fellowship", https://example.org/fellowship/,\n'
            'Other, https://example.org/other).\n'
        )
        self.assertEqual(links, [
            ("https://example.org/fellowship/", ""),
            ("https://example.org/other", ""),
        ])

    def test_generic_and_short_anchors_are_dropped(self):
        candidates = [
            self.candidate("Apply now", "https://one.example/apply"),
            self.candidate("More", "https://two.example/more"),
            self.candidate("abc", "https://three.example/abc"),
            self.candidate("Good Fellowship", "https://four.example/program"),
        ]
        seeds = candidates_to_seeds("research", candidates, [])
        self.assertEqual([seed["programme_name"] for seed in seeds], ["Good Fellowship"])

    def test_social_and_aggregator_hosts_are_dropped(self):
        candidates = [
            self.candidate("Twitter Programme", "https://twitter.com/example/program"),
            self.candidate("Linked Programme", "https://www.linkedin.com/company/program"),
            self.candidate("Repository Programme", "https://github.com/org/repo"),
            self.candidate("Actual Programme", "https://program.example/apply"),
        ]
        seeds = candidates_to_seeds("research", candidates, [])
        self.assertEqual([seed["programme_name"] for seed in seeds], ["Actual Programme"])

    def test_tracking_params_fragment_and_existing_url_are_handled(self):
        candidate = self.candidate(
            "Tracked Fellowship",
            "HTTPS://WWW.Example.COM/path/?utm_source=x&fbclid=z&keep=yes#section",
        )
        existing = [{"official_url": "https://already.example/program"}]
        seeds = candidates_to_seeds(
            "research",
            [candidate, self.candidate("Duplicate", "https://already.example/program/?gclid=x")],
            existing,
        )
        self.assertEqual(len(seeds), 1)
        self.assertEqual(seeds[0]["official_url"], "https://www.example.com/path?keep=yes")
        self.assertEqual(seeds[0]["allowed_path_hints"], ["path"])

    def test_duplicate_keeps_higher_source_count(self):
        candidates = [
            self.candidate("Lower Name", "https://example.org/program?utm_medium=x", 1),
            self.candidate("Higher Name", "https://example.org/program", 4),
        ]
        seeds = candidates_to_seeds("research", candidates, [])
        self.assertEqual(len(seeds), 1)
        self.assertEqual(seeds[0]["programme_name"], "Higher Name")

    def test_per_host_cap_and_max_total(self):
        candidates = [
            self.candidate("Example One", "https://same.example/one", 10),
            self.candidate("Example Two", "https://same.example/two", 9),
            self.candidate("Example Three", "https://same.example/three", 8),
            self.candidate("Other One", "https://other.example/one", 7),
            self.candidate("Other Two", "https://other.example/two", 6),
        ]
        seeds = candidates_to_seeds("research", candidates, [], max_per_host=2, max_total=3)
        self.assertEqual(len(seeds), 3)
        self.assertLessEqual(sum("same.example" in seed["official_url"] for seed in seeds), 2)
        self.assertEqual(seeds[0]["programme_name"], "Example One")

    def test_ids_are_deterministic_and_schema_is_canonical(self):
        candidates = [
            self.candidate("Root Programme", "https://www.Root.Example/", 2),
            self.candidate("Path Programme", "https://path.example/a/b/c#x", 5),
        ]
        first = candidates_to_seeds("community", candidates, [])
        second = candidates_to_seeds("community", candidates, [])
        self.assertEqual(first, second)
        for seed in first:
            self.assertEqual(set(seed), {
                "source_id", "programme_id", "programme_name", "organizer",
                "official_url", "allowed_path_hints", "check_cadence",
            })
            self.assertTrue(all(seed[field] for field in (
                "source_id", "programme_id", "programme_name", "organizer",
                "official_url", "check_cadence",
            )))
            self.assertIsInstance(seed["allowed_path_hints"], list)
            self.assertTrue(all(isinstance(item, str) for item in seed["allowed_path_hints"]))
            self.assertTrue(seed["official_url"].startswith(("http://", "https://")))
        self.assertEqual(first[0]["allowed_path_hints"], ["a/b/c"])

    def test_max_total_is_hard_cap(self):
        candidates = [self.candidate("Programme {}".format(i), "https://{}.example/apply".format(i), 1) for i in range(10)]
        self.assertEqual(len(candidates_to_seeds("research", candidates, [], max_total=4)), 4)
    def test_new_category_seed_ids_and_static_registry_paths(self):
        for category, prefix in (
            ("fellowships", "hub-fellowships-"),
            ("scholarships", "hub-scholarships-"),
        ):
            seeds = candidates_to_seeds(
                category,
                [self.candidate("Useful {}".format(category), "https://official.example/{}/apply".format(category))],
                [],
            )
            self.assertEqual(len(seeds), 1)
            self.assertTrue(seeds[0]["source_id"].startswith(prefix))
            self.assertEqual(_default_hubs_path(category).name, {
                "fellowships": "fellowship_directories.json",
                "scholarships": "scholarship_directories.json",
            }[category])

    def test_directory_terms_do_not_change_research_policy(self):
        research_terms, _ = _policy("research")
        directory_terms, _ = _policy("fellowships")
        self.assertIsNone(research_terms.search("grant award scholarship"))
        self.assertIsNotNone(directory_terms.search("grant award scholarship program"))

    def test_github_hub_cap_is_150_and_other_hub_cap_is_25(self):
        def candidates(hub_id):
            return [Candidate(
                "https://official{}.example/fellowship".format(index),
                {hub_id: ("https://github.com/owner/list" if hub_id == "github" else "https://directory.example/list", "Fellowship {}".format(index))},
            ) for index in range(151)]

        github_hub = [{"hub_id": "github", "url": "https://github.com/owner/list"}]
        regular_hub = [{"hub_id": "regular", "url": "https://directory.example/list"}]
        self.assertEqual(len(_capped_candidates(candidates("github"), github_hub, 25)), 150)
        self.assertEqual(len(_capped_candidates(candidates("regular"), regular_hub, 25)), 25)

        fixtures = [
            ("https://example.org/blog/program", "url_pattern"),
            ("https://amazon.jobs/jobs/123", "url_pattern"),
            ("https://example.org/2023/07/program", "url_pattern"),
        ]
        for url, reason in fixtures:
            with self.subTest(url=url):
                ok, actual, _ = admit_candidate(
                    "<h1>Summer Fellowship</h1><p>Apply now</p>", url, "research"
                )
                self.assertFalse(ok)
                self.assertEqual(actual, reason)

    def test_admission_rejects_article_json_ld_and_meta(self):
        json_ld = '<script type="application/ld+json">{"@type":"JobPosting"}</script>'
        ok, reason, _ = admit_candidate(
            json_ld + "<h1>Engineering Internship</h1><p>Apply</p>",
            "https://example.org/internship", "research",
        )
        self.assertFalse(ok)
        self.assertEqual(reason, "article_or_job")
        ok, reason, _ = admit_candidate(
            '<meta property="og:type" content="article"><h1>Summer Fellowship</h1><p>Apply</p>',
            "https://example.org/fellowship", "research",
        )
        self.assertFalse(ok)
        self.assertEqual(reason, "article_or_job")

    def test_admission_rejects_generic_name(self):
        ok, reason, _ = admit_candidate(
            "<h1>Research</h1><p>Apply now</p>",
            "https://example.org/research", "research",
        )
        self.assertFalse(ok)
        self.assertEqual(reason, "no_name")

    def test_admission_rejects_missing_programme_signal(self):
        ok, reason, _ = admit_candidate(
            "<title>Research Opportunities</title><p>Apply now</p>",
            "https://opportunities.org/opportunities", "research",
        )
        self.assertFalse(ok)
        self.assertEqual(reason, "no_programme_signal")

    def test_admission_rejects_missing_application_signal(self):
        ok, reason, _ = admit_candidate(
            "<h1>Summer Fellowship</h1><p>About this computer science opportunity</p>",
            "https://example.org/fellowship", "research",
        )
        self.assertFalse(ok)
        self.assertEqual(reason, "no_application_signal")

    def test_admission_accepts_and_cleans_names(self):
        ok, reason, name = admit_candidate(
            "<title>MLH Fellowship | Major League Hacking</title>"
            "<p>Software engineering. Apply now</p>",
            "https://example.org/fellowship", "research",
        )
        self.assertTrue(ok)
        self.assertEqual(reason, "admitted")
        self.assertEqual(name, "MLH Fellowship")
        ok, reason, name = admit_candidate(
            "<h1>Founder Fuel - accelerator</h1><p>Technology startups. Apply</p>",
            "https://example.org/founder-fuel", "startup_founder",
        )
        self.assertTrue(ok)
        self.assertEqual(reason, "admitted")
        self.assertEqual(name, "Founder Fuel - accelerator")

    def test_admission_names_prefer_title_segments_over_slogans(self):
        fixtures = [
            (
                "<title>Oxygen Accelerator | Apply</title>"
                "<h1>EUR21,000 per team in exchange for 8% equity</h1>"
                "<p>Technology startups. Apply now</p>",
                "https://oxygen.example/program",
                "Oxygen Accelerator",
            ),
            (
                "<title>Founder Fuel | Canada's leading venture accelerator</title>"
                "<h1>We are Canada's leading venture accelerator</h1>"
                "<p>Technology startups. Apply</p>",
                "https://founderfuel.example/program",
                "Founder Fuel",
            ),
            (
                "<title>MLH Fellowship - Major League Hacking</title>"
                "<h1>Learn software engineering through open source projects.</h1>"
                "<p>Apply</p>",
                "https://mlh.example/fellowship",
                "MLH Fellowship",
            ),
            (
                "<title>Bhumi Fellowship | Two years. One Classroom. Influence Change.</title>"
                "<h1>Two years. One Classroom. Influence Change.</h1>"
                "<p>Software engineering. Apply</p>",
                "https://bhumi.example/fellowship",
                "Bhumi Fellowship",
            ),
            (
                "<title>Acerca de - 52 Parindey Fellowship</title>"
                "<h1>Acerca de</h1><p>Research fellowship. Apply</p>",
                "https://parindey.example/fellowship",
                "52 Parindey Fellowship",
            ),
            (
                "<title>Adivasi Awaaz Fellowship - For- Digital Storytelling</title>"
                "<h1>For- Digital Storytelling</h1><p>Apply</p>",
                "https://adivasi.example/fellowship",
                "Adivasi Awaaz Fellowship",
            ),
        ]
        for html, url, expected in fixtures:
            with self.subTest(url=url):
                ok, reason, name = admit_candidate(html, url, "research")
                self.assertTrue(ok)
                self.assertEqual(reason, "admitted")
                self.assertEqual(name, expected)

    def test_admission_uses_open_graph_candidates_in_order(self):
        ok, reason, name = admit_candidate(
            "<title>About | Apply</title>"
            '<meta property="og:site_name" content="Open Source Fellowship">'
            '<meta property="og:title" content="Open Source Fellowship | Apply">'
            "<h1>Welcome to our programme</h1><p>Apply now</p>",
            "https://opensource.example/fellowship", "open_source",
        )
        self.assertTrue(ok)
        self.assertEqual(reason, "admitted")
        self.assertEqual(name, "Open Source Fellowship")

    def test_admission_rejects_pages_with_only_slogans(self):
        ok, reason, name = admit_candidate(
            "<title>Two years. One Classroom. Influence Change.</title>"
            "<h1>Learn software engineering through open source projects.</h1>"
            "<p>Welcome to our site.</p>",
            "https://slogans.example/program", "research", "Welcome",
        )
        self.assertFalse(ok)
        self.assertEqual(reason, "no_name")
        self.assertEqual(name, "")

    def test_admission_tech_relevance_has_positive_and_negative_cases(self):
        fixtures = [
            ("<title>Software Engineering Fellowship</title><p>Apply now</p>", True),
            ("<title>Arts Scholarship</title><p>Apply now</p>", False),
            ("<title>TOPS Louisiana Scholarship</title><p>Apply now</p>", False),
            ("<title>Oregon Student Aid</title><p>Apply now</p>", False),
            ("<title>Community Fellowship</title><p>Apply now</p>", False),
            ("<title>Community Grant</title><p>Apply now</p>", False),
        ]
        for html, expected in fixtures:
            with self.subTest(html=html):
                ok, reason, _ = admit_candidate(html, "https://official.example/program", "scholarships")
                self.assertEqual(ok, expected)
                if not expected and reason not in {"no_name", "no_tech_signal"}:
                    self.fail("unexpected rejection reason: {}".format(reason))

    def test_admission_form_hosts_have_positive_and_negative_cases(self):
        blocked = (
            "https://tally.so/r/example",
            "https://forms.gle/example",
            "https://docs.google.com/forms/d/e/example/viewform",
            "https://typeform.com/to/example",
            "https://airtable.com/app/example",
            "https://jotform.com/123",
            "https://surveymonkey.com/r/example",
            "https://linktr.ee/example",
        )
        for url in blocked:
            with self.subTest(url=url):
                ok, reason, _ = admit_candidate(
                    "<title>Software Fellowship</title><p>Apply now</p>", url, "research"
                )
                self.assertFalse(ok)
                self.assertEqual(reason, "blocked_form_host")
        ok, reason, _ = admit_candidate(
            "<title>Software Fellowship</title><p>Apply now</p>",
            "https://official.example/software-fellowship", "research",
        )
        self.assertTrue(ok)
        self.assertEqual(reason, "admitted")

    def test_admission_stale_year_has_past_and_current_or_future_cases(self):
        fixtures = (
            ("<title>Summer Research Fellowship Program 2022</title><p>Apply now</p>", False),
            ("<title>Summer Research Fellowship Program 2026</title><p>Apply now</p>", True),
            ("<title>Summer Research Fellowship Program 2027</title><p>Apply now</p>", True),
            ("<title>Summer Research Fellowship 2022</title><p>Apply for 2026</p>", False),
        )
        for html, expected in fixtures:
            with self.subTest(html=html):
                ok, reason, _ = admit_candidate(
                    html, "https://official.example/summer-fellowship", "research"
                )
                self.assertEqual(ok, expected)
                if not expected:
                    self.assertEqual(reason, "stale_year")
        ok, reason, _ = admit_candidate(
            "<title>Summer Research Fellowship Program</title><p>Apply now</p>",
            "https://official.example/summer-fellowship-2025", "research",
        )
        self.assertFalse(ok)
        self.assertEqual(reason, "stale_year")

    def test_admission_stale_year_uses_title_and_heading_not_body(self):
        ok, reason, _ = admit_candidate(
            "<title>Summer Research Fellowship Programme 2021</title>"
            "<h1>Summer Research Fellowship Programme</h1>"
            "<nav>Applications for 2026</nav><p>Apply now</p>",
            "https://official.example/summer-research-fellowship-2021", "research",
        )
        self.assertFalse(ok)
        self.assertEqual(reason, "stale_year")
        ok, reason, _ = admit_candidate(
            "<title>Summer Research Fellowship Programme 2021</title>"
            "<h1>Summer Research Fellowship Programme 2026</h1><p>Apply now</p>",
            "https://official.example/summer-research-fellowship-2021", "research",
        )
        self.assertFalse(ok)
        self.assertEqual(reason, "stale_year")

    def test_admission_programme_word_and_directory_cases(self):
        rejected = (
            "IISER-K Summer Research Programme 2025",
            "ETH Zurich",
            "Fellowship Finder",
        )
        for title in rejected:
            with self.subTest(title=title):
                ok, _reason, _ = admit_candidate(
                    "<title>{}</title><h1>{}</h1>"
                    "<p>Computer science research. Apply now</p>".format(title, title),
                    "https://official.example/{}".format(title.casefold().replace(" ", "-")),
                    "fellowships",
                )
                self.assertFalse(ok)

        admitted = (
            "NVIDIA Graduate Fellowship",
            "Thiel Fellowship",
            "Google PhD fellowship program",
            "GEM Fellowship",
            "ACM Doctoral Dissertation Award",
            "KDE Mentorship",
            "WorldQuant BRAIN",
            "GREAT Program",
        )
        for title in admitted:
            with self.subTest(title=title):
                page_evidence = (
                    "WorldQuant BRAIN is a research program for students. "
                    if title == "WorldQuant BRAIN" else ""
                )
                ok, reason, name = admit_candidate(
                    "<title>{}</title><h1>{}</h1><p>{}Computer science research. "
                    "Apply now</p>".format(title, title, page_evidence),
                    "https://official.example/{}".format(title.casefold().replace(" ", "-")),
                    "fellowships",
                )
                self.assertTrue(ok)
                self.assertEqual(reason, "admitted")
                self.assertEqual(name, title)

    def test_admission_rejects_exact_stale_form_and_ambassador_examples(self):
        fixtures = (
            ("Summer Research Fellowship Programme 2021", "https://official.example/program", "stale_year"),
            ("Facebook Fellowship 101 - Previous outline for basics for PhDs", "https://official.example/fellowship", "stale_year"),
            ("GHC Scholarships", "https://official.example/2019-student-academic/scholarships", "stale_year"),
            ("Codechef Representative Program", "https://official.example/representative-program", "ambassador"),
            ("Apple PhD fellowship in AI/ML", "https://official.example/apple-scholars-aiml-2024", "stale_year"),
            ("Dell Campus Ambassador", "https://official.example/campus-ambassador", "ambassador"),
            ("ServiceNow Campus Leaders — Deadline: Rolling Ambassador Program", "https://official.example/campus-leaders", "ambassador"),
            ("NSF Dristtributed Research Experiences for Undergraduates (DREU)", "https://jotform.com/242948236029866", "blocked_form_host"),
        )
        for title, url, expected_reason in fixtures:
            with self.subTest(title=title):
                ok, reason, _ = admit_candidate(
                    "<title>{}</title><p>Apply now</p>".format(title), url, "research",
                )
                self.assertFalse(ok)
                self.assertEqual(reason, expected_reason)

    def test_admission_form_host_checks_final_url(self):
        ok, reason, _ = admit_candidate(
            "<title>Software Fellowship</title><p>Apply now</p>",
            "https://official.example/software-fellowship", "research",
            effective_url="https://forms.gle/example",
        )
        self.assertFalse(ok)
        self.assertEqual(reason, "blocked_form_host")

    def test_admission_keeps_expected_technical_fellowships_and_scholarships(self):
        fixtures = (
            ("NVIDIA Graduate Fellowship", "https://nvidia.example/graduate-fellowships"),
            ("Google PhD Fellowship", "https://google.example/phd-fellowship"),
            ("Women Techmakers Scholarship by Google", "https://womentechmakers.example/scholars"),
        )
        for title, url in fixtures:
            with self.subTest(title=title):
                ok, reason, name = admit_candidate(
                    "<title>{}</title><p>Computer science research. Apply now</p>".format(title), url, "scholarships",
                )
                self.assertTrue(ok)
                self.assertEqual(reason, "admitted")
                self.assertEqual(name, title)

    def test_community_admits_developer_student_club_and_ambassador(self):
        ok, reason, name = admit_candidate(
            "<title>Google Developer Student Clubs Lead</title>"
            "<p>Developer community applications. Apply now</p>",
            "https://developers.google.com/community/gdsc",
            "community",
        )
        self.assertTrue(ok)
        self.assertEqual(reason, "admitted")
        self.assertEqual(name, "Google Developer Student Clubs Lead")

        ok, reason, _ = admit_candidate(
            "<title>Google Campus Ambassador</title><p>Computer science. Apply now</p>",
            "https://google.example/campus-ambassador",
            "fellowships",
        )
        self.assertFalse(ok)
        self.assertEqual(reason, "ambassador")
