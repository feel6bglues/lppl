# -*- coding: utf-8 -*-
import argparse
import unittest

from src.cli.tune_signal_model import _candidate_grid, _resolve_requested_symbols


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


if __name__ == "__main__":
    unittest.main()
