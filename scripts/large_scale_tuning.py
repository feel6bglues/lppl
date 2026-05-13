#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
大规模参数调优测试脚本
======================
扩大样本量到全部A股，增加测试规模，进行参数网格搜索

调优维度：
1. 阶段组合：markdown, distribution, accumulation
2. 市场状态：bull, bear, range
3. 持有期：30, 60, 90, 120, 150, 180天
4. 对齐类型：fully_aligned, weekly_daily_aligned, higher_timeframe_aligned
5. Wyckoff配置：不同回看窗口组合
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
from itertools import product

import numpy as np
import pandas as pd
import psutil

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
from src.parallel import get_optimal_workers, worker_init
from src.wyckoff.trading import calculate_wyckoff_return


# ============================================================================
# 调优配置
# ============================================================================

@dataclass
class TuningConfig:
    """调优配置"""
    # 测试规模
    n_cycles: int = 30
    n_seeds: int = 8
    stock_limit: int = 9999  # 全部A股
    
    # 参数网格
    phases_to_test: List[str] = field(default_factory=lambda: [
        ["markdown"],
        ["distribution"],
        ["accumulation"],
        ["markdown", "distribution"],
        ["markdown", "accumulation"],
        ["distribution", "accumulation"],
        ["markdown", "distribution", "accumulation"],
    ])
    
    regimes_to_test: List[str] = field(default_factory=lambda: [
        ["bull"],
        ["bear"],
        ["range"],
        ["bull", "bear"],
        ["bull", "range"],
        ["bear", "range"],
        ["bull", "bear", "range"],
    ])
    
    alignments_to_test: List[str] = field(default_factory=lambda: [
        ["fully_aligned"],
        ["weekly_daily_aligned"],
        ["higher_timeframe_aligned"],
        ["fully_aligned", "weekly_daily_aligned"],
        ["fully_aligned", "higher_timeframe_aligned"],
        ["weekly_daily_aligned", "higher_timeframe_aligned"],
    ])
    
    hold_periods: List[int] = field(default_factory=lambda: [30, 60, 90, 120, 150, 180])
    
    # Wyckoff配置
    wyckoff_configs: List[Dict] = field(default_factory=lambda: [
        {"lookback_days": 400, "weekly_lookback": 120, "monthly_lookback": 40},  # 默认
        {"lookback_days": 300, "weekly_lookback": 180, "monthly_lookback": 120},  # 300w180m120
        {"lookback_days": 300, "weekly_lookback": 120, "monthly_lookback": 40},  # 300w120m40
        {"lookback_days": 500, "weekly_lookback": 150, "monthly_lookback": 60},  # 500w150m60
    ])


# ============================================================================
# 数据加载
# ============================================================================

def load_all_stock_symbols(csv_path: Path, limit: int = 9999) -> List[Dict[str, str]]:
    """加载全部A股"""
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
    """检测泡沫阶段"""
    bubble_periods = []
    index_data = index_data.copy()
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
    
    merged = []
    curr_start, curr_end = bubble_periods[0]
    for start, end in bubble_periods[1:]:
        if start <= curr_end:
            curr_end = max(curr_end, end)
        else:
            merged.append((curr_start, curr_end))
            curr_start, curr_end = start, end
    merged.append((curr_start, curr_end))
    return merged


def is_in_bubble_period(date_str: str, bubble_periods: List[Tuple[str, str]]) -> bool:
    date = pd.Timestamp(date_str)
    for start, end in bubble_periods:
        if pd.Timestamp(start) <= date <= pd.Timestamp(end):
            return True
    return False


def classify_market_regime(index_data: pd.DataFrame, date_str: str) -> str:
    date = pd.Timestamp(date_str)
    hist_data = index_data[index_data['date'] <= date].tail(252)
    if len(hist_data) < 60:
        return "unknown"
    annual_return = (hist_data['close'].iloc[-1] / hist_data['close'].iloc[0]) ** (252 / len(hist_data)) - 1
    if annual_return > 0.15:
        return "bull"
    elif annual_return < -0.10:
        return "bear"
    else:
        return "range"


