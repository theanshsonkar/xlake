import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from categories import programme_core as core
from categories.scholarships import scholarships

CFG = scholarships.SCHOLARSHIP_CONFIG
EV = {"quote": "Applications close on 2026-12-01", "url": "https://official.example/apply"}


def record(**kw):
    rec = {
        "programme_id": "hand-1", "title": "Hand Programme", "organizer": "Org",
        "official_url": "https://official.example/", "verified_by": "manual",
        "verified_at": "2026-10-19T00:00:00Z", "recheck_after": "2026-11-18",
        "programme_status": "open", "deadline": "2026-12-01",
        "funding": "$1,000", "summary": "Neutral summary.",
        "official_evidence": {"status": EV, "deadline": EV, "funding": EV},
    }
    rec.update(kw)
    return rec


class HandVerifiedTests(unittest.TestCase):
    def test_merge_creates_authoritative_row_with_extended_fields(self):
        out = core.apply_verifications([], [record(requirements=["a"], logo_url="https://x/l.png")],
                                       "2026-10-20T00:00:00Z", config=CFG)
        row = out[0]
        self.assertEqual(row["programme_status"], "open")
        self.assertEqual(row["deadline"], "2026-12-01")
        self.assertEqual(row["requirements"], ["a"])
        self.assertTrue(row["manually_verified"])
        self.assertTrue(row["is_live"])
        self.assertNotIn("verification_flag", row)

    def test_expired_record_becomes_needs_confirmation(self):
        out = core.apply_verifications([], [record()], "2026-11-19T00:00:00Z", config=CFG)
        row = out[0]
        self.assertEqual(row["programme_status"], "needs_confirmation")
        self.assertFalse(row["is_live"])
        self.assertEqual(row["verification_flag"], "verification_expired")

    def test_url_flag_forces_needs_confirmation(self):
        out = core.apply_verifications([], [record()], "2026-10-20T00:00:00Z", config=CFG,
                                       url_flags={"hand-1": "official_url_http_404"})
        self.assertEqual(out[0]["programme_status"], "needs_confirmation")
        self.assertEqual(out[0]["verification_flag"], "official_url_http_404")

    def test_validation_requires_evidence_for_every_fact(self):
        bad = record(official_evidence={"status": EV, "deadline": EV})  # funding unbacked
        self.assertFalse(core.validate_verification(bad)[0])
        self.assertFalse(core.validate_verification(record(recheck_after="soon"))[0])
        self.assertTrue(core.validate_verification(record())[0])

    def test_recheck_flags_404_and_changed_quote_only(self):
        pages = {
            "https://a/": (404, "https://a/", "", None),
            "https://b/": (200, "https://b/", "<p>Totally different page</p>", None),
            "https://c/": (200, "https://c/", "<p>Applications close on 2026-12-01</p>", None),
            "https://d/": (None, "https://d/", "", "timeout"),
            "https://e/": (200, "https://e/", "<p>Totally different page</p>", None),
        }
        recs = [record(programme_id=k, official_url="https://%s/" % k, recheck_quote=(k in "bc"))
                for k in "abcde"]
        flagged = core.recheck_official_urls(recs, fetch=lambda url: pages[url])
        self.assertEqual(flagged, {"a": "official_url_http_404", "b": "official_page_changed"})


if __name__ == "__main__":
    unittest.main()
