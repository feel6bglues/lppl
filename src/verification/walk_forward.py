# -*- coding: utf-8 -*-
from typing import Dict, List, Tuple

import pandas as pd

from src.lppl_engine import LPPLConfig, process_single_day_ensemble, scan_single_date


def evaluate_future_drawdown(
    close_prices,
    idx: int,
    lookahead_days: int = 60,
    drop_threshold: float = 0.10,
) -> Tuple[bool, float]:
    future_prices = close_prices[idx + 1 : idx + 1 + lookahead_days]
    if len(future_prices) == 0:
        return False, 0.0

    current_price = close_prices[idx]
    future_min = min(future_prices)
    realized_drop = (current_price - future_min) / current_price
    return realized_drop >= drop_threshold, realized_drop


def summarize_walk_forward(records_df: pd.DataFrame) -> Dict[str, float]:
    total_points = len(records_df)
    signal_count = int(records_df["signal_detected"].sum()) if total_points > 0 else 0
    event_count = int(records_df["event_hit"].sum()) if total_points > 0 else 0

    true_positive = (
        int(((records_df["signal_detected"]) & (records_df["event_hit"])).sum())
        if total_points > 0
        else 0
    )
    false_positive = (
        int(((records_df["signal_detected"]) & (~records_df["event_hit"])).sum())
        if total_points > 0
        else 0
    )
    false_negative = (
        int(((~records_df["signal_detected"]) & (records_df["event_hit"])).sum())
        if total_points > 0
        else 0
    )

    precision = true_positive / signal_count if signal_count > 0 else 0.0
    recall = true_positive / event_count if event_count > 0 else 0.0
    false_positive_rate = false_positive / total_points if total_points > 0 else 0.0
    signal_density = signal_count / total_points if total_points > 0 else 0.0

    return {
        "total_points": total_points,
        "signal_count": signal_count,
        "event_count": event_count,
        "true_positive": true_positive,
        "false_positive": false_positive,
        "false_negative": false_negative,
        "precision": precision,
        "recall": recall,
        "false_positive_rate": false_positive_rate,
        "signal_density": signal_density,
    }


def run_walk_forward(
    df: pd.DataFrame,
    symbol: str,
    window_range: List[int],
    config: LPPLConfig,
    scan_step: int = 5,
    lookahead_days: int = 60,
    drop_threshold: float = 0.10,
    use_ensemble: bool = False,
) -> Tuple[pd.DataFrame, Dict[str, float]]:
    df = df.sort_values("date").reset_index(drop=True).copy()
    df["date"] = pd.to_datetime(df["date"])
    close_prices = df["close"].values

    start_idx = max(window_range)
    end_idx = len(df) - lookahead_days - 1
    records: List[Dict] = []

    for idx in range(start_idx, end_idx + 1, scan_step):
        event_hit, realized_drop = evaluate_future_drawdown(
            close_prices, idx, lookahead_days, drop_threshold
        )

        if use_ensemble:
            signal_result = process_single_day_ensemble(
                close_prices,
                idx,
                window_range,
                min_r2=config.r2_threshold,
                consensus_threshold=config.consensus_threshold,
                config=config,
            )
            signal_detected = bool(
                signal_result and signal_result["predicted_crash_days"] < config.danger_days
            )
            signal_type = "danger" if signal_detected else "none"
        else:
            signal_result = scan_single_date(close_prices, idx, window_range, config)
            signal_detected = bool(signal_result and signal_result.get("is_danger"))
            signal_type = "danger" if signal_detected else "none"

        records.append(
            {
                "symbol": symbol,
                "date": df.iloc[idx]["date"].strftime("%Y-%m-%d"),
                "price": float(df.iloc[idx]["close"]),
                "signal_detected": signal_detected,
                "signal_type": signal_type,
                "event_hit": event_hit,
                "realized_drop": realized_drop,
                "lookahead_days": lookahead_days,
                "drop_threshold": drop_threshold,
                "mode": "ensemble" if use_ensemble else "single_window",
            }
        )

    records_df = pd.DataFrame(records)
    summary = summarize_walk_forward(records_df)
    summary["symbol"] = symbol
    summary["mode"] = "ensemble" if use_ensemble else "single_window"
    summary["lookahead_days"] = lookahead_days
    summary["drop_threshold"] = drop_threshold

    return records_df, summary
