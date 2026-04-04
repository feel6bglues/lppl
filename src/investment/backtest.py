# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

import pandas as pd

# Unified import from lppl_engine (core functions migrated)
from src.lppl_engine import (
    LPPLConfig,
    calculate_bottom_signal_strength,
    classify_top_phase,
    detect_negative_bubble,
    process_single_day_ensemble,
    scan_single_date,
)

LARGE_CAP_SYMBOLS = {"000001.SH", "000016.SH", "000300.SH"}
BALANCED_SYMBOLS = {"399001.SZ", "000905.SH"}
HIGH_BETA_SYMBOLS = {"399006.SZ", "000852.SH", "932000.SH"}

import numpy as np


@dataclass
class InvestmentSignalConfig:
    # ========== 基础配置（继承新手指南）==========
    signal_model: str = "ma_cross_atr_v1"
    initial_position: float = 0.0
    full_position: float = 1.0
    flat_position: float = 0.0
    half_position: float = 0.5

    # MA趋势参数
    trend_fast_ma: int = 20
    trend_slow_ma: int = 60
    trend_slope_window: int = 10

    # ATR波动参数
    atr_period: int = 14
    atr_ma_window: int = 40
    vol_breakout_mult: float = 1.15
    buy_volatility_cap: float = 1.05
    high_volatility_mult: float = 1.15
    high_volatility_position_cap: float = 0.5

    # 阶段1: 动态波动率缩放参数
    enable_volatility_scaling: bool = False
    target_volatility: float = 0.15

    # 阶段2: 动量因子参数
    enable_momentum_factor: bool = False
    momentum_windows: tuple = (20, 60)
    momentum_weight: float = 1.0
    momentum_threshold: float = 0.0
    strong_momentum_threshold: float = 0.05

    # 阶段3: 市场状态参数
    enable_market_state: bool = False
    adx_threshold_trending: float = 25.0
    adx_threshold_ranging: float = 20.0

    # 阶段4: 52周高点参数
    enable_52w_high_factor: bool = False
    proximity_52w_threshold: float = 0.95
    breakout_weight: float = 0.25

    # ========== 原有LPPL/交易参数 ==========
    strong_buy_days: int = 20
    buy_days: int = 40
    strong_sell_days: int = 20
    reduce_days: int = 60
    watch_days: int = 25
    warning_days: int = 12
    danger_r2_offset: float = 0.0
    warning_trade_enabled: bool = True
    full_exit_days: int = 3
    positive_consensus_threshold: float = 0.25
    negative_consensus_threshold: float = 0.20
    danger_days: int = 5
    rebound_days: int = 15

    # 交易执行参数
    buy_vote_threshold: int = 3
    sell_vote_threshold: int = 3
    buy_confirm_days: int = 1
    sell_confirm_days: int = 1
    cooldown_days: int = 15
    post_sell_reentry_cooldown_days: int = 10
    min_hold_bars: int = 0
    allow_top_risk_override_min_hold: bool = True
    enable_regime_hysteresis: bool = True
    require_trend_recovery_for_buy: bool = True
    drawdown_confirm_threshold: float = 0.05
    buy_reentry_drawdown_threshold: float = 0.08
    buy_reentry_lookback: int = 20
    buy_trend_slow_buffer: float = 0.98

    @classmethod
    def for_symbol(cls, symbol: str) -> "InvestmentSignalConfig":
        """Load config for symbol. Group-specific values are from YAML if present,
        otherwise use dataclass defaults. Symbol group only adjusts consensus thresholds.        """
        base = cls()

        # Load YAML overrides if available
        try:
            from src.config.optimal_params import load_optimal_config
            yaml_cfg = load_optimal_config("config/optimal_params.yaml")
            sym_cfg = yaml_cfg.get("symbols", {}).get(symbol, {})

            # Apply YAML field overrides to base config
            for field in cls.__dataclass_fields__:
                if field in sym_cfg and sym_cfg[field] is not None:
                    setattr(base, field, sym_cfg[field])
        except Exception:
            pass  # Fall back to defaults if YAML unavailable

        # Apply symbol group specific consensus thresholds
        if symbol in LARGE_CAP_SYMBOLS:
            base.positive_consensus_threshold = 0.25
            base.negative_consensus_threshold = 0.20
        elif symbol in BALANCED_SYMBOLS:
            base.positive_consensus_threshold = 0.25
            base.negative_consensus_threshold = 0.20
        elif symbol in HIGH_BETA_SYMBOLS:
            base.positive_consensus_threshold = 0.20
            base.negative_consensus_threshold = 0.20

        return base

    @classmethod
    def from_mapping(cls, symbol: str, mapping: Optional[Dict[str, Any]] = None) -> "InvestmentSignalConfig":
        config = cls.for_symbol(symbol)
        if not mapping:
            return config

        for field_name in cls.__dataclass_fields__:
            if field_name in mapping and mapping[field_name] is not None:
                setattr(config, field_name, mapping[field_name])

        config.initial_position = float(min(max(config.initial_position, config.flat_position), config.full_position))
        config.buy_vote_threshold = max(1, int(config.buy_vote_threshold))
        config.sell_vote_threshold = max(1, int(config.sell_vote_threshold))
        config.buy_confirm_days = max(1, int(config.buy_confirm_days))
        config.sell_confirm_days = max(1, int(config.sell_confirm_days))
        config.cooldown_days = max(0, int(config.cooldown_days))
        config.post_sell_reentry_cooldown_days = max(0, int(config.post_sell_reentry_cooldown_days))
        config.min_hold_bars = max(0, int(config.min_hold_bars))
        config.warning_trade_enabled = _to_bool(config.warning_trade_enabled, True)
        config.allow_top_risk_override_min_hold = _to_bool(config.allow_top_risk_override_min_hold, True)
        config.enable_regime_hysteresis = _to_bool(config.enable_regime_hysteresis, True)
        config.require_trend_recovery_for_buy = _to_bool(config.require_trend_recovery_for_buy, True)
        config.full_exit_days = max(1, int(config.full_exit_days))
        config.danger_days = max(1, int(config.danger_days))
        config.warning_days = max(config.danger_days + 1, int(config.warning_days))
        config.watch_days = max(config.warning_days + 1, int(config.watch_days))
        config.trend_fast_ma = max(2, int(config.trend_fast_ma))
        config.trend_slow_ma = max(config.trend_fast_ma + 1, int(config.trend_slow_ma))
        config.trend_slope_window = max(1, int(config.trend_slope_window))
        config.atr_period = max(2, int(config.atr_period))
        config.atr_ma_window = max(2, int(config.atr_ma_window))
        config.momentum_windows = tuple(int(w) for w in config.momentum_windows)
        config.momentum_weight = float(max(config.momentum_weight, 0.0))
        return config


@dataclass
class BacktestConfig:
    initial_capital: float = 1_000_000.0
    buy_fee: float = 0.0003
    sell_fee: float = 0.0003
    slippage: float = 0.0005
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    execution_price: str = "open"