def generate_cycle_specs(n_cycles: int, seed: int, bubble_periods: List[Tuple[str, str]]) -> List[Dict]:
    random.seed(seed)
    specs = []
    attempts = 0
    while len(specs) < n_cycles and attempts < n_cycles * 100:
        attempts += 1
        year = random.randint(2012, 2025)
        month = random.randint(3, 11)
        day = random.randint(10, 25)
        date_str = f"{year}-{month:02d}-{day:02d}"
        if not is_in_bubble_period(date_str, bubble_periods):
            specs.append({
                "cycle_id": len(specs) + 1,
                "year": year,
                "as_of_date": date_str,
                "seed": seed,
            })
    while len(specs) < n_cycles:
        year = random.randint(2012, 2025)
        month = random.randint(3, 11)
        day = random.randint(10, 25)
        date_str = f"{year}-{month:02d}-{day:02d}"
        specs.append({
            "cycle_id": len(specs) + 1,
            "year": year,
            "as_of_date": date_str,
            "seed": seed,
        })
    return sorted(specs, key=lambda x: x["as_of_date"])


def calculate_multi_period_return(df: pd.DataFrame, as_of_date: str, periods: List[int],
                                   wyckoff_entry: Optional[float] = None,
                                   stop_loss: Optional[float] = None,
                                   first_target: Optional[float] = None) -> Dict[str, Optional[float]]:
    """计算多个持有期收益（支持Wyckoff交易逻辑）"""
    results = {}
    for days in periods:
        ret = calculate_wyckoff_return(df, as_of_date, days,
                                       wyckoff_entry=wyckoff_entry,
                                       stop_loss=stop_loss,
                                       first_target=first_target)
        results[f"return_{days}d"] = ret["return_pct"] if ret else None
    return results


# ============================================================================
# 单股票处理
# ============================================================================

def process_single_stock(args: tuple) -> List[Dict]:
    """处理单只股票"""
    symbol_info, cycle_specs, bubble_periods, index_data, wyckoff_config, hold_periods = args
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
            lookback_days=wyckoff_config["lookback_days"],
            weekly_lookback=wyckoff_config["weekly_lookback"],
            monthly_lookback=wyckoff_config["monthly_lookback"]
        )

        for spec in cycle_specs:
            as_of = pd.Timestamp(spec["as_of_date"])
            available_data = df[df["date"] <= as_of]
            if len(available_data) < 100:
                continue
            
            if is_in_bubble_period(spec["as_of_date"], bubble_periods):
                continue
            
            report = engine.analyze(available_data, symbol=symbol, period="日线", multi_timeframe=True)
            
            # 提取Wyckoff交易计划参数
            rr = report.risk_reward
            wyckoff_entry = rr.entry_price if rr and rr.entry_price and rr.entry_price > 0 else None
            stop_loss = rr.stop_loss if rr and rr.stop_loss and rr.stop_loss > 0 else None
            first_target = rr.first_target if rr and rr.first_target and rr.first_target > 0 else None
            signal_type = report.signal.signal_type
            is_no_trade = signal_type == "no_signal" or report.trading_plan.direction == "空仓观望"
            
            phase = report.structure.phase.value
            alignment = report.multi_timeframe.alignment if report.multi_timeframe else ""
            market_regime = classify_market_regime(index_data, spec["as_of_date"]) if index_data is not None else "unknown"
            
            period_returns = calculate_multi_period_return(df, spec["as_of_date"], hold_periods,
                wyckoff_entry=wyckoff_entry, stop_loss=stop_loss, first_target=first_target)
            
            # 基准收益
            benchmark_return = None
            if index_data is not None:
                benchmark_data = index_data[index_data["date"] > as_of].head(60)
                if len(benchmark_data) >= 48:
                    bm_entry = float(index_data[index_data["date"] <= as_of].iloc[-1]["close"])
                    bm_future = float(benchmark_data.iloc[-1]["close"])
                    benchmark_return = round((bm_future - bm_entry) / bm_entry * 100, 2)
            
            results.append({
                "cycle_id": spec["cycle_id"],
                "cycle_year": spec["year"],
                "as_of": spec["as_of_date"],
                "seed": spec["seed"],
                "symbol": symbol,
                "name": name,
                "phase": phase,
                "signal_type": signal_type,
                "is_no_trade": is_no_trade,
                "alignment": alignment,
                "market_regime": market_regime,
                "wyckoff_entry_price": round(wyckoff_entry, 3) if wyckoff_entry else None,
                "stop_loss": round(stop_loss, 3) if stop_loss else None,
                "first_target": round(first_target, 3) if first_target else None,
                "benchmark_60d_return": benchmark_return,
                **period_returns,
            })
    except Exception:
        pass

    return results


