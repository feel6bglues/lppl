#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
威科夫分析模块有效性验证
- 使用通达信日线数据合成周线月线
- 5个回看窗口：200/400/600/800/1200天
- 2012-2025年随机8轮时点采样
- 对比120天后真实走势
- 分析模块有效性和可靠性
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.data.manager import DataManager
from src.wyckoff.engine import WyckoffEngine
from src.wyckoff.models import WyckoffPhase

# 创建全局引擎实例用于数据合成
_engine = WyckoffEngine()


def synthesize_weekly(daily_df: pd.DataFrame) -> pd.DataFrame:
    """从日线合成周线数据（使用系统原生方法）"""
    return _engine._resample_ohlcv(daily_df, "W-FRI")


def synthesize_monthly(daily_df: pd.DataFrame) -> pd.DataFrame:
    """从日线合成月线数据（使用系统原生方法）"""
    return _engine._resample_ohlcv(daily_df, "ME")


# ============================================================================
# 数据加载函数
# ============================================================================

def load_stock_symbols(csv_path: Path, limit: int = 99999) -> List[Dict[str, str]]:
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


def generate_random_time_points(
    start_year: int = 2012,
    end_year: int = 2025,
    n_points: int = 8,
    seed: int = 42
) -> List[str]:
    """生成随机时点（每年随机选取）"""
    random.seed(seed)
    time_points = []
    
    for year in range(start_year, end_year + 1):
        # 每年随机选择一个交易日（跳过节假日）
        month = random.randint(1, 12)
        day = random.randint(1, 28)  # 避免月末问题
        time_points.append(f"{year}-{month:02d}-{day:02d}")
    
    # 如果需要更多时点，从已有年份中额外随机选取
    while len(time_points) < n_points:
        year = random.randint(start_year, end_year)
        month = random.randint(1, 12)
        day = random.randint(1, 28)
        tp = f"{year}-{month:02d}-{day:02d}"
        if tp not in time_points:
            time_points.append(tp)
    
    return sorted(time_points[:n_points])


# ============================================================================
# 分析函数
# ============================================================================

def analyze_single_stock(args) -> List[Dict]:
    """分析单只股票（多进程 worker）"""
    symbol_info, time_points, windows = args
    symbol = symbol_info["symbol"]
    name = symbol_info["name"]
    
    results = []
    
    try:
        dm = DataManager()
        daily_df = dm.get_data(symbol)
        
        if daily_df is None or daily_df.empty:
            return results
        
        daily_df["date"] = pd.to_datetime(daily_df["date"])
        daily_df = daily_df.sort_values("date").reset_index(drop=True)
        
        # 合成周线月线
        weekly_df = synthesize_weekly(daily_df)
        monthly_df = synthesize_monthly(daily_df)
        
        # 对每个时点和窗口进行分析
        for time_point in time_points:
            tp_date = pd.Timestamp(time_point)
            
            # 获取截至该时点的数据
            daily_available = daily_df[daily_df["date"] <= tp_date]
            weekly_available = weekly_df[weekly_df["date"] <= tp_date]
            monthly_available = monthly_df[monthly_df["date"] <= tp_date]
            
            if len(daily_available) < 100:
                continue
            
            # 计算120天后的真实走势
            future_date = tp_date + pd.Timedelta(days=120)
            future_data = daily_df[daily_df["date"] > tp_date].head(120)
            
            if len(future_data) < 20:
                continue
            
            current_price = float(daily_available["close"].iloc[-1])
            future_price = float(future_data["close"].iloc[-1])
            future_return = (future_price - current_price) / current_price
            future_max_return = float(future_data["close"].max()) / current_price - 1
            future_min_return = float(future_data["close"].min()) / current_price - 1
            
            # 判断真实趋势
            if future_return > 0.05:
                actual_trend = "上涨"
            elif future_return < -0.05:
                actual_trend = "下跌"
            else:
                actual_trend = "震荡"
            
            # 对每个窗口进行威科夫分析
            for window in windows:
                if len(daily_available) < window:
                    continue
                
                engine = WyckoffEngine(lookback_days=window)
                
                try:
                    report = engine.analyze(
                        daily_available,
                        symbol=symbol,
                        period="日线",
                        multi_timeframe=True
                    )
                    
                    phase = report.structure.phase.value
                    direction = report.trading_plan.direction
                    confidence = report.trading_plan.confidence.value
                    
                    # 判断预测是否正确
                    if direction in ("做多", "轻仓试探") and future_return > 0:
                        prediction_correct = True
                    elif direction in ("空仓观望", "持有观察") and future_return < 0:
                        prediction_correct = True
                    elif direction == "观察等待" and abs(future_return) < 0.1:
                        prediction_correct = True
                    else:
                        prediction_correct = False
                    
                    results.append({
                        "symbol": symbol,
                        "name": name,
                        "time_point": time_point,
                        "window": window,
                        "phase": phase,
                        "direction": direction,
                        "confidence": confidence,
                        "current_price": round(current_price, 2),
                        "future_return": round(future_return * 100, 2),
                        "future_max_return": round(future_max_return * 100, 2),
                        "future_min_return": round(future_min_return * 100, 2),
                        "actual_trend": actual_trend,
                        "prediction_correct": prediction_correct,
                        "rr_ratio": round(report.risk_reward.reward_risk_ratio, 3),
                    })
                    
                except Exception as e:
                    # 分析失败，跳过
                    continue
        
    except Exception as e:
        pass
    
    return results


