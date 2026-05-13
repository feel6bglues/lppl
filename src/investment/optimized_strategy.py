# -*- coding: utf-8 -*-
"""MA+ATR优化策略 - 平衡交易频率与收益"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

import pandas as pd


@dataclass
class OptimizedSignalConfig:
    """优化策略配置 - 基于有效因子提取"""

    # 基础仓位
    full_position: float = 1.0
    half_position: float = 0.5
    flat_position: float = 0.0
    initial_position: float = 0.0

    # MA均线参数 (主信号)
    ma_fast: int = 10
    ma_slow: int = 30

    # ATR参数 (辅助信号+仓位调整)
    atr_period: int = 14
    atr_ma_window: int = 40
    atr_low_threshold: float = 0.95  # ATR/ATR_MA < 此值为低波动
    atr_high_threshold: float = 1.15  # ATR/ATR_MA > 此值为高波动

    # 趋势过滤
    regime_filter_ma: int = 120  # 长期趋势线
    regime_filter_buffer: float = 1.0  # 价格/MA > 此值才允许买入

    # 交易抑制参数 (关键改进)
    confirm_days: int = 2  # 信号确认天数
    cooldown_days: int = 15  # 卖出后冷却天数
    min_hold_bars: int = 10  # 最小持仓天数

    # ATR动态仓位
    position_low_vol: float = 1.0  # 低波动时仓位
    position_normal_vol: float = 0.7  # 正常波动时仓位
    position_high_vol: float = 0.5  # 高波动时仓位

    # 风险控制
    drawdown_stop: float = 0.15  # 回撤止损阈值
    drawdown_lookback: int = 120  # 回撤计算窗口


@dataclass
class BacktestConfig:
    initial_capital: float = 1_000_000.0
    buy_fee: float = 0.0003
    sell_fee: float = 0.0003
    slippage: float = 0.0005
    start_date: Optional[str] = None
    end_date: Optional[str] = None


def compute_indicators(df: pd.DataFrame, config: OptimizedSignalConfig) -> pd.DataFrame:
    """计算技术指标"""
    enriched = df.copy()

    # 移动平均线
    enriched["ma_fast"] = enriched["close"].rolling(config.ma_fast, min_periods=1).mean()
    enriched["ma_slow"] = enriched["close"].rolling(config.ma_slow, min_periods=1).mean()
    enriched["ma_regime"] = enriched["close"].rolling(config.regime_filter_ma, min_periods=1).mean()

    # MA交叉信号
    enriched["ma_fast_prev"] = enriched["ma_fast"].shift(1)
    enriched["ma_slow_prev"] = enriched["ma_slow"].shift(1)
    enriched["bullish_cross"] = (enriched["ma_fast"] > enriched["ma_slow"]) & (
        enriched["ma_fast_prev"].fillna(enriched["ma_fast"])
        <= enriched["ma_slow_prev"].fillna(enriched["ma_slow"])
    )
    enriched["bearish_cross"] = (enriched["ma_fast"] < enriched["ma_slow"]) & (
        enriched["ma_fast_prev"].fillna(enriched["ma_fast"])
        >= enriched["ma_slow_prev"].fillna(enriched["ma_slow"])
    )

    # ATR计算
    prev_close = enriched["close"].shift(1).fillna(enriched["close"])
    true_range = pd.concat(
        [
            (enriched["high"] - enriched["low"]).abs(),
            (enriched["high"] - prev_close).abs(),
            (enriched["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    enriched["atr"] = true_range.rolling(config.atr_period, min_periods=1).mean()
    enriched["atr_ma"] = enriched["atr"].rolling(config.atr_ma_window, min_periods=1).mean()
    enriched["atr_ratio"] = (enriched["atr"] / enriched["atr_ma"].replace(0.0, pd.NA)).fillna(1.0)

    # 回撤计算
    enriched["rolling_peak"] = (
        enriched["close"].rolling(config.drawdown_lookback, min_periods=1).max()
    )
    enriched["drawdown"] = (enriched["close"] / enriched["rolling_peak"]) - 1.0

    return enriched


def generate_signals(
    df: pd.DataFrame,
    symbol: str,
    config: OptimizedSignalConfig,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> pd.DataFrame:
    """生成交易信号 - 带完整交易抑制机制"""

    # 计算指标
    price_df = compute_indicators(df, config)

    # 日期过滤
    price_df["date"] = pd.to_datetime(price_df["date"])
    start_ts = pd.to_datetime(start_date) if start_date else price_df["date"].min()
    end_ts = pd.to_datetime(end_date) if end_date else price_df["date"].max()
    output_mask = (price_df["date"] >= start_ts) & (price_df["date"] <= end_ts)

    # 状态变量
    current_target = config.initial_position
    holding_bars = 0  # 当前持仓天数
    cooldown_remaining = 0  # 剩余冷却天数
    confirm_buy_count = 0  # 买入确认计数
    confirm_sell_count = 0  # 卖出确认计数
    pending_action = None  # 待确认动作

    records = []

    for idx, row in price_df.iterrows():
        if not output_mask.iloc[idx]:
            continue

        close_price = float(row["close"])

        # 获取信号
        bullish_cross = bool(row.get("bullish_cross", False))
        bearish_cross = bool(row.get("bearish_cross", False))
        atr_ratio = float(row.get("atr_ratio", 1.0))
        regime_ma = float(row.get("ma_regime", close_price))
        regime_ratio = close_price / regime_ma if regime_ma > 0 else 1.0
        drawdown = float(row.get("drawdown", 0.0))

        # === 信号生成 ===
        action = "hold"
        position_reason = "无信号"
        next_target = current_target

        # 1. 风险控制: 回撤止损
        if (
            current_target > config.flat_position + 1e-8
            and drawdown <= -config.drawdown_stop
            and regime_ratio < 1.0
        ):
            next_target = config.flat_position
            action = "sell"
            position_reason = "回撤止损"
            holding_bars = 0
            cooldown_remaining = config.cooldown_days

        # 2. 买入信号处理
        elif bullish_cross and cooldown_remaining <= 0:
            # 趋势过滤
            if regime_ratio >= config.regime_filter_buffer:
                # ATR过滤: 至少不是高波动
                if atr_ratio <= config.atr_high_threshold:
                    # 确认机制
                    if config.confirm_days <= 1:
                        # 直接买入
                        if current_target < config.full_position - 1e-8:
                            # 根据ATR调整仓位
                            if atr_ratio < config.atr_low_threshold:
                                next_target = config.position_low_vol
                            elif atr_ratio < 1.05:
                                next_target = config.position_normal_vol
                            else:
                                next_target = config.position_high_vol
                            action = (
                                "buy" if current_target <= config.flat_position + 1e-8 else "add"
                            )
                            position_reason = f"MA金叉买入(ATR={atr_ratio:.2f})"
                    else:
                        # 需要确认
                        if pending_action == "buy":
                            confirm_buy_count += 1
                            if confirm_buy_count >= config.confirm_days:
                                if current_target < config.full_position - 1e-8:
                                    if atr_ratio < config.atr_low_threshold:
                                        next_target = config.position_low_vol
                                    elif atr_ratio < 1.05:
                                        next_target = config.position_normal_vol
                                    else:
                                        next_target = config.position_high_vol
                                    action = (
                                        "buy"
                                        if current_target <= config.flat_position + 1e-8
                                        else "add"
                                    )
                                    position_reason = f"MA金叉确认买入(ATR={atr_ratio:.2f})"
                                confirm_buy_count = 0
                                pending_action = None
                        else:
                            pending_action = "buy"
                            confirm_buy_count = 1

        # 3. 卖出信号处理
        elif bearish_cross and current_target > config.flat_position + 1e-8:
            # 最小持仓检查
            if holding_bars >= config.min_hold_bars:
                # 确认机制
                if config.confirm_days <= 1:
                    next_target = config.flat_position
                    action = "sell" if next_target <= config.flat_position + 1e-8 else "reduce"
                    if atr_ratio > config.atr_high_threshold:
                        position_reason = f"MA死叉卖出(ATR高波={atr_ratio:.2f})"
                    else:
                        position_reason = "MA死叉卖出"
                    holding_bars = 0
                    cooldown_remaining = config.cooldown_days
                else:
                    # 需要确认
                    if pending_action == "sell":
                        confirm_sell_count += 1
                        if confirm_sell_count >= config.confirm_days:
                            next_target = config.flat_position
                            action = (
                                "sell" if next_target <= config.flat_position + 1e-8 else "reduce"
                            )
                            position_reason = f"MA死叉确认卖出(ATR={atr_ratio:.2f})"
                            holding_bars = 0
                            cooldown_remaining = config.cooldown_days
                            confirm_sell_count = 0
                            pending_action = None
                    else:
                        pending_action = "sell"
                        confirm_sell_count = 1
            else:
                position_reason = f"持仓不足{config.min_hold_bars}天,暂缓卖出"

        # 4. 趋势减弱减仓
        elif (
            regime_ratio < 1.0
            and current_target > config.half_position + 1e-8
            and cooldown_remaining <= 0
        ):
            next_target = config.half_position
            action = "reduce"
            position_reason = "趋势减弱减仓"

        # 更新状态
        if next_target != current_target:
            current_target = next_target
            if action in ["sell", "reduce"]:
                holding_bars = 0
            elif action in ["buy", "add"]:
                holding_bars = 0

        if current_target > config.flat_position + 1e-8:
            holding_bars += 1

        if cooldown_remaining > 0:
            cooldown_remaining -= 1

        records.append(
            {
                "date": row["date"],
                "symbol": symbol,
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": close_price,
                "volume": float(row["volume"]),
                "action": action,
                "target_position": float(current_target),
                "position_reason": position_reason,
                "atr_ratio": atr_ratio,
                "holding_bars": holding_bars,
                "cooldown_remaining": cooldown_remaining,
                "drawdown": drawdown,
            }
        )

    return pd.DataFrame(records)


def run_backtest(
    signal_df: pd.DataFrame,
    config: Optional[BacktestConfig] = None,
) -> Tuple[pd.DataFrame, pd.DataFrame, Dict[str, Any]]:
    """运行回测 - 只在target_position变化时交易"""
    config = config or BacktestConfig()

    if signal_df.empty:
        raise ValueError("No data available")

    equity_df = signal_df.copy()
    equity_df["date"] = pd.to_datetime(equity_df["date"])

    if config.start_date:
        equity_df = equity_df[equity_df["date"] >= pd.to_datetime(config.start_date)]
    if config.end_date:
        equity_df = equity_df[equity_df["date"] <= pd.to_datetime(config.end_date)]
    equity_df = equity_df.reset_index(drop=True)

    if equity_df.empty:
        raise ValueError("No data in date range")

    cash = config.initial_capital
    units = 0.0
    prev_value = config.initial_capital
    prev_close = float(equity_df.iloc[0]["close"])
    first_close = float(equity_df.iloc[0]["close"])
    prev_target_position = 0.0  # Track previous target position

    trades = []
    records = []

    for row in equity_df.to_dict("records"):
        exec_price_buy = float(row["open"]) * (1.0 + config.slippage)
        exec_price_sell = float(row["open"]) * (1.0 - config.slippage)
        target_position = float(row.get("target_position", 0.0))

        # Only trade if target_position changed
        target_changed = abs(target_position - prev_target_position) > 1e-8

        portfolio_value_before = cash + units * float(row["open"])
        current_value = units * float(row["open"])

        trade_type = "hold"

        if target_changed:
            # Calculate desired holdings value based on new target
            desired_value = portfolio_value_before * target_position

            if desired_value > current_value + 1e-8:
                trade_value = desired_value - current_value
                affordable = cash / (exec_price_buy * (1.0 + config.buy_fee))
                desired_units = trade_value / exec_price_buy
                buy_units = min(affordable, desired_units)
                if buy_units > 1e-8:
                    cost = buy_units * exec_price_buy
                    fee = cost * config.buy_fee
                    cash -= cost + fee
                    units += buy_units
                    trade_type = "buy" if current_value <= 1e-8 else "add"
                    trades.append(
                        {
                            "date": row["date"],
                            "symbol": row.get("symbol", ""),
                            "type": trade_type,
                            "price": exec_price_buy,
                            "units": buy_units,
                        }
                    )
            elif desired_value < current_value - 1e-8:
                trade_value = current_value - desired_value
                sell_units = min(units, trade_value / exec_price_sell)
                if sell_units > 1e-8:
                    proceeds = sell_units * exec_price_sell
                    fee = proceeds * config.sell_fee
                    cash += proceeds - fee
                    units -= sell_units
                    trade_type = "sell" if target_position <= 1e-8 else "reduce"
                    trades.append(
                        {
                            "date": row["date"],
                            "symbol": row.get("symbol", ""),
                            "type": trade_type,
                            "price": exec_price_sell,
                            "units": sell_units,
                        }
                    )

        holdings_value = units * float(row["close"])
        portfolio_value = cash + holdings_value
        strategy_nav = portfolio_value / config.initial_capital
        benchmark_nav = float(row["close"]) / first_close
        daily_return = 0.0 if not records else (portfolio_value / prev_value) - 1.0
        benchmark_return = 0.0 if not records else (float(row["close"]) / prev_close) - 1.0
        executed_position = holdings_value / portfolio_value if portfolio_value > 0 else 0.0

        records.append(
            {
                **row,
                "executed_position": executed_position,
                "portfolio_value": portfolio_value,
                "strategy_nav": strategy_nav,
                "benchmark_nav": benchmark_nav,
                "daily_return": daily_return,
                "benchmark_return": benchmark_return,
                "excess_return": daily_return - benchmark_return,
            }
        )

        prev_value = portfolio_value
        prev_close = float(row["close"])
        prev_target_position = target_position  # Update previous target position

    result_df = pd.DataFrame(records)

    # 计算回撤
    result_df["running_max"] = result_df["strategy_nav"].cummax()
    result_df["drawdown_calc"] = result_df["strategy_nav"] / result_df["running_max"] - 1.0

    trades_df = pd.DataFrame(trades)

    # 计算汇总指标
    final_nav = float(result_df["strategy_nav"].iloc[-1])
    total_return = final_nav - 1.0
    benchmark_return_total = float(result_df["benchmark_nav"].iloc[-1] - 1.0)
    periods = len(result_df)
    annualized_return = (final_nav ** (252.0 / periods) - 1.0) if final_nav > 0 else -1.0
    annualized_benchmark = (
        ((1 + benchmark_return_total) ** (252.0 / periods) - 1.0)
        if benchmark_return_total > -1
        else -1.0
    )
    annualized_excess = annualized_return - annualized_benchmark
    max_drawdown = float(result_df["drawdown_calc"].min())

    summary = {
        "symbol": str(result_df.iloc[0].get("symbol", "")),
        "start_date": result_df.iloc[0]["date"].strftime("%Y-%m-%d"),
        "end_date": result_df.iloc[-1]["date"].strftime("%Y-%m-%d"),
        "final_nav": final_nav,
        "total_return": total_return,
        "benchmark_return": benchmark_return_total,
        "annualized_return": annualized_return,
        "annualized_benchmark": annualized_benchmark,
        "annualized_excess_return": annualized_excess,
        "max_drawdown": max_drawdown,
        "trade_count": len(trades_df),
        "average_position": float(result_df["executed_position"].mean()),
    }

    return result_df, trades_df, summary
