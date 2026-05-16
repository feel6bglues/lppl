# RESEARCH ONLY — not production code
# -*- coding: utf-8 -*-
"""
MA + ATR 长持仓与暴跌逃顶策略调优脚本

遵循 docs/ma_atr_long_horizon_newbie_execution_plan.md 的执行计划
- 长周期趋势持有
- ATR 风险过滤
- 暴跌逃顶
- 最小持仓周期控制
"""
from __future__ import annotations

import argparse
import os
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Dict, List

import pandas as pd

for env_name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ.setdefault(env_name, "1")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.cli.lppl_verify_v2 import SYMBOLS
from src.data.manager import DataManager
from src.investment import (
    BacktestConfig,
    InvestmentSignalConfig,
    generate_investment_signals,
    run_strategy_backtest,
    score_signal_tuning_results,
)
from src.lppl_engine import LPPLConfig

# 定义指数分组
LARGE_CAP_SYMBOLS = {"000001.SH", "000016.SH", "000300.SH", "000905.SH"}
HIGH_BETA_SYMBOLS = {"399006.SZ", "000852.SH"}

# ============ 长持仓策略参数矩阵 ============

# A1/A2/A3: 大盘/宽基组合
LARGE_CAP_CONFIGS = [
    # A1: MA20/MA120, ATR14/ATR20_MA <= 1.05, 最小持仓8周, 逃顶回撤10%
    {
        "name": "A1",
        "fast_ma": 20,
        "slow_ma": 120,
        "atr_period": 14,
        "atr_ma_window": 20,
        "buy_volatility_cap": 1.05,
        "vol_breakout_mult": 1.10,
        "confirm_days": 2,
        "cooldown_days": 8,  # 8周 = 40个交易日
        "regime_filter_ma": 120,
        "regime_filter_buffer": 1.0,
        "risk_drawdown_stop_threshold": 0.10,
        "risk_drawdown_lookback": 20,
        "min_hold_bars": 40,  # 8周
    },
    # A2: MA20/MA60, ATR14/ATR20_MA <= 1.10, 最小持仓10周, 逃顶回撤8%
    {
        "name": "A2",
        "fast_ma": 20,
        "slow_ma": 60,
        "atr_period": 14,
        "atr_ma_window": 20,
        "buy_volatility_cap": 1.10,
        "vol_breakout_mult": 1.05,
        "confirm_days": 2,
        "cooldown_days": 10,  # 10周 = 50个交易日
        "regime_filter_ma": 60,
        "regime_filter_buffer": 1.0,
        "risk_drawdown_stop_threshold": 0.08,
        "risk_drawdown_lookback": 20,
        "min_hold_bars": 50,  # 10周
    },
    # A3: MA30/MA120, ATR20/ATR40_MA <= 1.05, 最小持仓12周, 逃顶回撤12%
    {
        "name": "A3",
        "fast_ma": 30,
        "slow_ma": 120,
        "atr_period": 20,
        "atr_ma_window": 40,
        "buy_volatility_cap": 1.05,
        "vol_breakout_mult": 1.05,
        "confirm_days": 3,
        "cooldown_days": 12,  # 12周 = 60个交易日
        "regime_filter_ma": 120,
        "regime_filter_buffer": 1.0,
        "risk_drawdown_stop_threshold": 0.12,
        "risk_drawdown_lookback": 20,
        "min_hold_bars": 60,  # 12周
    },
]

