# -*- coding: utf-8 -*-
"""
LPPL 工业级引擎 - 统一核心模块

包含:
- 底层Numba加速算子
- 单窗口/多窗口拟合
- 风险判定
- 峰值检测与分析
"""

import warnings
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from scipy.optimize import differential_evolution, minimize

try:
    from numba import njit
    NUMBA_AVAILABLE = True
except ImportError:
    NUMBA_AVAILABLE = False
    def njit(*args, **kwargs):
        def decorator(func):
            return func
        return decorator

warnings.filterwarnings("ignore")


# ============================================================================
# 配置类
# ============================================================================

@dataclass
class LPPLConfig:
    """LPPL配置参数"""
    # 窗口配置
    window_range: List[int]
    
    # 优化器配置 (使用DE保持与原verify_lppl.py一致)
    optimizer: str = 'de'
    maxiter: int = 100
    popsize: int = 15
    tol: float = 0.05
    
    # 风险阈值 (与plan.md v1.2.0一致)
    m_bounds: Tuple[float, float] = (0.1, 0.9)
    w_bounds: Tuple[float, float] = (6, 13)
    tc_bound: Tuple[float, float] = (1, 100)  # days after current_t
    
    # 信号阈值
    r2_threshold: float = 0.5
    danger_days: int = 20
    warning_days: int = 60
    
    # Ensemble配置
    consensus_threshold: float = 0.15
    
    # 并行配置
    n_workers: int = -1
    
    def __post_init__(self):
        if self.n_workers == -1:
            import os
            self.n_workers = max(1, (os.cpu_count() or 4) - 2)


DEFAULT_CONFIG = LPPLConfig(
    window_range=list(range(40, 100, 20)),  # 与verify_lppl.py一致
)


# ============================================================================
# Numba加速底层算子
# ============================================================================

@njit(cache=True)
def _lppl_func_numba(t: np.ndarray, tc: float, m: float, w: float, 
                     a: float, b: float, c: float, phi: float) -> np.ndarray:
    """LPPL模型函数 - Numba加速"""
    n = len(t)
    result = np.empty(n)
    for i in range(n):
        tau = tc - t[i]
        if tau < 1e-8:
            tau = 1e-8
        power = tau ** m
        result[i] = a + b * power + c * power * np.cos(w * np.log(tau) + phi)
    return result


def lppl_func(t: np.ndarray, tc: float, m: float, w: float,
              a: float, b: float, c: float, phi: float) -> np.ndarray:
    """LPPL模型函数 - 自动选择Numba或纯Python"""
    if NUMBA_AVAILABLE:
        try:
            return _lppl_func_numba(t, tc, m, w, a, b, c, phi)
        except Exception:
            pass
    # 纯Python回退
    tau = tc - t
    tau = np.maximum(tau, 1e-8)
    return a + b * (tau ** m) + c * (tau ** m) * np.cos(w * np.log(tau) + phi)


@njit(cache=True)
def _cost_function_numba(params: np.ndarray, t: np.ndarray, 
                         log_prices: np.ndarray) -> float:
    """代价函数 - Numba加速"""
    tc = params[0]
    m = params[1]
    w = params[2]
    a = params[3]
    b = params[4]
    c = params[5]
    phi = params[6]
    
    n = len(t)
    total = 0.0
    for i in range(n):
        tau = tc - t[i]
        if tau < 1e-8:
            tau = 1e-8
        power = tau ** m
        pred = a + b * power + c * power * np.cos(w * np.log(tau) + phi)
        diff = pred - log_prices[i]
        total += diff * diff
    return total


def cost_function(params: Tuple, t: np.ndarray, log_prices: np.ndarray) -> float:
    """代价函数 - 自动选择优化"""
    if NUMBA_AVAILABLE:
        try:
            return _cost_function_numba(np.array(params), t, log_prices)
        except Exception:
            pass
    # 纯Python回退
    tc, m, w, a, b, c, phi = params
    prediction = lppl_func(t, tc, m, w, a, b, c, phi)
    residuals = prediction - log_prices
    return np.sum(residuals ** 2)


# ============================================================================
# 拟合函数
# ============================================================================

