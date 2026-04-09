# -*- coding: utf-8 -*-
"""
LPPL 回测 - 极速拟合模块
使用向量化预计算 + 快速优化
"""

import numpy as np
from numba import njit
from scipy.optimize import minimize


@njit(cache=True, parallel=True)
def lppl_vectorized(t, tc, m, w, a, b, c, phi):
    """LPPL 模型函数 - Numba 并行加速"""
    n = len(t)
    result = np.empty(n)
    for i in range(n):
        tau = tc - t[i]
        if tau < 1e-8:
            tau = 1e-8
        power = tau ** m
        result[i] = a + b * power + c * power * np.cos(w * np.log(tau) + phi)
    return result


@njit(cache=True)
def compute_cost(params, t, log_prices):
    """成本函数"""
    tc, m, w, a, b, c, phi = params
    prediction = lppl_vectorized(t, tc, m, w, a, b, c, phi)
    return np.sum((prediction - log_prices) ** 2)


def fit_single_point(data):
    """
    极速拟合 - 仅使用 L-BFGS-B 快速优化
    
    Args:
        data: tuple (idx, close_prices, window_size)
    
    Returns:
        dict 或 None
    """
    idx, close_prices, window_size = data

    if idx < window_size:
        return None

    close_subset = close_prices[max(0, idx - window_size):idx]

    if len(close_subset) < window_size:
        return None

    t_data = np.arange(len(close_subset), dtype=np.float64)
    log_prices = np.log(close_subset)
    current_t = float(len(close_subset))

    log_price_mean = np.mean(log_prices)
    log_price_min = np.min(log_prices)
    log_price_max = np.max(log_prices)
    log_price_range = log_price_max - log_price_min

    if log_price_range < 1e-6 or log_price_range > 50:
        return None

    bounds = [
        (current_t + 1, current_t + 100),
        (0.1, 0.9),
        (6, 13),
        (log_price_min - 0.5 * log_price_range, log_price_max + 0.5 * log_price_range),
        (-log_price_range * 3, log_price_range * 3),
        (-log_price_range * 3, log_price_range * 3),
        (0, 2 * np.pi)
    ]

    initial_guesses = [
        [current_t + 5, 0.5, 8.5, log_price_mean, log_price_range * 0.1, log_price_range * 0.01, 0.0],
        [current_t + 10, 0.4, 9.5, log_price_mean, log_price_range * 0.05, -log_price_range * 0.02, np.pi/2],
        [current_t + 15, 0.6, 7.5, log_price_mean, log_price_range * 0.08, log_price_range * 0.005, np.pi],
        [current_t + 8, 0.7, 8.0, log_price_mean, log_price_range * 0.06, -log_price_range * 0.01, np.pi/4],
    ]

    best_cost = np.inf
    best_params = None

    for x0 in initial_guesses:
        try:
            res = minimize(
                compute_cost,
                x0,
                args=(t_data, log_prices),
                method='L-BFGS-B',
                bounds=bounds,
                options={'maxiter': 50, 'ftol': 0.1}
            )

            if res.fun < best_cost:
                best_cost = res.fun
                best_params = res.x
        except Exception:
            continue

    if best_params is None:
        return None

    try:
        tc, m, w, a, b, c, phi = best_params
        days_to_crash = tc - current_t

        fitted_curve = lppl_vectorized(t_data, tc, m, w, a, b, c, phi)
        ss_res = np.sum((log_prices - fitted_curve) ** 2)
        ss_tot = np.sum((log_prices - log_price_mean) ** 2)
        r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0

        is_danger = (0.1 < m < 0.9) and (6 < w < 13) and (days_to_crash < 10) and (r_squared > 0.7)

        return {
            "idx": idx,
            "is_danger": bool(is_danger),
            "days_to_crash": float(days_to_crash) if is_danger else None,
            "m": float(m),
            "w": float(w),
            "rmse": float(np.sqrt(best_cost / len(log_prices))),
            "r_squared": float(r_squared)
        }
    except Exception:
        return None
