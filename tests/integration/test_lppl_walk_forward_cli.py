import os
import shutil
import sys
import tempfile
import unittest
from io import StringIO
from unittest.mock import Mock, patch

import pandas as pd

from src.cli.lppl_walk_forward import main


class LPPLWalkForwardCliIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp(prefix="lppl_walk_forward_")
        self.addCleanup(self._cleanup_temp_dir)

    def _cleanup_temp_dir(self) -> None:
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_cli_falls_back_to_default_params_when_optimal_config_load_fails(self) -> None:
        fake_df = pd.DataFrame(
            {
                "date": pd.date_range("2021-01-01", periods=4, freq="D"),
                "close": [100.0, 101.0, 99.0, 98.0],
            }
        )
        fake_data_manager = Mock()
        fake_data_manager.get_data.return_value = fake_df

        records_df = pd.DataFrame(
            {
                "date": pd.date_range("2021-01-01", periods=2, freq="D"),
                "signal_detected": [False, True],
                "event_hit": [False, True],
            }
        )
        summary = {
            "symbol": "000001.SH",
            "mode": "single_window",
            "signal_count": 1,
            "precision": 1.0,
            "recall": 1.0,
            "false_positive_rate": 0.0,
        }

        stdout = StringIO()
        with patch("src.cli.lppl_walk_forward.DataManager", return_value=fake_data_manager), \
             patch("src.cli.lppl_walk_forward.load_optimal_config", side_effect=FileNotFoundError("missing")), \
             patch("src.cli.lppl_walk_forward.run_walk_forward", return_value=(records_df, summary)), \
             patch("sys.stdout", new=stdout):
            argv = [
                "lppl_walk_forward.py",
                "--symbol",
                "000001.SH",
                "--output",
                self.temp_dir,
                "--use-optimal-config",
            ]
            with patch.object(sys, "argv", argv):
                main()

        summary_path = os.path.join(self.temp_dir, "walk_forward_000001_SH_single_window_summary.csv")
        summary_df = pd.read_csv(summary_path)
        self.assertEqual(summary_df.iloc[0]["param_source"], "default_fallback")
        self.assertIn("最优参数文件加载失败，使用默认参数: missing", stdout.getvalue())
        self.assertIn("source=default_fallback", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
