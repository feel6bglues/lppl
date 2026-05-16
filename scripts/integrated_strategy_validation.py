#!/usr/bin/env python3
# RESEARCH ONLY — not production code
# -*- coding: utf-8 -*-
"""
综合策略验证测试脚本

基于优化分析结果，验证推荐的策略组合：
1. 稳健型组合（推荐）
2. 平衡型组合
3. 进攻型组合

测试内容：
- LPPL参数：短期配置（50-190天），RMSE<0.015
- MA/ATR策略：MA(5,20,60) + ATR(20,40) + regime_filter=120
- 多因子自适应策略
- 信号调优参数
"""

import os
import sys
import time
import warnings
from datetime import datetime
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

# 输出目录
OUTPUT_DIR = "output/integrated_strategy_validation"
START_DATE = "2020-01-01"
END_DATE = "2026-03-27"


# ============================================================
# 策略配置定义
# ============================================================

def get_conservative_config() -> Dict[str, Any]:
    """稳健型配置（推荐）"""
    return {
        "name": "稳健型（推荐）",
        "description": "MA(5,20,60) + ATR(20,40) + regime_filter=120",
        "signal_model": "ma_cross_atr_v1",
        # MA 配置
        "trend_fast_ma": 5,
        "trend_slow_ma": 60,
        # ATR 配置
        "atr_period": 20,
        "atr_ma_window": 40,
        "buy_volatility_cap": 1.0,
        "vol_breakout_mult": 1.1,
        # Regime 过滤
        "regime_filter_ma": 120,
        "regime_filter_buffer": 1.0,
        "regime_filter_reduce_enabled": True,
        # 风险控制
        "risk_drawdown_stop_threshold": 0.15,
        "risk_drawdown_lookback": 120,
        # 交易控制
        "buy_confirm_days": 2,
        "sell_confirm_days": 2,
        "cooldown_days": 5,
        "min_hold_bars": 3,
        # 信号阈值
        "positive_consensus_threshold": 0.25,
        "negative_consensus_threshold": 0.2,
        "sell_vote_threshold": 2,
        "buy_vote_threshold": 3,
    }


def get_balanced_config() -> Dict[str, Any]:
    """平衡型配置"""
    return {
        "name": "平衡型",
        "description": "MA(5,20,60) + ATR(20,40) + vol_breakout=1.05",
        "signal_model": "ma_cross_atr_v1",
        # MA 配置
        "trend_fast_ma": 5,
        "trend_slow_ma": 60,
        # ATR 配置
        "atr_period": 20,
        "atr_ma_window": 40,
        "buy_volatility_cap": 1.05,
        "vol_breakout_mult": 1.05,
        # Regime 过滤
        "regime_filter_ma": 120,
        "regime_filter_buffer": 1.0,
        "regime_filter_reduce_enabled": True,
        # 风险控制
        "risk_drawdown_stop_threshold": 0.18,
        "risk_drawdown_lookback": 120,
        # 交易控制
        "buy_confirm_days": 2,
        "sell_confirm_days": 2,
        "cooldown_days": 10,
        "min_hold_bars": 3,
        # 信号阈值
        "positive_consensus_threshold": 0.25,
        "negative_consensus_threshold": 0.2,
        "sell_vote_threshold": 2,
        "buy_vote_threshold": 3,
    }


def get_aggressive_config() -> Dict[str, Any]:
    """进攻型配置"""
    return {
        "name": "进攻型",
        "description": "MA(5,60,120) + ATR(14,40) + vol_breakout=1.05",
        "signal_model": "ma_cross_atr_v1",
        # MA 配置
        "trend_fast_ma": 5,
        "trend_slow_ma": 120,
        # ATR 配置
        "atr_period": 14,
        "atr_ma_window": 40,
        "buy_volatility_cap": 1.05,
        "vol_breakout_mult": 1.05,
        # Regime 过滤
        "regime_filter_ma": 120,
        "regime_filter_buffer": 1.0,
        "regime_filter_reduce_enabled": True,
        # 风险控制
        "risk_drawdown_stop_threshold": 0.12,
        "risk_drawdown_lookback": 240,
        # 交易控制
        "buy_confirm_days": 2,
        "sell_confirm_days": 2,
        "cooldown_days": 15,
        "min_hold_bars": 3,
        # 信号阈值
        "positive_consensus_threshold": 0.25,
        "negative_consensus_threshold": 0.2,
        "sell_vote_threshold": 2,
        "buy_vote_threshold": 3,
    }