# ============================================================================
# 网格搜索
# ============================================================================

def bootstrap_ci(data: np.ndarray, n_bootstrap: int = 500, confidence: float = 0.95) -> Tuple[float, float, float]:
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


def evaluate_combination(df: pd.DataFrame, phases: List[str], regimes: List[str], 
                        alignments: List[str], period: int) -> Dict:
    """评估单个参数组合"""
    # 应用过滤
    filtered = df[
        (df["phase"].isin(phases)) &
        (df["market_regime"].isin(regimes)) &
        (df["alignment"].isin(alignments))
    ]
    
    if len(filtered) < 50:
        return {
            "n_samples": len(filtered),
            "mean_return": None,
            "valid": False,
        }
    
    col = f"return_{period}d"
    returns = filtered[col].dropna().values
    
    if len(returns) < 50:
        return {
            "n_samples": len(filtered),
            "mean_return": None,
            "valid": False,
        }
    
    mean_ret, ci_lower, ci_upper = bootstrap_ci(returns)
    win_rate = sum(returns > 0) / len(returns) * 100
    
    return {
        "n_samples": len(filtered),
        "filter_rate": round(len(filtered) / len(df) * 100, 2),
        "mean_return": round(mean_ret, 2),
        "ci_lower": round(ci_lower, 2),
        "ci_upper": round(ci_upper, 2),
        "win_rate": round(win_rate, 1),
        "median_return": round(np.median(returns), 2),
        "std_return": round(np.std(returns), 2),
        "valid": True,
    }


def run_grid_search(all_results: List[Dict], config: TuningConfig) -> Dict:
    """执行网格搜索"""
    df = pd.DataFrame(all_results)
    
    grid_search_results = []
    
    # 阶段×市场状态×对齐×持有期 的全网格搜索
    for phases in config.phases_to_test:
        for regimes in config.regimes_to_test:
            for alignments in config.alignments_to_test:
                for period in config.hold_periods:
                    eval_result = evaluate_combination(df, phases, regimes, alignments, period)
                    
                    if eval_result["valid"]:
                        grid_search_results.append({
                            "phases": phases,
                            "regimes": regimes,
                            "alignments": alignments,
                            "hold_period": period,
                            **eval_result,
                        })
    
    # 按收益排序
    grid_search_results.sort(key=lambda x: x["mean_return"], reverse=True)
    
    return {
        "total_combinations": len(grid_search_results),
        "valid_combinations": sum(1 for r in grid_search_results if r["valid"]),
        "top_20": grid_search_results[:20],
        "bottom_10": grid_search_results[-10:] if len(grid_search_results) >= 10 else [],
    }