# ============================================================================
# 统计分析函数
# ============================================================================

def analyze_effectiveness(results: List[Dict]) -> Dict:
    """分析模块有效性"""
    if not results:
        return {}
    
    df = pd.DataFrame(results)
    analysis = {}
    
    # 按窗口分组分析
    for window in df["window"].unique():
        window_int = int(window)  # 转换为普通int
        window_df = df[df["window"] == window]
        
        # 总体准确率
        total = len(window_df)
        correct = window_df["prediction_correct"].sum()
        accuracy = correct / total * 100 if total > 0 else 0
        
        # 按阶段分组
        phase_stats = {}
        for phase in window_df["phase"].unique():
            phase_df = window_df[window_df["phase"] == phase]
            phase_correct = phase_df["prediction_correct"].sum()
            phase_stats[phase] = {
                "count": int(len(phase_df)),
                "correct": int(phase_correct),
                "accuracy": round(float(phase_correct) / len(phase_df) * 100, 1) if len(phase_df) > 0 else 0,
                "avg_future_return": round(float(phase_df["future_return"].mean()), 2),
            }
        
        # 按方向分组
        direction_stats = {}
        for direction in window_df["direction"].unique():
            dir_df = window_df[window_df["direction"] == direction]
            dir_correct = dir_df["prediction_correct"].sum()
            direction_stats[direction] = {
                "count": int(len(dir_df)),
                "correct": int(dir_correct),
                "accuracy": round(float(dir_correct) / len(dir_df) * 100, 1) if len(dir_df) > 0 else 0,
                "avg_future_return": round(float(dir_df["future_return"].mean()), 2),
            }
        
        # 按置信度分组
        confidence_stats = {}
        for conf in window_df["confidence"].unique():
            conf_df = window_df[window_df["confidence"] == conf]
            conf_correct = conf_df["prediction_correct"].sum()
            confidence_stats[conf] = {
                "count": int(len(conf_df)),
                "correct": int(conf_correct),
                "accuracy": round(float(conf_correct) / len(conf_df) * 100, 1) if len(conf_df) > 0 else 0,
                "avg_future_return": round(float(conf_df["future_return"].mean()), 2),
            }
        
        # 做多信号的收益分析
        bullish_df = window_df[window_df["direction"].isin(["做多", "轻仓试探"])]
        bullish_return = float(bullish_df["future_return"].mean()) if len(bullish_df) > 0 else 0
        
        # 空仓信号的避险效果
        bearish_df = window_df[window_df["direction"].isin(["空仓观望", "持有观察"])]
        bearish_return = float(bearish_df["future_return"].mean()) if len(bearish_df) > 0 else 0
        
        analysis[window_int] = {
            "total_samples": int(total),
            "overall_accuracy": round(float(accuracy), 1),
            "phase_stats": phase_stats,
            "direction_stats": direction_stats,
            "confidence_stats": confidence_stats,
            "bullish_avg_return": round(bullish_return, 2),
            "bearish_avg_return": round(bearish_return, 2),
            "signal_quality": round(bullish_return - bearish_return, 2),
        }
    
    return analysis


