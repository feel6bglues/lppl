# -*- coding: utf-8 -*-
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from src.investment.group_rescan import (
    BALANCED_PLAN,
    HIGH_BETA_PLAN,
    LARGE_CAP_YAML_PARAMS,
    build_candidate_yaml_lines,
    build_group_report,
    build_merged_candidate_yaml_lines,
    build_rescan_grid,
    summarize_rescan_results,
)


class GroupRescanExecutionTests(unittest.TestCase):
    def test_build_candidate_yaml_lines_only_covers_large_cap_symbols(self) -> None:
        lines = build_candidate_yaml_lines()
        payload = "\n".join(lines)

        self.assertIn('"000001.SH"', payload)
        self.assertIn('"000016.SH"', payload)
        self.assertIn('"000300.SH"', payload)
        self.assertNotIn('"399001.SZ"', payload)
        self.assertIn("signal_model: ma_cross_atr_v1", payload)
        self.assertIn("trend_fast_ma: 20", payload)
        self.assertIn("trend_slow_ma: 250", payload)
        self.assertIn("target_volatility: 0.12", payload)

        for key, value in LARGE_CAP_YAML_PARAMS.items():
            rendered = "true" if value is True else "false" if value is False else value
            self.assertIn(str(rendered), payload)

    def test_build_rescan_grid_matches_balanced_plan_dimensions(self) -> None:
        grid = build_rescan_grid(BALANCED_PLAN)

        expected = (
            len(BALANCED_PLAN.ma_combos)
            * len(BALANCED_PLAN.atr_periods)
            * len(BALANCED_PLAN.atr_ma_windows)
            * len(BALANCED_PLAN.buy_volatility_caps)
            * len(BALANCED_PLAN.vol_breakout_mults)
            * (1 + len(BALANCED_PLAN.target_volatilities))
        )

        self.assertEqual(len(grid), expected)
        self.assertIn((20, 120), {(item["fast_ma"], item["slow_ma"]) for item in grid})
        self.assertIn(False, {bool(item["enable_volatility_scaling"]) for item in grid})
        self.assertIn(True, {bool(item["enable_volatility_scaling"]) for item in grid})

    def test_build_rescan_grid_matches_high_beta_plan_constraints(self) -> None:
        grid = build_rescan_grid(HIGH_BETA_PLAN)

        # target_volatilities only applies when enable_volatility_scaling=True
        vol_off_count = (
            len(HIGH_BETA_PLAN.ma_combos)
            * len(HIGH_BETA_PLAN.atr_periods)
            * len(HIGH_BETA_PLAN.atr_ma_windows)
            * len(HIGH_BETA_PLAN.buy_volatility_caps)
            * len(HIGH_BETA_PLAN.vol_breakout_mults)
            * 1  # target_volatilities[0] only when scaling is off
        )
        vol_on_count = (
            len(HIGH_BETA_PLAN.ma_combos)
            * len(HIGH_BETA_PLAN.atr_periods)
            * len(HIGH_BETA_PLAN.atr_ma_windows)
            * len(HIGH_BETA_PLAN.buy_volatility_caps)
            * len(HIGH_BETA_PLAN.vol_breakout_mults)
            * len(HIGH_BETA_PLAN.target_volatilities)
        )
        expected = vol_off_count + vol_on_count

        self.assertEqual(len(grid), expected)
        self.assertIn(False, {bool(item["enable_volatility_scaling"]) for item in grid})
        self.assertIn(True, {bool(item["enable_volatility_scaling"]) for item in grid})
        self.assertIn((5, 250), {(item["fast_ma"], item["slow_ma"]) for item in grid})
        self.assertIn(20, {int(item["atr_period"]) for item in grid})

    def test_summarize_rescan_results_generates_candidate_level_fields(self) -> None:
        raw_df = pd.DataFrame(
            [
                {
                    "group": "balanced",
                    "symbol": "399001.SZ",
                    "candidate_key": "a",
                    "fast_ma": 20,
                    "slow_ma": 120,
                    "atr_period": 14,
                    "atr_ma_window": 20,
                    "buy_volatility_cap": 1.00,
                    "vol_breakout_mult": 1.05,
                    "enable_volatility_scaling": False,
                    "target_volatility": 0.15,
                    "annualized_excess_return": 0.03,
                    "max_drawdown": -0.20,
                    "trade_count": 4,
                    "turnover_rate": 2.0,
                    "whipsaw_rate": 0.15,
                    "calmar_ratio": 0.60,
                    "eligible": True,
                },
                {
                    "group": "balanced",
                    "symbol": "000905.SH",
                    "candidate_key": "a",
                    "fast_ma": 20,
                    "slow_ma": 120,
                    "atr_period": 14,
                    "atr_ma_window": 20,
                    "buy_volatility_cap": 1.00,
                    "vol_breakout_mult": 1.05,
                    "enable_volatility_scaling": False,
                    "target_volatility": 0.15,
                    "annualized_excess_return": 0.01,
                    "max_drawdown": -0.22,
                    "trade_count": 5,
                    "turnover_rate": 3.0,
                    "whipsaw_rate": 0.10,
                    "calmar_ratio": 0.40,
                    "eligible": True,
                },
                {
                    "group": "balanced",
                    "symbol": "399001.SZ",
                    "candidate_key": "b",
                    "fast_ma": 30,
                    "slow_ma": 250,
                    "atr_period": 14,
                    "atr_ma_window": 60,
                    "buy_volatility_cap": 1.05,
                    "vol_breakout_mult": 1.15,
                    "enable_volatility_scaling": True,
                    "target_volatility": 0.18,
                    "annualized_excess_return": -0.01,
                    "max_drawdown": -0.36,
                    "trade_count": 2,
                    "turnover_rate": 10.0,
                    "whipsaw_rate": 0.40,
                    "calmar_ratio": 0.10,
                    "eligible": False,
                },
                {
                    "group": "balanced",
                    "symbol": "000905.SH",
                    "candidate_key": "b",
                    "fast_ma": 30,
                    "slow_ma": 250,
                    "atr_period": 14,
                    "atr_ma_window": 60,
                    "buy_volatility_cap": 1.05,
                    "vol_breakout_mult": 1.15,
                    "enable_volatility_scaling": True,
                    "target_volatility": 0.18,
                    "annualized_excess_return": 0.00,
                    "max_drawdown": -0.34,
                    "trade_count": 2,
                    "turnover_rate": 7.0,
                    "whipsaw_rate": 0.45,
                    "calmar_ratio": 0.15,
                    "eligible": False,
                },
            ]
        )

        summary_df = summarize_rescan_results(raw_df, BALANCED_PLAN)

        self.assertEqual(summary_df.iloc[0]["candidate_key"], "a")
        self.assertEqual(int(summary_df.iloc[0]["eligible_count"]), 2)
        self.assertTrue(bool(summary_df.iloc[0]["group_pass"]))
        self.assertIn("objective_score", summary_df.columns)
        self.assertIn("reject_reason", summary_df.columns)

    def test_build_group_report_writes_expected_sections(self) -> None:
        summary_df = pd.DataFrame(
            [
                {
                    "group": "high_beta",
                    "candidate_key": "x",
                    "fast_ma": 5,
                    "slow_ma": 250,
                    "atr_period": 20,
                    "atr_ma_window": 40,
                    "buy_volatility_cap": 1.05,
                    "vol_breakout_mult": 1.15,
                    "enable_volatility_scaling": True,
                    "target_volatility": 0.20,
                    "eligible_count": 1,
                    "symbol_count": 3,
                    "group_pass": True,
                    "avg_excess": 0.02,
                    "avg_drawdown": -0.28,
                    "avg_trade_count": 4.0,
                    "avg_turnover": 2.5,
                    "avg_whipsaw": 0.20,
                    "avg_calmar_ratio": 0.55,
                    "objective_score": 0.88,
                    "eligible": True,
                    "risk_band": "Watch",
                    "suggest_position": "60-80%",
                    "reject_reason": "",
                }
            ]
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            report_path = Path(tmpdir) / "report.md"
            build_group_report(report_path, HIGH_BETA_PLAN, summary_df)
            payload = report_path.read_text(encoding="utf-8")

        self.assertIn("# high_beta MA rescan report", payload)
        self.assertIn("目标通过线", payload)
        self.assertIn("MA5/250", payload)
        self.assertIn("eligible_count=1/3", payload)

    def test_build_merged_candidate_yaml_lines_includes_balanced_best_but_not_high_beta(self) -> None:
        balanced_summary = pd.DataFrame(
            [
                {
                    "group": "balanced",
                    "candidate_key": "best",
                    "fast_ma": 10,
                    "slow_ma": 120,
                    "atr_period": 14,
                    "atr_ma_window": 40,
                    "buy_volatility_cap": 1.00,
                    "vol_breakout_mult": 1.05,
                    "enable_volatility_scaling": True,
                    "target_volatility": 0.15,
                    "eligible_count": 1,
                    "symbol_count": 2,
                    "annualized_excess_return": 0.02,
                    "max_drawdown": -0.24,
                    "eligible": True,
                }
            ]
        )
        high_beta_summary = pd.DataFrame(
            [
                {
                    "group": "high_beta",
                    "candidate_key": "skip",
                    "fast_ma": 20,
                    "slow_ma": 120,
                    "atr_period": 20,
                    "atr_ma_window": 20,
                    "buy_volatility_cap": 1.00,
                    "vol_breakout_mult": 1.05,
                    "enable_volatility_scaling": True,
                    "target_volatility": 0.20,
                    "eligible_count": 1,
                    "symbol_count": 3,
                    "annualized_excess_return": -0.01,
                    "max_drawdown": -0.28,
                    "eligible": False,
                }
            ]
        )

        lines = build_merged_candidate_yaml_lines(balanced_summary, high_beta_summary)
        payload = "\n".join(lines)

        self.assertIn('"000001.SH"', payload)
        self.assertIn('"399001.SZ"', payload)
        self.assertIn('"000905.SH"', payload)
        self.assertIn("trend_fast_ma: 10", payload)
        self.assertIn("atr_ma_window: 40", payload)
        self.assertIn("target_volatility: 0.15", payload)
        self.assertNotIn('"399006.SZ"', payload)
        self.assertNotIn('"000852.SH"', payload)


if __name__ == "__main__":
    unittest.main()
