#!/usr/bin/env python3
# RESEARCH ONLY — not production code
# -*- coding: utf-8 -*-
"""
MA 双均线 + ATR + 冷却期 全参数组合优化

参数：
- MA 候选：MA5, MA10, MA20, MA30, MA60, MA120, MA250
- ATR 配置：低波（buy_cap=1.05, sell_mult=1.15）、高波（buy_cap=1.10, sell_mult=1.20）
- 冷却期：30, 60, 120, 250 天
- 确认天数：3 天

目标：找到最适合个人投资者的低频交易组合
"""

import itertools
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

# MA 候选值
MA_CANDIDATES = [5, 10, 20, 30, 60, 120, 250]

# 生成所有有效的 MA 组合（快线 < 慢线）
MA_COMBOS = [(fast, slow) for fast, slow in itertools.combinations(MA_CANDIDATES, 2) if fast < slow]

# ATR 配置
ATR_CONFIGS = [
    {"buy_volatility_cap": 1.05, "vol_breakout_mult": 1.15, "atr_period": 14, "atr_ma_window": 40, "name": "低波"},
    {"buy_volatility_cap": 1.10, "vol_breakout_mult": 1.20, "atr_period": 14, "atr_ma_window": 40, "name": "高波"},
]

# 冷却期
COOLDOWN_DAYS = [30, 60, 90, 120, 250, 360]

# 输出目录
OUTPUT_DIR = "output/ema_atr_cooldown_optimization"


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


def compute_indicators(df: pd.DataFrame, fast_ma: int, slow_ma: int, atr_config: Dict[str, Any]) -> pd.DataFrame:
    """计算技术指标"""
    enriched = df.copy()
    
    # EMA 指数移动平均线
    enriched["ma_fast"] = enriched["close"].ewm(span=fast_ma, adjust=False).mean()
    enriched["ma_slow"] = enriched["close"].ewm(span=slow_ma, adjust=False).mean()
    enriched["ma_fast_prev"] = enriched["ma_fast"].shift(1)
    enriched["ma_slow_prev"] = enriched["ma_slow"].shift(1)
    
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
    
    atr_period = atr_config.get("atr_period", 14)
    atr_ma_window = atr_config.get("atr_ma_window", 40)
    
    enriched["atr"] = true_range.rolling(atr_period, min_periods=1).mean()
    enriched["atr_ma"] = enriched["atr"].rolling(atr_ma_window, min_periods=1).mean()
    enriched["atr_ratio"] = (enriched["atr"] / enriched["atr_ma"].replace(0.0, pd.NA)).fillna(1.0)
    
    # 回撤计算
    enriched["rolling_peak"] = enriched["close"].rolling(120, min_periods=1).max()
    enriched["drawdown"] = (enriched["close"] / enriched["rolling_peak"]) - 1.0
    
    return enriched


