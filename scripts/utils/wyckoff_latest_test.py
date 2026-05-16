#!/usr/bin/env python3
# RESEARCH ONLY — not production code
# -*- coding: utf-8 -*-
"""
2组最新日线完整周期测试
- 使用最新日线日期
- 1200天日线 + 周线 + 月线多周期分析
- 对比分析结果和检查重构效果
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.data.manager import DataManager
from src.wyckoff.engine import WyckoffEngine


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
            # 包含所有A股：主板、中小板、创业板、科创板
            if code.startswith(("600", "601", "603", "605", "688", "689",  # 上海
                               "000", "001", "002", "003", "300", "301", "302")):  # 深圳
                symbols.append({
                    "symbol": f"{code}.{market}",
                    "code": code,
                    "market": market,
                    "name": name,
                })
            if len(symbols) >= limit:
                break
    return symbols


def get_latest_dates(dm: DataManager, sample_symbol: str = "600000.SH") -> List[str]:
    """获取最新的2个交易日日期"""
    df = dm.get_data(sample_symbol)
    if df is None or df.empty:
        return []
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date")
    # 获取最近的2个交易日
    latest_dates = df["date"].tail(2).dt.strftime("%Y-%m-%d").tolist()
    return latest_dates


def analyze_stock(
    engine: WyckoffEngine,
    df: pd.DataFrame,
    symbol: str,
    name: str,
    as_of_date: str,
) -> Optional[Dict]:
    """分析单只股票"""
    as_of = pd.Timestamp(as_of_date)
    available_data = df[df["date"] <= as_of]
    if len(available_data) < 100:
        return None

    report = engine.analyze(available_data, symbol=symbol, period="日线", multi_timeframe=True)

    return {
        "as_of": as_of_date,
        "symbol": symbol,
        "name": name,
        "phase": report.structure.phase.value,
        "sub_phase": report.structure.unknown_candidate,
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
        "t1_verdict": report.signal.t1_risk评估[:50] if report.signal.t1_risk评估 else "",
        "preconditions": report.trading_plan.preconditions[:100] if report.trading_plan.preconditions else "",
        "trigger": report.trading_plan.trigger_condition[:100] if report.trading_plan.trigger_condition else "",
        "invalidation": report.trading_plan.invalidation_point[:100] if report.trading_plan.invalidation_point else "",
        "first_target_text": report.trading_plan.first_target[:100] if report.trading_plan.first_target else "",
    }


def run_latest_test(
    symbols: List[Dict[str, str]],
    output_dir: Path,
    lookback_days: int = 200,
) -> List[Dict]:
    """运行最新日线测试"""
    engine = WyckoffEngine(lookback_days=lookback_days)
    dm = DataManager()

    # 获取最新日期
    latest_dates = get_latest_dates(dm)
    if not latest_dates:
        print("无法获取最新日期")
        return []

    print(f"最新日期: {latest_dates}")

    all_results = []
    total = len(symbols) * len(latest_dates)
    completed = 0
    failed = 0

    for symbol_info in symbols:
        symbol = symbol_info["symbol"]
        name = symbol_info["name"]

        df = dm.get_data(symbol)
        if df is None or df.empty:
            failed += len(latest_dates)
            continue

        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)

        for date in latest_dates:
            result = analyze_stock(engine, df, symbol, name, date)
            if result:
                all_results.append(result)
                completed += 1
            else:
                failed += 1

        if completed % 500 == 0 and completed > 0:
            print(f"  已完成 {completed}/{total} 次分析")

    print(f"\n测试完成: 成功 {completed}, 失败 {failed}")
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


def analyze_and_output(results: List[Dict], output_dir: Path) -> Dict:
    """分析并输出结果"""
    output_dir.mkdir(parents=True, exist_ok=True)

    if not results:
        return {}

    df = pd.DataFrame(results)

    # 阶段分布
    phase_stats = {}
    for phase in df["phase"].unique():
        phase_df = df[df["phase"] == phase]
        phase_stats[phase] = {
            "count": len(phase_df),
            "pct": round(len(phase_df) / len(df) * 100, 1),
        }

    # 信号分布
    signal_stats = {}
    for signal in df["signal_type"].unique():
        sig_df = df[df["signal_type"] == signal]
        signal_stats[signal] = {
            "count": len(sig_df),
            "pct": round(len(sig_df) / len(df) * 100, 1),
        }

    # 方向分布
    direction_stats = {}
    for direction in df["direction"].unique():
        dir_df = df[df["direction"] == direction]
        direction_stats[direction] = {
            "count": len(dir_df),
            "pct": round(len(dir_df) / len(df) * 100, 1),
        }

    # 置信度分布
    confidence_stats = {}
    for conf in df["confidence"].unique():
        conf_df = df[df["confidence"] == conf]
        confidence_stats[conf] = {
            "count": len(conf_df),
            "pct": round(len(conf_df) / len(df) * 100, 1),
        }

    # 多周期一致性
    mtf_stats = {}
    for alignment in df["mtf_alignment"].unique():
        if alignment:
            mtf_df = df[df["mtf_alignment"] == alignment]
            mtf_stats[alignment] = {
                "count": len(mtf_df),
                "pct": round(len(mtf_df) / len(df) * 100, 1),
            }

    analysis = {
        "total_samples": len(df),
        "dates": df["as_of"].unique().tolist(),
        "phase_stats": phase_stats,
        "signal_stats": signal_stats,
        "direction_stats": direction_stats,
        "confidence_stats": confidence_stats,
        "mtf_stats": mtf_stats,
    }

    # 保存原始数据
    with (output_dir / "latest_raw_results.jsonl").open("w", encoding="utf-8") as f:
        for row in results:
            f.write(json.dumps(convert_keys_to_str(row), ensure_ascii=False) + "\n")

    # 保存CSV
    df.to_csv(output_dir / "latest_results.csv", index=False, encoding="utf-8-sig")

    # 保存分析
    with (output_dir / "latest_analysis.json").open("w", encoding="utf-8") as f:
        json.dump(convert_keys_to_str(analysis), f, ensure_ascii=False, indent=2)

    # 生成Markdown报告
    md_lines = [
        "# 最新日线 Wyckoff Engine 测试报告",
        "",
        f"- 测试日期: {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 总样本数: {len(df)}",
        f"- 分析日期: {', '.join(df['as_of'].unique().tolist())}",
        "- 日线回看: 1200天",
        "- 多周期分析: 日线+周线+月线",
        "",
        "## 阶段分布",
        "",
        "| 阶段 | 样本数 | 占比 |",
        "|---|---:|---:|",
    ]

    for phase, stats in sorted(phase_stats.items(), key=lambda x: x[1]["count"], reverse=True):
        md_lines.append(f"| {phase} | {stats['count']} | {stats['pct']}% |")

    md_lines.extend(["", "## 信号类型分布", ""])
    md_lines.append("| 信号类型 | 样本数 | 占比 |")
    md_lines.append("|---|---:|---:|")
    for signal, stats in sorted(signal_stats.items(), key=lambda x: x[1]["count"], reverse=True):
        md_lines.append(f"| {signal} | {stats['count']} | {stats['pct']}% |")

    md_lines.extend(["", "## 方向分布", ""])
    md_lines.append("| 方向 | 样本数 | 占比 |")
    md_lines.append("|---|---:|---:|")
    for direction, stats in sorted(direction_stats.items(), key=lambda x: x[1]["count"], reverse=True):
        md_lines.append(f"| {direction} | {stats['count']} | {stats['pct']}% |")

    md_lines.extend(["", "## 置信度分布", ""])
    md_lines.append("| 置信度 | 样本数 | 占比 |")
    md_lines.append("|---|---:|---:|")
    for conf, stats in sorted(confidence_stats.items()):
        md_lines.append(f"| {conf} | {stats['count']} | {stats['pct']}% |")

    md_lines.extend(["", "## 多周期一致性", ""])
    md_lines.append("| 一致性 | 样本数 | 占比 |")
    md_lines.append("|---|---:|---:|")
    for alignment, stats in sorted(mtf_stats.items(), key=lambda x: x[1]["count"], reverse=True):
        md_lines.append(f"| {alignment} | {stats['count']} | {stats['pct']}% |")

    # 信号样本详情
    md_lines.extend(["", "## Spring信号样本", ""])
    spring_df = df[df["signal_type"] == "spring"].head(20)
    if not spring_df.empty:
        md_lines.append("| Symbol | Name | Phase | Direction | RR | Price |")
        md_lines.append("|---|---|---|---|---:|---:|")
        for _, row in spring_df.iterrows():
            md_lines.append(f"| {row['symbol']} | {row['name']} | {row['phase']} | {row['direction']} | {row['rr_ratio']} | {row['entry_price']} |")
    else:
        md_lines.append("| - | - | - | - | - | - |")

    md_lines.extend(["", "## SOS信号样本", ""])
    sos_df = df[df["signal_type"] == "sos_candidate"].head(20)
    if not sos_df.empty:
        md_lines.append("| Symbol | Name | Phase | Direction | RR | Price |")
        md_lines.append("|---|---|---|---|---:|---:|")
        for _, row in sos_df.iterrows():
            md_lines.append(f"| {row['symbol']} | {row['name']} | {row['phase']} | {row['direction']} | {row['rr_ratio']} | {row['entry_price']} |")
    else:
        md_lines.append("| - | - | - | - | - | - |")

    md_lines.extend(["", "## Accumulation信号样本", ""])
    acc_df = df[df["signal_type"] == "accumulation"].head(20)
    if not acc_df.empty:
        md_lines.append("| Symbol | Name | Phase | Direction | RR | Price |")
        md_lines.append("|---|---|---|---|---:|---:|")
        for _, row in acc_df.iterrows():
            md_lines.append(f"| {row['symbol']} | {row['name']} | {row['phase']} | {row['direction']} | {row['rr_ratio']} | {row['entry_price']} |")
    else:
        md_lines.append("| - | - | - | - | - | - |")

    (output_dir / "latest_report.md").write_text("\n".join(md_lines), encoding="utf-8")

    print("\n输出文件:")
    print(f"  - {output_dir / 'latest_raw_results.jsonl'}")
    print(f"  - {output_dir / 'latest_results.csv'}")
    print(f"  - {output_dir / 'latest_analysis.json'}")
    print(f"  - {output_dir / 'latest_report.md'}")

    return analysis


def main():
    output_dir = PROJECT_ROOT / "output" / "wyckoff_latest_200d_test"
    csv_path = PROJECT_ROOT / "data" / "stock_list.csv"

    print("=" * 60)
    print("Wyckoff Engine v3.0 - 最新日线测试 (ALL Stocks, 200 Days)")
    print("=" * 60)

    print("\n1. 加载股票列表...")
    symbols = load_stock_symbols(csv_path, limit=99999)
    print(f"   加载了 {len(symbols)} 只股票")

    print("\n2. 运行测试...")
    results = run_latest_test(symbols, output_dir, lookback_days=200)

    print("\n3. 分析结果...")
    analysis = analyze_and_output(results, output_dir)

    print("\n" + "=" * 60)
    print("测试摘要:")
    print(f"  总样本数: {analysis.get('total_samples', 0)}")
    print(f"  分析日期: {analysis.get('dates', [])}")
    print("=" * 60)


if __name__ == "__main__":
    main()