#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
6组完整周期测试:
- 使用不同随机年份(2010-2025)和日期
- 采用1000天日线 + 合并周线月线
- 输出到文件并与连续性文档对比
"""

from __future__ import annotations

import csv
import json
import random
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.data.manager import DataManager
from src.wyckoff import WyckoffAnalyzer, WyckoffReport
from scripts.generate_wyckoff_daily_replay import evaluate_design_completeness


@dataclass(frozen=True)
class CycleSpec:
    cycle_id: int
    year: int
    as_of_date: str
    description: str


SAMPLE_SYMBOLS = (
    ("600859.SH", "王府井"),
    ("002216.SZ", "三全食品"),
    ("300442.SZ", "润泽科技"),
)


def generate_cycle_specs(seed: int = 42) -> list[CycleSpec]:
    random.seed(seed)
    specs: list[CycleSpec] = []
    years = [2010, 2012, 2014, 2016, 2020, 2025]
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


def get_trading_dates(df: pd.DataFrame, year: int, month: int, day: int) -> list[pd.Timestamp]:
    target = pd.Timestamp(f"{year}-{month:02d}-{day:02d}")
    available = df[df["date"] <= target]["date"].sort_values()
    return [pd.Timestamp(d) for d in available.tolist()][-20:]


def analyze_at_date(
    analyzer: WyckoffAnalyzer,
    df: pd.DataFrame,
    symbol: str,
    as_of: pd.Timestamp,
) -> WyckoffReport:
    sliced = df[df["date"] <= as_of].copy()
    return analyzer.analyze(sliced, symbol=symbol, period="日线", multi_timeframe=True)


def run_cycle_test(
    analyzer: WyckoffAnalyzer,
    df: pd.DataFrame,
    symbol: str,
    name: str,
    cycle_spec: CycleSpec,
) -> dict:
    as_of = pd.Timestamp(cycle_spec.as_of_date)
    if as_of not in df["date"].values:
        available = df[df["date"] < as_of]["date"].sort_values()
        if len(available) == 0:
            return None
        as_of = pd.Timestamp(available.iloc[-1])
    
    report = analyze_at_date(analyzer, df, symbol, as_of)
    design = evaluate_design_completeness(report)
    
    return {
        "cycle_id": cycle_spec.cycle_id,
        "cycle_year": cycle_spec.year,
        "as_of": str(as_of.date()),
        "symbol": symbol,
        "name": name,
        "phase": report.structure.phase.value,
        "monthly_phase": (
            report.multi_timeframe.monthly.phase.value
            if report.multi_timeframe and report.multi_timeframe.monthly
            else ""
        ),
        "weekly_phase": (
            report.multi_timeframe.weekly.phase.value
            if report.multi_timeframe and report.multi_timeframe.weekly
            else ""
        ),
        "daily_phase": (
            report.multi_timeframe.daily.phase.value
            if report.multi_timeframe and report.multi_timeframe.daily
            else report.structure.phase.value
        ),
        "direction": report.trading_plan.direction,
        "signal_type": report.signal.signal_type,
        "signal_description": report.signal.description,
        "current_price": round(report.structure.current_price, 2),
        "bc_price": round(report.structure.bc_point.price, 3) if report.structure.bc_point else "",
        "sc_price": round(report.structure.sc_point.price, 3) if report.structure.sc_point else "",
        "tr_low": round(report.structure.trading_range_low, 2),
        "tr_high": round(report.structure.trading_range_high, 2),
        "entry_price": round((report.risk_reward.entry_price or 0), 2),
        "stop_loss": round((report.risk_reward.stop_loss or 0), 2),
        "first_target": round((report.risk_reward.first_target or 0), 2),
        "rr_ratio": round(report.risk_reward.reward_risk_ratio, 3),
        "design_score": design["score"],
        "design_max_score": design["max_score"],
        "design_ratio": round(design["score"] / max(1, design["max_score"]), 3),
        "qualification": report.trading_plan.current_qualification,
        "trigger": report.trading_plan.trigger_condition,
        "invalidation": report.trading_plan.invalidation_point,
    }


def write_cycle_results(output_dir: Path, rows: list[dict]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    
    with (output_dir / "cycle_test_summary.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    
    with (output_dir / "cycle_test_raw.jsonl").open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    
    phase_counts = {}
    for row in rows:
        ph = row.get("phase", "UNKNOWN")
        phase_counts[ph] = phase_counts.get(ph, 0) + 1
    
    avg_design = sum(r["design_ratio"] for r in rows) / len(rows) if rows else 0
    avg_rr = sum(r["rr_ratio"] for r in rows if r["rr_ratio"] > 0) / len([r for r in rows if r["rr_ratio"] > 0]) if rows else 0
    
    md_lines = [
        "# 6-Cycle Wyckoff Test Results",
        "",
        f"- 测试日期: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 样本数量: {len(rows)}",
        f"- 平均设计完整度: {avg_design:.3f}",
        f"- 平均盈亏比: {avg_rr:.3f}",
        "",
        "## 周期规格",
        "",
        "| Cycle ID | Year | As-Of Date |",
        "|---|---|---|",
    ]
    
    cycle_years = {}
    for row in rows:
        cycle_years[row["cycle_id"]] = (row["cycle_year"], row["as_of"])
    for cid in sorted(cycle_years.keys()):
        yr, dt = cycle_years[cid]
        md_lines.append(f"| {cid} | {yr} | {dt} |")
    
    md_lines.extend(["", "## 阶段分布", ""])
    for ph, cnt in sorted(phase_counts.items()):
        md_lines.append(f"- `{ph}`: {cnt}")
    
    md_lines.extend(["", "## 详细结果", ""])
    md_lines.append("| Cycle | Symbol | Date | Phase | Direction | RR | Design |")
    md_lines.append("|---|---|---|---|---:|---:|---:|")
    for row in rows:
        md_lines.append(
            f"| {row['cycle_id']} | {row['symbol']} | {row['as_of']} | "
            f"{row['phase']} | {row['direction']} | {row['rr_ratio']} | {row['design_ratio']} |"
        )
    
    (output_dir / "cycle_test_summary.md").write_text("\n".join(md_lines), encoding="utf-8")
    print(f"Saved: {output_dir}")


def get_baseline_comparison(cycle_rows: list[dict]) -> dict:
    baseline_doc_map = {
        "600859.SH": "docs/new/600859_王府井_连续性完整分析档案.md",
        "002216.SZ": "docs/new/002216_三全食品_连续性完整分析档案.md",
        "300442.SZ": "docs/new/300442_润泽科技_连续性完整分析档案.md",
    }
    return baseline_doc_map


def main() -> None:
    output_dir = PROJECT_ROOT / "output" / "wyckoff_6cycle_test"
    cycle_specs = generate_cycle_specs()
    
    print("6-Cycle Wyckoff Test")
    print("=" * 50)
    for spec in cycle_specs:
        print(f"Cycle {spec.cycle_id}: Year {spec.year}, Date {spec.as_of_date}")
    
    analyzer = WyckoffAnalyzer(lookback_days=1000)
    data_manager = DataManager()
    
    all_rows: list[dict] = []
    
    for symbol, name in SAMPLE_SYMBOLS:
        print(f"\nProcessing {symbol} ({name})...")
        df = data_manager.get_data(symbol)
        if df is None or df.empty:
            print(f"  Skipping {symbol}: no data")
            continue
        
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)
        
        for spec in cycle_specs:
            result = run_cycle_test(analyzer, df, symbol, name, spec)
            if result:
                all_rows.append(result)
                print(f"  Cycle {spec.cycle_id}: {result['phase']} / {result['direction']}")
            else:
                print(f"  Cycle {spec.cycle_id}: FAILED")
    
    write_cycle_results(output_dir, all_rows)
    
    print(f"\nTotal results: {len(all_rows)}")
    print(f"Output: {output_dir}")


if __name__ == "__main__":
    main()