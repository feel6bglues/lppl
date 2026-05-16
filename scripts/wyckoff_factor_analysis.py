#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
威科夫分析模块因子分析
- 分析影响收益的各种因子
- 输出详细因子分析结果
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Dict

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def load_effectiveness_data(csv_path: Path) -> pd.DataFrame:
    """加载有效性验证数据"""
    df = pd.read_csv(csv_path)
    return df


def analyze_factor(df: pd.DataFrame, factor_col: str, target_col: str = "future_return") -> Dict:
    """分析单个因子对收益的影响"""
    results = {}
    
    for factor_value in df[factor_col].unique():
        if pd.isna(factor_value):
            continue
            
        factor_df = df[df[factor_col] == factor_value]
        
        if len(factor_df) == 0:
            continue
        
        returns = factor_df[target_col]
        correct = factor_df["prediction_correct"]
        
        results[str(factor_value)] = {
            "样本数": int(len(factor_df)),
            "占比": round(len(factor_df) / len(df) * 100, 2),
            "平均收益": round(float(returns.mean()), 4),
            "收益中位数": round(float(returns.median()), 4),
            "收益标准差": round(float(returns.std()), 4),
            "最大收益": round(float(returns.max()), 4),
            "最大亏损": round(float(returns.min()), 4),
            "正收益占比": round(float((returns > 0).mean() * 100), 2),
            "负收益占比": round(float((returns < 0).mean() * 100), 2),
            "准确率": round(float(correct.mean() * 100), 2),
        }
    
    return results


def analyze_factor_by_window(df: pd.DataFrame, factor_col: str, target_col: str = "future_return") -> Dict:
    """按窗口分析因子对收益的影响"""
    results = {}
    
    for window in sorted(df["window"].unique()):
        window_df = df[df["window"] == window]
        window_results = {}
        
        for factor_value in window_df[factor_col].unique():
            if pd.isna(factor_value):
                continue
                
            factor_df = window_df[window_df[factor_col] == factor_value]
            
            if len(factor_df) == 0:
                continue
            
            returns = factor_df[target_col]
            correct = factor_df["prediction_correct"]
            
            window_results[str(factor_value)] = {
                "样本数": int(len(factor_df)),
                "占比": round(len(factor_df) / len(window_df) * 100, 2),
                "平均收益": round(float(returns.mean()), 4),
                "收益中位数": round(float(returns.median()), 4),
                "收益标准差": round(float(returns.std()), 4),
                "最大收益": round(float(returns.max()), 4),
                "最大亏损": round(float(returns.min()), 4),
                "正收益占比": round(float((returns > 0).mean() * 100), 2),
                "负收益占比": round(float((returns < 0).mean() * 100), 2),
                "准确率": round(float(correct.mean() * 100), 2),
            }
        
        results[int(window)] = window_results
    
    return results


def analyze_interaction_effects(df: pd.DataFrame) -> Dict:
    """分析因子交互效应"""
    results = {}
    
    # 阶段 × 置信度 交互效应
    phase_confidence = {}
    for phase in df["phase"].unique():
        if pd.isna(phase):
            continue
        phase_df = df[df["phase"] == phase]
        phase_confidence[str(phase)] = {}
        
        for conf in phase_df["confidence"].unique():
            if pd.isna(conf):
                continue
            conf_df = phase_df[phase_df["confidence"] == conf]
            
            if len(conf_df) == 0:
                continue
            
            returns = conf_df["future_return"]
            correct = conf_df["prediction_correct"]
            
            phase_confidence[str(phase)][str(conf)] = {
                "样本数": int(len(conf_df)),
                "平均收益": round(float(returns.mean()), 4),
                "准确率": round(float(correct.mean() * 100), 2),
            }
    
    results["阶段×置信度"] = phase_confidence
    
    # 阶段×窗口 交互效应
    phase_window = {}
    for phase in df["phase"].unique():
        if pd.isna(phase):
            continue
        phase_df = df[df["phase"] == phase]
        phase_window[str(phase)] = {}
        
        for window in sorted(phase_df["window"].unique()):
            window_df = phase_df[phase_df["window"] == window]
            
            if len(window_df) == 0:
                continue
            
            returns = window_df["future_return"]
            correct = window_df["prediction_correct"]
            
            phase_window[str(phase)][str(int(window))] = {
                "样本数": int(len(window_df)),
                "平均收益": round(float(returns.mean()), 4),
                "准确率": round(float(correct.mean() * 100), 2),
            }
    
    results["阶段×窗口"] = phase_window
    
    # 置信度×窗口 交互效应
    conf_window = {}
    for conf in df["confidence"].unique():
        if pd.isna(conf):
            continue
        conf_df = df[df["confidence"] == conf]
        conf_window[str(conf)] = {}
        
        for window in sorted(conf_df["window"].unique()):
            window_df = conf_df[conf_df["window"] == window]
            
            if len(window_df) == 0:
                continue
            
            returns = window_df["future_return"]
            correct = window_df["prediction_correct"]
            
            conf_window[str(conf)][str(int(window))] = {
                "样本数": int(len(window_df)),
                "平均收益": round(float(returns.mean()), 4),
                "准确率": round(float(correct.mean() * 100), 2),
            }
    
    results["置信度×窗口"] = conf_window
    
    return results


