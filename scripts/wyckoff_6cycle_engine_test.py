#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
6组完整周期测试 - 使用重构后的 WyckoffEngine
- 抽取 stock_list.csv 内 100 个股票
- 使用 2012-2025 随机日期运行 6 组完整周期测试
- 采用 1000 天日线和合并周线月线
- 对比分析结果和随后 120 个交易日的走势进行拟合
"""

from __future__ import annotations

import csv
import json
import random
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
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


def load_stock_symbols(csv_path: Path, limit: int = 100) -> List[Dict[str, str]]:
    """从 stock_list.csv 加载股票代码"""
    symbols = []
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            code = str(row.get("code", "")).strip()
            market = str(row.get("market", "")).strip().upper()
            name = str(row.get("name", "")).replace("\x00", "").strip()
            
            if not (code.isdigit() and len(code) == 6 and market in {"SH", "SZ"}):
                continue
            
            # 只要主板和中小板
            if code.startswith(("600", "601", "603", "605", "000", "001", "002", "003")):
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
    """生成 6 组随机年份和日期的测试规格"""
    random.seed(seed)
    specs = []
    
    # 选择 6 个不同的年份
    years = sorted(random.sample(range(2012, 2026), 6))
    
    for idx, yr in enumerate(years):
        # 随机选择月份和日期（避免年末）
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
    
    if len(future_data) < days * 0.8:  # 至少 80% 的数据
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
    
    # 检查数据是否足够
    available_data = df[df["date"] <= as_of]
    if len(available_data) < 100:
        return None
    
    # 截取到指定日期的数据
    analysis_df = available_data.copy()
    
    # 执行分析
    report = engine.analyze(analysis_df, symbol=symbol, period="日线", multi_timeframe=True)
    
    # 计算未来收益
    future_return = calculate_future_return(df, cycle_spec.as_of_date, days=120)
    
    if future_return is None:
        return None
    
    # 提取分析结果
    result = {
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
        # 未来收益
        "future_120d_return": future_return["return_pct"],
        "future_120d_max_gain": future_return["max_gain_pct"],
        "future_120d_max_drawdown": future_return["max_drawdown_pct"],
        "future_entry_price": future_return["entry_price"],
        "future_close": future_return["future_close"],
    }
    
    return result


def run_6cycle_test(
    symbols: List[Dict[str, str]],
    cycle_specs: List[CycleSpec],
    output_dir: Path,
    lookback_days: int = 1000,
) -> List[Dict]:
    """运行 6 组完整周期测试"""
    engine = WyckoffEngine(lookback_days=lookback_days)
    data_manager = DataManager()
    
    all_results = []
    total_tests = len(symbols) * len(cycle_specs)
    completed = 0
    failed = 0
    
    print(f"开始测试: {len(symbols)} 只股票 × {len(cycle_specs)} 个周期 = {total_tests} 次分析")
    print("=" * 60)
    
    for symbol_info in symbols:
        symbol = symbol_info["symbol"]
        name = symbol_info["name"]
        
        # 加载数据
        df = data_manager.get_data(symbol)
        if df is None or df.empty:
            print(f"  跳过 {symbol}: 无数据")
            failed += len(cycle_specs)
            continue
        
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)
        
        for spec in cycle_specs:
            result = analyze_single_cycle(engine, df, symbol, name, spec)
            if result:
                all_results.append(result)
                completed += 1
            else:
                failed += 1
        
        # 进度显示
        if completed % 100 == 0 and completed > 0:
            print(f"  已完成 {completed}/{total_tests} 次分析")
    
    print(f"\n测试完成: 成功 {completed}, 失败 {failed}")
    return all_results


def analyze_results(results: List[Dict]) -> Dict:
    """分析测试结果"""
    if not results:
        return {}
    
    df = pd.DataFrame(results)
    
    # 按阶段分组统计
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
    
    # 按方向分组统计
    direction_stats = {}
    for direction in df["direction"].unique():
        dir_df = df[df["direction"] == direction]
        direction_stats[direction] = {
            "count": len(dir_df),
            "avg_return": round(dir_df["future_120d_return"].mean(), 2),
            "win_rate": round(len(dir_df[dir_df["future_120d_return"] > 0]) / len(dir_df) * 100, 1),
        }
    
    # 按置信度分组统计
    confidence_stats = {}
    for conf in df["confidence"].unique():
        conf_df = df[df["confidence"] == conf]
        confidence_stats[conf] = {
            "count": len(conf_df),
            "avg_return": round(conf_df["future_120d_return"].mean(), 2),
            "win_rate": round(len(conf_df[conf_df["future_120d_return"] > 0]) / len(conf_df) * 100, 1),
        }
    
    # 按周期分组统计
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
    
    # 信号准确性分析
    signal_accuracy = {}
    for signal in df["signal_type"].unique():
        sig_df = df[df["signal_type"] == signal]
        signal_accuracy[signal] = {
            "count": len(sig_df),
            "avg_return": round(sig_df["future_120d_return"].mean(), 2),
            "win_rate": round(len(sig_df[sig_df["future_120d_return"] > 0]) / len(sig_df) * 100, 1),
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
    }


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


def write_outputs(output_dir: Path, results: List[Dict], analysis: Dict) -> None:
    """输出结果到文件"""
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # 保存原始数据
    with (output_dir / "cycle6_raw_results.jsonl").open("w", encoding="utf-8") as f:
        for row in results:
            f.write(json.dumps(convert_keys_to_str(row), ensure_ascii=False) + "\n")
    
    # 保存 CSV
    if results:
        df = pd.DataFrame(results)
        df.to_csv(output_dir / "cycle6_results.csv", index=False, encoding="utf-8-sig")
    
    # 保存分析报告
    with (output_dir / "cycle6_analysis.json").open("w", encoding="utf-8") as f:
        json.dump(convert_keys_to_str(analysis), f, ensure_ascii=False, indent=2)
    
    # 生成 Markdown 报告
    md_lines = [
        "# 6-Cycle Wyckoff Engine Test Report",
        "",
        f"- 测试日期: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 总样本数: {analysis.get('total_samples', 0)}",
        f"- 整体平均收益: {analysis.get('overall_avg_return', 0):.2f}%",
        f"- 整体胜率: {analysis.get('overall_win_rate', 0):.1f}%",
        "",
        "## 阶段分布与未来收益",
        "",
        "| 阶段 | 样本数 | 平均收益 | 中位收益 | 胜率 | 平均最大涨幅 | 平均最大回撤 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    
    for phase, stats in analysis.get("phase_stats", {}).items():
        md_lines.append(
            f"| {phase} | {stats['count']} | {stats['avg_return']:.2f}% | "
            f"{stats['median_return']:.2f}% | {stats['win_rate']:.1f}% | "
            f"{stats['avg_max_gain']:.2f}% | {stats['avg_max_drawdown']:.2f}% |"
        )
    
    md_lines.extend(["", "## 方向分布与未来收益", ""])
    md_lines.append("| 方向 | 样本数 | 平均收益 | 胜率 |")
    md_lines.append("|---|---:|---:|---:|")
    for direction, stats in analysis.get("direction_stats", {}).items():
        md_lines.append(f"| {direction} | {stats['count']} | {stats['avg_return']:.2f}% | {stats['win_rate']:.1f}% |")
    
    md_lines.extend(["", "## 置信度分布与未来收益", ""])
    md_lines.append("| 置信度 | 样本数 | 平均收益 | 胜率 |")
    md_lines.append("|---|---:|---:|---:|")
    for conf, stats in analysis.get("confidence_stats", {}).items():
        md_lines.append(f"| {conf} | {stats['count']} | {stats['avg_return']:.2f}% | {stats['win_rate']:.1f}% |")
    
    md_lines.extend(["", "## 各周期测试结果", ""])
    md_lines.append("| 周期 | 年份 | 日期 | 样本数 | 平均收益 | 胜率 |")
    md_lines.append("|---|---|---|---:|---:|---:|")
    for cycle_id, stats in analysis.get("cycle_stats", {}).items():
        md_lines.append(
            f"| {cycle_id} | {stats['year']} | {stats['as_of']} | "
            f"{stats['count']} | {stats['avg_return']:.2f}% | {stats['win_rate']:.1f}% |"
        )
    
    md_lines.extend(["", "## 信号类型准确性", ""])
    md_lines.append("| 信号类型 | 样本数 | 平均收益 | 胜率 |")
    md_lines.append("|---|---:|---:|---:|")
    for signal, stats in analysis.get("signal_accuracy", {}).items():
        md_lines.append(f"| {signal} | {stats['count']} | {stats['avg_return']:.2f}% | {stats['win_rate']:.1f}% |")
    
    # 添加重构效果评估
    md_lines.extend(["", "## 重构效果评估", ""])
    
    # 检查关键指标
    phase_stats = analysis.get("phase_stats", {})
    markdown_stats = phase_stats.get("markdown", {})
    accumulation_stats = phase_stats.get("accumulation", {})
    markup_stats = phase_stats.get("markup", {})
    
    md_lines.append("### 阶段判定准确性")
    if markdown_stats:
        md_lines.append(f"- Markdown阶段: {markdown_stats.get('count', 0)}个样本，平均收益{markdown_stats.get('avg_return', 0):.2f}%，胜率{markdown_stats.get('win_rate', 0):.1f}%")
        if markdown_stats.get('avg_return', 0) < 0:
            md_lines.append("  - ✅ 正确：Markdown阶段平均收益为负")
        else:
            md_lines.append("  - ⚠️ 需关注：Markdown阶段平均收益为正")
    
    if accumulation_stats:
        md_lines.append(f"- Accumulation阶段: {accumulation_stats.get('count', 0)}个样本，平均收益{accumulation_stats.get('avg_return', 0):.2f}%，胜率{accumulation_stats.get('win_rate', 0):.1f}%")
        if accumulation_stats.get('avg_return', 0) > 0:
            md_lines.append("  - ✅ 正确：Accumulation阶段平均收益为正")
        else:
            md_lines.append("  - ⚠️ 需关注：Accumulation阶段平均收益为负")
    
    if markup_stats:
        md_lines.append(f"- Markup阶段: {markup_stats.get('count', 0)}个样本，平均收益{markup_stats.get('avg_return', 0):.2f}%，胜率{markup_stats.get('win_rate', 0):.1f}%")
        if markup_stats.get('avg_return', 0) > 0:
            md_lines.append("  - ✅ 正确：Markup阶段平均收益为正")
        else:
            md_lines.append("  - ⚠️ 需关注：Markup阶段平均收益为负")
    
    (output_dir / "cycle6_report.md").write_text("\n".join(md_lines), encoding="utf-8")
    
    print(f"\n输出文件:")
    print(f"  - {output_dir / 'cycle6_raw_results.jsonl'}")
    print(f"  - {output_dir / 'cycle6_results.csv'}")
    print(f"  - {output_dir / 'cycle6_analysis.json'}")
    print(f"  - {output_dir / 'cycle6_report.md'}")


def main() -> None:
    """主函数"""
    output_dir = PROJECT_ROOT / "output" / "wyckoff_6cycle_all_stocks_test"
    csv_path = PROJECT_ROOT / "data" / "stock_list.csv"
    
    print("=" * 60)
    print("Wyckoff Engine v3.0 - 6 Cycle Test (ALL Stocks, 1200 Days)")
    print("=" * 60)
    
    # 加载所有股票列表
    print("\n1. 加载股票列表...")
    symbols = load_stock_symbols(csv_path, limit=99999)  # 加载所有股票
    print(f"   加载了 {len(symbols)} 只股票")
    
    # 生成测试周期
    print("\n2. 生成测试周期...")
    cycle_specs = generate_cycle_specs()
    for spec in cycle_specs:
        print(f"   Cycle {spec.cycle_id}: Year {spec.year}, Date {spec.as_of_date}")
    
    # 运行测试
    print("\n3. 运行测试...")
    results = run_6cycle_test(symbols, cycle_specs, output_dir, lookback_days=1200)
    
    # 分析结果
    print("\n4. 分析结果...")
    analysis = analyze_results(results)
    
    # 输出结果
    print("\n5. 输出结果...")
    write_outputs(output_dir, results, analysis)
    
    # 打印摘要
    print("\n" + "=" * 60)
    print("测试摘要:")
    print(f"  总样本数: {analysis.get('total_samples', 0)}")
    print(f"  整体平均收益: {analysis.get('overall_avg_return', 0):.2f}%")
    print(f"  整体胜率: {analysis.get('overall_win_rate', 0):.1f}%")
    print("=" * 60)


if __name__ == "__main__":
    main()