# B1/B2/B3: 高波动组合
HIGH_BETA_CONFIGS = [
    # B1: MA10/MA60, ATR14/ATR20_MA <= 1.10, 最小持仓4周, 逃顶回撤8%
    {
        "name": "B1",
        "fast_ma": 10,
        "slow_ma": 60,
        "atr_period": 14,
        "atr_ma_window": 20,
        "buy_volatility_cap": 1.10,
        "vol_breakout_mult": 1.05,
        "confirm_days": 2,
        "cooldown_days": 4,  # 4周 = 20个交易日
        "regime_filter_ma": 60,
        "regime_filter_buffer": 1.0,
        "risk_drawdown_stop_threshold": 0.08,
        "risk_drawdown_lookback": 20,
        "min_hold_bars": 20,  # 4周
    },
    # B2: MA20/MA60, ATR14/ATR20_MA <= 1.15, 最小持仓6周, 逃顶回撤10%
    {
        "name": "B2",
        "fast_ma": 20,
        "slow_ma": 60,
        "atr_period": 14,
        "atr_ma_window": 20,
        "buy_volatility_cap": 1.15,
        "vol_breakout_mult": 1.10,
        "confirm_days": 2,
        "cooldown_days": 6,  # 6周 = 30个交易日
        "regime_filter_ma": 60,
        "regime_filter_buffer": 1.0,
        "risk_drawdown_stop_threshold": 0.10,
        "risk_drawdown_lookback": 20,
        "min_hold_bars": 30,  # 6周
    },
    # B3: MA20/MA120, ATR20/ATR40_MA <= 1.10, 最小持仓8周, 逃顶回撤12%
    {
        "name": "B3",
        "fast_ma": 20,
        "slow_ma": 120,
        "atr_period": 20,
        "atr_ma_window": 40,
        "buy_volatility_cap": 1.10,
        "vol_breakout_mult": 1.05,
        "confirm_days": 3,
        "cooldown_days": 8,  # 8周 = 40个交易日
        "regime_filter_ma": 120,
        "regime_filter_buffer": 1.0,
        "risk_drawdown_stop_threshold": 0.12,
        "risk_drawdown_lookback": 20,
        "min_hold_bars": 40,  # 8周
    },
]


def _build_signal_config(config: Dict) -> InvestmentSignalConfig:
    """根据配置构建信号配置"""
    return InvestmentSignalConfig(
        signal_model="ma_cross_atr_long_hold_v1",
        initial_position=0.0,
        trend_fast_ma=config["fast_ma"],
        trend_slow_ma=config["slow_ma"],
        trend_slope_window=5,
        atr_period=config["atr_period"],
        atr_ma_window=config["atr_ma_window"],
        buy_volatility_cap=config["buy_volatility_cap"],
        vol_breakout_mult=config["vol_breakout_mult"],
        buy_confirm_days=config["confirm_days"],
        sell_confirm_days=config["confirm_days"],
        cooldown_days=config["cooldown_days"],
        full_exit_days=3,
        regime_filter_ma=config["regime_filter_ma"],
        regime_filter_buffer=config["regime_filter_buffer"],
        regime_filter_reduce_enabled=True,
        risk_drawdown_stop_threshold=config["risk_drawdown_stop_threshold"],
        risk_drawdown_lookback=config["risk_drawdown_lookback"],
        min_hold_bars=config["min_hold_bars"],
    )