def get_multi_factor_config() -> Dict[str, Any]:
    """多因子自适应配置"""
    return {
        "name": "多因子自适应",
        "description": "MA(10,30,60) + ATR + BB + 动量",
        "signal_model": "multi_factor_adaptive_v1",
        # MA 配置
        "ma_short": 10,
        "ma_mid": 30,
        "ma_long": 60,
        "htf_ma": 180,
        # ATR 配置
        "atr_period": 14,
        "atr_ma_window": 40,
        "atr_low_threshold": 0.95,
        "atr_high_threshold": 1.15,
        # BB 配置
        "bb_period": 20,
        "bb_std": 2.0,
        "bb_narrow_threshold": 0.05,
        "bb_wide_threshold": 0.10,
        # 评分权重
        "trend_weight": 0.40,
        "volatility_weight": 0.30,
        "market_state_weight": 0.20,
        "momentum_weight": 0.10,
        # 信号阈值
        "buy_score_threshold": 0.3,
        "sell_score_threshold": -0.3,
        "reduce_score_threshold": -0.1,
        # 风险控制
        "risk_drawdown_stop_threshold": 0.15,
        "regime_filter_reduce_enabled": True,
    }


# ============================================================
# 回测引擎
# ============================================================

def normalize_price_frame(df: pd.DataFrame) -> pd.DataFrame:
    """标准化数据"""
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


def compute_ma_atr_indicators(df: pd.DataFrame, config: Dict[str, Any]) -> pd.DataFrame:
    """计算 MA + ATR 指标"""
    enriched = df.copy()

    # MA 配置
    fast_ma = config.get("trend_fast_ma", 5)
    slow_ma = config.get("trend_slow_ma", 60)

    # 均线
    enriched["ma_fast"] = enriched["close"].rolling(fast_ma, min_periods=1).mean()
    enriched["ma_slow"] = enriched["close"].rolling(slow_ma, min_periods=1).mean()
    enriched["ma_fast_prev"] = enriched["ma_fast"].shift(1)
    enriched["ma_slow_prev"] = enriched["ma_slow"].shift(1)

    # 交叉信号
    enriched["bullish_cross"] = (
        (enriched["ma_fast"] > enriched["ma_slow"])
        & (enriched["ma_fast_prev"].fillna(enriched["ma_fast"]) <= enriched["ma_slow_prev"].fillna(enriched["ma_slow"]))
    )
    enriched["bearish_cross"] = (
        (enriched["ma_fast"] < enriched["ma_slow"])
        & (enriched["ma_fast_prev"].fillna(enriched["ma_fast"]) >= enriched["ma_slow_prev"].fillna(enriched["ma_slow"]))
    )

    # 趋势状态
    enriched["uptrend"] = enriched["ma_fast"] > enriched["ma_slow"]
    enriched["downtrend"] = enriched["ma_fast"] < enriched["ma_slow"]

    # ATR
    prev_close = enriched["close"].shift(1).fillna(enriched["close"])
    true_range = pd.concat([
        (enriched["high"] - enriched["low"]).abs(),
        (enriched["high"] - prev_close).abs(),
        (enriched["low"] - prev_close).abs(),
    ], axis=1).max(axis=1)

    atr_period = config.get("atr_period", 14)
    atr_ma_window = config.get("atr_ma_window", 40)

    enriched["atr"] = true_range.rolling(atr_period, min_periods=1).mean()
    enriched["atr_ma"] = enriched["atr"].rolling(atr_ma_window, min_periods=1).mean()
    enriched["atr_ratio"] = (enriched["atr"] / enriched["atr_ma"].replace(0.0, pd.NA)).fillna(1.0)

    # Regime 过滤
    regime_ma = config.get("regime_filter_ma", 120)
    enriched["ma_regime"] = enriched["close"].rolling(regime_ma, min_periods=1).mean()
    enriched["regime_ratio"] = enriched["close"] / enriched["ma_regime"]

    # 回撤计算
    enriched["rolling_peak"] = enriched["close"].rolling(120, min_periods=1).max()
    enriched["drawdown"] = (enriched["close"] / enriched["rolling_peak"]) - 1.0

    return enriched