def analyze_time_factor(df: pd.DataFrame) -> Dict:
    """分析时间因子"""
    results = {}
    
    # 按年份分析
    df["year"] = pd.to_datetime(df["time_point"]).dt.year
    year_stats = {}
    
    for year in sorted(df["year"].unique()):
        year_df = df[df["year"] == year]
        
        returns = year_df["future_return"]
        correct = year_df["prediction_correct"]
        
        year_stats[str(int(year))] = {
            "样本数": int(len(year_df)),
            "平均收益": round(float(returns.mean()), 4),
            "收益标准差": round(float(returns.std()), 4),
            "正收益占比": round(float((returns > 0).mean() * 100), 2),
            "准确率": round(float(correct.mean() * 100), 2),
        }
    
    results["年份"] = year_stats
    
    return results


def write_factor_analysis_report(
    df: pd.DataFrame,
    phase_analysis: Dict,
    confidence_analysis: Dict,
    window_analysis: Dict,
    direction_analysis: Dict,
    interaction_analysis: Dict,
    time_analysis: Dict,
    output_dir: Path
):
    """输出因子分析报告"""
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # 保存JSON
    all_analysis = {
        "阶段因子": phase_analysis,
        "置信度因子": confidence_analysis,
        "窗口因子": window_analysis,
        "方向因子": direction_analysis,
        "交互效应": interaction_analysis,
        "时间因子": time_analysis,
    }
    
    with (output_dir / "factor_analysis.json").open("w", encoding="utf-8") as f:
        json.dump(all_analysis, f, ensure_ascii=False, indent=2)
    
    # 生成Markdown报告
    md_lines = [
        "# 威科夫分析模块因子分析报告",
        "",
        f"- 分析日期: {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 总样本数: {len(df)}",
        "",
        "## 一、单因子分析",
        "",
        "### 1.1 阶段因子",
        "",
        "| 阶段 | 样本数 | 占比 | 平均收益 | 收益中位数 | 正收益占比 | 准确率 |",
        "|------|--------|------|----------|------------|------------|--------|",
    ]
    
    for phase, stats in sorted(phase_analysis.items(), key=lambda x: -x[1]["平均收益"]):
        md_lines.append(
            f"| {phase} | {stats['样本数']} | {stats['占比']}% | "
            f"{stats['平均收益']:.2f}% | {stats['收益中位数']:.2f}% | "
            f"{stats['正收益占比']}% | {stats['准确率']}% |"
        )
    
    md_lines.extend([
        "",
        "### 1.2 置信度因子",
        "",
        "| 置信度 | 样本数 | 占比 | 平均收益 | 收益中位数 | 正收益占比 | 准确率 |",
        "|--------|--------|------|----------|------------|------------|--------|",
    ])
    
    for conf, stats in sorted(confidence_analysis.items(), key=lambda x: -x[1]["平均收益"]):
        md_lines.append(
            f"| {conf} | {stats['样本数']} | {stats['占比']}% | "
            f"{stats['平均收益']:.2f}% | {stats['收益中位数']:.2f}% | "
            f"{stats['正收益占比']}% | {stats['准确率']}% |"
        )
    
    md_lines.extend([
        "",
        "### 1.3 窗口因子",
        "",
        "| 窗口 | 样本数 | 占比 | 平均收益 | 收益中位数 | 正收益占比 | 准确率 |",
        "|------|--------|------|----------|------------|------------|--------|",
    ])
    
    for window, stats in sorted(window_analysis.items(), key=lambda x: -x[1]["平均收益"]):
        md_lines.append(
            f"| {window}天 | {stats['样本数']} | {stats['占比']}% | "
            f"{stats['平均收益']:.2f}% | {stats['收益中位数']:.2f}% | "
            f"{stats['正收益占比']}% | {stats['准确率']}% |"
        )
    
    md_lines.extend([
        "",
        "### 1.4 方向因子",
        "",
        "| 方向 | 样本数 | 占比 | 平均收益 | 收益中位数 | 正收益占比 | 准确率 |",
        "|------|--------|------|----------|------------|------------|--------|",
    ])
    
    for direction, stats in sorted(direction_analysis.items(), key=lambda x: -x[1]["平均收益"]):
        md_lines.append(
            f"| {direction} | {stats['样本数']} | {stats['占比']}% | "
            f"{stats['平均收益']:.2f}% | {stats['收益中位数']:.2f}% | "
            f"{stats['正收益占比']}% | {stats['准确率']}% |"
        )
    
    # 交互效应分析
    md_lines.extend([
        "",
        "## 二、因子交互效应分析",
        "",
        "### 2.1 阶段×置信度 交互效应",
        "",
    ])
    
    for phase, conf_stats in interaction_analysis["阶段×置信度"].items():
        md_lines.extend([
            f"#### {phase}",
            "",
            "| 置信度 | 样本数 | 平均收益 | 准确率 |",
            "|--------|--------|----------|--------|",
        ])
        
        for conf, stats in sorted(conf_stats.items(), key=lambda x: -x[1]["平均收益"]):
            md_lines.append(
                f"| {conf} | {stats['样本数']} | {stats['平均收益']:.2f}% | {stats['准确率']}% |"
            )
        md_lines.append("")
    
    md_lines.extend([
        "",
        "### 2.2 阶段×窗口 交互效应",
        "",
    ])
    
    for phase, window_stats in interaction_analysis["阶段×窗口"].items():
        md_lines.extend([
            f"#### {phase}",
            "",
            "| 窗口 | 样本数 | 平均收益 | 准确率 |",
            "|------|--------|----------|--------|",
        ])
        
        for window, stats in sorted(window_stats.items(), key=lambda x: -x[1]["平均收益"]):
            md_lines.append(
                f"| {window}天 | {stats['样本数']} | {stats['平均收益']:.2f}% | {stats['准确率']}% |"
            )
        md_lines.append("")
    
    # 时间因子分析
    md_lines.extend([
        "",
        "## 三、时间因子分析",
        "",
        "### 3.1 年份因子",
        "",
        "| 年份 | 样本数 | 平均收益 | 收益标准差 | 正收益占比 | 准确率 |",
        "|------|--------|----------|------------|------------|--------|",
    ])
    
    for year, stats in sorted(time_analysis["年份"].items()):
        md_lines.append(
            f"| {year} | {stats['样本数']} | {stats['平均收益']:.2f}% | "
            f"{stats['收益标准差']:.2f}% | {stats['正收益占比']}% | {stats['准确率']}% |"
        )
    
    # 结论
    md_lines.extend([
        "",
        "## 四、因子分析结论",
        "",
        "### 4.1 关键发现",
        "",
    ])
    
    # 找出最佳和最差因子
    best_phase = max(phase_analysis.items(), key=lambda x: x[1]["平均收益"])
    worst_phase = min(phase_analysis.items(), key=lambda x: x[1]["平均收益"])
    
    best_conf = max(confidence_analysis.items(), key=lambda x: x[1]["平均收益"])
    worst_conf = min(confidence_analysis.items(), key=lambda x: x[1]["平均收益"])
    
    best_window = max(window_analysis.items(), key=lambda x: x[1]["平均收益"])
    worst_window = min(window_analysis.items(), key=lambda x: x[1]["平均收益"])
    
    best_direction = max(direction_analysis.items(), key=lambda x: x[1]["平均收益"])
    worst_direction = min(direction_analysis.items(), key=lambda x: x[1]["平均收益"])
    
    md_lines.extend([
        "#### 阶段因子",
        f"- **最佳阶段**: {best_phase[0]} (平均收益: {best_phase[1]['平均收益']:.2f}%)",
        f"- **最差阶段**: {worst_phase[0]} (平均收益: {worst_phase[1]['平均收益']:.2f}%)",
        "",
        "#### 置信度因子",
        f"- **最佳置信度**: {best_conf[0]} (平均收益: {best_conf[1]['平均收益']:.2f}%)",
        f"- **最差置信度**: {worst_conf[0]} (平均收益: {worst_conf[1]['平均收益']:.2f}%)",
        "",
        "#### 窗口因子",
        f"- **最佳窗口**: {best_window[0]}天 (平均收益: {best_window[1]['平均收益']:.2f}%)",
        f"- **最差窗口**: {worst_window[0]}天 (平均收益: {worst_window[1]['平均收益']:.2f}%)",
        "",
        "#### 方向因子",
        f"- **最佳方向**: {best_direction[0]} (平均收益: {best_direction[1]['平均收益']:.2f}%)",
        f"- **最差方向**: {worst_direction[0]} (平均收益: {worst_direction[1]['平均收益']:.2f}%)",
        "",
        "### 4.2 交易策略建议",
        "",
        "基于因子分析结果，建议以下交易策略：",
        "",
        "1. **阶段选择**",
        f"   - 优先选择 {best_phase[0]} 阶段的股票",
        f"   - 避免 {worst_phase[0]} 阶段的股票",
        "",
        "2. **置信度筛选**",
        f"   - 优先选择 {best_conf[0]} 置信度的信号",
        f"   - 避免 {worst_conf[0]} 置信度的信号",
        "",
        "3. **窗口选择**",
        f"   - 使用 {best_window[0]}天 回看窗口",
        f"   - 避免 {worst_window[0]}天 回看窗口",
        "",
        "4. **方向选择**",
        f"   - 优先选择 {best_direction[0]} 方向的信号",
        f"   - 避免 {worst_direction[0]} 方向的信号",
    ])
    
    (output_dir / "factor_analysis_report.md").write_text("\n".join(md_lines), encoding="utf-8")
    
    print("\n输出文件:")
    print(f"  - {output_dir / 'factor_analysis.json'}")
    print(f"  - {output_dir / 'factor_analysis_report.md'}")


