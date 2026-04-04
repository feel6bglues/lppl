import os
import shutil
import sys
import tempfile
import unittest
from io import StringIO
from unittest.mock import Mock, patch

import pandas as pd

from src.cli.index_investment_analysis import main


class IndexInvestmentAnalysisIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp(prefix="lppl_investment_")
        self.addCleanup(self._cleanup_temp_dir)

    def _cleanup_temp_dir(self) -> None:
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _make_price_df(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "date": pd.date_range("2021-01-01", periods=4, freq="D"),
                "open": [100.0, 101.0, 103.0, 102.0],
                "high": [102.0, 104.0, 105.0, 103.0],
                "low": [99.0, 100.0, 101.0, 100.0],
                "close": [101.0, 103.0, 102.0, 101.0],
                "volume": [1000, 1100, 1200, 1300],
            }
        )

    def test_cli_generates_expected_artifacts(self) -> None:
        fake_df = self._make_price_df()
        fake_data_manager = Mock()
        fake_data_manager.get_data.return_value = fake_df

        signal_df = fake_df.copy()
        signal_df["symbol"] = "000001.SH"
        signal_df["lppl_signal"] = ["none", "negative_bubble", "none", "bubble_risk"]
        signal_df["signal_strength"] = [0.0, 0.8, 0.0, 0.9]
        signal_df["position_reason"] = ["无信号", "强抄底信号", "无信号", "高危信号"]
        signal_df["action"] = ["hold", "buy", "hold", "sell"]
        signal_df["target_position"] = [0.0, 1.0, 1.0, 0.0]

        equity_df = signal_df.copy()
        equity_df["executed_position"] = [0.0, 1.0, 1.0, 0.0]
        equity_df["cash"] = [1000.0, 0.0, 0.0, 1000.0]
        equity_df["units"] = [0.0, 9.9, 9.9, 0.0]
        equity_df["holdings_value"] = [0.0, 1019.7, 1009.8, 0.0]
        equity_df["portfolio_value"] = [1000.0, 1019.7, 1009.8, 1009.8]
        equity_df["strategy_nav"] = [1.0, 1.0197, 1.0098, 1.0098]
        equity_df["benchmark_nav"] = [1.0, 1.0198, 1.0099, 1.0]
        equity_df["daily_return"] = [0.0, 0.0197, -0.0097, 0.0]
        equity_df["benchmark_return"] = [0.0, 0.0198, -0.0097, -0.0098]
        equity_df["excess_return"] = [0.0, -0.0001, -0.0000, 0.0098]
        equity_df["drawdown"] = [0.0, 0.0, -0.0097, -0.0097]

        trades_df = pd.DataFrame(
            {
                "date": pd.to_datetime(["2021-01-02", "2021-01-04"]),
                "symbol": ["000001.SH", "000001.SH"],
                "trade_type": ["buy", "sell"],
                "price": [101.0, 102.0],
                "target_position": [1.0, 0.0],
                "executed_position": [1.0, 0.0],
                "units": [9.9, 9.9],
                "cash_after_trade": [0.0, 1009.8],
                "portfolio_value_after_trade": [1000.0, 1009.8],
            }
        )
        summary = {
            "symbol": "000001.SH",
            "name": "上证综指",
            "start_date": "2021-01-01",
            "end_date": "2021-01-04",
            "final_nav": 1.0098,
            "total_return": 0.0098,
            "benchmark_return": 0.0,
            "annualized_return": 0.8,
            "max_drawdown": -0.0097,
            "trade_count": 2,
            "signal_count": 2,
            "average_position": 0.5,
            "latest_action": "sell",
            "latest_signal": "bubble_risk",
        }

        with patch("src.cli.index_investment_analysis.DataManager", return_value=fake_data_manager), \
             patch("src.cli.index_investment_analysis.generate_investment_signals", return_value=signal_df), \
             patch("src.cli.index_investment_analysis.run_strategy_backtest", return_value=(equity_df, trades_df, summary)):
            argv = [
                "index_investment_analysis.py",
                "--symbol",
                "000001.SH",
                "--output",
                self.temp_dir,
            ]
            with patch.object(sys, "argv", argv):
                main()

        raw_dir = os.path.join(self.temp_dir, "raw")
        plots_dir = os.path.join(self.temp_dir, "plots")
        reports_dir = os.path.join(self.temp_dir, "reports")
        summary_dir = os.path.join(self.temp_dir, "summary")

        self.assertTrue(os.path.isdir(raw_dir))
        self.assertTrue(os.path.isdir(plots_dir))
        self.assertTrue(os.path.isdir(reports_dir))
        self.assertTrue(os.path.isdir(summary_dir))
        self.assertTrue(any(name.endswith(".csv") for name in os.listdir(raw_dir)))
        self.assertTrue(any(name.endswith(".png") for name in os.listdir(plots_dir)))
        self.assertTrue(any(name.endswith(".md") for name in os.listdir(reports_dir)))
        self.assertTrue(any(name.endswith(".html") for name in os.listdir(reports_dir)))

    def test_cli_falls_back_to_default_params_when_optimal_config_load_fails(self) -> None:
        fake_df = self._make_price_df()
        fake_data_manager = Mock()
        fake_data_manager.get_data.return_value = fake_df

        signal_df = fake_df.copy()
        signal_df["symbol"] = "000001.SH"
        signal_df["lppl_signal"] = ["none"] * 4
        signal_df["signal_strength"] = [0.0] * 4
        signal_df["position_reason"] = ["无信号"] * 4
        signal_df["action"] = ["hold"] * 4
        signal_df["target_position"] = [0.0] * 4

        equity_df = signal_df.copy()
        equity_df["executed_position"] = [0.0] * 4
        equity_df["cash"] = [1000.0] * 4
        equity_df["units"] = [0.0] * 4
        equity_df["holdings_value"] = [0.0] * 4
        equity_df["portfolio_value"] = [1000.0] * 4
        equity_df["strategy_nav"] = [1.0] * 4
        equity_df["benchmark_nav"] = [1.0, 1.0198, 1.0099, 1.0]
        equity_df["daily_return"] = [0.0] * 4
        equity_df["benchmark_return"] = [0.0, 0.0198, -0.0097, -0.0098]
        equity_df["excess_return"] = [0.0, -0.0198, 0.0097, 0.0098]
        equity_df["drawdown"] = [0.0] * 4

        trades_df = pd.DataFrame(
            columns=[
                "date",
                "symbol",
                "trade_type",
                "price",
                "target_position",
                "executed_position",
                "units",
                "cash_after_trade",
                "portfolio_value_after_trade",
            ]
        )
        summary = {
            "symbol": "000001.SH",
            "name": "上证综指",
            "start_date": "2021-01-01",
            "end_date": "2021-01-04",
            "final_nav": 1.0,
            "total_return": 0.0,
            "benchmark_return": 0.0,
            "annualized_return": 0.0,
            "max_drawdown": 0.0,
            "trade_count": 0,
            "signal_count": 0,
            "average_position": 0.0,
            "latest_action": "hold",
            "latest_signal": "none",
        }

        stdout = StringIO()
        with patch("src.cli.index_investment_analysis.DataManager", return_value=fake_data_manager), \
             patch("src.cli.index_investment_analysis.load_optimal_config", side_effect=FileNotFoundError("missing")), \
             patch("src.cli.index_investment_analysis.generate_investment_signals", return_value=signal_df), \
             patch("src.cli.index_investment_analysis.run_strategy_backtest", return_value=(equity_df, trades_df, summary)), \
             patch("sys.stdout", new=stdout):
            argv = [
                "index_investment_analysis.py",
                "--symbol",
                "000001.SH",
                "--output",
                self.temp_dir,
                "--use-optimal-config",
            ]
            with patch.object(sys, "argv", argv):
                main()

        summary_path = os.path.join(self.temp_dir, "summary", "summary_000001_SH_single_window.csv")
        summary_df = pd.read_csv(summary_path)
        self.assertEqual(summary_df.iloc[0]["param_source"], "default_fallback")
        self.assertIn("最优参数文件加载失败，使用默认参数: missing", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