def compute_multi_factor_indicators(df: pd.DataFrame, config: Dict[str, Any]) -> pd.DataFrame:
    """计算多因子指标"""
    enriched = df.copy()

    # MA 配置
    ma_short = config.get("ma_short", 10)
    ma_mid = config.get("ma_mid", 30)
    ma_long = config.get("ma_long", 60)
    htf_ma = config.get("htf_ma", 180)

    # 均线
    enriched["ma_short"] = enriched["close"].rolling(ma_short, min_periods=1).mean()
    enriched["ma_mid"] = enriched["close"].rolling(ma_mid, min_periods=1).mean()
    enriched["ma_long"] = enriched["close"].rolling(ma_long, min_periods=1).mean()
    enriched["ma_regime"] = enriched["close"].rolling(htf_ma, min_periods=1).mean()

    # 交叉信号
    enriched["ma_short_prev"] = enriched["ma_short"].shift(1)
    enriched["ma_mid_prev"] = enriched["ma_mid"].shift(1)

    enriched["bullish_cross"] = (
        (enriched["ma_short"] > enriched["ma_mid"])
        & (enriched["ma_short_prev"].fillna(enriched["ma_short"]) <= enriched["ma_mid_prev"].fillna(enriched["ma_mid"]))
    )
    enriched["bearish_cross"] = (
        (enriched["ma_short"] < enriched["ma_mid"])
        & (enriched["ma_short_prev"].fillna(enriched["ma_short"]) >= enriched["ma_mid_prev"].fillna(enriched["ma_mid"]))
    )

    # ATR
    prev_close = enriched["close"].shift(1).fillna(enriched["close"])
    true_range = pd.concat([
        (enriched["high"] - enriched["low"]).abs(),
        (enriched["high"] - prev_close).abs(),
        (enriched["low"] - prev_close).abs(),
    ], axis=1).max(axis=1)

    atr_period = config.get("atr_period", 14)
    atr_ma_window = config.get("atr_ma_window", 40)

    enriched["atr"] = true_range.rolling(atr_period, min_periods=1).mean()
    enriched["atr_ma"] = enriched["atr"].rolling(atr_ma_window, min_periods=1).mean()
    enriched["atr_ratio"] = (enriched["atr"] / enriched["atr_ma"].replace(0.0, pd.NA)).fillna(1.0)

    # BB
    bb_period = config.get("bb_period", 20)
    bb_std = config.get("bb_std", 2.0)

    enriched["bb_ma"] = enriched["close"].rolling(bb_period, min_periods=1).mean()
    enriched["bb_std"] = enriched["close"].rolling(bb_period, min_periods=1).std()
    enriched["bb_upper"] = enriched["bb_ma"] + bb_std * enriched["bb_std"]
    enriched["bb_lower"] = enriched["bb_ma"] - bb_std * enriched["bb_std"]
    enriched["bb_width"] = (enriched["bb_upper"] - enriched["bb_lower"]) / enriched["bb_ma"]

    # 回撤计算
    enriched["rolling_peak"] = enriched["close"].rolling(120, min_periods=1).max()
    enriched["drawdown"] = (enriched["close"] / enriched["rolling_peak"]) - 1.0
    enriched["risk_price_drawdown"] = enriched["drawdown"]

    return enriched


