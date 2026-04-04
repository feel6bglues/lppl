# -*- coding: utf-8 -*-
import tempfile
import unittest
from pathlib import Path

from src.cli.generate_optimal8_report import _resolve_summary_csv


class GenerateOptimal8ReportTests(unittest.TestCase):
    def test_resolve_summary_csv_returns_existing_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            summary_path = Path(temp_dir) / "summary.csv"
            summary_path.write_text("symbol,objective_score\n000001.SH,0.1\n", encoding="utf-8")

            resolved = _resolve_summary_csv(str(summary_path))

            self.assertEqual(resolved, summary_path)

    def test_resolve_summary_csv_finds_latest_matching_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            summary_dir = Path(temp_dir)
            older = summary_dir / "walk_forward_optimal_8index_summary_20260301_010101.csv"
            newer = summary_dir / "walk_forward_optimal_8index_summary_20260302_010101.csv"
            older.write_text("symbol,objective_score\n000001.SH,0.1\n", encoding="utf-8")
            newer.write_text("symbol,objective_score\n000300.SH,0.2\n", encoding="utf-8")

            resolved = _resolve_summary_csv(str(summary_dir / "latest_walk_forward_optimal_8index_summary.csv"))

            self.assertEqual(resolved, newer)


if __name__ == "__main__":
    unittest.main()
