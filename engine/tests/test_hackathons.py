import json
import os
import sys
import tempfile
from unittest import mock
import unittest
from unittest.mock import patch
from datetime import date, datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from categories.hackathons.hackathons import (
    clean_description,
    collect,
    compute_status,
    enrich_rows,
    merge_hackathons,
    normalize_devpost,
    normalize_mlh,
    normalize_unstop,
    parse_devpost_dates,
    parse_event_page,
    parse_time_left,
    region_for,
    unstop_eligibility_text,
)
from pipeline.publish_supabase import is_serving, map_row, stable_id


FIXTURE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fixtures", "hackathons")
CHECKED_AT = datetime(2026, 8, 21, tzinfo=timezone.utc)
NO_PAGE = lambda url: None  # noqa: E731 - never touch the network in tests


def _fixture_json(name):
    with open(os.path.join(FIXTURE_DIR, name)) as handle:
        return json.load(handle)


def _fixture_html():
    with open(os.path.join(FIXTURE_DIR, "mlh.html")) as handle:
        return handle.read()


def _fixture_next_year_html():
    with open(os.path.join(FIXTURE_DIR, "mlh-next.html")) as handle:
        return handle.read()


def _fake_fetchers():
    unstop_items = _fixture_json("unstop.json")
    return (
        lambda: _fixture_json("devpost.json"),
        lambda _checked_at=None: [
            (_fixture_html(), "https://mlh.io/seasons/2026/events"),
            (_fixture_next_year_html(), "https://mlh.io/seasons/2027/events"),
        ],
        lambda: {"data": {"current_page": 1, "last_page": 1, "data": unstop_items}},
    )