# ============================================================================
# 输出函数
# ============================================================================

def write_outputs(all_results: List[Dict], analysis: Dict, output_dir: Path):
    """输出结果"""
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # 保存原始结果
    df = pd.DataFrame(all_results)
    df.to_csv(output_dir / "effectiveness_raw_results.csv", index=False, encoding="utf-8-sig")
    
    # 保存分析结果
    with (output_dir / "effectiveness_analysis.json").open("w", encoding="utf-8") as f:
        json.dump(analysis, f, ensure_ascii=False, indent=2)
    
    # 生成Markdown报告
    md_lines = [
        "# 威科夫分析模块有效性验证报告",
        "",
        f"- 测试日期: {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 总样本数: {len(all_results)}",
        f"- 测试时点: 2012-2025年随机20轮",
        f"- 回看窗口: 200/400/600/800/1200天",
        f"- 验证周期: 120天后真实走势",
        "",
        "## 窗口对比总览",
        "",
        "| 窗口 | 样本数 | 总体准确率 | 做多平均收益 | 空仓平均收益 | 信号质量 |",
        "|---:|---:|---:|---:|---:|---:|",
    ]
    
    for window in sorted(analysis.keys()):
        stats = analysis[window]
        md_lines.append(
            f"| {window}天 | {stats['total_samples']} | "
            f"{stats['overall_accuracy']}% | "
            f"{stats['bullish_avg_return']}% | "
            f"{stats['bearish_avg_return']}% | "
            f"{stats['signal_quality']}% |"
        )
    
    # 阶段分析
    md_lines.extend(["", "## 阶段分析（按窗口）", ""])
    
    for window in sorted(analysis.keys()):
        stats = analysis[window]
        md_lines.extend([f"### 窗口 {window}天", ""])
        md_lines.append("| 阶段 | 样本数 | 准确率 | 平均收益 |")
        md_lines.append("|---:|---:|---:|---:|")
        
        for phase, phase_stats in stats["phase_stats"].items():
            md_lines.append(
                f"| {phase} | {phase_stats['count']} | "
                f"{phase_stats['accuracy']}% | "
                f"{phase_stats['avg_future_return']}% |"
            )
        
        md_lines.append("")
    
    # 置信度分析
    md_lines.extend(["", "## 置信度分析（按窗口）", ""])
    
    for window in sorted(analysis.keys()):
        stats = analysis[window]
        md_lines.extend([f"### 窗口 {window}天", ""])
        md_lines.append("| 置信度 | 样本数 | 准确率 | 平均收益 |")
        md_lines.append("|---:|---:|---:|---:|")
        
        for conf, conf_stats in stats["confidence_stats"].items():
            md_lines.append(
                f"| {conf} | {conf_stats['count']} | "
                f"{conf_stats['accuracy']}% | "
                f"{conf_stats['avg_future_return']}% |"
            )
        
        md_lines.append("")
    
    # 结论
    md_lines.extend([
        "## 有效性结论",
        "",
        "### 信号质量评估",
        "",
    ])
    
    # 找出最佳窗口
    best_window = max(analysis.keys(), key=lambda w: analysis[w]["signal_quality"])
    best_accuracy_window = max(analysis.keys(), key=lambda w: analysis[w]["overall_accuracy"])
    
    md_lines.extend([
        f"- **最佳信号质量窗口**: {best_window}天 (信号质量: {analysis[best_window]['signal_quality']}%)",
        f"- **最高准确率窗口**: {best_accuracy_window}天 (准确率: {analysis[best_accuracy_window]['overall_accuracy']}%)",
        "",
        "### 建议",
        "",
    ])
    
    if analysis[best_window]["signal_quality"] > 5:
        md_lines.append(f"- 推荐使用 {best_window}天 回看窗口进行威科夫分析")
    else:
        md_lines.append("- 所有窗口的信号质量均较低，建议结合其他指标使用")
    
    (output_dir / "effectiveness_report.md").write_text("\n".join(md_lines), encoding="utf-8")
    
    print(f"\n输出文件:")
    print(f"  - {output_dir / 'effectiveness_raw_results.csv'}")
    print(f"  - {output_dir / 'effectiveness_analysis.json'}")
    print(f"  - {output_dir / 'effectiveness_report.md'}")


