import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from src.computation import _fit_single_window_compat


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


if __name__ == "__main__":
    unittest.main()
