# -*- coding: utf-8 -*-
"""
三层LPPL系统 Layer 2: 信号聚类检测

基于回测发现: 30天内danger信号≥3次几乎100%对应真实顶部
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Dict, List

import numpy as np
import pandas as pd


@dataclass
class ClusterConfig:
    window_days: int = 30
    strong_threshold: int = 5
    moderate_threshold: int = 3
    weak_threshold: int = 1
    decay_halflife_days: int = 15
    stability_threshold: float = 0.15


DEFAULT_CLUSTER_CONFIG = ClusterConfig()


class SignalClusterDetector:

    def __init__(self, config: ClusterConfig | None = None):
        self.config = config or DEFAULT_CLUSTER_CONFIG
        self.signal_history: deque = deque(maxlen=365)

    def add_signal(self, date_str: str, signal_result: Dict):
        layers = signal_result.get("layers", {})
        medium_m = layers.get("medium", {}).get("m", 0)
        self.signal_history.append({
            "date": date_str,
            "score": signal_result.get("final_score", 0),
            "level": signal_result.get("level", "none"),
            "is_danger": signal_result.get("level") == "danger",
            "is_warning": signal_result.get("level") in ("danger", "warning"),
            "medium_m": medium_m,
            "n_danger": signal_result.get("n_danger", 0),
        })

    def detect_cluster(self, current_date_str: str) -> Dict:
        current_date = pd.Timestamp(current_date_str)
        window_start = current_date - pd.Timedelta(days=self.config.window_days)

        window_signals = [
            s for s in self.signal_history
            if pd.Timestamp(s["date"]) >= window_start
            and pd.Timestamp(s["date"]) <= current_date
        ]

        danger_signals = [s for s in window_signals if s["is_danger"]]
        warning_signals = [s for s in window_signals if s["is_warning"]]

        raw_danger_count = len(danger_signals)
        raw_warning_count = len(warning_signals)

        weighted_danger = 0.0
        for s in danger_signals:
            days_ago = (current_date - pd.Timestamp(s["date"])).days
            decay = 0.5 ** (days_ago / self.config.decay_halflife_days)
            weighted_danger += decay * s["score"]

        weighted_warning = 0.0
        for s in warning_signals:
            days_ago = (current_date - pd.Timestamp(s["date"])).days
            decay = 0.5 ** (days_ago / self.config.decay_halflife_days)
            weighted_warning += decay * s["score"]

        if len(danger_signals) >= 2:
            m_values = [s["medium_m"] for s in danger_signals if s["medium_m"] > 0]
            if len(m_values) >= 2:
                m_stability = 1.0 - min(1.0, np.std(m_values) / 0.5)
            else:
                m_stability = 0.5
        else:
            m_stability = 0.5

        if raw_danger_count >= self.config.strong_threshold:
            cluster_level = "strong"
            cluster_score = 1.0
        elif raw_danger_count >= self.config.moderate_threshold:
            cluster_level = "moderate"
            cluster_score = 0.7
        elif raw_danger_count >= self.config.weak_threshold:
            cluster_level = "weak"
            cluster_score = 0.3
        else:
            cluster_level = "none"
            cluster_score = 0.0

        final_cluster_score = (
            cluster_score
            * min(1.0, weighted_danger / 3.0)
            * (0.5 + 0.5 * m_stability)
        )

        return {
            "cluster_level": cluster_level,
            "cluster_score": round(final_cluster_score, 4),
            "raw_danger_count": raw_danger_count,
            "raw_warning_count": raw_warning_count,
            "weighted_danger": round(weighted_danger, 4),
            "weighted_warning": round(weighted_warning, 4),
            "m_stability": round(m_stability, 4),
            "window_days": self.config.window_days,
        }

    def get_cluster_multiplier(self, cluster_score: float) -> float:
        if cluster_score >= 0.8:
            return 1.5
        elif cluster_score >= 0.5:
            return 1.2
        elif cluster_score >= 0.2:
            return 1.0
        else:
            return 0.5
