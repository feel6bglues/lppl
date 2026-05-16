#!/usr/bin/env python3
# RESEARCH ONLY — not production code
# -*- coding: utf-8 -*-
"""
中等规模深度测试 - 平衡速度和统计严谨性
"""

from __future__ import annotations

import csv
import json
import random
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
from src.parallel import get_optimal_workers, worker_init
from src.wyckoff.trading import calculate_wyckoff_return


def load_stock_symbols(csv_path: Path, limit: int = 500) -> List[Dict[str, str]]:
    """加载股票列表"""
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
    """检查是否在泡沫期"""
    date = pd.Timestamp(date_str)
    for start, end in bubble_periods:
        if pd.Timestamp(start) <= date <= pd.Timestamp(end):
            return True
    return False


def classify_market_regime(index_data: pd.DataFrame, date_str: str) -> str:
    """分类市场状态"""
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
    """生成测试周期"""
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


def calculate_future_return(df: pd.DataFrame, as_of_date: str, days: int = 60) -> Optional[Dict[str, float]]:
    """计算未来收益"""
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
        "return_pct": round(return_pct, 2),
        "max_gain_pct": round(max_gain_pct, 2),
        "max_drawdown_pct": round(max_drawdown_pct, 2),
    }


def process_single_stock(args: tuple) -> List[Dict]:
    """处理单只股票"""
    symbol_info, cycle_specs, bubble_periods, index_data = args
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
            lookback_days=400,
            weekly_lookback=120,
            monthly_lookback=40
        )

        for spec in cycle_specs:
            as_of = pd.Timestamp(spec["as_of_date"])
            available_data = df[df["date"] <= as_of]
            if len(available_data) < 100:
                continue
            
            report = engine.analyze(available_data, symbol=symbol, period="日线", multi_timeframe=True)
            
            # 提取Wyckoff交易计划参数
            rr = report.risk_reward
            wyckoff_entry = rr.entry_price if rr and rr.entry_price and rr.entry_price > 0 else None
            stop_loss = rr.stop_loss if rr and rr.stop_loss and rr.stop_loss > 0 else None
            first_target = rr.first_target if rr and rr.first_target and rr.first_target > 0 else None
            signal_type = report.signal.signal_type
            is_no_trade = signal_type == "no_signal" or report.trading_plan.direction == "空仓观望"
            
            future_return = calculate_wyckoff_return(df, spec["as_of_date"], days=60,
                wyckoff_entry=wyckoff_entry, stop_loss=stop_loss, first_target=first_target)
            if future_return is None:
                continue
            
            in_bubble = is_in_bubble_period(spec["as_of_date"], bubble_periods)
            market_regime = classify_market_regime(index_data, spec["as_of_date"]) if index_data is not None else "unknown"
            
            # 衰减收益（使用Wyckoff交易逻辑）
            decay_returns = {}
            for days in [10, 20, 30, 60, 90, 120, 180]:
                ret = calculate_wyckoff_return(df, spec["as_of_date"], days,
                    wyckoff_entry=wyckoff_entry, stop_loss=stop_loss, first_target=first_target)
                decay_returns[f"return_{days}d"] = ret["return_pct"] if ret else None
            
            results.append({
                "cycle_id": spec["cycle_id"],
                "cycle_year": spec["year"],
                "as_of": spec["as_of_date"],
                "seed": spec["seed"],
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
                "in_bubble": in_bubble,
                "market_regime": market_regime,
                "future_60d_return": future_return["return_pct"],
                "future_60d_max_gain": future_return["max_gain_pct"],
                "future_60d_max_drawdown": future_return["max_drawdown_pct"],
                **decay_returns,
            })
    except Exception:
        pass

    return results


def bootstrap_ci(data: np.ndarray, n_bootstrap: int = 1000, confidence: float = 0.95) -> Tuple[float, float, float]:
    """Bootstrap置信区间"""
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


