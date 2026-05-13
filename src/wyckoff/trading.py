"""
Wyckoff交易模拟工具函数
======================
用于测试脚本中正确模拟Wyckoff引擎的交易执行逻辑：
1. 使用引擎给出的入场价而非收盘价
2. 加入止损逻辑
3. 加入止盈逻辑
4. 跳过未被执行的交易（入场价未触及）
"""

from typing import Dict, List, Optional

import pandas as pd


def calculate_wyckoff_return(
    df: pd.DataFrame,
    as_of_date: str,
    days: int = 60,
    wyckoff_entry: Optional[float] = None,
    stop_loss: Optional[float] = None,
    first_target: Optional[float] = None,
) -> Optional[Dict[str, float]]:
    """
    按Wyckoff交易计划计算持有期收益

    相比原始calculate_future_return的改进:
    1. 使用引擎给出的入场价，而非收盘价市价买入
    2. 如果入场价未触及（entry > low），交易未执行 → 跳过
    3. 如果持有期内触发止损 → 以止损价退出
    4. 如果持有期内触达目标 → 以目标价退出
    5. 否则按收盘价持有到期
    """
    as_of = pd.Timestamp(as_of_date)
    future_data = df[df["date"] > as_of].head(days)
    if len(future_data) < days * 0.8:
        return None

    current_close = float(df[df["date"] <= as_of].iloc[-1]["close"])
    
    # 决定实际入场价
    use_wyckoff_entry = (
        wyckoff_entry is not None 
        and wyckoff_entry > 0 
        and abs(wyckoff_entry - current_close) / current_close > 0.001
    )
    entry_price = wyckoff_entry if use_wyckoff_entry else current_close
    
    # 如果使用Wyckoff入场价，检查是否实际成交
    if use_wyckoff_entry:
        period_low = float(future_data["low"].min())
        if wyckoff_entry < period_low:
            # 入场价在整个持有期内未被触及 → 交易未执行
            return None

    # 遍历K线，模拟止损/止盈逻辑
    exit_price = None
    exit_reason = "hold_to_end"
    hit_stop = False
    hit_target = False

    for _, row in future_data.iterrows():
        close = float(row["close"])
        high = float(row["high"])
        low = float(row["low"])

        # 检查止损
        if stop_loss is not None and stop_loss > 0:
            if low <= stop_loss:
                exit_price = stop_loss
                exit_reason = "stop_loss"
                hit_stop = True
                break

        # 检查止盈
        if first_target is not None and first_target > 0:
            if high >= first_target:
                exit_price = first_target
                exit_reason = "take_profit"
                hit_target = True
                break

        exit_price = close

    # 如果至期末未触发止损/止盈，按最终收盘价退出
    if not hit_stop and not hit_target:
        exit_price = float(future_data.iloc[-1]["close"])

    # 计算收益
    return_pct = (exit_price - entry_price) / entry_price * 100
    future_high = float(future_data["high"].max())
    future_low = float(future_data["low"].min())
    max_gain_pct = (future_high - entry_price) / entry_price * 100
    max_drawdown_pct = (entry_price - future_low) / entry_price * 100

    return {
        "entry_price": round(entry_price, 3),
        "exit_price": round(exit_price, 3),
        "exit_reason": exit_reason,
        "future_close": round(float(future_data.iloc[-1]["close"]), 3),
        "future_high": round(future_high, 3),
        "future_low": round(future_low, 3),
        "return_pct": round(return_pct, 2),
        "max_gain_pct": round(max_gain_pct, 2),
        "max_drawdown_pct": round(max_drawdown_pct, 2),
        "data_points": len(future_data),
        "hit_stop": hit_stop,
        "hit_target": hit_target,
    }


def calculate_wyckoff_decay_returns(
    df: pd.DataFrame,
    as_of_date: str,
    decay_days: List[int],
    wyckoff_entry: Optional[float] = None,
    stop_loss: Optional[float] = None,
    first_target: Optional[float] = None,
) -> Dict[str, Optional[float]]:
    """计算多个时间窗口的衰减收益（Wyckoff版本）"""
    results = {}
    for days in decay_days:
        ret = calculate_wyckoff_return(df, as_of_date, days, wyckoff_entry, stop_loss, first_target)
        results[f"return_{days}d"] = ret["return_pct"] if ret else None
    return results
