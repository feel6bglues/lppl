# -*- coding: utf-8 -*-
"""
三层LPPL系统 Layer 3: 市场环境检测

基于回测年份分析: 牛市信号误报率高，熊市信号准确率高
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict

import numpy as np
import pandas as pd


@dataclass
class RegimeConfig:
    trend_ma_periods: list = field(default_factory=lambda: [60, 120, 250])
    vol_lookback: int = 20
    vol_high_threshold: float = 0.30
    vol_low_threshold: float = 0.10
    breadth_high_threshold: float = 0.01


DEFAULT_REGIME_CONFIG = RegimeConfig()

REGIME_PARAMS = {
    "strong_bull": {
        "signal_adjustment": 0.7,
        "rr_multiplier": 0.8,
        "position_scale": 1.2,
        "description": "强牛市: 信号打7折",
    },
    "weak_bull": {
        "signal_adjustment": 0.9,
        "rr_multiplier": 0.9,
        "position_scale": 1.0,
        "description": "弱牛市: 轻度调整",
    },
    "range": {
        "signal_adjustment": 1.0,
        "rr_multiplier": 1.0,
        "position_scale": 0.8,
        "description": "震荡市: 不调整",
    },
    "weak_bear": {
        "signal_adjustment": 1.2,
        "rr_multiplier": 1.1,
        "position_scale": 0.6,
        "description": "弱熊市: 信号增强",
    },
    "strong_bear": {
        "signal_adjustment": 1.5,
        "rr_multiplier": 1.3,
        "position_scale": 0.3,
        "description": "强熊市: 信号最强",
    },
}


class MarketRegimeDetector:

    def __init__(self, config: RegimeConfig | None = None):
        self.config = config or DEFAULT_REGIME_CONFIG

    def detect(
        self,
        index_df: pd.DataFrame,
        individual_danger_rate: float = 0.0,
    ) -> Dict:
        if index_df is None or len(index_df) < max(self.config.trend_ma_periods):
            return {
                "regime": "unknown",
                "params": REGIME_PARAMS["range"],
                "trend_up": False,
                "trend_down": False,
                "vol": 0.0,
                "vol_high": False,
                "individual_danger_rate": individual_danger_rate,
                "ma_values": {},
            }

        close = index_df["close"].values.astype(float)

        mas = {}
        for p in self.config.trend_ma_periods:
            if len(close) >= p:
                mas[p] = float(np.mean(close[-p:]))
            else:
                mas[p] = float(close[-1])

        current = float(close[-1])

        if all(p in mas for p in [60, 120, 250]):
            trend_up = current > mas[60] > mas[120] > mas[250]
            trend_down = current < mas[60] < mas[120] < mas[250]
        else:
            trend_up = False
            trend_down = False

        if len(close) >= self.config.vol_lookback + 1:
            recent = close[-(self.config.vol_lookback + 1):]
            returns = np.diff(recent) / recent[:-1]
            returns = returns[np.isfinite(returns)]
            vol = float(np.std(returns) * np.sqrt(252)) if len(returns) > 0 else 0.0
        else:
            vol = 0.0

        vol_high = vol > self.config.vol_high_threshold
        breadth_high = individual_danger_rate > self.config.breadth_high_threshold

        if trend_up and not vol_high and breadth_high:
            regime = "strong_bull"
        elif trend_up and not vol_high:
            regime = "weak_bull"
        elif trend_down and vol_high:
            regime = "strong_bear"
        elif trend_down:
            regime = "weak_bear"
        else:
            regime = "range"

        return {
            "regime": regime,
            "params": REGIME_PARAMS[regime],
            "trend_up": trend_up,
            "trend_down": trend_down,
            "vol": round(vol, 4),
            "vol_high": vol_high,
            "individual_danger_rate": individual_danger_rate,
            "ma_values": {k: round(v, 2) for k, v in mas.items()},
        }
