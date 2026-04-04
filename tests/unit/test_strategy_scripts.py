# -*- coding: utf-8 -*-
import unittest

import pandas as pd

from ma_cross_atr_optimization import _is_eligible, build_signal_mapping
from personal_investor_optimization import run_backtest


class StrategyScriptTests(unittest.TestCase):
    def test_ma_cross_atr_optimization_eligible_uses_summary_metrics(self) -> None:
        summary = {
            "annualized_excess_return": 0.05,
            "max_drawdown": -0.20,
            "trade_count": 6,
            "turnover_rate": 2.0,
            "whipsaw_rate": 0.10,
        }

        self.assertTrue(_is_eligible(summary))

    def test_ma_cross_atr_optimization_eligible_rejects_high_turnover(self) -> None:
        summary = {
            "annualized_excess_return": 0.05,
            "max_drawdown": -0.20,
            "trade_count": 6,
            "turnover_rate": 12.0,
            "whipsaw_rate": 0.10,
        }

        self.assertFalse(_is_eligible(summary))

    def test_build_signal_mapping_can_enable_volatility_scaling(self) -> None:
        mapping = build_signal_mapping(
            fast_ma=20,
            slow_ma=60,
            atr_period=14,
            atr_ma_window=40,
            buy_volatility_cap=1.05,
            vol_breakout_mult=1.15,
            enable_volatility_scaling=True,
            target_volatility=0.12,
        )

        self.assertEqual(mapping["signal_model"], "ma_cross_atr_v1")
        self.assertTrue(mapping["enable_volatility_scaling"])
        self.assertEqual(mapping["target_volatility"], 0.12)
        self.assertEqual(mapping["trend_fast_ma"], 20)
        self.assertEqual(mapping["trend_slow_ma"], 60)

    def test_personal_investor_backtest_does_not_report_position_when_buy_cannot_execute(self) -> None:
        df = pd.DataFrame(
            {
                "date": pd.date_range("2021-01-01", periods=360, freq="D"),
                "open": [100.0] * 360,
                "high": [101.0] * 360,
                "low": [99.0] * 360,
                "close": ([100.0] * 355) + [101.0, 102.0, 103.0, 104.0, 105.0],
                "volume": [1000.0] * 360,
            }
        )
        config = {
            "initial_capital": 1_000.0,
            "ma_fast": 2,
            "ma_slow": 3,
            "atr_period": 2,
            "atr_ma_window": 2,
            "buy_volatility_cap": 10.0,
            "vol_breakout_mult": 10.0,
            "cooldown_days": 0,
            "confirm_days": 1,
        }

        result_df, trades_df, summary = run_backtest(df, config)

        self.assertTrue(trades_df.empty)
        self.assertEqual(int(summary["trade_count"]), 0)
        self.assertTrue((result_df["actual_shares"] == 0).all())
        self.assertTrue((result_df["executed_position"] == 0.0).all())

    def test_personal_investor_backtest_scales_add_position_from_current_portfolio(self) -> None:
        closes = ([100.0] * 351) + [105.0, 110.0, 200.0, 200.0, 200.0, 200.0, 200.0, 200.0, 200.0]
        df = pd.DataFrame(
            {
                "date": pd.date_range("2021-01-01", periods=len(closes), freq="D"),
                "open": closes,
                "high": [value + 1.0 for value in closes],
                "low": [value - 1.0 for value in closes],
                "close": closes,
                "volume": [1000.0] * len(closes),
            }
        )
        config = {
            "initial_capital": 1_000_000.0,
            "ma_fast": 2,
            "ma_slow": 3,
            "atr_period": 2,
            "atr_ma_window": 2,
            "buy_volatility_cap": 10.0,
            "vol_breakout_mult": 10.0,
            "cooldown_days": 2,
            "confirm_days": 1,
        }

        result_df, trades_df, summary = run_backtest(df, config)

        self.assertGreaterEqual(int(summary["trade_count"]), 2)
        self.assertGreaterEqual(int(result_df["actual_shares"].max()), 4000)

    def test_personal_investor_turnover_matches_main_backtest_notional_definition(self) -> None:
        df = pd.DataFrame(
            {
                "date": pd.date_range("2021-01-01", periods=360, freq="D"),
                "open": [100.0] * 360,
                "high": [101.0] * 360,
                "low": [99.0] * 360,
                "close": ([100.0] * 355) + [101.0, 102.0, 103.0, 104.0, 105.0],
                "volume": [1000.0] * 360,
            }
        )
        config = {
            "initial_capital": 1_000_000.0,
            "ma_fast": 2,
            "ma_slow": 3,
            "atr_period": 2,
            "atr_ma_window": 2,
            "buy_volatility_cap": 10.0,
            "vol_breakout_mult": 10.0,
            "cooldown_days": 0,
            "confirm_days": 1,
        }

        _, trades_df, summary = run_backtest(df, config)

        expected_turnover = float((trades_df["shares"] * trades_df["price"]).sum() / config["initial_capital"])
        self.assertAlmostEqual(float(summary["turnover_rate"]), expected_turnover, places=8)


if __name__ == "__main__":
    unittest.main()
