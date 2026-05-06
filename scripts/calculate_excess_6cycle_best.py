#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
计算超额收益 - 以沪深300为基准（6周期最佳日期版本）
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.data.manager import DataManager


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


def calculate_benchmark_return(
    benchmark_df: pd.DataFrame,
    as_of_date: str,
    days: int = 120
) -> Optional[Dict[str, float]]:
    as_of = pd.Timestamp(as_of_date)
    future_data = benchmark_df[benchmark_df["date"] > as_of].head(days)
    if len(future_data) < days * 0.8:
        return None
    entry_price = float(benchmark_df[benchmark_df["date"] <= as_of].iloc[-1]["close"])
    future_close = float(future_data.iloc[-1]["close"])
    future_high = float(future_data["high"].max())
    future_low = float(future_data["low"].min())
    return_pct = (future_close - entry_price) / entry_price * 100
    return {
        "entry_price": round(entry_price, 3),
        "future_close": round(future_close, 3),
        "return_pct": round(return_pct, 2),
    }


def calculate_excess_returns(test_results, benchmark_df):
    enhanced_results = []
    for result in test_results:
        as_of = result.get("as_of")
        if not as_of:
            continue
        benchmark = calculate_benchmark_return(benchmark_df, as_of, days=120)
        if benchmark is None:
            continue
        stock_return = result.get("future_120d_return", 0)
        benchmark_return = benchmark["return_pct"]
        excess_return = stock_return - benchmark_return
        enhanced_result = result.copy()
        enhanced_result["benchmark_return"] = benchmark_return
        enhanced_result["excess_return"] = round(excess_return, 2)
        enhanced_results.append(enhanced_result)
    return enhanced_results


def analyze_excess_returns(results):
    if not results:
        return {}
    df = pd.DataFrame(results)
    
    phase_excess = {}
    for phase in df["phase"].unique():
        phase_df = df[df["phase"] == phase]
        phase_excess[phase] = {
            "count": len(phase_df),
            "avg_stock_return": round(phase_df["future_120d_return"].mean(), 2),
            "avg_benchmark_return": round(phase_df["benchmark_return"].mean(), 2),
            "avg_excess_return": round(phase_df["excess_return"].mean(), 2),
            "excess_win_rate": round(len(phase_df[phase_df["excess_return"] > 0]) / len(phase_df) * 100, 1),
        }
    
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
        "cycle_excess": cycle_excess,
        "confidence_excess": confidence_excess,
        "mtf_excess": mtf_excess,
    }


def main():
    input_dir = PROJECT_ROOT / "output" / "wyckoff_6cycle_best_dates_test"
    output_dir = PROJECT_ROOT / "output" / "wyckoff_6cycle_best_dates_excess"
    
    print("加载测试结果...")
    results = []
    with (input_dir / "cycle6_raw_results.jsonl").open("r", encoding="utf-8") as f:
        for line in f:
            results.append(json.loads(line))
    print(f"  加载了 {len(results)} 条记录")
    
    print("加载沪深300数据...")
    dm = DataManager()
    benchmark_df = dm.get_data("000300.SH")
    benchmark_df["date"] = pd.to_datetime(benchmark_df["date"])
    benchmark_df = benchmark_df.sort_values("date").reset_index(drop=True)
    print(f"  加载了 {len(benchmark_df)} 条记录")
    
    print("计算超额收益...")
    enhanced_results = calculate_excess_returns(results, benchmark_df)
    print(f"  计算了 {len(enhanced_results)} 条记录")
    
    print("分析超额收益...")
    analysis = analyze_excess_returns(enhanced_results)
    
    output_dir.mkdir(parents=True, exist_ok=True)
    with (output_dir / "excess_returns_analysis.json").open("w", encoding="utf-8") as f:
        json.dump(convert_keys_to_str(analysis), f, ensure_ascii=False, indent=2)
    
    print(f"\n摘要:")
    print(f"  总样本数: {analysis.get('total_samples', 0)}")
    print(f"  整体股票收益: {analysis.get('overall_avg_stock_return', 0):.2f}%")
    print(f"  整体基准收益: {analysis.get('overall_avg_benchmark_return', 0):.2f}%")
    print(f"  整体超额收益: {analysis.get('overall_avg_excess_return', 0):+.2f}%")
    print(f"  超额胜率: {analysis.get('overall_excess_win_rate', 0):.1f}%")


if __name__ == "__main__":
    main()