def run_backtest(
    df: pd.DataFrame,
    fast_ma: int,
    slow_ma: int,
    atr_config: Dict[str, Any],
    cooldown_days: int,
    confirm_days: int = 3,
    start_date: str = "2020-01-01",
    end_date: str = "2026-03-27",
) -> Tuple[pd.DataFrame, pd.DataFrame, Dict[str, Any]]:
    """运行回测"""
    # 标准化数据
    price_df = normalize_price_frame(df)
    price_df = compute_indicators(price_df, fast_ma, slow_ma, atr_config)
    
    # 过滤日期
    start_ts = pd.to_datetime(start_date)
    end_ts = pd.to_datetime(end_date)
    price_df = price_df[(price_df["date"] >= start_ts) & (price_df["date"] <= end_ts)]
    
    # 预热期
    warmup = max(slow_ma, atr_config.get("atr_ma_window", 40))
    price_df = price_df.iloc[warmup:]
    
    if len(price_df) < 100:
        return pd.DataFrame(), pd.DataFrame(), {}
    
    # 回测参数
    initial_capital = 1_000_000.0
    buy_fee = 0.0003
    sell_fee = 0.0003
    slippage = 0.0005
    
    buy_volatility_cap = atr_config.get("buy_volatility_cap", 1.05)
    vol_breakout_mult = atr_config.get("vol_breakout_mult", 1.15)
    
    # 回撤保护阈值
    drawdown_reduce = -0.10
    drawdown_exit = -0.20
    
    # 初始化
    cash = initial_capital
    shares = 0
    current_position = 0.0
    cooldown_remaining = 0
    buy_signal_count = 0
    sell_signal_count = 0
    
    records = []
    trades = []
    actual_holding_days = 0
    
    for idx, row in price_df.iterrows():
        atr_ratio = float(row["atr_ratio"])
        drawdown = float(row["drawdown"])
        uptrend = bool(row.get("uptrend", False))
        downtrend = bool(row.get("downtrend", False))
        
        # 信号计数
        if uptrend and atr_ratio <= buy_volatility_cap:
            buy_signal_count += 1
        else:
            buy_signal_count = 0
        
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
        
        # 回撤保护（最高优先级）
        elif drawdown <= drawdown_exit:
            next_position = 0.0
            reason = f"回撤 {drawdown:.1%} 超过 {drawdown_exit:.0%}，清仓"
            cooldown_remaining = cooldown_days
        elif drawdown <= drawdown_reduce:
            next_position = max(0.0, current_position - 0.33)
            reason = f"回撤 {drawdown:.1%} 超过 {drawdown_reduce:.0%}，减仓"
            cooldown_remaining = cooldown_days
        
        # 趋势信号
        elif buy_confirmed and current_position < 1.0:
            next_position = min(current_position + 0.33, 1.0)
            reason = f"买入信号确认 {buy_signal_count} 天"
            cooldown_remaining = cooldown_days
            buy_signal_count = 0
        
        elif sell_confirmed and current_position > 0.0:
            next_position = max(current_position - 0.33, 0.0)
            reason = f"卖出信号确认 {sell_signal_count} 天"
            cooldown_remaining = cooldown_days
            sell_signal_count = 0
        
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
                        trades.append({"date": row["date"], "action": "buy", "price": buy_price, "shares": buy_shares})
        
        elif next_position < current_position and shares > 0:
            if next_position == 0:
                sell_shares = shares
            else:
                sell_shares = int(shares * (current_position - next_position) / current_position / 100) * 100
            if sell_shares > 0:
                sell_price = row["close"] * (1 - slippage)
                proceeds = sell_shares * sell_price * (1 - sell_fee)
                cash += proceeds
                shares -= sell_shares
                trades.append({"date": row["date"], "action": "sell", "price": sell_price, "shares": sell_shares})
        
        current_position = next_position
        portfolio_value = cash + shares * row["close"]
        if shares > 0:
            actual_holding_days += 1
        
        records.append({
            "date": row["date"],
            "close": row["close"],
            "target_position": current_position,
            "actual_shares": shares,
            "portfolio_value": portfolio_value,
            "drawdown": drawdown,
            "atr_ratio": atr_ratio,
            "reason": reason,
        })
    
    result_df = pd.DataFrame(records)
    trades_df = pd.DataFrame(trades) if trades else pd.DataFrame(columns=["date", "action", "price", "shares"])
    
    if len(result_df) < 10:
        return pd.DataFrame(), pd.DataFrame(), {}
    
    # 计算收益
    result_df["daily_return"] = result_df["portfolio_value"].pct_change()
    result_df["cumulative_return"] = (1 + result_df["daily_return"]).cumprod() - 1
    result_df["peak"] = result_df["portfolio_value"].cummax()
    result_df["portfolio_drawdown"] = (result_df["portfolio_value"] / result_df["peak"]) - 1.0
    result_df["benchmark_return"] = result_df["close"] / result_df["close"].iloc[0] - 1.0
    
    total_return = result_df["cumulative_return"].iloc[-1]
    benchmark_return = result_df["benchmark_return"].iloc[-1]
    annualized_return = (1 + total_return) ** (252 / len(result_df)) - 1
    annualized_benchmark = (1 + benchmark_return) ** (252 / len(result_df)) - 1
    annualized_excess = annualized_return - annualized_benchmark
    max_drawdown = result_df["portfolio_drawdown"].min()
    trade_count = len(trades_df)
    holding_ratio = actual_holding_days / len(result_df)
    
    summary = {
        "total_return": total_return,
        "benchmark_return": benchmark_return,
        "annualized_return": annualized_return,
        "annualized_benchmark": annualized_benchmark,
        "annualized_excess_return": annualized_excess,
        "max_drawdown": max_drawdown,
        "trade_count": trade_count,
        "holding_ratio": holding_ratio,
        "eligible": (annualized_excess > 0 and max_drawdown > -0.35 and trade_count >= 3),
    }
    
    return result_df, trades_df, summary


