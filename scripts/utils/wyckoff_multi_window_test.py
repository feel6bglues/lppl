#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
5窗口对比测试 - 200/400/600/1000/1200天日线 + 周线月线多周期分析
- 使用最新日线日期
- 对比不同窗口的分析结果
- 检查重构效果
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


def get_latest_dates(dm: DataManager, sample_symbol: str = "600000.SH") -> List[str]:
    df = dm.get_data(sample_symbol)
    if df is None or df.empty:
        return []
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date")
    latest_dates = df["date"].tail(2).dt.strftime("%Y-%m-%d").tolist()
    return latest_dates


def analyze_stock(
    engine: WyckoffEngine,
    df: pd.DataFrame,
    symbol: str,
    name: str,
    as_of_date: str,
) -> Optional[Dict]:
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
        "direction": report.trading_plan.direction,
        "confidence": report.trading_plan.confidence.value,
        "rr_ratio": round(report.risk_reward.reward_risk_ratio, 3),
        "entry_price": round(report.risk_reward.entry_price or 0, 3),
        "bc_price": round(report.structure.bc_point.price, 3) if report.structure.bc_point else None,
        "tr_low": round(report.structure.trading_range_low or 0, 3),
        "tr_high": round(report.structure.trading_range_high or 0, 3),
        "signal_type": report.signal.signal_type,
        "monthly_phase": report.multi_timeframe.monthly.phase.value if report.multi_timeframe and report.multi_timeframe.monthly else "",
        "weekly_phase": report.multi_timeframe.weekly.phase.value if report.multi_timeframe and report.multi_timeframe.weekly else "",
        "daily_phase": report.multi_timeframe.daily.phase.value if report.multi_timeframe and report.multi_timeframe.daily else "",
        "mtf_alignment": report.multi_timeframe.alignment if report.multi_timeframe else "",
    }


def run_window_test(
    symbols: List[Dict[str, str]],
    dm: DataManager,
    lookback_days: int,
    dates: List[str],
) -> List[Dict]:
    engine = WyckoffEngine(lookback_days=lookback_days)
    results = []
    total = len(symbols) * len(dates)
    completed = 0
    failed = 0

    for symbol_info in symbols:
        symbol = symbol_info["symbol"]
        name = symbol_info["name"]

        df = dm.get_data(symbol)
        if df is None or df.empty:
            failed += len(dates)
            continue

        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)

        for date in dates:
            result = analyze_stock(engine, df, symbol, name, date)
            if result:
                result["lookback_days"] = lookback_days
                results.append(result)
                completed += 1
            else:
                failed += 1

        if completed % 500 == 0 and completed > 0:
            print(f"    已完成 {completed}/{total}")

    print(f"    成功 {completed}, 失败 {failed}")
    return results


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


def analyze_window_results(results: List[Dict]) -> Dict:
    if not results:
        return {}

    df = pd.DataFrame(results)
    analysis = {}

    # 按窗口分组
    for window in df["lookback_days"].unique():
        window_df = df[df["lookback_days"] == window]

        phase_stats = {}
        for phase in window_df["phase"].unique():
            phase_df = window_df[window_df["phase"] == phase]
            phase_stats[phase] = {
                "count": len(phase_df),
                "pct": round(len(phase_df) / len(window_df) * 100, 1),
            }

        signal_stats = {}
        for signal in window_df["signal_type"].unique():
            sig_df = window_df[window_df["signal_type"] == signal]
            signal_stats[signal] = {
                "count": len(sig_df),
                "pct": round(len(sig_df) / len(window_df) * 100, 1),
            }

        direction_stats = {}
        for direction in window_df["direction"].unique():
            dir_df = window_df[window_df["direction"] == direction]
            direction_stats[direction] = {
                "count": len(dir_df),
                "pct": round(len(dir_df) / len(window_df) * 100, 1),
            }

        confidence_stats = {}
        for conf in window_df["confidence"].unique():
            conf_df = window_df[window_df["confidence"] == conf]
            confidence_stats[conf] = {
                "count": len(conf_df),
                "pct": round(len(conf_df) / len(window_df) * 100, 1),
            }

        mtf_stats = {}
        for alignment in window_df["mtf_alignment"].unique():
            if alignment:
                mtf_df = window_df[window_df["mtf_alignment"] == alignment]
                mtf_stats[alignment] = {
                    "count": len(mtf_df),
                    "pct": round(len(mtf_df) / len(window_df) * 100, 1),
                }

        analysis[window] = {
            "total_samples": len(window_df),
            "phase_stats": phase_stats,
            "signal_stats": signal_stats,
            "direction_stats": direction_stats,
            "confidence_stats": confidence_stats,
            "mtf_stats": mtf_stats,
        }

    return analysis


