# -*- coding: utf-8 -*-
"""
DEPRECATED — 请使用 backtest.py 替代。

本文件保留仅为参考。所有生产代码和测试均通过 backtest.py 进入。
若需新增功能或修复缺陷，请修改 backtest.py 而非本文件。
"""

from __future__ import annotations

import warnings

warnings.warn(
    "backtest_engine.py is deprecated. Use backtest.py instead.",
    DeprecationWarning,
    stacklevel=2,
)

from typing import Any, Dict, Optional, Tuple

import pandas as pd

from src.lppl_engine import LPPLConfig, process_single_day_ensemble, scan_single_date

from .config import BacktestConfig, InvestmentSignalConfig
from .indicators import compute_indicators, normalize_price_frame
from .signal_models import (
    evaluate_multi_factor_adaptive,
    map_ensemble_signal,
    map_single_window_signal,
    resolve_action,
)


def generate_investment_signals(
    df: pd.DataFrame,
    symbol: str,
    signal_config: Optional[InvestmentSignalConfig] = None,
    lppl_config: Optional[LPPLConfig] = None,
    use_ensemble: bool = False,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    scan_step: int = 1,
) -> pd.DataFrame:
    """Generate investment signals based on configured signal model.

    Supports:
    - legacy: LPPL single-window signals
    - multi_factor_adaptive_v1: Weighted multi-factor scoring
    """
    signal_config = signal_config or InvestmentSignalConfig()
    lppl_config = lppl_config or LPPLConfig(window_range=[40, 60, 80], n_workers=1)

    # Check if this is a multi-factor adaptive model
    is_multi_factor = signal_config.signal_model == "multi_factor_adaptive_v1"

    if is_multi_factor:
        price_df = compute_indicators(normalize_price_frame(df), signal_config)
    else:
        price_df = normalize_price_frame(df)

    scan_step = max(1, int(scan_step))

    start_ts = pd.to_datetime(start_date) if start_date else price_df["date"].min()
    end_ts = pd.to_datetime(end_date) if end_date else price_df["date"].max()
    output_mask = (price_df["date"] >= start_ts) & (price_df["date"] <= end_ts)

    current_target = signal_config.initial_position
    records = []
    close_prices = price_df["close"].values
    warmup = max(lppl_config.window_range)
    scan_counter = 0

    for idx, row in price_df.iterrows():
        if not output_mask.iloc[idx]:
            continue

        lppl_signal = "none"
        signal_strength = 0.0
        position_reason = "无信号"
        next_target = current_target

        if is_multi_factor:
            # Multi-factor adaptive model
            next_target, position_reason = evaluate_multi_factor_adaptive(row, signal_config, current_target)
        else:
            # Legacy LPPL model
            if idx >= warmup and scan_counter % scan_step == 0:
                if use_ensemble:
                    result = process_single_day_ensemble(
                        close_prices,
                        idx,
                        lppl_config.window_range,
                        min_r2=lppl_config.r2_threshold,
                        consensus_threshold=lppl_config.consensus_threshold,
                        config=lppl_config,
                    )
                    lppl_signal, signal_strength, position_reason, next_target = map_ensemble_signal(
                        result,
                        current_target,
                        signal_config,
                        lppl_config,
                    )
                else:
                    result = scan_single_date(close_prices, idx, lppl_config.window_range, lppl_config)
                    lppl_signal, signal_strength, position_reason, next_target = map_single_window_signal(
                        result,
                        current_target,
                        signal_config,
                        lppl_config,
                    )
            if idx >= warmup:
                scan_counter += 1

        action = resolve_action(current_target, next_target)
        current_target = next_target

        records.append(
            {
                "date": row["date"],
                "symbol": symbol,
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": float(row["volume"]),
                "lppl_signal": lppl_signal,
                "signal_strength": float(signal_strength),
                "position_reason": position_reason,
                "action": action,
                "target_position": float(current_target),
            }
        )

    return pd.DataFrame(records)


def calculate_drawdown(nav_series: pd.Series) -> pd.DataFrame:
    """Calculate drawdown from NAV series."""
    nav = pd.Series(nav_series, copy=True).astype(float).reset_index(drop=True)
    running_max = nav.cummax()
    drawdown = (nav / running_max) - 1.0
    return pd.DataFrame(
        {
            "strategy_nav": nav,
            "running_max": running_max,
            "drawdown": drawdown,
        }
    )


def summarize_strategy_performance(
    equity_df: pd.DataFrame,
    trades_df: pd.DataFrame,
) -> Dict[str, Any]:
    """Summarize strategy performance metrics."""
    if equity_df.empty:
        return {
            "final_nav": 1.0,
            "total_return": 0.0,
            "benchmark_return": 0.0,
            "annualized_return": 0.0,
            "max_drawdown": 0.0,
            "trade_count": 0,
            "signal_count": 0,
            "average_position": 0.0,
            "latest_action": "hold",
            "latest_signal": "none",
        }

    final_nav = float(equity_df["strategy_nav"].iloc[-1])
    total_return = final_nav - 1.0
    benchmark_return = float(equity_df["benchmark_nav"].iloc[-1] - 1.0)
    periods = max(len(equity_df), 1)
    annualized_return = (final_nav ** (252.0 / periods) - 1.0) if final_nav > 0 else -1.0
    max_drawdown = float(equity_df["drawdown"].min())
    signal_count = int((equity_df["action"] != "hold").sum())

    return {
        "final_nav": final_nav,
        "total_return": total_return,
        "benchmark_return": benchmark_return,
        "annualized_return": annualized_return,
        "max_drawdown": max_drawdown,
        "trade_count": int(len(trades_df)),
        "signal_count": signal_count,
        "average_position": float(equity_df["executed_position"].mean()),
        "latest_action": str(equity_df["action"].iloc[-1]),
        "latest_signal": str(equity_df["lppl_signal"].iloc[-1]),
    }


