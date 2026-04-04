# -*- coding: utf-8 -*-
import argparse
import unittest
from io import StringIO
from unittest.mock import patch

from src.cli.tune_signal_model import _candidate_grid, _resolve_configs, _resolve_requested_symbols


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


if __name__ == "__main__":
    unittest.main()
