# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import os
from datetime import datetime
from itertools import product
from typing import Dict, Iterable, List, Tuple

import pandas as pd

from src.cli.lppl_verify_v2 import SYMBOLS, create_config
from src.config import load_optimal_config, resolve_symbol_params
from src.constants import INDICES
from src.data.manager import DataManager
from src.investment import (
    BacktestConfig,
    InvestmentSignalConfig,
    generate_investment_signals,
    run_strategy_backtest,
    score_signal_tuning_results,
)
from src.reporting import Optimal8ReadableReportGenerator


def parse_float_list(value: str) -> List[float]:
    return [float(x.strip()) for x in value.split(",") if x.strip()]


def parse_int_list(value: str) -> List[int]:
    return [int(x.strip()) for x in value.split(",") if x.strip()]


def _resolve_requested_symbols(args: argparse.Namespace) -> List[str]:
    if getattr(args, "symbols", None):
        symbols = [item.strip() for item in str(args.symbols).split(",") if item.strip()]
    elif args.symbol:
        symbols = [args.symbol]
    elif args.all:
        symbols = list(INDICES.keys())
    else:
        raise SystemExit("请提供 --symbol、--symbols 或 --all")

    unknown = [symbol for symbol in symbols if symbol not in SYMBOLS]
    if unknown:
        raise SystemExit(f"未知指数代码: {unknown}")
    return symbols


def _fallback_config(base_step: int, use_ensemble: bool) -> Dict[str, object]:
    lppl_config = create_config(use_ensemble)
    lppl_config.optimizer = "lbfgsb" if lppl_config.optimizer == "de" else lppl_config.optimizer
    return {
        "step": base_step,
        "window_range": list(lppl_config.window_range),
        "r2_threshold": lppl_config.r2_threshold,
        "danger_r2_offset": lppl_config.danger_r2_offset,
        "consensus_threshold": lppl_config.consensus_threshold,
        "danger_days": lppl_config.danger_days,
        "warning_days": lppl_config.warning_days,
        "watch_days": lppl_config.watch_days,
        "optimizer": lppl_config.optimizer,
        "lookahead_days": 60,
        "drop_threshold": 0.10,
        "ma_window": 5,
        "max_peaks": 10,
        "signal_model": "multi_factor_v1",
        "initial_position": 0.0,
        "positive_consensus_threshold": lppl_config.consensus_threshold,
        "negative_consensus_threshold": max(0.10, lppl_config.consensus_threshold - 0.05),
        "rebound_days": lppl_config.danger_days,
        "trend_fast_ma": 20,
        "trend_slow_ma": 120,
        "trend_slope_window": 10,
        "atr_period": 14,
        "atr_ma_window": 60,
        "vol_breakout_mult": 1.05,
        "buy_volatility_cap": 1.05,
        "drawdown_confirm_threshold": 0.05,
        "buy_vote_threshold": 3,
        "sell_vote_threshold": 3,
        "buy_confirm_days": 2,
        "sell_confirm_days": 2,
        "cooldown_days": 15,
        "require_trend_recovery_for_buy": True,
    }


def _resolve_configs(
    symbol: str,
    optimal_config_path: str,
    base_step: int,
    use_ensemble: bool,
) -> Tuple[Dict[str, object], object]:
    lppl_config = create_config(use_ensemble)
    lppl_config.n_workers = 1
    lppl_config.optimizer = "lbfgsb" if lppl_config.optimizer == "de" else lppl_config.optimizer
    fallback = _fallback_config(base_step, use_ensemble)
    resolved = dict(fallback)
    try:
        optimal_data = load_optimal_config(optimal_config_path)
        resolved, warnings = resolve_symbol_params(optimal_data, symbol, fallback)
        for message in warnings:
            print(f"⚠️ {message}")
    except Exception as exc:
        print(f"⚠️ 最优参数文件加载失败，使用默认参数: {exc}")

    lppl_config.window_range = list(resolved["window_range"])
    lppl_config.optimizer = resolved["optimizer"]
    lppl_config.r2_threshold = resolved["r2_threshold"]
    lppl_config.danger_r2_offset = resolved["danger_r2_offset"]
    lppl_config.consensus_threshold = resolved["consensus_threshold"]
    lppl_config.danger_days = resolved["danger_days"]
    lppl_config.warning_days = resolved["warning_days"]
    lppl_config.watch_days = resolved["watch_days"]
    return resolved, lppl_config


def _candidate_grid(
    args: argparse.Namespace,
) -> Iterable[Tuple[float, float, int, int, int, int, float, float, int, float]]:
    return product(
        parse_float_list(args.positive_offsets),
        parse_float_list(args.negative_offsets),
        parse_int_list(args.sell_votes),
        parse_int_list(args.buy_votes),
        parse_int_list(args.sell_confirms),
        parse_int_list(args.buy_confirms),
        parse_float_list(args.vol_breakout_grid),
        parse_float_list(args.drawdown_grid),
        parse_int_list(args.cooldown_grid),
        parse_float_list(args.buy_volatility_cap_grid),
    )