def analyze_phase_by_regime(df: pd.DataFrame) -> Dict:
    """分析阶段×市场状态"""
    phase_regime = {}
    for phase in df["phase"].unique():
        phase_regime[phase] = {}
        for regime in df["market_regime"].unique():
            subset = df[(df["phase"] == phase) & (df["market_regime"] == regime)]
            if len(subset) >= 20:
                returns = subset["future_60d_return"].values
                mean_ret, ci_lower, ci_upper = bootstrap_ci(returns)
                phase_regime[phase][regime] = {
                    "n_samples": len(subset),
                    "mean_return": round(mean_ret, 2),
                    "ci_lower": round(ci_lower, 2),
                    "ci_upper": round(ci_upper, 2),
                    "win_rate": round(sum(returns > 0) / len(returns) * 100, 1),
                }
    return phase_regime


def analyze_crash_sensitivity(df: pd.DataFrame) -> Dict:
    """分析崩盘检测敏感性"""
    crashes = [
        ("2015-06-01", "2015-09-30", "2015年股灾"),
        ("2018-01-01", "2018-12-31", "2018年熊市"),
        ("2020-01-15", "2020-03-31", "2020年COVID"),
        ("2022-01-01", "2022-10-31", "2022年调整"),
    ]
    
    crash_analysis = {}
    for crash_start, crash_end, crash_name in crashes:
        crash_start_dt = pd.Timestamp(crash_start)
        crash_end_dt = pd.Timestamp(crash_end)
        pre_crash_start = crash_start_dt - pd.Timedelta(days=30)
        
        crash_signals = df[
            (pd.to_datetime(df["as_of"]) >= pre_crash_start) &
            (pd.to_datetime(df["as_of"]) <= crash_end_dt)
        ]
        
        if len(crash_signals) > 0:
            crash_returns = crash_signals["future_60d_return"].values
            phase_dist = crash_signals["phase"].value_counts().to_dict()
            
            crash_analysis[crash_name] = {
                "period": f"{crash_start} ~ {crash_end}",
                "n_signals": len(crash_signals),
                "avg_return": round(np.mean(crash_returns), 2),
                "win_rate": round(sum(crash_returns > 0) / len(crash_returns) * 100, 1),
                "markdown_rate": round(sum(crash_signals["phase"] == "markdown") / len(crash_signals) * 100, 1),
                "phase_distribution": phase_dist,
            }
    
    return crash_analysis


def analyze_monthly_consistency(df: pd.DataFrame) -> Dict:
    """分析月度一致性"""
    df["as_of_month"] = pd.to_datetime(df["as_of"]).dt.to_period("M")
    
    monthly_stats = {}
    for month, group in df.groupby("as_of_month"):
        if len(group) >= 20:
            returns = group["future_60d_return"].values
            monthly_stats[str(month)] = {
                "n_samples": len(group),
                "mean_return": round(np.mean(returns), 2),
                "win_rate": round(sum(returns > 0) / len(returns) * 100, 1),
            }
    
    if monthly_stats:
        monthly_returns = [v["mean_return"] for v in monthly_stats.values()]
        positive_months = sum(1 for r in monthly_returns if r > 0)
        consistency = {
            "n_months": len(monthly_stats),
            "positive_months": positive_months,
            "consistency_rate": round(positive_months / len(monthly_stats) * 100, 1),
            "monthly_std": round(np.std(monthly_returns), 2),
        }
    else:
        consistency = {}
    
    return {"monthly_details": monthly_stats, "consistency_summary": consistency}