def fit_single_window(close_prices: np.ndarray, window_size: int,
                      config: LPPLConfig = None) -> Optional[Dict[str, Any]]:
    """
    拟合单个窗口 (使用DE优化器，与verify_lppl.py一致)
    
    Args:
        close_prices: 收盘价数组
        window_size: 窗口大小
        config: 配置参数
    
    Returns:
        dict 或 None
    """
    if config is None:
        config = DEFAULT_CONFIG
    
    if len(close_prices) < window_size:
        return None
    
    t_data = np.arange(window_size, dtype=np.float64)
    price_data = close_prices[-window_size:]
    log_price_data = np.log(price_data)
    
    current_t = float(window_size)
    
    # 边界参数 (与verify_lppl.py一致)
    log_min = np.min(log_price_data)
    log_max = np.max(log_price_data)
    
    bounds = [
        (current_t + config.tc_bound[0], current_t + config.tc_bound[1]),  # tc
        config.m_bounds,   # m
        config.w_bounds,   # w
        (log_min, log_max * 1.1),  # a
        (-20, 20),   # b
        (-20, 20),   # c
        (0, 2 * np.pi)  # phi
    ]
    
    try:
        result = differential_evolution(
            cost_function, bounds, 
            args=(t_data, log_price_data),
            strategy='best1bin', 
            maxiter=config.maxiter, 
            popsize=config.popsize, 
            tol=config.tol, 
            seed=42, 
            workers=1
        )
        
        if not result.success:
            return None
        
        tc, m, w, a, b, c, phi = result.x
        days_to_crash = tc - current_t
        
        fitted_curve = lppl_func(t_data, tc, m, w, a, b, c, phi)
        
        # 计算R²
        ss_res = np.sum((log_price_data - fitted_curve) ** 2)
        ss_tot = np.sum((log_price_data - np.mean(log_price_data)) ** 2)
        r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0
        
        rmse = np.sqrt(np.mean((fitted_curve - log_price_data) ** 2))
        
        # Danger信号条件 (与verify_lppl.py:76一致)
        is_danger = (0.1 < m < 0.9) and (6 < w < 13) and (days_to_crash < 20) and (r_squared > 0.5)
        
        return {
            'window_size': window_size,
            'rmse': rmse,
            'r_squared': r_squared,
            'm': m,
            'w': w,
            'tc': tc,
            'days_to_crash': days_to_crash,
            'is_danger': bool(is_danger),
            'params': (tc, m, w, a, b, c, phi),
        }
    except Exception:
        return None