def _run_single_symbol(
    symbol: str,
    args: argparse.Namespace,
    output_dir: str,
) -> Dict[str, object]:
    resolved, lppl_config = _resolve_configs(symbol, args.optimal_config_path, args.step, args.ensemble)

    dm = DataManager()
    df = dm.get_data(symbol)
    if df is None or df.empty:
        raise SystemExit(f"无法获取 {symbol} 数据")

    rows: List[Dict[str, object]] = []
    base_positive = float(resolved["positive_consensus_threshold"])
    base_negative = float(resolved["negative_consensus_threshold"])
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    for idx, candidate in enumerate(_candidate_grid(args), start=1):
        (
            positive_offset,
            negative_offset,
            sell_votes,
            buy_votes,
            sell_confirm_days,
            buy_confirm_days,
            vol_breakout_mult,
            drawdown_confirm_threshold,
            cooldown_days,
            buy_volatility_cap,
        ) = candidate
        candidate_mapping = dict(resolved)
        candidate_mapping.update(
            {
                "positive_consensus_threshold": min(max(base_positive + positive_offset, 0.05), 0.95),
                "negative_consensus_threshold": min(max(base_negative + negative_offset, 0.05), 0.95),
                "sell_vote_threshold": sell_votes,
                "buy_vote_threshold": buy_votes,
                "sell_confirm_days": sell_confirm_days,
                "buy_confirm_days": buy_confirm_days,
                "vol_breakout_mult": vol_breakout_mult,
                "drawdown_confirm_threshold": drawdown_confirm_threshold,
                "cooldown_days": cooldown_days,
                "buy_volatility_cap": buy_volatility_cap,
            }
        )
        signal_config = InvestmentSignalConfig.from_mapping(symbol, candidate_mapping)
        signal_df = generate_investment_signals(
            df=df,
            symbol=symbol,
            signal_config=signal_config,
            lppl_config=lppl_config,
            use_ensemble=args.ensemble,
            start_date=args.start_date,
            end_date=args.end_date,
            scan_step=int(resolved["step"]),
        )
        _, _, summary = run_strategy_backtest(
            signal_df,
            BacktestConfig(
                initial_capital=args.initial_capital,
                buy_fee=args.buy_fee,
                sell_fee=args.sell_fee,
                slippage=args.slippage,
                start_date=args.start_date,
                end_date=args.end_date,
            ),
        )
        rows.append(
            {
                "run_id": idx,
                "symbol": symbol,
                "name": INDICES[symbol],
                "mode": "ensemble" if args.ensemble else "single_window",
                "window_count": len(lppl_config.window_range),
                "window_min": min(lppl_config.window_range),
                "window_max": max(lppl_config.window_range),
                "step": int(resolved["step"]),
                "positive_consensus_threshold": candidate_mapping["positive_consensus_threshold"],
                "negative_consensus_threshold": candidate_mapping["negative_consensus_threshold"],
                "sell_vote_threshold": sell_votes,
                "buy_vote_threshold": buy_votes,
                "sell_confirm_days": sell_confirm_days,
                "buy_confirm_days": buy_confirm_days,
                "vol_breakout_mult": vol_breakout_mult,
                "drawdown_confirm_threshold": drawdown_confirm_threshold,
                "cooldown_days": cooldown_days,
                "buy_volatility_cap": buy_volatility_cap,
                **summary,
            }
        )

    scored = score_signal_tuning_results(
        pd.DataFrame(rows),
        min_trade_count=args.min_trades,
        max_drawdown_cap=args.max_drawdown_cap,
        turnover_cap=args.turnover_cap,
        whipsaw_cap=args.whipsaw_cap,
        scoring_profile=args.scoring_profile,
    )
    raw_dir = os.path.join(output_dir, "raw")
    summary_dir = os.path.join(output_dir, "summary")
    os.makedirs(raw_dir, exist_ok=True)
    os.makedirs(summary_dir, exist_ok=True)

    symbol_slug = symbol.replace(".", "_")
    csv_path = os.path.join(summary_dir, f"signal_tuning_{symbol_slug}_{stamp}.csv")
    md_path = os.path.join(summary_dir, f"signal_tuning_{symbol_slug}_{stamp}.md")
    scored.to_csv(csv_path, index=False)

    top_n = min(10, len(scored))
    top_columns = [
        "symbol",
        "objective_score",
        "annualized_excess_return",
        "calmar_ratio",
        "max_drawdown",
        "trade_count",
        "turnover_rate",
        "whipsaw_rate",
        "positive_consensus_threshold",
        "negative_consensus_threshold",
        "sell_vote_threshold",
        "buy_vote_threshold",
        "sell_confirm_days",
        "buy_confirm_days",
        "vol_breakout_mult",
        "drawdown_confirm_threshold",
        "cooldown_days",
        "buy_volatility_cap",
        "reject_reason",
    ]
    with open(md_path, "w", encoding="utf-8") as handle:
        handle.write(
            "\n".join(
                [
                    f"# {symbol} 信号调优结果",
                    "",
                    f"- 运行模式: {'ensemble' if args.ensemble else 'single_window'}",
                    f"- 参数组合数: {len(scored)}",
                    "",
                    scored[top_columns].head(top_n).to_markdown(index=False),
                ]
            )
        )

    print(f"{symbol} 调优结果已保存: {csv_path}")
    return scored.iloc[0].to_dict()


