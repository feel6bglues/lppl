# -*- coding: utf-8 -*-
"""Signal evaluation models for investment strategies."""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

import pandas as pd

from src.lppl_core import calculate_bottom_signal_strength, detect_negative_bubble
from src.lppl_engine import LPPLConfig

from .config import InvestmentSignalConfig


def resolve_action(previous_target: float, next_target: float) -> str:
    """Resolve trading action based on position change."""
    if next_target > previous_target:
        return "buy" if previous_target <= 0.0 else "add"
    if next_target < previous_target:
        return "sell" if next_target <= 0.0 else "reduce"
    return "hold"


def evaluate_multi_factor_adaptive(
    row: pd.Series,
    config: InvestmentSignalConfig,
    current_target: float,
) -> Tuple[float, str]:
    """Evaluate multi-factor adaptive strategy with weighted scoring system.

    Combines:
    - Trend factor (MA cross + HTF trend) - 40%
    - Volatility factor (ATR ratio) - 30%
    - Market state factor (BB width) - 20%
    - Momentum factor (price momentum) - 10%
    """
    close_price = float(row["close"])

    # === Trend Factor (40%) ===
    bullish_cross = bool(row.get("bullish_cross", False))
    bearish_cross = bool(row.get("bearish_cross", False))
    trend_score = 0.0
    if bullish_cross:
        trend_score = 1.0
    elif bearish_cross:
        trend_score = -1.0

    # HTF trend confirmation
    htf_ma = float(row.get("ma_regime", close_price))
    htf_ratio = close_price / htf_ma if htf_ma > 0 else 1.0
    if htf_ratio >= 1.02:
        trend_score += 0.5
    elif htf_ratio <= 0.98:
        trend_score -= 0.5

    # === Volatility Factor (30%) ===
    atr_ratio = float(row.get("atr_ratio", 1.0))
    vol_score = 0.0
    if atr_ratio < config.atr_low_threshold:
        vol_score = 1.0
    elif atr_ratio > config.atr_high_threshold:
        vol_score = -1.0

    # === Market State Factor (20%) ===
    bb_width = float(row.get("bb_width", 0.10))
    state_score = 0.0
    if bb_width < config.bb_narrow_threshold:
        state_score = 0.5
    elif bb_width > config.bb_wide_threshold:
        state_score = -0.5

    # === Momentum Factor (10%) ===
    ma_short = float(row.get("ma_short", close_price))
    ma_mid = float(row.get("ma_mid", close_price))
    momentum_score = 0.0
    if ma_short > ma_mid:
        momentum_score = 0.5
    elif ma_short < ma_mid:
        momentum_score = -0.5

    # === Weighted Total Score ===
    total_score = (
        trend_score * config.trend_weight
        + vol_score * config.volatility_weight
        + state_score * config.market_state_weight
        + momentum_score * config.momentum_weight
    )

    # === Decision Logic ===
    risk_drawdown = float(row.get("risk_price_drawdown", 0.0))

    # Position sizing based on volatility
    vol_position_cap = float(config.full_position)
    if atr_ratio > config.atr_high_threshold:
        vol_position_cap = 0.5
    elif atr_ratio > 1.05:
        vol_position_cap = 0.7

    next_target = current_target

    # Risk layer - drawdown stop
    if (
        current_target > config.flat_position + 1e-8
        and config.regime_filter_reduce_enabled
        and risk_drawdown <= -config.risk_drawdown_stop_threshold
    ):
        next_target = config.flat_position
        return next_target, f"回撤止损(评分={total_score:.2f})"

    # Buy decision
    if total_score >= config.buy_score_threshold and trend_score > 0:
        next_target = min(config.full_position, vol_position_cap)
        return next_target, f"多因子买入(评分={total_score:.2f})"

    # Sell decision
    if total_score <= config.sell_score_threshold and trend_score < 0:
        next_target = config.flat_position
        return next_target, f"多因子卖出(评分={total_score:.2f})"

    # Reduce decision
    if (
        total_score < 0
        and total_score > config.sell_score_threshold
        and current_target > config.flat_position + 1e-8
    ):
        next_target = config.half_position
        return next_target, f"多因子减仓(评分={total_score:.2f})"

    return next_target, f"多因子持有(评分={total_score:.2f})"


