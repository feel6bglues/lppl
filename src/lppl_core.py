# -*- coding: utf-8 -*-
from __future__ import annotations

"""
LPPL 底层数值核心

职责：提供 LPPL 模型函数、代价函数、单窗口拟合、输入校验等基础运算。
被 src.lppl_engine 策略层调用，不包含策略级逻辑（扫描、集成、风险解释）。

关系：
- src.lppl_engine 是本模块的调用方（策略级入口）
"""

import logging
from typing import Any, Dict, Literal, Optional, Tuple

import pandas as pd

from src.constants import ENABLE_NUMBA_JIT, REQUIRED_COLUMNS
from src.exceptions import DataValidationError

LPPL_RMSE_THRESHOLD = 10.0

FitFailureReason = Literal[
    "insufficient_data",
    "non_positive_price",
    "nan_or_inf",
    "constant_price",
    "optimizer_failed",
    "numeric_error",
]

FitFailureStats = Dict[FitFailureReason, int]


def track_fit_failure(
    reason: FitFailureReason, stats: Optional[FitFailureStats] = None, context: str = ""
) -> None:
    if stats is not None:
        stats[reason] = stats.get(reason, 0) + 1
    logger.debug(f"LPPL fit failure [{reason}]{' - ' + context if context else ''}")


import numpy as np

logger = logging.getLogger(__name__)

NUMBA_AVAILABLE = False
try:
    from numba import njit

    NUMBA_AVAILABLE = True
    logger.info("Numba JIT compilation available")
except ImportError:
    NUMBA_AVAILABLE = False
    logger.warning("Numba not available, using pure Python implementation")


def precheck_fit_input(close_prices: np.ndarray, window_size: int) -> Optional[FitFailureReason]:
    if len(close_prices) < window_size:
        return "insufficient_data"
    subset = close_prices[-window_size:]
    if np.any(subset <= 0):
        return "non_positive_price"
    if np.any(~np.isfinite(subset)):
        return "nan_or_inf"
    if np.ptp(subset) < 1e-10:
        return "constant_price"
    return None


def _lppl_func_python(
    t: np.ndarray, tc: float, m: float, w: float, a: float, b: float, c: float, phi: float
) -> np.ndarray:
    tau = tc - t
    tau = np.maximum(tau, 1e-8)
    return a + b * (tau**m) + c * (tau**m) * np.cos(w * np.log(tau) + phi)


if NUMBA_AVAILABLE:

    @njit(cache=True, fastmath=True)
    def _lppl_func_numba(
        t: np.ndarray, tc: float, m: float, w: float, a: float, b: float, c: float, phi: float
    ) -> np.ndarray:
        tau = tc - t
        n = len(tau)
        result = np.empty(n)
        for i in range(n):
            if tau[i] < 1e-8:
                tau_i = 1e-8
            else:
                tau_i = tau[i]
            result[i] = a + b * (tau_i**m) + c * (tau_i**m) * np.cos(w * np.log(tau_i) + phi)
        return result


def lppl_func(
    t: np.ndarray, tc: float, m: float, w: float, a: float, b: float, c: float, phi: float
) -> np.ndarray:


    if NUMBA_AVAILABLE and ENABLE_NUMBA_JIT:
        return _lppl_func_numba(t, tc, m, w, a, b, c, phi)
    return _lppl_func_python(t, tc, m, w, a, b, c, phi)


def cost_function(params: Tuple, t: np.ndarray, log_prices: np.ndarray) -> float:

    if NUMBA_AVAILABLE and ENABLE_NUMBA_JIT:
        return _cost_function_numba(params, t, log_prices)
    return _cost_function_python(params, t, log_prices)


def _cost_function_python(params: Tuple, t: np.ndarray, log_prices: np.ndarray) -> float:
    tc, m, w, a, b, c, phi = params
    try:
        prediction = _lppl_func_python(t, tc, m, w, a, b, c, phi)
        residuals = prediction - log_prices
        return np.sum(residuals**2)
    except (FloatingPointError, OverflowError, ValueError):
        return 1e10


if NUMBA_AVAILABLE:

    @njit(cache=True, fastmath=True)
    def _cost_function_numba(params: np.ndarray, t: np.ndarray, log_prices: np.ndarray) -> float:
        tc = params[0]
        m = params[1]
        w = params[2]
        a = params[3]
        b = params[4]
        c = params[5]
        phi = params[6]

        prediction = _lppl_func_numba(t, tc, m, w, a, b, c, phi)
        residuals = prediction - log_prices
        return np.sum(residuals**2)


