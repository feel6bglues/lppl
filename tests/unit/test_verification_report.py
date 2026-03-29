import os
import unittest
from tempfile import TemporaryDirectory

import pandas as pd

from src.reporting.verification_report import VerificationReportGenerator


class VerificationReportTests(unittest.TestCase):
    def test_generate_markdown_report_writes_summary_and_plot_links(self) -> None:
        with TemporaryDirectory() as temp_dir:
            reports_dir = os.path.join(temp_dir, "reports")
            plots_dir = os.path.join(temp_dir, "plots")
            os.makedirs(plots_dir, exist_ok=True)

            plot_path = os.path.join(plots_dir, "timeline.png")
            with open(plot_path, "wb") as f:
                f.write(b"fake-png")

            summary_df = pd.DataFrame(
                [
                    {
                        "name": "上证综指",
                        "symbol": "000001.SH",
                        "detected": True,
                        "first_danger_days": -5,
                    }
                ]
            )

            generator = VerificationReportGenerator(output_dir=reports_dir)
            report_path = generator.generate_markdown_report(
                summary_df=summary_df,
                use_ensemble=True,
                plot_paths={"案例图": [plot_path]},
            )

            self.assertTrue(os.path.exists(report_path))
            with open(report_path, "r", encoding="utf-8") as f:
                content = f.read()
            self.assertIn("LPPL 验证报告", content)
            self.assertIn("Ensemble 多窗口共识", content)
            self.assertIn("timeline.png", content)
            self.assertIn("上证综指", content)

    def test_generate_html_report_writes_cards_and_images(self) -> None:
        with TemporaryDirectory() as temp_dir:
            reports_dir = os.path.join(temp_dir, "reports")
            plots_dir = os.path.join(temp_dir, "plots")
            os.makedirs(plots_dir, exist_ok=True)

            plot_path = os.path.join(plots_dir, "consensus.png")
            with open(plot_path, "wb") as f:
                f.write(b"fake-png")

            summary_df = pd.DataFrame(
                [
                    {
                        "name": "上证综指",
                        "symbol": "000001.SH",
                        "detected": True,
                        "first_danger_days": -5,
                        "first_danger_r2": 0.81,
                    }
                ]
            )

            generator = VerificationReportGenerator(output_dir=reports_dir)
            report_path = generator.generate_html_report(
                summary_df=summary_df,
                use_ensemble=True,
                plot_paths={"共识图": [plot_path]},
            )

            self.assertTrue(os.path.exists(report_path))
            with open(report_path, "r", encoding="utf-8") as f:
                content = f.read()
            self.assertIn("LPPL 验证报告", content)
            self.assertIn("Ensemble 多窗口共识", content)
            self.assertIn("案例卡片", content)
            self.assertIn("consensus.png", content)
            self.assertIn("上证综指", content)


if __name__ == "__main__":
    unittest.main()
