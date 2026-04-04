#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
个人投资者优化方案 v2：趋势跟踪 + 回撤保护 + 低频交易

改进：
1. 修复 holding_ratio 使用实际持仓计算
2. 添加冷却期（cooldown_days）
3. 添加信号确认（confirm_days）
4. 长周期均线减少频繁交易
"""

import os
import sys
import time
import warnings
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

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
OUTPUT_DIR = "output/personal_investor_optimization_v2"


def compute_indicators(df: pd.DataFrame, config: Dict[str, Any]) -> pd.DataFrame:
    """计算技术指标"""
    enriched = df.copy()
    
    # 长周期均线
    ma_fast = config.get("ma_fast", 60)
    ma_slow = config.get("ma_slow", 120)
    
    enriched["ma_fast"] = enriched["close"].rolling(ma_fast, min_periods=1).mean()
    enriched["ma_slow"] = enriched["close"].rolling(ma_slow, min_periods=1).mean()
    enriched["ma_fast_prev"] = enriched["ma_fast"].shift(1)
    enriched["ma_slow_prev"] = enriched["ma_slow"].shift(1)
    
    # 趋势状态
    enriched["uptrend"] = enriched["ma_fast"] > enriched["ma_slow"]
    enriched["downtrend"] = enriched["ma_fast"] < enriched["ma_slow"]
    
    # 交叉信号
    enriched["bullish_cross"] = (
        (enriched["ma_fast"] > enriched["ma_slow"])
        & (enriched["ma_fast_prev"].fillna(enriched["ma_fast"]) <= enriched["ma_slow_prev"].fillna(enriched["ma_slow"]))
    )
    enriched["bearish_cross"] = (
        (enriched["ma_fast"] < enriched["ma_slow"])
        & (enriched["ma_fast_prev"].fillna(enriched["ma_fast"]) >= enriched["ma_slow_prev"].fillna(enriched["ma_slow"]))
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
    
    # 回撤计算
    drawdown_window = config.get("drawdown_window", 120)
    enriched["rolling_peak"] = enriched["close"].rolling(drawdown_window, min_periods=1).max()
    enriched["drawdown"] = (enriched["close"] / enriched["rolling_peak"]) - 1.0
    
    return enriched


def run_backtest(
    df: pd.DataFrame,
    config: Dict[str, Any],
    start_date: str = "2020-01-01",
    end_date: str = "2026-03-27",
) -> Tuple[pd.DataFrame, pd.DataFrame, Dict[str, Any]]:
    """运行回测"""
    from src.investment.backtest import _normalize_price_frame
    
    # 标准化数据
    price_df = _normalize_price_frame(df)
    price_df = compute_indicators(price_df, config)
    
    # 过滤日期
    start_ts = pd.to_datetime(start_date)
    end_ts = pd.to_datetime(end_date)
    price_df = price_df[(price_df["date"] >= start_ts) & (price_df["date"] <= end_ts)]
    
    # 预热期
    warmup = max(250, config.get("atr_ma_window", 40), config.get("ma_slow", 120))
    price_df = price_df.iloc[warmup:]
    
    if len(price_df) < 100:
        return pd.DataFrame(), pd.DataFrame(), {}
    
    # 回测参数
    initial_capital = config.get("initial_capital", 1_000_000.0)
    buy_fee = config.get("buy_fee", 0.0003)
    sell_fee = config.get("sell_fee", 0.0003)
    slippage = config.get("slippage", 0.0005)
    
    # 交易控制参数
    cooldown_days = config.get("cooldown_days", 20)  # 冷却期
    confirm_days = config.get("confirm_days", 3)  # 信号确认天数
    
    # 回撤保护阈值
    drawdown_reduce = config.get("drawdown_reduce_threshold", -0.10)
    drawdown_exit = config.get("drawdown_exit_threshold", -0.20)
    
    # ATR 阈值
    buy_volatility_cap = config.get("buy_volatility_cap", 1.05)
    vol_breakout_mult = config.get("vol_breakout_mult", 1.15)
    
    # 初始化
    cash = initial_capital
    shares = 0
    current_position = 0.0
    cooldown_remaining = 0
    buy_signal_count = 0
    sell_signal_count = 0
    
    records = []
    trades = []
    actual_holding_days = 0  # 实际持仓天数
    
    for idx, row in price_df.iterrows():
        atr_ratio = float(row["atr_ratio"])
        drawdown = float(row["drawdown"])
        uptrend = bool(row.get("uptrend", False))
        downtrend = bool(row.get("downtrend", False))
        
        # 信号计数（使用趋势状态而非交叉信号）
        # 买入信号：上涨趋势 + ATR 低波动
        if uptrend and atr_ratio <= buy_volatility_cap:
            buy_signal_count += 1
        else:
            buy_signal_count = 0
        
        # 卖出信号：下跌趋势 + ATR 高波动
        if downtrend and atr_ratio >= vol_breakout_mult:
            sell_signal_count += 1
        else:
            sell_signal_count = 0
        
        # 信号逻辑
        buy_confirmed = buy_signal_count >= confirm_days
        sell_confirmed = sell_signal_count >= confirm_days
        
        next_position = current_position
        reason = "持有"
        
        # 冷却期检查
        if cooldown_remaining > 0:
            cooldown_remaining -= 1
            reason = f"冷却期剩余 {cooldown_remaining} 天"
        
        # 回撤保护（最高优先级，不受冷却期限制）
        elif drawdown <= drawdown_exit:
            next_position = 0.0
            reason = f"回撤 {drawdown:.1%} 超过 {drawdown_exit:.0%}，清仓"
            cooldown_remaining = cooldown_days
        elif drawdown <= drawdown_reduce:
            next_position = max(0.0, current_position - 0.33)
            reason = f"回撤 {drawdown:.1%} 超过 {drawdown_reduce:.0%}，减仓"
            cooldown_remaining = cooldown_days
        
        # 趋势信号（需要确认）
        elif buy_confirmed and current_position < 1.0:
            next_position = min(current_position + 0.33, 1.0)
            reason = f"买入信号确认 {buy_signal_count} 天，加仓至 {next_position:.0%}"
            cooldown_remaining = cooldown_days
            buy_signal_count = 0
        
        elif sell_confirmed and current_position > 0.0:
            next_position = max(current_position - 0.33, 0.0)
            reason = f"卖出信号确认 {sell_signal_count} 天，减仓至 {next_position:.0%}"
            cooldown_remaining = cooldown_days
            sell_signal_count = 0
        
        # 执行交易
        portfolio_value_before_trade = cash + shares * row["close"]
        current_holdings_value = shares * row["close"]
        desired_holdings_value = portfolio_value_before_trade * next_position

        if desired_holdings_value > current_holdings_value + 1e-8 and next_position > 0:
            # 加仓
            add_value = desired_holdings_value - current_holdings_value
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
        
        elif desired_holdings_value < current_holdings_value - 1e-8 and shares > 0:
            # 减仓
            sell_value = current_holdings_value - desired_holdings_value
            sell_shares = min(shares, int(sell_value / row["close"] / 100) * 100)
            
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
        
        # 记录实际持仓状态
        portfolio_value = cash + shares * row["close"]
        has_actual_position = shares > 0
        current_position = (shares * row["close"] / portfolio_value) if portfolio_value > 0 else 0.0
        if has_actual_position:
            actual_holding_days += 1
        
        records.append({
            "date": row["date"],
            "close": row["close"],
            "target_position": next_position,
            "executed_position": current_position,
            "actual_shares": shares,
            "has_actual_position": has_actual_position,
            "cash": cash,
            "portfolio_value": portfolio_value,
            "drawdown": drawdown,
            "atr_ratio": atr_ratio,
            "reason": reason,
            "cooldown_remaining": cooldown_remaining,
        })
    
    # 生成结果
    result_df = pd.DataFrame(records)
    trades_df = pd.DataFrame(trades) if trades else pd.DataFrame(columns=["date", "action", "price", "shares"])
    
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
    
    # 换手率（与 src 主回测统一：累计成交额 / 初始资金）
    if len(trades_df) > 0 and "shares" in trades_df.columns and "price" in trades_df.columns:
        total_trade_value = (trades_df["shares"] * trades_df["price"]).sum()
        turnover_rate = total_trade_value / initial_capital if initial_capital > 0 else 0.0
    else:
        turnover_rate = 0.0
    
    # 实际持仓比例（基于实际持仓股数）
    holding_ratio = actual_holding_days / len(result_df)
    
    summary = {
        "total_return": total_return,
        "benchmark_return": benchmark_return,
        "annualized_return": annualized_return,
        "annualized_benchmark": annualized_benchmark,
        "annualized_excess_return": annualized_excess,
        "max_drawdown": max_drawdown,
        "trade_count": trade_count,
        "turnover_rate": turnover_rate,
        "actual_holding_days": actual_holding_days,
        "holding_ratio": holding_ratio,
        "eligible": (annualized_excess > 0 and max_drawdown > -0.35 and trade_count >= 3),
    }
    
    return result_df, trades_df, summary


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
        
        result_df, trades_df, summary = run_backtest(df, config)
        
        if result_df.empty:
            return None
        
        return {
            "symbol": symbol,
            "symbol_name": SYMBOL_NAMES.get(symbol, symbol),
            **summary,
        }
    except Exception as e:
        print(f"  [ERROR] {symbol}: {e}")
        return None


def test_low_frequency_strategy():
    """测试低频交易策略"""
    print("=" * 100)
    print("个人投资者策略测试 v2：低频交易 + 回撤保护")
    print("=" * 100)
    
    # 测试配置
    configs = [
        {
            "name": "长周期60/120_冷却20天",
            "ma_fast": 60,
            "ma_slow": 120,
            "atr_period": 14,
            "atr_ma_window": 40,
            "cooldown_days": 20,
            "confirm_days": 3,
            "drawdown_reduce_threshold": -0.10,
            "drawdown_exit_threshold": -0.20,
            "buy_volatility_cap": 1.05,
            "vol_breakout_mult": 1.15,
        },
        {
            "name": "长周期60/120_冷却30天",
            "ma_fast": 60,
            "ma_slow": 120,
            "atr_period": 14,
            "atr_ma_window": 40,
            "cooldown_days": 30,
            "confirm_days": 3,
            "drawdown_reduce_threshold": -0.10,
            "drawdown_exit_threshold": -0.20,
            "buy_volatility_cap": 1.05,
            "vol_breakout_mult": 1.15,
        },
        {
            "name": "超长周期120/250_冷却30天",
            "ma_fast": 120,
            "ma_slow": 250,
            "atr_period": 14,
            "atr_ma_window": 40,
            "cooldown_days": 30,
            "confirm_days": 3,
            "drawdown_reduce_threshold": -0.10,
            "drawdown_exit_threshold": -0.20,
            "buy_volatility_cap": 1.05,
            "vol_breakout_mult": 1.15,
        },
        {
            "name": "长周期60/120_冷却60天",
            "ma_fast": 60,
            "ma_slow": 120,
            "atr_period": 14,
            "atr_ma_window": 40,
            "cooldown_days": 60,
            "confirm_days": 3,
            "drawdown_reduce_threshold": -0.10,
            "drawdown_exit_threshold": -0.20,
            "buy_volatility_cap": 1.05,
            "vol_breakout_mult": 1.15,
        },
    ]
    
    # 添加基础参数
    for config in configs:
        config.update({
            "initial_capital": 1_000_000.0,
            "buy_fee": 0.0003,
            "sell_fee": 0.0003,
            "slippage": 0.0005,
            "initial_position": 0.0,
            "drawdown_window": 120,
        })
    
    all_results = []
    
    for config in configs:
        print(f"\n{'='*80}")
        print(f"测试配置: {config['name']}")
        print(f"  MA: {config['ma_fast']}/{config['ma_slow']}")
        print(f"  冷却期: {config['cooldown_days']}天")
        print(f"  确认天数: {config['confirm_days']}天")
        print(f"{'='*80}")
        
        results = []
        for symbol in SYMBOLS:
            print(f"  {symbol} ({SYMBOL_NAMES[symbol]})...", end=" ", flush=True)
            result = run_single_test(symbol, config)
            if result:
                result["config_name"] = config["name"]
                results.append(result)
                eligible = "✅" if result["eligible"] else "❌"
                print(f"{eligible} 年化={result['annualized_return']:.2%}, 超额={result['annualized_excess_return']:.2%}, 回撤={result['max_drawdown']:.2%}, 交易={result['trade_count']}, 持仓={result['holding_ratio']:.0%}")
            else:
                print("FAILED")
        
        df = pd.DataFrame(results)
        all_results.append(df)
        
        # 打印配置汇总
        print("\n  配置汇总:")
        print(f"    eligible: {df['eligible'].sum()}/8")
        print(f"    平均年化收益: {df['annualized_return'].mean():.2%}")
        print(f"    平均年化超额: {df['annualized_excess_return'].mean():.2%}")
        print(f"    平均回撤: {df['max_drawdown'].mean():.2%}")
        print(f"    平均交易次数: {df['trade_count'].mean():.1f}")
        print(f"    平均持仓比例: {df['holding_ratio'].mean():.0%}")
    
    # 保存结果
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    combined_df = pd.concat(all_results, ignore_index=True)
    combined_df.to_csv(f"{OUTPUT_DIR}/low_frequency_test.csv", index=False)
    
    return combined_df


def generate_report(df: pd.DataFrame):
    """生成报告"""
    print("\n" + "=" * 100)
    print("生成报告")
    print("=" * 100)
    
    report_lines = []
    report_lines.append("# 个人投资者策略测试报告 v2")
    report_lines.append(f"\n**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report_lines.append("\n**测试周期**: 2020-01-01 ~ 2026-03-27")
    report_lines.append("\n---\n")
    
    report_lines.append("## 改进点\n")
    report_lines.append("1. **holding_ratio 修复**：使用实际持仓股数计算，而非目标仓位")
    report_lines.append("2. **冷却期机制**：交易后进入冷却期，避免频繁交易")
    report_lines.append("3. **信号确认**：连续 N 天信号才触发交易")
    report_lines.append("4. **长周期均线**：使用 MA60/MA120 或 MA120/MA250 减少信号频率")
    report_lines.append("")
    
    report_lines.append("## 测试配置\n")
    report_lines.append("| 配置名称 | MA组合 | 冷却期 | 确认天数 |")
    report_lines.append("|:---------|:-------|:------:|:--------:|")
    for config_name in df["config_name"].unique():
        parts = config_name.split("_")
        ma_part = parts[0] if len(parts) > 0 else ""
        cooldown_part = parts[1] if len(parts) > 1 else ""
        report_lines.append(f"| {config_name} | {ma_part} | {cooldown_part} | 3 |")
    report_lines.append("")
    
    report_lines.append("## 测试结果\n")
    
    for config_name in df["config_name"].unique():
        config_df = df[df["config_name"] == config_name]
        eligible_count = config_df["eligible"].sum()
        
        report_lines.append(f"### {config_name} (eligible={eligible_count}/8)\n")
        report_lines.append("| 指数 | 总收益 | 年化收益 | 基准收益 | 年化超额 | 最大回撤 | 交易次数 | 持仓比例 | eligible |")
        report_lines.append("|:-----|-------:|--------:|--------:|--------:|--------:|--------:|--------:|:--------:|")
        
        for _, row in config_df.sort_values("annualized_excess_return", ascending=False).iterrows():
            eligible = "✅" if row["eligible"] else "❌"
            report_lines.append(f"| {row['symbol']} | {row['total_return']:.2%} | {row['annualized_return']:.2%} | {row['benchmark_return']:.2%} | {row['annualized_excess_return']:.2%} | {row['max_drawdown']:.2%} | {int(row['trade_count'])} | {row['holding_ratio']:.0%} | {eligible} |")
        
        report_lines.append("")
    
    # 最优配置分析
    report_lines.append("## 最优配置分析\n")
    
    # 按 eligible 降序，然后按年化超额降序
    best_configs = df.groupby("config_name").agg({
        "eligible": "sum",
        "annualized_return": "mean",
        "annualized_excess_return": "mean",
        "max_drawdown": "mean",
        "trade_count": "mean",
        "holding_ratio": "mean",
    }).sort_values(["eligible", "annualized_excess_return"], ascending=False)
    
    report_lines.append("| 配置名称 | eligible | 平均年化收益 | 平均年化超额 | 平均回撤 | 平均交易 | 平均持仓 |")
    report_lines.append("|:---------|:--------:|-----------:|-----------:|--------:|--------:|--------:|")
    for config_name, row in best_configs.iterrows():
        report_lines.append(f"| {config_name} | {int(row['eligible'])}/8 | {row['annualized_return']:.2%} | {row['annualized_excess_return']:.2%} | {row['max_drawdown']:.2%} | {row['trade_count']:.1f} | {row['holding_ratio']:.0%} |")
    report_lines.append("")
    
    # 保存报告
    report_path = f"{OUTPUT_DIR}/low_frequency_report.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(report_lines))
    print(f"✅ 报告已保存: {report_path}")


def main():
    """主函数"""
    print("=" * 100)
    print("个人投资者策略测试 v2")
    print("=" * 100)
    print(f"输出目录: {OUTPUT_DIR}")
    print()
    
    start_time = time.time()
    
    df = test_low_frequency_strategy()
    generate_report(df)
    
    elapsed = time.time() - start_time
    print(f"\n总耗时: {elapsed:.1f}秒 ({elapsed/60:.1f}分钟)")


if __name__ == "__main__":
    main()
