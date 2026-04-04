# -*- coding: utf-8 -*-
import unittest

import pandas as pd

from grouped_ma_atr_optimization import (
    GROUPS,
    build_group_candidates,
    generate_yaml_suggestions,
    is_group_eligible,
    summarize_group_results,
)


class GroupedMaAtrOptimizationTests(unittest.TestCase):
    def test_build_group_candidates_includes_baseline_and_volatility_scaling(self) -> None:
        candidates = build_group_candidates(GROUPS[0])

        self.assertTrue(any(not item["enable_volatility_scaling"] for item in candidates))
        self.assertTrue(any(item["enable_volatility_scaling"] for item in candidates))

    def test_is_group_eligible_uses_group_drawdown_cap(self) -> None:
        summary = {
            "annualized_excess_return": 0.02,
            "max_drawdown": -0.38,
            "trade_count": 4,
            "turnover_rate": 2.0,
            "whipsaw_rate": 0.10,
        }

        self.assertFalse(is_group_eligible(summary, -0.35))
        self.assertTrue(is_group_eligible(summary, -0.40))

    def test_summarize_group_results_ranks_more_eligible_configs_first(self) -> None:
        df = pd.DataFrame(
            [
                {
                    "group": "large_cap",
                    "candidate_key": "a",
                    "enable_volatility_scaling": False,
                    "target_volatility": 0.15,
                    "atr_period": 14,
                    "atr_ma_window": 20,
                    "buy_volatility_cap": 1.00,
                    "vol_breakout_mult": 1.15,
                    "group_eligible": True,
                    "annualized_excess_return": 0.03,
                    "max_drawdown": -0.20,
                    "trade_count": 4,
                    "turnover_rate": 2.0,
                    "whipsaw_rate": 0.10,
                },
                {
                    "group": "large_cap",
                    "candidate_key": "a",
                    "enable_volatility_scaling": False,
                    "target_volatility": 0.15,
                    "atr_period": 14,
                    "atr_ma_window": 20,
                    "buy_volatility_cap": 1.00,
                    "vol_breakout_mult": 1.15,
                    "group_eligible": True,
                    "annualized_excess_return": 0.01,
                    "max_drawdown": -0.22,
                    "trade_count": 4,
                    "turnover_rate": 2.0,
                    "whipsaw_rate": 0.10,
                },
                {
                    "group": "large_cap",
                    "candidate_key": "b",
                    "enable_volatility_scaling": True,
                    "target_volatility": 0.12,
                    "atr_period": 14,
                    "atr_ma_window": 60,
                    "buy_volatility_cap": 1.00,
                    "vol_breakout_mult": 1.05,
                    "group_eligible": False,
                    "annualized_excess_return": 0.05,
                    "max_drawdown": -0.30,
                    "trade_count": 2,
                    "turnover_rate": 2.0,
                    "whipsaw_rate": 0.10,
                },
            ]
        )

        summary_df = summarize_group_results(df)
        self.assertEqual(summary_df.iloc[0]["candidate_key"], "a")
        self.assertEqual(int(summary_df.iloc[0]["group_eligible"]), 2)

    def test_generate_yaml_suggestions_omits_target_volatility_when_scaling_off(self) -> None:
        summary_df = pd.DataFrame(
            [
                {
                    "group": "large_cap",
                    "candidate_key": "a",
                    "enable_volatility_scaling": False,
                    "target_volatility": 0.15,
                    "atr_period": 14,
                    "atr_ma_window": 20,
                    "buy_volatility_cap": 1.00,
                    "vol_breakout_mult": 1.15,
                    "group_eligible": 2,
                    "avg_excess": 0.02,
                    "avg_drawdown": -0.20,
                    "avg_trades": 4.0,
                    "avg_turnover": 2.0,
                    "avg_whipsaw": 0.1,
                },
                {
                    "group": "balanced",
                    "candidate_key": "b",
                    "enable_volatility_scaling": True,
                    "target_volatility": 0.18,
                    "atr_period": 14,
                    "atr_ma_window": 60,
                    "buy_volatility_cap": 1.05,
                    "vol_breakout_mult": 1.05,
                    "group_eligible": 1,
                    "avg_excess": 0.01,
                    "avg_drawdown": -0.25,
                    "avg_trades": 5.0,
                    "avg_turnover": 2.0,
                    "avg_whipsaw": 0.1,
                },
                {
                    "group": "high_beta",
                    "candidate_key": "c",
                    "enable_volatility_scaling": True,
                    "target_volatility": 0.20,
                    "atr_period": 20,
                    "atr_ma_window": 40,
                    "buy_volatility_cap": 1.00,
                    "vol_breakout_mult": 1.05,
                    "group_eligible": 1,
                    "avg_excess": 0.01,
                    "avg_drawdown": -0.30,
                    "avg_trades": 5.0,
                    "avg_turnover": 2.0,
                    "avg_whipsaw": 0.1,
                },
            ]
        )

        lines = generate_yaml_suggestions(summary_df)
        payload = "\n".join(lines)

        self.assertIn('"000300.SH"', payload)
        self.assertIn("enable_volatility_scaling: false", payload)
        self.assertIn('"399001.SZ"', payload)
        self.assertIn("target_volatility: 0.18", payload)


if __name__ == "__main__":
    unittest.main()
