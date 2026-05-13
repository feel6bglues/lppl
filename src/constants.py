# -*- coding: utf-8 -*-
import os
from dataclasses import dataclass
from typing import Dict, List

INDICES: Dict[str, str] = {
    "000001.SH": "上证综指",
    "399001.SZ": "深证成指",
    "399006.SZ": "创业板指",
    "000016.SH": "上证50",
    "000300.SH": "沪深300",
    "000905.SH": "中证500",
    "000852.SH": "中证1000",
    "932000.SH": "中证2000",
}

LEGACY_TO_NEW_SYMBOL_MAP: Dict[str, str] = {
    "sh000001": "000001.SH",
    "sz399001": "399001.SZ",
    "sz399006": "399006.SZ",
    "sh000016": "000016.SH",
    "sh000300": "000300.SH",
    "sh000905": "000905.SH",
    "sh000852": "000852.SH",
    "sh000857": "932000.SH",
    "932000": "932000.SH",
}

LOCAL_DATA_INDICES: List[str] = [
    "000001.SH",
    "399001.SZ",
    "399006.SZ",
    "000016.SH",
    "000300.SH",
    "000905.SH",
    "000852.SH",
    "932000.SH",
]

AKSHARE_INDICES: List[str] = [
    "932000.SH",
]

TDX_DATA_DIR: str = os.environ.get(
    "LPPL_TDX_DATA_DIR", "/home/james/.local/share/tdxcfv/drive_c/tc/vipdoc"
)

REQUIRED_COLUMNS: List[str] = ["date", "open", "close", "high", "low", "volume"]

MIN_DATA_ROWS: int = 100

MAX_DATA_AGE_DAYS: int = 7


@dataclass(frozen=True)
class WindowConfig:
    short_windows: List[int]
    medium_windows: List[int]
    long_windows: List[int]

    @property
    def all_windows(self) -> List[int]:
        return self.short_windows + self.medium_windows + self.long_windows

    def get_category(self, window: int) -> str:
        if window < 200:
            return "short"
        elif 200 <= window <= 500:
            return "medium"
        else:
            return "long"


WINDOW_CONFIG = WindowConfig(
    short_windows=list(range(50, 300, 10)),
    medium_windows=list(range(300, 600, 20)),
    long_windows=list(range(600, 1200, 50)),
)

DEFAULT_DATA_DIR: str = os.environ.get(
    "LPPL_DATA_DIR", os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
)

OUTPUT_DIR: str = "output"
VERIFY_OUTPUT_DIR: str = os.environ.get("LPPL_VERIFY_OUTPUT_DIR", os.path.join(OUTPUT_DIR, "MA"))
PLOTS_OUTPUT_DIR: str = os.environ.get("LPPL_PLOTS_DIR", os.path.join(VERIFY_OUTPUT_DIR, "plots"))
REPORTS_OUTPUT_DIR: str = os.environ.get(
    "LPPL_REPORTS_DIR", os.path.join(VERIFY_OUTPUT_DIR, "reports")
)
SUMMARY_OUTPUT_DIR: str = os.environ.get(
    "LPPL_SUMMARY_DIR", os.path.join(VERIFY_OUTPUT_DIR, "summary")
)
RAW_OUTPUT_DIR: str = os.environ.get("LPPL_RAW_DIR", os.path.join(VERIFY_OUTPUT_DIR, "raw"))

DATA_COLUMNS: Dict[str, str] = {
    "日期": "date",
    "开盘": "open",
    "收盘": "close",
    "最高": "high",
    "最低": "low",
    "成交量": "volume",
    "成交额": "amount",
    "振幅": "amplitude",
    "涨跌幅": "pct_change",
    "涨跌额": "change",
    "换手率": "turnover",
}

ENABLE_NUMBA_JIT: bool = True
ENABLE_JOBLIB_PARALLEL: bool = True
ENABLE_INCREMENTAL_UPDATE: bool = True
ENABLE_NEGATIVE_BUBBLE: bool = True

WYCKOFF_PHASES: List[str] = [
    "accumulation",
    "markup",
    "distribution",
    "markdown",
]

WYCKOFF_DIRECTIONS: List[str] = [
    "bullish",
    "bearish",
    "neutral",
]

WYCKOFF_CONFIDENCE_LEVELS: List[str] = [
    "very_high",
    "high",
    "medium",
    "low",
    "very_low",
]

VOLUME_LABELS: List[str] = [
    "very_low",
    "low",
    "normal",
    "high",
    "very_high",
    "climax",
]

IMAGE_QUALITY_LEVELS: List[str] = [
    "low",
    "medium",
    "high",
    "ultra",
]

VISUAL_TRENDS: List[str] = [
    "strong_uptrend",
    "weak_uptrend",
    "sideways",
    "weak_downtrend",
    "strong_downtrend",
]

TIMEFRAME_HINTS: List[str] = [
    "intraday",
    "short_term",
    "medium_term",
    "long_term",
    "multi_year",
]

VISUAL_ANOMALIES: List[str] = [
    "gap_up",
    "gap_down",
    "spike_high",
    "spike_low",
    "doji",
    "engulfing",
    "divergence",
]

WYCKOFF_OUTPUT_DIR: str = os.environ.get(
    "LPPL_WYCKOFF_OUTPUT_DIR",
    os.path.join(OUTPUT_DIR, "wyckoff"),
)

MIN_WYCKOFF_DATA_ROWS: int = 200
BC_LOOKBACK_WINDOW: int = 20
SPRING_FREEZE_DAYS: int = 3
MIN_RR_RATIO: float = 2.5