def main():
    # 加载数据
    data_path = PROJECT_ROOT / "output" / "wyckoff_effectiveness" / "effectiveness_raw_results.csv"
    output_dir = PROJECT_ROOT / "output" / "wyckoff_factor_analysis"
    
    print("=" * 60)
    print("威科夫分析模块因子分析")
    print("=" * 60)
    
    print("\n1. 加载数据...")
    df = load_effectiveness_data(data_path)
    print(f"   加载了 {len(df)} 条记录")
    
    print("\n2. 分析因子...")
    
    # 单因子分析
    print("   - 阶段因子分析...")
    phase_analysis = analyze_factor(df, "phase")
    
    print("   - 置信度因子分析...")
    confidence_analysis = analyze_factor(df, "confidence")
    
    print("   - 窗口因子分析...")
    window_analysis = analyze_factor(df, "window")
    
    print("   - 方向因子分析...")
    direction_analysis = analyze_factor(df, "direction")
    
    # 交互效应分析
    print("   - 交互效应分析...")
    interaction_analysis = analyze_interaction_effects(df)
    
    # 时间因子分析
    print("   - 时间因子分析...")
    time_analysis = analyze_time_factor(df)
    
    print("\n3. 输出结果...")
    write_factor_analysis_report(
        df,
        phase_analysis,
        confidence_analysis,
        window_analysis,
        direction_analysis,
        interaction_analysis,
        time_analysis,
        output_dir
    )
    
    print("\n" + "=" * 60)
    print("因子分析完成")
    print("=" * 60)


if __name__ == "__main__":
    main()