@dataclass
class ActiveLPPLState:
    signal_strength: float = 0.0
    reason: str = "无信号"
    positive_consensus: float = 0.0
    negative_consensus: float = 0.0
    positive_days: Optional[float] = None
    negative_days: Optional[float] = None
    positive_signal_name: str = "none"
    negative_signal_name: str = "none"
    age_days: int = 0

    def advance(self) -> None:
        self.age_days += 1

    def effective_positive_days(self) -> Optional[float]:
        if self.positive_days is None:
            return None
        return float(self.positive_days) - float(self.age_days)

    def effective_negative_days(self) -> Optional[float]:
        if self.negative_days is None:
            return None
        return float(self.negative_days) - float(self.age_days)


def _positive_phase_rank(signal_name: str) -> int:
    return {
        "none": 0,
        "bubble_watch": 1,
        "bubble_warning": 2,
        "bubble_risk": 3,
    }.get(str(signal_name), 0)


def _normalize_price_frame(df: pd.DataFrame) -> pd.DataFrame:
    normalized = df.copy()
    normalized["date"] = pd.to_datetime(normalized["date"])
    normalized = normalized.sort_values("date").reset_index(drop=True)

    if "open" not in normalized.columns:
        normalized["open"] = normalized["close"]
    if "high" not in normalized.columns:
        normalized["high"] = normalized[["open", "close"]].max(axis=1)
    if "low" not in normalized.columns:
        normalized["low"] = normalized[["open", "close"]].min(axis=1)
    if "volume" not in normalized.columns:
        normalized["volume"] = 0.0

    return normalized