class TestHackathonsCollector(unittest.TestCase):
    def setUp(self):
        from unittest.mock import patch
        from categories.hackathons import hackathons as module
        patcher = patch.object(module, "_devfolio_fetch_default", lambda: [])
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_devfolio_official_site_listed_on_and_dedupe(self):
        from categories.hackathons.hackathons import normalize_devfolio, dedupe_rows, build_row, region_for
        hit = {"_source": {
            "name": "BIOS V2", "slug": "biosv2", "starts_at": "2026-10-30T06:30:00+00:00",
            "ends_at": "2026-11-01T06:30:00+00:00", "is_online": False, "city": "Patiala",
            "state": "Punjab", "country": "India", "team_min": 2, "team_size": 4,
            "timezone": "Asia/Calcutta", "themes": [{"theme": {"name": "AI"}}],
            "hackathon_setting": {"reg_ends_at": "2026-11-20T18:29:00+00:00", "site": "https://bios.example.org/", "logo": "https://x/logo.png"},
        }}
        rows = normalize_devfolio({"hits": {"hits": [hit]}}, "2026-10-19T00:00:00+00:00")
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["official_url"], "https://bios.example.org/")
        self.assertEqual(row["source_kind"], "official")
        self.assertEqual(row["hackathon_id"], "https://biosv2.devfolio.co/")
        self.assertEqual((row["team_min"], row["team_max"]), (2, 4))
        self.assertEqual(row["region"], "India")
        other = dict(row, source="devpost", official_url="https://bios.devpost.com/", hackathon_id="https://bios.devpost.com/",
                     listed_on=[{"name": "devpost", "url": "https://bios.devpost.com/"}], source_kind="aggregator")
        merged = dedupe_rows({"a": row, "b": other})
        self.assertEqual(len(merged), 1)
        self.assertEqual(len(next(iter(merged.values()))["listed_on"]), 2)
        self.assertEqual(region_for(location="Fort Worth"), "US")

    def test_merge_safety_preserves_all_non_hackathon_records(self):
        seeded = [
            {"title": "A job", "official_url": "https://jobs.example/1"},
            {"record_type": "programme", "programme_id": "programme-1"},
            {"record_type": "contribution", "contribution_id": "contribution-1"},
            {"record_type": "programme", "category": "research", "programme_id": "research-1"},
        ]
        devpost, mlh, unstop = _fake_fetchers()
        with tempfile.TemporaryDirectory() as td:
            lake_path = os.path.join(td, "lake.json")
            with open(lake_path, "w") as handle:
                json.dump(seeded, handle)
            with patch("categories.hackathons.hackathons.load_verifications", return_value=[]):
                result = collect(devpost, mlh, unstop, checked_at=CHECKED_AT, lake_path=lake_path, page_fetch=NO_PAGE)
            with open(lake_path) as handle:
                lake = json.load(handle)
        self.assertEqual(result["total_surfaced"], 8)
        for record in seeded:
            self.assertIn(record, lake)
        self.assertGreater(len([row for row in lake if row.get("record_type") == "hackathon"]), 0)

    def test_parse_devpost_dates_exact_cases(self):
        cases = {
            "Jul 31 - Oct 01, 2026": ("2026-07-31", "2026-10-01"),
            "Aug 04 - 31, 2026": ("2026-08-04", "2026-08-31"),
            "Aug 04, 2026": ("2026-08-04", "2026-08-04"),
            "Dec 15, 2025 - Jan 20, 2026": ("2025-12-15", "2026-01-20"),
            "Dec 15 - Jan 20, 2026": ("2025-12-15", "2026-01-20"),
            "": (None, None),
            "to be announced": (None, None),
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(parse_devpost_dates(text), expected)

    def test_freshness_sort_and_unparseable_devpost_date(self):
        devpost, mlh, unstop = _fake_fetchers()
        with tempfile.TemporaryDirectory() as td:
            lake_path = os.path.join(td, "lake.json")
            with patch("categories.hackathons.hackathons.load_verifications", return_value=[]):
                result = collect(devpost, mlh, unstop, checked_at=CHECKED_AT, lake_path=lake_path, page_fetch=NO_PAGE)
            with open(lake_path) as handle:
                rows = json.load(handle)
        hackathons = [row for row in rows if row.get("record_type") == "hackathon"]
        self.assertEqual(result["devpost"], 3)
        self.assertEqual(result["mlh"], 3)
        self.assertEqual(result["unstop"], 2)
        urls = {row["official_url"] for row in hackathons}
        self.assertNotIn("https://example.devpost.com/past-build", urls)
        self.assertNotIn("https://events.mlh.io/past", urls)
        self.assertIn("https://events.mlh.io/next-season", urls)
        self.assertNotIn("https://unstop.com/hackathon/past-hack", urls)
        sort_keys = [row.get("start_date") or row.get("registration_deadline") or row.get("end_date") or "9999" for row in hackathons]
        self.assertEqual(sort_keys, sorted(sort_keys))
        tba = next(row for row in hackathons if row["title"].startswith("Date To Be Announced"))
        self.assertIsNone(tba["start_date"])
        self.assertIsNone(tba["end_date"])
        self.assertEqual(tba["official_evidence"]["submission_period_dates"], "to be announced")

    def test_row_schema_has_hackathon_identity_and_official_url(self):
        devpost, mlh, unstop = _fake_fetchers()
        with tempfile.TemporaryDirectory() as td:
            lake_path = os.path.join(td, "lake.json")
            with patch("categories.hackathons.hackathons.load_verifications", return_value=[]):
                collect(devpost, mlh, unstop, checked_at=CHECKED_AT, lake_path=lake_path, page_fetch=NO_PAGE)
            with open(lake_path) as handle:
                rows = json.load(handle)
        hackathons = [row for row in rows if row.get("record_type") == "hackathon"]
        self.assertTrue(hackathons)
        for row in hackathons:
            self.assertEqual(row["record_type"], "hackathon")
            self.assertEqual(row["category"], "hackathons")
            self.assertEqual(row["opportunity_type"], "hackathon")
            self.assertEqual(row["hackathon_id"], row["application_url"])
            self.assertTrue(row["official_url"].startswith("http"))

    def test_mlh_strips_utm_parameters(self):
        html = _fixture_html()
        rows = normalize_mlh(html, CHECKED_AT, "https://mlh.io/seasons/2026/events")
        self.assertTrue(rows)
        for row in rows:
            self.assertNotIn("utm_", row["official_url"])
        self.assertTrue(any("ref=calendar" in row["official_url"] for row in rows))

    def test_mlh_normalizes_location_and_reads_digital_format(self):
        html = """
        <a itemscope itemtype="http://schema.org/Event" href="https://events.mlh.io/digital" data-format="digital">
          <h4 itemprop="name">MLH Digital Hack Day</h4>
          <meta itemprop="startDate" content="2026-09-01T09:00:00Z">
          <meta itemprop="endDate" content="2026-09-02T23:59:00Z">
          <span itemprop="location"></span>
        </a>
        <a itemscope itemtype="http://schema.org/Event" href="https://events.mlh.io/hyderabad">
          <h4 itemprop="name">MLH Hyderabad Hack Day</h4>
          <meta itemprop="startDate" content="2026-09-03T09:00:00Z">
          <meta itemprop="endDate" content="2026-09-04T23:59:00Z">
          <span itemprop="location"> Hyderabad ,   Telangana, IN </span>
        </a>
        """
        rows = normalize_mlh(html, CHECKED_AT)
        digital = next(row for row in rows if row["official_url"].endswith("/digital"))
        hyderabad = next(row for row in rows if row["official_url"].endswith("/hyderabad"))
        self.assertTrue(digital["is_online"])
        self.assertIsNone(digital["location"])
        self.assertEqual(hyderabad["location"], "Hyderabad, Telangana, IN")

    def test_wall_clock_expiry_retires_persisted_live_past_event(self):
        seeded = {
            "record_type": "hackathon", "hackathon_id": "past-event",
            "official_url": "https://example.test/past-event", "source": "devpost",
            "last_seen": "2026-08-20T00:00:00+00:00", "is_live": True,
            "end_date": "2026-08-01", "needs_confirmation": False,
        }
        with tempfile.TemporaryDirectory() as td:
            lake_path = os.path.join(td, "lake.json")
            with open(lake_path, "w") as handle:
                json.dump([seeded], handle)
            merged = merge_hackathons(
                {}, set(), lake_path,
                now="2026-08-21T00:00:00+00:00", today=date(2026, 8, 23),
            )
        self.assertFalse(merged[0]["is_live"])
        self.assertFalse(merged[0]["needs_confirmation"])
        self.assertFalse(is_serving(merged[0]))
        self.assertEqual(merged[0]["status"], "ended")
        self.assertEqual(merged[0]["liveness_reason"], "event_ended")

    def test_wall_clock_expiry_ignores_past_registration_deadline(self):
        seeded = {
            "record_type": "hackathon", "hackathon_id": "future-event",
            "official_url": "https://example.test/future-event", "source": "devpost",
            "last_seen": "2026-08-20T00:00:00+00:00", "is_live": True,
            "end_date": "2026-12-01", "registration_deadline": "2026-08-01",
        }
        with tempfile.TemporaryDirectory() as td:
            lake_path = os.path.join(td, "lake.json")
            with open(lake_path, "w") as handle:
                json.dump([seeded], handle)
            merged = merge_hackathons(
                {}, set(), lake_path,
                now="2026-08-21T00:00:00+00:00", today=date(2026, 8, 23),
            )
        self.assertTrue(merged[0]["is_live"])
        self.assertNotEqual(merged[0].get("liveness_reason"), "event_ended")

    def test_wall_clock_expiry_preserves_non_hackathon_row(self):
        programme = {
            "record_type": "programme", "programme_id": "programme-1",
            "title": "A programme", "is_live": True,
        }
        seeded = [programme, {
            "record_type": "hackathon", "hackathon_id": "past-event",
            "official_url": "https://example.test/past-event", "source": "devpost",
            "last_seen": "2026-08-20T00:00:00+00:00", "is_live": True,
            "end_date": "2026-08-01",
        }]
        with tempfile.TemporaryDirectory() as td:
            lake_path = os.path.join(td, "lake.json")
            with open(lake_path, "w") as handle:
                json.dump(seeded, handle)
            merge_hackathons(
                {}, set(), lake_path,
                now="2026-08-21T00:00:00+00:00", today=date(2026, 8, 23),
            )
            with open(lake_path) as handle:
                lake = json.load(handle)
        preserved = next(row for row in lake if row.get("record_type") == "programme")
        self.assertEqual(preserved, programme)

    def test_closure_distinguishes_successful_source_and_failed_source(self):
        successful_old = {
            "record_type": "hackathon", "hackathon_id": "https://devpost.com/old",
            "official_url": "https://devpost.com/old", "source": "devpost", "is_live": True,
            "last_seen": "2026-08-20T00:00:00+00:00",
        }
        with tempfile.TemporaryDirectory() as td:
            successful_path = os.path.join(td, "successful.json")
            with open(successful_path, "w") as handle:
                json.dump([successful_old], handle)
            merged = merge_hackathons({}, {"devpost"}, successful_path, now="2026-08-21T00:00:00+00:00")
        self.assertFalse(merged[0]["is_live"])
        self.assertEqual(merged[0]["liveness_reason"], "ended_or_removed")

        failed_old = dict(successful_old, source="unstop", hackathon_id="https://unstop.com/old", official_url="https://unstop.com/old", last_seen="2026-08-18T00:00:00+00:00")
        with tempfile.TemporaryDirectory() as td:
            failed_path = os.path.join(td, "failed.json")
            with open(failed_path, "w") as handle:
                json.dump([failed_old], handle)
            within = merge_hackathons({}, set(), failed_path, now="2026-08-21T00:00:00+00:00")[0]
            self.assertTrue(within["is_live"])
            self.assertNotIn("liveness_reason", within)
            with open(failed_path, "w") as handle:
                json.dump([failed_old], handle)
            decayed = merge_hackathons({}, set(), failed_path, now="2026-08-27T00:00:00+00:00")[0]
        self.assertFalse(decayed["is_live"])
        self.assertTrue(decayed["needs_confirmation"])
        self.assertEqual(decayed["liveness_reason"], "not_reconfirmed")


def _read(name):
    with open(os.path.join(FIXTURE_DIR, name)) as handle:
        return handle.read()


class TestHackathonQuality(unittest.TestCase):
    def test_devpost_dates_status_prize_logo_participants(self):
        rows = {r["title"]: r for r in normalize_devpost(_fixture_json("devpost_rich.json"), CHECKED_AT)}
        row = rows["Build, Ship, Shape"]
        self.assertEqual(row["start_date"], "2026-08-31")
        self.assertEqual(row["end_date"], "2026-10-23")
        self.assertEqual(row["deadline"], "2026-10-23")
        self.assertEqual(row["deadline_basis"], "submission_deadline")
        self.assertEqual(row["status"], "upcoming")
        self.assertEqual(row["prize"], "$138,000")
        self.assertEqual(row["funding"], "$138,000 in prizes")
        self.assertEqual(row["logo_url"], "https://d112y698adiu2z.cloudfront.net/photos/thumb/medium_square.png")
        self.assertEqual(row["participants"], 56650)
        self.assertEqual(row["themes"], ["Machine Learning/AI", "Open Ended"])
        self.assertEqual((row["mode"], row["region"]), ("online", "Global/Online"))
        self.assertEqual(row["hackathon_id"], "https://amazonappdev2026.devpost.com/")

    def test_devpost_unparseable_dates_fall_back_to_time_left_and_zero_prize_is_null(self):
        row = {r["title"]: r for r in normalize_devpost(_fixture_json("devpost_rich.json"), CHECKED_AT)}["Zero Prize Jam"]
        self.assertEqual(row["deadline"], "2026-08-24")
        self.assertIsNone(row["start_date"])
        self.assertIsNone(row["prize"])
        self.assertIsNone(row["funding"])
        self.assertEqual(row["logo_url"], "https://cdn.example/jam.png")
        self.assertEqual(row["eligibility"], "Invite only")
        self.assertEqual(row["region"], "Europe")
        self.assertEqual(row["status"], "open")
        self.assertIsNone(parse_time_left("about 2 months left", date(2026, 8, 21)))
        self.assertEqual(parse_time_left("5 days left", date(2026, 8, 21)), "2026-08-26")

    def test_devpost_page_description_eligibility_logo(self):
        found = parse_event_page(_read("devpost_page.html"), "https://x.devpost.com/")
        self.assertEqual(found["description"], "Build across Amazon Devices and shape what's next.")
        self.assertEqual(found["logo_url"], "https://d112y698adiu2z.cloudfront.net/photos/large.png")
        self.assertEqual(
            found["eligibility"],
            "Above legal age of majority in country of residence; All countries/territories, excluding standard exceptions")

    def test_page_jsonld_description_is_cleaned_to_two_sentences(self):
        found = parse_event_page(_read("event_ldjson_page.html"), "https://org.example/event/")
        self.assertEqual(found["description"], "A weekend of hacking. Second sentence here.")
        self.assertEqual(found["logo_url"], "https://org.example/img/logo.png")

    def test_clean_description_limits(self):
        self.assertIsNone(clean_description("  <p> </p> "))
        long = "word " * 200
        out = clean_description(long)
        self.assertLessEqual(len(out), 303)
        self.assertTrue(out.endswith("..."))
        sentence = ("A" * 150 + ". ") + ("B" * 200 + ".")
        self.assertEqual(clean_description(sentence), "A" * 150 + ".")

    def test_mlh_logo_country_organizer_mode_status(self):
        rows = {r["title"]: r for r in normalize_mlh(_read("mlh_rich.html"), CHECKED_AT)}
        row = rows["HackPrix Season 3"]
        self.assertEqual(row["official_url"], "https://s3.hackprix.tech/?utm_source=mlh".replace("?utm_source=mlh", ""))
        self.assertEqual(row["logo_url"], "https://mlhusercontent.com/logos/events/abc/hackprix_small.png")
        self.assertEqual(row["organizer_domain"], "s3.hackprix.tech")
        self.assertEqual((row["region"], row["mode"]), ("India", "in-person"))
        self.assertEqual(row["location"], "Hyderabad, Telangana")
        self.assertEqual((row["start_date"], row["end_date"], row["deadline"]), ("2026-09-13", "2026-09-14", "2026-09-14"))
        self.assertEqual(row["deadline_basis"], "event_end")
        self.assertEqual(row["status"], "upcoming")
        self.assertIsNone(row["funding"])
        digital = rows["Digital Jam"]
        self.assertEqual((digital["mode"], digital["region"], digital["is_online"]), ("online", "Global/Online", True))

    def test_unstop_dates_funding_logo_eligibility_description(self):
        rows = {r["title"]: r for r in normalize_unstop(_fixture_json("unstop_rich.json"), CHECKED_AT)}
        self.assertNotIn("Fully Ended", rows)
        row = rows["Smart India Build"]
        self.assertEqual(row["deadline"], "2026-09-10")
        self.assertEqual(row["registration_deadline"], "2026-09-10")
        self.assertEqual((row["start_date"], row["end_date"]), ("2026-08-01", "2026-09-30"))
        self.assertEqual(row["status"], "open")
        self.assertEqual(row["prize"], "\u20b92,500")
        self.assertEqual(row["funding"], "\u20b92,500 in prizes")
        self.assertEqual(row["logo_url"], "https://d8it4huxumps7.cloudfront.net/uploads/images/150x150/logo.png")
        self.assertEqual(row["organizer_domain"], "bitsathy.ac.in")
        self.assertEqual(row["participants"], 321)
        self.assertTrue(row["description"].startswith("Hackathon hosted by"))
        self.assertLessEqual(len(row["description"]), 300)
        self.assertEqual(
            row["eligibility"],
            "Open to: Engineering students (B.Tech, M.Tech, all years), Working professionals")
        self.assertEqual((row["mode"], row["region"], row["location"]), ("in-person", "India", "Erode, Tamil Nadu, India"))

    def test_unstop_registration_closed_but_event_running_is_kept_open(self):
        row = {r["title"]: r for r in normalize_unstop(_fixture_json("unstop_rich.json"), CHECKED_AT)}["Closed Reg Running Event"]
        self.assertEqual(row["status"], "open")
        self.assertEqual(row["eligibility"], "Open to: Everyone")
        self.assertIsNone(row["funding"])

    def test_unstop_eligibility_variants(self):
        self.assertEqual(unstop_eligibility_text("Open to all students"), "Open to all students")
        self.assertIsNone(unstop_eligibility_text(None))
        self.assertEqual(
            unstop_eligibility_text(None, [{"type": "eligible", "name": "Postgraduate"}]),
            "Open to: Postgraduate")
        blob = '{"sector":["students"],"engineering":["allCourses"],"bSchools":["allCourses"],"arts":["allCourses"]}'
        self.assertEqual(unstop_eligibility_text(blob), "Open to: Students (all courses)")
        blob = ('{"sector":["students"],"engineering":[{"course":"btech","passoutYear":["2026","2027"]}]}')
        self.assertEqual(unstop_eligibility_text(blob), "Open to: Engineering students (B.Tech, 2026/2027 batches)")

    def test_status_and_region_helpers(self):
        today = date(2026, 8, 21)
        self.assertEqual(compute_status("2026-09-01", "2026-09-05", "2026-09-05", today), "upcoming")
        self.assertEqual(compute_status("2026-08-01", "2026-09-05", "2026-08-10", today), "open")
        self.assertEqual(compute_status("2026-08-01", "2026-08-10", "2026-08-05", today), "ended")
        self.assertEqual(compute_status(None, None, None, today, "upcoming"), "upcoming")
        self.assertEqual(region_for(location="San Francisco, CA"), "US")
        self.assertEqual(region_for(location="Berlin, Germany"), "Europe")
        self.assertEqual(region_for(location="Pune, India"), "India")
        self.assertEqual(region_for(country="CA", location="Toronto"), "Canada")
        self.assertEqual(region_for(location="Online", online=True), "Global/Online")
        self.assertIsNone(region_for(location="Atlantis"))

    def test_enrich_uses_cache_then_fetches_only_missing_and_records_failure(self):
        calls = []

        def fetch(url):
            calls.append(url)
            return None if url.endswith("/fail") else _read("devpost_page.html")

        rows = [
            {"hackathon_id": "https://a.devpost.com/", "official_url": "https://a.devpost.com/", "source": "devpost"},
            {"hackathon_id": "https://b.devpost.com/", "official_url": "https://b.devpost.com/", "source": "devpost"},
            {"hackathon_id": "https://c.devpost.com/fail", "official_url": "https://c.devpost.com/fail", "source": "devpost"},
            {"hackathon_id": "https://u.com/x", "official_url": "https://u.com/x", "source": "unstop"},
        ]
        cache = {"https://a.devpost.com/": {"description": "cached", "eligibility": "e", "page_enriched": "2026-08-01"}}
        enrich_rows(rows, cache, fetch=fetch, today=date(2026, 8, 21), delay=0)
        self.assertEqual(calls, ["https://b.devpost.com/", "https://c.devpost.com/fail"])
        self.assertEqual(rows[0]["description"], "cached")
        self.assertEqual(rows[1]["page_enriched"], "2026-08-21")
        self.assertIn("eligibility", rows[1])
        self.assertNotIn("page_enriched", rows[2])
        self.assertNotIn("description", rows[3])
        calls.clear()
        enrich_rows(rows[:3], {}, fetch=fetch, limit=1, today=date(2026, 8, 21), delay=0)
        self.assertEqual(len(calls), 1)

    def test_ids_are_stable_and_unchanged_by_enrichment(self):
        rows = normalize_devpost(_fixture_json("devpost_rich.json"), CHECKED_AT)
        before = [stable_id(r) for r in rows]
        enrich_rows(rows, {}, fetch=lambda url: _read("devpost_page.html"), today=date(2026, 8, 21), delay=0)
        self.assertEqual(before, [stable_id(r) for r in rows])
        self.assertEqual(before[0], "hackathon:https://amazonappdev2026.devpost.com/")

    def test_merge_retires_ended_rows_including_previously_needs_confirmation(self):
        seeded = [
            {"record_type": "hackathon", "hackathon_id": "https://e.test/1", "official_url": "https://e.test/1",
             "source": "unstop", "is_live": False, "needs_confirmation": True, "liveness_reason": "event_ended",
             "registration_deadline": "2026-08-01", "end_date": "2026-08-05", "last_seen": "2026-08-20T00:00:00+00:00"},
            {"record_type": "hackathon", "hackathon_id": "https://e.test/2", "official_url": "https://e.test/2",
             "source": "unstop", "is_live": True, "needs_confirmation": False, "status": "open",
             "deadline": "2026-08-01", "end_date": "2026-12-05", "last_seen": "2026-08-20T00:00:00+00:00"},
        ]
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "lake.json")
            with open(path, "w") as handle:
                json.dump(seeded, handle)
            merged = {r["hackathon_id"]: r for r in merge_hackathons(
                {}, set(), path, now="2026-08-21T00:00:00+00:00", today=date(2026, 8, 21))}
        self.assertFalse(is_serving(merged["https://e.test/1"]))
        self.assertEqual(merged["https://e.test/1"]["status"], "ended")
        # registration closed (deadline past) even though the event is still running: not served
        self.assertFalse(is_serving(merged["https://e.test/2"]))
        self.assertEqual(merged["https://e.test/2"]["status"], "open")

    def test_collect_end_to_end_publishes_rich_fields(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "lake.json")
            collect(
                lambda: _fixture_json("devpost_rich.json"),
                lambda _c=None: [(_read("mlh_rich.html"), "https://mlh.io/seasons/2026/events")],
                lambda: {"data": {"current_page": 1, "last_page": 1, "data": _fixture_json("unstop_rich.json")}},
                checked_at=CHECKED_AT, lake_path=path, page_fetch=lambda url: _read("devpost_page.html"),
            )
            with open(path) as handle:
                lake = json.load(handle)
        with mock.patch("pipeline.publish_supabase._today", return_value="2026-08-21"):
            mapped = {m["url"]: m for m in (map_row(r) for r in lake if is_serving(r))}
        amazon = mapped["https://amazonappdev2026.devpost.com/"]
        self.assertEqual(amazon["type"], "hackathon")
        self.assertEqual(amazon["deadline"], "2026-10-23")
        self.assertEqual(amazon["funding"], "$138,000 in prizes")
        self.assertTrue(amazon["description"].startswith("Build across Amazon Devices"))
        self.assertTrue(amazon["eligibility"].startswith("Above legal age"))
        for key, expected in (("logo_url", "https://d112y698adiu2z.cloudfront.net/photos/thumb/medium_square.png"),
                              ("status", "upcoming"), ("participants", 56650), ("mode", "online"),
                              ("region", "Global/Online"), ("start_date", "2026-08-31"),
                              ("end_date", "2026-10-23"), ("prize", "$138,000")):
            self.assertEqual(amazon["extra"][key], expected, key)
        zero = mapped["https://zero.devpost.com/"]
        self.assertIsNone(zero["funding"])

    def test_zero_row_source_is_failed_and_rows_kept(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "lake.json")
            seeded = [{"record_type": "hackathon", "hackathon_id": "https://u.test/1", "official_url": "https://u.test/1",
                       "source": "unstop", "is_live": True, "status": "open", "deadline": "2999-01-01",
                       "last_seen": CHECKED_AT.isoformat(), "last_checked_at": CHECKED_AT.isoformat()}]
            with open(path, "w") as handle:
                json.dump(seeded, handle)
            out = collect(lambda: _fixture_json("devpost_rich.json"), lambda _c=None: None, lambda: [],
                          checked_at=CHECKED_AT, lake_path=path, page_fetch=lambda url: _read("devpost_page.html"))
            with open(path) as handle:
                lake = {r["hackathon_id"]: r for r in json.load(handle)}
        self.assertNotIn("unstop", out["sources_ok"])
        self.assertTrue(lake["https://u.test/1"]["is_live"])

    def test_map_row_hackathon_placeholders_and_description_length(self):
        base = {"record_type": "hackathon", "hackathon_id": "https://x.test/", "official_url": "https://x.test/",
                "title": "X", "is_live": True, "eligibility": "needs_confirmation", "funding": "not_stated",
                "description": "d" * 400, "status": "open", "logo_url": "https://x.test/l.png"}
        mapped = map_row(base)
        self.assertIsNone(mapped["eligibility"])
        self.assertIsNone(mapped["funding"])
        self.assertEqual(len(mapped["description"]), 300)
        self.assertEqual(mapped["extra"]["logo_url"], "https://x.test/l.png")

    def test_map_row_jobs_unchanged(self):
        job = {"url": "https://jobs.test/1", "title": "Eng", "company": "Co", "is_live": True,
               "description": "d" * 400, "status": "open", "logo_url": "x", "mode": "remote",
               "region": "US", "funding": "not_stated", "eligibility": "needs_confirmation"}
        mapped = map_row(job)
        # Jobs now publish a 300-char description, logo_url/region, and NULL
        # instead of placeholder funding/eligibility.
        self.assertEqual(len(mapped["description"]), 300)
        self.assertEqual(mapped["extra"], {"logo_url": "x", "region": "US"})
        self.assertIsNone(mapped["funding"])
        self.assertIsNone(mapped["eligibility"])



