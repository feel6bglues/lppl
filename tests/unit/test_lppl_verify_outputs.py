import os
import sys
import unittest
import warnings
from importlib import reload
from io import StringIO
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pandas as pd

import lppl_verify_v2


class LPPLVerifyOutputTests(unittest.TestCase):
    def test_create_config_aligns_with_core_lppl_thresholds(self) -> None:
        single_window = lppl_verify_v2.create_config(use_ensemble=False)
        ensemble = lppl_verify_v2.create_config(use_ensemble=True)

        self.assertEqual(single_window.tc_bound, (1, 150))
        self.assertEqual(ensemble.tc_bound, (1, 150))
        self.assertEqual(single_window.danger_days, 20)
        self.assertEqual(ensemble.danger_days, 20)
        self.assertEqual(single_window.warning_days, 60)
        self.assertEqual(ensemble.warning_days, 60)
        self.assertEqual(single_window.watch_days, 61)
        self.assertEqual(ensemble.watch_days, 61)

    def test_cli_warning_filters_are_targeted(self) -> None:
        filters_before = warnings.filters[:]
        reload(lppl_verify_v2)
        new_filters = warnings.filters[len(filters_before):]
        broad_ignore_rules = [
            entry for entry in new_filters
            if entry[0] == "ignore" and entry[1] is None and entry[2] is Warning
        ]
        self.assertFalse(broad_ignore_rules)

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

    def test_main_marks_default_fallback_when_optimal_config_load_fails(self) -> None:
        captured_sources = []

        def fake_run_verification(*args, **kwargs):
            captured_sources.append(kwargs.get("param_source"))
            return [
                {
                    "symbol": "000001.SH",
                    "name": "上证综指",
                    "peak_date": "2020-01-31",
                    "peak_price": 123.0,
                    "detected": True,
                    "first_danger_days": -5,
                    "first_danger_r2": 0.82,
                    "timeline": [],
                }
            ]

        stdout = StringIO()
        with patch("src.cli.lppl_verify_v2.load_optimal_config", side_effect=FileNotFoundError("missing")), \
             patch("src.cli.lppl_verify_v2.run_verification", side_effect=fake_run_verification), \
             patch("src.cli.lppl_verify_v2.print_summary"), \
             patch("src.cli.lppl_verify_v2.generate_verification_artifacts", return_value=None), \
             patch("sys.stdout", new=stdout):
            argv = [
                "lppl_verify_v2.py",
                "--symbol",
                "000001.SH",
                "--use-optimal-config",
            ]
            with patch.object(sys, "argv", argv):
                lppl_verify_v2.main()

        self.assertEqual(captured_sources, ["default_fallback"])
        self.assertIn("最优参数加载失败", stdout.getvalue())
        self.assertIn("missing", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