def analyze_by_dimension(all_results: List[Dict]) -> Dict:
    """按维度分析"""
    df = pd.DataFrame(all_results)
    
    dimension_analysis = {}
    
    # 1. 阶段分析（60天）
    phase_analysis = {}
    for phase in df["phase"].unique():
        subset = df[df["phase"] == phase]
        if len(subset) >= 100:
            returns = subset["return_60d"].dropna().values
            if len(returns) >= 100:
                mean_ret, ci_lower, ci_upper = bootstrap_ci(returns)
                phase_analysis[phase] = {
                    "n_samples": len(subset),
                    "mean_return": round(mean_ret, 2),
                    "ci_lower": round(ci_lower, 2),
                    "ci_upper": round(ci_upper, 2),
                    "win_rate": round(sum(returns > 0) / len(returns) * 100, 1),
                }
    dimension_analysis["phase_analysis"] = phase_analysis
    
    # 2. 市场状态分析（60天）
    regime_analysis = {}
    for regime in df["market_regime"].unique():
        subset = df[df["market_regime"] == regime]
        if len(subset) >= 100:
            returns = subset["return_60d"].dropna().values
            if len(returns) >= 100:
                mean_ret, ci_lower, ci_upper = bootstrap_ci(returns)
                regime_analysis[regime] = {
                    "n_samples": len(subset),
                    "mean_return": round(mean_ret, 2),
                    "ci_lower": round(ci_lower, 2),
                    "ci_upper": round(ci_upper, 2),
                    "win_rate": round(sum(returns > 0) / len(returns) * 100, 1),
                }
    dimension_analysis["regime_analysis"] = regime_analysis
    
    # 3. 对齐分析（60天）
    alignment_analysis = {}
    for alignment in df["alignment"].unique():
        if alignment:
            subset = df[df["alignment"] == alignment]
            if len(subset) >= 100:
                returns = subset["return_60d"].dropna().values
                if len(returns) >= 100:
                    mean_ret, ci_lower, ci_upper = bootstrap_ci(returns)
                    alignment_analysis[alignment] = {
                        "n_samples": len(subset),
                        "mean_return": round(mean_ret, 2),
                        "ci_lower": round(ci_lower, 2),
                        "ci_upper": round(ci_upper, 2),
                        "win_rate": round(sum(returns > 0) / len(returns) * 100, 1),
                    }
    dimension_analysis["alignment_analysis"] = alignment_analysis
    
    # 4. 持有期分析
    period_analysis = {}
    for days in [30, 60, 90, 120, 150, 180]:
        col = f"return_{days}d"
        if col in df.columns:
            valid = df[col].dropna()
            if len(valid) >= 100:
                mean_ret, ci_lower, ci_upper = bootstrap_ci(valid.values)
                period_analysis[f"{days}d"] = {
                    "n_samples": len(valid),
                    "mean_return": round(mean_ret, 2),
                    "ci_lower": round(ci_lower, 2),
                    "ci_upper": round(ci_upper, 2),
                    "win_rate": round(sum(valid > 0) / len(valid) * 100, 1),
                }
    dimension_analysis["period_analysis"] = period_analysis
    
    # 5. 阶段×市场状态交叉
    phase_regime_cross = {}
    for phase in df["phase"].unique():
        for regime in df["market_regime"].unique():
            subset = df[(df["phase"] == phase) & (df["market_regime"] == regime)]
            if len(subset) >= 50:
                returns = subset["return_60d"].dropna().values
                if len(returns) >= 50:
                    mean_ret, ci_lower, ci_upper = bootstrap_ci(returns)
                    key = f"{phase}_{regime}"
                    phase_regime_cross[key] = {
                        "n_samples": len(subset),
                        "mean_return": round(mean_ret, 2),
                        "ci_lower": round(ci_lower, 2),
                        "ci_upper": round(ci_upper, 2),
                        "win_rate": round(sum(returns > 0) / len(returns) * 100, 1),
                    }
    dimension_analysis["phase_regime_cross"] = phase_regime_cross
    
    # 6. 交叉分析（阶段×对齐）
    phase_alignment_cross = {}
    for phase in df["phase"].unique():
        for alignment in df["alignment"].unique():
            if alignment:
                subset = df[(df["phase"] == phase) & (df["alignment"] == alignment)]
                if len(subset) >= 50:
                    returns = subset["return_60d"].dropna().values
                    if len(returns) >= 50:
                        mean_ret, ci_lower, ci_upper = bootstrap_ci(returns)
                        key = f"{phase}_{alignment}"
                        phase_alignment_cross[key] = {
                            "n_samples": len(subset),
                            "mean_return": round(mean_ret, 2),
                            "ci_lower": round(ci_lower, 2),
                            "ci_upper": round(ci_upper, 2),
                            "win_rate": round(sum(returns > 0) / len(returns) * 100, 1),
                        }
    dimension_analysis["phase_alignment_cross"] = phase_alignment_cross
    
    # 7. 种子稳定性
    seed_analysis = {}
    for seed in df["seed"].unique():
        subset = df[df["seed"] == seed]
        if len(subset) >= 100:
            returns = subset["return_60d"].dropna().values
            if len(returns) >= 100:
                mean_ret, _, _ = bootstrap_ci(returns)
                seed_analysis[f"seed_{seed}"] = {
                    "n_samples": len(subset),
                    "mean_return": round(mean_ret, 2),
                }
    dimension_analysis["seed_analysis"] = seed_analysis
    
    return dimension_analysis


# ============================================================================
# 运行测试
# ============================================================================

