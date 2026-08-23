import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from categories.open_source.contributions import (
    CURATED_REPOS,
    MAX_COMMENTS,
    STALE_DAYS,
    build_row,
    collect,
    discover_repos,
    list_contributions,
    merge_contributions,
    parse_repo,
)


class TestContributionsCollector(unittest.TestCase):
    def test_collect_filters_issues_closes_absent_rows_and_preserves_lake_records(self):
        repo = "django/django"
        good_url = "https://github.com/django/django/issues/100"
        fake_issues = {
            repo: [
                {
                    "html_url": good_url,
                    "title": "Improve the documentation example",
                    "number": 100,
                    "labels": [{"name": "good first issue"}],
                    "state": "open",
                    "created_at": "2026-08-01T00:00:00Z",
                    "updated_at": "2026-08-17T00:00:00Z",
                },
                {
                    "html_url": "https://github.com/django/django/pull/101",
                    "title": "A pull request with the label",
                    "number": 101,
                    "labels": [{"name": "good first issue"}],
                    "state": "open",
                    "pull_request": {"url": "https://api.github.com/repos/django/django/pulls/101"},
                },
                {
                    "html_url": "https://github.com/django/django/issues/102",
                    "title": "Already assigned issue",
                    "number": 102,
                    "labels": [{"name": "good first issue"}],
                    "state": "open",
                    "assignees": [{"login": "contributor"}],
                    "assignee": {"login": "contributor"},
                },
            ]
        }
        old = {
            "record_type": "contribution",
            "contribution_id": "https://github.com/django/django/issues/99",
            "title": "Previously live issue",
            "repo": repo,
            "is_live": True,
            "first_seen": "2026-08-16T00:00:00+00:00",
        }
        programme = {"record_type": "programme", "programme_id": "programme-1", "is_live": True}
        job = {"record_type": "job", "url": "https://jobs.example/1", "title": "A job"}

        def fake_fetch(fetch_repo):
            return fake_issues[fetch_repo]

        checked_at = datetime(2026, 8, 18, 8, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as td:
            lake_path = os.path.join(td, "lake.json")
            with open(lake_path, "w") as handle:
                json.dump([programme, job, old], handle)

            result = collect(fetch=fake_fetch, checked_at=checked_at, lake_path=lake_path)

            self.assertEqual(result["repos_ok"], 1)
            self.assertEqual(result["repos_failed"], len(CURATED_REPOS) - 1)
            self.assertEqual(result["recently_active"], 1)
            self.assertEqual(result["new_this_month"], 1)
            with open(lake_path) as handle:
                lake = json.load(handle)

        contributions = [row for row in lake if row.get("record_type") == "contribution"]
        live = [row for row in contributions if row.get("is_live")]
        self.assertEqual(len(live), 1)
        self.assertEqual(live[0]["contribution_id"], good_url)
        self.assertEqual(live[0]["title"], "Improve the documentation example")
        self.assertEqual(live[0]["last_checked_at"], "2026-08-18T08:00:00+00:00")
        self.assertEqual(live[0]["posted_on"], "2026-08-01T00:00:00Z")
        self.assertEqual(live[0]["created_age_days"], 17)
        self.assertEqual(live[0]["activity_age_days"], 1)
        self.assertEqual(live[0]["is_new_this_month"], True)
        self.assertEqual(len(contributions), 2)
        absent = next(row for row in contributions if row["contribution_id"].endswith("/99"))
        self.assertFalse(absent["is_live"])
        self.assertTrue(absent["went_dead_at"])
        self.assertEqual([row for row in lake if row.get("record_type") == "programme"], [programme])
        self.assertEqual([row for row in lake if row.get("record_type") == "job"], [job])
        self.assertFalse(any(row["contribution_id"].endswith("/101") for row in contributions))
        self.assertFalse(any(row["contribution_id"].endswith("/102") for row in contributions))

    def test_build_row_marks_recent_and_older_issues(self):
        checked_at = "2026-08-18T08:00:00+00:00"
        recent = {
            "html_url": "https://github.com/django/django/issues/103",
            "title": "Recent documentation issue",
            "number": 103,
            "labels": [{"name": "good first issue"}],
            "created_at": "2026-08-14T08:00:00Z",
            "updated_at": "2026-08-17T00:00:00Z",
        }
        older = {
            "html_url": "https://github.com/django/django/issues/104",
            "title": "Older documentation issue",
            "number": 104,
            "labels": [{"name": "good first issue"}],
            "created_at": "2026-08-01T00:00:00Z",
            "updated_at": "2026-08-10T00:00:00Z",
        }

        recent_row = build_row("django/django", recent, checked_at)
        older_row = build_row("django/django", older, checked_at)

        self.assertEqual(recent_row["created_age_days"], 4)
        self.assertEqual(recent_row["activity_age_days"], 1)
        self.assertTrue(recent_row["is_new_this_month"])
        self.assertTrue(recent_row["is_recently_active"])
        self.assertEqual(recent_row["posted_on"], recent["created_at"])
        self.assertEqual(older_row["created_age_days"], 17)
        self.assertEqual(older_row["activity_age_days"], 8)
        self.assertTrue(older_row["is_new_this_month"])
        self.assertFalse(older_row["is_recently_active"])
        self.assertEqual(older_row["posted_on"], older["created_at"])

    def test_freshness_boundaries_and_unparseable_dates(self):
        checked_at = "2026-08-18T08:00:00+00:00"
        base = {
            "html_url": "https://github.com/django/django/issues/105",
            "title": "Boundary issue",
            "number": 105,
            "labels": [],
            "state": "open",
        }

        def row(created_at, updated_at, number):
            issue = dict(base, html_url="https://github.com/django/django/issues/{}".format(number), number=number)
            issue.update(created_at=created_at, updated_at=updated_at)
            return build_row("django/django", issue, checked_at)

        same_day = row("2026-08-18T08:00:00Z", "2026-08-15T08:00:00Z", 106)
        month_boundary = row("2026-07-19T08:00:00Z", "2026-08-14T08:00:00Z", 107)
        outside_month = row("2026-07-18T08:00:00Z", "2026-08-15T08:00:00Z", 108)
        future = row("2026-08-18T09:00:00Z", "not-a-timestamp", 109)
        missing = row(None, None, 110)

        self.assertEqual((same_day["created_age_days"], same_day["activity_age_days"]), (0, 3))
        self.assertTrue(same_day["is_new_this_month"])
        self.assertTrue(same_day["is_recently_active"])
        self.assertEqual((month_boundary["created_age_days"], month_boundary["activity_age_days"]), (30, 4))
        self.assertTrue(month_boundary["is_new_this_month"])
        self.assertFalse(month_boundary["is_recently_active"])
        self.assertEqual((outside_month["created_age_days"], outside_month["activity_age_days"]), (31, 3))
        self.assertFalse(outside_month["is_new_this_month"])
        self.assertTrue(outside_month["is_recently_active"])
        self.assertEqual(future["created_age_days"], -1)
        self.assertFalse(future["is_new_this_month"])
        self.assertIsNone(future["activity_age_days"])
        self.assertFalse(future["is_recently_active"])
        self.assertIsNone(missing["created_age_days"])
        self.assertIsNone(missing["activity_age_days"])
        self.assertFalse(missing["is_new_this_month"])
        self.assertFalse(missing["is_recently_active"])

    def test_difficulty_is_derived_from_labels(self):
        checked_at = "2026-08-18T08:00:00+00:00"
        issue = {
            "html_url": "https://github.com/django/django/issues/111",
            "title": "Difficulty issue",
            "number": 111,
            "labels": [{"name": "Help Wanted"}, {"name": "Good first issue"}],
        }
        beginner = build_row("django/django", issue, checked_at)
        issue["html_url"] = "https://github.com/django/django/issues/112"
        issue["number"] = 112
        issue["labels"] = [{"name": "medium"}]
        intermediate = build_row("django/django", issue, checked_at)
        issue["html_url"] = "https://github.com/django/django/issues/113"
        issue["number"] = 113
        issue["labels"] = [{"name": "documentation"}]
        default = build_row("django/django", issue, checked_at)

        self.assertEqual(beginner["difficulty"], "beginner")
        self.assertEqual(beginner["difficulty_signal"], "Good first issue")
        self.assertEqual(intermediate["difficulty"], "intermediate")
        self.assertEqual(intermediate["difficulty_signal"], "medium")
        self.assertEqual(default["difficulty"], "beginner")
        self.assertEqual(default["difficulty_signal"], "default")
        self.assertEqual(default["labels"], ["documentation"])

    def test_language_annotation_is_present_for_every_curated_repo(self):
        self.assertEqual(len(CURATED_REPOS), 45)
        for repo, language in CURATED_REPOS:
            issue = {
                "html_url": "https://github.com/{}/issues/1".format(repo),
                "title": "Language issue",
                "number": 1,
                "labels": [],
            }
            self.assertEqual(build_row(repo, issue, "2026-08-18T08:00:00Z")["language"], language)

    def test_list_contributions_filters_canonical_lake(self):
        rows = [
            {
                "record_type": "contribution",
                "title": "Python beginner",
                "official_url": "https://github.com/a/a/issues/1",
                "language": "Python",
                "difficulty": "beginner",
                "is_recently_active": True,
                "is_new_this_month": True,
            },
            {
                "record_type": "contribution",
                "title": "Java intermediate",
                "official_url": "https://github.com/b/b/issues/2",
                "language": "Java",
                "difficulty": "intermediate",
                "is_recently_active": False,
                "is_new_this_month": True,
            },
            {"record_type": "programme", "title": "Not a contribution"},
        ]
        with tempfile.TemporaryDirectory() as td:
            lake_path = os.path.join(td, "lake.json")
            with open(lake_path, "w") as handle:
                json.dump(rows, handle)
            with patch("categories.open_source.contributions.OPPORTUNITIES_PATH", lake_path):
                filtered = list_contributions(
                    language="pYtHoN",
                    difficulty="beginner",
                    recently_active=True,
                    new_this_month=True,
                )
                all_contributions = list_contributions()

        self.assertEqual([row["title"] for row in filtered], ["Python beginner"])
        self.assertEqual(len(all_contributions), 2)

    def test_failed_repo_is_not_closed(self):
        repo = "django/django"
        old = {
            "record_type": "contribution",
            "contribution_id": "https://github.com/django/django/issues/99",
            "repo": repo,
            "is_live": True,
        }
        with tempfile.TemporaryDirectory() as td:
            lake_path = os.path.join(td, "lake.json")
            with open(lake_path, "w") as handle:
                json.dump([old], handle)
            merged = merge_contributions({}, set(), lake_path=lake_path, now="2026-08-18T08:00:00+00:00")
            self.assertTrue(merged[0]["is_live"])
            self.assertNotIn("went_dead_at", merged[0])
            self.assertNotIn("needs_confirmation", merged[0])
            self.assertNotIn("liveness_reason", merged[0])

    def test_new_row_seen_this_run_is_live_and_not_needing_confirmation(self):
        now = "2026-08-18T08:00:00+00:00"
        row = {
            "record_type": "contribution",
            "contribution_id": "https://github.com/owner/repo/issues/1",
            "repo": "owner/repo",
        }
        with tempfile.TemporaryDirectory() as td:
            lake_path = os.path.join(td, "lake.json")
            with open(lake_path, "w") as handle:
                json.dump([], handle)
            merged = merge_contributions(
                {"owner/repo": [row]}, set(), lake_path=lake_path, now=now,
            )

        self.assertTrue(merged[0]["is_live"])
        self.assertFalse(merged[0]["needs_confirmation"])
        self.assertEqual(merged[0]["last_seen"], now)
        self.assertNotIn("liveness_reason", merged[0])

    def test_stale_activity_retires_live_rows_without_deleting_or_touching_other_records(self):
        now = "2026-08-23T00:00:00+00:00"
        stale = {
            "record_type": "contribution",
            "contribution_id": "https://github.com/owner/repo/issues/stale",
            "repo": "owner/repo",
            "updated_at": "2026-02-04T00:00:00+00:00",
            "last_seen": "2026-08-20T00:00:00+00:00",
            "status": "open",
            "is_live": True,
            "needs_confirmation": False,
        }
        recent = {
            "record_type": "contribution",
            "contribution_id": "https://github.com/owner/repo/issues/recent",
            "repo": "owner/repo",
            "updated_at": "2026-08-18T00:00:00+00:00",
            "last_seen": "2026-08-20T00:00:00+00:00",
            "status": "open",
            "is_live": True,
            "needs_confirmation": False,
        }
        programme = {
            "record_type": "programme",
            "programme_id": "programme-pass-through",
            "title": "Unchanged programme",
            "metadata": {"value": 1},
        }

        with tempfile.TemporaryDirectory() as td:
            lake_path = os.path.join(td, "lake.json")
            with open(lake_path, "w") as handle:
                json.dump([stale, recent, programme], handle)
            merged = merge_contributions({}, set(), lake_path=lake_path, now=now)
            with open(lake_path) as handle:
                lake = json.load(handle)

        by_id = {row.get("contribution_id"): row for row in merged}
        retired = by_id[stale["contribution_id"]]
        retained = by_id[recent["contribution_id"]]
        self.assertFalse(retired["is_live"])
        self.assertTrue(retired["needs_confirmation"])
        self.assertEqual(retired["liveness_reason"], "stale_activity")
        self.assertEqual(retired["last_seen"], stale["last_seen"])
        self.assertEqual(retired["status"], stale["status"])
        self.assertNotIn("went_dead_at", retired)
        self.assertTrue(retained["is_live"])
        self.assertFalse(retained["needs_confirmation"])
        self.assertEqual(
            next(row for row in lake if row.get("programme_id") == programme["programme_id"]),
            programme,
        )

    def test_absent_row_from_successfully_fetched_repo_is_confirmed_closed(self):
        now = "2026-08-18T08:00:00+00:00"
        old = {
            "record_type": "contribution",
            "contribution_id": "https://github.com/owner/repo/issues/2",
            "repo": "owner/repo",
            "is_live": True,
            "last_seen": "2026-08-17T08:00:00+00:00",
            "needs_confirmation": True,
            "liveness_reason": "not_reconfirmed",
        }
        with tempfile.TemporaryDirectory() as td:
            lake_path = os.path.join(td, "lake.json")
            with open(lake_path, "w") as handle:
                json.dump([old], handle)
            merged = merge_contributions(
                {"owner/repo": []}, {"owner/repo"}, lake_path=lake_path, now=now,
            )

        self.assertFalse(merged[0]["is_live"])
        self.assertEqual(merged[0]["went_dead_at"], now)
        self.assertFalse(merged[0]["needs_confirmation"])
        self.assertNotIn("liveness_reason", merged[0])

    def test_absent_row_from_unfetched_repo_decays_after_reconfirmation_window(self):
        now = "2026-08-18T08:00:00+00:00"
        old = {
            "record_type": "contribution",
            "contribution_id": "https://github.com/owner/repo/issues/3",
            "repo": "owner/repo",
            "is_live": True,
            "last_seen": "2026-08-10T08:00:00+00:00",
        }
        with tempfile.TemporaryDirectory() as td:
            lake_path = os.path.join(td, "lake.json")
            with open(lake_path, "w") as handle:
                json.dump([old], handle)
            merged = merge_contributions({}, set(), lake_path=lake_path, now=now)

        self.assertEqual(len(merged), 1)
        self.assertFalse(merged[0]["is_live"])
        self.assertTrue(merged[0]["needs_confirmation"])
        self.assertEqual(merged[0]["liveness_reason"], "not_reconfirmed")
        self.assertNotIn("went_dead_at", merged[0])

    def test_absent_row_from_unfetched_repo_stays_live_within_window(self):
        now = "2026-08-18T08:00:00+00:00"
        old = {
            "record_type": "contribution",
            "contribution_id": "https://github.com/owner/repo/issues/4",
            "repo": "owner/repo",
            "is_live": True,
            "last_seen": "2026-08-15T08:00:00+00:00",
            "needs_confirmation": False,
        }
        with tempfile.TemporaryDirectory() as td:
            lake_path = os.path.join(td, "lake.json")
            with open(lake_path, "w") as handle:
                json.dump([old], handle)
            merged = merge_contributions({}, set(), lake_path=lake_path, now=now)

        self.assertTrue(merged[0]["is_live"])
        self.assertFalse(merged[0]["needs_confirmation"])
        self.assertEqual(merged[0]["last_seen"], old["last_seen"])
        self.assertNotIn("liveness_reason", merged[0])

    def test_reappearing_row_self_heals_prior_reconfirmation_decay(self):
        now = "2026-08-18T08:00:00+00:00"
        issue_id = "https://github.com/owner/repo/issues/5"
        old = {
            "record_type": "contribution",
            "contribution_id": issue_id,
            "repo": "owner/repo",
            "is_live": False,
            "last_seen": "2026-08-10T08:00:00+00:00",
            "needs_confirmation": True,
            "liveness_reason": "not_reconfirmed",
        }
        row = {
            "record_type": "contribution",
            "contribution_id": issue_id,
            "repo": "owner/repo",
            "title": "Rediscovered issue",
        }
        with tempfile.TemporaryDirectory() as td:
            lake_path = os.path.join(td, "lake.json")
            with open(lake_path, "w") as handle:
                json.dump([old], handle)
            merged = merge_contributions(
                {"owner/repo": [row]}, set(), lake_path=lake_path, now=now,
            )

        self.assertTrue(merged[0]["is_live"])
        self.assertFalse(merged[0]["needs_confirmation"])
        self.assertEqual(merged[0]["last_seen"], now)
        self.assertNotIn("liveness_reason", merged[0])

    def test_parse_repo_drops_stale_and_discussion_heavy_issues_and_sorts_kept_rows(self):
        checked_at = datetime(2026, 8, 18, 8, 0, tzinfo=timezone.utc)
        base = {
            "title": "Contribution issue",
            "labels": [{"name": "good first issue"}],
            "state": "open",
            "created_at": "2026-08-01T00:00:00Z",
        }

        def issue(number, updated_at, **extra):
            return dict(
                base,
                html_url="https://github.com/owner/repo/issues/{}".format(number),
                number=number,
                updated_at=updated_at,
                **extra,
            )

        rows = parse_repo(
            "owner/repo",
            [
                issue(201, "2026-04-19T00:00:00Z"),
                issue(202, "2026-08-17T00:00:00Z", comments=MAX_COMMENTS + 1),
                issue(203, "2026-08-18T06:00:00Z", comments=MAX_COMMENTS),
                issue(204, "2026-08-18T07:00:00Z", comments=0),
                issue(
                    205,
                    "2026-08-18T07:30:00Z",
                    pull_request={"url": "https://api.github.com/repos/owner/repo/pulls/205"},
                ),
                issue(
                    206,
                    "2026-08-18T07:30:00Z",
                    assignee={"login": "contributor"},
                    assignees=[{"login": "contributor"}],
                ),
            ],
            checked_at,
        )

        self.assertEqual([row["issue_number"] for row in rows], [204, 203])
        self.assertEqual(rows[0]["updated_at"], "2026-08-18T07:00:00Z")
        self.assertEqual(rows[1]["updated_at"], "2026-08-18T06:00:00Z")
        self.assertGreater(STALE_DAYS, 0)

    def test_discover_repos_query_restricts_results_to_recently_updated_repositories(self):
        from categories.open_source import contributions as module

        queries = []

        def fake_search(query, token):
            queries.append(query)
            return {"items": []}

        with patch.object(module, "CURATED_REPOS", ()), \
                patch.object(module, "DISCOVERY_LANGUAGES", ["Python"]), \
                patch.object(module, "_discovery_sleep"):
            discover_repos(
                "test-token",
                datetime(2026, 8, 18, 8, 0, tzinfo=timezone.utc),
                search_fetch=fake_search,
            )

        self.assertEqual(len(queries), 1)
        self.assertIn("updated:>=2026-04-20", queries[0])
        self.assertIn("good-first-issues:>2", queries[0])
        self.assertIn("stars:>=500", queries[0])

if __name__ == "__main__":
    unittest.main()

    def test_discover_repos_skips_search_without_token(self):
        calls = []

        def fake_search(query, token):
            calls.append((query, token))
            return {"items": []}

        repos = discover_repos(
            None,
            datetime(2026, 8, 18, tzinfo=timezone.utc),
            search_fetch=fake_search,
        )

        self.assertEqual(repos, [])
        self.assertEqual(calls, [])

    def test_discover_repos_parses_deduplicates_and_caps_results(self):
        from categories.open_source import contributions as module

        responses = [{"items": [
            {"full_name": "OWNER/CURATED", "language": "Python", "stargazers_count": 900},
            {"full_name": "alpha/one", "language": "Python", "stargazers_count": 700},
            {"full_name": "beta/two", "language": None, "stargazers_count": "600"},
            {"full_name": "alpha/one", "language": "Python", "stargazers_count": 700},
        ]}]
        with patch.object(module, "CURATED_REPOS", (("owner/curated", "Python"),)), \
                patch.object(module, "DISCOVERY_LANGUAGES", ["Python"]), \
                patch.object(module, "DISCOVERY_MAX_REPOS", 2), \
                patch.object(module, "_discovery_sleep"):
            repos = discover_repos(
                "test-token",
                datetime(2026, 8, 18, tzinfo=timezone.utc),
                search_fetch=lambda query, token: responses.pop(0),
            )

        self.assertEqual(repos, [
            {"full_name": "alpha/one", "language": "Python", "stars": 700},
            {"full_name": "beta/two", "language": "Python", "stars": 600},
        ])

    def test_discover_repos_returns_partial_results_on_search_error(self):
        from categories.open_source import contributions as module

        def fake_search(query, token):
            if "language:Go" in query:
                raise RuntimeError("HTTP Error 403: secondary rate limit")
            return {"items": [{
                "full_name": "alpha/one",
                "language": "Python",
                "stargazers_count": 700,
            }]}

        with patch.object(module, "CURATED_REPOS", ()), \
                patch.object(module, "DISCOVERY_LANGUAGES", ["Python", "Go"]), \
                patch.object(module, "_discovery_sleep"):
            repos = discover_repos(
                "test-token",
                datetime(2026, 8, 18, tzinfo=timezone.utc),
                search_fetch=fake_search,
            )

        self.assertEqual(len(repos), 1)
        self.assertEqual(repos[0]["full_name"], "alpha/one")

    def test_collect_includes_curated_and_discovered_provenance(self):
        from categories.open_source import contributions as module

        issue_by_repo = {}
        with patch.object(module, "CURATED_REPOS", (("owner/curated", "Python"),)), \
                patch.object(module, "DISCOVERY_LANGUAGES", ["Go"]), \
                patch.object(module, "_discovery_sleep"), \
                patch.dict(os.environ, {"GITHUB_TOKEN": "test-token"}, clear=False):
            def fake_search(query, token):
                return {"items": [{
                    "full_name": "owner/discovered",
                    "language": "Go",
                    "stargazers_count": 1234,
                }]}

            def fake_fetch(repo):
                issue = {
                    "html_url": "https://github.com/{}/issues/1".format(repo),
                    "title": "A contribution issue",
                    "number": 1,
                    "labels": [{"name": "good first issue"}],
                    "state": "open",
                }
                issue_by_repo[repo] = issue
                return [issue]

            with tempfile.TemporaryDirectory() as td:
                lake_path = os.path.join(td, "lake.json")
                with open(lake_path, "w") as handle:
                    json.dump([], handle)
                result = collect(
                    fetch=fake_fetch,
                    search_fetch=fake_search,
                    checked_at=datetime(2026, 8, 18, tzinfo=timezone.utc),
                    lake_path=lake_path,
                )
                with open(lake_path) as handle:
                    rows = json.load(handle)

        self.assertEqual(result["repos_curated"], 1)
        self.assertEqual(result["repos_discovered"], 1)
        self.assertEqual(result["total_issues_collected"], 2)
        self.assertEqual(
            {row["discovery_source"] for row in rows},
            {"curated", "search"},
        )
        discovered = next(row for row in rows if row["repo"] == "owner/discovered")
        self.assertEqual(discovered["language"], "Go")
        self.assertEqual(discovered["repo_stars"], 1234)

    def test_build_row_sets_discovery_provenance(self):
        issue = {
            "html_url": "https://github.com/owner/repo/issues/1",
            "title": "A contribution issue",
            "number": 1,
            "labels": [],
        }
        row = build_row(
            "owner/repo",
            issue,
            "2026-08-18T08:00:00Z",
            language="Rust",
            discovery_source="search",
            repo_stars=501,
        )

        self.assertEqual(row["language"], "Rust")
        self.assertEqual(row["discovery_source"], "search")
        self.assertEqual(row["repo_stars"], 501)
