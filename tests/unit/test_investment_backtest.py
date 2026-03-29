import unittest
from unittest.mock import patch

import pandas as pd

from src.investment.backtest import (
    BacktestConfig,
    InvestmentSignalConfig,
    calculate_drawdown,
    generate_investment_signals,
    run_strategy_backtest,
)
from src.lppl_engine import LPPLConfig


class InvestmentBacktestTests(unittest.TestCase):
    def _make_price_df(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "date": pd.date_range("2021-01-01", periods=6, freq="D"),
                "open": [100, 102, 101, 98, 96, 97],
                "high": [103, 104, 102, 99, 98, 99],
                "low": [99, 100, 97, 95, 94, 95],
                "close": [102, 101, 98, 96, 97, 99],
                "volume": [1000, 1100, 1200, 1300, 1250, 1400],
            }
        )

    def test_generate_investment_signals_maps_buy_and_sell_actions(self) -> None:
        df = self._make_price_df()
        lppl_config = LPPLConfig(window_range=[2], n_workers=1)
        signal_config = InvestmentSignalConfig()

        def fake_scan(close_prices, idx, window_range, config):
            if idx == 2:
                return {
                    "m": 0.5,
                    "w": 8.0,
                    "r_squared": 0.91,
                    "rmse": 0.02,
                    "days_to_crash": 10.0,
                    "is_danger": False,
                    "params": (20.0, 0.5, 8.0, 1.0, 2.0, 0.1, 0.0),
                }
            if idx == 3:
                return {
                    "m": 0.5,
                    "w": 8.0,
                    "r_squared": 0.88,
                    "rmse": 0.02,
                    "days_to_crash": 8.0,
                    "is_danger": True,
                    "params": (20.0, 0.5, 8.0, 1.0, -2.0, 0.1, 0.0),
                }
            return None

        with patch("src.investment.backtest.scan_single_date", side_effect=fake_scan):
            signals_df = generate_investment_signals(
                df=df,
                symbol="000001.SH",
                signal_config=signal_config,
                lppl_config=lppl_config,
                use_ensemble=False,
            )

        signal_rows = signals_df.loc[signals_df["date"].isin(pd.to_datetime(["2021-01-03", "2021-01-04"]))]
        self.assertEqual(signal_rows.iloc[0]["action"], "buy")
        self.assertEqual(signal_rows.iloc[0]["target_position"], 1.0)
        self.assertEqual(signal_rows.iloc[0]["lppl_signal"], "negative_bubble")
        self.assertEqual(signal_rows.iloc[1]["action"], "sell")
        self.assertEqual(signal_rows.iloc[1]["target_position"], 0.0)
        self.assertEqual(signal_rows.iloc[1]["lppl_signal"], "bubble_risk")

    def test_run_strategy_backtest_executes_positions_and_costs(self) -> None:
        signal_df = pd.DataFrame(
            {
                "date": pd.date_range("2021-01-01", periods=3, freq="D"),
                "symbol": ["000001.SH"] * 3,
                "open": [100.0, 120.0, 120.0],
                "high": [110.0, 121.0, 121.0],
                "low": [99.0, 119.0, 119.0],
                "close": [110.0, 120.0, 120.0],
                "volume": [1000, 1000, 1000],
                "lppl_signal": ["negative_bubble", "none", "bubble_risk"],
                "signal_strength": [0.9, 0.0, 0.95],
                "position_reason": ["强抄底信号", "无信号", "高危信号"],
                "action": ["buy", "hold", "sell"],
                "target_position": [1.0, 1.0, 0.0],
            }
        )
        config = BacktestConfig(
            initial_capital=1000.0,
            buy_fee=0.01,
            sell_fee=0.01,
            slippage=0.0,
        )

        equity_df, trades_df, summary = run_strategy_backtest(signal_df, config)

        self.assertEqual(len(trades_df), 2)
        self.assertEqual(trades_df.iloc[0]["trade_type"], "buy")
        self.assertEqual(trades_df.iloc[1]["trade_type"], "sell")
        self.assertAlmostEqual(equity_df.iloc[0]["strategy_nav"], 1.0891089, places=4)
        self.assertAlmostEqual(equity_df.iloc[-1]["strategy_nav"], 1.1762376, places=4)
        self.assertAlmostEqual(summary["final_nav"], equity_df.iloc[-1]["strategy_nav"], places=6)
        self.assertLess(summary["max_drawdown"], 0.0)

    def test_calculate_drawdown_tracks_running_peak(self) -> None:
        drawdown_df = calculate_drawdown(pd.Series([1.0, 1.1, 1.05, 1.2, 0.9], name="strategy_nav"))

        self.assertEqual(drawdown_df.iloc[0]["running_max"], 1.0)
        self.assertAlmostEqual(drawdown_df.iloc[2]["drawdown"], -0.0454545, places=6)
        self.assertAlmostEqual(drawdown_df.iloc[4]["drawdown"], -0.25, places=6)

    def test_run_strategy_backtest_respects_date_window(self) -> None:
        signal_df = pd.DataFrame(
            {
                "date": pd.date_range("2021-01-01", periods=5, freq="D"),
                "symbol": ["000001.SH"] * 5,
                "open": [100, 101, 102, 103, 104],
                "high": [101, 102, 103, 104, 105],
                "low": [99, 100, 101, 102, 103],
                "close": [100, 102, 104, 103, 105],
                "volume": [1000] * 5,
                "lppl_signal": ["none"] * 5,
                "signal_strength": [0.0] * 5,
                "position_reason": ["无信号"] * 5,
                "action": ["hold", "buy", "hold", "sell", "hold"],
                "target_position": [0.0, 1.0, 1.0, 0.0, 0.0],
            }
        )
        config = BacktestConfig(
            initial_capital=1000.0,
            start_date="2021-01-02",
            end_date="2021-01-04",
        )

        equity_df, trades_df, _ = run_strategy_backtest(signal_df, config)

        self.assertEqual(list(equity_df["date"].dt.strftime("%Y-%m-%d")), ["2021-01-02", "2021-01-03", "2021-01-04"])
        self.assertEqual(len(trades_df), 2)

    def test_generate_investment_signals_respects_scan_step(self) -> None:
        df = self._make_price_df()
        lppl_config = LPPLConfig(window_range=[2], n_workers=1)

        with patch("src.investment.backtest.scan_single_date", return_value=None) as scan_mock:
            generate_investment_signals(
                df=df,
                symbol="000001.SH",
                lppl_config=lppl_config,
                use_ensemble=False,
                scan_step=2,
            )

        self.assertEqual(scan_mock.call_count, 2)

    def test_generate_investment_signals_respects_signal_window(self) -> None:
        df = pd.DataFrame(
            {
                "date": pd.date_range("2021-01-01", periods=8, freq="D"),
                "open": [100 + idx for idx in range(8)],
                "high": [101 + idx for idx in range(8)],
                "low": [99 + idx for idx in range(8)],
                "close": [100 + idx for idx in range(8)],
                "volume": [1000] * 8,
            }
        )
        lppl_config = LPPLConfig(window_range=[2], n_workers=1)

        with patch("src.investment.backtest.scan_single_date", return_value=None) as scan_mock:
            signals_df = generate_investment_signals(
                df=df,
                symbol="000001.SH",
                lppl_config=lppl_config,
                use_ensemble=False,
                start_date="2021-01-05",
                end_date="2021-01-07",
            )

        self.assertEqual(list(signals_df["date"].dt.strftime("%Y-%m-%d")), ["2021-01-05", "2021-01-06", "2021-01-07"])
        self.assertEqual(scan_mock.call_count, 3)


if __name__ == "__main__":
    unittest.main()
