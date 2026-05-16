#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
计算超额收益 - 以沪深300为基准（300天版本）
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.data.manager import DataManager


def convert_keys_to_str(obj):
    """递归转换所有 int64 键为 str"""
    if isinstance(obj, dict):
        return {str(k): convert_keys_to_str(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [convert_keys_to_str(item) for item in obj]
    elif isinstance(obj, (np.int64, np.int32)):
        return int(obj)
    elif isinstance(obj, (np.float64, np.float32)):
        return float(obj)
    return obj


def calculate_benchmark_return(
    benchmark_df: pd.DataFrame,
    as_of_date: str,
    days: int = 120
) -> Optional[Dict[str, float]]:
    """计算基准指数的收益率"""
    as_of = pd.Timestamp(as_of_date)
    future_data = benchmark_df[benchmark_df["date"] > as_of].head(days)
    
    if len(future_data) < days * 0.8:
        return None
    
    entry_price = float(benchmark_df[benchmark_df["date"] <= as_of].iloc[-1]["close"])
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


def calculate_excess_returns(
    test_results: List[Dict],
    benchmark_df: pd.DataFrame,
) -> List[Dict]:
    """计算超额收益"""
    enhanced_results = []
    
    for result in test_results:
        as_of = result.get("as_of")
        if not as_of:
            continue
        
        # 计算基准收益
        benchmark = calculate_benchmark_return(benchmark_df, as_of, days=120)
        if benchmark is None:
            continue
        
        # 计算超额收益
        stock_return = result.get("future_120d_return", 0)
        benchmark_return = benchmark["return_pct"]
        excess_return = stock_return - benchmark_return
        
        # 添加基准和超额收益字段
        enhanced_result = result.copy()
        enhanced_result["benchmark_return"] = benchmark_return
        enhanced_result["benchmark_max_gain"] = benchmark["max_gain_pct"]
        enhanced_result["benchmark_max_drawdown"] = benchmark["max_drawdown_pct"]
        enhanced_result["excess_return"] = round(excess_return, 2)
        enhanced_result["alpha"] = round(excess_return, 2)  # Alpha = 超额收益
        
        enhanced_results.append(enhanced_result)
    
    return enhanced_results


def analyze_excess_returns(results: List[Dict]) -> Dict:
    """分析超额收益"""
    if not results:
        return {}
    
    df = pd.DataFrame(results)
    
    # 按阶段分组统计超额收益
    phase_excess = {}
    for phase in df["phase"].unique():
        phase_df = df[df["phase"] == phase]
        phase_excess[phase] = {
            "count": len(phase_df),
            "avg_stock_return": round(phase_df["future_120d_return"].mean(), 2),
            "avg_benchmark_return": round(phase_df["benchmark_return"].mean(), 2),
            "avg_excess_return": round(phase_df["excess_return"].mean(), 2),
            "excess_win_rate": round(len(phase_df[phase_df["excess_return"] > 0]) / len(phase_df) * 100, 1),
            "stock_win_rate": round(len(phase_df[phase_df["future_120d_return"] > 0]) / len(phase_df) * 100, 1),
        }
    
    # 按信号类型分组统计超额收益
    signal_excess = {}
    for signal in df["signal_type"].unique():
        sig_df = df[df["signal_type"] == signal]
        signal_excess[signal] = {
            "count": len(sig_df),
            "avg_stock_return": round(sig_df["future_120d_return"].mean(), 2),
            "avg_benchmark_return": round(sig_df["benchmark_return"].mean(), 2),
            "avg_excess_return": round(sig_df["excess_return"].mean(), 2),
            "excess_win_rate": round(len(sig_df[sig_df["excess_return"] > 0]) / len(sig_df) * 100, 1),
        }
    
    # 按方向分组统计超额收益
    direction_excess = {}
    for direction in df["direction"].unique():
        dir_df = df[df["direction"] == direction]
        direction_excess[direction] = {
            "count": len(dir_df),
            "avg_stock_return": round(dir_df["future_120d_return"].mean(), 2),
            "avg_benchmark_return": round(dir_df["benchmark_return"].mean(), 2),
            "avg_excess_return": round(dir_df["excess_return"].mean(), 2),
            "excess_win_rate": round(len(dir_df[dir_df["excess_return"] > 0]) / len(dir_df) * 100, 1),
        }
    
    # 按周期分组统计超额收益
    cycle_excess = {}
    for cycle_id in df["cycle_id"].unique():
        cycle_df = df[df["cycle_id"] == cycle_id]
        cycle_excess[cycle_id] = {
            "year": cycle_df["cycle_year"].iloc[0],
            "as_of": cycle_df["as_of"].iloc[0],
            "count": len(cycle_df),
            "avg_stock_return": round(cycle_df["future_120d_return"].mean(), 2),
            "avg_benchmark_return": round(cycle_df["benchmark_return"].mean(), 2),
            "avg_excess_return": round(cycle_df["excess_return"].mean(), 2),
            "excess_win_rate": round(len(cycle_df[cycle_df["excess_return"] > 0]) / len(cycle_df) * 100, 1),
        }
    
    # 按置信度分组统计超额收益
    confidence_excess = {}
    for conf in df["confidence"].unique():
        conf_df = df[df["confidence"] == conf]
        confidence_excess[conf] = {
            "count": len(conf_df),
            "avg_stock_return": round(conf_df["future_120d_return"].mean(), 2),
            "avg_benchmark_return": round(conf_df["benchmark_return"].mean(), 2),
            "avg_excess_return": round(conf_df["excess_return"].mean(), 2),
            "excess_win_rate": round(len(conf_df[conf_df["excess_return"] > 0]) / len(conf_df) * 100, 1),
        }
    
    # 按多周期一致性分组统计超额收益
    mtf_excess = {}
    for alignment in df["mtf_alignment"].unique():
        if alignment:
            mtf_df = df[df["mtf_alignment"] == alignment]
            mtf_excess[alignment] = {
                "count": len(mtf_df),
                "avg_stock_return": round(mtf_df["future_120d_return"].mean(), 2),
                "avg_benchmark_return": round(mtf_df["benchmark_return"].mean(), 2),
                "avg_excess_return": round(mtf_df["excess_return"].mean(), 2),
                "excess_win_rate": round(len(mtf_df[mtf_df["excess_return"] > 0]) / len(mtf_df) * 100, 1),
            }
    
    return {
        "total_samples": len(df),
        "overall_avg_stock_return": round(df["future_120d_return"].mean(), 2),
        "overall_avg_benchmark_return": round(df["benchmark_return"].mean(), 2),
        "overall_avg_excess_return": round(df["excess_return"].mean(), 2),
        "overall_excess_win_rate": round(len(df[df["excess_return"] > 0]) / len(df) * 100, 1),
        "phase_excess": phase_excess,
        "signal_excess": signal_excess,
        "direction_excess": direction_excess,
        "cycle_excess": cycle_excess,
        "confidence_excess": confidence_excess,
        "mtf_excess": mtf_excess,
    }


def write_excess_report(output_dir: Path, analysis: Dict) -> None:
    """输出超额收益分析报告"""
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # 保存JSON
    with (output_dir / "excess_returns_analysis.json").open("w", encoding="utf-8") as f:
        json.dump(convert_keys_to_str(analysis), f, ensure_ascii=False, indent=2)
    
    # 生成Markdown报告
    md_lines = [
        "# 超额收益分析报告（基准：沪深300）- 300天版本",
        "",
        f"- 总样本数: {analysis.get('total_samples', 0)}",
        f"- 整体平均股票收益: {analysis.get('overall_avg_stock_return', 0):.2f}%",
        f"- 整体平均基准收益: {analysis.get('overall_avg_benchmark_return', 0):.2f}%",
        f"- **整体平均超额收益: {analysis.get('overall_avg_excess_return', 0):.2f}%**",
        f"- 超额收益胜率: {analysis.get('overall_excess_win_rate', 0):.1f}%",
        "",
        "## 阶段超额收益分析",
        "",
        "| 阶段 | 样本数 | 股票收益 | 基准收益 | 超额收益 | 超额胜率 | 股票胜率 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    
    for phase, stats in sorted(analysis.get("phase_excess", {}).items(), 
                                key=lambda x: x[1]["avg_excess_return"], reverse=True):
        md_lines.append(
            f"| {phase} | {stats['count']} | {stats['avg_stock_return']:.2f}% | "
            f"{stats['avg_benchmark_return']:.2f}% | **{stats['avg_excess_return']:.2f}%** | "
            f"{stats['excess_win_rate']:.1f}% | {stats['stock_win_rate']:.1f}% |"
        )
    
    md_lines.extend(["", "## 信号类型超额收益分析", ""])
    md_lines.append("| 信号类型 | 样本数 | 股票收益 | 基准收益 | 超额收益 | 超额胜率 |")
    md_lines.append("|---|---:|---:|---:|---:|---:|")
    
    for signal, stats in sorted(analysis.get("signal_excess", {}).items(), 
                                 key=lambda x: x[1]["avg_excess_return"], reverse=True):
        md_lines.append(
            f"| {signal} | {stats['count']} | {stats['avg_stock_return']:.2f}% | "
            f"{stats['avg_benchmark_return']:.2f}% | **{stats['avg_excess_return']:.2f}%** | "
            f"{stats['excess_win_rate']:.1f}% |"
        )
    
    md_lines.extend(["", "## 方向超额收益分析", ""])
    md_lines.append("| 方向 | 样本数 | 股票收益 | 基准收益 | 超额收益 | 超额胜率 |")
    md_lines.append("|---|---:|---:|---:|---:|---:|")
    
    for direction, stats in sorted(analysis.get("direction_excess", {}).items(), 
                                    key=lambda x: x[1]["avg_excess_return"], reverse=True):
        md_lines.append(
            f"| {direction} | {stats['count']} | {stats['avg_stock_return']:.2f}% | "
            f"{stats['avg_benchmark_return']:.2f}% | **{stats['avg_excess_return']:.2f}%** | "
            f"{stats['excess_win_rate']:.1f}% |"
        )
    
    md_lines.extend(["", "## 各周期超额收益分析", ""])
    md_lines.append("| 周期 | 年份 | 日期 | 样本数 | 股票收益 | 基准收益 | 超额收益 | 超额胜率 |")
    md_lines.append("|---|---|---|---:|---:|---:|---:|---:|")
    
    for cycle_id, stats in sorted(analysis.get("cycle_excess", {}).items()):
        md_lines.append(
            f"| {cycle_id} | {stats['year']} | {stats['as_of']} | {stats['count']} | "
            f"{stats['avg_stock_return']:.2f}% | {stats['avg_benchmark_return']:.2f}% | "
            f"**{stats['avg_excess_return']:.2f}%** | {stats['excess_win_rate']:.1f}% |"
        )
    
    md_lines.extend(["", "## 置信度超额收益分析", ""])
    md_lines.append("| 置信度 | 样本数 | 股票收益 | 基准收益 | 超额收益 | 超额胜率 |")
    md_lines.append("|---|---:|---:|---:|---:|---:|")
    
    for conf, stats in sorted(analysis.get("confidence_excess", {}).items()):
        md_lines.append(
            f"| {conf} | {stats['count']} | {stats['avg_stock_return']:.2f}% | "
            f"{stats['avg_benchmark_return']:.2f}% | **{stats['avg_excess_return']:.2f}%** | "
            f"{stats['excess_win_rate']:.1f}% |"
        )
    
    md_lines.extend(["", "## 多周期一致性超额收益分析", ""])
    md_lines.append("| 一致性 | 样本数 | 股票收益 | 基准收益 | 超额收益 | 超额胜率 |")
    md_lines.append("|---|---:|---:|---:|---:|---:|")
    
    for alignment, stats in sorted(analysis.get("mtf_excess", {}).items(),
                                    key=lambda x: x[1]["avg_excess_return"], reverse=True):
        md_lines.append(
            f"| {alignment} | {stats['count']} | {stats['avg_stock_return']:.2f}% | "
            f"{stats['avg_benchmark_return']:.2f}% | **{stats['avg_excess_return']:.2f}%** | "
            f"{stats['excess_win_rate']:.1f}% |"
        )
    
    # 添加结论
    md_lines.extend(["", "## 结论", ""])
    
    phase_excess = analysis.get("phase_excess", {})
    signal_excess = analysis.get("signal_excess", {})
    
    # 找出最佳阶段
    best_phase = max(phase_excess.items(), key=lambda x: x[1]["avg_excess_return"])
    md_lines.append(f"- **最佳阶段**: {best_phase[0]}，超额收益 **{best_phase[1]['avg_excess_return']:.2f}%**")
    
    # 找出最佳信号
    best_signal = max(signal_excess.items(), key=lambda x: x[1]["avg_excess_return"])
    md_lines.append(f"- **最佳信号**: {best_signal[0]}，超额收益 **{best_signal[1]['avg_excess_return']:.2f}%**")
    
    # 整体超额收益
    overall_excess = analysis.get("overall_avg_excess_return", 0)
    if overall_excess > 0:
        md_lines.append(f"- **整体超额收益**: +{overall_excess:.2f}%，跑赢基准")
    else:
        md_lines.append(f"- **整体超额收益**: {overall_excess:.2f}%，跑输基准")
    
    (output_dir / "excess_returns_report.md").write_text("\n".join(md_lines), encoding="utf-8")
    
    print("输出文件:")
    print(f"  - {output_dir / 'excess_returns_analysis.json'}")
    print(f"  - {output_dir / 'excess_returns_report.md'}")


def main() -> None:
    """主函数"""
    input_dir = PROJECT_ROOT / "output" / "wyckoff_8cycle_300d_test"
    output_dir = PROJECT_ROOT / "output" / "wyckoff_8cycle_300d_excess_returns"
    
    print("=" * 60)
    print("超额收益分析（基准：沪深300）- 8 Cycle 300 Days Test (5199 Stocks)")
    print("=" * 60)
    
    # 加载测试结果
    print("\n1. 加载测试结果...")
    results = []
    with (input_dir / "cycle8_raw_results.jsonl").open("r", encoding="utf-8") as f:
        for line in f:
            results.append(json.loads(line))
    print(f"   加载了 {len(results)} 条记录")
    
    # 加载沪深300数据
    print("\n2. 加载沪深300数据...")
    dm = DataManager()
    benchmark_df = dm.get_data("000300.SH")
    benchmark_df["date"] = pd.to_datetime(benchmark_df["date"])
    benchmark_df = benchmark_df.sort_values("date").reset_index(drop=True)
    print(f"   加载了 {len(benchmark_df)} 条记录")
    
    # 计算超额收益
    print("\n3. 计算超额收益...")
    enhanced_results = calculate_excess_returns(results, benchmark_df)
    print(f"   计算了 {len(enhanced_results)} 条记录")
    
    # 分析超额收益
    print("\n4. 分析超额收益...")
    analysis = analyze_excess_returns(enhanced_results)
    
    # 输出报告
    print("\n5. 输出报告...")
    write_excess_report(output_dir, analysis)
    
    # 打印摘要
    print("\n" + "=" * 60)
    print("摘要:")
    print(f"  总样本数: {analysis.get('total_samples', 0)}")
    print(f"  整体平均股票收益: {analysis.get('overall_avg_stock_return', 0):.2f}%")
    print(f"  整体平均基准收益: {analysis.get('overall_avg_benchmark_return', 0):.2f}%")
    print(f"  整体平均超额收益: {analysis.get('overall_avg_excess_return', 0):.2f}%")
    print(f"  超额收益胜率: {analysis.get('overall_excess_win_rate', 0):.1f}%")
    print("=" * 60)


if __name__ == "__main__":
    main()
