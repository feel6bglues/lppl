# -*- coding: utf-8 -*-
import os
import shutil
import tempfile
import unittest

import pandas as pd

from src.reporting.optimal8_readable_report import Optimal8ReadableReportGenerator


class Optimal8ReadableReportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp(prefix="lppl_opt8_")
        self.summary_dir = os.path.join(self.temp_dir, "summary")
        self.report_dir = os.path.join(self.temp_dir, "reports")
        self.plot_dir = os.path.join(self.temp_dir, "plots")
        os.makedirs(self.summary_dir, exist_ok=True)
        os.makedirs(self.report_dir, exist_ok=True)
        os.makedirs(self.plot_dir, exist_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_generate_creates_markdown_and_plots(self) -> None:
        data = pd.DataFrame(
            [
                {
                    "symbol": "000001.SH",
                    "risk_band": "DANGER",
                    "suggest_position": "0-20%",
                    "objective_score": 0.41,
                    "precision": 0.75,
                    "recall": 0.31,
                    "false_positive_rate": 0.03,
                    "signal_count": 8,
                    "true_positive": 6,
                    "false_positive": 2,
                    "step": 120,
                    "window_count": 9,
                },
                {
                    "symbol": "399006.SZ",
                    "risk_band": "Watch",
                    "suggest_position": "60-80%",
                    "objective_score": 0.17,
                    "precision": 0.50,
                    "recall": 0.04,
                    "false_positive_rate": 0.02,
                    "signal_count": 2,
                    "true_positive": 1,
                    "false_positive": 1,
                    "step": 60,
                    "window_count": 16,
                },
            ]
        )
        summary_csv = os.path.join(self.summary_dir, "summary.csv")
        data.to_csv(summary_csv, index=False)

        gen = Optimal8ReadableReportGenerator(report_dir=self.report_dir, plot_dir=self.plot_dir)
        outputs = gen.generate(summary_csv=summary_csv, output_stem="ut_opt8")

        self.assertTrue(os.path.isfile(outputs["report_path"]))
        self.assertTrue(os.path.isfile(outputs["chart_priority"]))
        self.assertTrue(os.path.isfile(outputs["chart_precision_recall"]))
        self.assertTrue(os.path.isfile(outputs["chart_signal_structure"]))
        self.assertTrue(os.path.isfile(outputs["chart_param_profile"]))

        with open(outputs["report_path"], "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("执行摘要", content)
        self.assertIn("图1 风险优先级", content)
        self.assertIn("000001.SH", content)


if __name__ == "__main__":
    unittest.main()