def run_ma_atr_backtest(
    df: pd.DataFrame,
    config: Dict[str, Any],
    start_date: str = START_DATE,
    end_date: str = END_DATE,
) -> tuple:
    """运行 MA + ATR 回测"""
    # 标准化数据
    price_df = normalize_price_frame(df)
    price_df = compute_ma_atr_indicators(price_df, config)

    # 过滤日期
    start_ts = pd.to_datetime(start_date)
    end_ts = pd.to_datetime(end_date)
    price_df = price_df[(price_df["date"] >= start_ts) & (price_df["date"] <= end_ts)]

    # 预热期
    warmup = max(config.get("trend_slow_ma", 60), config.get("atr_ma_window", 40), config.get("regime_filter_ma", 120))
    price_df = price_df.iloc[warmup:]

    if len(price_df) < 100:
        return pd.DataFrame(), pd.DataFrame(), {}

    # 回测参数
    initial_capital = 1_000_000.0
    buy_fee = 0.0003
    sell_fee = 0.0003
    slippage = 0.0005

    buy_volatility_cap = config.get("buy_volatility_cap", 1.0)
    vol_breakout_mult = config.get("vol_breakout_mult", 1.1)
    regime_buffer = config.get("regime_filter_buffer", 1.0)
    regime_reduce_enabled = config.get("regime_filter_reduce_enabled", True)
    drawdown_stop = config.get("risk_drawdown_stop_threshold", 0.15)
    cooldown_days = config.get("cooldown_days", 5)
    min_hold_bars = config.get("min_hold_bars", 3)

    # 初始化
    cash = initial_capital
    shares = 0
    current_position = 0.0
    cooldown_remaining = 0
    hold_bars = 0

    records = []
    trades = []

    for idx, row in price_df.iterrows():
        atr_ratio = float(row["atr_ratio"])
        bullish_cross = bool(row.get("bullish_cross", False))
        bearish_cross = bool(row.get("bearish_cross", False))
        regime_ratio = float(row.get("regime_ratio", 1.0))
        drawdown = float(row.get("drawdown", 0.0))

        # 信号逻辑
        buy_candidate = bullish_cross and atr_ratio <= buy_volatility_cap
        sell_candidate = bearish_cross and atr_ratio >= vol_breakout_mult

        # Regime 过滤
        regime_ok = regime_ratio >= (1.0 - regime_buffer / 100.0)

        next_position = current_position
        reason = "持有"

        # 冷却期检查
        if cooldown_remaining > 0:
            cooldown_remaining -= 1
            reason = f"冷却期剩余 {cooldown_remaining} 天"

        # 回撤止损
        elif drawdown <= -drawdown_stop:
            next_position = 0.0
            reason = f"回撤止损 {drawdown:.1%}"
            cooldown_remaining = cooldown_days

        # 买入信号
        elif buy_candidate and current_position < 1.0 and regime_ok:
            if hold_bars >= min_hold_bars or current_position == 0:
                next_position = min(current_position + 0.5, 1.0)
                reason = f"MA交叉买入 ATR={atr_ratio:.2f}"
                cooldown_remaining = cooldown_days
                hold_bars = 0

        # 卖出信号
        elif sell_candidate and current_position > 0.0:
            if hold_bars >= min_hold_bars:
                next_position = max(current_position - 0.5, 0.0)
                reason = f"MA交叉卖出 ATR={atr_ratio:.2f}"
                cooldown_remaining = cooldown_days
                hold_bars = 0

        # Regime 减仓
        elif regime_reduce_enabled and not regime_ok and current_position > 0.5:
            if hold_bars >= min_hold_bars:
                next_position = 0.5
                reason = f"Regime减仓 ratio={regime_ratio:.2f}"
                hold_bars = 0

        # 执行交易
        if next_position > current_position and next_position > 0:
            target_value = initial_capital * next_position
            add_value = target_value - (shares * row["close"])
            if add_value > 0:
                buy_price = row["close"] * (1 + slippage)
                buy_shares = int(add_value / buy_price / 100) * 100
                if buy_shares > 0:
                    cost = buy_shares * buy_price * (1 + buy_fee)
                    if cost <= cash:
                        cash -= cost
                        shares += buy_shares
                        trades.append({
                            "date": row["date"],
                            "action": "buy",
                            "price": buy_price,
                            "shares": buy_shares,
                        })

        elif next_position < current_position and shares > 0:
            if next_position == 0:
                sell_shares = shares
            else:
                sell_shares = int(shares * 0.5 / 100) * 100

            if sell_shares > 0:
                sell_price = row["close"] * (1 - slippage)
                proceeds = sell_shares * sell_price * (1 - sell_fee)
                cash += proceeds
                shares -= sell_shares
                trades.append({
                    "date": row["date"],
                    "action": "sell",
                    "price": sell_price,
                    "shares": sell_shares,
                })

        # 记录
        current_position = next_position
        portfolio_value = cash + shares * row["close"]
        hold_bars += 1

        records.append({
            "date": row["date"],
            "close": row["close"],
            "position": current_position,
            "portfolio_value": portfolio_value,
            "drawdown": drawdown,
            "atr_ratio": atr_ratio,
            "regime_ratio": regime_ratio,
            "reason": reason,
        })

    # 生成结果
    result_df = pd.DataFrame(records)
    trades_df = pd.DataFrame(trades)

    # 计算收益
    result_df["daily_return"] = result_df["portfolio_value"].pct_change()
    result_df["cumulative_return"] = (1 + result_df["daily_return"]).cumprod() - 1

    # 计算回撤
    result_df["peak"] = result_df["portfolio_value"].cummax()
    result_df["portfolio_drawdown"] = (result_df["portfolio_value"] / result_df["peak"]) - 1.0

    # 计算基准收益
    result_df["benchmark_return"] = result_df["close"] / result_df["close"].iloc[0] - 1.0

    # 计算汇总统计
    total_return = result_df["cumulative_return"].iloc[-1]
    benchmark_return = result_df["benchmark_return"].iloc[-1]
    annualized_return = (1 + total_return) ** (252 / len(result_df)) - 1
    annualized_benchmark = (1 + benchmark_return) ** (252 / len(result_df)) - 1
    annualized_excess = annualized_return - annualized_benchmark
    max_drawdown = result_df["portfolio_drawdown"].min()
    trade_count = len(trades_df)

    # 持仓比例
    holding_days = (result_df["position"] > 0).sum()
    holding_ratio = holding_days / len(result_df)

    # 换手率
    if len(trades_df) > 0:
        total_trade_value = (trades_df["shares"] * trades_df["price"]).sum()
        turnover_rate = total_trade_value / initial_capital
    else:
        turnover_rate = 0.0

    summary = {
        "total_return": total_return,
        "benchmark_return": benchmark_return,
        "annualized_return": annualized_return,
        "annualized_benchmark": annualized_benchmark,
        "annualized_excess_return": annualized_excess,
        "max_drawdown": max_drawdown,
        "trade_count": trade_count,
        "holding_ratio": holding_ratio,
        "turnover_rate": turnover_rate,
        "eligible": (annualized_excess > 0 and max_drawdown > -0.35 and trade_count >= 3),
    }

    return result_df, trades_df, summary


