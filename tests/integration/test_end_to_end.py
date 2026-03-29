# -*- coding: utf-8 -*-
"""
集成测试 - 端到端验证完整链路

测试目标:
- 跑一个单指数 + 单 peak 的最小验证链路
- 校验 CSV / PNG / MD / HTML 是否都被生成
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from lppl_verify_v2 import generate_verification_artifacts, run_verification


class IntegrationTests(unittest.TestCase):
    """端到端集成测试"""

    @classmethod
    def setUpClass(cls):
        fixture_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "fixtures",
            "integration_verification_results.json",
        )
        with open(fixture_path, "r", encoding="utf-8") as f:
            cls.fixture_results = json.load(f)

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="lppl_integration_")
        self.addCleanup(self._cleanup_temp_dir)

    def _cleanup_temp_dir(self):
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _make_price_df(self) -> pd.DataFrame:
        dates = pd.date_range("2015-01-01", periods=220, freq="D")
        closes = [3000.0 + idx * 10 for idx in range(220)]
        return pd.DataFrame({"date": dates, "close": closes})

    def _load_results_fixture(self, mode: str):
        return json.loads(json.dumps(self.fixture_results[mode]))

    def test_single_index_verification_single_window_mode(self):
        """测试单指数 + 单 peak 的单窗口验证链路"""
        symbol = "000001.SH"
        name = "上证综指"
        fake_df = self._make_price_df()
        fake_data_manager = Mock()
        fake_data_manager.get_data.return_value = fake_df
        peak = {"idx": 180, "date": fake_df.iloc[180]["date"], "price": 4800.0, "drop_pct": 0.18}
        analyze_result = self._load_results_fixture("single_window")[0]

        with patch("src.data.manager.DataManager", return_value=fake_data_manager), \
             patch("lppl_verify_v2.find_local_highs", return_value=[peak]), \
             patch("lppl_verify_v2.analyze_peak", return_value=analyze_result) as analyze_mock:
            results = run_verification(
                symbol=symbol,
                name=name,
                use_ensemble=False,
                scan_step=5,
                ma_window=5,
                max_peaks=1,
            )

        self.assertEqual(len(results), 1, f"应返回单个 peak 结果，实际: {len(results)}")
        self.assertEqual(analyze_mock.call_count, 1)

        result = results[0]
        self.assertIn("symbol", result)
        self.assertIn("peak_date", result)
        self.assertIn("detected", result)
        self.assertEqual(result["symbol"], symbol)
        self.assertEqual(result["drop_pct"], peak["drop_pct"])
        self.assertEqual(result["mode"], "single_window")

    def test_single_index_verification_ensemble_mode(self):
        """测试单指数 + 单 peak 的 Ensemble 验证链路"""
        symbol = "000001.SH"
        name = "上证综指"
        fake_df = self._make_price_df()
        fake_data_manager = Mock()
        fake_data_manager.get_data.return_value = fake_df
        peak = {"idx": 180, "date": fake_df.iloc[180]["date"], "price": 4800.0, "drop_pct": 0.18}
        analyze_result = self._load_results_fixture("ensemble")[0]

        with patch("src.data.manager.DataManager", return_value=fake_data_manager), \
             patch("lppl_verify_v2.find_local_highs", return_value=[peak]), \
             patch("lppl_verify_v2.analyze_peak_ensemble", return_value=analyze_result) as analyze_mock:
            results = run_verification(
                symbol=symbol,
                name=name,
                use_ensemble=True,
                scan_step=5,
                ma_window=5,
                max_peaks=1,
            )

        self.assertEqual(len(results), 1, f"应返回单个 peak 结果，实际: {len(results)}")
        self.assertEqual(analyze_mock.call_count, 1)

        result = results[0]
        self.assertIn("symbol", result)
        self.assertIn("peak_date", result)
        self.assertIn("detected", result)
        self.assertEqual(result["symbol"], symbol)
        self.assertEqual(result["drop_pct"], peak["drop_pct"])
        self.assertEqual(result["mode"], "ensemble")

    def test_artifacts_generation_single_window(self):
        """测试单窗口模式下所有工件生成"""
        results = self._load_results_fixture("single_window")

        artifacts = generate_verification_artifacts(
            all_results=results,
            output_dir=self.temp_dir,
            use_ensemble=False,
        )

        self.assertIsNotNone(artifacts, "应该生成工件")

        output_dirs = artifacts["output_dirs"]
        raw_dir = output_dirs["raw"]
        plots_dir = output_dirs["plots"]
        reports_dir = output_dirs["reports"]
        summary_dir = output_dirs["summary"]

        self.assertTrue(os.path.isdir(raw_dir), f"raw 目录应存在: {raw_dir}")
        self.assertTrue(os.path.isdir(plots_dir), f"plots 目录应存在: {plots_dir}")
        self.assertTrue(os.path.isdir(reports_dir), f"reports 目录应存在: {reports_dir}")
        self.assertTrue(os.path.isdir(summary_dir), f"summary 目录应存在: {summary_dir}")

        raw_files = [f for f in os.listdir(raw_dir) if f.endswith(".parquet")]
        plot_files = [f for f in os.listdir(plots_dir) if f.endswith(".png")]
        csv_files = [f for f in os.listdir(summary_dir) if f.endswith(".csv")]

        self.assertGreaterEqual(len(raw_files), 1, "应至少生成一个 raw parquet 文件")
        self.assertGreaterEqual(len(plot_files), 2, "应至少生成时间线图和汇总图")
        self.assertGreaterEqual(len(csv_files), 1, "应至少生成一个汇总 CSV")
        self.assertTrue(os.path.isfile(artifacts["markdown_path"]))
        self.assertTrue(os.path.isfile(artifacts["html_path"]))

    def test_artifacts_generation_ensemble(self):
        """测试 Ensemble 模式下所有工件生成"""
        results = self._load_results_fixture("ensemble")

        artifacts = generate_verification_artifacts(
            all_results=results,
            output_dir=self.temp_dir,
            use_ensemble=True,
        )

        self.assertIsNotNone(artifacts, "应该生成工件")

        plots_dir = artifacts["output_dirs"]["plots"]
        plot_files = [f for f in os.listdir(plots_dir) if f.endswith(".png")]
        self.assertGreaterEqual(len(plot_files), 4, "Ensemble 应生成时间线、共识、离散和汇总图")
        self.assertTrue(os.path.isfile(artifacts["markdown_path"]))
        self.assertTrue(os.path.isfile(artifacts["html_path"]))

    def test_summary_csv_has_required_columns(self):
        """测试汇总 CSV 包含必需字段"""
        results = self._load_results_fixture("single_window")

        artifacts = generate_verification_artifacts(
            all_results=results,
            output_dir=self.temp_dir,
            use_ensemble=False,
        )

        summary_df = artifacts["summary_df"]
        required_columns = [
            "symbol",
            "name",
            "peak_date",
            "peak_price",
            "detected",
            "first_danger_days",
            "first_danger_r2",
        ]

        for col in required_columns:
            self.assertIn(col, summary_df.columns, f"汇总 CSV 应包含字段: {col}")

    def test_html_report_contains_image_references(self):
        """测试 HTML 报告包含图片引用"""
        results = self._load_results_fixture("single_window")

        artifacts = generate_verification_artifacts(
            all_results=results,
            output_dir=self.temp_dir,
            use_ensemble=False,
        )

        with open(artifacts["html_path"], "r", encoding="utf-8") as f:
            html_content = f.read()

        self.assertTrue("<img" in html_content or "src=" in html_content, "HTML 报告应包含图片引用")

    def test_raw_parquet_contains_timeline_data(self):
        """测试 raw parquet 文件包含 timeline 数据"""
        results = self._load_results_fixture("single_window")

        artifacts = generate_verification_artifacts(
            all_results=results,
            output_dir=self.temp_dir,
            use_ensemble=False,
        )

        raw_dir = artifacts["output_dirs"]["raw"]
        raw_files = [f for f in os.listdir(raw_dir) if f.endswith(".parquet")]
        self.assertGreaterEqual(len(raw_files), 1, "至少应生成一个 raw parquet 文件")

        raw_path = os.path.join(raw_dir, raw_files[0])
        raw_df = pd.read_parquet(raw_path)

        expected_columns = ["idx", "date", "price", "days_to_peak"]
        for col in expected_columns:
            self.assertIn(col, raw_df.columns, f"timeline 应包含字段: {col}")


if __name__ == "__main__":
    unittest.main()
