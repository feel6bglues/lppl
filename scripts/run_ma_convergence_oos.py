# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
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

HIGH_BETA_SYMBOLS = {"399006.SZ", "000852.SH", "932000.SH"}


def _build_signal_config(row: pd.Series) -> InvestmentSignalConfig:
    return InvestmentSignalConfig(
        signal_model="ma_convergence_atr_v1",
        initial_position=0.0,
        bb_period=int(row["bb_period"]),
        bb_std=float(row["bb_std"]),
        bb_width_cap=float(row["bb_width_cap"]),
        atr_period=int(row["atr_period"]),
        atr_ma_window=int(row["atr_ma_window"]),
        atr_low_percentile=float(row["atr_low_percentile"]),
        atr_high_percentile=float(row["atr_high_percentile"]),
        atr_percentile_window=int(row["atr_percentile_window"]),
        ma_short=int(row["ma_short"]),
        ma_mid=int(row["ma_mid"]),
        ma_long=int(row["ma_long"]),
        regime_filter_ma=int(row["regime_filter_ma"]),
        regime_filter_buffer=float(row["regime_filter_buffer"]),
        regime_filter_reduce_enabled=True,
        risk_drawdown_stop_threshold=float(row["risk_drawdown_stop_threshold"]),
        risk_drawdown_lookback=int(row["risk_drawdown_lookback"]),
        buy_confirm_days=int(row["confirm_days"]),
        sell_confirm_days=int(row["confirm_days"]),
        cooldown_days=int(row["cooldown_days"]),
        min_hold_bars=int(row["min_hold_bars"]),
    )


def _score(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    max_dd_cap = -0.40 if symbol in HIGH_BETA_SYMBOLS else -0.35
    return score_signal_tuning_results(
        df,
        min_trade_count=3,
        max_drawdown_cap=max_dd_cap,
        turnover_cap=12.0,
        whipsaw_cap=0.50,
        scoring_profile="balanced",
        hard_reject=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="MA Convergence 固定参数 OOS 盲测")
    parser.add_argument(
        "--params-csv",
        default="output/retest_20260401/ma_convergence_retry/summary/ma_convergence_stage5_best_20260401_163821.csv",
    )
    parser.add_argument("--start-date", default="2021-01-01")
    parser.add_argument("--end-date", default="2025-12-31")
    parser.add_argument("--output", default="output/retest_20260401/ma_convergence_oos")
    args = parser.parse_args()

    params_df = pd.read_csv(args.params_csv)
    symbols = [str(x) for x in params_df["symbol"].tolist()]

    out_dir = Path(args.output)
    summary_dir = out_dir / "summary"
    reports_dir = out_dir / "reports"
    raw_dir = out_dir / "raw"
    summary_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)

    manager = DataManager()
    rows: List[Dict[str, object]] = []

    for _, row in params_df.iterrows():
        symbol = str(row["symbol"])
        print(f"[OOS] {symbol}", flush=True)
        df = manager.get_data(symbol)
        if df is None or df.empty:
            print(f"SKIP {symbol}: empty data", flush=True)
            continue

        signal_config = _build_signal_config(row)
        signal_df = generate_investment_signals(
            df=df,
            symbol=symbol,
            signal_config=signal_config,
            lppl_config=LPPLConfig(window_range=[20], n_workers=1),
            use_ensemble=False,
            start_date=args.start_date,
            end_date=args.end_date,
            scan_step=1,
        )
        equity_df, trades_df, summary = run_strategy_backtest(
            signal_df,
            BacktestConfig(
                initial_capital=1_000_000.0,
                buy_fee=0.0003,
                sell_fee=0.0003,
                slippage=0.0005,
                start_date=args.start_date,
                end_date=args.end_date,
            ),
        )
        result_row = {
            "symbol": symbol,
            "name": SYMBOLS[symbol],
            **row.to_dict(),
            **summary,
        }
        scored = _score(pd.DataFrame([result_row]), symbol)
        final_row = scored.iloc[0].to_dict()
        rows.append(final_row)

        symbol_slug = symbol.replace(".", "_")
        signal_df.to_csv(raw_dir / f"signals_{symbol_slug}.csv", index=False)
        equity_df.to_csv(raw_dir / f"equity_{symbol_slug}.csv", index=False)
        trades_df.to_csv(raw_dir / f"trades_{symbol_slug}.csv", index=False)
        print(
            f"[OOS-BEST] {symbol} excess={float(final_row['annualized_excess_return']):.4f} "
            f"mdd={float(final_row['max_drawdown']):.4f} trades={int(final_row['trade_count'])} "
            f"eligible={bool(final_row['eligible'])}",
            flush=True,
        )

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    summary_df = pd.DataFrame(rows)
    summary_path = summary_dir / f"ma_convergence_oos_best_{stamp}.csv"
    summary_df.to_csv(summary_path, index=False)

    report_lines = [
        "# MA Convergence 固定参数 OOS 盲测",
        "",
        f"- 参数来源: `{args.params_csv}`",
        f"- OOS 区间: {args.start_date} 到 {args.end_date}",
        f"- 指数数量: {len(summary_df)}",
        "",
    ]
    for row in summary_df.sort_values("annualized_excess_return", ascending=False).to_dict("records"):
        report_lines.extend(
            [
                f"## {row['symbol']} {row['name']}",
                f"- annualized_excess_return: {float(row['annualized_excess_return']):.4%}",
                f"- max_drawdown: {float(row['max_drawdown']):.4%}",
                f"- trade_count: {int(row['trade_count'])}",
                f"- annualized_turnover_rate: {float(row.get('annualized_turnover_rate', 0.0)):.4f}",
                f"- whipsaw_rate: {float(row.get('whipsaw_rate', 0.0)):.4f}",
                f"- eligible: {bool(row['eligible'])}",
                "",
            ]
        )
    report_path = reports_dir / f"ma_convergence_oos_report_{stamp}.md"
    report_path.write_text("\n".join(report_lines), encoding="utf-8")
    print(f"SAVED {summary_path}")
    print(f"SAVED {report_path}")


if __name__ == "__main__":
    main()