def run_single_test(
    symbol: str,
    fast_ma: int,
    slow_ma: int,
    atr_config: Dict[str, Any],
    cooldown_days: int,
) -> Optional[Dict[str, Any]]:
    """运行单次测试"""
    from src.data.manager import DataManager
    
    try:
        manager = DataManager()
        df = manager.get_data(symbol)
        if df is None or df.empty:
            return None
        
        result_df, trades_df, summary = run_backtest(df, fast_ma, slow_ma, atr_config, cooldown_days)
        
        if result_df.empty:
            return None
        
        return {
            "symbol": symbol,
            "symbol_name": SYMBOL_NAMES.get(symbol, symbol),
            "fast_ma": fast_ma,
            "slow_ma": slow_ma,
            "atr_config": atr_config["name"],
            "cooldown_days": cooldown_days,
            **summary,
        }
    except Exception as exc:
        print(
            f"  [ERROR] {symbol} MA{fast_ma}/{slow_ma} + {atr_config['name']} + 冷却{cooldown_days}天: {exc}"
        )
        return None


def full_optimization():
    """全参数组合优化"""
    print("=" * 120)
    print("MA 双均线 + ATR + 冷却期 全参数组合优化")
    print("=" * 120)
    print(f"MA 组合数: {len(MA_COMBOS)}")
    print(f"ATR 配置数: {len(ATR_CONFIGS)}")
    print(f"冷却期数: {len(COOLDOWN_DAYS)}")
    print(f"总组合数: {len(MA_COMBOS) * len(ATR_CONFIGS) * len(COOLDOWN_DAYS)}")
    print()
    
    all_results = []
    total = len(MA_COMBOS) * len(ATR_CONFIGS) * len(COOLDOWN_DAYS)
    count = 0
    
    for fast_ma, slow_ma in MA_COMBOS:
        for atr_config in ATR_CONFIGS:
            for cooldown_days in COOLDOWN_DAYS:
                count += 1
                combo_results = []
                failed_symbols = []
                for symbol in SYMBOLS:
                    result = run_single_test(symbol, fast_ma, slow_ma, atr_config, cooldown_days)
                    if result:
                        combo_results.append(result)
                    else:
                        failed_symbols.append(symbol)
                
                if failed_symbols:
                    print(
                        f"[{count}/{total}] MA{fast_ma}/{slow_ma} + {atr_config['name']} + 冷却{cooldown_days}天: "
                        f"SKIPPED, failed={','.join(failed_symbols)}"
                    )
                    continue

                if combo_results:
                    df = pd.DataFrame(combo_results)
                    eligible_count = df["eligible"].sum()
                    avg_excess = df["annualized_excess_return"].mean()
                    avg_drawdown = df["max_drawdown"].mean()
                    avg_trades = df["trade_count"].mean()
                    avg_holding = df["holding_ratio"].mean()
                    
                    if count % 20 == 0 or eligible_count >= 2:
                        print(
                            f"[{count}/{total}] MA{fast_ma}/{slow_ma} + {atr_config['name']} + 冷却{cooldown_days}天: "
                            f"eligible={eligible_count}/8, excess={avg_excess:.2%}, drawdown={avg_drawdown:.2%}, "
                            f"trades={avg_trades:.1f}, holding={avg_holding:.0%}"
                        )
                    
                    all_results.extend(combo_results)
    
    # 保存结果
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    combined_df = pd.DataFrame(all_results)
    combined_df.to_csv(f"{OUTPUT_DIR}/full_optimization.csv", index=False)
    
    print(f"\n✅ 优化完成，共 {len(all_results)} 条结果")
    return combined_df


def analyze_results(df: pd.DataFrame):
    """分析结果"""
    print("\n" + "=" * 120)
    print("分析结果")
    print("=" * 120)
    
    # 按组合汇总
    combo_summary = df.groupby(["fast_ma", "slow_ma", "atr_config", "cooldown_days"]).agg({
        "eligible": "sum",
        "annualized_return": "mean",
        "annualized_benchmark": "mean",
        "annualized_excess_return": "mean",
        "max_drawdown": "mean",
        "trade_count": "mean",
        "holding_ratio": "mean",
    }).reset_index()
    
    combo_summary = combo_summary.sort_values(["eligible", "annualized_excess_return"], ascending=False)
    
    print("\n--- Top 30 组合（eligible + excess 降序）---\n")
    print(f"{'MA组合':<12} {'ATR':<6} {'冷却期':<8} {'eligible':<10} {'avg_excess':<12} {'avg_drawdown':<12} {'avg_trades':<10} {'avg_holding':<10}")
    print("-" * 100)
    
    for _, row in combo_summary.head(30).iterrows():
        print(f"MA{int(row['fast_ma'])}/{int(row['slow_ma']):<7} {row['atr_config']:<6} {int(row['cooldown_days']):<8} {int(row['eligible'])}/8{'':<6} {row['annualized_excess_return']:.2%}{'':<6} {row['max_drawdown']:.2%}{'':<6} {row['trade_count']:.1f}{'':<6} {row['holding_ratio']:.0%}")


