#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
6周期测试 - 最佳版本日期 + 多进程优化版
使用ProcessPoolExecutor绕过GIL，实现真正并行
"""

from __future__ import annotations

import csv
import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd
import numpy as np
import psutil

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@dataclass(frozen=True)
class CycleSpec:
    cycle_id: int
    year: int
    as_of_date: str
    description: str


def get_optimal_workers() -> int:
    """根据系统资源计算最优worker数量"""
    cpu_count = psutil.cpu_count(logical=True)
    memory = psutil.virtual_memory()
    
    # 每个worker大约需要300MB内存
    memory_per_worker = 300  # MB
    available_memory_mb = memory.available / (1024**2)
    max_workers_by_memory = int(available_memory_mb / memory_per_worker)
    
    # 留2个核心给系统
    max_workers_by_cpu = max(1, cpu_count - 2)
    
    # 取较小值，最少2个，最多12个
    optimal = min(max_workers_by_memory, max_workers_by_cpu)
    return max(2, min(optimal, 12))


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


def generate_cycle_specs() -> List[CycleSpec]:
    """使用最佳版本(a438a32)的测试日期"""
    return [
        CycleSpec(cycle_id=1, year=2012, as_of_date="2012-05-13", description="Year 2012 Cycle 1"),
        CycleSpec(cycle_id=2, year=2013, as_of_date="2013-11-12", description="Year 2013 Cycle 2"),
        CycleSpec(cycle_id=3, year=2015, as_of_date="2015-09-11", description="Year 2015 Cycle 3"),
        CycleSpec(cycle_id=4, year=2016, as_of_date="2016-03-12", description="Year 2016 Cycle 4"),
        CycleSpec(cycle_id=5, year=2021, as_of_date="2021-06-17", description="Year 2021 Cycle 5"),
        CycleSpec(cycle_id=6, year=2022, as_of_date="2022-11-10", description="Year 2022 Cycle 6"),
    ]


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


def process_single_stock(args: tuple) -> List[Dict]:
    """处理单只股票的所有周期（用于多进程）"""
    symbol_info, cycle_specs, lookback_days = args
    symbol = symbol_info["symbol"]
    name = symbol_info["name"]
    results = []

    try:
        # 在子进程中导入和初始化
        from src.data.manager import DataManager
        from src.wyckoff.engine import WyckoffEngine
        
        dm = DataManager()
        df = dm.get_data(symbol)
        if df is None or df.empty:
            return results

        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)

        engine = WyckoffEngine(lookback_days=lookback_days)

        for spec in cycle_specs:
            as_of = pd.Timestamp(spec.as_of_date)
            available_data = df[df["date"] <= as_of]
            if len(available_data) < 100:
                continue
            
            report = engine.analyze(available_data, symbol=symbol, period="日线", multi_timeframe=True)
            future_return = calculate_future_return(df, spec.as_of_date, days=120)
            
            if future_return is None:
                continue
            
            results.append({
                "cycle_id": spec.cycle_id,
                "cycle_year": spec.year,
                "as_of": spec.as_of_date,
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
            })
    except Exception as e:
        pass

    return results


def run_6cycle_test_multiprocess(
    symbols: List[Dict[str, str]],
    cycle_specs: List[CycleSpec],
    output_dir: Path,
    lookback_days: int = 300,
    max_workers: int = None,
) -> List[Dict]:
    """运行 6 组完整周期测试（多进程版）"""
    if max_workers is None:
        max_workers = get_optimal_workers()

    total_tests = len(symbols) * len(cycle_specs)
    print(f"开始测试: {len(symbols)} 只股票 × {len(cycle_specs)} 个周期 = {total_tests} 次分析")
    print(f"多进程: {max_workers} workers (ProcessPoolExecutor)")
    print(f"日线回看: {lookback_days} 天")
    
    # 显示系统资源
    memory = psutil.virtual_memory()
    print(f"系统内存: {memory.total / (1024**3):.1f}GB 总计, {memory.available / (1024**3):.1f}GB 可用")
    print("=" * 60)

    all_results = []
    completed_stocks = 0
    
    # 准备参数
    args_list = [(symbol_info, cycle_specs, lookback_days) for symbol_info in symbols]

    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(process_single_stock, args): args[0]
            for args in args_list
        }

        for future in as_completed(futures):
            completed_stocks += 1
            try:
                results = future.result(timeout=300)
                all_results.extend(results)
            except Exception as e:
                pass

            if completed_stocks % 200 == 0:
                # 显示进度和内存使用
                memory = psutil.virtual_memory()
                print(f"  已处理 {completed_stocks}/{len(symbols)} 只股票, 累计 {len(all_results)} 条结果, 内存: {memory.percent}%")

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
    }


def write_outputs(output_dir: Path, results: List[Dict], analysis: Dict) -> None:
    """输出结果到文件"""
    output_dir.mkdir(parents=True, exist_ok=True)

    with (output_dir / "cycle6_raw_results.jsonl").open("w", encoding="utf-8") as f:
        for row in results:
            f.write(json.dumps(convert_keys_to_str(row), ensure_ascii=False) + "\n")

    if results:
        df = pd.DataFrame(results)
        df.to_csv(output_dir / "cycle6_results.csv", index=False, encoding="utf-8-sig")

    with (output_dir / "cycle6_analysis.json").open("w", encoding="utf-8") as f:
        json.dump(convert_keys_to_str(analysis), f, ensure_ascii=False, indent=2)

    md_lines = [
        "# 6-Cycle Wyckoff Engine Test Report (Optimized Multiprocess)",
        "",
        f"- 测试日期: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 总样本数: {analysis.get('total_samples', 0)}",
        f"- 整体平均收益: {analysis.get('overall_avg_return', 0):.2f}%",
        f"- 整体胜率: {analysis.get('overall_win_rate', 0):.1f}%",
        f"- 日线回看: 300天",
        f"- 多周期分析: 日线+周线+月线（周线/月线折合600天）",
        f"- 测试周期: 6周期（复刻最佳版本a438a32日期）",
        f"- 并行方式: ProcessPoolExecutor (多进程)",
        "",
        "## 阶段分布与未来收益",
        "",
        "| 阶段 | 样本数 | 平均收益 | 中位收益 | 胜率 | 平均最大涨幅 | 平均最大回撤 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]

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

    (output_dir / "cycle6_report.md").write_text("\n".join(md_lines), encoding="utf-8")

    print(f"\n输出文件:")
    print(f"  - {output_dir / 'cycle6_raw_results.jsonl'}")
    print(f"  - {output_dir / 'cycle6_results.csv'}")
    print(f"  - {output_dir / 'cycle6_analysis.json'}")
    print(f"  - {output_dir / 'cycle6_report.md'}")


def main() -> None:
    """主函数"""
    output_dir = PROJECT_ROOT / "output" / "wyckoff_6cycle_best_dates_test"
    csv_path = PROJECT_ROOT / "data" / "stock_list.csv"

    print("=" * 60)
    print("Wyckoff Engine v3.0 - 6 Cycle Test (Optimized Multiprocess)")
    print("=" * 60)

    print("\n1. 加载股票列表...")
    symbols = load_stock_symbols(csv_path, limit=99999)
    print(f"   加载了 {len(symbols)} 只股票")

    print("\n2. 生成测试周期（复刻最佳版本日期）...")
    cycle_specs = generate_cycle_specs()
    for spec in cycle_specs:
        print(f"   Cycle {spec.cycle_id}: Year {spec.year}, Date {spec.as_of_date}")

    print("\n3. 运行测试（多进程）...")
    results = run_6cycle_test_multiprocess(symbols, cycle_specs, output_dir, lookback_days=300)

    print("\n4. 分析结果...")
    analysis = analyze_results(results)

    print("\n5. 输出结果...")
    write_outputs(output_dir, results, analysis)

    print("\n" + "=" * 60)
    print("测试摘要:")
    print(f"  总样本数: {analysis.get('total_samples', 0)}")
    print(f"  整体平均收益: {analysis.get('overall_avg_return', 0):.2f}%")
    print(f"  整体胜率: {analysis.get('overall_win_rate', 0):.1f}%")
    print("=" * 60)


if __name__ == "__main__":
    main()