def _run_candidate(
    df: pd.DataFrame,
    symbol: str,
    config: Dict,
    start_date: str,
    end_date: str,
) -> Dict[str, object]:
    """运行单个候选配置"""
    signal_config = _build_signal_config(config)

    signal_df = generate_investment_signals(
        df=df,
        symbol=symbol,
        signal_config=signal_config,
        lppl_config=LPPLConfig(window_range=[20], n_workers=1),
        use_ensemble=False,
        start_date=start_date,
        end_date=end_date,
        scan_step=1,
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

    periods = max(len(equity_df), 1)
    benchmark_return_total = float(summary.get("benchmark_return", 0.0))
    annualized_return = float(summary.get("annualized_return", 0.0))
    annualized_benchmark = (
        ((1.0 + benchmark_return_total) ** (252.0 / periods) - 1.0) if benchmark_return_total > -1.0 else -1.0
    )
    annualized_excess_return = annualized_return - annualized_benchmark
    max_drawdown = float(summary.get("max_drawdown", 0.0))
    summary["annualized_benchmark"] = annualized_benchmark
    summary["annualized_excess_return"] = annualized_excess_return
    summary["calmar_ratio"] = annualized_return / abs(max_drawdown) if max_drawdown < 0 else annualized_return

    notional = 0.0
    if not trades_df.empty and {"price", "units"}.issubset(trades_df.columns):
        notional = float((trades_df["price"].astype(float) * trades_df["units"].astype(float)).sum())
    turnover_rate = notional / 1_000_000.0
    years = max((pd.to_datetime(end_date) - pd.to_datetime(start_date)).days / 365.25, 1 / 365.25)
    summary["turnover_rate"] = turnover_rate
    summary["annualized_turnover_rate"] = turnover_rate / years

    # 用“短持有回合占比”近似 whipsaw，长持仓策略下该值应明显偏低。
    round_trip_holds = []
    if not trades_df.empty and len(trades_df) >= 2:
        for i in range(0, len(trades_df) - 1, 2):
            if i + 1 >= len(trades_df):
                continue
            entry = pd.to_datetime(trades_df.iloc[i]["date"])
            exit_ = pd.to_datetime(trades_df.iloc[i + 1]["date"])
            round_trip_holds.append((exit_ - entry).days)
    whipsaw_threshold = max(10, int(config["min_hold_bars"]) // 2)
    if round_trip_holds:
        summary["whipsaw_rate"] = sum(1 for days in round_trip_holds if days <= whipsaw_threshold) / len(round_trip_holds)
    else:
        summary["whipsaw_rate"] = 0.0

    # 计算额外指标：平均持仓周期
    if not trades_df.empty and len(trades_df) >= 2:
        # 计算每笔交易的持仓天数
        hold_periods = []
        for i in range(0, len(trades_df) - 1, 2):
            if i + 1 < len(trades_df):
                entry_date = pd.to_datetime(trades_df.iloc[i]["date"])
                exit_date = pd.to_datetime(trades_df.iloc[i + 1]["date"])
                hold_days = (exit_date - entry_date).days
                hold_periods.append(hold_days)
        
        if hold_periods:
            summary["avg_hold_days"] = sum(hold_periods) / len(hold_periods)
            summary["max_hold_days"] = max(hold_periods)
            summary["min_hold_days"] = min(hold_periods)
        else:
            summary["avg_hold_days"] = 0
            summary["max_hold_days"] = 0
            summary["min_hold_days"] = 0
    else:
        summary["avg_hold_days"] = 0
        summary["max_hold_days"] = 0
        summary["min_hold_days"] = 0
    
    return summary


def _score_results(results_df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    """评分结果"""
    max_dd_cap = -0.40 if symbol in HIGH_BETA_SYMBOLS else -0.35
    return score_signal_tuning_results(
        results_df,
        min_trade_count=2,
        max_drawdown_cap=max_dd_cap,
        turnover_cap=8.0,  # 长持仓策略换手应该更低
        whipsaw_cap=0.30,
        scoring_profile="balanced",
        hard_reject=True,
    )

def _build_result_row(config: Dict, summary: Dict[str, object]) -> Dict[str, object]:
    return {
        "config_name": config["name"],
        "fast_ma": config["fast_ma"],
        "slow_ma": config["slow_ma"],
        "atr_period": config["atr_period"],
        "atr_ma_window": config["atr_ma_window"],
        "buy_volatility_cap": config["buy_volatility_cap"],
        "vol_breakout_mult": config["vol_breakout_mult"],
        "confirm_days": config["confirm_days"],
        "cooldown_days": config["cooldown_days"],
        "regime_filter_ma": config["regime_filter_ma"],
        "risk_drawdown_stop_threshold": config["risk_drawdown_stop_threshold"],
        "risk_drawdown_lookback": config["risk_drawdown_lookback"],
        "min_hold_bars": config["min_hold_bars"],
        **summary,
    }


def _evaluate_symbol_config(task: Dict[str, object]) -> Dict[str, object]:
    """单任务执行：一个指数 + 一个参数组合。"""
    symbol = str(task["symbol"])
    start_date = str(task["start_date"])
    end_date = str(task["end_date"])
    config = dict(task["config"])

    # 加载数据
    manager = DataManager()
    df = manager.get_data(symbol)
    if df is None or df.empty:
        raise ValueError(f"无法加载数据: {symbol}")

    summary = _run_candidate(df, symbol, config, start_date, end_date)
    return {
        "symbol": symbol,
        "name": SYMBOLS.get(symbol, symbol),
        "stage": "long_hold_test",
        **_build_result_row(config, summary),
    }


def _print_symbol_header(symbol: str, start_date: str, end_date: str) -> None:
    print(f"\n{'='*60}")
    print(f"运行长持仓策略调优: {symbol}")
    print(f"时间范围: {start_date} ~ {end_date}")
    print(f"{'='*60}\n")
    if symbol in HIGH_BETA_SYMBOLS:
        print("使用高波动配置 (B1/B2/B3)")
    else:
        print("使用大盘配置 (A1/A2/A3)")


def _print_symbol_summary(symbol: str, scored_df: pd.DataFrame, csv_path: Path) -> None:
    print(f"\n结果已保存: {csv_path}")
    print(f"\n{'='*60}")
    print(f"{symbol} 测试结果摘要")
    print(f"{'='*60}")
    for _, row in scored_df.iterrows():
        print(f"\n{row['config_name']}:")
        print(f"  年化收益: {row.get('annualized_return', 0)*100:.2f}%")
        print(f"  年化超额: {row.get('annualized_excess_return', 0)*100:.2f}%")
        print(f"  最大回撤: {row.get('max_drawdown', 0)*100:.2f}%")
        print(f"  交易次数: {row.get('trade_count', 0)}")
        print(f"  平均持仓: {row.get('avg_hold_days', 0):.1f} 天")
        print(f"  换手率: {row.get('turnover_rate', 0):.2f}%")
        print(f"  Eligible: {row.get('eligible', False)}")


def run_long_hold_tuning(
    symbol: str,
    start_date: str,
    end_date: str,
    output_dir: Path,
    workers: int = 4,
) -> pd.DataFrame:
    """运行长持仓策略调优"""
    result = _run_symbol_tuning((symbol, start_date, end_date, output_dir))
    return result if result is not None else pd.DataFrame()


def main():
    import multiprocessing

    # 自动检测系统CPU核心数
    total_cpus = multiprocessing.cpu_count()
    recommended_workers = max(2, total_cpus - 2)

    parser = argparse.ArgumentParser(description="MA+ATR 长持仓策略调优")
    parser.add_argument("--symbols", type=str, required=True, help="指数代码，逗号分隔")
    parser.add_argument("--start-date", type=str, required=True, help="开始日期 (YYYY-MM-DD)")
    parser.add_argument("--end-date", type=str, required=True, help="结束日期 (YYYY-MM-DD)")
    parser.add_argument("--output", type=str, required=True, help="输出目录")
    parser.add_argument("--workers", type=int, default=recommended_workers, help=f"并行 worker 数量 (默认: {recommended_workers}, 系统总核心数: {total_cpus})")
    
    args = parser.parse_args()
    
    symbols = [s.strip() for s in args.symbols.split(",")]
    output_dir = Path(args.output)
    
    print(f"\n{'='*80}")
    print("开始长持仓策略调优")
    print(f"测试指数: {len(symbols)} 个")
    print(f"时间范围: {args.start_date} ~ {args.end_date}")
    print(f"并行线程: {args.workers}")
    print(f"输出目录: {output_dir}")
    print(f"{'='*80}\n")
    
    output_dir.mkdir(parents=True, exist_ok=True)

    # 扁平化任务，避免“按指数并行 + 按配置并行”的嵌套进程结构。
    symbol_to_configs = {
        symbol: (HIGH_BETA_CONFIGS if symbol in HIGH_BETA_SYMBOLS else LARGE_CAP_CONFIGS)
        for symbol in symbols
    }
    for symbol in symbols:
        _print_symbol_header(symbol, args.start_date, args.end_date)

    tasks: List[Dict[str, object]] = []
    for symbol in symbols:
        for config in symbol_to_configs[symbol]:
            tasks.append(
                {
                    "symbol": symbol,
                    "start_date": args.start_date,
                    "end_date": args.end_date,
                    "config": config,
                }
            )

    effective_workers = max(1, min(args.workers, len(tasks)))
    print(f"\n使用 {effective_workers} 个 worker 并行处理 {len(tasks)} 个指数-参数任务...")

    completed_rows: List[Dict[str, object]] = []
    results_by_symbol: Dict[str, List[Dict[str, object]]] = {symbol: [] for symbol in symbols}
    remaining_by_symbol = {symbol: len(symbol_to_configs[symbol]) for symbol in symbols}

    if effective_workers == 1:
        for task in tasks:
            row = _evaluate_symbol_config(task)
            completed_rows.append(row)
            symbol = str(row["symbol"])
            results_by_symbol[symbol].append(row)
            remaining_by_symbol[symbol] -= 1
    else:
        with ProcessPoolExecutor(max_workers=effective_workers) as executor:
            future_to_task = {executor.submit(_evaluate_symbol_config, task): task for task in tasks}
            for future in as_completed(future_to_task):
                row = future.result()
                completed_rows.append(row)
                symbol = str(row["symbol"])
                results_by_symbol[symbol].append(row)
                remaining_by_symbol[symbol] -= 1
                print(
                    f"[完成] {symbol} {row['config_name']} | "
                    f"年化超额 {float(row.get('annualized_excess_return', 0.0)) * 100:.2f}% | "
                    f"回撤 {float(row.get('max_drawdown', 0.0)) * 100:.2f}% | "
                    f"剩余配置 {remaining_by_symbol[symbol]}"
                )

    all_results: List[pd.DataFrame] = []
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    for symbol in symbols:
        symbol_rows = results_by_symbol[symbol]
        if not symbol_rows:
            continue
        results_df = pd.DataFrame(symbol_rows)
        scored_df = _score_results(results_df, symbol)
        csv_path = output_dir / f"long_hold_results_{symbol}_{timestamp}.csv"
        scored_df.to_csv(csv_path, index=False)
        _print_symbol_summary(symbol, scored_df, csv_path)
        all_results.append(scored_df)

    if all_results:
        combined_df = pd.concat(all_results, ignore_index=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        combined_path = output_dir / f"long_hold_combined_{timestamp}.csv"
        combined_df.to_csv(combined_path, index=False)
        print(f"\n\n{'='*80}")
        print(f"所有结果已合并保存: {combined_path}")
        print(f"{'='*80}")
        
        # 打印总体摘要
        print(f"\n{'='*60}")
        print("总体测试摘要")
        print(f"{'='*60}")
        print(f"测试指数: {len(symbols)} 个")
        print(f"测试组合: {len(combined_df)} 个")
        print(f"通过策略: {combined_df['eligible'].sum()} / {len(combined_df)}")
        print(f"平均年化超额: {combined_df['annualized_excess_return'].mean()*100:.2f}%")
        print(f"平均最大回撤: {combined_df['max_drawdown'].mean()*100:.2f}%")
        print(f"平均持仓天数: {combined_df['avg_hold_days'].mean():.1f} 天")
        print(f"平均交易次数: {combined_df['trade_count'].mean():.1f}")
        print(f"平均换手率: {combined_df['turnover_rate'].mean():.2f}%")
    else:
        print("\n警告: 没有生成任何结果")


if __name__ == "__main__":
    main()
