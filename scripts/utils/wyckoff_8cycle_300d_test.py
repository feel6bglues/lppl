#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
8组完整周期测试（300天日线+多周期版本）
- 抽取 stock_list.csv 内所有有效股票（含创业板、科创板）
- 使用 2010-2025 随机日期运行 8 组完整周期测试
- 采用 300 天日线和折合600天的周线月线多周期分析
- 多线程并行计算，充分利用CPU
- 对比分析结果与随后120个交易日走势进行拟合检查
"""

from __future__ import annotations

import csv
import json
import os
import random
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.data.manager import DataManager
from src.wyckoff.engine import WyckoffEngine
from src.wyckoff.models import WyckoffPhase


@dataclass(frozen=True)
class CycleSpec:
    cycle_id: int
    year: int
    as_of_date: str
    description: str


def load_stock_symbols(csv_path: Path, limit: int = 99999) -> List[Dict[str, str]]:
    """从 stock_list.csv 加载所有A股股票代码"""
    symbols = []
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            code = str(row.get("code", "")).strip()
            market = str(row.get("market", "")).strip().upper()
            name = str(row.get("name", "")).replace("\x00", "").strip()
            if not (code.isdigit() and len(code) == 6 and market in {"SH", "SZ"}):
                continue
            # 包含所有A股：主板、中小板、创业板、科创板
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


def generate_cycle_specs(seed: int = 42) -> List[CycleSpec]:
    """生成 8 组随机年份和日期的测试规格（2010-2025）"""
    random.seed(seed)
    specs = []
    years = sorted(random.sample(range(2010, 2026), 8))
    for idx, yr in enumerate(years):
        month = random.randint(3, 11)
        day = random.randint(10, 25)
        date_str = f"{yr}-{month:02d}-{day:02d}"
        specs.append(CycleSpec(
            cycle_id=idx + 1,
            year=yr,
            as_of_date=date_str,
            description=f"Year {yr} Cycle {idx+1}"
        ))
    return specs


def calculate_future_return(
    df: pd.DataFrame, as_of_date: str, days: int = 120
) -> Optional[Dict[str, float]]:
    """计算未来 N 个交易日的收益率"""
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


def analyze_single_cycle(
    engine: WyckoffEngine,
    df: pd.DataFrame,
    symbol: str,
    name: str,
    cycle_spec: CycleSpec,
) -> Optional[Dict]:
    """单次分析"""
    as_of = pd.Timestamp(cycle_spec.as_of_date)
    available_data = df[df["date"] <= as_of]
    if len(available_data) < 100:
        return None
    report = engine.analyze(available_data, symbol=symbol, period="日线", multi_timeframe=True)
    future_return = calculate_future_return(df, cycle_spec.as_of_date, days=120)
    if future_return is None:
        return None
    return {
        "cycle_id": cycle_spec.cycle_id,
        "cycle_year": cycle_spec.year,
        "as_of": cycle_spec.as_of_date,
        "symbol": symbol,
        "name": name,
        "phase": report.structure.phase.value,
        "direction": report.trading_plan.direction,
        "confidence": report.trading_plan.confidence.value,
        "rr_ratio": round(report.risk_reward.reward_risk_ratio, 3),
        "entry_price": round(report.risk_reward.entry_price or 0, 3),
        "stop_loss": round(report.risk_reward.stop_loss or 0, 3),
        "first_target": round(report.risk_reward.first_target or 0, 3),
        "bc_price": round(report.structure.bc_point.price, 3) if report.structure.bc_point else None,
        "sc_price": round(report.structure.sc_point.price, 3) if report.structure.sc_point else None,
        "tr_low": round(report.structure.trading_range_low or 0, 3),
        "tr_high": round(report.structure.trading_range_high or 0, 3),
        "signal_type": report.signal.signal_type,
        "signal_description": report.signal.description[:100] if report.signal.description else "",
        "monthly_phase": report.multi_timeframe.monthly.phase.value if report.multi_timeframe and report.multi_timeframe.monthly else "",
        "weekly_phase": report.multi_timeframe.weekly.phase.value if report.multi_timeframe and report.multi_timeframe.weekly else "",
        "daily_phase": report.multi_timeframe.daily.phase.value if report.multi_timeframe and report.multi_timeframe.daily else "",
        "mtf_alignment": report.multi_timeframe.alignment if report.multi_timeframe else "",
        "future_120d_return": future_return["return_pct"],
        "future_120d_max_gain": future_return["max_gain_pct"],
        "future_120d_max_drawdown": future_return["max_drawdown_pct"],
        "future_entry_price": future_return["entry_price"],
        "future_close": future_return["future_close"],
    }


def process_single_stock(
    symbol_info: Dict[str, str],
    cycle_specs: List[CycleSpec],
    lookback_days: int,
) -> List[Dict]:
    """处理单只股票的所有周期（用于多线程）"""
    symbol = symbol_info["symbol"]
    name = symbol_info["name"]
    results = []

    try:
        dm = DataManager()
        df = dm.get_data(symbol)
        if df is None or df.empty:
            return results

        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)

        engine = WyckoffEngine(lookback_days=lookback_days)

        for spec in cycle_specs:
            result = analyze_single_cycle(engine, df, symbol, name, spec)
            if result:
                results.append(result)
    except Exception as e:
        pass

    return results


def run_8cycle_test_multithreaded(
    symbols: List[Dict[str, str]],
    cycle_specs: List[CycleSpec],
    output_dir: Path,
    lookback_days: int = 300,
    max_workers: int = None,
) -> List[Dict]:
    """运行 8 组完整周期测试（多线程版）"""
    if max_workers is None:
        max_workers = min(os.cpu_count() or 4, 12)

    total_tests = len(symbols) * len(cycle_specs)
    print(f"开始测试: {len(symbols)} 只股票 × {len(cycle_specs)} 个周期 = {total_tests} 次分析")
    print(f"多线程: {max_workers} 线程")
    print(f"日线回看: {lookback_days} 天")
    print("=" * 60)

    all_results = []
    completed_stocks = 0

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(process_single_stock, symbol_info, cycle_specs, lookback_days): symbol_info
            for symbol_info in symbols
        }

        for future in as_completed(futures):
            completed_stocks += 1
            results = future.result()
            all_results.extend(results)

            if completed_stocks % 200 == 0:
                print(f"  已处理 {completed_stocks}/{len(symbols)} 只股票, 累计 {len(all_results)} 条结果")

    print(f"\n测试完成: {len(all_results)} 条有效结果")
    return all_results


def convert_keys_to_str(obj):
    if isinstance(obj, dict):
        return {str(k): convert_keys_to_str(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [convert_keys_to_str(item) for item in obj]
    elif isinstance(obj, (np.int64, np.int32)):
        return int(obj)
    elif isinstance(obj, (np.float64, np.float32)):
        return float(obj)
    return obj


def analyze_results(results: List[Dict]) -> Dict:
    """分析测试结果"""
    if not results:
        return {}
    df = pd.DataFrame(results)

    phase_stats = {}
    for phase in df["phase"].unique():
        phase_df = df[df["phase"] == phase]
        phase_stats[phase] = {
            "count": len(phase_df),
            "avg_return": round(phase_df["future_120d_return"].mean(), 2),
            "median_return": round(phase_df["future_120d_return"].median(), 2),
            "win_rate": round(len(phase_df[phase_df["future_120d_return"] > 0]) / len(phase_df) * 100, 1),
            "avg_max_gain": round(phase_df["future_120d_max_gain"].mean(), 2),
            "avg_max_drawdown": round(phase_df["future_120d_max_drawdown"].mean(), 2),
        }

    direction_stats = {}
    for direction in df["direction"].unique():
        dir_df = df[df["direction"] == direction]
        direction_stats[direction] = {
            "count": len(dir_df),
            "avg_return": round(dir_df["future_120d_return"].mean(), 2),
            "win_rate": round(len(dir_df[dir_df["future_120d_return"] > 0]) / len(dir_df) * 100, 1),
        }

    confidence_stats = {}
    for conf in df["confidence"].unique():
        conf_df = df[df["confidence"] == conf]
        confidence_stats[conf] = {
            "count": len(conf_df),
            "avg_return": round(conf_df["future_120d_return"].mean(), 2),
            "win_rate": round(len(conf_df[conf_df["future_120d_return"] > 0]) / len(conf_df) * 100, 1),
        }

    cycle_stats = {}
    for cycle_id in df["cycle_id"].unique():
        cycle_df = df[df["cycle_id"] == cycle_id]
        cycle_stats[cycle_id] = {
            "year": cycle_df["cycle_year"].iloc[0],
            "as_of": cycle_df["as_of"].iloc[0],
            "count": len(cycle_df),
            "avg_return": round(cycle_df["future_120d_return"].mean(), 2),
            "win_rate": round(len(cycle_df[cycle_df["future_120d_return"] > 0]) / len(cycle_df) * 100, 1),
        }

    signal_accuracy = {}
    for signal in df["signal_type"].unique():
        sig_df = df[df["signal_type"] == signal]
        signal_accuracy[signal] = {
            "count": len(sig_df),
            "avg_return": round(sig_df["future_120d_return"].mean(), 2),
            "win_rate": round(len(sig_df[sig_df["future_120d_return"] > 0]) / len(sig_df) * 100, 1),
        }

    mtf_stats = {}
    for alignment in df["mtf_alignment"].unique():
        if alignment:
            mtf_df = df[df["mtf_alignment"] == alignment]
            mtf_stats[alignment] = {
                "count": len(mtf_df),
                "avg_return": round(mtf_df["future_120d_return"].mean(), 2),
                "win_rate": round(len(mtf_df[mtf_df["future_120d_return"] > 0]) / len(mtf_df) * 100, 1),
            }

    # 拟合度分析：检查信号与实际走势的一致性
    fit_analysis = analyze_signal_fit(df)

    return {
        "total_samples": len(df),
        "overall_avg_return": round(df["future_120d_return"].mean(), 2),
        "overall_median_return": round(df["future_120d_return"].median(), 2),
        "overall_win_rate": round(len(df[df["future_120d_return"] > 0]) / len(df) * 100, 1),
        "phase_stats": phase_stats,
        "direction_stats": direction_stats,
        "confidence_stats": confidence_stats,
        "cycle_stats": cycle_stats,
        "signal_accuracy": signal_accuracy,
        "mtf_stats": mtf_stats,
        "fit_analysis": fit_analysis,
    }


def analyze_signal_fit(df: pd.DataFrame) -> Dict:
    """分析信号与实际走势的拟合度"""
    fit_results = {}
    
    # 1. 阶段信号拟合度
    phase_fit = {}
    for phase in ["accumulation", "markup", "distribution", "markdown"]:
        phase_df = df[df["phase"] == phase]
        if len(phase_df) > 0:
            # 理论预期：accumulation/markup应有正收益，distribution/markdown应有负收益
            expected_positive = phase in ["accumulation", "markup"]
            actual_positive_rate = len(phase_df[phase_df["future_120d_return"] > 0]) / len(phase_df)
            
            # 拟合度 = 实际符合预期的比例
            if expected_positive:
                fit_rate = actual_positive_rate
            else:
                fit_rate = 1 - actual_positive_rate
            
            phase_fit[phase] = {
                "count": len(phase_df),
                "expected_positive": expected_positive,
                "actual_positive_rate": round(actual_positive_rate * 100, 1),
                "fit_rate": round(fit_rate * 100, 1),
                "avg_return": round(phase_df["future_120d_return"].mean(), 2),
            }
    
    # 2. 方向信号拟合度
    direction_fit = {}
    for direction in ["做多", "轻仓试探", "观察等待", "持有观察", "空仓观望"]:
        dir_df = df[df["direction"] == direction]
        if len(dir_df) > 0:
            # 理论预期：做多/轻仓试探 > 观察等待 > 持有观察 > 空仓观望
            expected_rank = {"做多": 5, "轻仓试探": 4, "观察等待": 3, "持有观察": 2, "空仓观望": 1}
            actual_avg_return = dir_df["future_120d_return"].mean()
            
            direction_fit[direction] = {
                "count": len(dir_df),
                "expected_rank": expected_rank.get(direction, 0),
                "avg_return": round(actual_avg_return, 2),
                "win_rate": round(len(dir_df[dir_df["future_120d_return"] > 0]) / len(dir_df) * 100, 1),
            }
    
    # 3. 置信度信号拟合度
    confidence_fit = {}
    for conf in ["A", "B", "C", "D"]:
        conf_df = df[df["confidence"] == conf]
        if len(conf_df) > 0:
            # 理论预期：A > B > C > D
            expected_rank = {"A": 4, "B": 3, "C": 2, "D": 1}
            actual_avg_return = conf_df["future_120d_return"].mean()
            
            confidence_fit[conf] = {
                "count": len(conf_df),
                "expected_rank": expected_rank.get(conf, 0),
                "avg_return": round(actual_avg_return, 2),
                "win_rate": round(len(conf_df[conf_df["future_120d_return"] > 0]) / len(conf_df) * 100, 1),
            }
    
    # 4. 多周期一致性拟合度
    mtf_fit = {}
    for alignment in ["fully_aligned", "weekly_daily_aligned", "higher_timeframe_aligned", "mixed"]:
        mtf_df = df[df["mtf_alignment"] == alignment]
        if len(mtf_df) > 0:
            # 理论预期：fully_aligned > weekly_daily_aligned > higher_timeframe_aligned > mixed
            expected_rank = {"fully_aligned": 4, "weekly_daily_aligned": 3, "higher_timeframe_aligned": 2, "mixed": 1}
            actual_avg_return = mtf_df["future_120d_return"].mean()
            
            mtf_fit[alignment] = {
                "count": len(mtf_df),
                "expected_rank": expected_rank.get(alignment, 0),
                "avg_return": round(actual_avg_return, 2),
                "win_rate": round(len(mtf_df[mtf_df["future_120d_return"] > 0]) / len(mtf_df) * 100, 1),
            }
    
    # 5. 计算整体拟合度得分
    # 阶段拟合度权重40%，方向拟合度权重20%，置信度拟合度权重20%，多周期拟合度权重20%
    phase_fit_score = sum(v["fit_rate"] for v in phase_fit.values()) / len(phase_fit) if phase_fit else 0
    
    # 方向拟合度：检查是否符合预期排序
    direction_returns = [(d, v["avg_return"]) for d, v in direction_fit.items()]
    direction_returns.sort(key=lambda x: x[1], reverse=True)
    expected_order = ["做多", "轻仓试探", "观察等待", "持有观察", "空仓观望"]
    direction_order = [d for d, _ in direction_returns]
    direction_fit_score = 100 - (sum(abs(expected_order.index(d) - direction_order.index(d)) for d in expected_order if d in direction_order) / len(expected_order) * 25) if all(d in direction_order for d in expected_order) else 50
    
    # 置信度拟合度：检查是否符合预期排序
    conf_returns = [(c, v["avg_return"]) for c, v in confidence_fit.items()]
    conf_returns.sort(key=lambda x: x[1], reverse=True)
    expected_conf_order = ["A", "B", "C", "D"]
    conf_order = [c for c, _ in conf_returns]
    conf_fit_score = 100 - (sum(abs(expected_conf_order.index(c) - conf_order.index(c)) for c in expected_conf_order if c in conf_order) / len(expected_conf_order) * 25) if all(c in conf_order for c in expected_conf_order) else 50
    
    # 多周期拟合度：检查是否符合预期排序
    mtf_returns = [(m, v["avg_return"]) for m, v in mtf_fit.items()]
    mtf_returns.sort(key=lambda x: x[1], reverse=True)
    expected_mtf_order = ["fully_aligned", "weekly_daily_aligned", "higher_timeframe_aligned", "mixed"]
    mtf_order = [m for m, _ in mtf_returns]
    mtf_fit_score = 100 - (sum(abs(expected_mtf_order.index(m) - mtf_order.index(m)) for m in expected_mtf_order if m in mtf_order) / len(expected_mtf_order) * 25) if all(m in mtf_order for m in expected_mtf_order) else 50
    
    overall_fit_score = (phase_fit_score * 0.4 + direction_fit_score * 0.2 + conf_fit_score * 0.2 + mtf_fit_score * 0.2)
    
    return {
        "phase_fit": phase_fit,
        "direction_fit": direction_fit,
        "confidence_fit": confidence_fit,
        "mtf_fit": mtf_fit,
        "overall_fit_score": round(overall_fit_score, 1),
        "phase_fit_score": round(phase_fit_score, 1),
        "direction_fit_score": round(direction_fit_score, 1),
        "confidence_fit_score": round(conf_fit_score, 1),
        "mtf_fit_score": round(mtf_fit_score, 1),
    }


def write_outputs(output_dir: Path, results: List[Dict], analysis: Dict) -> None:
    """输出结果到文件"""
    output_dir.mkdir(parents=True, exist_ok=True)

    with (output_dir / "cycle8_raw_results.jsonl").open("w", encoding="utf-8") as f:
        for row in results:
            f.write(json.dumps(convert_keys_to_str(row), ensure_ascii=False) + "\n")

    if results:
        df = pd.DataFrame(results)
        df.to_csv(output_dir / "cycle8_results.csv", index=False, encoding="utf-8-sig")

    with (output_dir / "cycle8_analysis.json").open("w", encoding="utf-8") as f:
        json.dump(convert_keys_to_str(analysis), f, ensure_ascii=False, indent=2)

    md_lines = [
        "# 8-Cycle Wyckoff Engine Test Report (300 Days + Multi-timeframe)",
        "",
        f"- 测试日期: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 总样本数: {analysis.get('total_samples', 0)}",
        f"- 整体平均收益: {analysis.get('overall_avg_return', 0):.2f}%",
        f"- 整体胜率: {analysis.get('overall_win_rate', 0):.1f}%",
        f"- 日线回看: 300天",
        f"- 多周期分析: 日线+周线+月线（周线/月线折合600天）",
        "",
        "## 拟合度分析",
        "",
        f"- **整体拟合度得分: {analysis.get('fit_analysis', {}).get('overall_fit_score', 0):.1f}/100**",
        f"- 阶段拟合度: {analysis.get('fit_analysis', {}).get('phase_fit_score', 0):.1f}/100",
        f"- 方向拟合度: {analysis.get('fit_analysis', {}).get('direction_fit_score', 0):.1f}/100",
        f"- 置信度拟合度: {analysis.get('fit_analysis', {}).get('confidence_fit_score', 0):.1f}/100",
        f"- 多周期拟合度: {analysis.get('fit_analysis', {}).get('mtf_fit_score', 0):.1f}/100",
        "",
        "## 阶段拟合度详情",
        "",
        "| 阶段 | 样本数 | 预期方向 | 实际正收益比例 | 拟合度 | 平均收益 |",
        "|---|---:|---|---:|---:|---:|",
    ]

    for phase, stats in sorted(analysis.get("fit_analysis", {}).get("phase_fit", {}).items(),
                                key=lambda x: x[1]["fit_rate"], reverse=True):
        expected = "正收益" if stats["expected_positive"] else "负收益"
        md_lines.append(
            f"| {phase} | {stats['count']} | {expected} | {stats['actual_positive_rate']:.1f}% | "
            f"{stats['fit_rate']:.1f}% | {stats['avg_return']:.2f}% |"
        )

    md_lines.extend(["", "## 方向拟合度详情", ""])
    md_lines.append("| 方向 | 样本数 | 预期排名 | 平均收益 | 胜率 |")
    md_lines.append("|---|---:|---:|---:|---:|")
    for direction, stats in sorted(analysis.get("fit_analysis", {}).get("direction_fit", {}).items(),
                                    key=lambda x: x[1]["avg_return"], reverse=True):
        md_lines.append(
            f"| {direction} | {stats['count']} | {stats['expected_rank']} | "
            f"{stats['avg_return']:.2f}% | {stats['win_rate']:.1f}% |"
        )

    md_lines.extend(["", "## 置信度拟合度详情", ""])
    md_lines.append("| 置信度 | 样本数 | 预期排名 | 平均收益 | 胜率 |")
    md_lines.append("|---|---:|---:|---:|---:|")
    for conf, stats in sorted(analysis.get("fit_analysis", {}).get("confidence_fit", {}).items(),
                               key=lambda x: x[1]["avg_return"], reverse=True):
        md_lines.append(
            f"| {conf} | {stats['count']} | {stats['expected_rank']} | "
            f"{stats['avg_return']:.2f}% | {stats['win_rate']:.1f}% |"
        )

    md_lines.extend(["", "## 多周期拟合度详情", ""])
    md_lines.append("| 一致性 | 样本数 | 预期排名 | 平均收益 | 胜率 |")
    md_lines.append("|---|---:|---:|---:|---:|")
    for alignment, stats in sorted(analysis.get("fit_analysis", {}).get("mtf_fit", {}).items(),
                                    key=lambda x: x[1]["avg_return"], reverse=True):
        md_lines.append(
            f"| {alignment} | {stats['count']} | {stats['expected_rank']} | "
            f"{stats['avg_return']:.2f}% | {stats['win_rate']:.1f}% |"
        )

    md_lines.extend(["", "## 阶段分布与未来收益", ""])
    md_lines.append("| 阶段 | 样本数 | 平均收益 | 中位收益 | 胜率 | 平均最大涨幅 | 平均最大回撤 |")
    md_lines.append("|---|---:|---:|---:|---:|---:|---:|")

    for phase, stats in sorted(analysis.get("phase_stats", {}).items(),
                                key=lambda x: x[1]["avg_return"], reverse=True):
        md_lines.append(
            f"| {phase} | {stats['count']} | {stats['avg_return']:.2f}% | "
            f"{stats['median_return']:.2f}% | {stats['win_rate']:.1f}% | "
            f"{stats['avg_max_gain']:.2f}% | {stats['avg_max_drawdown']:.2f}% |"
        )

    md_lines.extend(["", "## 方向分布与未来收益", ""])
    md_lines.append("| 方向 | 样本数 | 平均收益 | 胜率 |")
    md_lines.append("|---|---:|---:|---:|")
    for direction, stats in sorted(analysis.get("direction_stats", {}).items(),
                                    key=lambda x: x[1]["avg_return"], reverse=True):
        md_lines.append(f"| {direction} | {stats['count']} | {stats['avg_return']:.2f}% | {stats['win_rate']:.1f}% |")

    md_lines.extend(["", "## 置信度分布与未来收益", ""])
    md_lines.append("| 置信度 | 样本数 | 平均收益 | 胜率 |")
    md_lines.append("|---|---:|---:|---:|")
    for conf, stats in sorted(analysis.get("confidence_stats", {}).items()):
        md_lines.append(f"| {conf} | {stats['count']} | {stats['avg_return']:.2f}% | {stats['win_rate']:.1f}% |")

    md_lines.extend(["", "## 各周期测试结果", ""])
    md_lines.append("| 周期 | 年份 | 日期 | 样本数 | 平均收益 | 胜率 |")
    md_lines.append("|---|---|---|---:|---:|---:|")
    for cycle_id, stats in sorted(analysis.get("cycle_stats", {}).items()):
        md_lines.append(
            f"| {cycle_id} | {stats['year']} | {stats['as_of']} | "
            f"{stats['count']} | {stats['avg_return']:.2f}% | {stats['win_rate']:.1f}% |"
        )

    md_lines.extend(["", "## 信号类型准确性", ""])
    md_lines.append("| 信号类型 | 样本数 | 平均收益 | 胜率 |")
    md_lines.append("|---|---:|---:|---:|")
    for signal, stats in sorted(analysis.get("signal_accuracy", {}).items(),
                                 key=lambda x: x[1]["avg_return"], reverse=True):
        md_lines.append(f"| {signal} | {stats['count']} | {stats['avg_return']:.2f}% | {stats['win_rate']:.1f}% |")

    md_lines.extend(["", "## 多周期一致性分析", ""])
    md_lines.append("| 一致性 | 样本数 | 平均收益 | 胜率 |")
    md_lines.append("|---|---:|---:|---:|")
    for alignment, stats in sorted(analysis.get("mtf_stats", {}).items(),
                                    key=lambda x: x[1]["avg_return"], reverse=True):
        md_lines.append(f"| {alignment} | {stats['count']} | {stats['avg_return']:.2f}% | {stats['win_rate']:.1f}% |")

    (output_dir / "cycle8_report.md").write_text("\n".join(md_lines), encoding="utf-8")

    print(f"\n输出文件:")
    print(f"  - {output_dir / 'cycle8_raw_results.jsonl'}")
    print(f"  - {output_dir / 'cycle8_results.csv'}")
    print(f"  - {output_dir / 'cycle8_analysis.json'}")
    print(f"  - {output_dir / 'cycle8_report.md'}")


def main() -> None:
    """主函数"""
    output_dir = PROJECT_ROOT / "output" / "wyckoff_8cycle_300d_test"
    csv_path = PROJECT_ROOT / "data" / "stock_list.csv"

    print("=" * 60)
    print("Wyckoff Engine v3.0 - 8 Cycle Test (ALL Stocks, 300 Days + Multi-timeframe)")
    print("=" * 60)

    print("\n1. 加载股票列表...")
    symbols = load_stock_symbols(csv_path, limit=99999)
    print(f"   加载了 {len(symbols)} 只股票")

    print("\n2. 生成测试周期...")
    cycle_specs = generate_cycle_specs()
    for spec in cycle_specs:
        print(f"   Cycle {spec.cycle_id}: Year {spec.year}, Date {spec.as_of_date}")

    print("\n3. 运行测试（多线程）...")
    results = run_8cycle_test_multithreaded(symbols, cycle_specs, output_dir, lookback_days=300)

    print("\n4. 分析结果...")
    analysis = analyze_results(results)

    print("\n5. 输出结果...")
    write_outputs(output_dir, results, analysis)

    print("\n" + "=" * 60)
    print("测试摘要:")
    print(f"  总样本数: {analysis.get('total_samples', 0)}")
    print(f"  整体平均收益: {analysis.get('overall_avg_return', 0):.2f}%")
    print(f"  整体胜率: {analysis.get('overall_win_rate', 0):.1f}%")
    print(f"  整体拟合度: {analysis.get('fit_analysis', {}).get('overall_fit_score', 0):.1f}/100")
    print("=" * 60)


if __name__ == "__main__":
    main()
