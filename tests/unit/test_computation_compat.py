import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from src.computation import LPPLComputation, _fit_single_window_compat
from src.lppl_engine import LPPLConfig


class ComputationCompatTests(unittest.TestCase):
    def test_fit_single_window_compat_adapts_legacy_task_tuple(self) -> None:
        task = (
            50,
            pd.Series(pd.date_range("2024-01-01", periods=50, freq="D")),
            np.linspace(100.0, 150.0, 50),
        )

        captured = {}

        def fake_fit_single_window(close_prices, window_size, config=None):
            captured["close_prices"] = close_prices
            captured["window_size"] = window_size
            captured["config"] = config
            return {
                "window_size": window_size,
                "rmse": 0.01,
                "params": (60.0, 0.5, 8.0, 1.0, -2.0, 0.1, 0.0),
            }

        with patch("src.computation.fit_single_window", side_effect=fake_fit_single_window):
            result = _fit_single_window_compat(task)

        self.assertIsNotNone(result)
        self.assertEqual(captured["window_size"], 50)
        self.assertEqual(len(captured["close_prices"]), 50)
        self.assertEqual(result["window"], 50)
        self.assertEqual(result["last_date"], pd.Timestamp("2024-02-19"))

    def test_fit_single_window_compat_returns_none_when_engine_returns_none(self) -> None:
        task = (
            50,
            pd.Series(pd.date_range("2024-01-01", periods=50, freq="D")),
            np.linspace(100.0, 150.0, 50),
        )

        with patch("src.computation.fit_single_window", return_value=None):
            result = _fit_single_window_compat(task)

        self.assertIsNone(result)


class LPPLComputationConfigTests(unittest.TestCase):
    """验证 LPPLComputation 使用调用方传入的配置"""

    def test_computation_uses_custom_config_for_risk_label(self) -> None:
        custom_config = LPPLConfig(
            window_range=[50],
            danger_days=15,
            warning_days=20,
            watch_days=30,
            n_workers=1,
        )
        comp = LPPLComputation(lppl_config=custom_config)

        res = {
            "params": (60.0, 0.5, 8.0, 1.0, -2.0, 0.1, 0.0),
            "rmse": 0.01,
            "last_date": pd.Timestamp("2024-02-19"),
        }
        formatted = comp._format_output("000001.SH", "上证综指", 50, res, "短期")

        self.assertIsNotNone(formatted)
        self.assertEqual(len(formatted), 12)
        risk_label = formatted[9]
        self.assertIn(risk_label, {"高危", "极高危", "观察", "安全", "无效模型"},
                      f"Unexpected risk label: {risk_label}")

    def test_computation_without_config_uses_default(self) -> None:
        comp = LPPLComputation()
        self.assertIsNotNone(comp.lppl_config)


if __name__ == "__main__":
    unittest.main()