def run_large_scale_test(
    symbols: List[Dict[str, str]],
    config: TuningConfig,
    bubble_periods: List[Tuple[str, str]],
    index_data: pd.DataFrame,
    output_dir: Path,
) -> Tuple[List[Dict], Dict]:
    """运行大规模测试"""
    all_results = []
    seed_summaries = {}
    
    # 使用默认Wyckoff配置
    wyckoff_config = config.wyckoff_configs[0]
    
    for seed in range(config.n_seeds):
        print(f"\n   Seed {seed+1}/{config.n_seeds}:")
        cycle_specs = generate_cycle_specs(config.n_cycles, seed=42+seed, bubble_periods=bubble_periods)
        
        args_list = [(s, cycle_specs, bubble_periods, index_data, wyckoff_config, config.hold_periods) for s in symbols]
        
        seed_results = []
        completed = 0
        max_workers = get_optimal_workers()
        batch_size = max_workers * 4
        
        with ProcessPoolExecutor(max_workers=max_workers, initializer=worker_init) as executor:
            for batch_start in range(0, len(args_list), batch_size):
                batch = args_list[batch_start:batch_start + batch_size]
                futures = {executor.submit(process_single_stock, args): args[0] for args in batch}
                for future in as_completed(futures):
                    completed += 1
                    try:
                        results = future.result(timeout=300)
                        seed_results.extend(results)
                    except Exception:
                        pass
                    if completed % 500 == 0:
                        print(f"     已处理 {completed}/{len(symbols)} 只股票...")
        
        all_results.extend(seed_results)
        
        avg_returns = {}
        for period in config.hold_periods:
            col = f"return_{period}d"
            valid = [r[col] for r in seed_results if r.get(col) is not None]
            avg_returns[f"avg_{period}d"] = round(np.mean(valid), 2) if valid else 0
        
        seed_summaries[seed] = {
            "n_samples": len(seed_results),
            **avg_returns,
        }
        
        print(f"     样本数: {len(seed_results)}")
        for period in [60, 120, 180]:
            print(f"     {period}天平均收益: {avg_returns.get(f'avg_{period}d', 'N/A')}%")
    
    return all_results, seed_summaries


