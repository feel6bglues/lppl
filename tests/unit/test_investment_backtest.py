import unittest
from unittest.mock import patch

import pandas as pd

from src.investment.backtest import (
    ActiveLPPLState,
    BacktestConfig,
    InvestmentSignalConfig,
    _evaluate_ma_cross_atr_lppl,
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
        lppl_config = LPPLConfig(window_range=[2], n_workers=1, watch_days=12, warning_days=10, danger_days=9)
        signal_config = InvestmentSignalConfig(signal_model="legacy")

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

    def test_generate_investment_signals_requires_confirmation_for_large_cap_sell(self) -> None:
        df = pd.DataFrame(
            {
                "date": pd.date_range("2021-01-01", periods=7, freq="D"),
                "open": [100, 102, 104, 103, 99, 95, 94],
                "high": [101, 103, 105, 104, 100, 96, 95],
                "low": [99, 101, 103, 98, 94, 92, 91],
                "close": [100, 102, 104, 99, 95, 94, 93],
                "volume": [1000] * 7,
            }
        )
        lppl_config = LPPLConfig(window_range=[2], n_workers=1, watch_days=12, warning_days=8, danger_days=7)
        signal_config = InvestmentSignalConfig(
            signal_model="multi_factor_v1",
            initial_position=1.0,
            trend_fast_ma=2,
            trend_slow_ma=3,
            trend_slope_window=1,
            atr_period=2,
            atr_ma_window=2,
            sell_vote_threshold=3,
            buy_vote_threshold=3,
            positive_consensus_threshold=0.50,
            danger_days=20,
            sell_confirm_days=2,
            buy_confirm_days=2,
            cooldown_days=3,
        )

        def fake_scan(close_prices, idx, window_range, config):
            if idx >= 3:
                return {
                    "m": 0.5,
                    "w": 8.0,
                    "r_squared": 0.91,
                    "rmse": 0.02,
                    "days_to_crash": 6.0,
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
                start_date="2021-01-04",
            )

        self.assertEqual(list(signals_df["action"]), ["hold", "reduce", "hold", "hold"])
        self.assertEqual(list(signals_df["sell_votes"].iloc[:2]), [3, 3])
        self.assertEqual(list(signals_df["sell_streak"]), [1, 0, 0, 0])
        self.assertEqual(signals_df.iloc[1]["target_position"], 0.5)

    def test_generate_investment_signals_requires_lppl_vote(self) -> None:
        df = pd.DataFrame(
            {
                "date": pd.date_range("2021-01-01", periods=6, freq="D"),
                "open": [100, 99, 98, 97, 96, 95],
                "high": [101, 100, 99, 98, 97, 96],
                "low": [99, 98, 97, 96, 95, 94],
                "close": [100, 99, 98, 97, 96, 95],
                "volume": [1000] * 6,
            }
        )
        lppl_config = LPPLConfig(window_range=[2], n_workers=1, watch_days=12, warning_days=8, danger_days=7)
        signal_config = InvestmentSignalConfig(
            signal_model="multi_factor_v1",
            initial_position=1.0,
            trend_fast_ma=2,
            trend_slow_ma=3,
            trend_slope_window=1,
            atr_period=2,
            atr_ma_window=2,
            sell_vote_threshold=3,
            buy_vote_threshold=3,
            sell_confirm_days=1,
            buy_confirm_days=1,
            cooldown_days=1,
        )

        with patch("src.investment.backtest.scan_single_date", return_value=None):
            signals_df = generate_investment_signals(
                df=df,
                symbol="000300.SH",
                signal_config=signal_config,
                lppl_config=lppl_config,
                use_ensemble=False,
                start_date="2021-01-04",
            )

        self.assertTrue((signals_df["action"] == "hold").all())
        self.assertTrue((signals_df["lppl_vote"] == 0).all())

    def test_generate_investment_signals_treats_watch_as_non_tradable(self) -> None:
        df = pd.DataFrame(
            {
                "date": pd.date_range("2021-01-01", periods=6, freq="D"),
                "open": [100, 101, 102, 101, 100, 99],
                "high": [101, 102, 103, 102, 101, 100],
                "low": [99, 100, 101, 100, 99, 98],
                "close": [100, 101, 102, 101, 100, 99],
                "volume": [1000] * 6,
            }
        )
        lppl_config = LPPLConfig(window_range=[2], n_workers=1, watch_days=12, warning_days=6, danger_days=3)
        signal_config = InvestmentSignalConfig(
            signal_model="multi_factor_v1",
            initial_position=1.0,
            trend_fast_ma=2,
            trend_slow_ma=3,
            trend_slope_window=1,
            atr_period=2,
            atr_ma_window=2,
            sell_vote_threshold=1,
            buy_vote_threshold=3,
            sell_confirm_days=1,
            buy_confirm_days=1,
            cooldown_days=0,
            positive_consensus_threshold=0.5,
        )

        def fake_scan(close_prices, idx, window_range, config):
            if idx >= 3:
                return {
                    "m": 0.5,
                    "w": 8.0,
                    "r_squared": 0.55,
                    "rmse": 0.02,
                    "days_to_crash": 10.0,
                    "is_danger": False,
                    "params": (20.0, 0.5, 8.0, 1.0, -2.0, 0.1, 0.0),
                }
            return None

        with patch("src.investment.backtest.scan_single_date", side_effect=fake_scan):
            signals_df = generate_investment_signals(
                df=df,
                symbol="000300.SH",
                signal_config=signal_config,
                lppl_config=lppl_config,
                use_ensemble=False,
                start_date="2021-01-04",
            )

        self.assertTrue((signals_df["action"] == "hold").all())
        self.assertTrue((signals_df["lppl_signal"] == "bubble_watch").all())
        self.assertTrue((signals_df["lppl_vote"] == 0).all())

    def test_generate_investment_signals_can_treat_warning_as_observation_only_in_legacy(self) -> None:
        df = pd.DataFrame(
            {
                "date": pd.date_range("2021-01-01", periods=6, freq="D"),
                "open": [100, 101, 102, 101, 100, 99],
                "high": [101, 102, 103, 102, 101, 100],
                "low": [99, 100, 101, 100, 99, 98],
                "close": [100, 101, 102, 101, 100, 99],
                "volume": [1000] * 6,
            }
        )
        lppl_config = LPPLConfig(window_range=[2], n_workers=1, watch_days=12, warning_days=6, danger_days=3)
        signal_config = InvestmentSignalConfig(
            signal_model="legacy",
            initial_position=1.0,
            warning_trade_enabled=False,
        )

        def fake_scan(close_prices, idx, window_range, config):
            if idx >= 3:
                return {
                    "m": 0.5,
                    "w": 8.0,
                    "r_squared": 0.55,
                    "rmse": 0.02,
                    "days_to_crash": 5.0,
                    "is_danger": False,
                    "params": (20.0, 0.5, 8.0, 1.0, -2.0, 0.1, 0.0),
                }
            return None

        with patch("src.investment.backtest.scan_single_date", side_effect=fake_scan):
            signals_df = generate_investment_signals(
                df=df,
                symbol="000300.SH",
                signal_config=signal_config,
                lppl_config=lppl_config,
                use_ensemble=False,
                start_date="2021-01-04",
            )

        self.assertTrue((signals_df["lppl_signal"] == "bubble_warning").all())
        self.assertTrue((signals_df["action"] == "hold").all())
        self.assertTrue((signals_df["target_position"] == 1.0).all())

    def test_generate_investment_signals_can_treat_warning_as_observation_only_in_multi_factor(self) -> None:
        df = pd.DataFrame(
            {
                "date": pd.date_range("2021-01-01", periods=6, freq="D"),
                "open": [100, 101, 102, 101, 100, 99],
                "high": [101, 102, 103, 102, 101, 100],
                "low": [99, 100, 101, 100, 99, 98],
                "close": [100, 101, 102, 101, 100, 99],
                "volume": [1000] * 6,
            }
        )
        lppl_config = LPPLConfig(window_range=[2], n_workers=1, watch_days=12, warning_days=6, danger_days=3)
        signal_config = InvestmentSignalConfig(
            signal_model="multi_factor_v1",
            initial_position=1.0,
            trend_fast_ma=2,
            trend_slow_ma=3,
            trend_slope_window=1,
            atr_period=2,
            atr_ma_window=2,
            sell_vote_threshold=1,
            buy_vote_threshold=3,
            sell_confirm_days=1,
            buy_confirm_days=1,
            cooldown_days=0,
            positive_consensus_threshold=0.5,
            warning_trade_enabled=False,
        )

        def fake_scan(close_prices, idx, window_range, config):
            if idx >= 3:
                return {
                    "m": 0.5,
                    "w": 8.0,
                    "r_squared": 0.55,
                    "rmse": 0.02,
                    "days_to_crash": 5.0,
                    "is_danger": False,
                    "params": (20.0, 0.5, 8.0, 1.0, -2.0, 0.1, 0.0),
                }
            return None

        with patch("src.investment.backtest.scan_single_date", side_effect=fake_scan):
            signals_df = generate_investment_signals(
                df=df,
                symbol="000300.SH",
                signal_config=signal_config,
                lppl_config=lppl_config,
                use_ensemble=False,
                start_date="2021-01-04",
            )

        self.assertTrue((signals_df["lppl_signal"] == "bubble_warning").all())
        self.assertTrue((signals_df["action"] == "hold").all())
        self.assertTrue((signals_df["lppl_vote"] == 0).all())

    def test_generate_investment_signals_supports_relaxed_danger_r2_threshold(self) -> None:
        df = pd.DataFrame(
            {
                "date": pd.date_range("2021-01-01", periods=6, freq="D"),
                "open": [100, 101, 102, 101, 100, 99],
                "high": [101, 102, 103, 102, 101, 100],
                "low": [99, 100, 101, 100, 99, 98],
                "close": [100, 101, 102, 101, 100, 99],
                "volume": [1000] * 6,
            }
        )
        lppl_config = LPPLConfig(
            window_range=[2],
            n_workers=1,
            r2_threshold=0.50,
            danger_r2_offset=-0.02,
            watch_days=12,
            warning_days=6,
            danger_days=4,
        )
        signal_config = InvestmentSignalConfig(signal_model="legacy", initial_position=1.0)

        def fake_scan(close_prices, idx, window_range, config):
            if idx >= 3:
                return {
                    "m": 0.5,
                    "w": 8.0,
                    "r_squared": 0.49,
                    "rmse": 0.02,
                    "days_to_crash": 3.0,
                    "is_danger": False,
                    "params": (20.0, 0.5, 8.0, 1.0, -2.0, 0.1, 0.0),
                }
            return None

        with patch("src.investment.backtest.scan_single_date", side_effect=fake_scan):
            signals_df = generate_investment_signals(
                df=df,
                symbol="000300.SH",
                signal_config=signal_config,
                lppl_config=lppl_config,
                use_ensemble=False,
                start_date="2021-01-04",
            )

        self.assertTrue((signals_df["lppl_signal"] == "bubble_risk").all())
        self.assertEqual(signals_df.iloc[0]["action"], "sell")
        self.assertTrue((signals_df.iloc[1:]["action"] == "hold").all())

    def test_ma_cross_atr_lppl_model_buys_on_golden_cross_with_atr_confirmation(self) -> None:
        df = pd.DataFrame(
            {
                "date": pd.date_range("2021-01-01", periods=5, freq="D"),
                "open": [100, 99, 98, 103, 104],
                "high": [101, 100, 99, 104, 105],
                "low": [99, 98, 97, 102, 103],
                "close": [100, 99, 98, 103, 104],
                "volume": [1000] * 5,
            }
        )
        lppl_config = LPPLConfig(window_range=[2], n_workers=1)
        signal_config = InvestmentSignalConfig(
            signal_model="ma_cross_atr_lppl_v1",
            initial_position=0.0,
            trend_fast_ma=2,
            trend_slow_ma=3,
            atr_period=2,
            atr_ma_window=2,
            buy_volatility_cap=1.35,
            vol_breakout_mult=1.50,
            buy_confirm_days=1,
            sell_confirm_days=1,
            cooldown_days=0,
        )

        with patch("src.investment.backtest.scan_single_date", return_value=None):
            signals_df = generate_investment_signals(
                df=df,
                symbol="000300.SH",
                signal_config=signal_config,
                lppl_config=lppl_config,
                use_ensemble=False,
                start_date="2021-01-03",
            )

        self.assertEqual(list(signals_df["action"]), ["hold", "buy", "hold"])
        self.assertEqual(signals_df.iloc[1]["lppl_signal"], "none")

    def test_ma_cross_atr_lppl_model_blocks_buy_when_atr_too_high(self) -> None:
        df = pd.DataFrame(
            {
                "date": pd.date_range("2021-01-01", periods=5, freq="D"),
                "open": [100, 99, 98, 110, 111],
                "high": [101, 100, 99, 120, 121],
                "low": [99, 98, 97, 90, 91],
                "close": [100, 99, 98, 110, 111],
                "volume": [1000] * 5,
            }
        )
        lppl_config = LPPLConfig(window_range=[2], n_workers=1)
        signal_config = InvestmentSignalConfig(
            signal_model="ma_cross_atr_lppl_v1",
            initial_position=0.0,
            trend_fast_ma=2,
            trend_slow_ma=3,
            atr_period=2,
            atr_ma_window=2,
            buy_volatility_cap=0.95,
            vol_breakout_mult=1.50,
            buy_confirm_days=1,
            sell_confirm_days=1,
            cooldown_days=0,
        )

        with patch("src.investment.backtest.scan_single_date", return_value=None):
            signals_df = generate_investment_signals(
                df=df,
                symbol="000300.SH",
                signal_config=signal_config,
                lppl_config=lppl_config,
                use_ensemble=False,
                start_date="2021-01-03",
            )

        self.assertTrue((signals_df["action"] == "hold").all())

    def test_evaluate_ma_cross_atr_lppl_respects_buy_volatility_cap_without_hidden_buffer(self) -> None:
        signal_config = InvestmentSignalConfig(
            signal_model="ma_cross_atr_lppl_v1",
            initial_position=0.0,
            buy_volatility_cap=1.00,
            vol_breakout_mult=1.50,
        )
        row = pd.Series(
            {
                "atr_ratio": 1.20,
                "bullish_cross": True,
                "bearish_cross": False,
                "price_drawdown": -0.01,
                "recent_drawdown_min": -0.02,
            }
        )
        state = ActiveLPPLState()

        factor_state = _evaluate_ma_cross_atr_lppl(
            row=row,
            state=state,
            signal_config=signal_config,
            current_target=0.0,
        )

        self.assertFalse(factor_state["buy_candidate"])
        self.assertEqual(factor_state["next_target"], 0.0)

    def test_ma_cross_atr_lppl_model_reduces_on_death_cross_with_atr_confirmation(self) -> None:
        df = pd.DataFrame(
            {
                "date": pd.date_range("2021-01-01", periods=5, freq="D"),
                "open": [100, 105, 110, 96, 95],
                "high": [101, 106, 111, 98, 97],
                "low": [99, 104, 109, 94, 93],
                "close": [100, 105, 110, 96, 95],
                "volume": [1000] * 5,
            }
        )
        lppl_config = LPPLConfig(window_range=[2], n_workers=1)
        signal_config = InvestmentSignalConfig(
            signal_model="ma_cross_atr_lppl_v1",
            initial_position=1.0,
            trend_fast_ma=2,
            trend_slow_ma=3,
            atr_period=2,
            atr_ma_window=2,
            buy_volatility_cap=1.10,
            vol_breakout_mult=1.00,
            buy_confirm_days=1,
            sell_confirm_days=1,
            cooldown_days=0,
        )

        with patch("src.investment.backtest.scan_single_date", return_value=None):
            signals_df = generate_investment_signals(
                df=df,
                symbol="000300.SH",
                signal_config=signal_config,
                lppl_config=lppl_config,
                use_ensemble=False,
                start_date="2021-01-03",
            )

        self.assertEqual(list(signals_df["action"]), ["hold", "reduce", "hold"])
        self.assertEqual(signals_df.iloc[1]["target_position"], 0.5)

    def test_ma_cross_atr_v1_waits_for_indicator_warmup_before_trading(self) -> None:
        df = pd.DataFrame(
            {
                "date": pd.date_range("2021-01-01", periods=4, freq="D"),
                "open": [100, 99, 105, 106],
                "high": [101, 100, 106, 107],
                "low": [99, 98, 104, 105],
                "close": [100, 99, 105, 106],
                "volume": [1000] * 4,
            }
        )
        signal_config = InvestmentSignalConfig(
            signal_model="ma_cross_atr_v1",
            initial_position=0.0,
            trend_fast_ma=2,
            trend_slow_ma=4,
            atr_period=2,
            atr_ma_window=4,
            buy_volatility_cap=10.0,
            vol_breakout_mult=10.0,
        )

        signals_df = generate_investment_signals(
            df=df,
            symbol="000300.SH",
            signal_config=signal_config,
            lppl_config=None,
            use_ensemble=False,
            start_date="2021-01-01",
        )

        self.assertTrue((signals_df["action"] == "hold").all())
        self.assertEqual(signals_df.iloc[0]["position_reason"], "指标预热")

    def test_ma_cross_atr_lppl_model_warning_only_reduces_position(self) -> None:
        df = pd.DataFrame(
            {
                "date": pd.date_range("2021-01-01", periods=5, freq="D"),
                "open": [100, 101, 102, 103, 104],
                "high": [101, 102, 103, 104, 105],
                "low": [99, 100, 101, 102, 103],
                "close": [100, 101, 102, 103, 104],
                "volume": [1000] * 5,
            }
        )
        lppl_config = LPPLConfig(window_range=[2], n_workers=1, watch_days=12, warning_days=6, danger_days=4)
        signal_config = InvestmentSignalConfig(
            signal_model="ma_cross_atr_lppl_v1",
            initial_position=1.0,
            trend_fast_ma=2,
            trend_slow_ma=3,
            atr_period=2,
            atr_ma_window=2,
            buy_confirm_days=1,
            sell_confirm_days=1,
            cooldown_days=0,
        )

        def fake_scan(close_prices, idx, window_range, config):
            if idx >= 3:
                return {
                    "m": 0.5,
                    "w": 8.0,
                    "r_squared": 0.60,
                    "rmse": 0.02,
                    "days_to_crash": 5.0,
                    "is_danger": False,
                    "params": (20.0, 0.5, 8.0, 1.0, -2.0, 0.1, 0.0),
                }
            return None

        with patch("src.investment.backtest.scan_single_date", side_effect=fake_scan):
            signals_df = generate_investment_signals(
                df=df,
                symbol="000300.SH",
                signal_config=signal_config,
                lppl_config=lppl_config,
                use_ensemble=False,
                start_date="2021-01-03",
            )

        self.assertEqual(list(signals_df["action"]), ["hold", "reduce", "hold"])
        self.assertEqual(signals_df.iloc[1]["target_position"], 0.5)
        self.assertEqual(signals_df.iloc[1]["lppl_signal"], "bubble_warning")

    def test_ma_cross_atr_lppl_model_only_clears_inside_three_day_danger_window(self) -> None:
        df = pd.DataFrame(
            {
                "date": pd.date_range("2021-01-01", periods=5, freq="D"),
                "open": [100, 101, 102, 103, 104],
                "high": [101, 102, 103, 104, 105],
                "low": [99, 100, 101, 102, 103],
                "close": [100, 101, 102, 103, 104],
                "volume": [1000] * 5,
            }
        )
        lppl_config = LPPLConfig(
            window_range=[2],
            n_workers=1,
            watch_days=12,
            warning_days=6,
            danger_days=5,
            danger_r2_offset=-0.02,
        )
        signal_config = InvestmentSignalConfig(
            signal_model="ma_cross_atr_lppl_v1",
            initial_position=1.0,
            trend_fast_ma=2,
            trend_slow_ma=3,
            atr_period=2,
            atr_ma_window=2,
            buy_confirm_days=1,
            sell_confirm_days=1,
            cooldown_days=0,
            full_exit_days=3,
        )

        def fake_scan(close_prices, idx, window_range, config):
            if idx == 3:
                return {
                    "m": 0.5,
                    "w": 8.0,
                    "r_squared": 0.60,
                    "rmse": 0.02,
                    "days_to_crash": 4.0,
                    "is_danger": False,
                    "params": (20.0, 0.5, 8.0, 1.0, -2.0, 0.1, 0.0),
                }
            if idx == 4:
                return {
                    "m": 0.5,
                    "w": 8.0,
                    "r_squared": 0.60,
                    "rmse": 0.02,
                    "days_to_crash": 2.0,
                    "is_danger": True,
                    "params": (20.0, 0.5, 8.0, 1.0, -2.0, 0.1, 0.0),
                }
            return None

        with patch("src.investment.backtest.scan_single_date", side_effect=fake_scan):
            signals_df = generate_investment_signals(
                df=df,
                symbol="000300.SH",
                signal_config=signal_config,
                lppl_config=lppl_config,
                use_ensemble=False,
                start_date="2021-01-03",
            )

        self.assertEqual(list(signals_df["action"]), ["hold", "reduce", "sell"])
        self.assertEqual(signals_df.iloc[1]["target_position"], 0.5)
        self.assertEqual(signals_df.iloc[2]["target_position"], 0.0)

    def test_generate_investment_signals_supports_stepwise_position_ladder(self) -> None:
        df = pd.DataFrame(
            {
                "date": pd.date_range("2021-01-01", periods=8, freq="D"),
                "open": [100, 101, 102, 103, 104, 103, 101, 99],
                "high": [101, 102, 103, 104, 105, 104, 102, 100],
                "low": [99, 100, 101, 102, 103, 101, 99, 97],
                "close": [100, 101, 102, 103, 104, 102, 100, 98],
                "volume": [1000] * 8,
            }
        )
        lppl_config = LPPLConfig(window_range=[2], n_workers=1, watch_days=12, warning_days=8, danger_days=7)
        signal_config = InvestmentSignalConfig(
            signal_model="multi_factor_v1",
            initial_position=0.0,
            trend_fast_ma=2,
            trend_slow_ma=3,
            trend_slope_window=1,
            atr_period=2,
            atr_ma_window=2,
            sell_vote_threshold=2,
            buy_vote_threshold=2,
            sell_confirm_days=1,
            buy_confirm_days=1,
            cooldown_days=0,
            require_trend_recovery_for_buy=False,
            positive_consensus_threshold=0.5,
            negative_consensus_threshold=0.2,
            danger_days=20,
            rebound_days=20,
            enable_regime_hysteresis=False,
        )

        def fake_scan(close_prices, idx, window_range, config):
            if idx in {3, 4}:
                return {
                    "m": 0.5,
                    "w": 8.0,
                    "r_squared": 0.91,
                    "rmse": 0.02,
                    "days_to_crash": 8.0,
                    "is_danger": False,
                    "params": (20.0, 0.5, 8.0, 1.0, 2.0, 0.1, 0.0),
                }
            if idx in {5, 6}:
                return {
                    "m": 0.5,
                    "w": 8.0,
                    "r_squared": 0.91,
                    "rmse": 0.02,
                    "days_to_crash": 6.0,
                    "is_danger": True,
                    "params": (20.0, 0.5, 8.0, 1.0, -2.0, 0.1, 0.0),
                }
            return None

        with patch("src.investment.backtest.scan_single_date", side_effect=fake_scan):
            signals_df = generate_investment_signals(
                df=df,
                symbol="000300.SH",
                signal_config=signal_config,
                lppl_config=lppl_config,
                use_ensemble=False,
                start_date="2021-01-04",
            )

        self.assertEqual(list(signals_df["action"]), ["buy", "add", "reduce", "sell", "hold"])
        self.assertEqual(list(signals_df["target_position"]), [0.5, 1.0, 0.5, 0.0, 0.0])

    def test_generate_investment_signals_allows_warning_then_danger_sell_in_same_regime(self) -> None:
        df = pd.DataFrame(
            {
                "date": pd.date_range("2021-01-01", periods=7, freq="D"),
                "open": [100, 101, 102, 101, 99, 97, 96],
                "high": [101, 102, 103, 102, 100, 98, 97],
                "low": [99, 100, 101, 99, 96, 94, 93],
                "close": [100, 101, 102, 100, 97, 95, 94],
                "volume": [1000] * 7,
            }
        )
        lppl_config = LPPLConfig(window_range=[2], n_workers=1, watch_days=12, warning_days=8, danger_days=3)
        signal_config = InvestmentSignalConfig(
            signal_model="multi_factor_v1",
            initial_position=1.0,
            trend_fast_ma=2,
            trend_slow_ma=3,
            trend_slope_window=1,
            atr_period=2,
            atr_ma_window=2,
            sell_vote_threshold=1,
            buy_vote_threshold=3,
            sell_confirm_days=1,
            buy_confirm_days=1,
            cooldown_days=0,
            positive_consensus_threshold=0.5,
            enable_regime_hysteresis=True,
        )

        def fake_scan(close_prices, idx, window_range, config):
            if idx == 3:
                return {
                    "m": 0.5,
                    "w": 8.0,
                    "r_squared": 0.52,
                    "rmse": 0.02,
                    "days_to_crash": 6.0,
                    "is_danger": False,
                    "params": (20.0, 0.5, 8.0, 1.0, -2.0, 0.1, 0.0),
                }
            if idx in {4, 5}:
                return {
                    "m": 0.5,
                    "w": 8.0,
                    "r_squared": 0.87,
                    "rmse": 0.02,
                    "days_to_crash": 2.0,
                    "is_danger": True,
                    "params": (20.0, 0.5, 8.0, 1.0, -2.0, 0.1, 0.0),
                }
            return None

        with patch("src.investment.backtest.scan_single_date", side_effect=fake_scan):
            signals_df = generate_investment_signals(
                df=df,
                symbol="000300.SH",
                signal_config=signal_config,
                lppl_config=lppl_config,
                use_ensemble=False,
                start_date="2021-01-04",
            )

        self.assertEqual(list(signals_df["action"]), ["reduce", "sell", "hold", "hold"])
        self.assertEqual(list(signals_df["target_position"]), [0.5, 0.0, 0.0, 0.0])

    def test_generate_investment_signals_caps_buy_position_under_high_volatility(self) -> None:
        df = pd.DataFrame(
            {
                "date": pd.date_range("2021-01-01", periods=7, freq="D"),
                "open": [100, 101, 102, 103, 104, 105, 106],
                "high": [101, 102, 103, 104, 105, 106, 107],
                "low": [99, 100, 101, 102, 103, 104, 105],
                "close": [100, 101, 102, 103, 104, 105, 106],
                "volume": [1000] * 7,
            }
        )
        lppl_config = LPPLConfig(window_range=[2], n_workers=1, watch_days=12, warning_days=8, danger_days=7)
        signal_config = InvestmentSignalConfig(
            signal_model="multi_factor_v1",
            initial_position=0.0,
            trend_fast_ma=2,
            trend_slow_ma=3,
            trend_slope_window=1,
            atr_period=2,
            atr_ma_window=2,
            sell_vote_threshold=2,
            buy_vote_threshold=2,
            sell_confirm_days=1,
            buy_confirm_days=1,
            cooldown_days=0,
            buy_reentry_drawdown_threshold=0.0,
            high_volatility_mult=0.0,
            high_volatility_position_cap=0.5,
        )

        def fake_scan(close_prices, idx, window_range, config):
            if idx in {3, 4}:
                return {
                    "m": 0.5,
                    "w": 8.0,
                    "r_squared": 0.91,
                    "rmse": 0.02,
                    "days_to_crash": 8.0,
                    "is_danger": False,
                    "params": (20.0, 0.5, 8.0, 1.0, 2.0, 0.1, 0.0),
                }
            return None

        with patch("src.investment.backtest.scan_single_date", side_effect=fake_scan):
            signals_df = generate_investment_signals(
                df=df,
                symbol="000300.SH",
                signal_config=signal_config,
                lppl_config=lppl_config,
                use_ensemble=False,
                start_date="2021-01-04",
            )

        self.assertEqual(list(signals_df["action"]), ["buy", "hold", "hold", "hold"])
        self.assertEqual(list(signals_df["target_position"]), [0.5, 0.5, 0.5, 0.5])
        self.assertTrue((signals_df["vol_position_cap"] == 0.5).all())

    def test_generate_investment_signals_blocks_immediate_reentry_after_sell(self) -> None:
        df = pd.DataFrame(
            {
                "date": pd.date_range("2021-01-01", periods=8, freq="D"),
                "open": [100, 101, 102, 100, 99, 100, 101, 102],
                "high": [101, 102, 103, 101, 100, 101, 102, 103],
                "low": [99, 100, 101, 98, 97, 99, 100, 101],
                "close": [100, 101, 102, 99, 98, 100, 101, 102],
                "volume": [1000] * 8,
            }
        )
        lppl_config = LPPLConfig(window_range=[2], n_workers=1)
        signal_config = InvestmentSignalConfig(
            signal_model="multi_factor_v1",
            initial_position=0.5,
            trend_fast_ma=2,
            trend_slow_ma=3,
            trend_slope_window=1,
            atr_period=2,
            atr_ma_window=2,
            sell_vote_threshold=2,
            buy_vote_threshold=1,
            sell_confirm_days=1,
            buy_confirm_days=1,
            cooldown_days=0,
            post_sell_reentry_cooldown_days=2,
            buy_reentry_drawdown_threshold=0.0,
            require_trend_recovery_for_buy=False,
        )

        def fake_scan(close_prices, idx, window_range, config):
            if idx == 3:
                return {
                    "m": 0.5,
                    "w": 8.0,
                    "r_squared": 0.91,
                    "rmse": 0.02,
                    "days_to_crash": 6.0,
                    "is_danger": True,
                    "params": (20.0, 0.5, 8.0, 1.0, -2.0, 0.1, 0.0),
                }
            if idx in {4, 5, 6}:
                return {
                    "m": 0.5,
                    "w": 8.0,
                    "r_squared": 0.91,
                    "rmse": 0.02,
                    "days_to_crash": 8.0,
                    "is_danger": False,
                    "params": (20.0, 0.5, 8.0, 1.0, 2.0, 0.1, 0.0),
                }
            return None

        with patch("src.investment.backtest.scan_single_date", side_effect=fake_scan):
            signals_df = generate_investment_signals(
                df=df,
                symbol="000300.SH",
                signal_config=signal_config,
                lppl_config=lppl_config,
                use_ensemble=False,
                start_date="2021-01-04",
            )

        self.assertEqual(list(signals_df["action"]), ["sell", "hold", "hold", "buy", "hold"])
        self.assertEqual(list(signals_df["target_position"]), [0.0, 0.0, 0.0, 0.5, 0.5])
        self.assertEqual(list(signals_df["buy_reentry_block_remaining"]), [2, 2, 1, 0, 0])

    def test_generate_investment_signals_requires_drawdown_reentry_for_bottom_buy(self) -> None:
        df = pd.DataFrame(
            {
                "date": pd.date_range("2021-01-01", periods=10, freq="D"),
                "open": [100, 102, 104, 106, 103, 100, 102, 104, 105, 106],
                "high": [101, 103, 105, 107, 104, 101, 103, 105, 106, 107],
                "low": [99, 101, 103, 105, 100, 98, 100, 102, 104, 105],
                "close": [100, 102, 104, 106, 103, 100, 102, 104, 105, 106],
                "volume": [1000] * 10,
            }
        )
        lppl_config = LPPLConfig(window_range=[2], n_workers=1)
        signal_config = InvestmentSignalConfig(
            signal_model="multi_factor_v1",
            initial_position=0.0,
            trend_fast_ma=2,
            trend_slow_ma=3,
            trend_slope_window=1,
            atr_period=2,
            atr_ma_window=2,
            buy_vote_threshold=3,
            sell_vote_threshold=2,
            buy_confirm_days=1,
            sell_confirm_days=1,
            cooldown_days=0,
            buy_reentry_drawdown_threshold=0.03,
            buy_reentry_lookback=4,
        )

        def fake_scan(close_prices, idx, window_range, config):
            if idx in {3, 7}:
                return {
                    "m": 0.5,
                    "w": 8.0,
                    "r_squared": 0.91,
                    "rmse": 0.02,
                    "days_to_crash": 8.0,
                    "is_danger": False,
                    "params": (20.0, 0.5, 8.0, 1.0, 2.0, 0.1, 0.0),
                }
            return None

        with patch("src.investment.backtest.scan_single_date", side_effect=fake_scan):
            signals_df = generate_investment_signals(
                df=df,
                symbol="000905.SH",
                signal_config=signal_config,
                lppl_config=lppl_config,
                use_ensemble=False,
                start_date="2021-01-04",
            )

        self.assertEqual(signals_df.iloc[0]["drawdown_buy_vote"], 0)
        self.assertEqual(signals_df.iloc[0]["action"], "hold")
        self.assertEqual(signals_df.loc[signals_df["date"] == pd.Timestamp("2021-01-08"), "drawdown_buy_vote"].iloc[0], 1)
        self.assertEqual(signals_df.loc[signals_df["date"] == pd.Timestamp("2021-01-08"), "action"].iloc[0], "buy")

    def test_generate_investment_signals_applies_regime_hysteresis_to_bottom_regime(self) -> None:
        df = pd.DataFrame(
            {
                "date": pd.date_range("2021-01-01", periods=9, freq="D"),
                "open": [100, 101, 102, 103, 104, 104, 103, 104, 105],
                "high": [101, 102, 103, 104, 105, 105, 104, 105, 106],
                "low": [99, 100, 101, 102, 103, 103, 102, 103, 104],
                "close": [100, 101, 102, 103, 104, 104, 103, 104, 105],
                "volume": [1000] * 9,
            }
        )
        lppl_config = LPPLConfig(window_range=[2], n_workers=1)
        signal_config = InvestmentSignalConfig(
            signal_model="multi_factor_v1",
            initial_position=0.0,
            trend_fast_ma=2,
            trend_slow_ma=3,
            trend_slope_window=1,
            atr_period=2,
            atr_ma_window=2,
            buy_vote_threshold=2,
            sell_vote_threshold=2,
            buy_confirm_days=1,
            sell_confirm_days=1,
            cooldown_days=0,
            buy_reentry_drawdown_threshold=0.0,
            require_trend_recovery_for_buy=False,
        )

        def fake_scan(close_prices, idx, window_range, config):
            if idx in {3, 4, 7}:
                return {
                    "m": 0.5,
                    "w": 8.0,
                    "r_squared": 0.91,
                    "rmse": 0.02,
                    "days_to_crash": 8.0,
                    "is_danger": False,
                    "params": (20.0, 0.5, 8.0, 1.0, 2.0, 0.1, 0.0),
                }
            return None

        with patch("src.investment.backtest.scan_single_date", side_effect=fake_scan):
            signals_df = generate_investment_signals(
                df=df,
                symbol="000300.SH",
                signal_config=signal_config,
                lppl_config=lppl_config,
                use_ensemble=False,
                start_date="2021-01-04",
            )

        self.assertEqual(list(signals_df["action"]), ["buy", "hold", "hold", "hold", "hold", "hold"])
        self.assertEqual(list(signals_df["target_position"]), [0.5, 0.5, 0.5, 0.5, 0.5, 0.5])

    def test_generate_investment_signals_blocks_sell_during_min_hold_without_override(self) -> None:
        df = pd.DataFrame(
            {
                "date": pd.date_range("2021-01-01", periods=9, freq="D"),
                "open": [100, 101, 102, 103, 99, 98, 97, 96, 95],
                "high": [101, 102, 103, 104, 100, 99, 98, 97, 96],
                "low": [99, 100, 101, 102, 96, 95, 94, 93, 92],
                "close": [100, 101, 102, 103, 98, 97, 96, 95, 94],
                "volume": [1000] * 9,
            }
        )
        lppl_config = LPPLConfig(window_range=[2], n_workers=1)
        signal_config = InvestmentSignalConfig(
            signal_model="multi_factor_v1",
            initial_position=0.0,
            trend_fast_ma=2,
            trend_slow_ma=3,
            trend_slope_window=1,
            atr_period=2,
            atr_ma_window=2,
            buy_vote_threshold=2,
            sell_vote_threshold=2,
            buy_confirm_days=1,
            sell_confirm_days=1,
            cooldown_days=0,
            min_hold_bars=3,
            allow_top_risk_override_min_hold=False,
            buy_reentry_drawdown_threshold=0.0,
            require_trend_recovery_for_buy=False,
        )

        def fake_scan(close_prices, idx, window_range, config):
            if idx == 3:
                return {
                    "m": 0.5,
                    "w": 8.0,
                    "r_squared": 0.91,
                    "rmse": 0.02,
                    "days_to_crash": 8.0,
                    "is_danger": False,
                    "params": (20.0, 0.5, 8.0, 1.0, 2.0, 0.1, 0.0),
                }
            if idx in {4, 5, 6, 7}:
                return {
                    "m": 0.5,
                    "w": 8.0,
                    "r_squared": 0.91,
                    "rmse": 0.02,
                    "days_to_crash": 6.0,
                    "is_danger": True,
                    "params": (20.0, 0.5, 8.0, 1.0, -2.0, 0.1, 0.0),
                }
            return None

        with patch("src.investment.backtest.scan_single_date", side_effect=fake_scan):
            signals_df = generate_investment_signals(
                df=df,
                symbol="000300.SH",
                signal_config=signal_config,
                lppl_config=lppl_config,
                use_ensemble=False,
                start_date="2021-01-04",
            )

        self.assertEqual(list(signals_df["action"]), ["buy", "hold", "hold", "hold", "sell", "hold"])
        self.assertEqual(list(signals_df["holding_bars"]), [0, 0, 1, 2, 3, 0])

    def test_generate_investment_signals_allows_clear_top_risk_to_override_min_hold(self) -> None:
        df = pd.DataFrame(
            {
                "date": pd.date_range("2021-01-01", periods=7, freq="D"),
                "open": [100, 101, 102, 103, 99, 98, 97],
                "high": [101, 102, 103, 104, 100, 99, 98],
                "low": [99, 100, 101, 102, 96, 95, 94],
                "close": [100, 101, 102, 103, 98, 97, 96],
                "volume": [1000] * 7,
            }
        )
        lppl_config = LPPLConfig(window_range=[2], n_workers=1, watch_days=12, warning_days=8, danger_days=7)
        signal_config = InvestmentSignalConfig(
            signal_model="multi_factor_v1",
            initial_position=0.0,
            trend_fast_ma=2,
            trend_slow_ma=3,
            trend_slope_window=1,
            atr_period=2,
            atr_ma_window=2,
            buy_vote_threshold=2,
            sell_vote_threshold=2,
            buy_confirm_days=1,
            sell_confirm_days=1,
            cooldown_days=0,
            min_hold_bars=3,
            allow_top_risk_override_min_hold=True,
            buy_reentry_drawdown_threshold=0.0,
            require_trend_recovery_for_buy=False,
        )

        def fake_scan(close_prices, idx, window_range, config):
            if idx == 3:
                return {
                    "m": 0.5,
                    "w": 8.0,
                    "r_squared": 0.91,
                    "rmse": 0.02,
                    "days_to_crash": 8.0,
                    "is_danger": False,
                    "params": (20.0, 0.5, 8.0, 1.0, 2.0, 0.1, 0.0),
                }
            if idx == 4:
                return {
                    "m": 0.5,
                    "w": 8.0,
                    "r_squared": 0.91,
                    "rmse": 0.02,
                    "days_to_crash": 6.0,
                    "is_danger": True,
                    "params": (20.0, 0.5, 8.0, 1.0, -2.0, 0.1, 0.0),
                }
            return None

        with patch("src.investment.backtest.scan_single_date", side_effect=fake_scan):
            signals_df = generate_investment_signals(
                df=df,
                symbol="000300.SH",
                signal_config=signal_config,
                lppl_config=lppl_config,
                use_ensemble=False,
                start_date="2021-01-04",
            )

        self.assertEqual(list(signals_df["action"]), ["buy", "sell", "hold", "hold"])

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

    def test_run_strategy_backtest_does_not_rebalance_on_hold_days(self) -> None:
        signal_df = pd.DataFrame(
            {
                "date": pd.date_range("2021-01-01", periods=3, freq="D"),
                "symbol": ["000001.SH"] * 3,
                "open": [100.0, 120.0, 125.0],
                "high": [101.0, 121.0, 126.0],
                "low": [99.0, 119.0, 124.0],
                "close": [100.0, 120.0, 125.0],
                "volume": [1000, 1000, 1000],
                "lppl_signal": ["negative_bubble", "none", "none"],
                "signal_strength": [0.9, 0.0, 0.0],
                "position_reason": ["买入", "无信号", "无信号"],
                "action": ["buy", "hold", "hold"],
                "target_position": [0.5, 0.5, 0.5],
            }
        )

        equity_df, trades_df, summary = run_strategy_backtest(
            signal_df,
            BacktestConfig(initial_capital=1000.0, buy_fee=0.0, sell_fee=0.0, slippage=0.0),
        )

        self.assertEqual(len(trades_df), 1)
        self.assertEqual(trades_df.iloc[0]["trade_type"], "buy")
        self.assertEqual(list(equity_df["trade_flag"]), [True, False, False])
        self.assertEqual(summary["trade_count"], 1)

    def test_run_strategy_backtest_returns_empty_trades_with_expected_columns(self) -> None:
        signal_df = pd.DataFrame(
            {
                "date": pd.date_range("2021-01-01", periods=3, freq="D"),
                "symbol": ["000001.SH"] * 3,
                "open": [100.0, 101.0, 102.0],
                "high": [101.0, 102.0, 103.0],
                "low": [99.0, 100.0, 101.0],
                "close": [100.0, 101.0, 102.0],
                "volume": [1000, 1000, 1000],
                "lppl_signal": ["none", "none", "none"],
                "signal_strength": [0.0, 0.0, 0.0],
                "position_reason": ["无信号", "无信号", "无信号"],
                "action": ["hold", "hold", "hold"],
                "target_position": [0.0, 0.0, 0.0],
            }
        )

        _, trades_df, summary = run_strategy_backtest(
            signal_df,
            BacktestConfig(initial_capital=1000.0, buy_fee=0.0, sell_fee=0.0, slippage=0.0),
        )

        self.assertEqual(len(trades_df), 0)
        self.assertIn("trade_type", trades_df.columns)
        self.assertEqual(summary["trade_count"], 0)

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

    def test_run_strategy_backtest_preserves_trade_export_columns(self) -> None:
        signal_df = pd.DataFrame(
            {
                "date": pd.date_range("2021-01-01", periods=4, freq="D"),
                "symbol": ["000001.SH"] * 4,
                "open": [100.0, 101.0, 102.0, 103.0],
                "high": [101.0, 102.0, 103.0, 104.0],
                "low": [99.0, 100.0, 101.0, 102.0],
                "close": [100.0, 101.0, 102.0, 103.0],
                "volume": [1000.0] * 4,
                "lppl_signal": ["none"] * 4,
                "signal_strength": [0.0] * 4,
                "position_reason": ["无信号"] * 4,
                "action": ["hold", "buy", "hold", "sell"],
                "target_position": [0.0, 1.0, 1.0, 0.0],
            }
        )

        _, trades_df, _ = run_strategy_backtest(signal_df, BacktestConfig(initial_capital=1000.0))

        self.assertEqual(
            list(trades_df.columns),
            [
                "date",
                "symbol",
                "trade_type",
                "price",
                "target_position",
                "units",
                "cash_after_trade",
                "holdings_value_after_trade",
                "portfolio_value_after_trade",
                "executed_position",
            ],
        )
        self.assertFalse(
            trades_df[["cash_after_trade", "holdings_value_after_trade", "portfolio_value_after_trade"]]
            .isna()
            .any()
            .any()
        )

    def test_run_strategy_backtest_uses_actual_first_day_return(self) -> None:
        signal_df = pd.DataFrame(
            {
                "date": pd.date_range("2021-01-01", periods=2, freq="D"),
                "symbol": ["000001.SH"] * 2,
                "open": [100.0, 100.0],
                "high": [101.0, 101.0],
                "low": [99.0, 99.0],
                "close": [100.0, 100.0],
                "volume": [1000.0, 1000.0],
                "lppl_signal": ["negative_bubble", "none"],
                "signal_strength": [0.9, 0.0],
                "position_reason": ["买入", "持有"],
                "action": ["buy", "hold"],
                "target_position": [1.0, 1.0],
            }
        )

        equity_df, _, _ = run_strategy_backtest(
            signal_df,
            BacktestConfig(initial_capital=1000.0, buy_fee=0.01, sell_fee=0.0, slippage=0.0),
        )

        self.assertLess(float(equity_df.iloc[0]["daily_return"]), 0.0)
        self.assertAlmostEqual(float(equity_df.iloc[0]["daily_return"]), -0.009900990099, places=8)

    def test_generate_investment_signals_respects_scan_step(self) -> None:
        df = self._make_price_df()
        lppl_config = LPPLConfig(window_range=[2], n_workers=1)
        signal_config = InvestmentSignalConfig(signal_model="legacy")

        with patch("src.investment.backtest.scan_single_date", return_value=None) as scan_mock:
            generate_investment_signals(
                df=df,
                symbol="000001.SH",
                signal_config=signal_config,
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
        signal_config = InvestmentSignalConfig(signal_model="legacy")

        with patch("src.investment.backtest.scan_single_date", return_value=None) as scan_mock:
            signals_df = generate_investment_signals(
                df=df,
                symbol="000001.SH",
                signal_config=signal_config,
                lppl_config=lppl_config,
                use_ensemble=False,
                start_date="2021-01-05",
                end_date="2021-01-07",
            )

        self.assertEqual(list(signals_df["date"].dt.strftime("%Y-%m-%d")), ["2021-01-05", "2021-01-06", "2021-01-07"])
        self.assertEqual(scan_mock.call_count, 6)


if __name__ == "__main__":
    unittest.main()
