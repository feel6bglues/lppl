import os
import unittest
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pandas as pd

import lppl_verify_v2


class LPPLVerifyOutputTests(unittest.TestCase):
    def test_save_results_writes_summary_and_raw_timeline(self) -> None:
        with TemporaryDirectory() as temp_dir:
            all_results = [
                {
                    "symbol": "000001.SH",
                    "name": "上证综指",
                    "peak_date": "2020-01-31",
                    "peak_price": 123.0,
                    "detected": True,
                    "first_danger_days": -5,
                    "first_danger_r2": 0.82,
                    "timeline": [
                        {"idx": 1, "date": "2020-01-01", "signal_strength": 0.7},
                        {"idx": 2, "date": "2020-01-02", "signal_strength": 0.8},
                    ],
                }
            ]

            results_df = lppl_verify_v2.save_results(
                all_results,
                output_dir=temp_dir,
                use_ensemble=True,
            )

            summary_path = os.path.join(temp_dir, "summary", "peak_verification_v2_ensemble.csv")
            raw_path = os.path.join(temp_dir, "raw", "raw_000001_SH_ensemble_2020-01-31.parquet")

            self.assertTrue(os.path.exists(summary_path))
            self.assertTrue(os.path.exists(raw_path))
            self.assertNotIn("timeline", results_df.columns)

            raw_df = pd.read_parquet(raw_path)
            self.assertEqual(len(raw_df), 2)

    def test_generate_verification_artifacts_creates_reports_and_plots(self) -> None:
        with TemporaryDirectory() as temp_dir:
            all_results = [
                {
                    "symbol": "000001.SH",
                    "name": "上证综指",
                    "peak_date": "2020-01-31",
                    "peak_price": 123.0,
                    "detected": True,
                    "first_danger_days": -5,
                    "first_danger_r2": 0.82,
                    "mode": "ensemble",
                    "timeline": [
                        {
                            "idx": 1,
                            "date": "2020-01-01",
                            "price": 100,
                            "is_warning": True,
                            "is_danger": False,
                            "consensus_rate": 0.4,
                            "valid_windows": 2,
                            "predicted_crash_days": 15,
                            "tc_std": 1.5,
                        }
                    ],
                }
            ]

            with patch("lppl_verify_v2.PlotGenerator.generate_price_timeline_plot", return_value=f"{temp_dir}/plots/timeline.png"), \
                 patch("lppl_verify_v2.PlotGenerator.generate_consensus_plot", return_value=f"{temp_dir}/plots/consensus.png"), \
                 patch("lppl_verify_v2.PlotGenerator.generate_crash_dispersion_plot", return_value=f"{temp_dir}/plots/dispersion.png"), \
                 patch("lppl_verify_v2.PlotGenerator.generate_summary_statistics_plot", return_value=f"{temp_dir}/plots/summary.png"), \
                 patch("lppl_verify_v2.VerificationReportGenerator.generate_markdown_report", return_value=f"{temp_dir}/reports/report.md"), \
                 patch("lppl_verify_v2.VerificationReportGenerator.generate_html_report", return_value=f"{temp_dir}/reports/report.html"):
                artifacts = lppl_verify_v2.generate_verification_artifacts(
                    all_results,
                    output_dir=temp_dir,
                    use_ensemble=True,
                )

            self.assertEqual(artifacts["markdown_path"], f"{temp_dir}/reports/report.md")
            self.assertEqual(artifacts["html_path"], f"{temp_dir}/reports/report.html")
            self.assertIn("汇总统计图", artifacts["plot_paths"])
            self.assertEqual(len(artifacts["plot_paths"]["案例价格时间线图"]), 1)
            self.assertEqual(len(artifacts["plot_paths"]["案例 Ensemble 共识图"]), 1)
            self.assertEqual(len(artifacts["plot_paths"]["案例预测时间离散图"]), 1)


if __name__ == "__main__":
    unittest.main()
