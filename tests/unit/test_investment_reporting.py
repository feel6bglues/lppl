import os
import tempfile
import unittest

import pandas as pd

from src.reporting.investment_report import InvestmentReportGenerator
from src.reporting.plot_generator import PlotGenerator


class InvestmentReportingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)

    def _make_equity_df(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "date": pd.date_range("2021-01-01", periods=4, freq="D"),
                "symbol": ["000001.SH"] * 4,
                "open": [100.0, 101.0, 103.0, 102.0],
                "high": [102.0, 104.0, 105.0, 103.0],
                "low": [99.0, 100.0, 101.0, 100.0],
                "close": [101.0, 103.0, 102.0, 101.0],
                "strategy_nav": [1.0, 1.03, 1.01, 1.02],
                "benchmark_nav": [1.0, 1.02, 1.01, 1.00],
                "drawdown": [0.0, 0.0, -0.019417, -0.009709],
                "executed_position": [0.0, 1.0, 1.0, 0.5],
            }
        )

    def _make_trades_df(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "date": pd.to_datetime(["2021-01-02", "2021-01-04"]),
                "trade_type": ["buy", "reduce"],
                "price": [101.0, 102.0],
                "target_position": [1.0, 0.5],
            }
        )

    def test_plot_generator_outputs_strategy_charts(self) -> None:
        generator = PlotGenerator(output_dir=self.temp_dir.name)
        equity_df = self._make_equity_df()
        trades_df = self._make_trades_df()
        metadata = {
            "symbol": "000001.SH",
            "name": "上证综指",
            "start_date": "2021-01-01",
            "end_date": "2021-01-04",
            "max_drawdown": -0.019417,
            "total_return": 0.02,
        }

        overview_path = generator.generate_strategy_overview_plot(equity_df, trades_df, metadata)
        drawdown_path = generator.generate_strategy_drawdown_plot(equity_df, metadata)

        self.assertTrue(os.path.isfile(overview_path))
        self.assertTrue(os.path.isfile(drawdown_path))

    def test_investment_report_generator_outputs_markdown_and_html(self) -> None:
        report_generator = InvestmentReportGenerator(output_dir=self.temp_dir.name)
        summary_df = pd.DataFrame(
            [
                {
                    "symbol": "000001.SH",
                    "name": "上证综指",
                    "start_date": "2021-01-01",
                    "end_date": "2021-01-04",
                    "final_nav": 1.02,
                    "total_return": 0.02,
                    "benchmark_return": 0.0,
                    "max_drawdown": -0.019417,
                    "trade_count": 2,
                    "latest_action": "reduce",
                    "latest_signal": "bubble_risk",
                }
            ]
        )
        plot_paths = {
            "核心图表": [
                os.path.join(self.temp_dir.name, "overview.png"),
                os.path.join(self.temp_dir.name, "drawdown.png"),
            ]
        }

        for path in plot_paths["核心图表"]:
            with open(path, "wb") as handle:
                handle.write(b"stub")

        markdown_path = report_generator.generate_markdown_report(summary_df, plot_paths)
        html_path = report_generator.generate_html_report(summary_df, plot_paths)

        self.assertTrue(os.path.isfile(markdown_path))
        self.assertTrue(os.path.isfile(html_path))
        with open(markdown_path, "r", encoding="utf-8") as handle:
            markdown = handle.read()
        self.assertIn("最新信号", markdown)
        self.assertIn("overview.png", markdown)


if __name__ == "__main__":
    unittest.main()
