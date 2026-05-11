#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Wyckoff+MA+LPPL 融合策略优化脚本

目标：
- 以Wyckoff分析作为主力模型
- 结合MA策略进行趋势确认
- 结合LPPL策略进行泡沫/底部检测
- 针对上证50和沪深300优化拟合准确率、收益率和回撤率

基于分析结果的关键发现：
1. Wyckoff最佳配置：d400_w120_m40（日线400天，周线120周，月线40月）
2. markdown阶段准确率最高（51.51%），但收益为负
3. accumulation阶段收益最高（800天窗口：5.61%）
4. 置信度B级收益最高（6.39%）
5. 多周期weekly_daily_aligned收益最好（1.48%）
"""

import os
import sys
import time
import warnings
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
warnings.filterwarnings("ignore")

# 常量定义
SYMBOLS = ["000016.SH", "000300.SH"]  # 上证50和沪深300

SYMBOL_NAMES = {
    "000016.SH": "上证50",
    "000300.SH": "沪深300",
}

OUTPUT_DIR = "output/wyckoff_ma_lppl_fusion"
START_DATE = "2020-01-01"
END_DATE = "2026-03-27"


# ============================================================
# LPPL 模块
# ============================================================

def lppl_func(t, tc, m, w, a, b, c, phi):
    """LPPL模型函数"""
    tau = tc - t
    tau = np.maximum(tau, 1e-8)
    return a + b * (tau ** m) + c * (tau ** m) * np.cos(w * np.log(tau) + phi)


def calculate_lppl_risk(close_prices: pd.Series, window: int = 250) -> Dict[str, float]:
    """计算LPPL风险指标"""
    if len(close_prices) < window:
        return {"rmse": 1.0, "m": 0.0, "w": 0.0, "days_to_crash": 9999, "risk_level": "unknown"}
    
    prices = close_prices.tail(window).values
    t = np.arange(len(prices))
    log_prices = np.log(prices)
    
    # 简化的LPPL拟合（使用OLS近似）
    try:
        # 计算对数价格的趋势
        slope = np.polyfit(t, log_prices, 1)[0]
        
        # 计算波动率
        returns = np.diff(log_prices)
        volatility = np.std(returns)
        
        # 计算偏离度
        trend = np.polyval(np.polyfit(t, log_prices, 1), t)
        deviation = log_prices - trend
        max_deviation = np.max(np.abs(deviation))
        
        # 简化的风险评估
        rmse = volatility * np.sqrt(252)  # 年化波动率
        
        # 估算m和w参数（基于偏离度模式）
        m_est = 0.5 + 0.3 * (1 - max_deviation / 0.5)  # 偏离度越小，m越接近0.8
        w_est = 6 + 4 * volatility / 0.02  # 波动率越大，w越大
        
        # 估算距崩盘天数（简化模型）
        if slope > 0:
            days_to_crash = int(250 * (1 - slope / 0.001))
        else:
            days_to_crash = 50  # 负斜率，风险较高
        
        days_to_crash = max(10, min(500, days_to_crash))
        
        # 风险等级
        if rmse < 0.15 and m_est < 0.6:
            risk_level = "low"
        elif rmse < 0.25 and m_est < 0.8:
            risk_level = "medium"
        else:
            risk_level = "high"
        
        return {
            "rmse": rmse,
            "m": m_est,
            "w": w_est,
            "days_to_crash": days_to_crash,
            "risk_level": risk_level,
            "slope": slope,
            "volatility": volatility,
        }
    except Exception:
        return {"rmse": 1.0, "m": 0.0, "w": 0.0, "days_to_crash": 9999, "risk_level": "unknown"}


# ============================================================
# MA 模块
# ============================================================

def compute_ma_signals(df: pd.DataFrame, config: Dict[str, Any]) -> pd.DataFrame:
    """计算MA信号"""
    enriched = df.copy()
    
    fast_ma = config.get("fast_ma", 5)
    slow_ma = config.get("slow_ma", 60)
    regime_ma = config.get("regime_ma", 120)
    
    # 计算均线
    enriched["ma_fast"] = enriched["close"].rolling(fast_ma, min_periods=1).mean()
    enriched["ma_slow"] = enriched["close"].rolling(slow_ma, min_periods=1).mean()
    enriched["ma_regime"] = enriched["close"].rolling(regime_ma, min_periods=1).mean()
    
    # 交叉信号
    enriched["ma_fast_prev"] = enriched["ma_fast"].shift(1)
    enriched["ma_slow_prev"] = enriched["ma_slow"].shift(1)
    
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
    
    # Regime 过滤
    enriched["regime_ratio"] = enriched["close"] / enriched["ma_regime"]
    enriched["regime_bullish"] = enriched["regime_ratio"] >= 1.0
    
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
    
    # MA信号评分
    enriched["ma_score"] = 0.0
    enriched.loc[enriched["bullish_cross"], "ma_score"] = 1.0
    enriched.loc[enriched["bearish_cross"], "ma_score"] = -1.0
    enriched.loc[enriched["uptrend"] & ~enriched["bullish_cross"], "ma_score"] = 0.3
    enriched.loc[enriched["downtrend"] & ~enriched["bearish_cross"], "ma_score"] = -0.3
    
    # Regime调整
    enriched["ma_score_adjusted"] = enriched["ma_score"]
    enriched.loc[~enriched["regime_bullish"] & (enriched["ma_score"] > 0), "ma_score_adjusted"] *= 0.5
    enriched.loc[enriched["regime_bullish"] & (enriched["ma_score"] < 0), "ma_score_adjusted"] *= 0.5
    
    return enriched


# ============================================================
# Wyckoff 模块（简化版）
# ============================================================

def detect_wyckoff_phase(df: pd.DataFrame, lookback: int = 400) -> Dict[str, Any]:
    """检测Wyckoff阶段（简化版）"""
    if len(df) < lookback:
        return {"phase": "unknown", "confidence": "D", "mtf": "mixed"}
    
    recent = df.tail(lookback)
    close = recent["close"].values
    volume = recent["volume"].values if "volume" in recent.columns else np.ones(len(recent))
    
    # 计算价格特征
    price_change = (close[-1] - close[0]) / close[0]
    volatility = np.std(np.diff(np.log(close)))
    
    # 计算成交量特征
    avg_volume = np.mean(volume)
    recent_volume = np.mean(volume[-20:])
    volume_ratio = recent_volume / avg_volume if avg_volume > 0 else 1.0
    
    # 计算趋势强度
    ma20 = np.mean(close[-20:])
    ma60 = np.mean(close[-60:])
    ma120 = np.mean(close[-120:]) if len(close) >= 120 else ma60
    
    trend_up = ma20 > ma60 > ma120
    trend_down = ma20 < ma60 < ma120
    
    # 阶段检测逻辑
    if trend_up and price_change > 0.1:
        phase = "markup"
        confidence = "C"
    elif trend_down and price_change < -0.1:
        phase = "markdown"
        confidence = "C"
    elif abs(price_change) < 0.05 and volatility < 0.015:
        # 横盘整理
        if close[-1] > np.mean(close[-60:]):
            phase = "accumulation"
            confidence = "D"
        else:
            phase = "distribution"
            confidence = "D"
    else:
        phase = "unknown"
        confidence = "D"
    
    # MTF对齐检测
    if trend_up and volume_ratio > 1.2:
        mtf = "fully_aligned"
    elif trend_up or trend_down:
        mtf = "higher_timeframe_aligned"
    else:
        mtf = "mixed"
    
    # Spring检测（底部反弹）
    spring_detected = False
    if len(close) >= 50:
        recent_low = np.min(close[-50:])
        if close[-1] > recent_low * 1.05 and close[-2] <= recent_low * 1.02:
            spring_detected = True
    
    return {
        "phase": phase,
        "confidence": confidence,
        "mtf": mtf,
        "spring_detected": spring_detected,
        "price_change": price_change,
        "volatility": volatility,
        "volume_ratio": volume_ratio,
        "trend_up": trend_up,
        "trend_down": trend_down,
    }


# ============================================================
# 融合策略
# ============================================================

def calculate_fusion_score(
    wyckoff_result: Dict[str, Any],
    ma_score: float,
    lppl_result: Dict[str, Any],
    config: Dict[str, Any],
) -> Tuple[float, str]:
    """计算融合评分"""
    
    # Wyckoff权重
    wyckoff_weight = config.get("wyckoff_weight", 0.5)
    ma_weight = config.get("ma_weight", 0.3)
    lppl_weight = config.get("lppl_weight", 0.2)
    
    # Wyckoff评分
    phase = wyckoff_result.get("phase", "unknown")
    confidence = wyckoff_result.get("confidence", "D")
    mtf = wyckoff_result.get("mtf", "mixed")
    spring = wyckoff_result.get("spring_detected", False)
    
    # 阶段评分
    phase_scores = {
        "accumulation": 0.8 if spring else 0.4,
        "markup": 0.6,
        "distribution": -0.4,
        "markdown": -0.6,
        "unknown": 0.0,
    }
    wyckoff_score = phase_scores.get(phase, 0.0)
    
    # 置信度调整
    confidence_mult = {"B": 1.2, "C": 1.0, "D": 0.8, "A": 0.5}.get(confidence, 0.8)
    wyckoff_score *= confidence_mult
    
    # MTF调整
    mtf_mult = {
        "fully_aligned": 1.2,
        "higher_timeframe_aligned": 1.0,
        "weekly_daily_aligned": 0.8,
        "mixed": 0.6,
    }.get(mtf, 0.6)
    wyckoff_score *= mtf_mult
    
    # LPPL评分
    lppl_risk = lppl_result.get("risk_level", "unknown")
    lppl_rmse = lppl_result.get("rmse", 1.0)
    
    lppl_score = 0.0
    if lppl_risk == "low":
        lppl_score = 0.5
    elif lppl_risk == "medium":
        lppl_score = 0.0
    elif lppl_risk == "high":
        lppl_score = -0.5
    
    # RMSE调整
    if lppl_rmse < 0.15:
        lppl_score *= 1.2
    elif lppl_rmse > 0.25:
        lppl_score *= 0.8
    
    # 融合评分
    total_score = (
        wyckoff_score * wyckoff_weight
        + ma_score * ma_weight
        + lppl_score * lppl_weight
    )
    
    # 生成理由
    reasons = []
    if phase in ["accumulation", "markup"]:
        reasons.append(f"Wyckoff:{phase}")
    if ma_score > 0:
        reasons.append("MA:多头")
    elif ma_score < 0:
        reasons.append("MA:空头")
    if lppl_risk == "low":
        reasons.append("LPPL:低风险")
    elif lppl_risk == "high":
        reasons.append("LPPL:高风险")
    
    reason = " | ".join(reasons) if reasons else "无明确信号"
    
    return total_score, reason


def run_fusion_backtest(
    df: pd.DataFrame,
    config: Dict[str, Any],
    start_date: str = START_DATE,
    end_date: str = END_DATE,
) -> Tuple[pd.DataFrame, pd.DataFrame, Dict[str, Any]]:
    """运行融合策略回测"""
    
    # 标准化数据
    price_df = df.copy()
    price_df["date"] = pd.to_datetime(price_df["date"])
    price_df = price_df.sort_values("date").reset_index(drop=True)
    
    if "open" not in price_df.columns:
        price_df["open"] = price_df["close"]
    if "high" not in price_df.columns:
        price_df["high"] = price_df[["open", "close"]].max(axis=1)
    if "low" not in price_df.columns:
        price_df["low"] = price_df[["open", "close"]].min(axis=1)
    if "volume" not in price_df.columns:
        price_df["volume"] = 0.0
    
    # 过滤日期
    start_ts = pd.to_datetime(start_date)
    end_ts = pd.to_datetime(end_date)
    price_df = price_df[(price_df["date"] >= start_ts) & (price_df["date"] <= end_ts)]
    
    # 计算MA信号
    price_df = compute_ma_signals(price_df, config)
    
    # 预热期
    warmup = max(config.get("slow_ma", 60), config.get("regime_ma", 120), 250)
    price_df = price_df.iloc[warmup:].reset_index(drop=True)
    
    if len(price_df) < 100:
        return pd.DataFrame(), pd.DataFrame(), {}
    
    # 回测参数
    initial_capital = 1_000_000.0
    buy_fee = 0.0003
    sell_fee = 0.0003
    slippage = 0.0005
    
    # 策略参数
    buy_threshold = config.get("buy_threshold", 0.3)
    sell_threshold = config.get("sell_threshold", -0.2)
    cooldown_days = config.get("cooldown_days", 10)
    drawdown_stop = config.get("drawdown_stop", 0.15)
    wyckoff_lookback = config.get("wyckoff_lookback", 400)
    lppl_window = config.get("lppl_window", 250)
    
    # 初始化
    cash = initial_capital
    shares = 0
    current_position = 0.0
    cooldown_remaining = 0
    
    records = []
    trades = []
    
    for idx in range(len(price_df)):
        row = price_df.iloc[idx]
        
        # 获取历史数据用于Wyckoff和LPPL分析
        if idx < wyckoff_lookback:
            historical = price_df.iloc[:idx+1]
        else:
            historical = price_df.iloc[idx-wyckoff_lookback+1:idx+1]
        
        # Wyckoff分析
        wyckoff_result = detect_wyckoff_phase(historical, wyckoff_lookback)
        
        # LPPL分析
        if idx >= lppl_window:
            lppl_prices = price_df["close"].iloc[idx-lppl_window+1:idx+1]
            lppl_result = calculate_lppl_risk(lppl_prices, lppl_window)
        else:
            lppl_result = {"rmse": 1.0, "m": 0.0, "w": 0.0, "days_to_crash": 9999, "risk_level": "unknown"}
        
        # MA评分
        ma_score = float(row.get("ma_score_adjusted", 0.0))
        
        # 融合评分
        fusion_score, reason = calculate_fusion_score(
            wyckoff_result, ma_score, lppl_result, config
        )
        
        # ATR
        atr_ratio = float(row.get("atr_ratio", 1.0))
        
        # 回撤
        if idx >= 120:
            peak = price_df["close"].iloc[idx-120:idx+1].max()
            drawdown = (row["close"] / peak) - 1.0
        else:
            drawdown = 0.0
        
        # 信号逻辑
        next_position = current_position
        
        # 冷却期检查
        if cooldown_remaining > 0:
            cooldown_remaining -= 1
            action_reason = f"冷却期 {cooldown_remaining}天"
        # 回撤止损
        elif drawdown <= -drawdown_stop:
            next_position = 0.0
            action_reason = f"回撤止损 {drawdown:.1%}"
            cooldown_remaining = cooldown_days
        # 买入信号
        elif fusion_score >= buy_threshold and current_position < 1.0:
            next_position = min(current_position + 0.5, 1.0)
            action_reason = f"买入 {reason} 评分={fusion_score:.2f}"
            cooldown_remaining = cooldown_days
        # 卖出信号
        elif fusion_score <= sell_threshold and current_position > 0.0:
            next_position = max(current_position - 0.5, 0.0)
            action_reason = f"卖出 {reason} 评分={fusion_score:.2f}"
            cooldown_remaining = cooldown_days
        else:
            action_reason = f"持有 评分={fusion_score:.2f}"
        
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
                            "score": fusion_score,
                            "reason": reason,
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
                    "score": fusion_score,
                    "reason": reason,
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
            "wyckoff_phase": wyckoff_result.get("phase", "unknown"),
            "wyckoff_confidence": wyckoff_result.get("confidence", "D"),
            "ma_score": ma_score,
            "lppl_risk": lppl_result.get("risk_level", "unknown"),
            "fusion_score": fusion_score,
            "reason": action_reason,
        })
    
    # 生成结果
    result_df = pd.DataFrame(records)
    trades_df = pd.DataFrame(trades) if trades else pd.DataFrame(columns=["date", "action", "price", "shares", "score", "reason"])
    
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
    
    # Wyckoff阶段统计
    phase_stats = result_df.groupby("wyckoff_phase").agg({
        "daily_return": ["mean", "count"],
    }).reset_index()
    phase_stats.columns = ["phase", "avg_return", "count"]
    
    # 准确率计算（阶段与收益方向一致性）
    correct_predictions = 0
    total_predictions = 0
    for _, row in result_df.iterrows():
        phase = row["wyckoff_phase"]
        daily_return = row["daily_return"]
        
        if pd.isna(daily_return):
            continue
        
        total_predictions += 1
        if phase in ["accumulation", "markup"] and daily_return > 0:
            correct_predictions += 1
        elif phase in ["distribution", "markdown"] and daily_return <= 0:
            correct_predictions += 1
        elif phase == "unknown":
            correct_predictions += 0.5  # unknown算半对
    
    accuracy = correct_predictions / total_predictions if total_predictions > 0 else 0.0
    
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
        "accuracy": accuracy,
        "eligible": (annualized_excess > 0 and max_drawdown > -0.30 and trade_count >= 3),
    }
    
    return result_df, trades_df, summary


# ============================================================
# 测试执行
# ============================================================

def get_configs() -> List[Dict[str, Any]]:
    """获取测试配置"""
    return [
        {
            "name": "Wyckoff主导+MA确认",
            "description": "Wyckoff权重0.6, MA权重0.3, LPPL权重0.1",
            "wyckoff_weight": 0.6,
            "ma_weight": 0.3,
            "lppl_weight": 0.1,
            "fast_ma": 5,
            "slow_ma": 60,
            "regime_ma": 120,
            "atr_period": 14,
            "atr_ma_window": 40,
            "buy_threshold": 0.3,
            "sell_threshold": -0.2,
            "cooldown_days": 10,
            "drawdown_stop": 0.15,
            "wyckoff_lookback": 400,
            "lppl_window": 250,
        },
        {
            "name": "Wyckoff主导+LPPL确认",
            "description": "Wyckoff权重0.5, MA权重0.2, LPPL权重0.3",
            "wyckoff_weight": 0.5,
            "ma_weight": 0.2,
            "lppl_weight": 0.3,
            "fast_ma": 5,
            "slow_ma": 60,
            "regime_ma": 120,
            "atr_period": 14,
            "atr_ma_window": 40,
            "buy_threshold": 0.3,
            "sell_threshold": -0.2,
            "cooldown_days": 10,
            "drawdown_stop": 0.15,
            "wyckoff_lookback": 400,
            "lppl_window": 250,
        },
        {
            "name": "均衡融合",
            "description": "Wyckoff权重0.4, MA权重0.35, LPPL权重0.25",
            "wyckoff_weight": 0.4,
            "ma_weight": 0.35,
            "lppl_weight": 0.25,
            "fast_ma": 5,
            "slow_ma": 60,
            "regime_ma": 120,
            "atr_period": 14,
            "atr_ma_window": 40,
            "buy_threshold": 0.25,
            "sell_threshold": -0.15,
            "cooldown_days": 15,
            "drawdown_stop": 0.18,
            "wyckoff_lookback": 400,
            "lppl_window": 250,
        },
        {
            "name": "保守型融合",
            "description": "高阈值, 长冷却期",
            "wyckoff_weight": 0.5,
            "ma_weight": 0.3,
            "lppl_weight": 0.2,
            "fast_ma": 10,
            "slow_ma": 120,
            "regime_ma": 180,
            "atr_period": 20,
            "atr_ma_window": 60,
            "buy_threshold": 0.4,
            "sell_threshold": -0.3,
            "cooldown_days": 20,
            "drawdown_stop": 0.12,
            "wyckoff_lookback": 600,
            "lppl_window": 250,
        },
    ]


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
        
        result_df, trades_df, summary = run_fusion_backtest(df, config)
        
        if result_df.empty:
            return None
        
        return {
            "symbol": symbol,
            "symbol_name": SYMBOL_NAMES.get(symbol, symbol),
            "config_name": config["name"],
            **summary,
        }
    except Exception as e:
        print(f"  [ERROR] {symbol}: {e}")
        return None


def run_optimization():
    """运行优化测试"""
    print("=" * 100)
    print("Wyckoff+MA+LPPL 融合策略优化")
    print("=" * 100)
    print(f"测试周期: {START_DATE} ~ {END_DATE}")
    print(f"测试指数: {', '.join([SYMBOL_NAMES.get(s, s) for s in SYMBOLS])}")
    print()
    
    configs = get_configs()
    all_results = []
    
    for config in configs:
        print(f"\n{'='*80}")
        print(f"测试配置: {config['name']}")
        print(f"  描述: {config['description']}")
        print(f"  权重: Wyckoff={config['wyckoff_weight']}, MA={config['ma_weight']}, LPPL={config['lppl_weight']}")
        print(f"{'='*80}")
        
        results = []
        for symbol in SYMBOLS:
            print(f"  {symbol} ({SYMBOL_NAMES[symbol]})...", end=" ", flush=True)
            result = run_single_test(symbol, config)
            if result:
                results.append(result)
                eligible = "✅" if result["eligible"] else "❌"
                print(f"{eligible} 年化={result['annualized_return']:.2%}, 超额={result['annualized_excess_return']:.2%}, 回撤={result['max_drawdown']:.2%}, 准确率={result['accuracy']:.1%}")
            else:
                print("FAILED")
        
        if results:
            df = pd.DataFrame(results)
            all_results.append(df)
            
            # 打印配置汇总
            print(f"\n  配置汇总:")
            print(f"    eligible: {df['eligible'].sum()}/{len(results)}")
            print(f"    平均年化收益: {df['annualized_return'].mean():.2%}")
            print(f"    平均年化超额: {df['annualized_excess_return'].mean():.2%}")
            print(f"    平均回撤: {df['max_drawdown'].mean():.2%}")
            print(f"    平均准确率: {df['accuracy'].mean():.1%}")
    
    # 保存结果
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    combined_df = pd.concat(all_results, ignore_index=True)
    combined_df.to_csv(f"{OUTPUT_DIR}/optimization_results.csv", index=False)
    
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
        "accuracy": "mean",
        "trade_count": "mean",
        "turnover_rate": "mean",
    }).sort_values(["eligible", "annualized_excess_return"], ascending=False)
    
    print("\n--- 配置排名 ---\n")
    print(f"{'配置名称':<25} {'eligible':<10} {'平均年化':<10} {'平均超额':<10} {'平均回撤':<10} {'准确率':<10} {'平均交易':<10}")
    print("-" * 85)
    
    for config_name, row in config_summary.iterrows():
        print(f"{config_name:<25} {int(row['eligible'])}/2{'':<6} {row['annualized_return']:.2%}{'':<4} {row['annualized_excess_return']:.2%}{'':<4} {row['max_drawdown']:.2%}{'':<4} {row['accuracy']:.1%}{'':<4} {row['trade_count']:.1f}")
    
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
        print(f"  {eligible} 年化={best['annualized_return']:.2%}, 超额={best['annualized_excess_return']:.2%}, 回撤={best['max_drawdown']:.2%}, 准确率={best['accuracy']:.1%}")
        print()


def generate_report(df: pd.DataFrame):
    """生成报告"""
    print("\n" + "=" * 100)
    print("生成报告")
    print("=" * 100)
    
    report_lines = []
    report_lines.append("# Wyckoff+MA+LPPL 融合策略优化报告")
    report_lines.append(f"\n**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report_lines.append(f"\n**测试周期**: {START_DATE} ~ {END_DATE}")
    report_lines.append(f"\n**测试指数**: {', '.join([SYMBOL_NAMES.get(s, s) for s in SYMBOLS])}")
    report_lines.append("\n---\n")
    
    report_lines.append("## 策略设计\n")
    report_lines.append("### 核心理念\n")
    report_lines.append("- **Wyckoff**: 主力模型，识别市场阶段（accumulation/markup/distribution/markdown）")
    report_lines.append("- **MA**: 趋势确认，提供短期买卖信号")
    report_lines.append("- **LPPL**: 风险评估，检测泡沫和底部")
    report_lines.append("")
    
    report_lines.append("### 融合权重\n")
    report_lines.append("| 配置名称 | Wyckoff权重 | MA权重 | LPPL权重 | 买入阈值 | 卖出阈值 |")
    report_lines.append("|:---------|:-----------:|:------:|:--------:|:--------:|:--------:|")
    
    configs = get_configs()
    for config in configs:
        report_lines.append(f"| {config['name']} | {config['wyckoff_weight']} | {config['ma_weight']} | {config['lppl_weight']} | {config['buy_threshold']} | {config['sell_threshold']} |")
    report_lines.append("")
    
    # 配置排名
    config_summary = df.groupby("config_name").agg({
        "eligible": "sum",
        "annualized_return": "mean",
        "annualized_excess_return": "mean",
        "max_drawdown": "mean",
        "accuracy": "mean",
        "trade_count": "mean",
        "turnover_rate": "mean",
    }).sort_values(["eligible", "annualized_excess_return"], ascending=False)
    
    report_lines.append("## 配置排名\n")
    report_lines.append("| 配置名称 | eligible | 平均年化收益 | 平均年化超额 | 平均回撤 | 准确率 | 平均交易 | 平均换手 |")
    report_lines.append("|:---------|:--------:|-----------:|-----------:|--------:|:------:|--------:|--------:|")
    
    for config_name, row in config_summary.iterrows():
        report_lines.append(f"| {config_name} | {int(row['eligible'])}/2 | {row['annualized_return']:.2%} | {row['annualized_excess_return']:.2%} | {row['max_drawdown']:.2%} | {row['accuracy']:.1%} | {row['trade_count']:.1f} | {row['turnover_rate']:.2f} |")
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
        report_lines.append(f"- **准确率**: {best['accuracy']:.1%}")
        report_lines.append(f"- **交易次数**: {int(best['trade_count'])}")
        report_lines.append(f"- **持仓比例**: {best['holding_ratio']:.0%}")
        report_lines.append(f"- **换手率**: {best['turnover_rate']:.2f}")
        report_lines.append("")
    
    # 结论
    report_lines.append("## 结论\n")
    
    best_config = config_summary.index[0]
    best_row = config_summary.iloc[0]
    
    report_lines.append(f"### 最优配置: {best_config}\n")
    report_lines.append(f"- **eligible 指数数**: {int(best_row['eligible'])}/2")
    report_lines.append(f"- **平均年化收益**: {best_row['annualized_return']:.2%}")
    report_lines.append(f"- **平均年化超额**: {best_row['annualized_excess_return']:.2%}")
    report_lines.append(f"- **平均最大回撤**: {best_row['max_drawdown']:.2%}")
    report_lines.append(f"- **平均准确率**: {best_row['accuracy']:.1%}")
    report_lines.append("")
    
    report_lines.append("### 优化建议\n")
    report_lines.append("1. **Wyckoff阶段优化**: accumulation阶段信号最有效，应优先考虑")
    report_lines.append("2. **MA确认**: 使用MA交叉作为入场确认，提高信号质量")
    report_lines.append("3. **LPPL风险控制**: 高风险时降低仓位，低风险时增加仓位")
    report_lines.append("4. **冷却期**: 适当延长冷却期，避免频繁交易")
    report_lines.append("5. **止损**: 设置合理止损阈值，控制回撤")
    report_lines.append("")
    
    # 保存报告
    report_path = f"{OUTPUT_DIR}/optimization_report.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(report_lines))
    print(f"✅ 报告已保存: {report_path}")


def main():
    """主函数"""
    print("=" * 100)
    print("Wyckoff+MA+LPPL 融合策略优化")
    print("=" * 100)
    print(f"输出目录: {OUTPUT_DIR}")
    print()
    
    start_time = time.time()
    
    df = run_optimization()
    analyze_results(df)
    generate_report(df)
    
    elapsed = time.time() - start_time
    print(f"\n总耗时: {elapsed:.1f}秒 ({elapsed/60:.1f}分钟)")


if __name__ == "__main__":
    main()