# ============================================================================
# 主函数
# ============================================================================

def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description="威科夫分析模块有效性验证"
    )
    parser.add_argument(
        "--workers", "-w",
        type=int,
        default=1,
        help="并行进程数（默认: 1）"
    )
    parser.add_argument(
        "--limit", "-l",
        type=int,
        default=99999,
        help="股票数量限制（默认: 99999，全部）"
    )
    parser.add_argument(
        "--output", "-o",
        type=str,
        default=None,
        help="输出目录"
    )
    parser.add_argument(
        "--windows",
        type=str,
        default="200,400,600,800,1200",
        help="窗口列表（默认: 200,400,600,800,1200）"
    )
    parser.add_argument(
        "--time-points", "-t",
        type=int,
        default=8,
        help="随机时点数量（默认: 8）"
    )
    parser.add_argument(
        "--seed", "-s",
        type=int,
        default=42,
        help="随机种子（默认: 42）"
    )
    parser.add_argument(
        "--batch-size", "-b",
        type=int,
        default=100,
        help="批次大小（默认: 100）"
    )
    parser.add_argument(
        "--resume", "-r",
        action="store_true",
        help="从断点继续"
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="清除断点重新开始"
    )
    return parser.parse_args()


def load_checkpoint(checkpoint_file: Path) -> Dict:
    """加载断点文件"""
    if checkpoint_file.exists():
        with checkpoint_file.open("r", encoding="utf-8") as f:
            return json.load(f)
    return {"completed_symbols": [], "total_results": 0}


def save_checkpoint(checkpoint_file: Path, checkpoint: Dict):
    """保存断点文件"""
    with checkpoint_file.open("w", encoding="utf-8") as f:
        json.dump(checkpoint, f, ensure_ascii=False, indent=2)


def append_results_to_file(results_file: Path, results: List[Dict]):
    """增量追加结果到文件"""
    results_file.parent.mkdir(parents=True, exist_ok=True)
    with results_file.open("a", encoding="utf-8") as f:
        for row in results:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def load_existing_results(results_file: Path) -> List[Dict]:
    """加载已有的结果文件"""
    results = []
    if results_file.exists():
        with results_file.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    results.append(json.loads(line))
    return results


