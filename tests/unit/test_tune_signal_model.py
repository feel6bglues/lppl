# -*- coding: utf-8 -*-
import argparse
import unittest
from io import StringIO
from unittest.mock import Mock, patch

import pandas as pd

from src.cli.tune_signal_model import (
    _candidate_grid,
    _resolve_configs,
    _resolve_requested_symbols,
    _run_single_symbol,
)


class TuneSignalModelTests(unittest.TestCase):
    def test_candidate_grid_expands_new_round_two_dimensions(self) -> None:
        args = argparse.Namespace(
            positive_offsets="-0.10,0.00",
            negative_offsets="0.00",
            sell_votes="2,3",
            buy_votes="2,3",
            sell_confirms="1,2",
            buy_confirms="1,2",
            vol_breakout_grid="1.00,1.05",
            drawdown_grid="0.03,0.05",
            cooldown_grid="5,10",
            buy_volatility_cap_grid="1.00,1.05",
        )

        grid = list(_candidate_grid(args))

        self.assertEqual(len(grid), 512)

    def test_resolve_requested_symbols_supports_comma_separated_input(self) -> None:
        args = argparse.Namespace(
            all=False,
            symbol=None,
            symbols="000300.SH,000016.SH",
        )

        symbols = _resolve_requested_symbols(args)

        self.assertEqual(symbols, ["000300.SH", "000016.SH"])

    def test_resolve_configs_falls_back_when_optimal_config_load_fails(self) -> None:
        stdout = StringIO()
        with patch("src.cli.tune_signal_model.load_optimal_config", side_effect=FileNotFoundError("missing")), \
             patch("sys.stdout", new=stdout):
            resolved, lppl_config = _resolve_configs(
                symbol="000300.SH",
                optimal_config_path="missing.yaml",
                base_step=7,
                use_ensemble=False,
            )

        self.assertEqual(int(resolved["step"]), 7)
        self.assertEqual(str(resolved["signal_model"]), "multi_factor_v1")
        self.assertEqual(list(lppl_config.window_range), list(resolved["window_range"]))
        self.assertEqual(int(lppl_config.watch_days), int(resolved["watch_days"]))
        self.assertIn("最优参数文件加载失败，使用默认参数: missing", stdout.getvalue())

    def test_run_single_symbol_preserves_resolved_signal_model(self) -> None:
        args = argparse.Namespace(
            optimal_config_path="config/optimal_params.yaml",
            step=5,
            ensemble=False,
            start_date="2024-01-01",
            end_date="2024-06-30",
            initial_capital=1_000_000.0,
            buy_fee=0.0003,
            sell_fee=0.0003,
            slippage=0.0005,
            positive_offsets="0.00",
            negative_offsets="0.00",
            sell_votes="2",
            buy_votes="3",
            sell_confirms="1",
            buy_confirms="2",
            vol_breakout_grid="1.05",
            drawdown_grid="0.05",
            cooldown_grid="10",
            buy_volatility_cap_grid="1.05",
            min_trades=1,
            max_drawdown_cap=-0.50,
            turnover_cap=20.0,
            whipsaw_cap=1.0,
            scoring_profile="balanced",
            output="unused",
        )
        fake_df = pd.DataFrame(
            {
                "date": pd.date_range("2024-01-01", periods=4, freq="D"),
                "open": [100.0, 101.0, 102.0, 103.0],
                "high": [101.0, 102.0, 103.0, 104.0],
                "low": [99.0, 100.0, 101.0, 102.0],
                "close": [100.0, 101.0, 102.0, 103.0],
                "volume": [1000.0] * 4,
            }
        )
        fake_manager = Mock()
        fake_manager.get_data.return_value = fake_df
        captured = {}

        def _capture_signal_df(**kwargs):
            captured["signal_model"] = kwargs["signal_config"].signal_model
            return fake_df.copy()

        with patch("src.cli.tune_signal_model.DataManager", return_value=fake_manager), \
             patch("src.cli.tune_signal_model.generate_investment_signals", side_effect=_capture_signal_df), \
             patch(
                 "src.cli.tune_signal_model.run_strategy_backtest",
                 return_value=(fake_df.copy(), pd.DataFrame(), {"annualized_excess_return": 0.01, "max_drawdown": -0.1, "trade_count": 3}),
             ):
            _run_single_symbol("000300.SH", args, "unused")

        self.assertEqual(captured["signal_model"], "ma_cross_atr_v1")


if __name__ == "__main__":
    unittest.main()