class RetireStaleTests(unittest.TestCase):
    NOW = "2026-10-18T00:00:00+00:00"

    def _run(self, rows, ok=()):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "lake.json")
            with open(path, "w") as handle:
                json.dump(rows, handle)
            merged = merge_hackathons({}, set(ok), path, now=self.NOW, today=date(2026, 10, 18))
        return {row["hackathon_id"]: row for row in merged}

    def _row(self, hid, **kw):
        row = {
            "record_type": "hackathon", "hackathon_id": hid, "official_url": "https://x.test/" + hid,
            "source": "devpost", "is_live": True, "needs_confirmation": False, "status": "open",
            "last_seen": "2026-10-17T00:00:00+00:00", "last_checked_at": "2026-10-17T00:00:00+00:00",
        }
        row.update(kw)
        return row

    def _retired(self, row):
        self.assertFalse(row["is_live"])
        self.assertFalse(row["needs_confirmation"])
        self.assertFalse(is_serving(row))

    def test_past_deadline_and_end_retired(self):
        out = self._run([self._row("a", deadline="2026-09-01", end_date="2026-09-05")])
        self._retired(out["a"])

    def test_absent_from_healthy_source_retired(self):
        out = self._run([self._row("b", needs_confirmation=True)], ok={"devpost"})
        self._retired(out["b"])

    def test_failed_source_keeps_recent_row(self):
        out = self._run([self._row("c")], ok={"mlh"})
        self.assertTrue(out["c"]["is_live"])

    def test_old_row_aged_out_even_if_source_failed(self):
        old = "2026-09-01T00:00:00+00:00"
        out = self._run([self._row("d", last_seen=old, last_checked_at=old, needs_confirmation=True)])
        self._retired(out["d"])

    def test_stale_days_env(self):
        row = self._row("e", last_seen="2026-10-13T00:00:00+00:00", last_checked_at="2026-10-13T00:00:00+00:00")
        self.assertTrue(self._run([row])["e"]["is_live"])
        os.environ["XLAKE_HACKATHON_STALE_DAYS"] = "2"
        try:
            self._retired(self._run([row])["e"])
        finally:
            del os.environ["XLAKE_HACKATHON_STALE_DAYS"]

    def test_legacy_no_status_not_live_retired(self):
        row = self._row("f", is_live=False, needs_confirmation=True)
        del row["status"]
        self._retired(self._run([row])["f"])


if __name__ == "__main__":
    unittest.main()