def analyze_comprehensive(all_results: List[Dict], seed_summaries: Dict) -> Dict:
    """综合分析"""
    df = pd.DataFrame(all_results)
    
    # 总体统计
    overall_returns = df["future_60d_return"].values
    overall_mean, overall_ci_lower, overall_ci_upper = bootstrap_ci(overall_returns)
    
    overall_stats = {
        "n_samples": len(df),
        "mean_return": round(overall_mean, 2),
        "ci_lower": round(overall_ci_lower, 2),
        "ci_upper": round(overall_ci_upper, 2),
        "median_return": round(np.median(overall_returns), 2),
        "win_rate": round(sum(overall_returns > 0) / len(overall_returns) * 100, 1),
        "std_return": round(np.std(overall_returns), 2),
    }
    
    # 阶段分析
    phase_analysis = {}
    for phase in df["phase"].unique():
        phase_returns = df[df["phase"] == phase]["future_60d_return"].values
        if len(phase_returns) >= 20:
            mean_ret, ci_lower, ci_upper = bootstrap_ci(phase_returns)
            phase_analysis[phase] = {
                "n_samples": len(phase_returns),
                "mean_return": round(mean_ret, 2),
                "ci_lower": round(ci_lower, 2),
                "ci_upper": round(ci_upper, 2),
                "win_rate": round(sum(phase_returns > 0) / len(phase_returns) * 100, 1),
                "median_return": round(np.median(phase_returns), 2),
            }
    
    # LPPL过滤分析
    bubble_results = df[df["in_bubble"] == True]
    non_bubble_results = df[df["in_bubble"] == False]
    
    lppl_analysis = {
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
    
    if len(bubble_results) > 0 and len(non_bubble_results) > 0:
        lppl_analysis["filter_effect"] = {
            "return_improvement": round(non_bubble_results["future_60d_return"].mean() - bubble_results["future_60d_return"].mean(), 2),
            "win_rate_improvement": round(
                sum(non_bubble_results["future_60d_return"] > 0) / len(non_bubble_results) * 100 -
                sum(bubble_results["future_60d_return"] > 0) / len(bubble_results) * 100, 1
            ),
        }
    
    # 衰减曲线
    decay_analysis = {}
    for days in [10, 20, 30, 60, 90, 120, 180]:
        col = f"return_{days}d"
        if col in df.columns:
            valid_data = df[col].dropna()
            if len(valid_data) > 0:
                mean_ret, ci_lower, ci_upper = bootstrap_ci(valid_data.values)
                decay_analysis[f"{days}d"] = {
                    "n_samples": len(valid_data),
                    "mean_return": round(mean_ret, 2),
                    "ci_lower": round(ci_lower, 2),
                    "ci_upper": round(ci_upper, 2),
                    "win_rate": round(sum(valid_data > 0) / len(valid_data) * 100, 1),
                }
    
    # 市场状态分析
    regime_analysis = {}
    for regime in df["market_regime"].unique():
        regime_returns = df[df["market_regime"] == regime]["future_60d_return"].values
        if len(regime_returns) >= 20:
            mean_ret, ci_lower, ci_upper = bootstrap_ci(regime_returns)
            regime_analysis[regime] = {
                "n_samples": len(regime_returns),
                "mean_return": round(mean_ret, 2),
                "ci_lower": round(ci_lower, 2),
                "ci_upper": round(ci_upper, 2),
                "win_rate": round(sum(regime_returns > 0) / len(regime_returns) * 100, 1),
            }
    
    # 阶段×市场状态
    phase_regime = analyze_phase_by_regime(df)
    
    # 崩盘检测
    crash_analysis = analyze_crash_sensitivity(df)
    
    # 月度一致性
    monthly_analysis = analyze_monthly_consistency(df)
    
    # 多时间框架
    mtf_analysis = {}
    for alignment in df["mtf_alignment"].unique():
        if alignment:
            mtf_returns = df[df["mtf_alignment"] == alignment]["future_60d_return"].values
            if len(mtf_returns) >= 20:
                mean_ret, ci_lower, ci_upper = bootstrap_ci(mtf_returns)
                mtf_analysis[alignment] = {
                    "n_samples": len(mtf_returns),
                    "mean_return": round(mean_ret, 2),
                    "ci_lower": round(ci_lower, 2),
                    "ci_upper": round(ci_upper, 2),
                    "win_rate": round(sum(mtf_returns > 0) / len(mtf_returns) * 100, 1),
                }
    
    # 种子稳定性
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
        "lppl_analysis": lppl_analysis,
        "decay_analysis": decay_analysis,
        "regime_analysis": regime_analysis,
        "phase_regime_analysis": phase_regime,
        "crash_detection": crash_analysis,
        "monthly_analysis": monthly_analysis,
        "mtf_analysis": mtf_analysis,
        "seed_stability": seed_stability,
        "seed_summaries": seed_summaries,
    }


