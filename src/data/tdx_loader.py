# -*- coding: utf-8 -*-
"""
统一通达信数据加载器
====================
集中管理TDX .day文件解析，所有脚本通过此模块加载数据。

关键修复：
1. volume字段(uint32, 字节24-28) 和 amount字段(float, 字节20-23) 的正确读取
2. 价格乘数统一为100.0（指数和个股一致）
3. 集中化泡沫检测和市场状态分类
"""

import struct
from pathlib import Path
from typing import List, Optional, Tuple

import pandas as pd

TDX_DAY_RECORD_SIZE = 32
TDX_DAY_FORMAT = '<IIIIIfII'
TDX_DIR = Path("/home/james/.local/share/tdxcfv/drive_c/tc/vipdoc")


def _get_divisor() -> float:
    """
    TDX .day格式: 所有品种（指数和个股）价格乘数均为100.0
    """
    return 100.0


def load_tdx_data(filepath: str, max_records: Optional[int] = None) -> Optional[pd.DataFrame]:
    """
    从TDX .day文件加载数据（正确解析volume和amount）

    Args:
        filepath: .day文件完整路径
        max_records: 最大读取记录数（None为全部）

    Returns:
        DataFrame with columns: date, open, high, low, close, volume, amount
    """
    fp = Path(filepath)
    if not fp.exists():
        return None

    divisor = _get_divisor()
    records = []

    with open(fp, 'rb') as f:
        while True:
            data = f.read(TDX_DAY_RECORD_SIZE)
            if not data or len(data) < TDX_DAY_RECORD_SIZE:
                break

            try:
                dt, o, h, l, c, amt, vol, _ = struct.unpack(TDX_DAY_FORMAT, data)  # noqa: E741

                if dt < 19900101 or dt > 21000101:
                    continue

                year = dt // 10000
                month = (dt % 10000) // 100
                day = dt % 100

                records.append({
                    "date": f"{year}-{month:02d}-{day:02d}",
                    "open": o / divisor,
                    "high": h / divisor,
                    "low": l / divisor,
                    "close": c / divisor,
                    "volume": vol,
                    "amount": amt,
                })
            except (struct.error, ValueError):
                continue

    if not records:
        return None

    df = pd.DataFrame(records)
    if max_records and len(df) > max_records:
        df = df.tail(max_records)

    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    return df


def load_index_from_tdx(tdx_path: str) -> pd.DataFrame:
    """
    加载指数数据（兼容旧函数签名）
    这是所有策略验证脚本使用的接口

    Args:
        tdx_path: 指数.day文件路径

    Returns:
        DataFrame with correct price divisor
    """
    df = load_tdx_data(tdx_path)
    if df is not None:
        return df
    return pd.DataFrame()


def load_bubble_periods(index_df: pd.DataFrame) -> List[Tuple[str, str]]:
    """
    检测大盘泡沫阶段（集中化，避免各脚本重复实现）
    基于价格涨幅和波动率检测
    """
    bubble_periods = []
    df = index_df.copy()
    df['ma60'] = df['close'].rolling(60).mean()
    df['returns'] = df['close'].pct_change()
    df['volatility'] = df['returns'].rolling(20).std()
    df['high_120'] = df['close'].rolling(120).max()
    df['low_120'] = df['close'].rolling(120).min()
    df['relative_position'] = (df['close'] - df['low_120']) / (df['high_120'] - df['low_120']).replace(0, 1)

    for i in range(120, len(df)):
        row = df.iloc[i]
        is_bubble = False
        if row['ma60'] > 0 and (row['close'] - row['ma60']) / row['ma60'] > 0.2:
            is_bubble = True
        if row['volatility'] > 0.03:
            is_bubble = True
        if row['relative_position'] > 0.95:
            is_bubble = True

        if is_bubble:
            bubble_start = df.iloc[max(0, i-30)]['date']
            bubble_end = df.iloc[min(len(df)-1, i+30)]['date']
            bubble_periods.append((str(bubble_start), str(bubble_end)))

    if not bubble_periods:
        return []

    merged = []
    curr_start, curr_end = bubble_periods[0]
    for start, end in bubble_periods[1:]:
        if start <= curr_end:
            curr_end = max(curr_end, end)
        else:
            merged.append((curr_start, curr_end))
            curr_start, curr_end = start, end
    merged.append((curr_start, curr_end))
    return merged


def is_in_bubble_period(date_str: str, bubble_periods: List[Tuple[str, str]]) -> bool:
    """检查日期是否在泡沫期"""
    date = pd.Timestamp(date_str)
    for start, end in bubble_periods:
        if pd.Timestamp(start) <= date <= pd.Timestamp(end):
            return True
    return False


def classify_market_regime(index_df: pd.DataFrame, date_str: str) -> str:
    """
    分类市场状态：bull/bear/range
    基于252天年化收益
    """
    date = pd.Timestamp(date_str)
    hist = index_df[index_df['date'] <= date].tail(252)
    if len(hist) < 60:
        return "unknown"
    annual_return = (hist['close'].iloc[-1] / hist['close'].iloc[0]) ** (252 / len(hist)) - 1
    if annual_return > 0.15:
        return "bull"
    elif annual_return < -0.10:
        return "bear"
    else:
        return "range"