def write_outputs(all_results: List[Dict], analysis: Dict, output_dir: Path):
    output_dir.mkdir(parents=True, exist_ok=True)

    # 保存原始数据
    with (output_dir / "multi_window_raw_results.jsonl").open("w", encoding="utf-8") as f:
        for row in all_results:
            f.write(json.dumps(convert_keys_to_str(row), ensure_ascii=False) + "\n")

    # 保存CSV
    df = pd.DataFrame(all_results)
    df.to_csv(output_dir / "multi_window_results.csv", index=False, encoding="utf-8-sig")

    # 保存分析
    with (output_dir / "multi_window_analysis.json").open("w", encoding="utf-8") as f:
        json.dump(convert_keys_to_str(analysis), f, ensure_ascii=False, indent=2)

    # 生成Markdown报告
    md_lines = [
        "# 5窗口对比测试报告",
        "",
        f"- 测试日期: {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 总样本数: {len(all_results)}",
        "- 窗口: 200/400/600/1000/1200天",
        "- 多周期分析: 日线+周线+月线",
        "",
        "## 窗口对比总览",
        "",
        "| 窗口 | 样本数 | Markdown | Unknown | Markup | Distribution | Accumulation |",
        "|---:|---:|---:|---:|---:|---:|---:|",
    ]

    for window in sorted(analysis.keys()):
        stats = analysis[window]
        phase = stats["phase_stats"]
        md_lines.append(
            f"| {window}天 | {stats['total_samples']} | "
            f"{phase.get('markdown', {}).get('pct', 0)}% | "
            f"{phase.get('unknown', {}).get('pct', 0)}% | "
            f"{phase.get('markup', {}).get('pct', 0)}% | "
            f"{phase.get('distribution', {}).get('pct', 0)}% | "
            f"{phase.get('accumulation', {}).get('pct', 0)}% |"
        )

    md_lines.extend(["", "## 信号类型对比", ""])
    md_lines.append("| 窗口 | no_signal | markup | markdown | spring | accumulation | sos_candidate |")
    md_lines.append("|---:|---:|---:|---:|---:|---:|---:|")

    for window in sorted(analysis.keys()):
        stats = analysis[window]
        sig = stats["signal_stats"]
        md_lines.append(
            f"| {window}天 | "
            f"{sig.get('no_signal', {}).get('pct', 0)}% | "
            f"{sig.get('markup', {}).get('pct', 0)}% | "
            f"{sig.get('markdown', {}).get('pct', 0)}% | "
            f"{sig.get('spring', {}).get('pct', 0)}% | "
            f"{sig.get('accumulation', {}).get('pct', 0)}% | "
            f"{sig.get('sos_candidate', {}).get('pct', 0)}% |"
        )

    md_lines.extend(["", "## 方向对比", ""])
    md_lines.append("| 窗口 | 空仓观望 | 持有观察 | 观察等待 | 轻仓试探 | 做多 |")
    md_lines.append("|---:|---:|---:|---:|---:|---:|")

    for window in sorted(analysis.keys()):
        stats = analysis[window]
        dir_stats = stats["direction_stats"]
        md_lines.append(
            f"| {window}天 | "
            f"{dir_stats.get('空仓观望', {}).get('pct', 0)}% | "
            f"{dir_stats.get('持有观察', {}).get('pct', 0)}% | "
            f"{dir_stats.get('观察等待', {}).get('pct', 0)}% | "
            f"{dir_stats.get('轻仓试探', {}).get('pct', 0)}% | "
            f"{dir_stats.get('做多', {}).get('pct', 0)}% |"
        )

    md_lines.extend(["", "## 置信度对比", ""])
    md_lines.append("| 窗口 | A | B | C | D |")
    md_lines.append("|---:|---:|---:|---:|---:|")

    for window in sorted(analysis.keys()):
        stats = analysis[window]
        conf = stats["confidence_stats"]
        md_lines.append(
            f"| {window}天 | "
            f"{conf.get('A', {}).get('pct', 0)}% | "
            f"{conf.get('B', {}).get('pct', 0)}% | "
            f"{conf.get('C', {}).get('pct', 0)}% | "
            f"{conf.get('D', {}).get('pct', 0)}% |"
        )

    md_lines.extend(["", "## 多周期一致性对比", ""])
    md_lines.append("| 窗口 | fully_aligned | weekly_daily_aligned | higher_timeframe_aligned | mixed |")
    md_lines.append("|---:|---:|---:|---:|---:|")

    for window in sorted(analysis.keys()):
        stats = analysis[window]
        mtf = stats["mtf_stats"]
        md_lines.append(
            f"| {window}天 | "
            f"{mtf.get('fully_aligned', {}).get('pct', 0)}% | "
            f"{mtf.get('weekly_daily_aligned', {}).get('pct', 0)}% | "
            f"{mtf.get('higher_timeframe_aligned', {}).get('pct', 0)}% | "
            f"{mtf.get('mixed', {}).get('pct', 0)}% |"
        )

    (output_dir / "multi_window_report.md").write_text("\n".join(md_lines), encoding="utf-8")

    print("\n输出文件:")
    print(f"  - {output_dir / 'multi_window_raw_results.jsonl'}")
    print(f"  - {output_dir / 'multi_window_results.csv'}")
    print(f"  - {output_dir / 'multi_window_analysis.json'}")
    print(f"  - {output_dir / 'multi_window_report.md'}")


def main():
    output_dir = PROJECT_ROOT / "output" / "wyckoff_multi_window_test"
    csv_path = PROJECT_ROOT / "data" / "stock_list.csv"
    windows = [200, 400, 600, 1000, 1200]

    print("=" * 60)
    print("Wyckoff Engine v3.0 - 5窗口对比测试")
    print("=" * 60)

    print("\n1. 加载股票列表...")
    symbols = load_stock_symbols(csv_path, limit=99999)
    print(f"   加载了 {len(symbols)} 只股票")

    print("\n2. 获取最新日期...")
    dm = DataManager()
    dates = get_latest_dates(dm)
    print(f"   分析日期: {dates}")

    print("\n3. 运行5窗口测试...")
    all_results = []

    for window in windows:
        print(f"\n  窗口 {window}天:")
        results = run_window_test(symbols, dm, window, dates)
        all_results.extend(results)

    print("\n4. 分析结果...")
    analysis = analyze_window_results(all_results)

    print("\n5. 输出结果...")
    write_outputs(all_results, analysis, output_dir)

    print("\n" + "=" * 60)
    print("测试摘要:")
    print(f"  总样本数: {len(all_results)}")
    print(f"  窗口数: {len(windows)}")
    print(f"  每窗口样本: {len(all_results) // len(windows)}")
    print("=" * 60)


if __name__ == "__main__":
    main()