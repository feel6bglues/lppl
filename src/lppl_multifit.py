# -*- coding: utf-8 -*-
"""
三层LPPL系统 Layer 1: 多窗口拟合

基于7组历史LPPL参数数据的实证分析，设计三层窗口独立拟合:
- 短期窗口 [40,60,80]: 捕捉短期泡沫，m范围0.10-0.25
- 中期窗口 [80,120,180]: 捕捉主趋势，m范围0.15-0.90
- 长期窗口 [180,240,360]: 捕捉大周期，m范围0.15-0.60

复用已有: lppl_engine.py 的 fit_single_window / fit_single_window_lbfgsb
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import numpy as np


@dataclass
class WindowConfig:
    """单层窗口配置"""

    name: str
    windows: List[int]
    m_bounds: Tuple[float, float]
    w_bounds: Tuple[float, float]
    r2_threshold: float
    danger_days: int
    warning_days: int
    watch_days: int
    weight: float


MULTI_WINDOW_CONFIGS = {
    "short": WindowConfig(
        name="short",
        windows=[40, 60, 80],
        m_bounds=(0.10, 0.25),
        w_bounds=(6.0, 13.0),
        r2_threshold=0.6,
        danger_days=5,
        warning_days=12,
        watch_days=25,
        weight=0.3,
    ),
    "medium": WindowConfig(
        name="medium",
        windows=[80, 120, 180],
        m_bounds=(0.15, 0.90),
        w_bounds=(6.0, 12.0),
        r2_threshold=0.5,
        danger_days=10,
        warning_days=20,
        watch_days=40,
        weight=0.5,
    ),
    "long": WindowConfig(
        name="long",
        windows=[180, 240, 360],
        m_bounds=(0.15, 0.60),
        w_bounds=(7.0, 12.5),
        r2_threshold=0.4,
        danger_days=20,
        warning_days=40,
        watch_days=60,
        weight=0.2,
    ),
}


def _classify_phase(days_left: float, r2: float, config: WindowConfig) -> str:
    if days_left < 0:
        return "none"
    if days_left < config.danger_days and r2 >= config.r2_threshold:
        return "danger"
    if days_left < config.warning_days and r2 >= max(0.0, config.r2_threshold - 0.05):
        return "warning"
    if days_left < config.watch_days and r2 >= max(0.0, config.r2_threshold - 0.15):
        return "watch"
    return "none"


def fit_single_layer(
    close_prices: np.ndarray,
    idx: int,
    config: WindowConfig,
) -> Optional[Dict[str, Any]]:
    """
    对单层窗口进行独立拟合，选择最佳窗口(RMSE最低)
    使用L-BFGS-B优化器(比DE快10-50倍)
    """
    from src.lppl_engine import LPPLConfig, fit_single_window_lbfgsb

    candidates = []
    for window_size in config.windows:
        if idx < window_size:
            continue

        subset = close_prices[idx - window_size : idx]

        lppl_config = LPPLConfig(
            window_range=[window_size],
            optimizer="lbfgsb",
            maxiter=30,
            popsize=5,
            m_bounds=config.m_bounds,
            w_bounds=config.w_bounds,
            tc_bound=(1, 100),
            r2_threshold=config.r2_threshold,
            danger_days=config.danger_days,
            warning_days=config.warning_days,
            watch_days=config.watch_days,
            n_workers=1,
        )

        result = fit_single_window_lbfgsb(subset, window_size, lppl_config)
        if result is not None:
            phase = _classify_phase(result["days_to_crash"], result["r_squared"], config)
            result["layer"] = config.name
            result["idx"] = idx
            result["phase"] = phase
            result["is_danger"] = phase == "danger"
            result["is_warning"] = phase in ("danger", "warning")
            result["is_watch"] = phase in ("danger", "warning", "watch")
            result["layer_config"] = config.name
            candidates.append(result)

    if not candidates:
        return None

    best = min(candidates, key=lambda x: x["rmse"])
    return best


def fit_multi_window(
    close_prices: np.ndarray,
    idx: int,
    configs: Dict[str, WindowConfig] | None = None,
) -> Dict[str, Optional[Dict]]:
    """
    对单个日期进行三层窗口独立拟合

    Returns:
        {"short": result_or_None, "medium": ..., "long": ...}
    """
    if configs is None:
        configs = MULTI_WINDOW_CONFIGS

    results = {}
    for layer_name, config in configs.items():
        results[layer_name] = fit_single_layer(close_prices, idx, config)
    return results


def calculate_multifit_score(
    multi_results: Dict[str, Optional[Dict]],
    configs: Dict[str, WindowConfig] | None = None,
) -> Dict:
    """
    基于三层拟合结果计算综合得分

    逻辑:
    1. 各层独立评分: R² × m有效 × 时间衰减
    2. 加权合成: short×0.3 + medium×0.5 + long×0.2
    3. 一致性加分: 两层以上danger → 额外加分
    """
    if configs is None:
        configs = MULTI_WINDOW_CONFIGS

    scores = {}
    dangers = []

    for layer_name, config in configs.items():
        result = multi_results.get(layer_name)
        if result is None:
            scores[layer_name] = {
                "raw": 0.0,
                "adjusted": 0.0,
                "is_danger": False,
                "is_warning": False,
                "r_squared": 0.0,
                "m": 0.0,
                "w": 0.0,
                "days_to_crash": 999,
                "phase": "none",
                "window_size": 0,
                "rmse": 999,
                "weight": config.weight,
            }
            continue

        m = result.get("m", 0)
        w = result.get("w", 0)
        r2 = result.get("r_squared", 0)
        days_to_crash = result.get("days_to_crash", 999)
        is_danger = result.get("is_danger", False)
        phase = result.get("phase", "none")
        rmse = result.get("rmse", 999)

        m_valid = config.m_bounds[0] < m < config.m_bounds[1]
        w_valid = config.w_bounds[0] < w < config.w_bounds[1]

        base = r2 if (m_valid and w_valid) else r2 * 0.5

        if days_to_crash <= config.danger_days:
            time_factor = 1.0
        elif days_to_crash <= config.warning_days:
            time_factor = 0.6
        elif days_to_crash <= config.watch_days:
            time_factor = 0.3
        else:
            time_factor = 0.1

        raw_score = base * time_factor

        if is_danger:
            raw_score *= 1.3
        elif phase == "warning":
            raw_score *= 1.1

        scores[layer_name] = {
            "raw": round(raw_score, 4),
            "adjusted": round(raw_score * config.weight, 4),
            "is_danger": is_danger,
            "is_warning": result.get("is_warning", False),
            "r_squared": round(r2, 4),
            "m": round(m, 4),
            "w": round(w, 4),
            "days_to_crash": round(days_to_crash, 2),
            "phase": phase,
            "window_size": result.get("window_size", 0),
            "rmse": round(rmse, 6),
            "m_valid": m_valid,
            "w_valid": w_valid,
            "weight": config.weight,
        }

        if is_danger:
            dangers.append(layer_name)

    weighted_score = sum(s["adjusted"] for s in scores.values())

    consistency_bonus = 0.0
    if len(dangers) >= 3:
        consistency_bonus = 0.3
    elif len(dangers) >= 2:
        consistency_bonus = 0.15

    final_score = min(1.0, weighted_score + consistency_bonus)

    if final_score >= 0.6:
        level = "danger"
    elif final_score >= 0.4:
        level = "warning"
    elif final_score >= 0.2:
        level = "watch"
    else:
        level = "none"

    return {
        "final_score": round(final_score, 4),
        "level": level,
        "weighted_score": round(weighted_score, 4),
        "consistency_bonus": consistency_bonus,
        "layers": scores,
        "danger_layers": dangers,
        "n_danger": len(dangers),
    }
