import unittest
from unittest.mock import patch

import pandas as pd

from src.lppl_engine import LPPLConfig
from src.verification.walk_forward import (
    evaluate_future_drawdown,
    run_walk_forward,
    summarize_walk_forward,
)


class WalkForwardTests(unittest.TestCase):
    def test_evaluate_future_drawdown_detects_drop(self) -> None:
        prices = [100, 98, 92, 89, 95]
        hit, drop, tc_error = evaluate_future_drawdown(prices, idx=0, lookahead_days=4, drop_threshold=0.10)
        self.assertTrue(hit)
        self.assertAlmostEqual(drop, 0.11, places=2)

    def test_summarize_walk_forward_metrics(self) -> None:
        records_df = pd.DataFrame(
            [
                {"signal_detected": True, "event_hit": True},
                {"signal_detected": True, "event_hit": False},
                {"signal_detected": False, "event_hit": True},
                {"signal_detected": False, "event_hit": False},
            ]
        )

        summary = summarize_walk_forward(records_df)

        self.assertEqual(summary["true_positive"], 1)
        self.assertEqual(summary["false_positive"], 1)
        self.assertEqual(summary["false_negative"], 1)
        self.assertAlmostEqual(summary["precision"], 0.5)
        self.assertAlmostEqual(summary["recall"], 0.5)

    def test_run_walk_forward_uses_signal_function(self) -> None:
        df = pd.DataFrame(
            {
                "date": pd.date_range("2020-01-01", periods=140, freq="D"),
                "close": [100 + idx * 0.2 for idx in range(140)],
            }
        )
        config = LPPLConfig(window_range=[40, 50, 60], n_workers=1)

        def fake_scan(close_prices, idx, window_range, config):
            if idx == 60:
                return {"is_danger": True}
            return None

        with patch("src.verification.walk_forward.scan_single_date", side_effect=fake_scan):
            records_df, summary = run_walk_forward(
                df=df,
                symbol="000001.SH",
                window_range=config.window_range,
                config=config,
                scan_step=20,
                lookahead_days=20,
                drop_threshold=0.05,
                use_ensemble=False,
            )

        self.assertEqual(len(records_df), 3)
        self.assertEqual(int(records_df["signal_detected"].sum()), 1)
        self.assertEqual(summary["signal_count"], 1)
        self.assertEqual(summary["symbol"], "000001.SH")


if __name__ == "__main__":
    unittest.main()