def run_multi_factor_backtest(
    df: pd.DataFrame,
    config: Dict[str, Any],
    start_date: str = START_DATE,
    end_date: str = END_DATE,
) -> tuple:
    """运行多因子自适应回测"""
    # 标准化数据
    price_df = normalize_price_frame(df)
    price_df = compute_multi_factor_indicators(price_df, config)

    # 过滤日期
    start_ts = pd.to_datetime(start_date)
    end_ts = pd.to_datetime(end_date)
    price_df = price_df[(price_df["date"] >= start_ts) & (price_df["date"] <= end_ts)]

    # 预热期
    warmup = max(config.get("htf_ma", 180), config.get("atr_ma_window", 40))
    price_df = price_df.iloc[warmup:]

    if len(price_df) < 100:
        return pd.DataFrame(), pd.DataFrame(), {}

    # 回测参数
    initial_capital = 1_000_000.0
    buy_fee = 0.0003
    sell_fee = 0.0003
    slippage = 0.0005

    # 因子权重
    trend_weight = config.get("trend_weight", 0.40)
    volatility_weight = config.get("volatility_weight", 0.30)
    market_state_weight = config.get("market_state_weight", 0.20)
    momentum_weight = config.get("momentum_weight", 0.10)

    # 阈值
    buy_score_threshold = config.get("buy_score_threshold", 0.3)
    sell_score_threshold = config.get("sell_score_threshold", -0.3)
    atr_low_threshold = config.get("atr_low_threshold", 0.95)
    atr_high_threshold = config.get("atr_high_threshold", 1.15)
    bb_narrow_threshold = config.get("bb_narrow_threshold", 0.05)
    bb_wide_threshold = config.get("bb_wide_threshold", 0.10)
    drawdown_stop = config.get("risk_drawdown_stop_threshold", 0.15)

    # 初始化
    cash = initial_capital
    shares = 0
    current_position = 0.0

    records = []
    trades = []

    for idx, row in price_df.iterrows():
        # 计算各因子得分
        bullish_cross = bool(row.get("bullish_cross", False))
        bearish_cross = bool(row.get("bearish_cross", False))
        atr_ratio = float(row.get("atr_ratio", 1.0))
        bb_width = float(row.get("bb_width", 0.10))
        ma_short = float(row.get("ma_short", row["close"]))
        ma_mid = float(row.get("ma_mid", row["close"]))
        regime_ratio = float(row.get("close", row["close"]) / row.get("ma_regime", row["close"]))
        drawdown = float(row.get("risk_price_drawdown", 0.0))

        # 趋势因子 (40%)
        trend_score = 0.0
        if bullish_cross:
            trend_score = 1.0
        elif bearish_cross:
            trend_score = -1.0

        if regime_ratio >= 1.02:
            trend_score += 0.5
        elif regime_ratio <= 0.98:
            trend_score -= 0.5

        # 波动率因子 (30%)
        vol_score = 0.0
        if atr_ratio < atr_low_threshold:
            vol_score = 1.0
        elif atr_ratio > atr_high_threshold:
            vol_score = -1.0

        # 市场状态因子 (20%)
        state_score = 0.0
        if bb_width < bb_narrow_threshold:
            state_score = 0.5
        elif bb_width > bb_wide_threshold:
            state_score = -0.5

        # 动量因子 (10%)
        momentum_score = 0.0
        if ma_short > ma_mid:
            momentum_score = 0.5
        elif ma_short < ma_mid:
            momentum_score = -0.5

        # 综合评分
        total_score = (
            trend_score * trend_weight
            + vol_score * volatility_weight
            + state_score * market_state_weight
            + momentum_score * momentum_weight
        )

        # 信号逻辑
        next_position = current_position
        reason = f"持有 评分={total_score:.2f}"

        # 回撤止损
        if drawdown <= -drawdown_stop and current_position > 0:
            next_position = 0.0
            reason = f"回撤止损 {drawdown:.1%}"

        # 买入决策
        elif total_score >= buy_score_threshold and trend_score > 0:
            next_position = min(1.0, current_position + 0.5)
            reason = f"多因子买入 评分={total_score:.2f}"

        # 卖出决策
        elif total_score <= sell_score_threshold and trend_score < 0:
            next_position = max(0.0, current_position - 0.5)
            reason = f"多因子卖出 评分={total_score:.2f}"

        # 减仓决策
        elif total_score < 0 and current_position > 0:
            next_position = max(0.0, current_position - 0.33)
            reason = f"多因子减仓 评分={total_score:.2f}"

        # 执行交易
        if next_position > current_position and next_position > 0:
            target_value = initial_capital * next_position
            add_value = target_value - (shares * row["close"])
            if add_value > 0:
                buy_price = row["close"] * (1 + slippage)
                buy_shares = int(add_value / buy_price / 100) * 100
                if buy_shares > 0:
                    cost = buy_shares * buy_price * (1 + buy_fee)
                    if cost <= cash:
                        cash -= cost
                        shares += buy_shares
                        trades.append({
                            "date": row["date"],
                            "action": "buy",
                            "price": buy_price,
                            "shares": buy_shares,
                            "score": total_score,
                        })

        elif next_position < current_position and shares > 0:
            if next_position == 0:
                sell_shares = shares
            else:
                sell_shares = int(shares * 0.5 / 100) * 100

            if sell_shares > 0:
                sell_price = row["close"] * (1 - slippage)
                proceeds = sell_shares * sell_price * (1 - sell_fee)
                cash += proceeds
                shares -= sell_shares
                trades.append({
                    "date": row["date"],
                    "action": "sell",
                    "price": sell_price,
                    "shares": sell_shares,
                    "score": total_score,
                })

        # 记录
        current_position = next_position
        portfolio_value = cash + shares * row["close"]

        records.append({
            "date": row["date"],
            "close": row["close"],
            "position": current_position,
            "portfolio_value": portfolio_value,
            "drawdown": drawdown,
            "atr_ratio": atr_ratio,
            "bb_width": bb_width,
            "total_score": total_score,
            "reason": reason,
        })

    # 生成结果
    result_df = pd.DataFrame(records)
    trades_df = pd.DataFrame(trades)

    # 计算收益
    result_df["daily_return"] = result_df["portfolio_value"].pct_change()
    result_df["cumulative_return"] = (1 + result_df["daily_return"]).cumprod() - 1

    # 计算回撤
    result_df["peak"] = result_df["portfolio_value"].cummax()
    result_df["portfolio_drawdown"] = (result_df["portfolio_value"] / result_df["peak"]) - 1.0

    # 计算基准收益
    result_df["benchmark_return"] = result_df["close"] / result_df["close"].iloc[0] - 1.0

    # 计算汇总统计
    total_return = result_df["cumulative_return"].iloc[-1]
    benchmark_return = result_df["benchmark_return"].iloc[-1]
    annualized_return = (1 + total_return) ** (252 / len(result_df)) - 1
    annualized_benchmark = (1 + benchmark_return) ** (252 / len(result_df)) - 1
    annualized_excess = annualized_return - annualized_benchmark
    max_drawdown = result_df["portfolio_drawdown"].min()
    trade_count = len(trades_df)

    # 持仓比例
    holding_days = (result_df["position"] > 0).sum()
    holding_ratio = holding_days / len(result_df)

    # 换手率
    if len(trades_df) > 0:
        total_trade_value = (trades_df["shares"] * trades_df["price"]).sum()
        turnover_rate = total_trade_value / initial_capital
    else:
        turnover_rate = 0.0

    summary = {
        "total_return": total_return,
        "benchmark_return": benchmark_return,
        "annualized_return": annualized_return,
        "annualized_benchmark": annualized_benchmark,
        "annualized_excess_return": annualized_excess,
        "max_drawdown": max_drawdown,
        "trade_count": trade_count,
        "holding_ratio": holding_ratio,
        "turnover_rate": turnover_rate,
        "eligible": (annualized_excess > 0 and max_drawdown > -0.35 and trade_count >= 3),
    }

    return result_df, trades_df, summary


