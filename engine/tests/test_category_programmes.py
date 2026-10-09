import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SEED_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "operations", "generated_seeds",
)
_previous_seed_dir = os.environ.get("XLAKE_GENERATED_SEEDS_DIR")
os.environ["XLAKE_GENERATED_SEEDS_DIR"] = SEED_DIR
try:
    from categories.community import programmes as community
    from categories.startup_founder import programmes as startup_founder
finally:
    if _previous_seed_dir is None:
        os.environ.pop("XLAKE_GENERATED_SEEDS_DIR", None)
    else:
        os.environ["XLAKE_GENERATED_SEEDS_DIR"] = _previous_seed_dir


class TestCategoryProgrammeCollectors(unittest.TestCase):
    def test_registries_include_generated_seeds(self):
        seed_dir = SEED_DIR
        for module, stem in ((startup_founder, "startup_founder"), (community, "community")):
            with self.subTest(category=stem):
                with open(os.path.join(seed_dir, stem + ".json"), encoding="utf-8") as handle:
                    generated = json.load(handle)
                self.assertTrue(generated)
                self.assertTrue(
                    {seed["programme_id"] for seed in generated}
                    <= {seed["programme_id"] for seed in module.SOURCE_REGISTRY}
                )

    def test_startup_founder_record_category_and_type(self):
        seed = startup_founder.SOURCE_REGISTRY[0]
        record, observation = startup_founder.parse_programme(
            seed,
            "<html><body><h1>Startup programme</h1>"
            "<p>Applications are rolling basis for this official programme.</p>"
            "<a href='/apply'>Apply</a></body></html>",
        )
        self.assertIsNotNone(record)
        self.assertEqual(record["record_type"], "programme")
        self.assertEqual(record["category"], "startup-founder")
        self.assertEqual(record["opportunity_type"], "programme")
        self.assertEqual(observation["state"], "actionable")

    def test_community_record_category_and_type(self):
        seed = community.SOURCE_REGISTRY[0]
        record, observation = community.parse_programme(
            seed,
            "<html><body><h1>Community programme</h1>"
            "<p>Applications are rolling basis for this official programme.</p>"
            "<a href='/apply'>Apply</a></body></html>",
        )
        self.assertIsNotNone(record)
        self.assertEqual(record["record_type"], "programme")
        self.assertEqual(record["category"], "community")
        self.assertEqual(record["opportunity_type"], "programme")
        self.assertEqual(observation["state"], "actionable")


if __name__ == "__main__":
    unittest.main()
