# -*- coding: utf-8 -*-
import unittest

import pandas as pd

from src.investment.tuning import score_signal_tuning_results


class SignalTuningTests(unittest.TestCase):
    def test_score_signal_tuning_results_prefers_better_risk_adjusted_candidates(self) -> None:
        df = pd.DataFrame(
            [
                {
                    "symbol": "000001.SH",
                    "annualized_return": 0.08,
                    "annualized_excess_return": 0.03,
                    "calmar_ratio": 0.60,
                    "max_drawdown": -0.15,
                    "trade_count": 6,
                    "turnover_rate": 0.80,
                    "whipsaw_rate": 0.20,
                },
                {
                    "symbol": "000001.SH",
                    "annualized_return": 0.12,
                    "annualized_excess_return": 0.07,
                    "calmar_ratio": 1.10,
                    "max_drawdown": -0.10,
                    "trade_count": 8,
                    "turnover_rate": 0.70,
                    "whipsaw_rate": 0.10,
                },
            ]
        )

        scored = score_signal_tuning_results(df)

        self.assertGreater(float(scored.iloc[0]["objective_score"]), float(scored.iloc[1]["objective_score"]))
        self.assertEqual(scored.iloc[0]["risk_band"], "Safe")

    def test_score_signal_tuning_results_marks_low_trade_candidates_ineligible(self) -> None:
        df = pd.DataFrame(
            [
                {
                    "symbol": "000300.SH",
                    "annualized_return": 0.20,
                    "annualized_excess_return": 0.10,
                    "calmar_ratio": 1.50,
                    "max_drawdown": -0.08,
                    "trade_count": 1,
                    "turnover_rate": 0.10,
                    "whipsaw_rate": 0.00,
                }
            ]
        )

        scored = score_signal_tuning_results(df, min_trade_count=3)

        self.assertFalse(bool(scored.iloc[0]["eligible"]))
        self.assertEqual(float(scored.iloc[0]["objective_score"]), -1.0)

    def test_score_signal_tuning_results_rejects_non_positive_excess_and_high_risk(self) -> None:
        df = pd.DataFrame(
            [
                {
                    "symbol": "932000.SH",
                    "annualized_return": 0.09,
                    "annualized_excess_return": -0.01,
                    "calmar_ratio": 0.25,
                    "max_drawdown": -0.41,
                    "trade_count": 9,
                    "turnover_rate": 11.2,
                    "whipsaw_rate": 0.0,
                }
            ]
        )

        scored = score_signal_tuning_results(
            df,
            min_trade_count=3,
            max_drawdown_cap=-0.35,
            turnover_cap=8.0,
            whipsaw_cap=0.35,
        )

        self.assertFalse(bool(scored.iloc[0]["eligible"]))
        self.assertIn("non_positive_excess", scored.iloc[0]["reject_reason"])
        self.assertIn("max_drawdown_cap", scored.iloc[0]["reject_reason"])
        self.assertIn("turnover_cap", scored.iloc[0]["reject_reason"])

    def test_score_signal_tuning_results_supports_risk_reduction_profile(self) -> None:
        df = pd.DataFrame(
            [
                {
                    "symbol": "000016.SH",
                    "annualized_return": 0.05,
                    "annualized_excess_return": 0.02,
                    "calmar_ratio": 0.40,
                    "max_drawdown": -0.28,
                    "trade_count": 6,
                    "turnover_rate": 4.0,
                    "whipsaw_rate": 0.10,
                },
                {
                    "symbol": "000016.SH",
                    "annualized_return": 0.04,
                    "annualized_excess_return": 0.018,
                    "calmar_ratio": 0.55,
                    "max_drawdown": -0.18,
                    "trade_count": 4,
                    "turnover_rate": 2.0,
                    "whipsaw_rate": 0.05,
                },
            ]
        )

        scored = score_signal_tuning_results(df, scoring_profile="risk_reduction")

        self.assertEqual(float(scored.iloc[0]["max_drawdown"]), -0.18)
        self.assertTrue(bool(scored.iloc[0]["eligible"]))

    def test_score_signal_tuning_results_can_keep_scores_for_ineligible_candidates(self) -> None:
        df = pd.DataFrame(
            [
                {
                    "symbol": "399006.SZ",
                    "annualized_return": 0.03,
                    "annualized_excess_return": -0.01,
                    "calmar_ratio": 0.20,
                    "max_drawdown": -0.40,
                    "trade_count": 11,
                    "turnover_rate": 12.0,
                    "whipsaw_rate": 0.05,
                },
                {
                    "symbol": "000905.SH",
                    "annualized_return": 0.04,
                    "annualized_excess_return": -0.02,
                    "calmar_ratio": 0.15,
                    "max_drawdown": -0.42,
                    "trade_count": 3,
                    "turnover_rate": 3.0,
                    "whipsaw_rate": 0.05,
                },
            ]
        )

        scored = score_signal_tuning_results(df, hard_reject=False)

        self.assertFalse(bool(scored.iloc[0]["eligible"]))
        self.assertNotEqual(float(scored.iloc[0]["objective_score"]), -1.0)
        self.assertNotEqual(float(scored.iloc[1]["objective_score"]), -1.0)


if __name__ == "__main__":
    unittest.main()