def validate_input_data(df: pd.DataFrame, symbol: str) -> None:
    if df is None or df.empty:
        raise DataValidationError(f"{symbol}: DataFrame is None or empty")


    missing_cols = [col for col in REQUIRED_COLUMNS if col not in df.columns]
    if missing_cols:
        raise DataValidationError(f"{symbol}: Missing required columns: {missing_cols}")

    if len(df) < 50:
        raise DataValidationError(f"{symbol}: Insufficient data rows: {len(df)} < 50")

    if df["close"].isnull().any():
        raise DataValidationError(f"{symbol}: Null values found in close column")

    if (df["close"] <= 0).any():
        raise DataValidationError(f"{symbol}: Non-positive prices found in close column")


def fit_single_window_task(args: Tuple[int, pd.Series, np.ndarray]) -> Optional[Dict[str, Any]]:
    window_size, dates_series, prices_array = args

    try:
        if len(prices_array) < 50 or window_size <= 0:
            return None

        t_data = np.arange(len(prices_array))
        log_price_data = np.log(prices_array)

        if np.any(np.isnan(log_price_data)) or np.any(np.isinf(log_price_data)):
            return None

        current_t = len(prices_array)
        last_date_raw = dates_series.iloc[-1] if hasattr(dates_series, "iloc") else dates_series[-1]
        if hasattr(last_date_raw, "to_pydatetime"):
            last_date = last_date_raw
        else:
            import pandas as pd

            last_date = pd.Timestamp(last_date_raw)

        price_min = np.min(log_price_data)
        price_max = np.max(log_price_data)

        if price_min == price_max:
            return None

        bounds = [
            (current_t + 1, current_t + 100),
            (0.1, 0.9),
            (6, 13),
            (price_min, price_max * 1.1),
            (-20, 20),
            (-20, 20),
            (0, 2 * np.pi),
        ]

        from scipy.optimize import differential_evolution

        best_result = None
        best_fun = float("inf")
        for seed in [0, 42, 123, 9999]:
            result = differential_evolution(
                cost_function, bounds, args=(t_data, log_price_data),
                strategy="best1bin", maxiter=100, popsize=15,
                tol=0.05, seed=seed, workers=1,
            )
            if result.success and result.fun < best_fun:
                best_result = result
                best_fun = result.fun
        result = best_result

        if result is None or not result.success or not np.isfinite(result.fun):
            return None

        fitted_curve = lppl_func(t_data, *result.x)
        mse = np.mean((fitted_curve - log_price_data) ** 2)

        if not np.isfinite(mse):
            return None

        rmse = np.sqrt(mse)

        if not np.isfinite(rmse) or rmse > LPPL_RMSE_THRESHOLD:
            return None

        return {"window": window_size, "params": result.x, "rmse": rmse, "last_date": last_date}
    except (ValueError, TypeError, FloatingPointError):
        logger.debug("fit_single_window_task failed")
        return None


def calculate_risk_level(m: float, w: float, days_left: float) -> str:
    """
    计算风险等级（已弃用，仅保留向后兼容）

    请使用 src.lppl_engine.calculate_risk_level() 替代：
      - 支持 LPPLConfig 参数
      - 返回 (risk_label, is_danger, is_warning) 三元组
      - 阈值通过配置控制，而非硬编码

    此函数使用硬编码阈值（5/20/60 天），不受 LPPLConfig 影响。
    """
    DANGER_DAYS = 5
    WARNING_DAYS = 20
    WATCH_DAYS = 60
    if 0.1 < m < 0.9 and 6 < w < 13:
        if days_left < DANGER_DAYS:
            return "极高危 (DANGER)"
        elif days_left < WARNING_DAYS:
            return "高危 (Warning)"
        elif days_left < WATCH_DAYS:
            return "观察 (Watch)"
        else:
            return "安全 (Safe)"
    else:
        return "无效模型 (假信号)"


def detect_negative_bubble(m: float, w: float, b: float, days_left: float) -> Tuple[bool, str]:
    is_negative = False
    signal = "无抄底信号"

    if 0.1 < m < 0.9 and 6 < w < 13:
        if b > 0:
            is_negative = True
            if days_left < 20:
                signal = "强抄底信号 (Strong Buy)"
            elif days_left < 40:
                signal = "中等抄底信号 (Buy)"
            else:
                signal = "弱抄底信号 (Watch for Buy)"

    return is_negative, signal


def calculate_bottom_signal_strength(m: float, w: float, b: float, rmse: float) -> float:
    strength = 0.0

    if not (0.1 < m < 0.9 and 6 < w < 13):
        return 0.0

    if b <= 0:
        return 0.0

    m_score = 1.0 - abs(m - 0.5) / 0.4

    w_score = 1.0 - abs(w - 8.0) / 5.0

    b_score = min(b / 1.0, 1.0)

    rmse_score = max(0.0, 1.0 - rmse / 0.1)

    strength = m_score * 0.3 + w_score * 0.3 + b_score * 0.2 + rmse_score * 0.2

    return min(max(strength, 0.0), 1.0)