def fit_single_window_lbfgsb(close_prices: np.ndarray, window_size: int,
                              config: LPPLConfig = None) -> Optional[Dict[str, Any]]:
    """
    拟合单个窗口 (使用L-BFGS-B优化器，更快)
    
    Args:
        close_prices: 收盘价数组
        window_size: 窗口大小
        config: 配置参数
    
    Returns:
        dict 或 None
    """
    if config is None:
        config = DEFAULT_CONFIG
    
    if len(close_prices) < window_size:
        return None
    
    t_data = np.arange(window_size, dtype=np.float64)
    price_data = close_prices[-window_size:]
    log_price_data = np.log(price_data)
    
    current_t = float(window_size)
    
    log_mean = np.mean(log_price_data)
    log_min = np.min(log_price_data)
    log_max = np.max(log_price_data)
    log_range = log_max - log_min
    
    if log_range < 1e-6 or log_range > 50:
        return None
    
    bounds = [
        (current_t + config.tc_bound[0], current_t + config.tc_bound[1]),
        config.m_bounds,
        config.w_bounds,
        (log_min - 0.5 * log_range, log_max + 0.5 * log_range),
        (-log_range * 3, log_range * 3),
        (-log_range * 3, log_range * 3),
        (0, 2 * np.pi)
    ]
    
    # 多个初始点
    initial_guesses = [
        [current_t + 5, 0.5, 8.5, log_mean, log_range * 0.1, log_range * 0.01, 0.0],
        [current_t + 10, 0.4, 9.5, log_mean, log_range * 0.05, -log_range * 0.02, np.pi/2],
        [current_t + 15, 0.6, 7.5, log_mean, log_range * 0.08, log_range * 0.005, np.pi],
        [current_t + 8, 0.7, 8.0, log_mean, log_range * 0.06, -log_range * 0.01, np.pi/4],
    ]
    
    best_cost = np.inf
    best_params = None
    
    for x0 in initial_guesses:
        try:
            res = minimize(
                cost_function,
                x0,
                args=(t_data, log_price_data),
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
        
        fitted_curve = lppl_func(t_data, tc, m, w, a, b, c, phi)
        
        ss_res = np.sum((log_price_data - fitted_curve) ** 2)
        ss_tot = np.sum((log_price_data - log_mean) ** 2)
        r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0
        
        rmse = np.sqrt(best_cost / len(log_price_data))
        
        # Danger信号条件
        is_danger = (0.1 < m < 0.9) and (6 < w < 13) and (days_to_crash < 20) and (r_squared > 0.5)
        
        return {
            'window_size': window_size,
            'rmse': rmse,
            'r_squared': r_squared,
            'm': m,
            'w': w,
            'tc': tc,
            'days_to_crash': days_to_crash,
            'is_danger': bool(is_danger),
            'params': (tc, m, w, a, b, c, phi),
        }
    except Exception:
        return None


# ============================================================================
# 风险判定
# ============================================================================

def calculate_risk_level(m: float, w: float, days_left: float,
                        r2: float = 1.0) -> Tuple[str, bool, bool]:
    """
    计算风险等级
    
    Returns:
        (risk_level, is_danger, is_warning)
    """
    valid_model = (config.m_bounds[0] < m < config.m_bounds[1] and 
                   config.w_bounds[0] < w < config.w_bounds[1])
    
    if not valid_model:
        return "无效模型", False, False
    
    is_danger = (days_left < config.danger_days) and (r2 > config.r2_threshold)
    is_warning = (days_left < config.warning_days) and (r2 > config.r2_threshold * 0.6)
    
    if days_left < 5:
        return "极高危", is_danger, is_warning
    elif days_left < config.danger_days:
        return "高危", is_danger, is_warning
    elif days_left < config.warning_days:
        return "观察", is_danger, is_warning
    else:
        return "安全", is_danger, is_warning


def validate_model(params: Dict, config: LPPLConfig = None) -> bool:
    """验证模型是否有效"""
    if config is None:
        config = DEFAULT_CONFIG
    
    m, w = params.get('m', 0), params.get('w', 0)
    r2 = params.get('r_squared', 0)
    
    return (config.m_bounds[0] < m < config.m_bounds[1] and
            config.w_bounds[0] < w < config.w_bounds[1] and
            r2 > config.r2_threshold)


# ============================================================================
# 扫描函数
# ============================================================================

def scan_single_date(close_prices: np.ndarray, idx: int, 
                    window_range: List[int], 
                    config: LPPLConfig = None) -> Optional[Dict[str, Any]]:
    """
    扫描单个日期的所有窗口，选择最佳拟合
    
    Args:
        close_prices: 收盘价数组
        idx: 当前索引
        window_range: 窗口范围列表
        config: 配置参数
    
    Returns:
        dict 或 None
    """
    if config is None:
        config = DEFAULT_CONFIG
    
    results = []
    for window_size in window_range:
        if idx < window_size:
            continue
        
        subset = close_prices[idx - window_size:idx]
        
        if config.optimizer == 'lbfgsb':
            res = fit_single_window_lbfgsb(subset, window_size, config)
        else:
            res = fit_single_window(subset, window_size, config)
        
        if res is not None:
            res['idx'] = idx
            results.append(res)
    
    if not results:
        return None
    
    # 选择RMSE最低的结果
    best = min(results, key=lambda x: x['rmse'])
    return best


def scan_date_range(close_prices: np.ndarray, start_idx: int, end_idx: int,
                   window_range: List[int], step: int = 1,
                   config: LPPLConfig = None) -> List[Dict[str, Any]]:
    """
    扫描日期范围内的所有窗口
    
    Args:
        close_prices: 收盘价数组
        start_idx: 起始索引
        end_idx: 结束索引
        window_range: 窗口范围列表
        step: 步长
        config: 配置参数
    
    Returns:
        list of dict
    """
    from joblib import Parallel, delayed
    
    if config is None:
        config = DEFAULT_CONFIG
    
    indices = list(range(start_idx, end_idx, step))
    
    results = Parallel(n_jobs=config.n_workers, backend='loky', verbose=0)(
        delayed(scan_single_date)(close_prices, idx, window_range, config)
        for idx in indices
    )
    
    return [r for r in results if r is not None]


# ============================================================================
# 峰值检测与分析
# ============================================================================

def find_local_highs(df: pd.DataFrame, min_gap: int = 60, 
                     min_drop_pct: float = 0.05,
                     window: int = 20) -> List[Dict[str, Any]]:
    """
    查找局部最高点
    
    Args:
        df: 包含date和close的DataFrame
        min_gap: 两个高点之间的最小间隔天数
        min_drop_pct: 高点后最小跌幅百分比
        window: 检测窗口大小
    
    Returns:
        list of dict: 高点信息
    """
    highs = []
    close = df['close'].values
    dates = df['date'].values
    
    for i in range(window, len(close) - window):
        local_max = np.max(close[i-window:i+window+1])
        if close[i] == local_max:
            future_window = min(60, len(close) - i - 1)
            if future_window > 0:
                future_min = np.min(close[i+1:i+1+future_window])
                drop_pct = (close[i] - future_min) / close[i]
                
                if drop_pct >= min_drop_pct:
                    too_close = False
                    for h in highs:
                        if abs(i - h['idx']) < min_gap:
                            too_close = True
                            break
                    
                    if not too_close:
                        highs.append({
                            'idx': i,
                            'date': dates[i],
                            'price': close[i],
                            'drop_pct': drop_pct
                        })
    
    return highs


def calculate_trend_scores(daily_results: List[Dict], 
                          ma_window: int = 5,
                          config: LPPLConfig = None) -> pd.DataFrame:
    """
    计算趋势评分
    
    Args:
        daily_results: 每日最佳拟合结果列表
        ma_window: 移动平均窗口
        config: 配置参数
    
    Returns:
        DataFrame
    """
    if config is None:
        config = DEFAULT_CONFIG
    
    if not daily_results:
        return pd.DataFrame()
    
    df = pd.DataFrame(daily_results)
    df = df.sort_values('idx').reset_index(drop=True)
    
    # 如果没有is_danger列，根据参数计算
    if 'is_danger' not in df.columns:
        is_danger_list = []
        for _, row in df.iterrows():
            is_d = (
                config.m_bounds[0] < row['m'] < config.m_bounds[1] and
                config.w_bounds[0] < row['w'] < config.w_bounds[1] and
                row['days_to_crash'] < config.danger_days and
                row['r_squared'] > config.r2_threshold
            )
            is_danger_list.append(is_d)
        df['is_danger'] = is_danger_list
    
    # 如果没有is_warning列，根据参数计算
    if 'is_warning' not in df.columns:
        is_warning_list = []
        warning_r2_threshold = max(0.0, config.r2_threshold - 0.2)
        for _, row in df.iterrows():
            is_w = (
                config.m_bounds[0] < row['m'] < config.m_bounds[1] and
                config.w_bounds[0] < row['w'] < config.w_bounds[1] and
                row['days_to_crash'] < config.warning_days and
                row['r_squared'] > warning_r2_threshold
            )
            is_warning_list.append(is_w)
        df['is_warning'] = is_warning_list
    
    # R²移动平均
    df['r2_ma'] = df['r_squared'].rolling(window=ma_window, min_periods=1).mean()
    
    # Danger信号计数
    df['danger_count'] = df['is_danger'].rolling(window=ma_window, min_periods=1).sum()
    
    # 趋势得分
    df['trend_score'] = df['r2_ma'] * (df['danger_count'] / ma_window)
    
    return df


def analyze_peak(df: pd.DataFrame, peak_idx: int,
                window_range: List[int], 
                scan_step: int = 2, 
                ma_window: int = 5,
                config: LPPLConfig = None) -> Optional[Dict[str, Any]]:
    """
    分析单个高点前后的LPPL信号
    
    Args:
        df: DataFrame with date and close
        peak_idx: 高点索引
        window_range: LPPL窗口范围
        scan_step: 扫描步长
        ma_window: 移动平均窗口
        config: 配置参数
    
    Returns:
        dict: 分析结果
    """
    if config is None:
        config = DEFAULT_CONFIG
    
    close_prices = df['close'].values
    
    # 扫描范围: 高点前120天到高点
    start_idx = max(max(window_range) + 5, peak_idx - 120)
    end_idx = peak_idx
    
    if start_idx >= end_idx:
        return None
    
    indices = list(range(start_idx, end_idx + 1, scan_step))
    
    from joblib import Parallel, delayed
    results = Parallel(n_jobs=config.n_workers, backend='loky', verbose=0)(
        delayed(scan_single_date)(close_prices, idx, window_range, config)
        for idx in indices
    )
    results = [r for r in results if r is not None]
    
    if len(results) == 0:
        return None
    
    # 添加日期和价格
    for r in results:
        r['date'] = df.iloc[r['idx']]['date']
        r['price'] = df.iloc[r['idx']]['close']
        r['days_to_peak'] = r['idx'] - peak_idx
    
    # 计算趋势得分
    trend_df = calculate_trend_scores(results, ma_window, config)
    
    # 分析危险信号
    danger_signals = trend_df[trend_df['is_danger']]
    danger_before_peak = danger_signals[danger_signals['days_to_peak'] <= 0]
    
    first_danger = danger_before_peak.sort_values('date').iloc[0] if len(danger_before_peak) > 0 else None
    
    # 最高趋势得分
    before_peak = trend_df[trend_df['days_to_peak'] <= 0]
    if len(before_peak) > 0 and len(before_peak[before_peak['trend_score'] > 0]) > 0:
        best_trend = before_peak.loc[before_peak['trend_score'].idxmax()]
    else:
        best_trend = None
    
    peak_date = df.iloc[peak_idx]['date']
    peak_price = df.iloc[peak_idx]['close']
    
    return {
        'peak_idx': peak_idx,
        'peak_date': peak_date if isinstance(peak_date, str) else peak_date.strftime('%Y-%m-%d'),
        'peak_price': peak_price,
        'total_scans': len(results),
        'danger_count': len(danger_signals),
        'danger_before_peak': len(danger_before_peak),
        'first_danger_days': first_danger['days_to_peak'] if first_danger is not None else None,
        'first_danger_r2': first_danger['r_squared'] if first_danger is not None else None,
        'first_danger_m': first_danger['m'] if first_danger is not None else None,
        'first_danger_w': first_danger['w'] if first_danger is not None else None,
        'best_trend_days': best_trend['days_to_peak'] if best_trend is not None else None,
        'best_trend_score': best_trend['trend_score'] if best_trend is not None else None,
        'best_trend_r2': best_trend['r_squared'] if best_trend is not None else None,
        'detected': len(danger_before_peak) > 0,
        'mode': 'single_window',
        'timeline': trend_df.to_dict('records'),
    }


def analyze_peak_ensemble(df: pd.DataFrame, peak_idx: int,
                         window_range: List[int],
                         scan_step: int = 2,
                         ma_window: int = 5,
                         config: LPPLConfig = None) -> Optional[Dict[str, Any]]:
    """
    分析单个高点前后的 Ensemble 信号

    Returns:
        dict: 与 analyze_peak 兼容的 summary 字段，并额外包含 timeline
    """
    if config is None:
        config = DEFAULT_CONFIG

    close_prices = df["close"].values

    start_idx = max(max(window_range) + 5, peak_idx - 120)
    end_idx = peak_idx

    if start_idx >= end_idx:
        return None

    indices = list(range(start_idx, end_idx + 1, scan_step))

    if config.n_workers == 1:
        results = [
            process_single_day_ensemble(
                close_prices,
                idx,
                window_range,
                min_r2=config.r2_threshold,
                consensus_threshold=config.consensus_threshold,
                config=config,
            )
            for idx in indices
        ]
    else:
        from joblib import Parallel, delayed

        results = Parallel(n_jobs=config.n_workers, backend='loky', verbose=0)(
            delayed(process_single_day_ensemble)(
                close_prices,
                idx,
                window_range,
                config.r2_threshold,
                config.consensus_threshold,
                config,
            )
            for idx in indices
        )

    results = [r for r in results if r is not None]

    if not results:
        return None

    for r in results:
        r["date"] = df.iloc[r["idx"]]["date"]
        r["price"] = df.iloc[r["idx"]]["close"]
        r["days_to_peak"] = r["idx"] - peak_idx
        r["is_danger"] = bool(r["predicted_crash_days"] < config.danger_days)
        r["is_warning"] = bool(r["predicted_crash_days"] < config.warning_days)
        r["trend_score"] = r["signal_strength"]

    trend_df = pd.DataFrame(results).sort_values("idx").reset_index(drop=True)
    before_peak = trend_df[trend_df["days_to_peak"] <= 0]
    danger_before_peak = before_peak[before_peak["is_danger"]]

    first_danger = danger_before_peak.sort_values("date").iloc[0] if len(danger_before_peak) > 0 else None
    best_trend = before_peak.loc[before_peak["signal_strength"].idxmax()] if len(before_peak) > 0 else None

    peak_date = df.iloc[peak_idx]["date"]
    peak_price = df.iloc[peak_idx]["close"]

    return {
        "peak_idx": peak_idx,
        "peak_date": peak_date if isinstance(peak_date, str) else peak_date.strftime("%Y-%m-%d"),
        "peak_price": peak_price,
        "total_scans": len(results),
        "danger_count": int(trend_df["is_danger"].sum()),
        "danger_before_peak": len(danger_before_peak),
        "first_danger_days": first_danger["days_to_peak"] if first_danger is not None else None,
        "first_danger_r2": first_danger["avg_r2"] if first_danger is not None else None,
        "first_danger_m": None,
        "first_danger_w": None,
        "best_trend_days": best_trend["days_to_peak"] if best_trend is not None else None,
        "best_trend_score": best_trend["signal_strength"] if best_trend is not None else None,
        "best_trend_r2": best_trend["avg_r2"] if best_trend is not None else None,
        "detected": len(danger_before_peak) > 0,
        "mode": "ensemble",
        "timeline": trend_df.to_dict("records"),
    }


# ============================================================================
# Ensemble集成 (来自target.md)
# ============================================================================

def process_single_day_ensemble(close_prices: np.ndarray, idx: int,
                                window_range: List[int],
                                min_r2: float = None,
                                consensus_threshold: float = None,
                                config: LPPLConfig = None) -> Optional[Dict[str, Any]]:
    """
    处理特定交易日，执行系综集成 (来自target.md)
    
    Args:
        close_prices: 收盘价数组
        idx: 当前索引
        window_range: 窗口范围
        min_r2: 最小R²阈值
        consensus_threshold: 共识度阈值
        config: 配置参数
    
    Returns:
        dict 或 None
    """
    if config is None:
        config = DEFAULT_CONFIG
    if min_r2 is None:
        min_r2 = config.r2_threshold
    if consensus_threshold is None:
        consensus_threshold = config.consensus_threshold
    
    valid_fits = []
    total_windows = len(window_range)
    
    # 1. 扫描当天所有窗口
    for w_size in window_range:
        if idx < w_size:
            continue
        
        subset = close_prices[idx - w_size:idx]
        
        if config.optimizer == 'lbfgsb':
            res = fit_single_window_lbfgsb(subset, w_size, config)
        else:
            res = fit_single_window(subset, w_size, config)
        
        # 2. 硬过滤
        if res is not None and res['r_squared'] > min_r2:
            if (config.m_bounds[0] < res['m'] < config.m_bounds[1] and 
                config.w_bounds[0] < res['w'] < config.w_bounds[1]):
                valid_fits.append(res)
    
    valid_n = len(valid_fits)
    consensus_rate = valid_n / total_windows if total_windows > 0 else 0
    
    # 3. 共识度验证
    if consensus_rate < consensus_threshold:
        return None
    
    # 4. 崩溃时间聚类分析
    tc_array = np.array([fit['days_to_crash'] for fit in valid_fits])
    tc_std = np.std(tc_array)

    positive_fits = [fit for fit in valid_fits if fit.get("params", (None, None, None, None, 0))[4] <= 0]
    negative_fits = [fit for fit in valid_fits if fit.get("params", (None, None, None, None, 0))[4] > 0]

    positive_consensus_rate = len(positive_fits) / total_windows if total_windows > 0 else 0.0
    negative_consensus_rate = len(negative_fits) / total_windows if total_windows > 0 else 0.0
    predicted_rebound_days = np.median([fit["days_to_crash"] for fit in negative_fits]) if negative_fits else None
    
    # 5. 信号强度计算
    signal_strength = consensus_rate * (1.0 / (tc_std + 1.0))
    
    return {
        'idx': idx,
        'consensus_rate': consensus_rate,
        'valid_windows': valid_n,
        'predicted_crash_days': np.median(tc_array),
        'tc_std': tc_std,
        'signal_strength': signal_strength,
        'avg_r2': np.mean([fit['r_squared'] for fit in valid_fits]),
        'positive_consensus_rate': positive_consensus_rate,
        'negative_consensus_rate': negative_consensus_rate,
        'predicted_rebound_days': predicted_rebound_days,
    }


# 全局config引用
config = DEFAULT_CONFIG
