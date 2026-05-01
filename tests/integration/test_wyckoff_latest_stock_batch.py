import tempfile
import unittest
from pathlib import Path

from scripts.analyze_mtf_execution_semantics import build_mtf_execution_report
from scripts.run_wyckoff_latest_stock_batch import (
    analyze_latest_batch,
    analyze_symbol_batch,
    default_worker_count,
    discover_stock_symbols,
    load_symbols_from_csv,
    write_outputs,
)
from scripts.study_wyckoff_batch_gaps import build_gap_study


class WyckoffLatestStockBatchIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        required_dir = Path("/home/james/.local/share/tdxcfv/drive_c/tc/vipdoc")
        if not required_dir.exists():
            raise unittest.SkipTest("missing local TDX directory for batch replay")

    def test_discover_stock_symbols_returns_requested_count(self) -> None:
        symbols = discover_stock_symbols(5)
        self.assertEqual(len(symbols), 5)
        self.assertTrue(all(symbol.endswith((".SH", ".SZ")) for symbol in symbols))

    def test_latest_stock_batch_generates_summary_outputs(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wyckoff_latest_batch_") as temp_dir:
            output_dir = Path(temp_dir)
            rows = analyze_latest_batch(5, output_dir)
            self.assertEqual(len(rows), 5)
            write_outputs(output_dir, rows)
            self.assertTrue((output_dir / "latest_5_stock_summary.csv").exists())
            self.assertTrue((output_dir / "latest_5_stock_summary.md").exists())
            self.assertTrue((output_dir / "latest_5_stock_raw.jsonl").exists())

    def test_load_symbols_from_csv_reads_expected_shape(self) -> None:
        items = load_symbols_from_csv(Path("data/stock_list.csv"))
        self.assertGreater(len(items), 5000)
        self.assertEqual(items[0]["symbol"], "600000.SH")
        self.assertIn(items[0]["supported"], {"0", "1"})

    def test_analyze_symbol_batch_marks_unsupported_prefix(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wyckoff_latest_batch_") as temp_dir:
            output_dir = Path(temp_dir)
            rows = analyze_symbol_batch(
                [
                    {
                        "symbol": "689009.SH",
                        "code": "689009",
                        "market": "SH",
                        "name": "九号公司",
                        "sector": "科创板",
                        "supported": "0",
                    }
                ],
                output_dir,
                workers=2,
            )
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["analysis_status"], "unsupported_prefix")

    def test_default_worker_count_reserves_at_least_one_thread(self) -> None:
        self.assertGreaterEqual(default_worker_count(), 1)

    def test_build_gap_study_writes_expected_outputs(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wyckoff_gap_study_") as temp_dir:
            output_dir = Path(temp_dir)
            stats = build_gap_study(
                batch_summary_csv=Path("output/wyckoff_stock_list_full/latest_5199_stock_summary.csv"),
                continuity_csv=Path("output/wyckoff_daily_replay/continuity_comparison.csv"),
                output_dir=output_dir,
                cohort_size=5,
            )
            self.assertGreater(stats["batch_count"], 5000)
            self.assertTrue((output_dir / "gap_study_report.md").exists())
            self.assertTrue((output_dir / "unknown_cohort.csv").exists())
            self.assertTrue((output_dir / "sample_mismatch_cohort.csv").exists())

    def test_build_mtf_execution_report_writes_expected_outputs(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wyckoff_mtf_semantics_") as temp_dir:
            output_dir = Path(temp_dir)
            stats = build_mtf_execution_report(
                summary_csv=Path("output/wyckoff_stock_list_full_1000d_round2/latest_5199_stock_summary.csv"),
                output_dir=output_dir,
            )
            self.assertGreater(stats["analyzed_count"], 5000)
            self.assertGreater(stats["combo_count"], 1)
            self.assertTrue((output_dir / "mtf_execution_semantics_report.md").exists())
            self.assertTrue((output_dir / "mtf_combo_summary.csv").exists())
            self.assertTrue((output_dir / "mtf_semantic_issue_cohort.csv").exists())


if __name__ == "__main__":
    unittest.main()
