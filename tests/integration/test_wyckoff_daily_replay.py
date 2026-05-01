import tempfile
import unittest
from pathlib import Path

from scripts.generate_wyckoff_daily_replay import (
    BASELINE_EXPECTATIONS,
    generate_daily_replay,
)


class WyckoffDailyReplayIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        required_files = [
            Path("/home/james/.local/share/tdxcfv/drive_c/tc/vipdoc/sh/lday/sh600859.day"),
            Path("/home/james/.local/share/tdxcfv/drive_c/tc/vipdoc/sz/lday/sz002216.day"),
            Path("/home/james/.local/share/tdxcfv/drive_c/tc/vipdoc/sz/lday/sz300442.day"),
        ]
        if not all(path.exists() for path in required_files):
            raise unittest.SkipTest("missing local TDX stock files for daily replay")

    def test_generate_daily_replay_outputs_reports_and_comparisons(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wyckoff_daily_replay_") as temp_dir:
            output_dir = Path(temp_dir)
            replay_rows, comparison_rows = generate_daily_replay(output_dir)

            self.assertGreater(len(replay_rows), len(comparison_rows))
            self.assertEqual(len(comparison_rows), len(BASELINE_EXPECTATIONS))
            self.assertTrue((output_dir / "daily_replay_summary.csv").exists())
            self.assertTrue((output_dir / "continuity_comparison.csv").exists())
            self.assertTrue((output_dir / "continuity_verification.md").exists())

    def test_generated_reports_meet_minimum_design_completeness(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wyckoff_daily_replay_") as temp_dir:
            replay_rows, _ = generate_daily_replay(Path(temp_dir))
            baseline_rows = [row for row in replay_rows if int(row["is_baseline_day"]) == 1]

            self.assertTrue(baseline_rows)
            min_ratio = min(float(row["design_score_ratio"]) for row in baseline_rows)
            self.assertGreaterEqual(min_ratio, 0.8)


if __name__ == "__main__":
    unittest.main()