def run_strategy_backtest(
    signal_df: pd.DataFrame,
    backtest_config: Optional[BacktestConfig] = None,
) -> Tuple[pd.DataFrame, pd.DataFrame, Dict[str, Any]]:
    """Run strategy backtest on signal DataFrame.

    Returns:
        Tuple of (equity_df, trades_df, summary_dict)
    """
    backtest_config = backtest_config or BacktestConfig()
    equity_df = normalize_price_frame(signal_df)

    if backtest_config.start_date:
        equity_df = equity_df[equity_df["date"] >= pd.to_datetime(backtest_config.start_date)]
    if backtest_config.end_date:
        equity_df = equity_df[equity_df["date"] <= pd.to_datetime(backtest_config.end_date)]
    equity_df = equity_df.reset_index(drop=True)

    if equity_df.empty:
        raise ValueError("No data available for the requested backtest window")

    cash = float(backtest_config.initial_capital)
    units = 0.0
    prev_value = float(backtest_config.initial_capital)
    prev_close = float(equity_df.iloc[0]["close"])
    first_close = float(equity_df.iloc[0]["close"])

    trades = []
    records = []

    for row in equity_df.to_dict("records"):
        execution_base_price = float(row["open"] if backtest_config.execution_price == "open" else row["close"])
        execution_buy_price = execution_base_price * (1.0 + backtest_config.slippage)
        execution_sell_price = execution_base_price * (1.0 - backtest_config.slippage)
        target_position = float(row.get("target_position", 0.0))

        portfolio_value_before_trade = cash + units * execution_base_price
        current_holdings_value = units * execution_base_price
        desired_holdings_value = portfolio_value_before_trade * target_position

        trade_type = "hold"
        if desired_holdings_value > current_holdings_value + 1e-8:
            trade_value = desired_holdings_value - current_holdings_value
            affordable_units = cash / (execution_buy_price * (1.0 + backtest_config.buy_fee))
            desired_units = trade_value / execution_buy_price
            units_to_buy = min(affordable_units, desired_units)
            if units_to_buy > 1e-8:
                gross_cost = units_to_buy * execution_buy_price
                fee = gross_cost * backtest_config.buy_fee
                cash -= gross_cost + fee
                units += units_to_buy
                trade_type = "buy" if current_holdings_value <= 1e-8 else "add"
                trades.append(
                    {
                        "date": row["date"],
                        "symbol": row.get("symbol", ""),
                        "trade_type": trade_type,
                        "price": execution_buy_price,
                        "target_position": target_position,
                        "executed_position": 0.0,
                        "units": units_to_buy,
                        "cash_after_trade": cash,
                        "portfolio_value_after_trade": cash + units * execution_base_price,
                    }
                )
        elif desired_holdings_value < current_holdings_value - 1e-8:
            trade_value = current_holdings_value - desired_holdings_value
            units_to_sell = min(units, trade_value / execution_sell_price)
            if units_to_sell > 1e-8:
                gross_proceeds = units_to_sell * execution_sell_price
                fee = gross_proceeds * backtest_config.sell_fee
                cash += gross_proceeds - fee
                units -= units_to_sell
                trade_type = "sell" if target_position <= 1e-8 else "reduce"
                trades.append(
                    {
                        "date": row["date"],
                        "symbol": row.get("symbol", ""),
                        "trade_type": trade_type,
                        "price": execution_sell_price,
                        "target_position": target_position,
                        "executed_position": 0.0,
                        "units": units_to_sell,
                        "cash_after_trade": cash,
                        "portfolio_value_after_trade": cash + units * execution_base_price,
                    }
                )

        holdings_value = units * float(row["close"])
        portfolio_value = cash + holdings_value
        strategy_nav = portfolio_value / backtest_config.initial_capital
        benchmark_nav = float(row["close"]) / first_close
        daily_return = 0.0 if not records else (portfolio_value / prev_value) - 1.0
        benchmark_return = 0.0 if not records else (float(row["close"]) / prev_close) - 1.0
        executed_position = (holdings_value / portfolio_value) if portfolio_value > 0 else 0.0

        if trades and pd.Timestamp(trades[-1]["date"]) == pd.Timestamp(row["date"]):
            trades[-1]["executed_position"] = executed_position

        records.append(
            {
                **row,
                "executed_position": executed_position,
                "cash": cash,
                "units": units,
                "holdings_value": holdings_value,
                "portfolio_value": portfolio_value,
                "strategy_nav": strategy_nav,
                "benchmark_nav": benchmark_nav,
                "daily_return": daily_return,
                "benchmark_return": benchmark_return,
                "excess_return": daily_return - benchmark_return,
                "trade_flag": trade_type != "hold",
            }
        )

        prev_value = portfolio_value
        prev_close = float(row["close"])

    result_df = pd.DataFrame(records)
    drawdown_df = calculate_drawdown(result_df["strategy_nav"])
    result_df["running_max"] = drawdown_df["running_max"]
    result_df["drawdown"] = drawdown_df["drawdown"]

    trades_df = pd.DataFrame(trades)
    summary = summarize_strategy_performance(result_df, trades_df)
    summary["start_date"] = result_df.iloc[0]["date"].strftime("%Y-%m-%d")
    summary["end_date"] = result_df.iloc[-1]["date"].strftime("%Y-%m-%d")
    summary["symbol"] = str(result_df.iloc[0].get("symbol", ""))

    return result_df, trades_df, summary
