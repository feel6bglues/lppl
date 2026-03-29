# -*- coding: utf-8 -*-
import os
import tempfile
import unittest

import src.config.optimal_params as optimal_params
from src.config.optimal_params import load_optimal_config, resolve_symbol_params


class OptimalParamsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fallback = {
            "step": 5,
            "window_range": [40, 60, 80],
            "r2_threshold": 0.6,
            "consensus_threshold": 0.25,
            "danger_days": 20,
            "warning_days": 60,
            "optimizer": "de",
            "lookahead_days": 60,
            "drop_threshold": 0.10,
            "ma_window": 5,
            "max_peaks": 10,
        }
        self.config_data = {
            "defaults": {"optimizer": "lbfgsb", "drop_threshold": 0.12},
            "window_sets": {
                "narrow_40_120": [40, 50, 60, 70, 80, 90, 100, 110, 120],
            },
            "symbols": {
                "000001.SH": {
                    "step": 120,
                    "window_set": "narrow_40_120",
                    "r2_threshold": 0.50,
                    "consensus_threshold": 0.20,
                    "danger_days": 20,
                }
            },
        }

    def test_resolve_symbol_params_applies_symbol_and_defaults(self) -> None:
        resolved, warnings = resolve_symbol_params(self.config_data, "000001.SH", self.fallback)

        self.assertEqual(warnings, [])
        self.assertEqual(resolved["param_source"], "optimal_yaml")
        self.assertEqual(resolved["step"], 120)
        self.assertEqual(resolved["window_set"], "narrow_40_120")
        self.assertEqual(resolved["window_range"][0], 40)
        self.assertEqual(resolved["window_range"][-1], 120)
        self.assertEqual(resolved["optimizer"], "lbfgsb")
        self.assertAlmostEqual(resolved["drop_threshold"], 0.12)

    def test_resolve_symbol_params_fallback_when_symbol_missing(self) -> None:
        resolved, warnings = resolve_symbol_params(self.config_data, "399001.SZ", self.fallback)

        self.assertEqual(resolved["param_source"], "default_fallback")
        self.assertEqual(resolved["step"], self.fallback["step"])
        self.assertEqual(resolved["window_range"], self.fallback["window_range"])
        self.assertTrue(any("未在最优参数配置中定义" in msg for msg in warnings))

    def test_resolve_symbol_params_invalid_values_fallback_with_warning(self) -> None:
        bad_data = {
            "defaults": {},
            "window_sets": {},
            "symbols": {
                "000001.SH": {
                    "step": -2,
                    "window_set": "missing_set",
                    "r2_threshold": 1.5,
                }
            },
        }
        resolved, warnings = resolve_symbol_params(bad_data, "000001.SH", self.fallback)

        self.assertEqual(resolved["step"], self.fallback["step"])
        self.assertEqual(resolved["window_range"], self.fallback["window_range"])
        self.assertEqual(resolved["r2_threshold"], self.fallback["r2_threshold"])
        self.assertGreaterEqual(len(warnings), 3)

    def test_load_optimal_config_reads_yaml(self) -> None:
        if optimal_params.yaml is None:
            self.skipTest("PyYAML 未安装，跳过 YAML 读取测试")

        content = """
version: 1
defaults:
  optimizer: lbfgsb
window_sets:
  a: [40, 50]
symbols:
  "000001.SH":
    step: 120
"""
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, suffix=".yaml") as f:
            f.write(content)
            path = f.name

        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))
        loaded = load_optimal_config(path)

        self.assertIn("defaults", loaded)
        self.assertIn("window_sets", loaded)
        self.assertIn("symbols", loaded)


if __name__ == "__main__":
    unittest.main()
