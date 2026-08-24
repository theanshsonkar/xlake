import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from adapters import boards  # noqa: E402


class WorkableLocationTest(unittest.TestCase):
    def test_real_field_shape_resolves_locations_and_preserves_fields(self):
        jobs = [
            {
                "city": "Mumbai",
                "country": "India",
                "state": "Maharashtra",
                "telecommuting": False,
                "locations": [
                    {
                        "city": "Mumbai",
                        "country": "India",
                        "region": "Maharashtra",
                        "hidden": False,
                    }
                ],
                "shortcode": "MUM123",
                "title": "Mumbai Engineer",
                "url": "https://apply.workable.com/j/MUM123",
            },
            {
                "city": "",
                "country": "",
                "state": "",
                "telecommuting": False,
                "locations": [
                    {"hidden": True, "city": "X", "country": "Y"},
                    {
                        "hidden": False,
                        "city": "Berlin",
                        "country": "Germany",
                        "region": "Berlin",
                    },
                ],
                "shortcode": "BER456",
                "title": "Berlin Engineer",
                "url": "https://apply.workable.com/j/BER456",
            },
            {
                "city": "",
                "country": "",
                "state": "",
                "telecommuting": True,
                "locations": [],
                "shortcode": "REM789",
                "title": "Remote Engineer",
                "url": "https://apply.workable.com/j/REM789",
            },
            {
                "city": "",
                "country": "",
                "state": "",
                "telecommuting": False,
                "locations": [],
                "shortcode": "EMP012",
                "title": "Unspecified Engineer",
                "url": "https://apply.workable.com/j/EMP012",
            },
        ]

        with mock.patch.object(
            boards, "_request", return_value=(200, {"jobs": jobs}, None)
        ):
            result = boards._workable("example")

        self.assertEqual(result.status, 200)
        self.assertIsNone(result.error)
        self.assertEqual(
            [posting.location for posting in result.postings],
            ["Mumbai, India", "Berlin, Germany", "Remote", ""],
        )
        self.assertEqual(
            [
                (posting.job_id, posting.title, posting.url)
                for posting in result.postings
            ],
            [
                ("MUM123", "Mumbai Engineer", "https://apply.workable.com/j/MUM123"),
                ("BER456", "Berlin Engineer", "https://apply.workable.com/j/BER456"),
                ("REM789", "Remote Engineer", "https://apply.workable.com/j/REM789"),
                ("EMP012", "Unspecified Engineer", "https://apply.workable.com/j/EMP012"),
            ],
        )


if __name__ == "__main__":
    unittest.main()