def _compute_indicators(df: pd.DataFrame, signal_config: InvestmentSignalConfig) -> pd.DataFrame:
    enriched = df.copy()

    # ===== 基础指标（趋势层）=====
    enriched["ma_fast"] = enriched["close"].rolling(signal_config.trend_fast_ma, min_periods=1).mean()
    enriched["ma_slow"] = enriched["close"].rolling(signal_config.trend_slow_ma, min_periods=1).mean()
    enriched["ma_fast_prev"] = enriched["ma_fast"].shift(1)
    enriched["ma_slow_prev"] = enriched["ma_slow"].shift(1)
    enriched["bullish_cross"] = (
        (enriched["ma_fast"] > enriched["ma_slow"])
        & (enriched["ma_fast_prev"].fillna(enriched["ma_fast"]) <= enriched["ma_slow_prev"].fillna(enriched["ma_slow"]))
    )
    enriched["bearish_cross"] = (
        (enriched["ma_fast"] < enriched["ma_slow"])
        & (enriched["ma_fast_prev"].fillna(enriched["ma_fast"]) >= enriched["ma_slow_prev"].fillna(enriched["ma_slow"]))
    )
    slope_base = enriched["ma_fast"].shift(signal_config.trend_slope_window)
    enriched["ma_fast_slope"] = enriched["ma_fast"] - slope_base

    # ===== ATR波动率指标 =====
    prev_close = enriched["close"].shift(1).fillna(enriched["close"])
    true_range = pd.concat(
        [
            enriched["high"] - enriched["low"],
            (enriched["high"] - prev_close).abs(),
            (enriched["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    enriched["atr"] = true_range.rolling(signal_config.atr_period, min_periods=1).mean()
    enriched["atr_ma"] = enriched["atr"].rolling(signal_config.atr_ma_window, min_periods=1).mean()
    enriched["atr_ratio"] = enriched["atr"] / enriched["atr_ma"].clip(lower=1e-10)

    # ===== 回撤指标 =====
    # 注意: rolling_peak 使用滚动窗口而非全局 cummax，用于检测短期回撤
    # 与回测引擎中的全局回撤 (cummax) 口径不同
    drawdown_window = max(signal_config.atr_ma_window, 20)
    enriched["rolling_peak"] = enriched["close"].rolling(drawdown_window, min_periods=1).max()
    enriched["price_drawdown"] = (enriched["close"] / enriched["rolling_peak"]) - 1.0
    enriched["recent_drawdown_min"] = enriched["price_drawdown"].rolling(20, min_periods=1).min()

    # ===== 阶段1: 动态波动率缩放 =====
    if signal_config.enable_volatility_scaling:
        enriched["returns"] = enriched["close"].pct_change()
        enriched["realized_vol_21"] = (
            enriched["returns"].rolling(21, min_periods=1).std() * np.sqrt(252)
        )
        target_vol = signal_config.target_volatility
        enriched["vol_scale_factor"] = (
            target_vol / enriched["realized_vol_21"].clip(lower=0.05)
        ).clip(upper=2.0)
    else:
        enriched["vol_scale_factor"] = 1.0

    # ===== 阶段2: 动量因子 =====
    if signal_config.enable_momentum_factor:
        for window in signal_config.momentum_windows:
            col_name = f"momentum_{window}"
            enriched[col_name] = enriched["close"] / enriched["close"].shift(window) - 1

        # 合成动量得分
        momentum_cols = [f"momentum_{w}" for w in signal_config.momentum_windows]
        enriched["momentum_score"] = enriched[momentum_cols].mean(axis=1)
        enriched["momentum_direction"] = np.sign(enriched["momentum_score"])

    # ===== 阶段4: 52周高点效应 =====
    if signal_config.enable_52w_high_factor:
        rolling_52w_high = enriched["close"].rolling(252, min_periods=1).max()
        enriched["proximity_52w_high"] = enriched["close"] / rolling_52w_high
        enriched["is_near_52w_high"] = enriched["proximity_52w_high"] >= signal_config.proximity_52w_threshold

        # 突破动量合成（如果有动量因子）
        if signal_config.enable_momentum_factor:
            enriched["breakout_momentum"] = (
                enriched["is_near_52w_high"].astype(float) *
                enriched["momentum_score"].clip(lower=0)
            ) * signal_config.breakout_weight

    return enriched


def _evaluate_ma_cross_atr_lppl(
    row: pd.Series,
    state: ActiveLPPLState,
    signal_config: InvestmentSignalConfig,
    current_target: float,
) -> Dict[str, Any]:
    positive_days = state.effective_positive_days()
    positive_signal_name = str(state.positive_signal_name)
    atr_ratio = float(row["atr_ratio"])
    bullish_cross = bool(row.get("bullish_cross", False))
    bearish_cross = bool(row.get("bearish_cross", False))

    buy_atr_limit = float(signal_config.buy_volatility_cap)
    buy_candidate = bullish_cross and atr_ratio <= buy_atr_limit
    sell_candidate = bearish_cross and atr_ratio >= float(signal_config.vol_breakout_mult)

    lppl_signal = "none"
    signal_strength = 0.0
    position_reason = "MA20/MA60 未触发"
    target_position_cap = float(signal_config.full_position)
    forced_target: Optional[float] = None

    positive_lppl_active = (
        positive_signal_name in {"bubble_watch", "bubble_warning", "bubble_risk"}
        and positive_days is not None
        and positive_days >= 0.0
    )
    if positive_lppl_active:
        lppl_signal = positive_signal_name
        signal_strength = max(float(state.signal_strength), float(state.positive_consensus))
        buy_candidate = False
        sell_candidate = False
        if positive_signal_name == "bubble_watch":
            target_position_cap = min(target_position_cap, float(signal_config.full_position))
            position_reason = "LPPL 顶部观察"
        elif positive_signal_name == "bubble_warning":
            forced_target = min(float(current_target), float(signal_config.half_position))
            position_reason = "LPPL 警告，限制至半仓"
        elif positive_signal_name == "bubble_risk":
            if positive_days <= float(signal_config.full_exit_days):
                forced_target = float(signal_config.flat_position)
                position_reason = f"LPPL 高危<= {signal_config.full_exit_days} 天，清仓"
            else:
                forced_target = min(float(current_target), float(signal_config.half_position))
                position_reason = "LPPL 高危，先减至半仓"

    if forced_target is None:
        if buy_candidate:
            forced_target = min(float(signal_config.full_position), target_position_cap)
            position_reason = "MA20 上穿 MA60 + ATR 买入确认"
        elif sell_candidate:
            forced_target = float(signal_config.half_position)
            position_reason = "MA20 下穿 MA60 + ATR 卖出确认"

    if forced_target is None:
        forced_target = float(current_target)

    if current_target <= float(signal_config.flat_position) + 1e-8:
        forced_target = max(float(signal_config.flat_position), forced_target)
    if current_target <= float(signal_config.half_position) + 1e-8 and forced_target > float(signal_config.half_position):
        forced_target = min(forced_target, float(signal_config.full_position))
    if current_target >= float(signal_config.half_position) - 1e-8 and forced_target < float(signal_config.flat_position) + 1e-8:
        forced_target = float(signal_config.flat_position)

    return {
        "lppl_signal": lppl_signal,
        "signal_strength": float(signal_strength),
        "position_reason": position_reason,
        "lppl_vote": int(positive_lppl_active),
        "positive_lppl_vote": int(positive_lppl_active),
        "negative_lppl_vote": 0,
        "trend_buy_vote": int(bullish_cross),
        "trend_sell_vote": int(bearish_cross),
        "vol_buy_vote": int(atr_ratio <= buy_atr_limit),
        "vol_sell_vote": int(atr_ratio >= float(signal_config.vol_breakout_mult)),
        "drawdown_buy_vote": 0,
        "drawdown_sell_vote": 0,
        "buy_votes": int(buy_candidate),
        "sell_votes": int(sell_candidate) + int(positive_signal_name in {"bubble_warning", "bubble_risk"}),
        "buy_candidate": bool(buy_candidate),
        "sell_candidate": bool(sell_candidate or positive_signal_name in {"bubble_warning", "bubble_risk"}),
        "atr_ratio": atr_ratio,
        "price_drawdown": float(row["price_drawdown"]),
        "recent_drawdown_min": float(row["recent_drawdown_min"]),
        "vol_position_cap": float(signal_config.full_position),
        "positive_days_left": positive_days,
        "negative_days_left": None,
        "positive_consensus": float(state.positive_consensus),
        "negative_consensus": float(state.negative_consensus),
        "positive_signal_name": positive_signal_name,
        "next_target": float(forced_target),
    }


def _evaluate_ma_cross_atr(
    row: pd.Series,
    signal_config: InvestmentSignalConfig,
    current_target: float,
) -> Dict[str, Any]:
    """融合版 MA交叉 + ATR + 动态波动率缩放模型（无 LPPL）。"""
    atr_ratio = float(row["atr_ratio"])
    bullish_cross = bool(row.get("bullish_cross", False))
    bearish_cross = bool(row.get("bearish_cross", False))

    # ===== 阶段2: 动量确认 =====
    if signal_config.enable_momentum_factor:
        momentum_score = float(row.get("momentum_score", 0))
        momentum_positive = momentum_score > signal_config.momentum_threshold

        # MA金叉 + 动量确认
        buy_candidate = bullish_cross and momentum_positive and atr_ratio <= float(signal_config.buy_volatility_cap)
        # MA死叉 或 动量转负
        sell_candidate = bearish_cross or (momentum_score < -0.02)
    else:
        # 纯MA+ATR（阶段0/1）
        buy_candidate = bullish_cross and atr_ratio <= float(signal_config.buy_volatility_cap)
        sell_candidate = bearish_cross and atr_ratio >= float(signal_config.vol_breakout_mult)

    # ===== 阶段1: 动态波动率缩放 =====
    if signal_config.enable_volatility_scaling:
        vol_scale = float(row.get("vol_scale_factor", 1.0))
        # 高波动时降低目标仓位
        volatility_cap = signal_config.full_position * vol_scale
    else:
        volatility_cap = signal_config.full_position

    next_target = current_target
    position_reason = "持有"

    if buy_candidate:
        next_target = min(signal_config.full_position, volatility_cap)
        if signal_config.enable_momentum_factor:
            position_reason = f"MA金叉+动量确认(得分={row.get('momentum_score', 0):.2%})"
        else:
            position_reason = "MA金叉+ATR确认"
    elif sell_candidate:
        next_target = signal_config.flat_position
        position_reason = "MA死叉信号"

    return {
        "position_reason": position_reason,
        "next_target": next_target,
        "atr_ratio": atr_ratio,
        "vol_scale": row.get("vol_scale_factor", 1.0) if signal_config.enable_volatility_scaling else 1.0,
        "buy_candidate": bool(buy_candidate),
        "sell_candidate": bool(sell_candidate),
        "price_drawdown": float(row["price_drawdown"]),
        "recent_drawdown_min": float(row["recent_drawdown_min"]),
    }

# 新增：动量增强版评估函数
def _evaluate_momentum_ma_atr(
    row: pd.Series,
    signal_config: InvestmentSignalConfig,
    current_target: float,
) -> Dict[str, Any]:
    """阶段2+：动量+MA+ATR 三层确认模型。"""
    # 基础指标
    atr_ratio = float(row["atr_ratio"])
    bullish_cross = bool(row.get("bullish_cross", False))
    bearish_cross = bool(row.get("bearish_cross", False))

    # 动量指标
    momentum_score = float(row.get("momentum_score", 0))
    momentum_participation = momentum_score * signal_config.momentum_weight

    # ===== 阶段4: 52周高点增强 =====
    breakout_boost = 0.0
    if signal_config.enable_52w_high_factor and row.get("is_near_52w_high", False):
        breakout_boost = float(row.get("breakout_momentum", 0))
        momentum_participation += breakout_boost

    # ===== 响应评分（0-1之间）=====
    # 基础得分：MA趋势
    trend_score = 1.0 if bullish_cross else (0.5 if row["ma_fast"] > row["ma_slow"] else 0.0)

    # 动量得分
    momentum_adjusted = max(0, momentum_participation + 0.5)  # 归一化到0-1

    # 综合得分
    composite_score = trend_score * 0.4 + momentum_adjusted * 0.6

    # ===== 阶段1: 波动率缩放 =====
    if signal_config.enable_volatility_scaling:
        vol_scale = float(row.get("vol_scale_factor", 1.0))
    else:
        vol_scale = 1.0

    # ===== ATR过滤 =====
    vol_filter_pass = atr_ratio <= signal_config.buy_volatility_cap

    # ===== 决策 =====
    if composite_score > 0.6 and vol_filter_pass:
        next_target = signal_config.full_position * min(composite_score * vol_scale, 1.0)
        position_reason = f"共振买入(趋势={trend_score:.2f},动量={momentum_adjusted:.2f})"
    elif bearish_cross or momentum_score < -0.05:
        next_target = signal_config.flat_position
        position_reason = "卖出信号"
    else:
        next_target = current_target
        position_reason = "观望"

    return {
        "position_reason": position_reason,
        "next_target": next_target,
        "composite_score": composite_score,
        "atr_ratio": atr_ratio,
        "vol_scale": vol_scale,
        "momentum_score": momentum_score,
        "price_drawdown": float(row["price_drawdown"]),
        "recent_drawdown_min": float(row["recent_drawdown_min"]),
    }


def _resolve_action(previous_target: float, next_target: float) -> str:
    if next_target > previous_target:
        return "buy" if previous_target <= 0.0 else "add"
    if next_target < previous_target:
        return "sell" if next_target <= 0.0 else "reduce"
    return "hold"


def _position_ladder(signal_config: InvestmentSignalConfig) -> list[float]:
    ladder = sorted(
        {
            float(signal_config.flat_position),
            float(signal_config.half_position),
            float(signal_config.full_position),
        }
    )
    return ladder


def _next_ladder_position(current_target: float, signal_config: InvestmentSignalConfig, direction: str) -> float:
    ladder = _position_ladder(signal_config)
    current = float(current_target)
    if direction == "buy":
        for level in ladder:
            if level > current + 1e-8:
                return level
        return ladder[-1]
    for level in reversed(ladder):
        if level < current - 1e-8:
            return level
    return ladder[0]


def _map_single_window_signal(
    result: Optional[Dict[str, Any]],
    current_target: float,
    signal_config: InvestmentSignalConfig,
    lppl_config: LPPLConfig,
) -> Tuple[str, float, str, float]:
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

    phase = classify_top_phase(days_to_crash, r_squared, lppl_config) if b_value <= 0 else "none"
    if phase == "danger":
        return "bubble_risk", r_squared, "高危信号", signal_config.flat_position
    if phase == "warning":
        if not signal_config.warning_trade_enabled:
            return "bubble_warning", r_squared, "观察信号", current_target
        target = min(current_target, signal_config.half_position)
        return "bubble_warning", r_squared, "观察信号", target
    if phase == "watch":
        return "bubble_watch", r_squared, "顶部观察", current_target

    return "none", 0.0, "无信号", current_target


def _map_ensemble_signal(
    result: Optional[Dict[str, Any]],
    current_target: float,
    signal_config: InvestmentSignalConfig,
    lppl_config: LPPLConfig,
) -> Tuple[str, float, str, float]:
    if not result:
        return "none", 0.0, "无信号", current_target

    signal_strength = float(result.get("signal_strength", 0.0))
    positive_consensus = float(result.get("positive_consensus_rate", result.get("consensus_rate", 0.0)))
    negative_consensus = float(result.get("negative_consensus_rate", 0.0))
    positive_days = result.get("predicted_crash_days")
    negative_days = result.get("predicted_rebound_days")

    if negative_days is not None and negative_consensus > positive_consensus:
        negative_days = float(negative_days)
        if negative_days < signal_config.strong_buy_days:
            return "negative_bubble", signal_strength, "Ensemble 抄底共识", signal_config.full_position
        if negative_days < signal_config.buy_days:
            target = max(current_target, signal_config.half_position)
            return "negative_bubble", signal_strength, "Ensemble 抄底共识", target
        return "negative_bubble_watch", signal_strength, "Ensemble 抄底观察", current_target

    if positive_days is not None:
        positive_days = float(positive_days)
        if positive_days < lppl_config.danger_days:
            return "bubble_risk", signal_strength, "Ensemble 高危共识", signal_config.flat_position
        if positive_days < lppl_config.warning_days:
            if not signal_config.warning_trade_enabled:
                return "bubble_warning", signal_strength, "Ensemble 观察信号", current_target
            target = min(current_target, signal_config.half_position)
            return "bubble_warning", signal_strength, "Ensemble 观察信号", target
        if positive_days < lppl_config.watch_days:
            return "bubble_watch", signal_strength, "Ensemble 顶部观察", current_target

    return "none", 0.0, "无信号", current_target


def _state_from_single_window_result(
    result: Optional[Dict[str, Any]],
    lppl_config: LPPLConfig,
) -> ActiveLPPLState:
    if not result:
        return ActiveLPPLState()

    params = result.get("params", ())
    b_value = float(params[4]) if len(params) > 4 else 0.0
    days_to_crash = float(result.get("days_to_crash", 9999.0))
    m_value = float(result.get("m", 0.0))
    w_value = float(result.get("w", 0.0))
    rmse = float(result.get("rmse", 1.0))
    r_squared = float(result.get("r_squared", 0.0))

    is_negative, bottom_signal = detect_negative_bubble(m_value, w_value, b_value, days_to_crash)
    if is_negative:
        return ActiveLPPLState(
            signal_strength=calculate_bottom_signal_strength(m_value, w_value, b_value, rmse),
            reason=bottom_signal,
            negative_consensus=calculate_bottom_signal_strength(m_value, w_value, b_value, rmse),
            negative_days=days_to_crash,
            negative_signal_name="negative_bubble",
        )

    phase = classify_top_phase(days_to_crash, r_squared, lppl_config) if b_value <= 0 else "none"
    if phase in {"watch", "warning", "danger"}:
        signal_name = {
            "watch": "bubble_watch",
            "warning": "bubble_warning",
            "danger": "bubble_risk",
        }[phase]
        return ActiveLPPLState(
            signal_strength=r_squared,
            reason=(
                "高危信号"
                if signal_name == "bubble_risk"
                else ("警告信号" if signal_name == "bubble_warning" else "顶部观察")
            ),
            positive_consensus=r_squared,
            positive_days=days_to_crash,
            positive_signal_name=signal_name,
        )

    return ActiveLPPLState()


def _state_from_ensemble_result(result: Optional[Dict[str, Any]], lppl_config: LPPLConfig) -> ActiveLPPLState:
    if not result:
        return ActiveLPPLState()

    positive_days = (
        float(result["predicted_crash_days"])
        if result.get("predicted_crash_days") is not None
        else None
    )
    positive_confidence = float(result.get("positive_consensus_rate", result.get("consensus_rate", 0.0)))
    positive_phase = (
        classify_top_phase(positive_days, positive_confidence, lppl_config)
        if positive_days is not None
        else "none"
    )

    return ActiveLPPLState(
        signal_strength=float(result.get("signal_strength", 0.0)),
        reason="Ensemble 共识",
        positive_consensus=positive_confidence,
        negative_consensus=float(result.get("negative_consensus_rate", 0.0)),
        positive_days=positive_days,
        negative_days=(
            float(result["predicted_rebound_days"])
            if result.get("predicted_rebound_days") is not None
            else None
        ),
        positive_signal_name={
            "watch": "bubble_watch",
            "warning": "bubble_warning",
            "danger": "bubble_risk",
        }.get(positive_phase, "none"),
        negative_signal_name="negative_bubble",
    )


def _to_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return bool(value)


def _evaluate_multi_factor(
    row: pd.Series,
    state: ActiveLPPLState,
    signal_config: InvestmentSignalConfig,
) -> Dict[str, Any]:
    positive_days = state.effective_positive_days()
    negative_days = state.effective_negative_days()
    positive_signal_name = str(state.positive_signal_name)
    warning_active = positive_signal_name == "bubble_warning"
    positive_lppl = (
        positive_signal_name in {"bubble_warning", "bubble_risk"}
        and (signal_config.warning_trade_enabled or positive_signal_name == "bubble_risk")
        and positive_days is not None
        and positive_days >= 0.0
        and state.positive_consensus >= float(signal_config.positive_consensus_threshold)
    )
    positive_watch = (
        positive_signal_name == "bubble_watch"
        and positive_days is not None
        and positive_days >= 0.0
    ) or (
        warning_active
        and not signal_config.warning_trade_enabled
        and positive_days is not None
        and positive_days >= 0.0
    )
    negative_lppl = (
        negative_days is not None
        and negative_days >= 0.0
        and negative_days <= float(signal_config.rebound_days)
        and state.negative_consensus >= float(signal_config.negative_consensus_threshold)
    )

    close_price = float(row["close"])
    ma_fast = float(row["ma_fast"])
    ma_slow = float(row["ma_slow"])
    fast_slope = float(row["ma_fast_slope"])
    atr_ratio = float(row["atr_ratio"])
    price_drawdown = float(row["price_drawdown"])
    recent_drawdown_min = float(row.get("recent_drawdown_min", price_drawdown))

    slow_gap = close_price / ma_slow if ma_slow > 0 else 1.0
    trend_buy = slow_gap >= float(signal_config.buy_trend_slow_buffer) and fast_slope > 0.0
    if signal_config.require_trend_recovery_for_buy:
        trend_buy = trend_buy and close_price > ma_fast
    trend_sell = close_price < ma_slow and fast_slope < 0.0

    vol_sell = atr_ratio >= float(signal_config.vol_breakout_mult)
    vol_position_cap = float(signal_config.full_position)
    if atr_ratio >= float(signal_config.high_volatility_mult):
        vol_position_cap = min(vol_position_cap, float(signal_config.high_volatility_position_cap))

    drawdown_sell = price_drawdown <= -float(signal_config.drawdown_confirm_threshold)
    drawdown_buy = (
        recent_drawdown_min <= -float(signal_config.buy_reentry_drawdown_threshold)
        and close_price > ma_fast
        and fast_slope > 0.0
    )

    sell_votes = int(positive_lppl) + int(trend_sell) + int(vol_sell) + int(drawdown_sell)
    buy_votes = int(negative_lppl) + int(trend_buy) + int(drawdown_buy)

    sell_candidate = positive_lppl and sell_votes >= int(signal_config.sell_vote_threshold)
    buy_candidate = negative_lppl and buy_votes >= int(signal_config.buy_vote_threshold)

    if sell_candidate and buy_candidate:
        if state.positive_consensus >= state.negative_consensus:
            buy_candidate = False
        else:
            sell_candidate = False

    lppl_signal = "none"
    position_reason = "无信号"
    signal_strength = 0.0
    if sell_candidate:
        lppl_signal = state.positive_signal_name
        signal_strength = max(state.signal_strength, state.positive_consensus)
        position_reason = f"LPPL顶部+{sell_votes}票确认"
    elif buy_candidate:
        lppl_signal = state.negative_signal_name
        signal_strength = max(state.signal_strength, state.negative_consensus)
        position_reason = f"LPPL底部+{buy_votes}票确认"
    elif positive_lppl or positive_watch:
        lppl_signal = state.positive_signal_name
        signal_strength = max(state.signal_strength, state.positive_consensus)
        if positive_watch:
            position_reason = "LPPL顶部观察"
        else:
            position_reason = f"LPPL顶部待确认({sell_votes}票)"
    elif negative_lppl:
        lppl_signal = state.negative_signal_name
        signal_strength = max(state.signal_strength, state.negative_consensus)
        position_reason = f"LPPL底部待确认({buy_votes}票)"

    return {
        "lppl_signal": lppl_signal,
        "signal_strength": float(signal_strength),
        "position_reason": position_reason,
        "lppl_vote": int(positive_lppl or negative_lppl),
        "positive_lppl_vote": int(positive_lppl),
        "negative_lppl_vote": int(negative_lppl),
        "trend_buy_vote": int(trend_buy),
        "trend_sell_vote": int(trend_sell),
        "vol_buy_vote": int(atr_ratio <= float(signal_config.buy_volatility_cap)),
        "vol_sell_vote": int(vol_sell),
        "drawdown_buy_vote": int(drawdown_buy),
        "drawdown_sell_vote": int(drawdown_sell),
        "buy_votes": int(buy_votes),
        "sell_votes": int(sell_votes),
        "buy_candidate": bool(buy_candidate),
        "sell_candidate": bool(sell_candidate),
        "atr_ratio": atr_ratio,
        "price_drawdown": price_drawdown,
        "recent_drawdown_min": recent_drawdown_min,
        "vol_position_cap": float(vol_position_cap),
        "positive_days_left": positive_days,
        "negative_days_left": negative_days,
        "positive_consensus": float(state.positive_consensus),
        "negative_consensus": float(state.negative_consensus),
        "positive_signal_name": positive_signal_name,
    }


def generate_investment_signals(
    df: pd.DataFrame,
    symbol: str,
    signal_config: Optional[InvestmentSignalConfig] = None,
    lppl_config: Optional[LPPLConfig] = None,
    use_ensemble: bool = False,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    scan_step: int = 1,
) -> pd.DataFrame:
    signal_config = signal_config or InvestmentSignalConfig.for_symbol(symbol)
    lppl_config = lppl_config or LPPLConfig(window_range=[40, 60, 80], n_workers=1)
    price_df = _compute_indicators(_normalize_price_frame(df), signal_config)
    scan_step = max(1, int(scan_step))

    start_ts = pd.to_datetime(start_date) if start_date else price_df["date"].min()
    end_ts = pd.to_datetime(end_date) if end_date else price_df["date"].max()
    output_mask = (price_df["date"] >= start_ts) & (price_df["date"] <= end_ts)

    current_target = float(signal_config.initial_position)
    records = []
    close_prices = price_df["close"].values
    warmup = max(lppl_config.window_range)
    scan_counter = 0
    active_state = ActiveLPPLState()
    buy_streak = 0
    sell_streak = 0
    cooldown_remaining = 0
    buy_reentry_block_remaining = 0
    holding_bars = 0
    positive_regime_id = 0
    negative_regime_id = 0
    prev_positive_lppl = False
    prev_negative_lppl = False
    traded_positive_regime_id: Optional[int] = None
    traded_positive_regime_rank: int = 0
    traded_negative_regime_id: Optional[int] = None

    for idx, row in price_df.iterrows():
        # 纯 MA 交叉 + ATR 模型：跳过 LPPL 扫描
        if signal_config.signal_model == "ma_cross_atr_v1":
            if not output_mask.iloc[idx]:
                continue
            indicator_warmup = max(
                signal_config.trend_slow_ma,
                signal_config.atr_period + signal_config.atr_ma_window - 1
            ) - 1
            if idx < indicator_warmup:
                records.append({
                    "date": row["date"],
                    "symbol": symbol,
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": float(row["volume"]),
                    "lppl_signal": "none",
                    "signal_strength": 0.0,
                    "position_reason": "指标预热",
                    "action": "hold",
                    "target_position": float(current_target),
                    "atr_ratio": float(row["atr_ratio"]),
                    "price_drawdown": float(row["price_drawdown"]),
                    "recent_drawdown_min": float(row["recent_drawdown_min"]),
                })
                continue
            factor_state = _evaluate_ma_cross_atr(row, signal_config, current_target)
            next_target = float(factor_state["next_target"])
            action = _resolve_action(current_target, next_target)
            current_target = next_target
            records.append({
                "date": row["date"],
                "symbol": symbol,
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": float(row["volume"]),
                "lppl_signal": "none",
                "signal_strength": 0.0,
                "position_reason": factor_state["position_reason"],
                "action": action,
                "target_position": float(current_target),
                "atr_ratio": factor_state["atr_ratio"],
                "price_drawdown": factor_state["price_drawdown"],
                "recent_drawdown_min": factor_state["recent_drawdown_min"],
            })
            continue

        scan_result: Optional[Dict[str, Any]] = None
        if idx >= warmup and scan_counter % scan_step == 0:
            if use_ensemble:
                scan_result = process_single_day_ensemble(
                    close_prices,
                    idx,
                    lppl_config.window_range,
                    min_r2=lppl_config.r2_threshold,
                    consensus_threshold=lppl_config.consensus_threshold,
                    config=lppl_config,
                )
                active_state = _state_from_ensemble_result(scan_result, lppl_config)
            else:
                scan_result = scan_single_date(close_prices, idx, lppl_config.window_range, lppl_config)
                active_state = _state_from_single_window_result(scan_result, lppl_config)
        if idx >= warmup:
            scan_counter += 1

        if not output_mask.iloc[idx]:
            if idx >= warmup:
                active_state.advance()
            continue

        if signal_config.signal_model == "legacy":
            if idx >= warmup:
                if use_ensemble:
                    lppl_signal, signal_strength, position_reason, next_target = _map_ensemble_signal(
                        scan_result,
                        current_target,
                        signal_config,
                        lppl_config,
                    )
                else:
                    lppl_signal, signal_strength, position_reason, next_target = _map_single_window_signal(
                        scan_result,
                        current_target,
                        signal_config,
                        lppl_config,
                    )
            else:
                lppl_signal, signal_strength, position_reason, next_target = ("none", 0.0, "无信号", current_target)

            action = _resolve_action(current_target, next_target)
            current_target = next_target
            records.append(
                {
                    "date": row["date"],
                    "symbol": symbol,
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": float(row["volume"]),
                    "lppl_signal": lppl_signal,
                    "signal_strength": float(signal_strength),
                    "position_reason": position_reason,
                    "action": action,
                    "target_position": float(current_target),
                }
            )
            if idx >= warmup:
                active_state.advance()
            continue

        if signal_config.signal_model == "ma_cross_atr_lppl_v1":
            factor_state = _evaluate_ma_cross_atr_lppl(row, active_state, signal_config, current_target)
            next_target = float(factor_state["next_target"])
            action = _resolve_action(current_target, next_target)
            current_target = next_target
            record = {
                "date": row["date"],
                "symbol": symbol,
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": float(row["volume"]),
                "lppl_signal": factor_state["lppl_signal"],
                "signal_strength": factor_state["signal_strength"],
                "position_reason": factor_state["position_reason"],
                "action": action,
                "target_position": float(current_target),
                "lppl_vote": factor_state["lppl_vote"],
                "positive_lppl_vote": factor_state["positive_lppl_vote"],
                "negative_lppl_vote": factor_state["negative_lppl_vote"],
                "trend_buy_vote": factor_state["trend_buy_vote"],
                "trend_sell_vote": factor_state["trend_sell_vote"],
                "vol_buy_vote": factor_state["vol_buy_vote"],
                "vol_sell_vote": factor_state["vol_sell_vote"],
                "drawdown_buy_vote": factor_state["drawdown_buy_vote"],
                "drawdown_sell_vote": factor_state["drawdown_sell_vote"],
                "buy_votes": factor_state["buy_votes"],
                "sell_votes": factor_state["sell_votes"],
                "buy_streak": 0,
                "sell_streak": 0,
                "cooldown_remaining": 0,
                "buy_reentry_block_remaining": 0,
                "holding_bars": 0,
                "positive_regime_id": 0,
                "negative_regime_id": 0,
                "atr_ratio": factor_state["atr_ratio"],
                "price_drawdown": factor_state["price_drawdown"],
                "recent_drawdown_min": factor_state["recent_drawdown_min"],
                "vol_position_cap": factor_state["vol_position_cap"],
                "positive_days_left": factor_state["positive_days_left"],
                "negative_days_left": factor_state["negative_days_left"],
                "positive_consensus": factor_state["positive_consensus"],
                "negative_consensus": factor_state["negative_consensus"],
            }
            records.append(record)
            if idx >= warmup:
                active_state.advance()
            continue

        factor_state = _evaluate_multi_factor(row, active_state, signal_config)
        positive_lppl_active = bool(factor_state["positive_lppl_vote"])
        negative_lppl_active = bool(factor_state["negative_lppl_vote"])
        if positive_lppl_active and not prev_positive_lppl:
            positive_regime_id += 1
        if negative_lppl_active and not prev_negative_lppl:
            negative_regime_id += 1
        current_positive_regime_id = positive_regime_id if positive_lppl_active else 0
        current_negative_regime_id = negative_regime_id if negative_lppl_active else 0
        current_positive_phase_rank = _positive_phase_rank(str(factor_state["positive_signal_name"]))
        buy_position_cap = min(float(signal_config.full_position), float(factor_state["vol_position_cap"]))
        buy_candidate = (
            factor_state["buy_candidate"]
            and buy_reentry_block_remaining <= 0
            and current_target < buy_position_cap - 1e-8
        )
        sell_candidate = factor_state["sell_candidate"] and current_target > signal_config.flat_position + 1e-8

        if signal_config.enable_regime_hysteresis:
            if (
                buy_candidate
                and current_negative_regime_id > 0
                and traded_negative_regime_id == current_negative_regime_id
            ):
                buy_candidate = False
            if (
                sell_candidate
                and current_positive_regime_id > 0
                and traded_positive_regime_id == current_positive_regime_id
                and current_positive_phase_rank <= traded_positive_regime_rank
            ):
                sell_candidate = False

        if sell_candidate and holding_bars < signal_config.min_hold_bars:
            top_risk_override = (
                signal_config.allow_top_risk_override_min_hold
                and str(factor_state["lppl_signal"]) == "bubble_risk"
            )
            if not top_risk_override:
                sell_candidate = False

        if cooldown_remaining > 0:
            buy_streak = 0
            sell_streak = 0
        else:
            if buy_candidate:
                buy_streak += 1
            else:
                buy_streak = 0
            if sell_candidate:
                sell_streak += 1
            else:
                sell_streak = 0

        next_target = current_target
        if cooldown_remaining <= 0:
            if sell_candidate and sell_streak >= signal_config.sell_confirm_days:
                next_target = _next_ladder_position(current_target, signal_config, "sell")
                sell_streak = 0
                buy_streak = 0
                cooldown_remaining = signal_config.cooldown_days
            elif buy_candidate and buy_streak >= signal_config.buy_confirm_days:
                next_target = min(
                    _next_ladder_position(current_target, signal_config, "buy"),
                    buy_position_cap,
                )
                sell_streak = 0
                buy_streak = 0
                cooldown_remaining = signal_config.cooldown_days

        action = _resolve_action(current_target, next_target)
        current_target = next_target
        if action in {"sell", "reduce"}:
            buy_reentry_block_remaining = signal_config.post_sell_reentry_cooldown_days
            if current_positive_regime_id > 0:
                traded_positive_regime_id = current_positive_regime_id
                traded_positive_regime_rank = current_positive_phase_rank
        if action in {"buy", "add"} and current_negative_regime_id > 0:
            traded_negative_regime_id = current_negative_regime_id
        record = {
            "date": row["date"],
            "symbol": symbol,
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "volume": float(row["volume"]),
            "lppl_signal": factor_state["lppl_signal"],
            "signal_strength": factor_state["signal_strength"],
            "position_reason": factor_state["position_reason"],
            "action": action,
            "target_position": float(current_target),
            "lppl_vote": factor_state["lppl_vote"],
            "positive_lppl_vote": factor_state["positive_lppl_vote"],
            "negative_lppl_vote": factor_state["negative_lppl_vote"],
            "trend_buy_vote": factor_state["trend_buy_vote"],
            "trend_sell_vote": factor_state["trend_sell_vote"],
            "vol_buy_vote": factor_state["vol_buy_vote"],
            "vol_sell_vote": factor_state["vol_sell_vote"],
            "drawdown_buy_vote": factor_state["drawdown_buy_vote"],
            "drawdown_sell_vote": factor_state["drawdown_sell_vote"],
            "buy_votes": factor_state["buy_votes"],
            "sell_votes": factor_state["sell_votes"],
            "buy_streak": buy_streak,
            "sell_streak": sell_streak,
            "cooldown_remaining": max(cooldown_remaining, 0),
            "buy_reentry_block_remaining": max(buy_reentry_block_remaining, 0),
            "holding_bars": int(holding_bars),
            "positive_regime_id": int(current_positive_regime_id),
            "negative_regime_id": int(current_negative_regime_id),
            "atr_ratio": factor_state["atr_ratio"],
            "price_drawdown": factor_state["price_drawdown"],
            "recent_drawdown_min": factor_state["recent_drawdown_min"],
            "vol_position_cap": factor_state["vol_position_cap"],
            "positive_days_left": factor_state["positive_days_left"],
            "negative_days_left": factor_state["negative_days_left"],
            "positive_consensus": factor_state["positive_consensus"],
            "negative_consensus": factor_state["negative_consensus"],
        }
        records.append(record)

        if cooldown_remaining > 0:
            cooldown_remaining -= 1
        if buy_reentry_block_remaining > 0 and action not in {"sell", "reduce"}:
            buy_reentry_block_remaining -= 1
        if action in {"buy", "add"}:
            holding_bars = 0
        elif current_target > signal_config.flat_position + 1e-8:
            holding_bars += 1
        else:
            holding_bars = 0
        prev_positive_lppl = positive_lppl_active
        prev_negative_lppl = negative_lppl_active
        if idx >= warmup:
            active_state.advance()

    return pd.DataFrame(records)


def calculate_drawdown(nav_series: pd.Series) -> pd.DataFrame:
    nav = pd.Series(nav_series, copy=True).astype(float).reset_index(drop=True)
    running_max = nav.cummax()
    drawdown = (nav / running_max) - 1.0
    return pd.DataFrame(
        {
            "strategy_nav": nav,
            "running_max": running_max,
            "drawdown": drawdown,
        }
    )


def _calculate_turnover_rate(trades_df: pd.DataFrame, initial_capital: float) -> float:
    if trades_df.empty or initial_capital <= 0:
        return 0.0
    notional = (trades_df["price"].astype(float) * trades_df["units"].astype(float)).sum()
    return float(notional / initial_capital)


def _calculate_whipsaw_rate(trades_df: pd.DataFrame, holding_days_threshold: int = 10) -> float:
    if len(trades_df) < 2:
        return 0.0

    whipsaws = 0
    round_trips = 0
    open_trade_date: Optional[pd.Timestamp] = None

    for row in trades_df.to_dict("records"):
        trade_type = str(row["trade_type"])
        trade_date = pd.Timestamp(row["date"])
        if trade_type in {"buy", "add"} and open_trade_date is None:
            open_trade_date = trade_date
        elif trade_type in {"sell", "reduce"} and open_trade_date is not None:
            round_trips += 1
            if (trade_date - open_trade_date).days <= holding_days_threshold:
                whipsaws += 1
            open_trade_date = None

    return float(whipsaws / round_trips) if round_trips > 0 else 0.0


def summarize_strategy_performance(equity_df: pd.DataFrame, trades_df: pd.DataFrame) -> Dict[str, Any]:
    if equity_df.empty:
        return {
            "final_nav": 1.0,
            "total_return": 0.0,
            "benchmark_return": 0.0,
            "annualized_return": 0.0,
            "annualized_excess_return": 0.0,
            "calmar_ratio": 0.0,
            "max_drawdown": 0.0,
            "trade_count": 0,
            "signal_count": 0,
            "average_position": 0.0,
            "turnover_rate": 0.0,
            "whipsaw_rate": 0.0,
            "latest_action": "hold",
            "latest_signal": "none",
        }

    final_nav = float(equity_df["strategy_nav"].iloc[-1])
    total_return = final_nav - 1.0
    benchmark_nav = float(equity_df["benchmark_nav"].iloc[-1])
    benchmark_return = benchmark_nav - 1.0

    # 使用交易日数计算年化因子（A股约252个交易日/年）
    # equity_df 已按交易日排列，行数即为交易日数
    periods = max(len(equity_df), 1)
    annualized_return = (final_nav ** (252.0 / periods) - 1.0) if final_nav > 0 else -1.0
    benchmark_annualized_return = (benchmark_nav ** (252.0 / periods) - 1.0) if benchmark_nav > 0 else -1.0
    annualized_excess_return = annualized_return - benchmark_annualized_return
    max_drawdown = float(equity_df["drawdown"].min())
    signal_count = int((equity_df["action"] != "hold").sum())
    turnover_rate = _calculate_turnover_rate(trades_df, float(equity_df["portfolio_value"].iloc[0]))
    whipsaw_rate = _calculate_whipsaw_rate(trades_df)
    calmar_ratio = 0.0
    if max_drawdown < 0:
        calmar_ratio = annualized_excess_return / abs(max_drawdown)
    elif annualized_excess_return > 0:
        calmar_ratio = annualized_excess_return
    elif annualized_excess_return < 0:
        calmar_ratio = annualized_excess_return

    return {
        "final_nav": final_nav,
        "total_return": total_return,
        "benchmark_return": benchmark_return,
        "annualized_return": annualized_return,
        "annualized_excess_return": annualized_excess_return,
        "calmar_ratio": calmar_ratio,
        "max_drawdown": max_drawdown,
        "trade_count": int(len(trades_df)),
        "signal_count": signal_count,
        "average_position": float(equity_df["executed_position"].mean()),
        "turnover_rate": turnover_rate,
        "whipsaw_rate": whipsaw_rate,
        "latest_action": str(equity_df["action"].iloc[-1]),
        "latest_signal": str(equity_df["lppl_signal"].iloc[-1]),
    }


def run_strategy_backtest(
    signal_df: pd.DataFrame,
    backtest_config: Optional[BacktestConfig] = None,
) -> Tuple[pd.DataFrame, pd.DataFrame, Dict[str, Any]]:
    backtest_config = backtest_config or BacktestConfig()
    equity_df = _normalize_price_frame(signal_df)

    if backtest_config.start_date:
        equity_df = equity_df[equity_df["date"] >= pd.to_datetime(backtest_config.start_date)]
    if backtest_config.end_date:
        equity_df = equity_df[equity_df["date"] <= pd.to_datetime(backtest_config.end_date)]
    equity_df = equity_df.reset_index(drop=True)

    if equity_df.empty:
        raise ValueError("No data available for the requested backtest window")

    cash = float(backtest_config.initial_capital)
    units = 0.0
    prev_value = float(backtest_config.initial_capital)
    prev_close = float(equity_df.iloc[0]["close"])
    first_close = float(equity_df.iloc[0]["close"])

    trades = []
    records = []

    for row in equity_df.to_dict("records"):
        execution_base_price = float(row["open"] if backtest_config.execution_price == "open" else row["close"])
        execution_buy_price = execution_base_price * (1.0 + backtest_config.slippage)
        execution_sell_price = execution_base_price * (1.0 - backtest_config.slippage)
        target_position = float(row.get("target_position", 0.0))
        signal_action = str(row.get("action", "hold"))

        portfolio_value_before_trade = cash + units * execution_base_price
        current_holdings_value = units * execution_base_price
        desired_holdings_value = current_holdings_value
        if signal_action != "hold":
            desired_holdings_value = portfolio_value_before_trade * target_position

        trade_type = "hold"
        if signal_action != "hold" and desired_holdings_value > current_holdings_value + 1e-8:
            trade_value = desired_holdings_value - current_holdings_value
            affordable_units = cash / (execution_buy_price * (1.0 + backtest_config.buy_fee))
            desired_units = trade_value / execution_buy_price
            units_to_buy = min(affordable_units, desired_units)
            if units_to_buy > 1e-8:
                gross_cost = units_to_buy * execution_buy_price
                fee = gross_cost * backtest_config.buy_fee
                cash -= gross_cost + fee
                units += units_to_buy
                trade_type = "buy" if current_holdings_value <= 1e-8 else "add"
                trades.append(
                    {
                        "date": row["date"],
                        "symbol": row.get("symbol", ""),
                        "trade_type": trade_type,
                        "price": execution_buy_price,
                        "target_position": target_position,
                        "executed_position": 0.0,
                        "units": units_to_buy,
                        "cash_after_trade": cash,
                        "holdings_value_after_trade": units * execution_base_price,
                        "portfolio_value_after_trade": cash + units * execution_base_price,
                    }
                )
        elif signal_action != "hold" and desired_holdings_value < current_holdings_value - 1e-8:
            trade_value = current_holdings_value - desired_holdings_value
            units_to_sell = min(units, trade_value / execution_sell_price)
            if units_to_sell > 1e-8:
                gross_proceeds = units_to_sell * execution_sell_price
                fee = gross_proceeds * backtest_config.sell_fee
                cash += gross_proceeds - fee
                units -= units_to_sell
                trade_type = "sell" if target_position <= 1e-8 else "reduce"
                trades.append(
                    {
                        "date": row["date"],
                        "symbol": row.get("symbol", ""),
                        "trade_type": trade_type,
                        "price": execution_sell_price,
                        "target_position": target_position,
                        "executed_position": 0.0,
                        "units": units_to_sell,
                        "cash_after_trade": cash,
                        "holdings_value_after_trade": units * execution_base_price,
                        "portfolio_value_after_trade": cash + units * execution_base_price,
                    }
                )

        holdings_value = units * float(row["close"])
        portfolio_value = cash + holdings_value
        strategy_nav = portfolio_value / backtest_config.initial_capital
        benchmark_nav = float(row["close"]) / first_close
        daily_return = (portfolio_value / backtest_config.initial_capital) - 1.0 if not records else (portfolio_value / prev_value) - 1.0
        benchmark_return = (float(row["close"]) / first_close) - 1.0 if not records else (float(row["close"]) / prev_close) - 1.0
        executed_position = (holdings_value / portfolio_value) if portfolio_value > 0 else 0.0

        if trades and pd.Timestamp(trades[-1]["date"]) == pd.Timestamp(row["date"]):
            trades[-1]["executed_position"] = executed_position

        records.append(
            {
                **row,
                "executed_position": executed_position,
                "cash": cash,
                "units": units,
                "holdings_value": holdings_value,
                "portfolio_value": portfolio_value,
                "strategy_nav": strategy_nav,
                "benchmark_nav": benchmark_nav,
                "daily_return": daily_return,
                "benchmark_return": benchmark_return,
                "excess_return": daily_return - benchmark_return,
                "trade_flag": trade_type != "hold",
            }
        )

        prev_value = portfolio_value
        prev_close = float(row["close"])

    result_df = pd.DataFrame(records)
    drawdown_df = calculate_drawdown(result_df["strategy_nav"])
    result_df["running_max"] = drawdown_df["running_max"]
    result_df["drawdown"] = drawdown_df["drawdown"]

    trades_df = pd.DataFrame(
        trades,
        columns=[
            "date",
            "symbol",
            "trade_type",
            "price",
            "target_position",
            "units",
            "cash_after_trade",
            "holdings_value_after_trade",
            "portfolio_value_after_trade",
            "executed_position",
        ],
    )
    summary = summarize_strategy_performance(result_df, trades_df)
    summary["start_date"] = result_df.iloc[0]["date"].strftime("%Y-%m-%d")
    summary["end_date"] = result_df.iloc[-1]["date"].strftime("%Y-%m-%d")
    summary["symbol"] = str(result_df.iloc[0].get("symbol", ""))

    return result_df, trades_df, summary
