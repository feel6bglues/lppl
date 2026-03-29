import unittest
from datetime import datetime
from tempfile import TemporaryDirectory
from unittest.mock import Mock

import pandas as pd

from src.data.manager import DataAvailabilityStatus, DataManager, summarize_update_results


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


if __name__ == "__main__":
    unittest.main()
