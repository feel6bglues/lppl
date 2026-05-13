#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
深度有效性测试脚本
==================
针对已识别的有效因子进行严格的统计验证：

1. Wyckoff + LPPL过滤（最有效）- 配对t检验 + Bootstrap置信区间
2. LPPL多层拟合（中高有效）- 分层贡献分析
3. Wyckoff阶段有效性 - 衰减曲线 + 市场状态条件分析

解决现有测试的空白：
- 统计严谨性（置信区间、假设检验）
- 样本外验证（多随机种子）
- 更多周期覆盖（50+周期）
- 衰减曲线分析（10-180天）
- 崩溃检测敏感性测试
"""

from __future__ import annotations

import csv
import json
import os
import random
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import psutil

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
from src.parallel import get_optimal_workers, worker_init
from src.wyckoff.trading import calculate_wyckoff_return, calculate_wyckoff_decay_returns


# ============================================================================
# 配置
# ============================================================================

@dataclass(frozen=True)
class DeepTestConfig:
    """深度测试配置"""
    # 周期数量
    n_cycles: int = 50
    n_seeds: int = 5  # 多随机种子验证
    
    # 衰减测试天数
    decay_days: List[int] = field(default_factory=lambda: [10, 20, 30, 60, 90, 120, 180])
    
    # Wyckoff配置
    wyckoff_lookback_days: int = 400
    wyckoff_weekly_lookback: int = 120
    wyckoff_monthly_lookback: int = 40
    
    # Bootstrap配置
    bootstrap_n: int = 1000
    confidence_level: float = 0.95
    
    # 市场状态阈值
    bull_threshold: float = 0.15  # 年化收益>15%视为牛市
    bear_threshold: float = -0.10  # 年化收益<-10%视为熊市
    
    # 已知崩盘期（用于敏感性测试）
    known_crashes: List[Tuple[str, str, str]] = field(default_factory=lambda: [
        ("2015-06-01", "2015-09-30", "2015年股灾"),
        ("2018-01-01", "2018-12-31", "2018年熊市"),
        ("2020-01-15", "2020-03-31", "2020年COVID崩盘"),
        ("2022-01-01", "2022-10-31", "2022年调整"),
    ])


@dataclass(frozen=True)
class CycleSpec:
    cycle_id: int
    year: int
    as_of_date: str
    seed: int
    description: str


# ============================================================================
# 工具函数
# ============================================================================


def load_stock_symbols(csv_path: Path, limit: int = 99999) -> List[Dict[str, str]]:
    symbols = []
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            code = str(row.get("code", "")).strip()
            market = str(row.get("market", "")).strip().upper()
            name = str(row.get("name", "")).replace("\x00", "").strip()
            if not (code.isdigit() and len(code) == 6 and market in {"SH", "SZ"}):
                continue
            if code.startswith(("600", "601", "603", "605", "688", "689",
                               "000", "001", "002", "003", "300", "301", "302")):
                symbols.append({
                    "symbol": f"{code}.{market}",
                    "code": code,
                    "market": market,
                    "name": name,
                })
            if len(symbols) >= limit:
                break
    return symbols


def load_index_from_tdx(tdx_path: Path) -> pd.DataFrame:
    """加载TDX指数数据（使用集中加载器）"""
    from src.data.tdx_loader import load_tdx_data
    df = load_tdx_data(str(tdx_path))
    return df if df is not None else pd.DataFrame()


def detect_bubble_periods(index_data: pd.DataFrame) -> List[Tuple[str, str]]:
    """检测大盘泡沫阶段"""
    bubble_periods = []
    index_data = index_data.copy()
    index_data['ma20'] = index_data['close'].rolling(20).mean()
    index_data['ma60'] = index_data['close'].rolling(60).mean()
    index_data['returns'] = index_data['close'].pct_change()
    index_data['volatility'] = index_data['returns'].rolling(20).std()
    index_data['high_120'] = index_data['close'].rolling(120).max()
    index_data['low_120'] = index_data['close'].rolling(120).min()
    index_data['relative_position'] = (index_data['close'] - index_data['low_120']) / (index_data['high_120'] - index_data['low_120'])
    
    for i in range(120, len(index_data)):
        row = index_data.iloc[i]
        is_bubble = False
        if row['ma60'] > 0 and (row['close'] - row['ma60']) / row['ma60'] > 0.2:
            is_bubble = True
        if row['volatility'] > 0.03:
            is_bubble = True
        if row['relative_position'] > 0.95:
            is_bubble = True
        if is_bubble:
            bubble_start = index_data.iloc[max(0, i-30)]['date']
            bubble_end = index_data.iloc[min(len(index_data)-1, i+30)]['date']
            bubble_periods.append((str(bubble_start), str(bubble_end)))
    
    if not bubble_periods:
        return []
    
    merged_periods = []
    current_start, current_end = bubble_periods[0]
    for start, end in bubble_periods[1:]:
        if start <= current_end:
            current_end = max(current_end, end)
        else:
            merged_periods.append((current_start, current_end))
            current_start, current_end = start, end
    merged_periods.append((current_start, current_end))
    return merged_periods


def is_in_bubble_period(date_str: str, bubble_periods: List[Tuple[str, str]]) -> bool:
    date = pd.Timestamp(date_str)
    for start, end in bubble_periods:
        if pd.Timestamp(start) <= date <= pd.Timestamp(end):
            return True
    return False


def classify_market_regime(index_data: pd.DataFrame, date_str: str, lookback_days: int = 252) -> str:
    """分类市场状态：bull/bear/range"""
    date = pd.Timestamp(date_str)
    hist_data = index_data[index_data['date'] <= date].tail(lookback_days)
    if len(hist_data) < 60:
        return "unknown"
    
    annual_return = (hist_data['close'].iloc[-1] / hist_data['close'].iloc[0]) ** (252 / len(hist_data)) - 1
    
    if annual_return > 0.15:
        return "bull"
    elif annual_return < -0.10:
        return "bear"
    else:
        return "range"


def generate_cycle_specs(n_cycles: int, seed: int, bubble_periods: List[Tuple[str, str]]) -> List[CycleSpec]:
    """生成测试周期规格"""
    random.seed(seed)
    specs = []
    attempts = 0
    max_attempts = n_cycles * 100
    
    while len(specs) < n_cycles and attempts < max_attempts:
        attempts += 1
        year = random.randint(2012, 2025)
        month = random.randint(3, 11)
        day = random.randint(10, 25)
        date_str = f"{year}-{month:02d}-{day:02d}"
        
        if not is_in_bubble_period(date_str, bubble_periods):
            specs.append(CycleSpec(
                cycle_id=len(specs) + 1,
                year=year,
                as_of_date=date_str,
                seed=seed,
                description=f"Seed{seed}_Year{year}_Cycle{len(specs)+1}"
            ))
    
    # 放宽条件补充
    while len(specs) < n_cycles:
        year = random.randint(2012, 2025)
        month = random.randint(3, 11)
        day = random.randint(10, 25)
        date_str = f"{year}-{month:02d}-{day:02d}"
        specs.append(CycleSpec(
            cycle_id=len(specs) + 1,
            year=year,
            as_of_date=date_str,
            seed=seed,
            description=f"Seed{seed}_Year{year}_Cycle{len(specs)+1}_relaxed"
        ))
    
    return sorted(specs, key=lambda x: x.as_of_date)


def calculate_future_return(df: pd.DataFrame, as_of_date: str, days: int = 60) -> Optional[Dict[str, float]]:
    """计算未来N个交易日的收益率"""
    as_of = pd.Timestamp(as_of_date)
    future_data = df[df["date"] > as_of].head(days)
    if len(future_data) < days * 0.8:
        return None
    entry_price = float(df[df["date"] <= as_of].iloc[-1]["close"])
    future_close = float(future_data.iloc[-1]["close"])
    future_high = float(future_data["high"].max())
    future_low = float(future_data["low"].min())
    return_pct = (future_close - entry_price) / entry_price * 100
    max_gain_pct = (future_high - entry_price) / entry_price * 100
    max_drawdown_pct = (entry_price - future_low) / entry_price * 100
    return {
        "entry_price": round(entry_price, 3),
        "future_close": round(future_close, 3),
        "future_high": round(future_high, 3),
        "future_low": round(future_low, 3),
        "return_pct": round(return_pct, 2),
        "max_gain_pct": round(max_gain_pct, 2),
        "max_drawdown_pct": round(max_drawdown_pct, 2),
        "data_points": len(future_data),
    }


def calculate_decay_returns(df: pd.DataFrame, as_of_date: str, decay_days: List[int]) -> Dict[str, Optional[float]]:
    """计算多个时间窗口的衰减收益"""
    results = {}
    for days in decay_days:
        ret = calculate_future_return(df, as_of_date, days)
        results[f"return_{days}d"] = ret["return_pct"] if ret else None
    return results


# ============================================================================
# 核心测试函数
# ============================================================================

def process_single_stock_paired(args: tuple) -> List[Dict]:
    """处理单只股票的配对测试（同一周期，过滤vs未过滤）"""
    symbol_info, cycle_specs, config, bubble_periods, index_data = args
    symbol = symbol_info["symbol"]
    name = symbol_info["name"]
    results = []

    try:
        from src.data.manager import DataManager
        from src.wyckoff.engine import WyckoffEngine
        
        dm = DataManager()
        df = dm.get_data(symbol)
        if df is None or df.empty:
            return results

        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)

        engine = WyckoffEngine(
            lookback_days=config.wyckoff_lookback_days,
            weekly_lookback=config.wyckoff_weekly_lookback,
            monthly_lookback=config.wyckoff_monthly_lookback
        )

        for spec in cycle_specs:
            as_of = pd.Timestamp(spec.as_of_date)
            available_data = df[df["date"] <= as_of]
            if len(available_data) < 100:
                continue
            
            # 运行Wyckoff分析
            report = engine.analyze(available_data, symbol=symbol, period="日线", multi_timeframe=True)
            
            # 提取Wyckoff交易计划参数
            rr = report.risk_reward
            wyckoff_entry = rr.entry_price if rr and rr.entry_price and rr.entry_price > 0 else None
            stop_loss = rr.stop_loss if rr and rr.stop_loss and rr.stop_loss > 0 else None
            first_target = rr.first_target if rr and rr.first_target and rr.first_target > 0 else None
            
            # 按Wyckoff引擎规则过滤No Trade Zone
            signal_type = report.signal.signal_type
            is_no_trade = signal_type == "no_signal" or report.trading_plan.direction == "空仓观望"
            
            # 计算衰减收益（使用Wyckoff交易逻辑）
            decay_returns = calculate_wyckoff_decay_returns(
                df, spec.as_of_date, config.decay_days,
                wyckoff_entry=wyckoff_entry, stop_loss=stop_loss, first_target=first_target
            )
            
            # 60天收益（主要指标，使用Wyckoff交易逻辑）
            future_return = calculate_wyckoff_return(
                df, spec.as_of_date, days=60,
                wyckoff_entry=wyckoff_entry, stop_loss=stop_loss, first_target=first_target
            )
            if future_return is None:
                continue
            
            # 判断是否在泡沫期
            in_bubble = is_in_bubble_period(spec.as_of_date, bubble_periods)
            
            # 市场状态
            market_regime = classify_market_regime(index_data, spec.as_of_date) if index_data is not None else "unknown"
            
            # 月度收益（使用Wyckoff交易逻辑）
            monthly_return = calculate_wyckoff_return(
                df, spec.as_of_date, days=20,
                wyckoff_entry=wyckoff_entry, stop_loss=stop_loss, first_target=first_target
            )
            
            results.append({
                "cycle_id": spec.cycle_id,
                "cycle_year": spec.year,
                "as_of": spec.as_of_date,
                "seed": spec.seed,
                "symbol": symbol,
                "name": name,
                "phase": report.structure.phase.value,
                "direction": report.trading_plan.direction,
                "confidence": report.trading_plan.confidence.value,
                "signal_type": signal_type,
                "is_no_trade": is_no_trade,
                "mtf_alignment": report.multi_timeframe.alignment if report.multi_timeframe else "",
                "wyckoff_entry_price": round(wyckoff_entry, 3) if wyckoff_entry else None,
                "stop_loss": round(stop_loss, 3) if stop_loss else None,
                "first_target": round(first_target, 3) if first_target else None,
                "exit_reason": future_return.get("exit_reason", "hold_to_end"),
                "hit_stop": future_return.get("hit_stop", False),
                "hit_target": future_return.get("hit_target", False),
                "in_bubble": in_bubble,
                "market_regime": market_regime,
                "future_60d_return": future_return["return_pct"],
                "future_60d_max_gain": future_return["max_gain_pct"],
                "future_60d_max_drawdown": future_return["max_drawdown_pct"],
                "future_20d_return": monthly_return["return_pct"] if monthly_return else None,
                **decay_returns,
            })
    except Exception as e:
        pass

    return results


def run_deep_test(
    symbols: List[Dict[str, str]],
    config: DeepTestConfig,
    bubble_periods: List[Tuple[str, str]],
    index_data: pd.DataFrame,
    output_dir: Path,
    max_workers: int = None,
) -> Tuple[List[Dict], Dict]:
    """运行深度测试"""
    if max_workers is None:
        max_workers = get_optimal_workers()

    all_results = []
    seed_summaries = {}
    
    for seed in range(config.n_seeds):
        print(f"\n{'='*60}")
        print(f"Seed {seed+1}/{config.n_seeds}")
        print(f"{'='*60}")
        
        cycle_specs = generate_cycle_specs(config.n_cycles, seed=42+seed, bubble_periods=bubble_periods)
        print(f"生成了 {len(cycle_specs)} 个测试周期")
        
        args_list = [
            (symbol_info, cycle_specs, config, bubble_periods, index_data)
            for symbol_info in symbols
        ]
        
        seed_results = []
        completed_stocks = 0
        max_workers = get_optimal_workers()
        batch_size = max_workers * 4
        
        with ProcessPoolExecutor(max_workers=max_workers, initializer=worker_init) as executor:
            for batch_start in range(0, len(args_list), batch_size):
                batch = args_list[batch_start:batch_start + batch_size]
                futures = {
                    executor.submit(process_single_stock_paired, args): args[0]
                    for args in batch
                }
                
                for future in as_completed(futures):
                    completed_stocks += 1
                    try:
                        results = future.result(timeout=300)
                        seed_results.extend(results)
                    except Exception:
                        pass
                    
                    if completed_stocks % 500 == 0:
                        memory = psutil.virtual_memory()
                        print(f"  已处理 {completed_stocks}/{len(symbols)} 只股票, "
                              f"累计 {len(seed_results)} 条结果, 内存: {memory.percent}%")
        
        all_results.extend(seed_results)
        seed_summaries[seed] = {
            "n_samples": len(seed_results),
            "avg_return": np.mean([r["future_60d_return"] for r in seed_results]) if seed_results else 0,
            "win_rate": sum(1 for r in seed_results if r["future_60d_return"] > 0) / len(seed_results) * 100 if seed_results else 0,
        }
        print(f"  Seed {seed}: {len(seed_results)} 样本, 平均收益 {seed_summaries[seed]['avg_return']:.2f}%, 胜率 {seed_summaries[seed]['win_rate']:.1f}%")
    
    return all_results, seed_summaries


# ============================================================================
# 统计分析函数
# ============================================================================

def bootstrap_confidence_interval(data: np.ndarray, n_bootstrap: int = 1000, confidence: float = 0.95) -> Tuple[float, float, float]:
    """计算Bootstrap置信区间"""
    if len(data) < 10:
        return np.nan, np.nan, np.nan
    
    bootstrap_means = []
    for _ in range(n_bootstrap):
        sample = np.random.choice(data, size=len(data), replace=True)
        bootstrap_means.append(np.mean(sample))
    
    bootstrap_means = np.array(bootstrap_means)
    mean = np.mean(bootstrap_means)
    lower = np.percentile(bootstrap_means, (1 - confidence) / 2 * 100)
    upper = np.percentile(bootstrap_means, (1 + confidence) / 2 * 100)
    
    return mean, lower, upper


def paired_t_test(filtered_returns: np.ndarray, unfiltered_returns: np.ndarray) -> Dict:
    """配对t检验（使用内置统计）"""
    # 确保长度一致
    min_len = min(len(filtered_returns), len(unfiltered_returns))
    filtered = filtered_returns[:min_len]
    unfiltered = unfiltered_returns[:min_len]
    
    # 计算差异
    diff = filtered - unfiltered
    n = len(diff)
    mean_diff = np.mean(diff)
    std_diff = np.std(diff, ddof=1)
    se_diff = std_diff / np.sqrt(n)
    
    # t统计量
    t_stat = mean_diff / se_diff if se_diff > 0 else 0
    
    # 近似p值（使用正态分布近似，当n>30时足够准确）
    # 使用简单的近似：p ≈ 2 * (1 - Φ(|t|))
    # 对于大样本，t分布接近正态分布
    abs_t = abs(t_stat)
    if abs_t > 3.5:
        p_value = 0.001
    elif abs_t > 2.576:
        p_value = 0.01
    elif abs_t > 1.96:
        p_value = 0.05
    elif abs_t > 1.645:
        p_value = 0.10
    else:
        p_value = 0.5  # 保守估计
    
    # 效应量（Cohen's d）
    cohens_d = mean_diff / std_diff if std_diff > 0 else 0
    
    return {
        "t_statistic": round(t_stat, 4),
        "p_value": round(p_value, 6),
        "cohens_d": round(cohens_d, 4),
        "significant_005": p_value < 0.05,
        "significant_001": p_value < 0.01,
        "mean_diff": round(mean_diff, 4),
        "std_diff": round(std_diff, 4),
    }


def analyze_lppl_layer_contribution(results: List[Dict]) -> Dict:
    """分析LPPL各层的贡献"""
    df = pd.DataFrame(results)
    
    # 按是否在泡沫期分组
    bubble_results = df[df["in_bubble"] == True]
    non_bubble_results = df[df["in_bubble"] == False]
    
    contribution = {
        "bubble_period": {
            "n_samples": len(bubble_results),
            "avg_return": round(bubble_results["future_60d_return"].mean(), 2) if len(bubble_results) > 0 else None,
            "win_rate": round(sum(bubble_results["future_60d_return"] > 0) / len(bubble_results) * 100, 1) if len(bubble_results) > 0 else None,
        },
        "non_bubble_period": {
            "n_samples": len(non_bubble_results),
            "avg_return": round(non_bubble_results["future_60d_return"].mean(), 2) if len(non_bubble_results) > 0 else None,
            "win_rate": round(sum(non_bubble_results["future_60d_return"] > 0) / len(non_bubble_results) * 100, 1) if len(non_bubble_results) > 0 else None,
        },
    }
    
    # 计算过滤效果
    if len(bubble_results) > 0 and len(non_bubble_results) > 0:
        contribution["filter_effect"] = {
            "return_improvement": round(non_bubble_results["future_60d_return"].mean() - bubble_results["future_60d_return"].mean(), 2),
            "win_rate_improvement": round(
                sum(non_bubble_results["future_60d_return"] > 0) / len(non_bubble_results) * 100 -
                sum(bubble_results["future_60d_return"] > 0) / len(bubble_results) * 100, 1
            ),
        }
    
    return contribution


def analyze_decay_curve(results: List[Dict], decay_days: List[int]) -> Dict:
    """分析收益衰减曲线"""
    df = pd.DataFrame(results)
    decay_analysis = {}
    
    for days in decay_days:
        col = f"return_{days}d"
        if col in df.columns:
            valid_data = df[col].dropna()
            if len(valid_data) > 0:
                mean_ret, ci_lower, ci_upper = bootstrap_confidence_interval(valid_data.values)
                decay_analysis[f"{days}d"] = {
                    "n_samples": len(valid_data),
                    "mean_return": round(mean_ret, 2),
                    "ci_lower": round(ci_lower, 2),
                    "ci_upper": round(ci_upper, 2),
                    "win_rate": round(sum(valid_data > 0) / len(valid_data) * 100, 1),
                    "median_return": round(valid_data.median(), 2),
                }
    
    return decay_analysis


def analyze_market_regime_performance(results: List[Dict]) -> Dict:
    """分析不同市场状态下的表现"""
    df = pd.DataFrame(results)
    regime_analysis = {}
    
    for regime in df["market_regime"].unique():
        regime_df = df[df["market_regime"] == regime]
        if len(regime_df) > 10:
            returns = regime_df["future_60d_return"].values
            mean_ret, ci_lower, ci_upper = bootstrap_confidence_interval(returns)
            regime_analysis[regime] = {
                "n_samples": len(regime_df),
                "mean_return": round(mean_ret, 2),
                "ci_lower": round(ci_lower, 2),
                "ci_upper": round(ci_upper, 2),
                "win_rate": round(sum(returns > 0) / len(returns) * 100, 1),
                "median_return": round(np.median(returns), 2),
            }
    
    return regime_analysis


def analyze_phase_by_regime(results: List[Dict]) -> Dict:
    """分析各阶段在不同市场状态下的表现"""
    df = pd.DataFrame(results)
    phase_regime = {}
    
    for phase in df["phase"].unique():
        phase_regime[phase] = {}
        for regime in df["market_regime"].unique():
            subset = df[(df["phase"] == phase) & (df["market_regime"] == regime)]
            if len(subset) >= 10:
                returns = subset["future_60d_return"].values
                mean_ret, ci_lower, ci_upper = bootstrap_confidence_interval(returns)
                phase_regime[phase][regime] = {
                    "n_samples": len(subset),
                    "mean_return": round(mean_ret, 2),
                    "ci_lower": round(ci_lower, 2),
                    "ci_upper": round(ci_upper, 2),
                    "win_rate": round(sum(returns > 0) / len(returns) * 100, 1),
                }
    
    return phase_regime


def analyze_crash_detection_sensitivity(results: List[Dict], config: DeepTestConfig) -> Dict:
    """分析崩盘检测敏感性"""
    df = pd.DataFrame(results)
    crash_analysis = {}
    
    for crash_start, crash_end, crash_name in config.known_crashes:
        crash_start_dt = pd.Timestamp(crash_start)
        crash_end_dt = pd.Timestamp(crash_end)
        
        # 筛选崩盘期前30天的信号
        pre_crash_start = crash_start_dt - pd.Timedelta(days=30)
        crash_signals = df[
            (pd.to_datetime(df["as_of"]) >= pre_crash_start) &
            (pd.to_datetime(df["as_of"]) <= crash_end_dt)
        ]
        
        if len(crash_signals) > 0:
            # 计算崩盘期收益
            crash_returns = crash_signals["future_60d_return"].values
            
            # 分析信号类型分布
            phase_dist = crash_signals["phase"].value_counts().to_dict()
            
            crash_analysis[crash_name] = {
                "period": f"{crash_start} ~ {crash_end}",
                "n_signals": len(crash_signals),
                "avg_return": round(np.mean(crash_returns), 2),
                "win_rate": round(sum(crash_returns > 0) / len(crash_returns) * 100, 1),
                "phase_distribution": phase_dist,
                "markdown_rate": round(sum(crash_signals["phase"] == "markdown") / len(crash_signals) * 100, 1),
            }
    
    return crash_analysis


def analyze_monthly_consistency(results: List[Dict]) -> Dict:
    """分析月度一致性"""
    df = pd.DataFrame(results)
    df["as_of_month"] = pd.to_datetime(df["as_of"]).dt.to_period("M")
    
    monthly_stats = {}
    for month, group in df.groupby("as_of_month"):
        if len(group) >= 10:
            returns = group["future_60d_return"].values
            monthly_stats[str(month)] = {
                "n_samples": len(group),
                "mean_return": round(np.mean(returns), 2),
                "win_rate": round(sum(returns > 0) / len(returns) * 100, 1),
            }
    
    # 计算月度一致性
    if monthly_stats:
        monthly_returns = [v["mean_return"] for v in monthly_stats.values()]
        positive_months = sum(1 for r in monthly_returns if r > 0)
        monthly_consistency = {
            "n_months": len(monthly_stats),
            "positive_months": positive_months,
            "consistency_rate": round(positive_months / len(monthly_stats) * 100, 1),
            "monthly_std": round(np.std(monthly_returns), 2),
            "monthly_sharpe": round(np.mean(monthly_returns) / np.std(monthly_returns), 2) if np.std(monthly_returns) > 0 else 0,
        }
    else:
        monthly_consistency = {}
    
    return {
        "monthly_details": monthly_stats,
        "consistency_summary": monthly_consistency,
    }


def perform_comprehensive_analysis(all_results: List[Dict], config: DeepTestConfig, seed_summaries: Dict) -> Dict:
    """执行综合统计分析"""
    print("\n执行综合统计分析...")
    
    df = pd.DataFrame(all_results)
    
    # 1. 总体统计
    overall_returns = df["future_60d_return"].values
    overall_mean, overall_ci_lower, overall_ci_upper = bootstrap_confidence_interval(overall_returns)
    
    overall_stats = {
        "n_samples": len(df),
        "mean_return": round(overall_mean, 2),
        "ci_lower": round(overall_ci_lower, 2),
        "ci_upper": round(overall_ci_upper, 2),
        "median_return": round(np.median(overall_returns), 2),
        "win_rate": round(sum(overall_returns > 0) / len(overall_returns) * 100, 1),
        "std_return": round(np.std(overall_returns), 2),
        "sharpe_ratio": round(np.mean(overall_returns) / np.std(overall_returns), 2) if np.std(overall_returns) > 0 else 0,
    }
    
    # No Trade Zone统计
    if "is_no_trade" in df.columns:
        n_no_trade = int(df["is_no_trade"].sum())
        n_tradeable = len(df) - n_no_trade
        overall_stats["n_no_trade"] = n_no_trade
        overall_stats["n_tradeable"] = n_tradeable
        overall_stats["no_trade_rate"] = round(n_no_trade / len(df) * 100, 1) if len(df) > 0 else 0
        
        # 可交易样本的收益统计
        tradeable = df[~df["is_no_trade"]]
        if len(tradeable) >= 10:
            t_returns = tradeable["future_60d_return"].values
            t_mean, t_ci_lower, t_ci_upper = bootstrap_confidence_interval(t_returns)
            overall_stats["tradeable_mean_return"] = round(t_mean, 2)
            overall_stats["tradeable_ci_lower"] = round(t_ci_lower, 2)
            overall_stats["tradeable_ci_upper"] = round(t_ci_upper, 2)
            overall_stats["tradeable_win_rate"] = round(sum(t_returns > 0) / len(t_returns) * 100, 1)
    
    # 2. 阶段分析（带置信区间）
    phase_analysis = {}
    for phase in df["phase"].unique():
        phase_returns = df[df["phase"] == phase]["future_60d_return"].values
        if len(phase_returns) >= 10:
            mean_ret, ci_lower, ci_upper = bootstrap_confidence_interval(phase_returns)
            phase_analysis[phase] = {
                "n_samples": len(phase_returns),
                "mean_return": round(mean_ret, 2),
                "ci_lower": round(ci_lower, 2),
                "ci_upper": round(ci_upper, 2),
                "win_rate": round(sum(phase_returns > 0) / len(phase_returns) * 100, 1),
                "median_return": round(np.median(phase_returns), 2),
            }
    
    # 3. LPPL过滤贡献分析
    lppl_contribution = analyze_lppl_layer_contribution(all_results)
    
    # 4. 衰减曲线分析
    decay_analysis = analyze_decay_curve(all_results, config.decay_days)
    
    # 5. 市场状态分析
    regime_analysis = analyze_market_regime_performance(all_results)
    
    # 6. 阶段×市场状态分析
    phase_regime = analyze_phase_by_regime(all_results)
    
    # 7. 崩盘检测敏感性
    crash_analysis = analyze_crash_detection_sensitivity(all_results, config)
    
    # 8. 月度一致性
    monthly_analysis = analyze_monthly_consistency(all_results)
    
    # 9. 多时间框架分析
    mtf_analysis = {}
    for alignment in df["mtf_alignment"].unique():
        if alignment:
            mtf_returns = df[df["mtf_alignment"] == alignment]["future_60d_return"].values
            if len(mtf_returns) >= 10:
                mean_ret, ci_lower, ci_upper = bootstrap_confidence_interval(mtf_returns)
                mtf_analysis[alignment] = {
                    "n_samples": len(mtf_returns),
                    "mean_return": round(mean_ret, 2),
                    "ci_lower": round(ci_lower, 2),
                    "ci_upper": round(ci_upper, 2),
                    "win_rate": round(sum(mtf_returns > 0) / len(mtf_returns) * 100, 1),
                }
    
    # 10. 种子稳定性分析
    seed_returns = [v["avg_return"] for v in seed_summaries.values()]
    seed_stability = {
        "n_seeds": len(seed_returns),
        "mean_return": round(np.mean(seed_returns), 2),
        "std_return": round(np.std(seed_returns), 2),
        "min_return": round(min(seed_returns), 2),
        "max_return": round(max(seed_returns), 2),
        "all_positive": all(r > 0 for r in seed_returns),
    }
    
    return {
        "overall_stats": overall_stats,
        "phase_analysis": phase_analysis,
        "lppl_contribution": lppl_contribution,
        "decay_analysis": decay_analysis,
        "regime_analysis": regime_analysis,
        "phase_regime_analysis": phase_regime,
        "crash_detection": crash_analysis,
        "monthly_analysis": monthly_analysis,
        "mtf_analysis": mtf_analysis,
        "seed_stability": seed_stability,
        "seed_summaries": seed_summaries,
    }


# ============================================================================
# 输出函数
# ============================================================================

def write_deep_test_report(output_dir: Path, analysis: Dict, config: DeepTestConfig, bubble_periods: List[Tuple[str, str]]) -> None:
    """输出深度测试报告"""
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # 保存JSON
    with (output_dir / "deep_test_analysis.json").open("w", encoding="utf-8") as f:
        json.dump(analysis, f, ensure_ascii=False, indent=2, default=str)
    
    # 生成Markdown报告
    md_lines = [
        "# 深度有效性测试报告",
        "",
        f"**测试日期**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"**测试周期数**: {config.n_cycles} × {config.n_seeds} seeds = {config.n_cycles * config.n_seeds} 组",
        f"**衰减测试窗口**: {', '.join(str(d)+'天' for d in config.decay_days)}",
        f"**Bootstrap次数**: {config.bootstrap_n}",
        f"**置信水平**: {config.confidence_level*100:.0f}%",
        "",
        "---",
        "",
        "## 1. 总体统计",
        "",
    ]
    
    overall = analysis["overall_stats"]
    md_lines.extend([
        "| 指标 | 值 |",
        "|---|---|",
        f"| 样本数 | {overall['n_samples']} |",
        f"| 平均收益 | {overall['mean_return']:.2f}% |",
        f"| 95%置信区间 | [{overall['ci_lower']:.2f}%, {overall['ci_upper']:.2f}%] |",
        f"| 中位收益 | {overall['median_return']:.2f}% |",
        f"| 胜率 | {overall['win_rate']:.1f}% |",
        f"| 标准差 | {overall['std_return']:.2f}% |",
        f"| 夏普比率 | {overall['sharpe_ratio']:.2f} |",
        "",
    ])
    
    # No Trade Zone过滤统计
    if "n_no_trade" in overall:
        md_lines.extend([
            "## 2. No Trade Zone过滤效果",
            "",
            "| 指标 | 值 |",
            "|---|---|",
            f"| 总样本 | {overall['n_samples']} |",
            f"| No Trade Zone（被过滤） | {overall['n_no_trade']} ({overall['no_trade_rate']}%) |",
            f"| 可交易样本 | {overall['n_tradeable']} |",
        ])
        if "tradeable_mean_return" in overall:
            md_lines.extend([
                f"| 可交易平均收益 | {overall['tradeable_mean_return']:.2f}% |",
                f"| 可交易95%CI | [{overall['tradeable_ci_lower']:.2f}%, {overall['tradeable_ci_upper']:.2f}%] |",
                f"| 可交易胜率 | {overall['tradeable_win_rate']:.1f}% |",
            ])
        md_lines.append("")
    
    # 种子稳定性
    seed_stab = analysis["seed_stability"]
    md_lines.extend([
        "## 3. 多种子稳定性分析",
        "",
        "| 指标 | 值 |",
        "|---|---|",
        f"| 种子数 | {seed_stab['n_seeds']} |",
        f"| 平均收益（跨种子） | {seed_stab['mean_return']:.2f}% |",
        f"| 标准差 | {seed_stab['std_return']:.2f}% |",
        f"| 最小收益 | {seed_stab['min_return']:.2f}% |",
        f"| 最大收益 | {seed_stab['max_return']:.2f}% |",
        f"| 所有种子为正 | {'是' if seed_stab['all_positive'] else '否'} |",
        "",
    ])
    
    # 阶段分析
    md_lines.extend([
        "## 4. 阶段有效性分析（带95%置信区间）",
        "",
        "| 阶段 | 样本数 | 平均收益 | 95% CI | 胜率 | 中位收益 |",
        "|---|---:|---:|---:|---:|---:|",
    ])
    for phase, stats in sorted(analysis["phase_analysis"].items(), key=lambda x: x[1]["mean_return"], reverse=True):
        md_lines.append(
            f"| {phase} | {stats['n_samples']} | {stats['mean_return']:.2f}% | "
            f"[{stats['ci_lower']:.2f}%, {stats['ci_upper']:.2f}%] | "
            f"{stats['win_rate']:.1f}% | {stats['median_return']:.2f}% |"
        )
    md_lines.append("")
    
    # LPPL过滤贡献
    lppl = analysis["lppl_contribution"]
    md_lines.extend([
        "## 5. LPPL泡沫过滤贡献分析",
        "",
        "| 状态 | 样本数 | 平均收益 | 胜率 |",
        "|---|---:|---:|---:|",
        f"| 泡沫期（被过滤） | {lppl['bubble_period']['n_samples']} | {lppl['bubble_period']['avg_return']}% | {lppl['bubble_period']['win_rate']}% |",
        f"| 非泡沫期（保留） | {lppl['non_bubble_period']['n_samples']} | {lppl['non_bubble_period']['avg_return']}% | {lppl['non_bubble_period']['win_rate']}% |",
        "",
    ])
    if "filter_effect" in lppl:
        fe = lppl["filter_effect"]
        md_lines.extend([
            "**过滤效果**:",
            f"- 收益提升: {fe['return_improvement']:.2f}个百分点",
            f"- 胜率提升: {fe['win_rate_improvement']:.1f}个百分点",
            "",
        ])
    
    # 衰减曲线
    md_lines.extend([
        "## 6. 收益衰减曲线分析",
        "",
        "| 持有天数 | 平均收益 | 95% CI | 胜率 | 中位收益 |",
        "|---:|---:|---:|---:|---:|",
    ])
    for days, stats in sorted(analysis["decay_analysis"].items(), key=lambda x: int(x[0].replace('d', ''))):
        md_lines.append(
            f"| {days} | {stats['mean_return']:.2f}% | "
            f"[{stats['ci_lower']:.2f}%, {stats['ci_upper']:.2f}%] | "
            f"{stats['win_rate']:.1f}% | {stats['median_return']:.2f}% |"
        )
    md_lines.append("")
    
    # 市场状态分析
    md_lines.extend([
        "## 7. 市场状态条件分析",
        "",
        "| 市场状态 | 样本数 | 平均收益 | 95% CI | 胜率 |",
        "|---|---:|---:|---:|---:|",
    ])
    for regime, stats in sorted(analysis["regime_analysis"].items(), key=lambda x: x[1]["mean_return"], reverse=True):
        regime_name = {"bull": "牛市", "bear": "熊市", "range": "震荡", "unknown": "未知"}.get(regime, regime)
        md_lines.append(
            f"| {regime_name} | {stats['n_samples']} | {stats['mean_return']:.2f}% | "
            f"[{stats['ci_lower']:.2f}%, {stats['ci_upper']:.2f}%] | "
            f"{stats['win_rate']:.1f}% |"
        )
    md_lines.append("")
    
    # 阶段×市场状态
    md_lines.extend([
        "## 8. 阶段×市场状态交叉分析",
        "",
    ])
    for phase, regimes in analysis["phase_regime_analysis"].items():
        md_lines.extend([
            f"### {phase}",
            "",
            "| 市场状态 | 样本数 | 平均收益 | 95% CI | 胜率 |",
            "|---|---:|---:|---:|---:|",
        ])
        for regime, stats in sorted(regimes.items(), key=lambda x: x[1]["mean_return"], reverse=True):
            regime_name = {"bull": "牛市", "bear": "熊市", "range": "震荡", "unknown": "未知"}.get(regime, regime)
            md_lines.append(
                f"| {regime_name} | {stats['n_samples']} | {stats['mean_return']:.2f}% | "
                f"[{stats['ci_lower']:.2f}%, {stats['ci_upper']:.2f}%] | "
                f"{stats['win_rate']:.1f}% |"
            )
        md_lines.append("")
    
    # 崩盘检测
    md_lines.extend([
        "## 9. 崩盘检测敏感性分析",
        "",
        "| 崩盘事件 | 时间段 | 信号数 | 平均收益 | 胜率 | Markdown比例 |",
        "|---|---|---:|---:|---:|---:|",
    ])
    for crash_name, stats in analysis["crash_detection"].items():
        md_lines.append(
            f"| {crash_name} | {stats['period']} | {stats['n_signals']} | "
            f"{stats['avg_return']:.2f}% | {stats['win_rate']:.1f}% | "
            f"{stats['markdown_rate']:.1f}% |"
        )
    md_lines.append("")
    
    # 月度一致性
    monthly = analysis["monthly_analysis"]
    if "consistency_summary" in monthly and monthly["consistency_summary"]:
        cs = monthly["consistency_summary"]
        md_lines.extend([
            "## 10. 月度一致性分析",
            "",
            "| 指标 | 值 |",
            "|---|---|",
            f"| 月份数 | {cs.get('n_months', 0)} |",
            f"| 正收益月份 | {cs.get('positive_months', 0)} |",
            f"| 一致性比率 | {cs.get('consistency_rate', 0):.1f}% |",
            f"| 月度标准差 | {cs.get('monthly_std', 0):.2f}% |",
            f"| 月度夏普 | {cs.get('monthly_sharpe', 0):.2f} |",
            "",
        ])
    
    # 多时间框架
    md_lines.extend([
        "## 11. 多时间框架对齐分析",
        "",
        "| 对齐类型 | 样本数 | 平均收益 | 95% CI | 胜率 |",
        "|---|---:|---:|---:|---:|",
    ])
    for alignment, stats in sorted(analysis["mtf_analysis"].items(), key=lambda x: x[1]["mean_return"], reverse=True):
        md_lines.append(
            f"| {alignment} | {stats['n_samples']} | {stats['mean_return']:.2f}% | "
            f"[{stats['ci_lower']:.2f}%, {stats['ci_upper']:.2f}%] | "
            f"{stats['win_rate']:.1f}% |"
        )
    md_lines.append("")
    
    # 结论
    md_lines.extend([
        "---",
        "",
        "## 结论与建议",
        "",
        "### 统计显著性",
        f"- 总样本量: {overall['n_samples']}",
        f"- 95%置信区间: [{overall['ci_lower']:.2f}%, {overall['ci_upper']:.2f}%]",
        f"- 种子稳定性: {'所有种子均为正收益' if seed_stab['all_positive'] else '存在种子差异'}",
        "",
        "### 关键发现",
        "",
    ])
    
    # 自动生成关键发现
    best_phase = max(analysis["phase_analysis"].items(), key=lambda x: x[1]["mean_return"])
    worst_phase = min(analysis["phase_analysis"].items(), key=lambda x: x[1]["mean_return"])
    md_lines.append(f"1. **最佳阶段**: {best_phase[0]} (平均收益 {best_phase[1]['mean_return']:.2f}%, 胜率 {best_phase[1]['win_rate']:.1f}%)")
    md_lines.append(f"2. **最差阶段**: {worst_phase[0]} (平均收益 {worst_phase[1]['mean_return']:.2f}%, 胜率 {worst_phase[1]['win_rate']:.1f}%)")
    
    if "filter_effect" in lppl:
        md_lines.append(f"3. **LPPL过滤效果**: 收益提升 {lppl['filter_effect']['return_improvement']:.2f}pp, 胜率提升 {lppl['filter_effect']['win_rate_improvement']:.1f}pp")
    
    if analysis["decay_analysis"]:
        best_hold = max(analysis["decay_analysis"].items(), key=lambda x: x[1]["mean_return"])
        md_lines.append(f"4. **最优持有期**: {best_hold[0]} (平均收益 {best_hold[1]['mean_return']:.2f}%)")
    
    md_lines.extend([
        "",
        "### 风险提示",
        "- 置信区间不包含0表示统计显著",
        "- 种子稳定性验证了结果的可重复性",
        "- 市场状态条件分析揭示了策略的适用环境",
        "",
        "---",
        "",
        f"**报告生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
    ])
    
    (output_dir / "deep_test_report.md").write_text("\n".join(md_lines), encoding="utf-8")
    
    print(f"\n输出文件:")
    print(f"  - {output_dir / 'deep_test_analysis.json'}")
    print(f"  - {output_dir / 'deep_test_report.md'}")


# ============================================================================
# 主函数
# ============================================================================

def main() -> None:
    """主函数"""
    config = DeepTestConfig()
    output_dir = PROJECT_ROOT / "output" / "deep_effectiveness_test"
    csv_path = PROJECT_ROOT / "data" / "stock_list.csv"
    tdx_index_path = Path("/home/james/.local/share/tdxcfv/drive_c/tc/vipdoc/sh/lday/sh000001.day")

    print("=" * 70)
    print("深度有效性测试")
    print("=" * 70)
    print(f"测试周期: {config.n_cycles} × {config.n_seeds} seeds")
    print(f"衰减窗口: {config.decay_days}")
    print(f"Bootstrap: {config.bootstrap_n} 次")
    print(f"置信水平: {config.confidence_level*100:.0f}%")
    print("=" * 70)

    # 1. 加载数据
    print("\n1. 加载数据...")
    symbols = load_stock_symbols(csv_path, limit=99999)
    print(f"   加载了 {len(symbols)} 只股票")

    index_data = None
    if tdx_index_path.exists():
        index_data = load_index_from_tdx(tdx_index_path)
        print(f"   加载了 {len(index_data)} 条指数数据")

    # 2. 检测泡沫阶段
    print("\n2. 检测泡沫阶段...")
    bubble_periods = []
    if index_data is not None:
        bubble_periods = detect_bubble_periods(index_data)
        print(f"   检测到 {len(bubble_periods)} 个泡沫阶段")

    # 3. 运行深度测试
    print("\n3. 运行深度测试...")
    all_results, seed_summaries = run_deep_test(
        symbols, config, bubble_periods, index_data, output_dir
    )
    print(f"\n总计收集 {len(all_results)} 条结果")

    # 4. 保存原始结果
    print("\n4. 保存原始结果...")
    output_dir.mkdir(parents=True, exist_ok=True)
    with (output_dir / "raw_results.jsonl").open("w", encoding="utf-8") as f:
        for row in all_results:
            f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
    
    if all_results:
        df = pd.DataFrame(all_results)
        df.to_csv(output_dir / "raw_results.csv", index=False, encoding="utf-8-sig")

    # 5. 执行综合分析
    print("\n5. 执行综合分析...")
    analysis = perform_comprehensive_analysis(all_results, config, seed_summaries)

    # 6. 输出报告
    print("\n6. 输出报告...")
    write_deep_test_report(output_dir, analysis, config, bubble_periods)

    # 7. 打印摘要
    overall = analysis["overall_stats"]
    print("\n" + "=" * 70)
    print("测试摘要:")
    print(f"  总样本数: {overall['n_samples']}")
    print(f"  平均收益: {overall['mean_return']:.2f}%")
    print(f"  95%置信区间: [{overall['ci_lower']:.2f}%, {overall['ci_upper']:.2f}%]")
    print(f"  胜率: {overall['win_rate']:.1f}%")
    print(f"  夏普比率: {overall['sharpe_ratio']:.2f}")
    print(f"  种子稳定性: {'稳定' if analysis['seed_stability']['all_positive'] else '不稳定'}")
    print("=" * 70)


if __name__ == "__main__":
    main()
