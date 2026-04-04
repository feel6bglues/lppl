#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MA 交叉 + ATR 参数优化脚本

轮次一：单指数 Smoke Test
轮次二：11 组 MA 组合扫描
轮次三：前 3 组合 × 8 指数
轮次四：ATR 参数优化
"""

import itertools
import os
import sys
import time
import warnings
from datetime import datetime
from multiprocessing import cpu_count
from typing import Any, Dict, Optional

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
warnings.filterwarnings("ignore")

# 常量定义
SYMBOLS = [
    "000001.SH", "399001.SZ", "399006.SZ", "000016.SH",
    "000300.SH", "000905.SH", "000852.SH", "932000.SH",
]

SYMBOL_NAMES = {
    "000001.SH": "上证综指",
    "399001.SZ": "深证成指",
    "399006.SZ": "创业板指",
    "000016.SH": "上证50",
    "000300.SH": "沪深300",
    "000905.SH": "中证500",
    "000852.SH": "中证1000",
    "932000.SH": "中证2000",
}

# MA 组合
MA_COMBOS = [
    (5, 30), (5, 120), (5, 250),
    (10, 30), (10, 120), (10, 250),
    (20, 30), (20, 120), (20, 250),
    (30, 120), (30, 250),
]

# 输出目录
OUTPUT_DIR = "output/ma_cross_atr_optimization"


def _is_eligible(summary: Dict[str, Any]) -> bool:
    return (
        float(summary.get("annualized_excess_return", 0.0)) > 0.0
        and float(summary.get("max_drawdown", 0.0)) > -0.35
        and int(summary.get("trade_count", 0)) >= 3
        and float(summary.get("turnover_rate", 0.0)) < 8.0
        and float(summary.get("whipsaw_rate", 0.0)) <= 0.35
    )


def build_signal_mapping(
    *,
    fast_ma: int,
    slow_ma: int,
    atr_period: int,
    atr_ma_window: int,
    buy_volatility_cap: float,
    vol_breakout_mult: float,
    enable_volatility_scaling: bool = False,
    target_volatility: float = 0.15,
) -> Dict[str, Any]:
    return {
        "signal_model": "ma_cross_atr_v1",
        "trend_fast_ma": fast_ma,
        "trend_slow_ma": slow_ma,
        "atr_period": atr_period,
        "atr_ma_window": atr_ma_window,
        "buy_volatility_cap": buy_volatility_cap,
        "vol_breakout_mult": vol_breakout_mult,
        "buy_confirm_days": 1,
        "sell_confirm_days": 1,
        "cooldown_days": 5,
        "initial_position": 0.0,
        "enable_volatility_scaling": enable_volatility_scaling,
        "target_volatility": target_volatility,
    }


def load_data_manager():
    """加载数据管理器"""
    from src.data.manager import DataManager
    return DataManager()


def run_single_backtest(
    symbol: str,
    fast_ma: int,
    slow_ma: int,
    atr_period: int,
    atr_ma_window: int,
    buy_volatility_cap: float,
    vol_breakout_mult: float,
    enable_volatility_scaling: bool = False,
    target_volatility: float = 0.15,
    start_date: str = "2020-01-01",
    end_date: str = "2026-03-27",
) -> Optional[Dict[str, Any]]:
    """运行单次回测"""
    from src.data.manager import DataManager
    from src.investment import (
        BacktestConfig,
        InvestmentSignalConfig,
        generate_investment_signals,
        run_strategy_backtest,
    )

    try:
        manager = DataManager()
        df = manager.get_data(symbol)
        if df is None or df.empty:
            return None

        signal_cfg = InvestmentSignalConfig.from_mapping(
            symbol,
            build_signal_mapping(
                fast_ma=fast_ma,
                slow_ma=slow_ma,
                atr_period=atr_period,
                atr_ma_window=atr_ma_window,
                buy_volatility_cap=buy_volatility_cap,
                vol_breakout_mult=vol_breakout_mult,
                enable_volatility_scaling=enable_volatility_scaling,
                target_volatility=target_volatility,
            ),
        )

        signal_df = generate_investment_signals(
            df=df,
            symbol=symbol,
            signal_config=signal_cfg,
            lppl_config=None,
            use_ensemble=False,
            start_date=start_date,
            end_date=end_date,
            scan_step=5,
        )

        equity_df, trades_df, summary = run_strategy_backtest(
            signal_df,
            BacktestConfig(
                initial_capital=1_000_000.0,
                buy_fee=0.0003,
                sell_fee=0.0003,
                slippage=0.0005,
                start_date=start_date,
                end_date=end_date,
            ),
        )

        return {
            "symbol": symbol,
            "symbol_name": SYMBOL_NAMES.get(symbol, symbol),
            "fast_ma": fast_ma,
            "slow_ma": slow_ma,
            "atr_period": atr_period,
            "atr_ma_window": atr_ma_window,
            "buy_volatility_cap": buy_volatility_cap,
            "vol_breakout_mult": vol_breakout_mult,
            "annualized_excess_return": summary.get("annualized_excess_return", 0.0),
            "max_drawdown": summary.get("max_drawdown", -1.0),
            "trade_count": summary.get("trade_count", 0),
            "turnover_rate": summary.get("turnover_rate", 0.0),
            "whipsaw_rate": summary.get("whipsaw_rate", 0.0),
            "enable_volatility_scaling": enable_volatility_scaling,
            "target_volatility": target_volatility,
            "eligible": _is_eligible(summary),
        }
    except Exception as e:
        print(f"  [ERROR] {symbol} MA{fast_ma}/{slow_ma}: {e}")
        return None


def round1_smoke_test(
    *,
    enable_volatility_scaling: bool = False,
    target_volatility: float = 0.15,
    start_date: str = "2020-01-01",
    end_date: str = "2026-03-27",
):
    """轮次一：单指数 Smoke Test"""
    print("=" * 80)
    print("轮次一：单指数 Smoke Test")
    print("=" * 80)
    print("测试指数: 000300.SH (沪深300)")
    print("测试组合: MA20 / MA60")
    print("测试参数: ATR14, ATR_MA40, buy_cap=1.05, sell_mult=1.15")
    print(f"波动率缩放: {'开启' if enable_volatility_scaling else '关闭'} (target_vol={target_volatility:.2f})")
    print()

    result = run_single_backtest(
        symbol="000300.SH",
        fast_ma=20,
        slow_ma=60,
        atr_period=14,
        atr_ma_window=40,
        buy_volatility_cap=1.05,
        vol_breakout_mult=1.15,
        enable_volatility_scaling=enable_volatility_scaling,
        target_volatility=target_volatility,
        start_date=start_date,
        end_date=end_date,
    )

    if result:
        print("✅ Smoke Test 通过")
        print(f"  年化超额: {result['annualized_excess_return']:.2%}")
        print(f"  最大回撤: {result['max_drawdown']:.2%}")
        print(f"  交易次数: {result['trade_count']}")
        print(f"  eligible: {result['eligible']}")
    else:
        print("❌ Smoke Test 失败")

    return result


def round2_ma_combination_scan(
    *,
    enable_volatility_scaling: bool = False,
    target_volatility: float = 0.15,
    start_date: str = "2020-01-01",
    end_date: str = "2026-03-27",
):
    """轮次二：11 组 MA 组合扫描"""
    print("\n" + "=" * 80)
    print("轮次二：11 组 MA 组合扫描")
    print("=" * 80)
    print("测试指数: 000300.SH (沪深300)")
    print(f"MA 组合: {len(MA_COMBOS)} 组")
    print(f"波动率缩放: {'开启' if enable_volatility_scaling else '关闭'} (target_vol={target_volatility:.2f})")
    print()

    results = []
    total = len(MA_COMBOS)
    for i, (fast_ma, slow_ma) in enumerate(MA_COMBOS, 1):
        print(f"[{i}/{total}] MA{fast_ma}/MA{slow_ma}...", end=" ", flush=True)
        result = run_single_backtest(
            symbol="000300.SH",
            fast_ma=fast_ma,
            slow_ma=slow_ma,
            atr_period=14,
            atr_ma_window=40,
            buy_volatility_cap=1.05,
            vol_breakout_mult=1.15,
            enable_volatility_scaling=enable_volatility_scaling,
            target_volatility=target_volatility,
            start_date=start_date,
            end_date=end_date,
        )
        if result:
            results.append(result)
            print(f"excess={result['annualized_excess_return']:.2%}, drawdown={result['max_drawdown']:.2%}, trades={result['trade_count']}")
        else:
            print("FAILED")

    # 保存结果
    os.makedirs(f"{OUTPUT_DIR}/round2", exist_ok=True)
    df = pd.DataFrame(results)
    df.to_csv(f"{OUTPUT_DIR}/round2/ma_combination_scan.csv", index=False)

    # 打印排名
    print("\n" + "-" * 60)
    print("MA 组合排名（按年化超额）:")
    print("-" * 60)
    ranked = df.sort_values("annualized_excess_return", ascending=False)
    for _, row in ranked.iterrows():
        eligible = "✅" if row["eligible"] else "❌"
        print(f"  {eligible} MA{int(row['fast_ma'])}/{int(row['slow_ma'])}: excess={row['annualized_excess_return']:.2%}, drawdown={row['max_drawdown']:.2%}, trades={int(row['trade_count'])}")

    return df


def round3_full_index_test(
    top_n: int = 3,
    *,
    enable_volatility_scaling: bool = False,
    target_volatility: float = 0.15,
    start_date: str = "2020-01-01",
    end_date: str = "2026-03-27",
):
    """轮次三：前 N 组合 × 8 指数全量测试"""
    print("\n" + "=" * 80)
    print(f"轮次三：前 {top_n} 组合 × 8 指数全量测试")
    print("=" * 80)
    print(f"波动率缩放: {'开启' if enable_volatility_scaling else '关闭'} (target_vol={target_volatility:.2f})")

    # 读取轮次二结果
    round2_file = f"{OUTPUT_DIR}/round2/ma_combination_scan.csv"
    if not os.path.exists(round2_file):
        print("❌ 轮次二结果不存在，请先运行轮次二")
        return None

    round2_df = pd.read_csv(round2_file)
    top_combos = round2_df.sort_values("annualized_excess_return", ascending=False).head(top_n)
    print(f"选出前 {top_n} 组合:")
    for _, row in top_combos.iterrows():
        print(f"  MA{int(row['fast_ma'])}/MA{int(row['slow_ma'])}")
    print()

    all_results = []
    for _, combo in top_combos.iterrows():
        fast_ma = int(combo["fast_ma"])
        slow_ma = int(combo["slow_ma"])
        print(f"\n{'='*60}")
        print(f"测试组合: MA{fast_ma}/MA{slow_ma}")
        print(f"{'='*60}")

        for i, symbol in enumerate(SYMBOLS, 1):
            print(f"  [{i}/{len(SYMBOLS)}] {symbol} ({SYMBOL_NAMES[symbol]})...", end=" ", flush=True)
            result = run_single_backtest(
                symbol=symbol,
                fast_ma=fast_ma,
                slow_ma=slow_ma,
                atr_period=14,
                atr_ma_window=40,
                buy_volatility_cap=1.05,
                vol_breakout_mult=1.15,
                enable_volatility_scaling=enable_volatility_scaling,
                target_volatility=target_volatility,
                start_date=start_date,
                end_date=end_date,
            )
            if result:
                all_results.append(result)
                eligible = "✅" if result["eligible"] else "❌"
                print(f"{eligible} excess={result['annualized_excess_return']:.2%}, drawdown={result['max_drawdown']:.2%}, trades={result['trade_count']}")
            else:
                print("FAILED")

    # 保存结果
    os.makedirs(f"{OUTPUT_DIR}/round3", exist_ok=True)
    df = pd.DataFrame(all_results)
    df.to_csv(f"{OUTPUT_DIR}/round3/full_index_test.csv", index=False)

    # 打印汇总
    print("\n" + "=" * 60)
    print("轮次三汇总:")
    print("=" * 60)
    for _, combo in top_combos.iterrows():
        fast_ma = int(combo["fast_ma"])
        slow_ma = int(combo["slow_ma"])
        combo_df = df[(df["fast_ma"] == fast_ma) & (df["slow_ma"] == slow_ma)]
        eligible_count = combo_df["eligible"].sum()
        print(f"\n  MA{fast_ma}/MA{slow_ma}: eligible={eligible_count}/8")
        for _, row in combo_df.iterrows():
            eligible = "✅" if row["eligible"] else "❌"
            print(f"    {eligible} {row['symbol']}: excess={row['annualized_excess_return']:.2%}, drawdown={row['max_drawdown']:.2%}")

    return df


def round4_atr_optimization(
    *,
    enable_volatility_scaling: bool = False,
    target_volatility: float = 0.15,
    start_date: str = "2020-01-01",
    end_date: str = "2026-03-27",
):
    """轮次四：ATR 参数优化"""
    print("\n" + "=" * 80)
    print("轮次四：ATR 参数优化")
    print("=" * 80)
    print(f"波动率缩放: {'开启' if enable_volatility_scaling else '关闭'} (target_vol={target_volatility:.2f})")

    # 读取轮次二结果，取最优组合
    round2_file = f"{OUTPUT_DIR}/round2/ma_combination_scan.csv"
    if not os.path.exists(round2_file):
        print("❌ 轮次二结果不存在，请先运行轮次二")
        return None

    round2_df = pd.read_csv(round2_file)
    best_combo = round2_df.sort_values("annualized_excess_return", ascending=False).iloc[0]
    fast_ma = int(best_combo["fast_ma"])
    slow_ma = int(best_combo["slow_ma"])
    print(f"使用最优 MA 组合: MA{fast_ma}/MA{slow_ma}")
    print()

    # ATR 参数扫描
    atr_periods = [10, 14, 20]
    atr_ma_windows = [20, 40, 60]
    buy_volatility_caps = [1.00, 1.05, 1.10]
    vol_breakout_mults = [1.05, 1.10, 1.15]

    atr_combos = list(itertools.product(atr_periods, atr_ma_windows, buy_volatility_caps, vol_breakout_mults))
    print(f"ATR 参数组合: {len(atr_combos)} 组")
    print()

    results = []
    total = len(atr_combos)
    for i, (atr_period, atr_ma_window, buy_cap, sell_mult) in enumerate(atr_combos, 1):
        print(f"[{i}/{total}] ATR{atr_period}/ATR_MA{atr_ma_window}/buy{buy_cap}/sell{sell_mult}...", end=" ", flush=True)
        result = run_single_backtest(
            symbol="000300.SH",
            fast_ma=fast_ma,
            slow_ma=slow_ma,
            atr_period=atr_period,
            atr_ma_window=atr_ma_window,
            buy_volatility_cap=buy_cap,
            vol_breakout_mult=sell_mult,
            enable_volatility_scaling=enable_volatility_scaling,
            target_volatility=target_volatility,
            start_date=start_date,
            end_date=end_date,
        )
        if result:
            results.append(result)
            eligible = "✅" if result["eligible"] else "❌"
            print(f"{eligible} excess={result['annualized_excess_return']:.2%}, drawdown={result['max_drawdown']:.2%}")
        else:
            print("FAILED")

    # 保存结果
    os.makedirs(f"{OUTPUT_DIR}/round4", exist_ok=True)
    df = pd.DataFrame(results)
    df.to_csv(f"{OUTPUT_DIR}/round4/atr_optimization.csv", index=False)

    # 打印排名
    print("\n" + "-" * 60)
    print("ATR 参数排名（按年化超额）:")
    print("-" * 60)
    ranked = df.sort_values("annualized_excess_return", ascending=False).head(10)
    for _, row in ranked.iterrows():
        eligible = "✅" if row["eligible"] else "❌"
        print(f"  {eligible} ATR{int(row['atr_period'])}/ATR_MA{int(row['atr_ma_window'])}/buy{row['buy_volatility_cap']:.2f}/sell{row['vol_breakout_mult']:.2f}: excess={row['annualized_excess_return']:.2%}")

    return df


def generate_summary_report():
    """生成测试报告"""
    print("\n" + "=" * 80)
    print("生成测试报告")
    print("=" * 80)

    report_lines = []
    report_lines.append("# MA 交叉 + ATR 参数优化报告")
    report_lines.append(f"\n**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report_lines.append("\n**测试周期**: 2020-01-01 ~ 2026-03-27")
    report_lines.append("\n---\n")

    # 轮次二结果
    round2_file = f"{OUTPUT_DIR}/round2/ma_combination_scan.csv"
    if os.path.exists(round2_file):
        df = pd.read_csv(round2_file)
        report_lines.append("## 轮次二：MA 组合扫描\n")
        report_lines.append("| MA组合 | 年化超额 | 最大回撤 | 交易次数 | eligible |")
        report_lines.append("|:-------|--------:|--------:|--------:|:--------:|")
        for _, row in df.sort_values("annualized_excess_return", ascending=False).iterrows():
            eligible = "✅" if row["eligible"] else "❌"
            report_lines.append(f"| MA{int(row['fast_ma'])}/MA{int(row['slow_ma'])} | {row['annualized_excess_return']:.2%} | {row['max_drawdown']:.2%} | {int(row['trade_count'])} | {eligible} |")
        report_lines.append("")

    # 轮次三结果
    round3_file = f"{OUTPUT_DIR}/round3/full_index_test.csv"
    if os.path.exists(round3_file):
        df = pd.read_csv(round3_file)
        report_lines.append("## 轮次三：8 指数全量测试\n")
        for combo_key, combo_df in df.groupby(["fast_ma", "slow_ma"]):
            fast_ma, slow_ma = combo_key
            eligible_count = combo_df["eligible"].sum()
            report_lines.append(f"### MA{int(fast_ma)}/MA{int(slow_ma)} (eligible={eligible_count}/8)\n")
            report_lines.append("| 指数 | 年化超额 | 最大回撤 | 交易次数 | eligible |")
            report_lines.append("|:-----|--------:|--------:|--------:|:--------:|")
            for _, row in combo_df.iterrows():
                eligible = "✅" if row["eligible"] else "❌"
                report_lines.append(f"| {row['symbol']} | {row['annualized_excess_return']:.2%} | {row['max_drawdown']:.2%} | {int(row['trade_count'])} | {eligible} |")
            report_lines.append("")

    # 轮次四结果
    round4_file = f"{OUTPUT_DIR}/round4/atr_optimization.csv"
    if os.path.exists(round4_file):
        df = pd.read_csv(round4_file)
        report_lines.append("## 轮次四：ATR 参数优化\n")
        report_lines.append("| ATR周期 | ATR_MA | 买入上限 | 卖出触发 | 年化超额 | 最大回撤 | eligible |")
        report_lines.append("|:--------|:------:|--------:|--------:|--------:|--------:|:--------:|")
        for _, row in df.sort_values("annualized_excess_return", ascending=False).head(10).iterrows():
            eligible = "✅" if row["eligible"] else "❌"
            report_lines.append(f"| {int(row['atr_period'])} | {int(row['atr_ma_window'])} | {row['buy_volatility_cap']:.2f} | {row['vol_breakout_mult']:.2f} | {row['annualized_excess_return']:.2%} | {row['max_drawdown']:.2%} | {eligible} |")
        report_lines.append("")

    # 保存报告
    report_path = f"{OUTPUT_DIR}/optimization_report.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(report_lines))
    print(f"✅ 报告已保存: {report_path}")

    return report_path


def main():
    """主函数"""
    global OUTPUT_DIR
    import argparse

    parser = argparse.ArgumentParser(description="MA 交叉 + ATR 参数优化")
    parser.add_argument("--round", type=int, default=0, help="运行指定轮次 (0=全部)")
    parser.add_argument("--symbol", type=str, default=None, help="指定指数")
    parser.add_argument("--output", type=str, default=OUTPUT_DIR, help="输出目录")
    parser.add_argument("--start-date", type=str, default="2020-01-01", help="起始日期")
    parser.add_argument("--end-date", type=str, default="2026-03-27", help="结束日期")
    parser.add_argument(
        "--enable-volatility-scaling",
        action="store_true",
        help="启用动态波动率缩放",
    )
    parser.add_argument(
        "--target-volatility",
        type=float,
        default=0.15,
        help="目标年化波动率",
    )
    args = parser.parse_args()

    OUTPUT_DIR = args.output

    print("=" * 80)
    print("MA 交叉 + ATR 参数优化")
    print("=" * 80)
    print(f"输出目录: {OUTPUT_DIR}")
    print(f"CPU 核心: {cpu_count()}")
    print(f"测试区间: {args.start_date} ~ {args.end_date}")
    print(
        "波动率缩放: "
        f"{'开启' if args.enable_volatility_scaling else '关闭'} "
        f"(target_vol={args.target_volatility:.2f})"
    )
    print()

    start_time = time.time()

    if args.round == 0 or args.round == 1:
        round1_smoke_test(
            enable_volatility_scaling=args.enable_volatility_scaling,
            target_volatility=args.target_volatility,
            start_date=args.start_date,
            end_date=args.end_date,
        )

    if args.round == 0 or args.round == 2:
        round2_ma_combination_scan(
            enable_volatility_scaling=args.enable_volatility_scaling,
            target_volatility=args.target_volatility,
            start_date=args.start_date,
            end_date=args.end_date,
        )

    if args.round == 0 or args.round == 3:
        round3_full_index_test(
            top_n=3,
            enable_volatility_scaling=args.enable_volatility_scaling,
            target_volatility=args.target_volatility,
            start_date=args.start_date,
            end_date=args.end_date,
        )

    if args.round == 0 or args.round == 4:
        round4_atr_optimization(
            enable_volatility_scaling=args.enable_volatility_scaling,
            target_volatility=args.target_volatility,
            start_date=args.start_date,
            end_date=args.end_date,
        )

    if args.round == 0:
        generate_summary_report()

    elapsed = time.time() - start_time
    print(f"\n总耗时: {elapsed:.1f}秒 ({elapsed/60:.1f}分钟)")


if __name__ == "__main__":
    main()