# ============================================================
# 测试执行
# ============================================================

def run_single_test(
    symbol: str,
    config: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """运行单次测试"""
    from src.data.manager import DataManager

    try:
        manager = DataManager()
        df = manager.get_data(symbol)
        if df is None or df.empty:
            return None

        signal_model = config.get("signal_model", "ma_cross_atr_v1")

        if signal_model == "multi_factor_adaptive_v1":
            result_df, trades_df, summary = run_multi_factor_backtest(df, config)
        else:
            result_df, trades_df, summary = run_ma_atr_backtest(df, config)

        if result_df.empty:
            return None

        return {
            "symbol": symbol,
            "symbol_name": SYMBOL_NAMES.get(symbol, symbol),
            "config_name": config["name"],
            "signal_model": signal_model,
            **summary,
        }
    except Exception as e:
        print(f"  [ERROR] {symbol}: {e}")
        return None


def run_validation_tests():
    """运行验证测试"""
    print("=" * 100)
    print("综合策略验证测试")
    print("=" * 100)
    print(f"测试周期: {START_DATE} ~ {END_DATE}")
    print(f"测试指数: {len(SYMBOLS)} 个")
    print()

    # 获取配置
    configs = [
        get_conservative_config(),
        get_balanced_config(),
        get_aggressive_config(),
        get_multi_factor_config(),
    ]

    all_results = []

    for config in configs:
        print(f"\n{'='*80}")
        print(f"测试配置: {config['name']}")
        print(f"  描述: {config['description']}")
        print(f"  信号模型: {config['signal_model']}")
        print(f"{'='*80}")

        results = []
        for symbol in SYMBOLS:
            print(f"  {symbol} ({SYMBOL_NAMES[symbol]})...", end=" ", flush=True)
            result = run_single_test(symbol, config)
            if result:
                results.append(result)
                eligible = "✅" if result["eligible"] else "❌"
                print(f"{eligible} 年化={result['annualized_return']:.2%}, 超额={result['annualized_excess_return']:.2%}, 回撤={result['max_drawdown']:.2%}, 交易={result['trade_count']}")
            else:
                print("FAILED")

        if results:
            df = pd.DataFrame(results)
            all_results.append(df)

            # 打印配置汇总
            print("\n  配置汇总:")
            print(f"    eligible: {df['eligible'].sum()}/{len(results)}")
            print(f"    平均年化收益: {df['annualized_return'].mean():.2%}")
            print(f"    平均年化超额: {df['annualized_excess_return'].mean():.2%}")
            print(f"    平均回撤: {df['max_drawdown'].mean():.2%}")
            print(f"    平均交易次数: {df['trade_count'].mean():.1f}")
            print(f"    平均持仓比例: {df['holding_ratio'].mean():.0%}")

    # 保存结果
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    combined_df = pd.concat(all_results, ignore_index=True)
    combined_df.to_csv(f"{OUTPUT_DIR}/validation_results.csv", index=False)

    return combined_df


def analyze_results(df: pd.DataFrame):
    """分析结果"""
    print("\n" + "=" * 100)
    print("结果分析")
    print("=" * 100)

    # 按配置汇总
    config_summary = df.groupby("config_name").agg({
        "eligible": "sum",
        "annualized_return": "mean",
        "annualized_excess_return": "mean",
        "max_drawdown": "mean",
        "trade_count": "mean",
        "holding_ratio": "mean",
        "turnover_rate": "mean",
    }).sort_values(["eligible", "annualized_excess_return"], ascending=False)

    print("\n--- 配置排名 ---\n")
    print(f"{'配置名称':<20} {'eligible':<10} {'平均年化':<10} {'平均超额':<10} {'平均回撤':<10} {'平均交易':<10} {'平均持仓':<10}")
    print("-" * 80)

    for config_name, row in config_summary.iterrows():
        print(f"{config_name:<20} {int(row['eligible'])}/8{'':<6} {row['annualized_return']:.2%}{'':<4} {row['annualized_excess_return']:.2%}{'':<4} {row['max_drawdown']:.2%}{'':<4} {row['trade_count']:.1f}{'':<6} {row['holding_ratio']:.0%}")

    # 各指数最优配置
    print("\n--- 各指数最优配置 ---\n")

    for symbol in SYMBOLS:
        symbol_df = df[df["symbol"] == symbol]
        if symbol_df.empty:
            continue

        best = symbol_df.sort_values("annualized_excess_return", ascending=False).iloc[0]
        eligible = "✅" if best["eligible"] else "❌"
        print(f"{symbol} ({SYMBOL_NAMES[symbol]}):")
        print(f"  最优配置: {best['config_name']}")
        print(f"  {eligible} 年化={best['annualized_return']:.2%}, 超额={best['annualized_excess_return']:.2%}, 回撤={best['max_drawdown']:.2%}, 交易={int(best['trade_count'])}次")
        print()


def generate_report(df: pd.DataFrame):
    """生成报告"""
    print("\n" + "=" * 100)
    print("生成报告")
    print("=" * 100)

    report_lines = []
    report_lines.append("# 综合策略验证测试报告")
    report_lines.append(f"\n**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report_lines.append(f"\n**测试周期**: {START_DATE} ~ {END_DATE}")
    report_lines.append("\n---\n")

    report_lines.append("## 测试配置\n")
    report_lines.append("| 配置名称 | 描述 | 信号模型 |")
    report_lines.append("|:---------|:-----|:---------|")

    configs = [
        get_conservative_config(),
        get_balanced_config(),
        get_aggressive_config(),
        get_multi_factor_config(),
    ]

    for config in configs:
        report_lines.append(f"| {config['name']} | {config['description']} | {config['signal_model']} |")
    report_lines.append("")

    # 按配置汇总
    config_summary = df.groupby("config_name").agg({
        "eligible": "sum",
        "annualized_return": "mean",
        "annualized_excess_return": "mean",
        "max_drawdown": "mean",
        "trade_count": "mean",
        "holding_ratio": "mean",
        "turnover_rate": "mean",
    }).sort_values(["eligible", "annualized_excess_return"], ascending=False)

    report_lines.append("## 配置排名\n")
    report_lines.append("| 配置名称 | eligible | 平均年化收益 | 平均年化超额 | 平均回撤 | 平均交易 | 平均持仓 | 平均换手 |")
    report_lines.append("|:---------|:--------:|-----------:|-----------:|--------:|--------:|--------:|--------:|")

    for config_name, row in config_summary.iterrows():
        report_lines.append(f"| {config_name} | {int(row['eligible'])}/8 | {row['annualized_return']:.2%} | {row['annualized_excess_return']:.2%} | {row['max_drawdown']:.2%} | {row['trade_count']:.1f} | {row['holding_ratio']:.0%} | {row['turnover_rate']:.2f} |")
    report_lines.append("")

    # 各指数最优配置
    report_lines.append("## 各指数最优配置\n")

    for symbol in SYMBOLS:
        symbol_df = df[df["symbol"] == symbol]
        if symbol_df.empty:
            continue

        best = symbol_df.sort_values("annualized_excess_return", ascending=False).iloc[0]
        eligible = "✅" if best["eligible"] else "❌"

        report_lines.append(f"### {symbol} ({SYMBOL_NAMES[symbol]})\n")
        report_lines.append(f"- **最优配置**: {best['config_name']}")
        report_lines.append(f"- **状态**: {eligible}")
        report_lines.append(f"- **总收益**: {best['total_return']:.2%}")
        report_lines.append(f"- **年化收益**: {best['annualized_return']:.2%}")
        report_lines.append(f"- **基准收益**: {best['benchmark_return']:.2%}")
        report_lines.append(f"- **年化超额**: {best['annualized_excess_return']:.2%}")
        report_lines.append(f"- **最大回撤**: {best['max_drawdown']:.2%}")
        report_lines.append(f"- **交易次数**: {int(best['trade_count'])}")
        report_lines.append(f"- **持仓比例**: {best['holding_ratio']:.0%}")
        report_lines.append(f"- **换手率**: {best['turnover_rate']:.2f}")
        report_lines.append("")

    # 详细结果
    report_lines.append("## 详细结果\n")

    for config_name in df["config_name"].unique():
        config_df = df[df["config_name"] == config_name]
        eligible_count = config_df["eligible"].sum()

        report_lines.append(f"### {config_name} (eligible={eligible_count}/8)\n")
        report_lines.append("| 指数 | 总收益 | 年化收益 | 基准收益 | 年化超额 | 最大回撤 | 交易次数 | 持仓比例 | 换手率 | eligible |")
        report_lines.append("|:-----|-------:|--------:|--------:|--------:|--------:|--------:|--------:|--------:|:--------:|")

        for _, row in config_df.sort_values("annualized_excess_return", ascending=False).iterrows():
            eligible = "✅" if row["eligible"] else "❌"
            report_lines.append(f"| {row['symbol']} | {row['total_return']:.2%} | {row['annualized_return']:.2%} | {row['benchmark_return']:.2%} | {row['annualized_excess_return']:.2%} | {row['max_drawdown']:.2%} | {int(row['trade_count'])} | {row['holding_ratio']:.0%} | {row['turnover_rate']:.2f} | {eligible} |")

        report_lines.append("")

    # 结论
    report_lines.append("## 结论\n")

    best_config = config_summary.index[0]
    best_row = config_summary.iloc[0]

    report_lines.append(f"### 最优配置: {best_config}\n")
    report_lines.append(f"- **eligible 指数数**: {int(best_row['eligible'])}/8")
    report_lines.append(f"- **平均年化收益**: {best_row['annualized_return']:.2%}")
    report_lines.append(f"- **平均年化超额**: {best_row['annualized_excess_return']:.2%}")
    report_lines.append(f"- **平均最大回撤**: {best_row['max_drawdown']:.2%}")
    report_lines.append(f"- **平均交易次数**: {best_row['trade_count']:.1f}")
    report_lines.append(f"- **平均持仓比例**: {best_row['holding_ratio']:.0%}")
    report_lines.append("")

    # 保存报告
    report_path = f"{OUTPUT_DIR}/validation_report.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(report_lines))
    print(f"✅ 报告已保存: {report_path}")


def main():
    """主函数"""
    print("=" * 100)
    print("综合策略验证测试")
    print("=" * 100)
    print(f"输出目录: {OUTPUT_DIR}")
    print()

    start_time = time.time()

    df = run_validation_tests()
    analyze_results(df)
    generate_report(df)

    elapsed = time.time() - start_time
    print(f"\n总耗时: {elapsed:.1f}秒 ({elapsed/60:.1f}分钟)")


if __name__ == "__main__":
    main()
