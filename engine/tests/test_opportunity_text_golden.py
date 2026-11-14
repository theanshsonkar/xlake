"""Golden snapshot of the date / status / quote logic and of parse_programme.

The inputs (observation quotes) are stored in the fixture itself, so the test does
not depend on the crawled data files. Regenerate on purpose with XLAKE_REGEN_GOLDEN=1."""
import json
import os
import sys
import unittest
from datetime import date, datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from categories import programme_core as pc
from categories.community import programmes as community
from categories.fellowships import fellowships
from categories.grants import grants
from categories.open_source import programmes as open_source
from categories.research import research
from categories.scholarships import scholarships
from categories.startup_founder import programmes as startup_founder

ENGINE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GOLDEN = os.path.join(ENGINE_ROOT, "tests", "fixtures", "opportunity_text_golden.json")
OBSERVATIONS = os.path.join(ENGINE_ROOT, "data", "operations")
TODAY = date(2026, 11, 14)
CHECKED_AT = datetime(2026, 11, 14, tzinfo=timezone.utc)
SAMPLE = 2500
PAGES = [os.path.join("programmes", name) for name in sorted(os.listdir(os.path.join(ENGINE_ROOT, "fixtures", "programmes")))
         if name.endswith(".html")] + [os.path.join("research", "mitacs.html")]
MODULES = (("open_source", open_source), ("research", research), ("fellowships", fellowships), ("grants", grants),
           ("scholarships", scholarships), ("startup_founder", startup_founder), ("community", community))


def _collect_quotes(node, out):
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "quote" and isinstance(value, str) and value.strip():
                out.add(value)
            else:
                _collect_quotes(value, out)
    elif isinstance(node, list):
        for value in node:
            _collect_quotes(value, out)


def _sample_quotes():
    quotes = set()
    for name in sorted(os.listdir(OBSERVATIONS)):
        if name.endswith("_observations.json"):
            with open(os.path.join(OBSERVATIONS, name), encoding="utf-8") as handle:
                _collect_quotes(json.load(handle), quotes)
    ordered = sorted(quotes)
    step = max(1, len(ordered) // SAMPLE)
    return ordered[::step][:SAMPLE] if len(ordered) > SAMPLE else ordered


def _jsonable(value):
    return json.loads(json.dumps(value, default=str, sort_keys=True))


def _quote_outputs(quote):
    windows = pc.detect_applicant_windows(quote, TODAY)
    parsed = pc.parse_date(quote)
    iso = parsed["start"].isoformat() if parsed and parsed.get("start") else "2026-09-15"
    return _jsonable({
        "parse_dates": pc.parse_dates(quote, None, TODAY),
        "parse_dates_year": pc.parse_dates(quote, 2026),
        "parse_date": parsed,
        "windows": windows,
        "status_formal": pc.classify_status(quote, windows, TODAY, True, None),
        "status_plain": pc.classify_status(quote, windows, TODAY, False, "https://example.org/apply"),
        "lexical": pc._lexical_status(quote, TODAY),
        "opens_pattern": pc.detect_opens_pattern(quote, "https://example.org/"),
        "quality": pc.is_quality_evidence(quote),
        "has_date": pc.quote_has_date(quote, iso),
        "opening_quote": pc.official_opening_quote(quote, iso),
        "closing": pc.closing_from_opening_quote(quote, iso),
    })


def _parse_programme_outputs():
    out = {}
    for stem, module in MODULES:
        seed = dict(getattr(module, "STATIC_SOURCE_REGISTRY", module.SEEDS)[0])
        for page in PAGES:
            with open(os.path.join(ENGINE_ROOT, "fixtures", page), encoding="utf-8") as handle:
                html = handle.read()
            record, observation = module.parse_programme(dict(seed), html, CHECKED_AT)
            out["%s|%s" % (stem, page)] = _jsonable({"record": record, "observation": observation})
    return out


class TestOpportunityTextGolden(unittest.TestCase):
    def test_matches_snapshot(self):
        if os.environ.get("XLAKE_REGEN_GOLDEN") == "1":
            quotes = _sample_quotes()
            snapshot = {"quotes": quotes, "quote_outputs": [_quote_outputs(q) for q in quotes],
                        "parse_programme": _parse_programme_outputs()}
            with open(GOLDEN, "w", encoding="utf-8") as handle:
                json.dump(snapshot, handle, sort_keys=True, ensure_ascii=False)
            return
        with open(GOLDEN, encoding="utf-8") as handle:
            snapshot = json.load(handle)
        self.assertGreaterEqual(len(snapshot["quotes"]), 2000)
        for quote, expected in zip(snapshot["quotes"], snapshot["quote_outputs"]):
            self.assertEqual(_quote_outputs(quote), expected, quote[:120])
        self.assertEqual(_parse_programme_outputs(), snapshot["parse_programme"])


if __name__ == "__main__":
    unittest.main()
