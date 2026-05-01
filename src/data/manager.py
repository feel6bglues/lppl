# -*- coding: utf-8 -*-
import logging
import os
import re
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

import pandas as pd

from src.constants import (
    AKSHARE_INDICES,
    DATA_COLUMNS,
    DEFAULT_DATA_DIR,
    ENABLE_INCREMENTAL_UPDATE,
    INDICES,
    LOCAL_DATA_INDICES,
    MAX_DATA_AGE_DAYS,
    MIN_DATA_ROWS,
    REQUIRED_COLUMNS,
    TDX_DATA_DIR,
)
from src.exceptions import DataFetchError, DataValidationError

logger = logging.getLogger(__name__)

try:
    import akshare as ak
    AKSHARE_AVAILABLE = True
    logger.info(f"akshare version: {ak.__version__}")
except ImportError:
    AKSHARE_AVAILABLE = False
    logger.warning("akshare not available, some indices may not be accessible")


class DataAvailabilityStatus:
    AVAILABLE_LOCAL = "available_local"
    AVAILABLE_CACHE = "available_cache"
    UPDATED_REMOTE = "updated_remote"
    STALE = "stale"
    MISSING = "missing"
    FAILED = "failed"


AVAILABLE_DATA_STATUSES = {
    DataAvailabilityStatus.AVAILABLE_LOCAL,
    DataAvailabilityStatus.AVAILABLE_CACHE,
    DataAvailabilityStatus.UPDATED_REMOTE,
    DataAvailabilityStatus.STALE,
}

FAILED_DATA_STATUSES = {
    DataAvailabilityStatus.MISSING,
    DataAvailabilityStatus.FAILED,
}


def summarize_update_results(results: Dict[str, str]) -> Tuple[int, int]:
    success_count = sum(1 for status in results.values() if status in AVAILABLE_DATA_STATUSES)
    failed_count = sum(1 for status in results.values() if status in FAILED_DATA_STATUSES)
    return success_count, failed_count


def validate_dataframe(df: pd.DataFrame, symbol: str) -> Tuple[bool, str]:
    if df is None or df.empty:
        return False, "DataFrame is None or empty"

    missing_cols = [col for col in REQUIRED_COLUMNS if col not in df.columns]
    if missing_cols:
        return False, f"Missing required columns: {missing_cols}"

    if len(df) < MIN_DATA_ROWS:
        return False, f"Insufficient data rows: {len(df)} < {MIN_DATA_ROWS}"

    null_counts = df[REQUIRED_COLUMNS].isnull().sum()
    if null_counts.any():
        return False, f"Null values found in columns: {null_counts[null_counts > 0].to_dict()}"

    bad_high_low = (df["high"] < df["low"]).sum()
    if bad_high_low > len(df) * 0.01:
        return False, f"Too many high < low: {bad_high_low} rows ({bad_high_low/len(df)*100:.1f}%)"

    if (df["close"] <= 0).any() or (df["open"] <= 0).any():
        return False, "Invalid data: non-positive prices found"

    if (df["volume"] < 0).any():
        return False, "Invalid data: negative volume found"

    dates = pd.to_datetime(df["date"], errors="coerce")
    if dates.isnull().any():
        return False, "Invalid date format found"

    return True, "Validation passed"


def validate_symbol(symbol: str) -> bool:
    if not symbol or not isinstance(symbol, str):
        return False
    if symbol in INDICES:
        return True
    return re.fullmatch(r"\d{6}\.(SH|SZ)", symbol) is not None