def generate_tuning_report(grid_search: Dict, dimension_analysis: Dict, 
                          seed_summaries: Dict, config: TuningConfig,
                          output_dir: Path) -> None:
    """生成调优报告"""
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # 保存JSON
    with (output_dir / "tuning_analysis.json").open("w", encoding="utf-8") as f:
        json.dump({
            "grid_search": grid_search,
            "dimension_analysis": dimension_analysis,
            "seed_summaries": seed_summaries,
        }, f, ensure_ascii=False, indent=2, default=str)
    
    # 生成Markdown报告
    md = [
        "# 大规模参数调优报告",
        "",
        f"**测试日期**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"**测试规模**: {config.n_seeds} seeds × {config.n_cycles} cycles × {len(symbols)} stocks",
        "",
        "---",
        "",
        "## 1. 网格搜索结果概览",
        "",
        "| 指标 | 值 |",
        "|---|---|",
        f"| 总组合数 | {grid_search['total_combinations']} |",
        f"| 有效组合数 | {grid_search['valid_combinations']} |",
        "",
        "## 2. Top 20 最优组合",
        "",
        "| 排名 | 阶段 | 市场状态 | 对齐 | 持有期 | 样本数 | 平均收益 | 95% CI | 胜率 |",
        "|:---:|:---|:---|:---|---:|---:|---:|---:|---:|",
    ]
    
    for i, combo in enumerate(grid_search["top_20"][:20], 1):
        phases_str = "+".join(combo["phases"])
        regimes_str = "+".join(combo["regimes"])
        alignments_str = "+".join(combo["alignments"])
        md.append(
            f"| {i} | {phases_str} | {regimes_str} | {alignments_str} | "
            f"{combo['hold_period']}天 | {combo['n_samples']} | "
            f"{combo['mean_return']:.2f}% | [{combo['ci_lower']:.2f}%, {combo['ci_upper']:.2f}%] | "
            f"{combo['win_rate']:.1f}% |"
        )
    md.append("")
    
    # 阶段分析
    md.extend([
        "## 3. 维度分析",
        "",
        "### 3.1 阶段分析（60天）",
        "",
        "| 阶段 | 样本数 | 平均收益 | 95% CI | 胜率 |",
        "|---|---:|---:|---:|---:|",
    ])
    for phase, stats in sorted(dimension_analysis["phase_analysis"].items(), 
                               key=lambda x: x[1]["mean_return"], reverse=True):
        md.append(
            f"| {phase} | {stats['n_samples']} | {stats['mean_return']:.2f}% | "
            f"[{stats['ci_lower']:.2f}%, {stats['ci_upper']:.2f}%] | {stats['win_rate']:.1f}% |"
        )
    md.append("")
    
    # 市场状态分析
    md.extend([
        "### 3.2 市场状态分析（60天）",
        "",
        "| 市场状态 | 样本数 | 平均收益 | 95% CI | 胜率 |",
        "|---|---:|---:|---:|---:|",
    ])
    for regime, stats in sorted(dimension_analysis["regime_analysis"].items(), 
                                key=lambda x: x[1]["mean_return"], reverse=True):
        regime_name = {"bull": "牛市", "bear": "熊市", "range": "震荡", "unknown": "未知"}.get(regime, regime)
        md.append(
            f"| {regime_name} | {stats['n_samples']} | {stats['mean_return']:.2f}% | "
            f"[{stats['ci_lower']:.2f}%, {stats['ci_upper']:.2f}%] | {stats['win_rate']:.1f}% |"
        )
    md.append("")
    
    # 对齐分析
    md.extend([
        "### 3.3 时间框架对齐分析（60天）",
        "",
        "| 对齐类型 | 样本数 | 平均收益 | 95% CI | 胜率 |",
        "|---|---:|---:|---:|---:|",
    ])
    for alignment, stats in sorted(dimension_analysis["alignment_analysis"].items(), 
                                   key=lambda x: x[1]["mean_return"], reverse=True):
        md.append(
            f"| {alignment} | {stats['n_samples']} | {stats['mean_return']:.2f}% | "
            f"[{stats['ci_lower']:.2f}%, {stats['ci_upper']:.2f}%] | {stats['win_rate']:.1f}% |"
        )
    md.append("")
    
    # 持有期分析
    md.extend([
        "### 3.4 持有期分析",
        "",
        "| 持有期 | 样本数 | 平均收益 | 95% CI | 胜率 |",
        "|---:|---:|---:|---:|---:|",
    ])
    for period, stats in sorted(dimension_analysis["period_analysis"].items(), 
                                key=lambda x: int(x[0].replace('d', ''))):
        md.append(
            f"| {period} | {stats['n_samples']} | {stats['mean_return']:.2f}% | "
            f"[{stats['ci_lower']:.2f}%, {stats['ci_upper']:.2f}%] | {stats['win_rate']:.1f}% |"
        )
    md.append("")
    
    # 阶段×市场状态交叉
    md.extend([
        "### 3.5 阶段×市场状态交叉分析",
        "",
        "| 组合 | 样本数 | 平均收益 | 95% CI | 胜率 |",
        "|---|---:|---:|---:|---:|",
    ])
    for key, stats in sorted(dimension_analysis["phase_regime_cross"].items(), 
                            key=lambda x: x[1]["mean_return"], reverse=True)[:15]:
        parts = key.split("_")
        phase = parts[0]
        regime = parts[1]
        regime_name = {"bull": "牛市", "bear": "熊市", "range": "震荡"}.get(regime, regime)
        md.append(
            f"| {phase}+{regime_name} | {stats['n_samples']} | {stats['mean_return']:.2f}% | "
            f"[{stats['ci_lower']:.2f}%, {stats['ci_upper']:.2f}%] | {stats['win_rate']:.1f}% |"
        )
    md.append("")
    
    # 种子稳定性
    md.extend([
        "### 3.6 种子稳定性分析",
        "",
        "| 种子 | 样本数 | 60天平均收益 | 120天平均收益 | 180天平均收益 |",
        "|---|---:|---:|---:|---:|",
    ])
    for seed_key, stats in sorted(dimension_analysis.get("seed_analysis", {}).items()):
        seed_idx = seed_key.replace("seed_", "")
        seed_stats = seed_summaries.get(int(seed_idx), {})
        md.append(
            f"| {seed_key} | {stats['n_samples']} | {stats['mean_return']:.2f}% | "
            f"{seed_stats.get('avg_120d', 'N/A')}% | {seed_stats.get('avg_180d', 'N/A')}% |"
        )
    md.append("")
    
    # 结论
    md.extend([
        "---",
        "",
        "## 4. 调优结论",
        "",
    ])
    
    # 自动生成最优组合推荐
    if grid_search["top_20"]:
        best = grid_search["top_20"][0]
        md.extend([
            "### 最优组合",
            "",
            "```yaml",
            f"最优配置:",
            f"  阶段: {best['phases']}",
            f"  市场状态: {best['regimes']}",
            f"  对齐: {best['alignments']}",
            f"  持有期: {best['hold_period']}天",
            f"  预期收益: {best['mean_return']:.2f}%",
            f"  95% CI: [{best['ci_lower']:.2f}%, {best['ci_upper']:.2f}%]",
            f"  胜率: {best['win_rate']:.1f}%",
            f"  过滤率: {best['filter_rate']:.2f}%",
            "```",
            "",
        ])
    
    # 稳健组合推荐（高样本量）
    robust_combos = [c for c in grid_search["top_20"] if c["n_samples"] >= 1000]
    if robust_combos:
        best_robust = robust_combos[0]
        md.extend([
            "### 稳健组合（样本量≥1000）",
            "",
            "```yaml",
            f"稳健配置:",
            f"  阶段: {best_robust['phases']}",
            f"  市场状态: {best_robust['regimes']}",
            f"  对齐: {best_robust['alignments']}",
            f"  持有期: {best_robust['hold_period']}天",
            f"  预期收益: {best_robust['mean_return']:.2f}%",
            f"  样本数: {best_robust['n_samples']}",
            "```",
            "",
        ])
    
    md.extend([
        "---",
        "",
        f"**报告生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
    ])
    
    (output_dir / "tuning_report.md").write_text("\n".join(md), encoding="utf-8")
    
    print(f"\n输出文件:")
    print(f"  - {output_dir / 'tuning_analysis.json'}")
    print(f"  - {output_dir / 'tuning_report.md'}")


