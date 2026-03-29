import json
import os
import unittest

import pandas as pd


class VerificationBaselineTests(unittest.TestCase):
    def test_baseline_fixture_has_expected_cases(self) -> None:
        fixture_path = "tests/fixtures/verification_baselines.json"
        self.assertTrue(os.path.exists(fixture_path))

        with open(fixture_path, "r", encoding="utf-8") as f:
            payload = json.load(f)

        self.assertEqual(payload["mode"], "ensemble")
        self.assertEqual(len(payload["cases"]), 3)
        for case in payload["cases"]:
            self.assertIn("symbol", case)
            self.assertIn("peak_date", case)
            self.assertIn("detected", case)
            self.assertIn("first_danger_r2", case)

    def test_baseline_summary_csv_matches_fixture(self) -> None:
        csv_path = "output/MA/summary/verification_baselines.csv"
        self.assertTrue(os.path.exists(csv_path))

        df = pd.read_csv(csv_path)
        self.assertEqual(len(df), 3)
        self.assertEqual(sorted(df["symbol"].tolist()), ["000001.SH", "000300.SH", "399006.SZ"])
        self.assertTrue((df["mode"] == "ensemble").all())


if __name__ == "__main__":
    unittest.main()