def main():
    args = parse_args()
    
    output_dir = Path(args.output) if args.output else PROJECT_ROOT / "output" / "wyckoff_effectiveness"
    csv_path = PROJECT_ROOT / "data" / "stock_list.csv"
    windows = [int(w) for w in args.windows.split(",")]
    max_workers = args.workers
    batch_size = args.batch_size
    
    # 断点文件路径
    checkpoint_file = output_dir / "checkpoint.json"
    results_file = output_dir / "effectiveness_raw_results.jsonl"
    
    # 清除断点
    if args.reset:
        if checkpoint_file.exists():
            checkpoint_file.unlink()
            print("已清除断点文件")
        if results_file.exists():
            results_file.unlink()
            print("已清除结果文件")
    
    print("=" * 60)
    print("威科夫分析模块有效性验证")
    print("=" * 60)

    print("\n1. 加载股票列表...")
    symbols = load_stock_symbols(csv_path, limit=args.limit)
    print(f"   加载了 {len(symbols)} 只股票")

    print("\n2. 生成随机时点...")
    time_points = generate_random_time_points(
        start_year=2012,
        end_year=2025,
        n_points=args.time_points,
        seed=args.seed
    )
    print(f"   时点: {time_points}")

    print(f"\n3. 运行有效性验证...")
    print(f"   窗口: {windows}")
    print(f"   并行进程: {max_workers}")
    print(f"   批次大小: {batch_size}")
    
    # 加载断点
    checkpoint = load_checkpoint(checkpoint_file) if args.resume else {"completed_symbols": [], "total_results": 0}
    completed_symbols = set(checkpoint.get("completed_symbols", []))
    
    if args.resume and completed_symbols:
        print(f"   从断点继续: 已完成 {len(completed_symbols)} 只股票")

    start_time = time.time()
    
    # 分批处理
    total_batches = (len(symbols) + batch_size - 1) // batch_size
    all_results = load_existing_results(results_file) if args.resume else []
    
    for batch_idx in range(total_batches):
        batch_start = batch_idx * batch_size
        batch_end = min(batch_start + batch_size, len(symbols))
        batch_symbols = symbols[batch_start:batch_end]
        
        # 过滤已完成的股票
        if completed_symbols:
            batch_symbols = [s for s in batch_symbols if s["symbol"] not in completed_symbols]
        
        if not batch_symbols:
            continue
        
        print(f"\n  批次 {batch_idx + 1}/{total_batches}: {len(batch_symbols)} 只股票")
        
        # 准备任务参数
        tasks = [(symbol_info, time_points, windows) for symbol_info in batch_symbols]
        
        batch_results = []
        
        if max_workers > 1:
            # 多进程模式
            with ProcessPoolExecutor(max_workers=max_workers) as executor:
                future_to_symbol = {
                    executor.submit(analyze_single_stock, task): task[0]["symbol"]
                    for task in tasks
                }
                
                for future in as_completed(future_to_symbol, timeout=600):
                    symbol = future_to_symbol[future]
                    try:
                        symbol_results = future.result(timeout=60)
                        batch_results.extend(symbol_results)
                    except Exception as e:
                        print(f"    警告: {symbol} 分析失败: {e}")
        else:
            # 串行模式
            for task in tasks:
                symbol_results = analyze_single_stock(task)
                batch_results.extend(symbol_results)
        
        # 保存批次结果
        all_results.extend(batch_results)
        append_results_to_file(results_file, batch_results)
        
        # 更新断点
        for s in batch_symbols:
            completed_symbols.add(s["symbol"])
        
        checkpoint = {
            "completed_symbols": list(completed_symbols),
            "total_results": len(all_results),
            "last_update": time.strftime("%Y-%m-%d %H:%M:%S")
        }
        save_checkpoint(checkpoint_file, checkpoint)
        
        # 显示进度
        elapsed = time.time() - start_time
        rate = len(all_results) / elapsed if elapsed > 0 else 0
        print(f"    已完成: {len(completed_symbols)}/{len(symbols)} 只股票, "
              f"{len(all_results)} 个样本, "
              f"速度: {rate:.1f} 样本/秒")

    total_time = time.time() - start_time
    print(f"\n  总耗时: {total_time:.1f}秒")

    print("\n4. 分析有效性...")
    analysis = analyze_effectiveness(all_results)

    print("\n5. 输出结果...")
    write_outputs(all_results, analysis, output_dir)

    print("\n" + "=" * 60)
    print("验证摘要:")
    print(f"  总样本数: {len(all_results)}")
    print(f"  测试时点: {len(time_points)}")
    print(f"  回看窗口: {len(windows)}")
    print(f"  总耗时: {total_time:.1f}秒")
    print("=" * 60)


if __name__ == "__main__":
    main()
