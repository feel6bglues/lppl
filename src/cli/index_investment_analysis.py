# -*- coding: utf-8 -*-
import argparse
import os
from typing import Dict

import pandas as pd

from src.cli.lppl_verify_v2 import SYMBOLS, create_config
from src.config import load_optimal_config, resolve_symbol_params
from src.data.manager import DataManager
from src.investment import (
    BacktestConfig,
    InvestmentSignalConfig,
    generate_investment_signals,
    run_strategy_backtest,
)
from src.reporting import InvestmentReportGenerator, PlotGenerator


def resolve_output_dirs(base_output_dir: str) -> Dict[str, str]:
    return {
        "base": base_output_dir,
        "raw": os.path.join(base_output_dir, "raw"),
        "plots": os.path.join(base_output_dir, "plots"),
        "reports": os.path.join(base_output_dir, "reports"),
        "summary": os.path.join(base_output_dir, "summary"),
    }


def ensure_output_dirs(output_dirs: Dict[str, str]) -> None:
    for path in output_dirs.values():
        os.makedirs(path, exist_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="指数投资分析引擎")
    parser.add_argument("--symbol", "-s", default="000001.SH", help="指数代码")
    parser.add_argument("--ensemble", "-e", action="store_true", help="使用 Ensemble 模式")
    parser.add_argument("--start-date", help="回测起始日期 YYYY-MM-DD")
    parser.add_argument("--end-date", help="回测结束日期 YYYY-MM-DD")
    parser.add_argument("--step", type=int, default=5, help="扫描步长")
    parser.add_argument("--initial-capital", type=float, default=1_000_000.0, help="初始资金")
    parser.add_argument("--buy-fee", type=float, default=0.0003, help="买入手续费")
    parser.add_argument("--sell-fee", type=float, default=0.0003, help="卖出手续费")
    parser.add_argument("--slippage", type=float, default=0.0005, help="滑点")
    parser.add_argument("--output", "-o", default="output/investment", help="输出目录")
    parser.add_argument(
        "--use-optimal-config",
        action="store_true",
        help="按指数从 YAML 读取最优 LPPL 参数",
    )
    parser.add_argument(
        "--optimal-config-path",
        default="config/optimal_params.yaml",
        help="最优参数 YAML 路径",
    )
    args = parser.parse_args()

    if args.symbol not in SYMBOLS:
        raise SystemExit(f"未知指数代码: {args.symbol}")

    output_dirs = resolve_output_dirs(args.output)
    ensure_output_dirs(output_dirs)

    data_manager = DataManager()
    df = data_manager.get_data(args.symbol)
    if df is None or df.empty:
        raise SystemExit(f"无法获取 {args.symbol} 数据")

    lppl_config = create_config(args.ensemble)
    lppl_config.n_workers = 1
    lppl_config.optimizer = "lbfgsb" if lppl_config.optimizer == "de" else lppl_config.optimizer
    param_source = "default_cli"

    if args.use_optimal_config:
        fallback = {
            "step": args.step,
            "window_range": list(lppl_config.window_range),
            "r2_threshold": lppl_config.r2_threshold,
            "consensus_threshold": lppl_config.consensus_threshold,
            "danger_days": lppl_config.danger_days,
            "warning_days": lppl_config.warning_days,
            "optimizer": lppl_config.optimizer,
            "lookahead_days": 60,
            "drop_threshold": 0.10,
            "ma_window": 5,
            "max_peaks": 10,
        }
        optimal_data = load_optimal_config(args.optimal_config_path)
        resolved, warnings = resolve_symbol_params(optimal_data, args.symbol, fallback)
        for message in warnings:
            print(f"⚠️ {message}")

        lppl_config.window_range = list(resolved["window_range"])
        lppl_config.optimizer = resolved["optimizer"]
        lppl_config.r2_threshold = resolved["r2_threshold"]
        lppl_config.consensus_threshold = resolved["consensus_threshold"]
        lppl_config.danger_days = resolved["danger_days"]
        lppl_config.warning_days = resolved["warning_days"]
        args.step = resolved["step"]
        param_source = resolved["param_source"]

    signal_df = generate_investment_signals(
        df=df,
        symbol=args.symbol,
        signal_config=InvestmentSignalConfig(),
        lppl_config=lppl_config,
        use_ensemble=args.ensemble,
        start_date=args.start_date,
        end_date=args.end_date,
        scan_step=args.step,
    )
    signal_df["param_source"] = param_source

    equity_df, trades_df, summary = run_strategy_backtest(
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

    summary["name"] = SYMBOLS[args.symbol]
    summary["mode"] = "ensemble" if args.ensemble else "single_window"
    summary["param_source"] = param_source
    summary["step"] = args.step
    summary_df = pd.DataFrame([summary])

    mode_slug = "ensemble" if args.ensemble else "single_window"
    symbol_slug = args.symbol.replace(".", "_")

    signals_path = os.path.join(output_dirs["raw"], f"signals_{symbol_slug}_{mode_slug}.csv")
    equity_path = os.path.join(output_dirs["raw"], f"equity_{symbol_slug}_{mode_slug}.csv")
    trades_path = os.path.join(output_dirs["raw"], f"trades_{symbol_slug}_{mode_slug}.csv")
    summary_path = os.path.join(output_dirs["summary"], f"summary_{symbol_slug}_{mode_slug}.csv")

    signal_df.to_csv(signals_path, index=False)
    equity_df.to_csv(equity_path, index=False)
    trades_df.to_csv(trades_path, index=False)
    summary_df.to_csv(summary_path, index=False)

    plot_generator = PlotGenerator(output_dir=output_dirs["plots"])
    metadata = {
        "symbol": args.symbol,
        "name": SYMBOLS[args.symbol],
        "start_date": summary["start_date"],
        "end_date": summary["end_date"],
        "max_drawdown": summary["max_drawdown"],
        "total_return": summary["total_return"],
    }
    overview_path = plot_generator.generate_strategy_overview_plot(equity_df, trades_df, metadata)
    drawdown_path = plot_generator.generate_strategy_drawdown_plot(equity_df, metadata)

    report_generator = InvestmentReportGenerator(output_dir=output_dirs["reports"])
    plot_paths = {"核心图表": [overview_path, drawdown_path]}
    markdown_path = report_generator.generate_markdown_report(summary_df, plot_paths)
    html_path = report_generator.generate_html_report(summary_df, plot_paths)

    print(f"逐日信号已保存: {signals_path}")
    print(f"净值明细已保存: {equity_path}")
    print(f"交易流水已保存: {trades_path}")
    print(f"汇总统计已保存: {summary_path}")
    print(f"Markdown 报告已保存: {markdown_path}")
    print(f"HTML 报告已保存: {html_path}")


if __name__ == "__main__":
    main()
