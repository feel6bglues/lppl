import os
import unittest
from tempfile import TemporaryDirectory

import pandas as pd

from src.reporting.plot_generator import PlotGenerator


class PlotGeneratorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.generator = PlotGenerator(output_dir=self.temp_dir.name)
        self.metadata = {
            "symbol": "000001.SH",
            "name": "上证综指",
            "peak_date": "2020-01-31",
            "mode": "ensemble",
            "first_danger_days": -5,
        }
        self.timeline_df = pd.DataFrame(
            {
                "date": pd.date_range("2020-01-01", periods=5, freq="D"),
                "price": [100, 102, 104, 101, 99],
                "is_warning": [False, True, True, False, False],
                "is_danger": [False, False, True, True, False],
                "consensus_rate": [0.1, 0.2, 0.4, 0.5, 0.3],
                "valid_windows": [1, 1, 2, 3, 2],
                "predicted_crash_days": [40, 30, 20, 15, 10],
                "tc_std": [4.0, 3.0, 2.0, 1.5, 1.0],
            }
        )
        self.summary_df = pd.DataFrame(
            {
                "name": ["上证综指", "上证综指", "沪深300"],
                "detected": [True, False, True],
                "first_danger_days": [-5, None, -8],
            }
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_generate_price_timeline_plot(self) -> None:
        path = self.generator.generate_price_timeline_plot(self.timeline_df, self.metadata)
        self.assertTrue(os.path.exists(path))

    def test_generate_consensus_plot(self) -> None:
        path = self.generator.generate_consensus_plot(self.timeline_df, self.metadata, consensus_threshold=0.25)
        self.assertTrue(os.path.exists(path))

    def test_generate_crash_dispersion_plot(self) -> None:
        path = self.generator.generate_crash_dispersion_plot(self.timeline_df, self.metadata)
        self.assertTrue(os.path.exists(path))

    def test_generate_summary_statistics_plot(self) -> None:
        path = self.generator.generate_summary_statistics_plot(self.summary_df)
        self.assertTrue(os.path.exists(path))


if __name__ == "__main__":
    unittest.main()
