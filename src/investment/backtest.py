# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

import pandas as pd

from src.lppl_core import calculate_bottom_signal_strength, detect_negative_bubble
from src.lppl_engine import LPPLConfig, process_single_day_ensemble, scan_single_date


@dataclass
class InvestmentSignalConfig:
    full_position: float = 1.0
    half_position: float = 0.5
    flat_position: float = 0.0
    strong_buy_days: int = 20
    buy_days: int = 40
    strong_sell_days: int = 20
    reduce_days: int = 60


@dataclass
class BacktestConfig:
    initial_capital: float = 1_000_000.0
    buy_fee: float = 0.0003
    sell_fee: float = 0.0003
    slippage: float = 0.0005
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    execution_price: str = "open"


def _normalize_price_frame(df: pd.DataFrame) -> pd.DataFrame:
    normalized = df.copy()
    normalized["date"] = pd.to_datetime(normalized["date"])
    normalized = normalized.sort_values("date").reset_index(drop=True)

    if "open" not in normalized.columns:
        normalized["open"] = normalized["close"]
    if "high" not in normalized.columns:
        normalized["high"] = normalized[["open", "close"]].max(axis=1)
    if "low" not in normalized.columns:
        normalized["low"] = normalized[["open", "close"]].min(axis=1)
    if "volume" not in normalized.columns:
        normalized["volume"] = 0.0

    return normalized


def _resolve_action(previous_target: float, next_target: float) -> str:
    if next_target > previous_target:
        return "buy" if previous_target <= 0.0 else "add"
    if next_target < previous_target:
        return "sell" if next_target <= 0.0 else "reduce"
    return "hold"


def _map_single_window_signal(
    result: Optional[Dict[str, Any]],
    current_target: float,
    signal_config: InvestmentSignalConfig,
    lppl_config: LPPLConfig,
) -> Tuple[str, float, str, float]:
    if not result:
        return "none", 0.0, "无信号", current_target

    params = result.get("params", ())
    b_value = float(params[4]) if len(params) > 4 else 0.0
    days_to_crash = float(result.get("days_to_crash", 9999.0))
    m_value = float(result.get("m", 0.0))
    w_value = float(result.get("w", 0.0))
    rmse = float(result.get("rmse", 1.0))
    r_squared = float(result.get("r_squared", 0.0))

    is_negative, bottom_signal = detect_negative_bubble(m_value, w_value, b_value, days_to_crash)
    if is_negative:
        bottom_strength = calculate_bottom_signal_strength(m_value, w_value, b_value, rmse)
        if days_to_crash < signal_config.strong_buy_days:
            return "negative_bubble", bottom_strength, bottom_signal, signal_config.full_position
        if days_to_crash < signal_config.buy_days:
            target = max(current_target, signal_config.half_position)
            return "negative_bubble", bottom_strength, bottom_signal, target
        return "negative_bubble_watch", bottom_strength, bottom_signal, current_target

    if b_value <= 0 and days_to_crash < lppl_config.danger_days and r_squared >= lppl_config.r2_threshold:
        return "bubble_risk", r_squared, "高危信号", signal_config.flat_position

    warning_threshold = max(0.0, lppl_config.r2_threshold - 0.1)
    if b_value <= 0 and days_to_crash < lppl_config.warning_days and r_squared >= warning_threshold:
        target = min(current_target, signal_config.half_position)
        return "bubble_warning", r_squared, "观察信号", target

    return "none", 0.0, "无信号", current_target


def _map_ensemble_signal(
    result: Optional[Dict[str, Any]],
    current_target: float,
    signal_config: InvestmentSignalConfig,
    lppl_config: LPPLConfig,
) -> Tuple[str, float, str, float]:
    if not result:
        return "none", 0.0, "无信号", current_target

    signal_strength = float(result.get("signal_strength", 0.0))
    positive_consensus = float(result.get("positive_consensus_rate", result.get("consensus_rate", 0.0)))
    negative_consensus = float(result.get("negative_consensus_rate", 0.0))
    positive_days = result.get("predicted_crash_days")
    negative_days = result.get("predicted_rebound_days")

    if negative_days is not None and negative_consensus > positive_consensus:
        negative_days = float(negative_days)
        if negative_days < signal_config.strong_buy_days:
            return "negative_bubble", signal_strength, "Ensemble 抄底共识", signal_config.full_position
        if negative_days < signal_config.buy_days:
            target = max(current_target, signal_config.half_position)
            return "negative_bubble", signal_strength, "Ensemble 抄底共识", target
        return "negative_bubble_watch", signal_strength, "Ensemble 抄底观察", current_target

    if positive_days is not None:
        positive_days = float(positive_days)
        if positive_days < lppl_config.danger_days:
            return "bubble_risk", signal_strength, "Ensemble 高危共识", signal_config.flat_position
        if positive_days < lppl_config.warning_days:
            target = min(current_target, signal_config.half_position)
            return "bubble_warning", signal_strength, "Ensemble 观察信号", target

    return "none", 0.0, "无信号", current_target


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
    signal_config = signal_config or InvestmentSignalConfig()
    lppl_config = lppl_config or LPPLConfig(window_range=[40, 60, 80], n_workers=1)
    price_df = _normalize_price_frame(df)
    scan_step = max(1, int(scan_step))

    start_ts = pd.to_datetime(start_date) if start_date else price_df["date"].min()
    end_ts = pd.to_datetime(end_date) if end_date else price_df["date"].max()
    output_mask = (price_df["date"] >= start_ts) & (price_df["date"] <= end_ts)

    current_target = signal_config.flat_position
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
                lppl_signal, signal_strength, position_reason, next_target = _map_ensemble_signal(
                    result,
                    current_target,
                    signal_config,
                    lppl_config,
                )
            else:
                result = scan_single_date(close_prices, idx, lppl_config.window_range, lppl_config)
                lppl_signal, signal_strength, position_reason, next_target = _map_single_window_signal(
                    result,
                    current_target,
                    signal_config,
                    lppl_config,
                )
        if idx >= warmup:
            scan_counter += 1

        action = _resolve_action(current_target, next_target)
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


def summarize_strategy_performance(equity_df: pd.DataFrame, trades_df: pd.DataFrame) -> Dict[str, Any]:
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
    backtest_config = backtest_config or BacktestConfig()
    equity_df = _normalize_price_frame(signal_df)

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