def generate_report(df: pd.DataFrame):
    """生成报告"""
    print("\n" + "=" * 120)
    print("生成报告")
    print("=" * 120)
    
    report_lines = []
    report_lines.append("# MA 双均线 + ATR + 冷却期 全参数组合优化报告")
    report_lines.append(f"\n**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report_lines.append("\n**测试周期**: 2020-01-01 ~ 2026-03-27")
    report_lines.append("\n---\n")
    
    report_lines.append("## 参数设置\n")
    report_lines.append(f"- **MA 候选**: {MA_CANDIDATES}")
    report_lines.append(f"- **MA 组合数**: {len(MA_COMBOS)}")
    report_lines.append("- **ATR 配置**: 低波（buy=1.05, sell=1.15）、高波（buy=1.10, sell=1.20）")
    report_lines.append(f"- **冷却期**: {COOLDOWN_DAYS} 天")
    report_lines.append("- **确认天数**: 3 天")
    report_lines.append(f"- **总组合数**: {len(MA_COMBOS) * len(ATR_CONFIGS) * len(COOLDOWN_DAYS)}")
    report_lines.append("")
    
    # 按组合汇总
    combo_summary = df.groupby(["fast_ma", "slow_ma", "atr_config", "cooldown_days"]).agg({
        "eligible": "sum",
        "annualized_return": "mean",
        "annualized_benchmark": "mean",
        "annualized_excess_return": "mean",
        "max_drawdown": "mean",
        "trade_count": "mean",
        "holding_ratio": "mean",
    }).reset_index()
    
    combo_summary = combo_summary.sort_values(["eligible", "annualized_excess_return"], ascending=False)
    
    report_lines.append("## Top 30 组合\n")
    report_lines.append("| MA组合 | ATR | 冷却期 | eligible | 平均年化收益 | 平均基准收益 | 平均年化超额 | 平均回撤 | 平均交易 | 平均持仓 |")
    report_lines.append("|:-------|:---:|:------:|:--------:|-----------:|-----------:|-----------:|--------:|--------:|--------:|")
    
    for _, row in combo_summary.head(30).iterrows():
        report_lines.append(f"| MA{int(row['fast_ma'])}/MA{int(row['slow_ma'])} | {row['atr_config']} | {int(row['cooldown_days'])}天 | {int(row['eligible'])}/8 | {row['annualized_return']:.2%} | {row['annualized_benchmark']:.2%} | {row['annualized_excess_return']:.2%} | {row['max_drawdown']:.2%} | {row['trade_count']:.1f} | {row['holding_ratio']:.0%} |")
    
    report_lines.append("")
    
    # 各指数最优组合
    report_lines.append("## 各指数最优组合\n")
    
    for symbol in SYMBOLS:
        symbol_df = df[df["symbol"] == symbol]
        if symbol_df.empty:
            continue
        
        # 按年化超额降序
        best = symbol_df.sort_values("annualized_excess_return", ascending=False).iloc[0]
        eligible = "✅" if best["eligible"] else "❌"
        
        report_lines.append(f"### {symbol} ({SYMBOL_NAMES[symbol]})\n")
        report_lines.append(f"- **最优组合**: MA{int(best['fast_ma'])}/MA{int(best['slow_ma'])} + {best['atr_config']} + 冷却{int(best['cooldown_days'])}天")
        report_lines.append(f"- **状态**: {eligible}")
        report_lines.append(f"- **总收益**: {best['total_return']:.2%}")
        report_lines.append(f"- **年化收益**: {best['annualized_return']:.2%}")
        report_lines.append(f"- **基准收益**: {best['benchmark_return']:.2%}")
        report_lines.append(f"- **年化超额**: {best['annualized_excess_return']:.2%}")
        report_lines.append(f"- **最大回撤**: {best['max_drawdown']:.2%}")
        report_lines.append(f"- **交易次数**: {int(best['trade_count'])}")
        report_lines.append(f"- **持仓比例**: {best['holding_ratio']:.0%}")
        report_lines.append("")
    
    # 保存报告
    report_path = f"{OUTPUT_DIR}/optimization_report.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(report_lines))
    print(f"✅ 报告已保存: {report_path}")


def main():
    """主函数"""
    print("=" * 120)
    print("MA 双均线 + ATR + 冷却期 全参数组合优化")
    print("=" * 120)
    print(f"输出目录: {OUTPUT_DIR}")
    print()
    
    start_time = time.time()
    
    df = full_optimization()
    analyze_results(df)
    generate_report(df)
    
    elapsed = time.time() - start_time
    print(f"\n总耗时: {elapsed:.1f}秒 ({elapsed/60:.1f}分钟)")


if __name__ == "__main__":
    main()
