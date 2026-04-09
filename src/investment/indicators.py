# -*- coding: utf-8 -*-
"""Technical indicator computation for investment strategies."""
from __future__ import annotations

import pandas as pd

from .config import InvestmentSignalConfig


def normalize_price_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize price DataFrame to standard format.

    Ensures all required columns exist and are properly typed.
    """
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


def compute_indicators(
    df: pd.DataFrame,
    config: InvestmentSignalConfig,
) -> pd.DataFrame:
    """Compute technical indicators for signal generation.

    Calculates:
    - Moving averages (short, mid, long, regime)
    - MA crossover signals
    - ATR and ATR ratio
    - Bollinger Bands and width
    - Risk drawdown
    """
    enriched = df.copy()

    # Moving averages
    enriched["ma_short"] = enriched["close"].rolling(config.ma_short, min_periods=1).mean()
    enriched["ma_mid"] = enriched["close"].rolling(config.ma_mid, min_periods=1).mean()
    enriched["ma_long"] = enriched["close"].rolling(config.ma_long, min_periods=1).mean()
    enriched["ma_regime"] = enriched["close"].rolling(config.regime_filter_ma, min_periods=1).mean()

    # MA crossover signals
    enriched["ma_short_prev"] = enriched["ma_short"].shift(1)
    enriched["ma_mid_prev"] = enriched["ma_mid"].shift(1)
    enriched["bullish_cross"] = (
        (enriched["ma_short"] > enriched["ma_mid"])
        & (
            enriched["ma_short_prev"].fillna(enriched["ma_short"])
            <= enriched["ma_mid_prev"].fillna(enriched["ma_mid"])
        )
    )
    enriched["bearish_cross"] = (
        (enriched["ma_short"] < enriched["ma_mid"])
        & (
            enriched["ma_short_prev"].fillna(enriched["ma_short"])
            >= enriched["ma_mid_prev"].fillna(enriched["ma_mid"])
        )
    )

    # ATR (Average True Range)
    prev_close = enriched["close"].shift(1).fillna(enriched["close"])
    true_range = pd.concat(
        [
            (enriched["high"] - enriched["low"]).abs(),
            (enriched["high"] - prev_close).abs(),
            (enriched["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    enriched["atr"] = true_range.rolling(config.atr_period, min_periods=1).mean()
    enriched["atr_ma"] = enriched["atr"].rolling(config.atr_ma_window, min_periods=1).mean()
    enriched["atr_ratio"] = (enriched["atr"] / enriched["atr_ma"].replace(0.0, pd.NA)).fillna(1.0)

    # Bollinger Bands
    enriched["bb_middle"] = enriched["close"].rolling(config.bb_period, min_periods=1).mean()
    enriched["bb_std_dev"] = enriched["close"].rolling(config.bb_period, min_periods=1).std().fillna(0.0)
    enriched["bb_upper"] = enriched["bb_middle"] + config.bb_std * enriched["bb_std_dev"]
    enriched["bb_lower"] = enriched["bb_middle"] - config.bb_std * enriched["bb_std_dev"]
    enriched["bb_width"] = (
        (enriched["bb_upper"] - enriched["bb_lower"]) / enriched["bb_middle"].replace(0.0, pd.NA)
    ).fillna(0.0)

    # Risk drawdown
    enriched["risk_rolling_peak"] = enriched["close"].rolling(
        config.risk_drawdown_lookback, min_periods=1
    ).max()
    enriched["risk_price_drawdown"] = (enriched["close"] / enriched["risk_rolling_peak"]) - 1.0

    return enriched