class DataManager:
    def __init__(self, data_dir: Optional[str] = None):
        self.data_dir = data_dir or DEFAULT_DATA_DIR
        if not os.path.exists(self.data_dir):
            logger.error(f"Data directory not found: {self.data_dir}")
            raise FileNotFoundError(f"Data directory not found: {self.data_dir}")
        logger.info(f"DataManager initialized with data_dir: {self.data_dir}")

        from src.data.tdx_reader import TDXReader
        self.tdx_reader = TDXReader(TDX_DATA_DIR)
        logger.info(f"TDX Reader initialized with tdxdir: {TDX_DATA_DIR}")

    def _get_file_path(self, symbol: str) -> str:
        if not validate_symbol(symbol):
            raise ValueError(f"Invalid symbol: {symbol}")
        return os.path.join(self.data_dir, f"{symbol}.parquet")

    def _is_akshare_index(self, symbol: str) -> bool:
        return symbol in AKSHARE_INDICES

    def _classify_cached_dataframe(self, df: pd.DataFrame, symbol: str) -> str:
        is_valid, msg = validate_dataframe(df, symbol)
        if not is_valid:
            logger.error(f"Cached data validation failed for {symbol}: {msg}")
            return DataAvailabilityStatus.FAILED

        last_date = pd.to_datetime(df["date"]).max()
        days_diff = (datetime.now().date() - last_date.date()).days
        if days_diff > MAX_DATA_AGE_DAYS:
            return DataAvailabilityStatus.STALE
        return DataAvailabilityStatus.AVAILABLE_CACHE

    def _get_local_index_status(self, symbol: str) -> str:
        try:
            tdx_df = self.tdx_reader.daily(symbol)
            if tdx_df is not None and not tdx_df.empty:
                is_valid, msg = validate_dataframe(tdx_df, symbol)
                if is_valid:
                    return DataAvailabilityStatus.AVAILABLE_LOCAL
                logger.warning(f"TDX data validation failed for {symbol}: {msg}")
        except Exception as e:
            logger.error(f"Error checking TDX data for {symbol}: {e}")

        file_path = self._get_file_path(symbol)
        if not os.path.exists(file_path):
            return DataAvailabilityStatus.MISSING

        try:
            parquet_df = pd.read_parquet(file_path)
            parquet_df["date"] = pd.to_datetime(parquet_df["date"])
            parquet_df = parquet_df.sort_values("date").reset_index(drop=True)
            return self._classify_cached_dataframe(parquet_df, symbol)
        except Exception as e:
            logger.error(f"Error checking cached parquet for {symbol}: {e}")
            return DataAvailabilityStatus.FAILED

    def _normalize_akshare_update_status(self, status: str, rows: int = 0) -> str:
        if status in {"incremental", "full_fetch"} and rows > 0:
            return DataAvailabilityStatus.UPDATED_REMOTE
        if status in {"up_to_date", "no_new_data"}:
            return DataAvailabilityStatus.AVAILABLE_CACHE
        if status in {"not_found"}:
            return DataAvailabilityStatus.MISSING
        return DataAvailabilityStatus.FAILED

    def _fetch_akshare_data(self, symbol: str) -> Optional[pd.DataFrame]:
        if not AKSHARE_AVAILABLE:
            logger.error(f"akshare is not available for {symbol}")
            raise DataFetchError("akshare library is not available")

        if not validate_symbol(symbol):
            raise ValueError(f"Invalid symbol: {symbol}")

        try:
            pure_symbol = symbol.replace(".SH", "").replace(".SZ", "")

            logger.info(f"Fetching data for {symbol} using akshare (code: {pure_symbol})")

            if symbol == "932000.SH":
                start_date = "20100101"
                end_date = datetime.now().strftime("%Y%m%d")

                logger.info(f"Using stock_zh_index_hist_csindex for {symbol}")
                df = ak.stock_zh_index_hist_csindex(
                    symbol=pure_symbol,
                    start_date=start_date,
                    end_date=end_date
                )

                if df is None or df.empty:
                    logger.warning(f"No data returned from akshare for {symbol}")
                    return None

                df = df.rename(columns=DATA_COLUMNS)
                df = df.dropna(subset=["open", "high", "low", "close", "volume"])
            else:
                df = ak.index_zh_a_hist(
                    symbol=pure_symbol,
                    period="daily",
                    start_date="20100101",
                    end_date=datetime.now().strftime("%Y%m%d")
                )

                if df is None or df.empty:
                    logger.warning(f"No data returned from akshare for {symbol}")
                    return None

                df = df.rename(columns=DATA_COLUMNS)

            df["date"] = pd.to_datetime(df["date"])
            df = df.sort_values("date").reset_index(drop=True)

            is_valid, msg = validate_dataframe(df, symbol)
            if not is_valid:
                logger.error(f"Data validation failed for {symbol}: {msg}")
                return None

            self._save_data(symbol, df)

            logger.info(f"Successfully fetched data for {symbol} (rows: {len(df)}, last date: {df['date'].iloc[-1].date()})")
            return df
        except ValueError as e:
            logger.error(f"Value error fetching akshare data for {symbol}: {e}")
            raise
        except KeyError as e:
            logger.error(f"Key error fetching akshare data for {symbol}: {e}")
            raise DataFetchError(f"API response missing expected data: {e}")
        except ConnectionError as e:
            logger.error(f"Connection error fetching akshare data for {symbol}: {e}")
            raise DataFetchError(f"Network connection failed: {e}")
        except Exception as e:
            logger.error(f"Error fetching akshare data for {symbol}: {type(e).__name__}: {e}")
            return None

    def _save_data(self, symbol: str, df: pd.DataFrame) -> None:
        if not validate_symbol(symbol):
            raise ValueError(f"Invalid symbol: {symbol}")

        is_valid, msg = validate_dataframe(df, symbol)
        if not is_valid:
            raise DataValidationError(f"Invalid data before saving: {msg}")

        try:
            file_path = self._get_file_path(symbol)
            df.to_parquet(file_path, index=False)
            logger.info(f"Data saved to {file_path}")
        except PermissionError as e:
            logger.error(f"Permission denied saving data for {symbol}: {e}")
            raise
        except OSError as e:
            logger.error(f"OS error saving data for {symbol}: {e}")
            raise

    def _get_last_date_from_file(self, symbol: str) -> Optional[datetime]:
        if not validate_symbol(symbol):
            raise ValueError(f"Invalid symbol: {symbol}")

        file_path = self._get_file_path(symbol)

        if not os.path.exists(file_path):
            return None

        try:
            df = pd.read_parquet(file_path)
            if df.empty:
                return None
            df["date"] = pd.to_datetime(df["date"])
            return df["date"].max()
        except Exception as e:
            logger.error(f"Error reading last date for {symbol}: {e}")
            return None

    def _append_data_to_file(self, symbol: str, new_data: pd.DataFrame) -> bool:
        if not validate_symbol(symbol):
            raise ValueError(f"Invalid symbol: {symbol}")

        if new_data is None or new_data.empty:
            logger.warning(f"No new data to append for {symbol}")
            return False

        file_path = self._get_file_path(symbol)

        try:
            if os.path.exists(file_path):
                existing_df = pd.read_parquet(file_path)
                existing_df["date"] = pd.to_datetime(existing_df["date"])
                new_data["date"] = pd.to_datetime(new_data["date"])

                combined_df = pd.concat([existing_df, new_data], ignore_index=True)
                combined_df = combined_df.drop_duplicates(subset=["date"], keep="last")
                combined_df = combined_df.sort_values("date").reset_index(drop=True)
            else:
                new_data["date"] = pd.to_datetime(new_data["date"])
                combined_df = new_data.sort_values("date").reset_index(drop=True)

            is_valid, msg = validate_dataframe(combined_df, symbol)
            if not is_valid:
                logger.error(f"Combined data validation failed for {symbol}: {msg}")
                return False

            combined_df.to_parquet(file_path, index=False)
            logger.info(f"Data appended for {symbol}, total rows: {len(combined_df)}")
            return True
        except Exception as e:
            logger.error(f"Error appending data for {symbol}: {e}")
            return False

    def incremental_update_data(self, symbol: str) -> Tuple[str, int]:
        if not validate_symbol(symbol):
            raise ValueError(f"Invalid symbol: {symbol}")

        if not ENABLE_INCREMENTAL_UPDATE:
            logger.info(f"Incremental update disabled, fetching full data for {symbol}")
            df = self._fetch_akshare_data(symbol) if self._is_akshare_index(symbol) else None
            return ("full_fetch", len(df) if df is not None else 0)

        last_date = self._get_last_date_from_file(symbol)
        today = datetime.now().date()

        if last_date is None:
            logger.info(f"No existing data for {symbol}, performing full fetch")
            df = self._fetch_akshare_data(symbol) if self._is_akshare_index(symbol) else None
            return ("full_fetch", len(df) if df is not None else 0)

        days_diff = (today - last_date.date()).days

        if days_diff <= 0:
            logger.info(f"Data for {symbol} is already up-to-date (last date: {last_date.date()})")
            return ("up_to_date", 0)

        logger.info(f"Incremental update for {symbol}: {days_diff} days to fetch (from {last_date.date()} to {today})")

        if not self._is_akshare_index(symbol):
            logger.warning(f"Incremental update not supported for local data index {symbol}")
            return ("not_supported", 0)

        try:
            pure_symbol = symbol.replace(".SH", "").replace(".SZ", "")
            start_date = (last_date + pd.Timedelta(days=1)).strftime("%Y%m%d")
            end_date = today.strftime("%Y%m%d")

            if symbol == "932000.SH":
                new_df = ak.stock_zh_index_hist_csindex(
                    symbol=pure_symbol,
                    start_date=start_date,
                    end_date=end_date
                )
                if new_df is not None and not new_df.empty:
                    new_df = new_df.rename(columns=DATA_COLUMNS)
                    new_df = new_df.dropna(subset=["open", "high", "low", "close", "volume"])
                    if new_df.empty:
                        new_df = None
            else:
                new_df = ak.index_zh_a_hist(
                    symbol=pure_symbol,
                    period="daily",
                    start_date=start_date,
                    end_date=end_date
                )
                new_df = new_df.rename(columns=DATA_COLUMNS)

            if new_df is None or new_df.empty:
                logger.info(f"No new data available for {symbol} from {start_date} to {end_date}")
                return ("no_new_data", 0)

            new_df["date"] = pd.to_datetime(new_df["date"])

            rows_added = len(new_df)

            if self._append_data_to_file(symbol, new_df):
                logger.info(f"Incremental update successful for {symbol}: {rows_added} rows added")
                return ("incremental", rows_added)
            else:
                logger.warning(f"Failed to append incremental data for {symbol}")
                return ("append_failed", 0)

        except Exception as e:
            logger.error(f"Error during incremental update for {symbol}: {e}")
            return ("error", 0)

    def check_data_timeliness(self, symbol: str) -> Tuple[bool, Optional[datetime], Optional[str]]:
        if not validate_symbol(symbol):
            raise ValueError(f"Invalid symbol: {symbol}")

        if self._is_akshare_index(symbol):
            try:
                df = self._fetch_akshare_data(symbol)
                if df is not None and not df.empty:
                    last_date = df["date"].max()
                    today = datetime.now().date()
                    days_diff = (today - last_date.date()).days
                    if days_diff >= 1:
                        return False, last_date, None
                    else:
                        return True, last_date, None
                return False, None, None
            except DataFetchError as e:
                logger.error(f"Failed to fetch data for timeliness check: {e}")
                return False, None, None

        file_path = self._get_file_path(symbol)

        if not os.path.exists(file_path):
            return False, None, file_path

        try:
            df = pd.read_parquet(file_path)
            df["date"] = pd.to_datetime(df["date"])
            last_date = df["date"].max()

            today = datetime.now().date()
            days_diff = (today - last_date.date()).days

            if days_diff >= 1:
                return False, last_date, file_path
            else:
                return True, last_date, file_path
        except ValueError as e:
            logger.error(f"Data format error checking timeliness for {symbol}: {e}")
            return False, None, file_path
        except KeyError as e:
            logger.error(f"Missing column checking timeliness for {symbol}: {e}")
            return False, None, file_path
        except Exception as e:
            logger.error(f"Error checking data timeliness for {symbol}: {type(e).__name__}: {e}")
            return False, None, file_path

    def get_data(self, symbol: str) -> Optional[pd.DataFrame]:
        if not validate_symbol(symbol):
            logger.error(f"Invalid symbol requested: {symbol}")
            return None

        if symbol in LOCAL_DATA_INDICES:
            return self._read_from_tdx(symbol)

        # 个股优先从本地通达信读取，失败后再回退到缓存 parquet
        tdx_df = self._read_from_tdx(symbol)
        if tdx_df is not None and not tdx_df.empty:
            return tdx_df

        if self._is_akshare_index(symbol):
            file_path = self._get_file_path(symbol)
            if os.path.exists(file_path):
                try:
                    df = pd.read_parquet(file_path)
                    df["date"] = pd.to_datetime(df["date"])
                    df = df.sort_values("date").reset_index(drop=True)

                    is_valid, msg = validate_dataframe(df, symbol)
                    if is_valid:
                        return df
                    else:
                        logger.warning(f"Cached data validation failed for {symbol}: {msg}, will refetch")
                except ValueError as e:
                    logger.error(f"Data format error reading local data for {symbol}: {e}")
                except KeyError as e:
                    logger.error(f"Missing column reading local data for {symbol}: {e}")
                except Exception as e:
                    logger.error(f"Error reading local data for {symbol}: {type(e).__name__}: {e}")

            return self._fetch_akshare_data(symbol)

        file_path = self._get_file_path(symbol)

        if not os.path.exists(file_path):
            logger.warning(f"No data found for {symbol}")
            return None

        try:
            df = pd.read_parquet(file_path)
            df["date"] = pd.to_datetime(df["date"])
            df = df.sort_values("date").reset_index(drop=True)

            is_valid, msg = validate_dataframe(df, symbol)
            if not is_valid:
                logger.error(f"Data validation failed for {symbol}: {msg}")
                return None

            return df
        except ValueError as e:
            logger.error(f"Data format error reading data for {e}")
            return None
        except KeyError as e:
            logger.error(f"Missing column reading data for {e}")
            return None
        except Exception as e:
            logger.error(f"Error reading data for {type(e).__name__}: {e}")
            return None

    def _read_from_tdx(self, symbol: str) -> Optional[pd.DataFrame]:
        """从通达信本地读取数据"""
        try:
            df = self.tdx_reader.daily(symbol)
            if df is None or df.empty:
                logger.warning(f"No data from TDX for {symbol}")
                return self._read_from_parquet(symbol)

            is_valid, msg = validate_dataframe(df, symbol)
            if is_valid:
                return df
            else:
                logger.warning(f"TDX data validation failed for {symbol}: {msg}")
                return self._read_from_parquet(symbol)

        except Exception as e:
            logger.error(f"Error reading from TDX for {symbol}: {e}")
            return self._read_from_parquet(symbol)

    def _read_from_parquet(self, symbol: str) -> Optional[pd.DataFrame]:
        """从本地parquet缓存读取数据"""
        file_path = self._get_file_path(symbol)

        if not os.path.exists(file_path):
            logger.warning(f"No parquet file found for {symbol}")
            return None

        try:
            df = pd.read_parquet(file_path)
            df["date"] = pd.to_datetime(df["date"])
            df = df.sort_values("date").reset_index(drop=True)

            is_valid, msg = validate_dataframe(df, symbol)
            if is_valid:
                return df
            else:
                logger.error(f"Parquet data validation failed for {symbol}: {msg}")
                return None

        except Exception as e:
            logger.error(f"Error reading parquet for {symbol}: {e}")
            return None

    def update_all_data(self) -> Dict[str, str]:
        results = {}

        for symbol, name in INDICES.items():
            logger.info(f"\nProcessing {name} ({symbol})...")

            if self._is_akshare_index(symbol):
                if ENABLE_INCREMENTAL_UPDATE:
                    try:
                        status, rows = self.incremental_update_data(symbol)
                        normalized_status = self._normalize_akshare_update_status(status, rows)
                        results[symbol] = normalized_status
                        if normalized_status == DataAvailabilityStatus.UPDATED_REMOTE:
                            logger.info(f"Data for {symbol} incrementally updated ({rows} rows added)")
                        elif normalized_status == DataAvailabilityStatus.AVAILABLE_CACHE:
                            logger.info(f"Data for {symbol} is already up-to-date")
                        elif status == "full_fetch" and rows > 0:
                            logger.info(f"Data for {symbol} fetched fully ({rows} rows)")
                        elif normalized_status == DataAvailabilityStatus.FAILED:
                            logger.warning(f"Data update for {symbol} failed with status: {status}")
                        else:
                            logger.warning(f"Data update for {symbol} returned status: {status}")
                    except Exception as e:
                        logger.error(f"Incremental update failed for {symbol}: {e}")
                        results[symbol] = DataAvailabilityStatus.FAILED
                else:
                    try:
                        df = self._fetch_akshare_data(symbol)
                        if df is not None and not df.empty:
                            last_date = df["date"].max()
                            logger.info(f"Data for {symbol} fetched from akshare (last date: {last_date.date()})")
                            results[symbol] = DataAvailabilityStatus.UPDATED_REMOTE
                        else:
                            logger.warning(f"Failed to fetch data from akshare for {symbol}")
                            results[symbol] = DataAvailabilityStatus.FAILED
                    except DataFetchError as e:
                        logger.error(f"Data fetch failed for {symbol}: {e}")
                        results[symbol] = DataAvailabilityStatus.FAILED
                continue

            try:
                status = self._get_local_index_status(symbol)
                results[symbol] = status
                if status == DataAvailabilityStatus.AVAILABLE_LOCAL:
                    logger.info(f"Data for {symbol} is available from local TDX source")
                elif status == DataAvailabilityStatus.AVAILABLE_CACHE:
                    logger.info(f"Data for {symbol} is available from parquet cache")
                elif status == DataAvailabilityStatus.STALE:
                    logger.info(f"Data for {symbol} is only available from stale parquet cache")
                elif status == DataAvailabilityStatus.MISSING:
                    logger.warning(f"No local or cached data found for {symbol}")
                else:
                    logger.error(f"Failed to determine local data status for {symbol}")
            except Exception as e:
                logger.error(f"Error processing {symbol}: {type(e).__name__}: {e}")
                results[symbol] = DataAvailabilityStatus.FAILED

        return results

    def get_all_indices_data(self) -> Dict[str, Dict[str, Any]]:
        all_data = {}
        for symbol, name in INDICES.items():
            df = self.get_data(symbol)
            if df is not None and not df.empty:
                is_valid, msg = validate_dataframe(df, symbol)
                if is_valid:
                    all_data[symbol] = {
                        "name": name,
                        "data": df
                    }
                else:
                    logger.warning(f"Skipping {symbol} due to validation failure: {msg}")
            else:
                logger.warning(f"No valid data retrieved for {symbol}")
        return all_data
