#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
威科夫全量最新分析
- 读取stock_list.csv所有有效股票
- 使用通达信最新日线数据
- 合成周线和月线
- 回看1200天
- 输出详细分析结果
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd
import numpy as np

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


# ============================================================================
# 分析函数
# ============================================================================

def analyze_single_stock(args) -> Dict:
    """分析单只股票（多进程 worker）"""
    symbol_info, lookback_days = args
    symbol = symbol_info["symbol"]
    name = symbol_info["name"]
    
    result = {
        "symbol": symbol,
        "name": name,
        "status": "failed",
        "phase": "",
        "direction": "",
        "confidence": "",
        "sub_phase": "",
        "unknown_candidate": "",
        "trading_range": "",
        "bc_point": "",
        "sc_point": "",
        "lps_point": "",
        "markup_target": "",
        "markdown_target": "",
        "risk_reward": "",
        "multi_timeframe": "",
        "mtf_alignment": "",
        "monthly_phase": "",
        "weekly_phase": "",
        "daily_phase": "",
        "signal_type": "",
        "entry_price": 0,
        "stop_loss": 0,
        "target_price": 0,
        "reward_risk_ratio": 0,
        "data_range": "",
        "current_price": 0,
    }
    
    try:
        dm = DataManager()
        daily_df = dm.get_data(symbol)
        
        if daily_df is None or daily_df.empty:
            return result
        
        daily_df["date"] = pd.to_datetime(daily_df["date"])
        daily_df = daily_df.sort_values("date").reset_index(drop=True)
        
        # 合成周线月线
        weekly_df = synthesize_weekly(daily_df)
        monthly_df = synthesize_monthly(daily_df)
        
        # 获取最新日期数据
        latest_date = daily_df["date"].max()
        current_price = float(daily_df["close"].iloc[-1])
        
        # 分析数据范围
        data_start = daily_df["date"].min().strftime("%Y-%m-%d")
        data_end = daily_df["date"].max().strftime("%Y-%m-%d")
        data_count = len(daily_df)
        
        result["current_price"] = round(current_price, 2)
        result["data_range"] = f"{data_start} ~ {data_end} ({data_count}天)"
        
        if len(daily_df) < lookback_days:
            result["status"] = "数据不足"
            return result
        
        # 使用回看窗口的数据进行分析
        analysis_df = daily_df.tail(lookback_days)
        
        engine = WyckoffEngine(lookback_days=lookback_days)
        
        report = engine.analyze(
            analysis_df,
            symbol=symbol,
            period="日线",
            multi_timeframe=True
        )
        
        # 提取分析结果
        result["status"] = "success"
        result["phase"] = report.structure.phase.value
        result["direction"] = report.trading_plan.direction
        result["confidence"] = report.trading_plan.confidence.value
        
        # 阶段细分
        if hasattr(report.structure, 'sub_phase'):
            result["sub_phase"] = report.structure.sub_phase or ""
        
        # 未知阶段候选
        if hasattr(report.structure, 'unknown_candidate'):
            result["unknown_candidate"] = report.structure.unknown_candidate or ""
        
        # 交易区间
        if report.structure.trading_range_low and report.structure.trading_range_high:
            result["trading_range"] = f"{report.structure.trading_range_low:.2f} - {report.structure.trading_range_high:.2f}"
        
        # 关键点位
        if report.structure.bc_point:
            result["bc_point"] = f"{report.structure.bc_point.price:.2f} ({report.structure.bc_point.date})"
        
        if hasattr(report.structure, 'sc_point') and report.structure.sc_point:
            result["sc_point"] = f"{report.structure.sc_point.price:.2f} ({report.structure.sc_point.date})"
        
        if hasattr(report.structure, 'lps_point') and report.structure.lps_point:
            result["lps_point"] = f"{report.structure.lps_point.price:.2f} ({report.structure.lps_point.date})"
        
        # 目标价位
        if hasattr(report.trading_plan, 'markup_target') and report.trading_plan.markup_target:
            result["markup_target"] = f"{report.trading_plan.markup_target:.2f}"
        
        if hasattr(report.trading_plan, 'markdown_target') and report.trading_plan.markdown_target:
            result["markdown_target"] = f"{report.trading_plan.markdown_target:.2f}"
        
        # 风险收益比
        result["risk_reward"] = f"{report.risk_reward.reward_risk_ratio:.3f}"
        result["reward_risk_ratio"] = report.risk_reward.reward_risk_ratio
        
        # 入场止损目标
        if report.risk_reward.entry_price:
            result["entry_price"] = round(report.risk_reward.entry_price, 2)
        
        if hasattr(report.risk_reward, 'stop_loss') and report.risk_reward.stop_loss:
            result["stop_loss"] = round(report.risk_reward.stop_loss, 2)
        
        if hasattr(report.risk_reward, 'target_price') and report.risk_reward.target_price:
            result["target_price"] = round(report.risk_reward.target_price, 2)
        
        # 多周期分析
        if report.multi_timeframe:
            if report.multi_timeframe.monthly:
                result["monthly_phase"] = report.multi_timeframe.monthly.phase.value
            
            if report.multi_timeframe.weekly:
                result["weekly_phase"] = report.multi_timeframe.weekly.phase.value
            
            if report.multi_timeframe.daily:
                result["daily_phase"] = report.multi_timeframe.daily.phase.value
            
            result["mtf_alignment"] = report.multi_timeframe.alignment or ""
            result["multi_timeframe"] = f"月:{result['monthly_phase']} 周:{result['weekly_phase']} 日:{result['daily_phase']} 一致:{result['mtf_alignment']}"
        
        # 信号类型
        result["signal_type"] = report.signal.signal_type or ""
        
    except Exception as e:
        result["status"] = f"错误: {str(e)[:50]}"
    
    return result