def generate_report(analysis: Dict, output_dir: Path) -> None:
    """生成报告"""
    output_dir.mkdir(parents=True, exist_ok=True)
    
    with (output_dir / "medium_test_analysis.json").open("w", encoding="utf-8") as f:
        json.dump(analysis, f, ensure_ascii=False, indent=2, default=str)
    
    overall = analysis["overall_stats"]
    lppl = analysis["lppl_analysis"]
    seed_stab = analysis["seed_stability"]
    
    md = [
        "# 深度有效性测试报告（中等规模）",
        "",
        f"**测试日期**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "---",
        "",
        "## 1. 总体统计",
        "",
        "| 指标 | 值 |",
        "|---|---|",
        f"| 样本数 | {overall['n_samples']} |",
        f"| 平均收益 | {overall['mean_return']:.2f}% |",
        f"| 95%置信区间 | [{overall['ci_lower']:.2f}%, {overall['ci_upper']:.2f}%] |",
        f"| 中位收益 | {overall['median_return']:.2f}% |",
        f"| 胜率 | {overall['win_rate']:.1f}% |",
        f"| 标准差 | {overall['std_return']:.2f}% |",
        "",
    ]
    
    # 种子稳定性
    md.extend([
        "## 2. 多种子稳定性分析",
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
    
    # LPPL过滤
    md.extend([
        "## 3. LPPL泡沫过滤效果",
        "",
        "| 状态 | 样本数 | 平均收益 | 胜率 |",
        "|---|---:|---:|---:|",
        f"| 泡沫期（被过滤） | {lppl['bubble_period']['n_samples']} | {lppl['bubble_period']['avg_return']}% | {lppl['bubble_period']['win_rate']}% |",
        f"| 非泡沫期（保留） | {lppl['non_bubble_period']['n_samples']} | {lppl['non_bubble_period']['avg_return']}% | {lppl['non_bubble_period']['win_rate']}% |",
        "",
    ])
    
    if "filter_effect" in lppl:
        fe = lppl["filter_effect"]
        md.extend([
            "**过滤效果**:",
            f"- 收益提升: {fe['return_improvement']:.2f}个百分点",
            f"- 胜率提升: {fe['win_rate_improvement']:.1f}个百分点",
            "",
        ])
    
    # 阶段分析
    md.extend([
        "## 4. 阶段有效性分析（带95%置信区间）",
        "",
        "| 阶段 | 样本数 | 平均收益 | 95% CI | 胜率 | 中位收益 |",
        "|---|---:|---:|---:|---:|---:|",
    ])
    for phase, stats in sorted(analysis["phase_analysis"].items(), key=lambda x: x[1]["mean_return"], reverse=True):
        md.append(
            f"| {phase} | {stats['n_samples']} | {stats['mean_return']:.2f}% | "
            f"[{stats['ci_lower']:.2f}%, {stats['ci_upper']:.2f}%] | "
            f"{stats['win_rate']:.1f}% | {stats['median_return']:.2f}% |"
        )
    md.append("")
    
    # 衰减曲线
    md.extend([
        "## 5. 收益衰减曲线分析",
        "",
        "| 持有天数 | 平均收益 | 95% CI | 胜率 |",
        "|---:|---:|---:|---:|",
    ])
    for days, stats in sorted(analysis["decay_analysis"].items(), key=lambda x: int(x[0].replace('d', ''))):
        md.append(
            f"| {days} | {stats['mean_return']:.2f}% | "
            f"[{stats['ci_lower']:.2f}%, {stats['ci_upper']:.2f}%] | "
            f"{stats['win_rate']:.1f}% |"
        )
    md.append("")
    
    # 市场状态分析
    md.extend([
        "## 6. 市场状态条件分析",
        "",
        "| 市场状态 | 样本数 | 平均收益 | 95% CI | 胜率 |",
        "|---|---:|---:|---:|---:|",
    ])
    for regime, stats in sorted(analysis["regime_analysis"].items(), key=lambda x: x[1]["mean_return"], reverse=True):
        regime_name = {"bull": "牛市", "bear": "熊市", "range": "震荡", "unknown": "未知"}.get(regime, regime)
        md.append(
            f"| {regime_name} | {stats['n_samples']} | {stats['mean_return']:.2f}% | "
            f"[{stats['ci_lower']:.2f}%, {stats['ci_upper']:.2f}%] | "
            f"{stats['win_rate']:.1f}% |"
        )
    md.append("")
    
    # 阶段×市场状态
    md.extend([
        "## 7. 阶段×市场状态交叉分析",
        "",
    ])
    for phase, regimes in analysis["phase_regime_analysis"].items():
        md.extend([
            f"### {phase}",
            "",
            "| 市场状态 | 样本数 | 平均收益 | 95% CI | 胜率 |",
            "|---|---:|---:|---:|---:|",
        ])
        for regime, stats in sorted(regimes.items(), key=lambda x: x[1]["mean_return"], reverse=True):
            regime_name = {"bull": "牛市", "bear": "熊市", "range": "震荡", "unknown": "未知"}.get(regime, regime)
            md.append(
                f"| {regime_name} | {stats['n_samples']} | {stats['mean_return']:.2f}% | "
                f"[{stats['ci_lower']:.2f}%, {stats['ci_upper']:.2f}%] | "
                f"{stats['win_rate']:.1f}% |"
            )
        md.append("")
    
    # 崩盘检测
    md.extend([
        "## 8. 崩盘检测敏感性分析",
        "",
        "| 崩盘事件 | 时间段 | 信号数 | 平均收益 | 胜率 | Markdown比例 |",
        "|---|---|---:|---:|---:|---:|",
    ])
    for crash_name, stats in analysis["crash_detection"].items():
        md.append(
            f"| {crash_name} | {stats['period']} | {stats['n_signals']} | "
            f"{stats['avg_return']:.2f}% | {stats['win_rate']:.1f}% | "
            f"{stats['markdown_rate']:.1f}% |"
        )
    md.append("")
    
    # 月度一致性
    monthly = analysis["monthly_analysis"]
    if "consistency_summary" in monthly and monthly["consistency_summary"]:
        cs = monthly["consistency_summary"]
        md.extend([
            "## 9. 月度一致性分析",
            "",
            "| 指标 | 值 |",
            "|---|---|",
            f"| 月份数 | {cs.get('n_months', 0)} |",
            f"| 正收益月份 | {cs.get('positive_months', 0)} |",
            f"| 一致性比率 | {cs.get('consistency_rate', 0):.1f}% |",
            f"| 月度标准差 | {cs.get('monthly_std', 0):.2f}% |",
            "",
        ])
    
    # 多时间框架
    md.extend([
        "## 10. 多时间框架对齐分析",
        "",
        "| 对齐类型 | 样本数 | 平均收益 | 95% CI | 胜率 |",
        "|---|---:|---:|---:|---:|",
    ])
    for alignment, stats in sorted(analysis["mtf_analysis"].items(), key=lambda x: x[1]["mean_return"], reverse=True):
        md.append(
            f"| {alignment} | {stats['n_samples']} | {stats['mean_return']:.2f}% | "
            f"[{stats['ci_lower']:.2f}%, {stats['ci_upper']:.2f}%] | "
            f"{stats['win_rate']:.1f}% |"
        )
    md.append("")
    
    # 结论
    md.extend([
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
    
    best_phase = max(analysis["phase_analysis"].items(), key=lambda x: x[1]["mean_return"])
    worst_phase = min(analysis["phase_analysis"].items(), key=lambda x: x[1]["mean_return"])
    md.append(f"1. **最佳阶段**: {best_phase[0]} (平均收益 {best_phase[1]['mean_return']:.2f}%, 胜率 {best_phase[1]['win_rate']:.1f}%)")
    md.append(f"2. **最差阶段**: {worst_phase[0]} (平均收益 {worst_phase[1]['mean_return']:.2f}%, 胜率 {worst_phase[1]['win_rate']:.1f}%)")
    
    if "filter_effect" in lppl:
        md.append(f"3. **LPPL过滤效果**: 收益提升 {lppl['filter_effect']['return_improvement']:.2f}pp, 胜率提升 {lppl['filter_effect']['win_rate_improvement']:.1f}pp")
    
    if analysis["decay_analysis"]:
        best_hold = max(analysis["decay_analysis"].items(), key=lambda x: x[1]["mean_return"])
        md.append(f"4. **最优持有期**: {best_hold[0]} (平均收益 {best_hold[1]['mean_return']:.2f}%)")
    
    md.extend([
        "",
        "---",
        "",
        f"**报告生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
    ])
    
    (output_dir / "medium_test_report.md").write_text("\n".join(md), encoding="utf-8")
    
    print("\n输出文件:")
    print(f"  - {output_dir / 'medium_test_analysis.json'}")
    print(f"  - {output_dir / 'medium_test_report.md'}")


def main():
    """主函数"""
    output_dir = PROJECT_ROOT / "output" / "deep_effectiveness_test"
    csv_path = PROJECT_ROOT / "data" / "stock_list.csv"
    tdx_index_path = Path("/home/james/.local/share/tdxcfv/drive_c/tc/vipdoc/sh/lday/sh000001.day")

    print("=" * 60)
    print("深度有效性测试（中等规模）")
    print("=" * 60)
    print("配置: 5 seeds × 20 cycles × 500 stocks")
    print("=" * 60)

    # 加载数据
    print("\n1. 加载数据...")
    symbols = load_stock_symbols(csv_path, limit=500)
    print(f"   加载了 {len(symbols)} 只股票")

    index_data = None
    if tdx_index_path.exists():
        index_data = load_index_from_tdx(tdx_index_path)
        print(f"   加载了 {len(index_data)} 条指数数据")

    # 检测泡沫
    print("\n2. 检测泡沫阶段...")
    bubble_periods = detect_bubble_periods(index_data) if index_data is not None else []
    print(f"   检测到 {len(bubble_periods)} 个泡沫阶段")

    # 运行测试
    print("\n3. 运行测试（5 seeds × 20 cycles）...")
    all_results = []
    seed_summaries = {}
    
    for seed in range(5):
        print(f"\n   Seed {seed+1}/5:")
        cycle_specs = generate_cycle_specs(20, seed=42+seed, bubble_periods=bubble_periods)
        
        args_list = [(s, cycle_specs, bubble_periods, index_data) for s in symbols]
        
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
        avg_ret = np.mean([r["future_60d_return"] for r in seed_results]) if seed_results else 0
        win_rate = sum(1 for r in seed_results if r["future_60d_return"] > 0) / len(seed_results) * 100 if seed_results else 0
        seed_summaries[seed] = {
            "n_samples": len(seed_results),
            "avg_return": avg_ret,
            "win_rate": win_rate,
        }
        print(f"     样本数: {len(seed_results)}, 平均收益: {avg_ret:.2f}%, 胜率: {win_rate:.1f}%")

    print(f"\n   总样本数: {len(all_results)}")

    # 保存原始结果
    print("\n4. 保存结果...")
    output_dir.mkdir(parents=True, exist_ok=True)
    with (output_dir / "medium_raw_results.jsonl").open("w", encoding="utf-8") as f:
        for row in all_results:
            f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
    
    df = pd.DataFrame(all_results)
    df.to_csv(output_dir / "medium_raw_results.csv", index=False, encoding="utf-8-sig")

    # 分析
    print("\n5. 分析结果...")
    analysis = analyze_comprehensive(all_results, seed_summaries)

    # 生成报告
    print("\n6. 生成报告...")
    generate_report(analysis, output_dir)

    # 打印摘要
    overall = analysis["overall_stats"]
    print("\n" + "=" * 60)
    print("测试摘要:")
    print(f"  总样本数: {overall['n_samples']}")
    print(f"  平均收益: {overall['mean_return']:.2f}%")
    print(f"  95%置信区间: [{overall['ci_lower']:.2f}%, {overall['ci_upper']:.2f}%]")
    print(f"  胜率: {overall['win_rate']:.1f}%")
    print(f"  种子稳定性: {'稳定' if analysis['seed_stability']['all_positive'] else '不稳定'}")
    print("=" * 60)


if __name__ == "__main__":
    main()
