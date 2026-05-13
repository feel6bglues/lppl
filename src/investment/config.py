# -*- coding: utf-8 -*-
"""Investment configuration dataclasses."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class InvestmentSignalConfig:
    """Configuration for investment signal generation.

    Supports multiple signal models:
    - legacy: LPPL-based single-window signals
    - multi_factor_adaptive_v1: Weighted multi-factor scoring system
    """

    # Position sizing
    full_position: float = 1.0
    half_position: float = 0.5
    flat_position: float = 0.0
    initial_position: float = 0.0

    # LPPL signal thresholds
    strong_buy_days: int = 20
    buy_days: int = 40
    strong_sell_days: int = 20
    reduce_days: int = 60
    # NOTE: danger_days / warning_days / watch_days 与 src.lppl_engine.LPPLConfig 重复。
    # 实际风险判断已通过 lppl_config 传入，此处字段为历史遗留，仅供向后兼容。
    danger_days: int = 5
    watch_days: int = 25
    warning_days: int = 12

    # Signal model selection
    signal_model: str = "legacy"
    warning_trade_enabled: bool = True

    # Moving average parameters
    ma_short: int = 10
    ma_mid: int = 30
    ma_long: int = 60

    # ATR parameters
    atr_period: int = 14
    atr_ma_window: int = 40
    atr_low_threshold: float = 0.95
    atr_high_threshold: float = 1.15

    # Bollinger Band parameters
    bb_period: int = 20
    bb_std: float = 2.0
    bb_narrow_threshold: float = 0.05
    bb_wide_threshold: float = 0.10

    # Trend filter
    regime_filter_ma: int = 120
    regime_filter_buffer: float = 1.0
    regime_filter_reduce_enabled: bool = True

    # Risk management
    risk_drawdown_stop_threshold: float = 0.15
    risk_drawdown_lookback: int = 120

    # Trade suppression
    buy_confirm_days: int = 2
    sell_confirm_days: int = 2
    cooldown_days: int = 10
    min_hold_bars: int = 0

    # Multi-factor scoring thresholds
    buy_score_threshold: float = 0.3
    sell_score_threshold: float = -0.3

    # Multi-factor weights
    trend_weight: float = 0.40
    volatility_weight: float = 0.30
    market_state_weight: float = 0.20
    momentum_weight: float = 0.10


@dataclass
class BacktestConfig:
    """Configuration for strategy backtesting."""

    initial_capital: float = 1_000_000.0
    buy_fee: float = 0.0003
    sell_fee: float = 0.0003
    slippage: float = 0.0005
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    execution_price: str = "open"