def map_single_window_signal(
    result: Optional[Dict[str, Any]],
    current_target: float,
    signal_config: InvestmentSignalConfig,
    lppl_config: LPPLConfig,
) -> Tuple[str, float, str, float]:
    """Map LPPL single-window scan result to investment signal.

    Returns:
        Tuple of (signal_name, signal_strength, position_reason, next_target)
    """
    if not result:
        return "none", 0.0, "无信号", current_target

    params = result.get("params", ())
    b_value = float(params[4]) if len(params) > 4 else 0.0
    days_to_crash = float(result.get("days_to_crash", 9999.0))
    m_value = float(result.get("m", 0.0))
    w_value = float(result.get("w", 0.0))
    rmse = float(result.get("rmse", 1.0))
    r_squared = float(result.get("r_squared", 0.0))

    is_negative, bottom_signal = detect_negative_bubble(m_value, w_value, b_value, days_to_crash)
    if is_negative:
        bottom_strength = calculate_bottom_signal_strength(m_value, w_value, b_value, rmse)
        if days_to_crash < signal_config.strong_buy_days:
            return "negative_bubble", bottom_strength, bottom_signal, signal_config.full_position
        if days_to_crash < signal_config.buy_days:
            target = max(current_target, signal_config.half_position)
            return "negative_bubble", bottom_strength, bottom_signal, target
        return "negative_bubble_watch", bottom_strength, bottom_signal, current_target

    if (
        b_value <= 0
        and days_to_crash < lppl_config.danger_days
        and r_squared >= lppl_config.r2_threshold
    ):
        return "bubble_risk", r_squared, "高危信号", signal_config.flat_position

    warning_threshold = max(0.0, lppl_config.r2_threshold - 0.1)
    if b_value <= 0 and days_to_crash < lppl_config.warning_days and r_squared >= warning_threshold:
        target = min(current_target, signal_config.half_position)
        return "bubble_warning", r_squared, "观察信号", target

    return "none", 0.0, "无信号", current_target


def map_ensemble_signal(
    result: Optional[Dict[str, Any]],
    current_target: float,
    signal_config: InvestmentSignalConfig,
    lppl_config: LPPLConfig,
) -> Tuple[str, float, str, float]:
    """Map LPPL ensemble consensus result to investment signal.

    Returns:
        Tuple of (signal_name, signal_strength, position_reason, next_target)
    """
    if not result:
        return "none", 0.0, "无信号", current_target

    signal_strength = float(result.get("signal_strength", 0.0))
    positive_consensus = float(
        result.get("positive_consensus_rate", result.get("consensus_rate", 0.0))
    )
    negative_consensus = float(result.get("negative_consensus_rate", 0.0))
    positive_days = result.get("predicted_crash_days")
    negative_days = result.get("predicted_rebound_days")

    if negative_days is not None and negative_consensus > positive_consensus:
        negative_days = float(negative_days)
        if negative_days < signal_config.strong_buy_days:
            return (
                "negative_bubble",
                signal_strength,
                "Ensemble 抄底共识",
                signal_config.full_position,
            )
        if negative_days < signal_config.buy_days:
            target = max(current_target, signal_config.half_position)
            return "negative_bubble", signal_strength, "Ensemble 抄底共识", target
        return "negative_bubble_watch", signal_strength, "Ensemble 抄底观察", current_target

    if positive_days is not None:
        positive_days = float(positive_days)
        if positive_days < lppl_config.danger_days:
            return "bubble_risk", signal_strength, "Ensemble 高危共识", signal_config.flat_position
        if positive_days < lppl_config.warning_days:
            target = min(current_target, signal_config.half_position)
            return "bubble_warning", signal_strength, "Ensemble 观察信号", target

    return "none", 0.0, "无信号", current_target
