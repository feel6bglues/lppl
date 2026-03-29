import unittest
from unittest.mock import Mock, patch

import numpy as np
import pandas as pd

import lppl_verify_v2
from src.lppl_engine import (
    LPPLConfig,
    analyze_peak_ensemble,
    calculate_trend_scores,
    find_local_highs,
    process_single_day_ensemble,
    scan_single_date,
)


class LPPLEnsembleTests(unittest.TestCase):
    def _make_dataframe(self) -> pd.DataFrame:
        rows = 240
        dates = pd.date_range(start="2020-01-01", periods=rows, freq="D")
        closes = [100 + idx * 0.5 for idx in range(rows)]
        return pd.DataFrame({"date": dates, "close": closes})

    def test_analyze_peak_ensemble_returns_summary_and_timeline(self) -> None:
        df = self._make_dataframe()
        config = LPPLConfig(
            window_range=[40, 50, 60],
            optimizer="de",
            r2_threshold=0.6,
            danger_days=20,
            warning_days=60,
            consensus_threshold=0.25,
            n_workers=1,
        )

        def fake_process(close_prices, idx, window_range, min_r2=0.6, consensus_threshold=0.25, config=None):
            if idx in {180, 185}:
                return {
                    "idx": idx,
                    "consensus_rate": 0.5,
                    "valid_windows": 2,
                    "predicted_crash_days": 10,
                    "tc_std": 1.2,
                    "signal_strength": 0.7,
                    "avg_r2": 0.81,
                }
            return None

        with patch("src.lppl_engine.process_single_day_ensemble", side_effect=fake_process):
            result = analyze_peak_ensemble(
                df,
                peak_idx=190,
                window_range=config.window_range,
                scan_step=5,
                ma_window=5,
                config=config,
            )

        self.assertIsNotNone(result)
        self.assertTrue(result["detected"])
        self.assertEqual(result["mode"], "ensemble")
        self.assertEqual(result["danger_before_peak"], 2)
        self.assertEqual(len(result["timeline"]), 2)

    def test_run_verification_routes_to_ensemble_analyzer(self) -> None:
        fake_df = self._make_dataframe()
        fake_data_manager = Mock()
        fake_data_manager.get_data.return_value = fake_df

        with patch("src.data.manager.DataManager", return_value=fake_data_manager), \
             patch("lppl_verify_v2.find_local_highs", return_value=[{"idx": 190, "date": fake_df.iloc[190]["date"], "price": 195.0, "drop_pct": 0.2}]), \
             patch("lppl_verify_v2.analyze_peak_ensemble", return_value={
                 "detected": True,
                 "first_danger_days": -5,
                 "first_danger_r2": 0.88,
                 "timeline": [],
             }) as ensemble_mock, \
             patch("lppl_verify_v2.analyze_peak", return_value=None) as single_mock:
            results = lppl_verify_v2.run_verification(
                "000001.SH",
                "上证综指",
                use_ensemble=True,
                max_peaks=1,
            )

        self.assertEqual(len(results), 1)
        self.assertEqual(ensemble_mock.call_count, 1)
        self.assertEqual(single_mock.call_count, 0)

    def test_calculate_trend_scores_uses_config_thresholds(self) -> None:
        daily_results = [
            {"idx": 1, "m": 0.5, "w": 8.0, "days_to_crash": 25, "r_squared": 0.61},
            {"idx": 2, "m": 0.5, "w": 8.0, "days_to_crash": 15, "r_squared": 0.59},
        ]
        config = LPPLConfig(
            window_range=[40, 50, 60],
            r2_threshold=0.6,
            danger_days=20,
            warning_days=30,
            n_workers=1,
        )

        trend_df = calculate_trend_scores(daily_results, ma_window=2, config=config)

        self.assertEqual(trend_df.loc[0, "is_warning"], True)
        self.assertEqual(trend_df.loc[0, "is_danger"], False)
        self.assertEqual(trend_df.loc[1, "is_danger"], False)

    def test_find_local_highs_detects_peak_with_required_drop(self) -> None:
        df = pd.DataFrame(
            {
                "date": pd.date_range("2020-01-01", periods=9, freq="D"),
                "close": [100, 102, 108, 120, 110, 100, 98, 99, 101],
            }
        )

        highs = find_local_highs(df, min_gap=2, min_drop_pct=0.10, window=2)

        self.assertEqual(len(highs), 1)
        self.assertEqual(highs[0]["idx"], 3)
        self.assertAlmostEqual(highs[0]["price"], 120)
        self.assertGreaterEqual(highs[0]["drop_pct"], 0.10)

    def test_scan_single_date_selects_lowest_rmse_result(self) -> None:
        close_prices = np.array([100 + idx for idx in range(120)], dtype=float)
        config = LPPLConfig(window_range=[40, 60], n_workers=1)

        def fake_fit(subset, window_size, config=None):
            if window_size == 40:
                return {"window_size": 40, "rmse": 0.3, "r_squared": 0.8}
            if window_size == 60:
                return {"window_size": 60, "rmse": 0.1, "r_squared": 0.7}
            return None

        with patch("src.lppl_engine.fit_single_window", side_effect=fake_fit):
            result = scan_single_date(close_prices, idx=80, window_range=[40, 60], config=config)

        self.assertIsNotNone(result)
        self.assertEqual(result["window_size"], 60)
        self.assertEqual(result["idx"], 80)

    def test_process_single_day_ensemble_applies_r2_and_consensus_thresholds(self) -> None:
        close_prices = np.array([100 + idx for idx in range(160)], dtype=float)
        config = LPPLConfig(
            window_range=[40, 50, 60],
            r2_threshold=0.6,
            consensus_threshold=0.5,
            danger_days=20,
            warning_days=60,
            n_workers=1,
        )

        def fake_fit(subset, window_size, config=None):
            if window_size == 40:
                return {"r_squared": 0.8, "m": 0.5, "w": 8.0, "days_to_crash": 12}
            if window_size == 50:
                return {"r_squared": 0.75, "m": 0.4, "w": 9.0, "days_to_crash": 18}
            if window_size == 60:
                return {"r_squared": 0.55, "m": 0.5, "w": 8.0, "days_to_crash": 25}
            return None

        with patch("src.lppl_engine.fit_single_window", side_effect=fake_fit):
            result = process_single_day_ensemble(
                close_prices,
                idx=100,
                window_range=[40, 50, 60],
                min_r2=config.r2_threshold,
                consensus_threshold=config.consensus_threshold,
                config=config,
            )

        self.assertIsNotNone(result)
        self.assertEqual(result["valid_windows"], 2)
        self.assertAlmostEqual(result["consensus_rate"], 2 / 3)
        self.assertAlmostEqual(result["predicted_crash_days"], 15.0)
        self.assertGreater(result["signal_strength"], 0.0)


if __name__ == "__main__":
    unittest.main()
