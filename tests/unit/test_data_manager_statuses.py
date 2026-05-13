import unittest
from datetime import datetime
from tempfile import TemporaryDirectory
from unittest.mock import Mock

import pandas as pd

from src.data.manager import (
    DataAvailabilityStatus,
    DataManager,
    summarize_update_results,
    validate_symbol,
)
from src.exceptions import InvalidInputDataError


class DataManagerStatusTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manager = DataManager.__new__(DataManager)
        self.manager.tdx_reader = Mock()
        self.temp_dir = TemporaryDirectory()
        self.manager.data_dir = self.temp_dir.name

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _make_dataframe(self, end_date: str) -> pd.DataFrame:
        rows = 120
        dates = pd.date_range(end=end_date, periods=rows, freq="D")
        values = [100.0 + idx for idx in range(rows)]
        return pd.DataFrame(
            {
                "date": dates,
                "open": values,
                "close": values,
                "high": [v + 1 for v in values],
                "low": [v - 1 for v in values],
                "volume": [1000 for _ in range(rows)],
                "amount": [v * 1000 for v in values],
            }
        )

    def test_summarize_update_results_uses_canonical_statuses(self) -> None:
        results = {
            "000001.SH": DataAvailabilityStatus.AVAILABLE_LOCAL,
            "399001.SZ": DataAvailabilityStatus.STALE,
            "932000.SH": DataAvailabilityStatus.UPDATED_REMOTE,
            "000300.SH": DataAvailabilityStatus.MISSING,
            "000905.SH": DataAvailabilityStatus.FAILED,
        }

        success_count, failed_count = summarize_update_results(results)

        self.assertEqual(success_count, 3)
        self.assertEqual(failed_count, 2)

    def test_normalize_akshare_update_status_maps_success_cases(self) -> None:
        self.assertEqual(
            self.manager._normalize_akshare_update_status("incremental", 12),
            DataAvailabilityStatus.UPDATED_REMOTE,
        )
        self.assertEqual(
            self.manager._normalize_akshare_update_status("full_fetch", 8),
            DataAvailabilityStatus.UPDATED_REMOTE,
        )
        self.assertEqual(
            self.manager._normalize_akshare_update_status("up_to_date", 0),
            DataAvailabilityStatus.AVAILABLE_CACHE,
        )
        self.assertEqual(
            self.manager._normalize_akshare_update_status("no_new_data", 0),
            DataAvailabilityStatus.AVAILABLE_CACHE,
        )

    def test_normalize_akshare_update_status_maps_failures(self) -> None:
        self.assertEqual(
            self.manager._normalize_akshare_update_status("append_failed", 0),
            DataAvailabilityStatus.FAILED,
        )
        self.assertEqual(
            self.manager._normalize_akshare_update_status("error", 0),
            DataAvailabilityStatus.FAILED,
        )
        self.assertEqual(
            self.manager._normalize_akshare_update_status("full_fetch", 0),
            DataAvailabilityStatus.FAILED,
        )

    def test_get_local_index_status_prefers_tdx_data(self) -> None:
        self.manager.tdx_reader.daily.return_value = self._make_dataframe(datetime.now().strftime("%Y-%m-%d"))

        status = self.manager._get_local_index_status("000001.SH")

        self.assertEqual(status, DataAvailabilityStatus.AVAILABLE_LOCAL)

    def test_get_local_index_status_falls_back_to_cache(self) -> None:
        self.manager.tdx_reader.daily.return_value = None
        parquet_df = self._make_dataframe(datetime.now().strftime("%Y-%m-%d"))
        parquet_df.to_parquet(f"{self.temp_dir.name}/000001.SH.parquet", index=False)

        status = self.manager._get_local_index_status("000001.SH")

        self.assertEqual(status, DataAvailabilityStatus.AVAILABLE_CACHE)

    def test_get_local_index_status_marks_missing_when_no_sources_exist(self) -> None:
        self.manager.tdx_reader.daily.return_value = None

        status = self.manager._get_local_index_status("000001.SH")

        self.assertEqual(status, DataAvailabilityStatus.MISSING)

    def test_validate_symbol_accepts_stock_and_index_formats(self) -> None:
        self.assertTrue(validate_symbol("000001.SH"))
        self.assertTrue(validate_symbol("600859.SH"))
        self.assertTrue(validate_symbol("002216.SZ"))
        self.assertTrue(validate_symbol("300442.SZ"))
        self.assertFalse(validate_symbol("600859"))
        self.assertFalse(validate_symbol("ABC859.SH"))

    def test_normalize_symbol_supports_common_inputs(self) -> None:
        self.assertEqual(self.manager.normalize_symbol("600519"), "600519.SH")
        self.assertEqual(self.manager.normalize_symbol("600519.sh"), "600519.SH")
        self.assertEqual(self.manager.normalize_symbol("002216.SZ"), "002216.SZ")
        self.assertEqual(self.manager.normalize_symbol("sz300442"), "300442.SZ")

    def test_classify_asset_type_distinguishes_index_and_stock(self) -> None:
        self.assertEqual(self.manager.classify_asset_type("000300.SH"), "index")
        self.assertEqual(self.manager.classify_asset_type("600519.SH"), "stock")

    def test_read_from_file_loads_csv_and_validates(self) -> None:
        df = self._make_dataframe(datetime.now().strftime("%Y-%m-%d"))
        file_path = f"{self.temp_dir.name}/sample.csv"
        df.to_csv(file_path, index=False)

        result = self.manager.read_from_file(file_path)

        self.assertIsNotNone(result)
        self.assertEqual(len(result), len(df))

    def test_read_from_file_raises_for_invalid_data(self) -> None:
        invalid_df = pd.DataFrame({"date": ["2026-01-01"], "open": [1.0]})
        file_path = f"{self.temp_dir.name}/invalid.csv"
        invalid_df.to_csv(file_path, index=False)

        with self.assertRaises(InvalidInputDataError):
            self.manager.read_from_file(file_path)

    def test_get_wyckoff_data_prefers_file_input(self) -> None:
        df = self._make_dataframe(datetime.now().strftime("%Y-%m-%d"))
        file_path = f"{self.temp_dir.name}/sample.csv"
        df.to_csv(file_path, index=False)

        result_df, asset_type, input_source = self.manager.get_wyckoff_data(input_file=file_path)

        self.assertIsNotNone(result_df)
        self.assertEqual(asset_type, "unknown")
        self.assertEqual(input_source, "file")

    def test_get_data_reads_stock_from_tdx_before_cache(self) -> None:
        stock_df = self._make_dataframe(datetime.now().strftime("%Y-%m-%d"))
        self.manager.tdx_reader.daily.return_value = stock_df

        result = self.manager.get_data("600859.SH")

        self.assertIsNotNone(result)
        self.assertEqual(len(result), len(stock_df))
        self.manager.tdx_reader.daily.assert_called_once_with("600859.SH")


if __name__ == "__main__":
    unittest.main()