# ============================================================================
# 主函数
# ============================================================================

def main():
    global symbols
    
    config = TuningConfig()
    output_dir = PROJECT_ROOT / "output" / "large_scale_tuning"
    csv_path = PROJECT_ROOT / "data" / "stock_list.csv"
    tdx_index_path = Path("/home/james/.local/share/tdxcfv/drive_c/tc/vipdoc/sh/lday/sh000001.day")

    print("=" * 70)
    print("大规模参数调优测试")
    print("=" * 70)
    print(f"测试规模: {config.n_seeds} seeds × {config.n_cycles} cycles")
    print(f"股票数量: 全部A股")
    print("=" * 70)

    # 1. 加载数据
    print("\n1. 加载数据...")
    symbols = load_all_stock_symbols(csv_path, limit=config.stock_limit)
    print(f"   加载了 {len(symbols)} 只股票")

    index_data = None
    if tdx_index_path.exists():
        index_data = load_index_from_tdx(tdx_index_path)
        print(f"   加载了 {len(index_data)} 条指数数据")

    # 2. 检测泡沫
    print("\n2. 检测泡沫阶段...")
    bubble_periods = detect_bubble_periods(index_data) if index_data is not None else []
    print(f"   检测到 {len(bubble_periods)} 个泡沫阶段")

    # 3. 运行大规模测试
    print("\n3. 运行大规模测试...")
    all_results, seed_summaries = run_large_scale_test(symbols, config, bubble_periods, index_data, output_dir)
    
    print(f"\n   总样本数: {len(all_results)}")

    # 4. 保存原始数据
    print("\n4. 保存原始数据...")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    df = pd.DataFrame(all_results)
    df.to_csv(output_dir / "large_scale_raw_results.csv", index=False, encoding="utf-8-sig")
    
    with (output_dir / "large_scale_raw_results.jsonl").open("w", encoding="utf-8") as f:
        for row in all_results:
            f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")

    # 5. 网格搜索
    print("\n5. 执行网格搜索...")
    grid_search = run_grid_search(all_results, config)
    print(f"   有效组合数: {grid_search['valid_combinations']}")

    # 6. 维度分析
    print("\n6. 执行维度分析...")
    dimension_analysis = analyze_by_dimension(all_results)

    # 7. 生成报告
    print("\n7. 生成调优报告...")
    generate_tuning_report(grid_search, dimension_analysis, seed_summaries, config, output_dir)

    # 8. 打印摘要
    print("\n" + "=" * 70)
    print("调优摘要:")
    
    if grid_search["top_20"]:
        best = grid_search["top_20"][0]
        print(f"  最优组合:")
        print(f"    阶段: {best['phases']}")
        print(f"    市场状态: {best['regimes']}")
        print(f"    对齐: {best['alignments']}")
        print(f"    持有期: {best['hold_period']}天")
        print(f"    预期收益: {best['mean_return']:.2f}%")
        print(f"    95% CI: [{best['ci_lower']:.2f}%, {best['ci_upper']:.2f}%]")
        print(f"    胜率: {best['win_rate']:.1f}%")
    
    print("=" * 70)


if __name__ == "__main__":
    main()
