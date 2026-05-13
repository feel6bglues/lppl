# -*- coding: utf-8 -*-
"""
通达信本地数据读取模块

直接读取通达信 .day 二进制文件，不依赖 Wine
"""

import logging
import os
import re
import struct
from pathlib import Path
from typing import Dict, Optional, Tuple

import pandas as pd

logger = logging.getLogger(__name__)

TDX_DAY_RECORD_SIZE = 32
TDX_DAY_FORMAT = "<IIIIIfII"

LPPL_TO_TDX_MAP: Dict[str, Dict[str, str]] = {
    "000001.SH": {"market": "sh", "code": "000001"},
    "399001.SZ": {"market": "sz", "code": "399001"},
    "399006.SZ": {"market": "sz", "code": "399006"},
    "000016.SH": {"market": "sh", "code": "000016"},
    "000300.SH": {"market": "sh", "code": "000300"},
    "000905.SH": {"market": "sh", "code": "000905"},
    "000852.SH": {"market": "sh", "code": "000852"},
}


class TDXReader:
    """通达信本地数据读取器"""

    def __init__(self, tdxdir: str):
        self.tdxdir = Path(tdxdir)
        if not self.tdxdir.exists():
            raise FileNotFoundError(f"TDX directory not found: {tdxdir}")
        logger.info(f"TDXReader initialized with tdxdir: {tdxdir}")

    def _parse_lppl_code(self, lppl_code: str) -> Optional[Tuple[str, str]]:
        """解析 LPPL 代码为通达信 market/code。"""
        if lppl_code in LPPL_TO_TDX_MAP:
            market_info = LPPL_TO_TDX_MAP[lppl_code]
            return market_info["market"], market_info["code"]

        match = re.fullmatch(r"(\d{6})\.(SH|SZ)", lppl_code)
        if not match:
            logger.warning(f"Unsupported LPPL symbol format: {lppl_code}")
            return None

        code, exchange = match.groups()
        market = exchange.lower()
        return market, code

    def _get_file_path(self, lppl_code: str) -> Optional[Path]:
        """根据LPPL代码获取通达信文件路径"""
        parsed = self._parse_lppl_code(lppl_code)
        if parsed is None:
            return None

        market, code = parsed

        file_path = self.tdxdir / market / "lday" / f"{market}{code}.day"

        if not file_path.exists():
            logger.warning(f"Tdx file not found: {file_path}")
            return None

        return file_path

    def daily(self, lppl_code: str) -> Optional[pd.DataFrame]:
        """
        读取日线数据

        Args:
            lppl_code: LPPL格式的指数代码，如 "000001.SH"

        Returns:
            DataFrame with columns: date, open, high, low, close, volume, amount
        """
        file_path = self._get_file_path(lppl_code)
        if file_path is None:
            return None

        try:
            records = []

            with open(file_path, "rb") as f:
                while True:
                    data = f.read(TDX_DAY_RECORD_SIZE)
                    if not data or len(data) < TDX_DAY_RECORD_SIZE:
                        break

                    try:
                        unpacked = struct.unpack(TDX_DAY_FORMAT, data)
                        (
                            date_int,
                            open_price,
                            high_price,
                            low_price,
                            close_price,
                            amount,
                            volume,
                            _,
                        ) = unpacked

                        if date_int < 19900101 or date_int > 21000101:
                            continue

                        date_str = str(date_int)
                        year = int(date_str[:4])
                        month = int(date_str[4:6])
                        day = int(date_str[6:8])

                        # TDX格式：所有品种（指数和个股）价格乘数均为100
                        records.append(
                            {
                                "date": f"{year}-{month:02d}-{day:02d}",
                                "open": open_price / 100.0,
                                "high": high_price / 100.0,
                                "low": low_price / 100.0,
                                "close": close_price / 100.0,
                                "volume": volume,
                                "amount": amount,
                            }
                        )
                    except (struct.error, ValueError) as e:
                        logger.warning(f"Failed to parse record: {e}")
                        continue

            if not records:
                logger.warning(f"No valid records in {file_path}")
                return None

            df = pd.DataFrame(records)
            df["date"] = pd.to_datetime(df["date"])
            df = df.sort_values("date").reset_index(drop=True)

            logger.info(
                f"Read {len(df)} records for {lppl_code}, date range: {df['date'].min().date()} to {df['date'].max().date()}"
            )

            return df

        except Exception as e:
            logger.error(f"Error reading TDX file {file_path}: {e}")
            return None


def get_tdx_reader(tdxdir: Optional[str] = None) -> TDXReader:
    if tdxdir is None:
        tdxdir = os.environ.get("TDX_DATA_PATH",
                     "/home/james/.local/share/tdxcfv/drive_c/tc/vipdoc")
    return TDXReader(tdxdir)