# ============================================================================
# 输出函数
# ============================================================================

def write_outputs(all_results: List[Dict], output_dir: Path):
    """输出结果"""
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # 保存CSV
    df = pd.DataFrame(all_results)
    df.to_csv(output_dir / "latest_analysis_results.csv", index=False, encoding="utf-8-sig")
    
    # 保存JSON
    with (output_dir / "latest_analysis_results.json").open("w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)
    
    # 统计分析
    success_df = df[df["status"] == "success"]
    failed_df = df[df["status"] != "success"]
    
    # 阶段分布
    phase_stats = success_df["phase"].value_counts().to_dict()
    
    # 方向分布
    direction_stats = success_df["direction"].value_counts().to_dict()
    
    # 置信度分布
    confidence_stats = success_df["confidence"].value_counts().to_dict()
    
    # 多周期一致性分布
    mtf_stats = success_df["mtf_alignment"].value_counts().to_dict()
    
    # 生成Markdown报告
    md_lines = [
        "# 威科夫全量最新分析报告",
        "",
        f"- 分析日期: {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 回看窗口: 1200天",
        f"- 总股票数: {len(all_results)}",
        f"- 成功分析: {len(success_df)}",
        f"- 失败分析: {len(failed_df)}",
        f"- 成功率: {len(success_df)/len(all_results)*100:.1f}%",
        "",
        "## 阶段分布",
        "",
        "| 阶段 | 数量 | 占比 |",
        "|------|------|------|",
    ]
    
    for phase, count in sorted(phase_stats.items(), key=lambda x: -x[1]):
        pct = count / len(success_df) * 100
        md_lines.append(f"| {phase} | {count} | {pct:.1f}% |")
    
    md_lines.extend([
        "",
        "## 方向分布",
        "",
        "| 方向 | 数量 | 占比 |",
        "|------|------|------|",
    ])
    
    for direction, count in sorted(direction_stats.items(), key=lambda x: -x[1]):
        pct = count / len(success_df) * 100
        md_lines.append(f"| {direction} | {count} | {pct:.1f}% |")
    
    md_lines.extend([
        "",
        "## 置信度分布",
        "",
        "| 置信度 | 数量 | 占比 |",
        "|--------|------|------|",
    ])
    
    for conf, count in sorted(confidence_stats.items(), key=lambda x: -x[1]):
        pct = count / len(success_df) * 100
        md_lines.append(f"| {conf} | {count} | {pct:.1f}% |")
    
    md_lines.extend([
        "",
        "## 多周期一致性分布",
        "",
        "| 一致性 | 数量 | 占比 |",
        "|--------|------|------|",
    ])
    
    for alignment, count in sorted(mtf_stats.items(), key=lambda x: -x[1]):
        if alignment:
            pct = count / len(success_df) * 100
            md_lines.append(f"| {alignment} | {count} | {pct:.1f}% |")
    
    # 做多信号列表
    bullish_df = success_df[success_df["direction"].isin(["做多", "轻仓试探"])]
    if len(bullish_df) > 0:
        md_lines.extend([
            "",
            "## 做多信号列表",
            "",
            "| 代码 | 名称 | 阶段 | 置信度 | 入场价 | 止损 | 目标 | 风险收益比 | 多周期 |",
            "|------|------|------|--------|--------|------|------|------------|--------|",
        ])
        
        for _, row in bullish_df.iterrows():
            md_lines.append(
                f"| {row['symbol']} | {row['name']} | {row['phase']} | {row['confidence']} | "
                f"{row['entry_price']} | {row['stop_loss']} | {row['target_price']} | "
                f"{row['reward_risk_ratio']:.3f} | {row['mtf_alignment']} |"
            )
    
    # 持有观察信号列表
    hold_df = success_df[success_df["direction"] == "持有观察"]
    if len(hold_df) > 0:
        md_lines.extend([
            "",
            "## 持有观察信号列表",
            "",
            "| 代码 | 名称 | 阶段 | 置信度 | 当前价 | 风险收益比 | 多周期 |",
            "|------|------|------|--------|--------|------------|--------|",
        ])
        
        for _, row in hold_df.head(50).iterrows():
            md_lines.append(
                f"| {row['symbol']} | {row['name']} | {row['phase']} | {row['confidence']} | "
                f"{row['current_price']} | {row['reward_risk_ratio']:.3f} | {row['mtf_alignment']} |"
            )
    
    # 空仓观望信号列表
    bearish_df = success_df[success_df["direction"] == "空仓观望"]
    if len(bearish_df) > 0:
        md_lines.extend([
            "",
            f"## 空仓观望信号列表（共{len(bearish_df)}只，显示前50只）",
            "",
            "| 代码 | 名称 | 阶段 | 置信度 | 当前价 | 多周期 |",
            "|------|------|------|--------|--------|--------|",
        ])
        
        for _, row in bearish_df.head(50).iterrows():
            md_lines.append(
                f"| {row['symbol']} | {row['name']} | {row['phase']} | {row['confidence']} | "
                f"{row['current_price']} | {row['mtf_alignment']} |"
            )
    
    (output_dir / "latest_analysis_report.md").write_text("\n".join(md_lines), encoding="utf-8")
    
    print(f"\n输出文件:")
    print(f"  - {output_dir / 'latest_analysis_results.csv'}")
    print(f"  - {output_dir / 'latest_analysis_results.json'}")
    print(f"  - {output_dir / 'latest_analysis_report.md'}")


# ============================================================================
# 主函数
# ============================================================================

def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description="威科夫全量最新分析"
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
        "--lookback",
        type=int,
        default=1200,
        help="回看窗口天数（默认: 1200）"
    )
    parser.add_argument(
        "--batch-size", "-b",
        type=int,
        default=200,
        help="批次大小（默认: 200）"
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
    
    output_dir = Path(args.output) if args.output else PROJECT_ROOT / "output" / "wyckoff_latest"
    csv_path = PROJECT_ROOT / "data" / "stock_list.csv"
    lookback_days = args.lookback
    max_workers = args.workers
    batch_size = args.batch_size
    
    # 断点文件路径
    checkpoint_file = output_dir / "checkpoint.json"
    results_file = output_dir / "latest_analysis_results.jsonl"
    
    # 清除断点
    if args.reset:
        if checkpoint_file.exists():
            checkpoint_file.unlink()
            print("已清除断点文件")
        if results_file.exists():
            results_file.unlink()
            print("已清除结果文件")
    
    print("=" * 60)
    print("威科夫全量最新分析")
    print("=" * 60)

    print("\n1. 加载股票列表...")
    symbols = load_stock_symbols(csv_path, limit=args.limit)
    print(f"   加载了 {len(symbols)} 只股票")

    print(f"\n2. 运行全量分析...")
    print(f"   回看窗口: {lookback_days}天")
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
        tasks = [(symbol_info, lookback_days) for symbol_info in batch_symbols]
        
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
                        symbol_result = future.result(timeout=60)
                        batch_results.append(symbol_result)
                    except Exception as e:
                        print(f"    警告: {symbol} 分析失败: {e}")
                        batch_results.append({
                            "symbol": symbol,
                            "status": f"错误: {str(e)[:50]}"
                        })
        else:
            # 串行模式
            for task in tasks:
                symbol_result = analyze_single_stock(task)
                batch_results.append(symbol_result)
        
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
        
        # 统计成功/失败
        batch_success = sum(1 for r in batch_results if r.get("status") == "success")
        batch_failed = len(batch_results) - batch_success
        
        print(f"    已完成: {len(completed_symbols)}/{len(symbols)} 只股票, "
              f"成功: {batch_success}, 失败: {batch_failed}, "
              f"速度: {rate:.1f} 只/秒")

    total_time = time.time() - start_time
    print(f"\n  总耗时: {total_time:.1f}秒")

    print("\n3. 输出结果...")
    write_outputs(all_results, output_dir)

    print("\n" + "=" * 60)
    print("分析摘要:")
    print(f"  总股票数: {len(all_results)}")
    print(f"  回看窗口: {lookback_days}天")
    print(f"  总耗时: {total_time:.1f}秒")
    print("=" * 60)


if __name__ == "__main__":
    main()
