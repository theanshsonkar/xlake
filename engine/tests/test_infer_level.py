import unittest

from core.filters import infer_level as lv


class InferLevelTests(unittest.TestCase):
    def test_existing_level_kept(self):
        self.assertEqual(lv("Senior Engineer", current="junior"), "junior")

    def test_senior_titles(self):
        for t in ("Senior Data Analyst", "Sr. Developer", "Engineering Manager",
                  "Associate Director, Finance", "Head of Growth", "Principal Engineer",
                  "Staff Software Engineer", "VP Sales"):
            self.assertEqual(lv(t), "senior", t)

    def test_early_titles(self):
        self.assertEqual(lv("Senior Intern"), "intern")
        self.assertEqual(lv("Werkstudent Marketing"), "intern")
        self.assertEqual(lv("Graduate Research Assistant"), "entry")
        self.assertEqual(lv("Associate Software Engineer"), "entry")
        self.assertEqual(lv("Fresher - Developer"), "entry")
        self.assertEqual(lv("Analista Júnior"), "junior")
        self.assertEqual(lv("Data Scientist", employment_type="internship"), "intern")

    def test_unsure_stays_unknown(self):
        for t in ("Data Analyst", "Assistant Manager", "Lead Generation Specialist",
                  "Collection Analyst (Late Stage)", "Member of Technical Staff"):
            self.assertIsNone(lv(t), t)

    def test_experience_years(self):
        self.assertEqual(lv("Data Analyst", experience_min=5), "senior")
        self.assertEqual(lv("Data Analyst", experience_min=0, experience_max=2), "entry")

    def test_conflicts_unknown(self):
        self.assertIsNone(lv("Data Analyst", experience_min=1, experience_max=5,
                             experience_conflict=True))
        self.assertIsNone(lv("Senior Engineer", experience_min=0, experience_max=1))
        self.assertIsNone(lv("Junior Engineer", experience_min=5))


if __name__ == "__main__":
    unittest.main()