def main() -> None:
    parser = argparse.ArgumentParser(description="指数买卖信号调优工具")
    parser.add_argument("--symbol", help="单个指数代码")
    parser.add_argument("--symbols", help="多个指数代码，逗号分隔")
    parser.add_argument("--all", action="store_true", help="对全部 8 个指数调优")
    parser.add_argument("--ensemble", action="store_true", help="使用 Ensemble 模式")
    parser.add_argument("--start-date", help="回测起始日期 YYYY-MM-DD")
    parser.add_argument("--end-date", help="回测结束日期 YYYY-MM-DD")
    parser.add_argument("--step", type=int, default=5, help="回退步长，仅在 YAML 缺失时生效")
    parser.add_argument("--initial-capital", type=float, default=1_000_000.0, help="初始资金")
    parser.add_argument("--buy-fee", type=float, default=0.0003, help="买入手续费")
    parser.add_argument("--sell-fee", type=float, default=0.0003, help="卖出手续费")
    parser.add_argument("--slippage", type=float, default=0.0005, help="滑点")
    parser.add_argument("--output", default="output/signal_tuning", help="输出目录")
    parser.add_argument(
        "--optimal-config-path",
        default="config/optimal_params.yaml",
        help="最优参数 YAML 路径",
    )
    parser.add_argument("--positive-offsets", default="-0.05,0.00,0.05", help="顶部共识阈值偏移")
    parser.add_argument("--negative-offsets", default="0.00,0.05", help="底部共识阈值偏移")
    parser.add_argument("--sell-votes", default="2,3", help="卖出投票门槛")
    parser.add_argument("--buy-votes", default="3", help="买入投票门槛")
    parser.add_argument("--sell-confirms", default="1,2", help="卖出确认天数")
    parser.add_argument("--buy-confirms", default="2,3", help="买入确认天数")
    parser.add_argument("--vol-breakout-grid", default="1.02,1.05,1.08", help="ATR 突破阈值")
    parser.add_argument("--drawdown-grid", default="0.05,0.08,0.10", help="回撤确认阈值")
    parser.add_argument("--cooldown-grid", default="10,15", help="冷却期天数")
    parser.add_argument("--buy-volatility-cap-grid", default="1.00,1.05", help="买入波动率上限")
    parser.add_argument(
        "--scoring-profile",
        default="balanced",
        choices=["balanced", "signal_release", "risk_reduction"],
        help="评分偏好",
    )
    parser.add_argument("--min-trades", type=int, default=3, help="最少交易次数")
    parser.add_argument("--max-drawdown-cap", type=float, default=-0.35, help="最大回撤硬门槛")
    parser.add_argument("--turnover-cap", type=float, default=8.0, help="换手率硬门槛")
    parser.add_argument("--whipsaw-cap", type=float, default=0.35, help="反复打脸率硬门槛")
    args = parser.parse_args()

    symbols = _resolve_requested_symbols(args)
    os.makedirs(args.output, exist_ok=True)

    best_rows = []
    for symbol in symbols:
        best_rows.append(_run_single_symbol(symbol, args, args.output))

    if len(best_rows) > 1:
        combined_df = pd.DataFrame(best_rows).sort_values("objective_score", ascending=False).reset_index(drop=True)
        summary_dir = os.path.join(args.output, "summary")
        report_dir = os.path.join(args.output, "reports")
        plot_dir = os.path.join(args.output, "plots")
        os.makedirs(summary_dir, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        combined_csv = os.path.join(summary_dir, f"optimal8_signal_tuning_summary_{stamp}.csv")
        combined_df.to_csv(combined_csv, index=False)
        report_generator = Optimal8ReadableReportGenerator(report_dir=report_dir, plot_dir=plot_dir)
        report_outputs = report_generator.generate(combined_csv, output_stem="optimal8_signal_tuning_report")
        print(f"8指数汇总已保存: {combined_csv}")
        print(f"8指数报告已保存: {report_outputs['report_path']}")


if __name__ == "__main__":
    main()
