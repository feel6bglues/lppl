#!/usr/bin/env python3
# RESEARCH ONLY — not production code
# -*- coding: utf-8 -*-
"""
Wyckoff 三阶段执行逻辑验证脚本
===============================
设计目标: 实现三阶段动态出场管理, 修复盈亏比倒挂问题

三阶段执行逻辑:
  阶段1 (入场-30天): 结构止损 + 第一目标 + 早期预警
  阶段2 (30-90天):  阶梯止盈(达目标卖50%) + 时间止损(60天) + 移动止损
  阶段3 (90-180天): 移动止损保护 + 180天强制平仓

验证数据集: 全量A股 (5199只) × 20个时间窗口 × 90天持有期
基准: 沪深300
"""

import csv
import json
import random
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
from src.data.manager import DataManager
from src.data.tdx_loader import load_tdx_data
from src.parallel import get_optimal_workers, worker_init
from src.wyckoff.engine import WyckoffEngine

# ============================================================================
# 配置
# ============================================================================
N_STOCKS = 99999
N_WINDOWS = 20
MAX_HOLD = 180  # 最大持有天数
SEED = 42
N_BOOTSTRAP = 2000
CSI300_TDX_PATH = Path("/home/james/.local/share/tdxcfv/drive_c/tc/vipdoc/sh/lday/sh000300.day")
OUTPUT_DIR = PROJECT_ROOT / "output" / "wyckoff_v2_test"


def load_stocks(csv_path: Path, limit: int = N_STOCKS) -> List[Dict[str, str]]:
    symbols = []
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            code = str(row.get("code", "")).strip()
            market = str(row.get("market", "")).strip().upper()
            name = str(row.get("name", "")).replace("\x00", "").strip()
            if not (code.isdigit() and len(code) == 6 and market in {"SH", "SZ"}):
                continue
            if code.startswith(("600", "601", "603", "605", "688", "689",
                               "000", "001", "002", "003", "300", "301", "302")):
                symbols.append({"symbol": f"{code}.{market}", "code": code, "market": market, "name": name})
            if len(symbols) >= limit:
                break
    return symbols


def load_csi300() -> Optional[pd.DataFrame]:
    if CSI300_TDX_PATH.exists():
        df = load_tdx_data(str(CSI300_TDX_PATH))
        if df is not None and not df.empty:
            df["date"] = pd.to_datetime(df["date"])
            df = df.sort_values("date").reset_index(drop=True)
            return df
    return None


def generate_windows(csi300_df: pd.DataFrame, n: int = N_WINDOWS) -> List[str]:
    if csi300_df is None or len(csi300_df) < 200:
        return []
    trading_dates = csi300_df["date"].dt.strftime("%Y-%m-%d").tolist()
    available = trading_dates[:len(trading_dates) - MAX_HOLD]
    random.seed(SEED)
    return sorted(random.sample(available, min(n, len(available))))


def classify_market_regime(index_data: pd.DataFrame, as_of_date: str) -> str:
    as_of = pd.Timestamp(as_of_date)
    hist = index_data[index_data["date"] <= as_of]
    if len(hist) < 120:
        return "unknown"
    close = float(hist.iloc[-1]["close"])
    ma120 = float(hist.tail(120)["close"].mean())
    ma60 = float(hist.tail(60)["close"].mean())
    if close > ma120 * 1.02 and ma60 > ma120:
        return "bull"
    elif close < ma120 * 0.98:
        return "bear"
    else:
        return "range"


def calc_atr(df_slice: pd.DataFrame, period: int = 20) -> float:
    """计算ATR"""
    if len(df_slice) < period + 1:
        return 0.0
    high = df_slice["high"].values
    low = df_slice["low"].values
    close = df_slice["close"].values
    tr = []
    for i in range(1, len(df_slice)):
        hl = high[i] - low[i]
        hc = abs(high[i] - close[i-1])
        lc = abs(low[i] - close[i-1])
        tr.append(max(hl, hc, lc))
    if len(tr) < period:
        return float(np.mean(tr)) if tr else 0.0
    return float(np.mean(tr[-period:]))


def calculate_three_stage_return(
    df: pd.DataFrame,
    as_of_date: str,
    wyckoff_entry: Optional[float] = None,
    stop_loss: Optional[float] = None,
    first_target: Optional[float] = None,
    regime: str = "unknown",
) -> Optional[Dict]:
    """
    三阶段执行逻辑:
    阶段1 (入场-30天): 结构止损 + 第一目标
      若达第一目标 → 记录partial_exit(卖50%), 剩余仓位进入阶段2
      若触止损 → 全仓退出
      若20天内回撤>3% → 记录预警

    阶段2 (30-90天): 阶梯止盈 + 时间止损
      若已达第一目标(剩余仓位): 设移动止损(高点回落2×ATR)
      若未达第一目标且>60天: 时间止损全退
      若未达第一目标且<=60天: 继续持有

    阶段3 (90-180天): 移动止损保护
      从进入阶段2后的最高点回落2×ATR → 退出
      满180天强制退出
    """
    as_of = pd.Timestamp(as_of_date)
    future = df[df["date"] > as_of].head(MAX_HOLD)
    if len(future) < MAX_HOLD * 0.6:
        return None

    current_close = float(df[df["date"] <= as_of].iloc[-1]["close"])

    # 决定入场价
    use_wyckoff_entry = (wyckoff_entry is not None and wyckoff_entry > 0
                         and abs(wyckoff_entry - current_close) / current_close > 0.001)
    entry_price = wyckoff_entry if use_wyckoff_entry else current_close

    # 如果使用Wyckoff入场价但未触及 → 交易未执行
    if use_wyckoff_entry:
        period_low_30 = float(future.head(30)["low"].min())
        if wyckoff_entry < period_low_30:
            # 30天内未触及entry → 跳过
            early_check = future.head(10)
            if len(early_check) > 0 and wyckoff_entry < float(early_check["low"].min()):
                return None

    # 计算ATR用于移动止损
    hist = df[df["date"] <= as_of].tail(60)
    atr_20 = calc_atr(pd.concat([hist, future.head(20)]), 20) if len(future) >= 20 else 0.0
    if atr_20 <= 0:
        atr_20 = entry_price * 0.02  # 备用: 2% of entry

    # ===== 执行模拟 =====
    n = len(future)
    half_exited = False        # 阶段1是否已卖50%
    trailing_stop = None       # 移动止损价
    peak_price = entry_price   # 用于移动止损的最高点追踪
    stage2_active = False      # 是否进入阶段2
    time_stop_triggered = False
    final_exit_price = None
    final_exit_reason = "hold_to_end"
    stage1_exit_price = None
    stage1_exit_reason = None
    hit_stop = False
    hit_target = False
    days_in_trade = 0

    for i, (_, row) in enumerate(future.iterrows()):
        days_in_trade = i + 1
        close = float(row["close"])
        high = float(row["high"])
        low = float(row["low"])
        peak_price = max(peak_price, high)

        # ---- 止损检查 (始终有效) ----
        if stop_loss is not None and stop_loss > 0 and low <= stop_loss:
            if not half_exited:
                final_exit_price = stop_loss
                final_exit_reason = "stop_loss_full"
                hit_stop = True
            else:
                final_exit_price = stop_loss
                final_exit_reason = "stop_loss_remainder"
                hit_stop = True
            break

        # ---- 阶段1: 入场-30天, 检查第一目标 ----
        if days_in_trade <= 30 and not half_exited:
            if first_target is not None and first_target > 0 and high >= first_target:
                # 达第一目标: 卖50%, 进入阶段2
                half_exited = True
                stage1_exit_price = first_target
                stage1_exit_reason = "first_target_50pct"
                hit_target = True
                # 剩余仓位从下一根K线开始用移动止损保护
                trailing_stop = peak_price - 2 * atr_20
                stage2_active = True
                continue

            # 30天到期仍未达目标 → 自动进入阶段2
            if days_in_trade == 30:
                stage2_active = True
                trailing_stop = peak_price - 2 * atr_20

        # ---- 阶段2: 30-90天, 移动止损 + 时间止损 ----
        if stage2_active:
            # 更新移动止损
            trailing_stop = max(trailing_stop, peak_price - 2 * atr_20) if trailing_stop else (peak_price - 2 * atr_20)

            # 检查移动止损是否触发
            if trailing_stop and low <= trailing_stop:
                final_exit_price = trailing_stop
                final_exit_reason = "trailing_stop" if half_exited else "trailing_stop_full"
                break

            # 时间止损: 入场超过60天且从未达第一目标
            if days_in_trade > 60 and not half_exited:
                final_exit_price = close
                final_exit_reason = "time_stop_60d"
                time_stop_triggered = True
                break

        # ---- 阶段3: 90天后, 移动止损保护 ----
        if days_in_trade > 90 and stage2_active:
            # 移动止损持续更新
            trailing_stop = max(trailing_stop, peak_price - 2 * atr_20) if trailing_stop else (peak_price - 2 * atr_20)
            if trailing_stop and low <= trailing_stop:
                final_exit_price = trailing_stop
                final_exit_reason = "trailing_stop_stage3"
                break

        # 更新最终的持有到期退出价
        final_exit_price = close

    # ---- 强制180天平仓 ----
    if days_in_trade >= MAX_HOLD:
        final_exit_price = float(future.iloc[-1]["close"])
        final_exit_reason = "max_hold_180d"

    # ---- 计算最终收益 ----
    # 如果阶段1卖出了50%, 需要合并计算
    if half_exited and stage1_exit_price:
        # 50%以第一目标价退出
        r1 = (stage1_exit_price - entry_price) / entry_price * 100
        # 50%以最终退出价退出 (可能已被移动止损/时间止损/到期保护)
        final_exit = final_exit_price if final_exit_price else float(future.iloc[-1]["close"])
        r2 = (final_exit - entry_price) / entry_price * 100
        total_return = 0.5 * r1 + 0.5 * r2
        total_exit_reason = f"{stage1_exit_reason}+{final_exit_reason}"
    else:
        r1 = 0
        r2 = (final_exit_price - entry_price) / entry_price * 100 if final_exit_price else 0
        total_return = r2
        total_exit_reason = final_exit_reason

    future_high = float(future["high"].max())
    future_low = float(future["low"].min())
    max_gain = (future_high - entry_price) / entry_price * 100
    max_dd = (entry_price - future_low) / entry_price * 100

    # 计算实际盈亏比
    if r2 < 0 and abs(r2) > 0.01:
        actual_rr = abs(r1 / r2) if abs(r1) > 0.01 else 0
    else:
        actual_rr = abs(r1 / r2) if r2 and abs(r2) > 0.01 else 0

    return {
        "entry_price": round(entry_price, 3),
        "total_return": round(total_return, 2),
        "total_exit_reason": total_exit_reason,
        "stage1_return": round(r1, 2),
        "stage2_return": round(r2, 2),
        "half_exited": half_exited,
        "hit_stop": hit_stop,
        "hit_target": hit_target,
        "time_stop_60d": time_stop_triggered,
        "max_gain_pct": round(max_gain, 2),
        "max_drawdown_pct": round(max_dd, 2),
        "actual_rr_ratio": round(actual_rr, 2),
        "days_in_trade": days_in_trade,
        "data_points": len(future),
    }


def process_stock(args) -> List[Dict]:
    symbol_info, windows, csi300_df = args
    symbol = symbol_info["symbol"]
    name = symbol_info["name"]
    results = []
    try:
        dm = DataManager()
        df = dm.get_data(symbol)
        if df is None or df.empty or len(df) < 300:
            return results
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)

        engine = WyckoffEngine(lookback_days=400, weekly_lookback=120, monthly_lookback=40)

        for as_of_date in windows:
            as_of = pd.Timestamp(as_of_date)
            available = df[df["date"] <= as_of]
            if len(available) < 100:
                continue

            report = engine.analyze(available, symbol=symbol, period="日线", multi_timeframe=True)

            rr = report.risk_reward
            wyckoff_entry = rr.entry_price if rr and rr.entry_price and rr.entry_price > 0 else None
            stop_loss = rr.stop_loss if rr and rr.stop_loss and rr.stop_loss > 0 else None
            first_target = rr.first_target if rr and rr.first_target and rr.first_target > 0 else None
            sig = report.signal.signal_type
            is_no_trade = sig == "no_signal" or report.trading_plan.direction == "空仓观望"
            phase = report.structure.phase.value
            alignment = report.multi_timeframe.alignment if report.multi_timeframe else ""
            direction = report.trading_plan.direction
            confidence = report.trading_plan.confidence.value
            market_regime = classify_market_regime(csi300_df, as_of_date) if csi300_df is not None else "unknown"

            # 使用三阶段执行逻辑
            ret = calculate_three_stage_return(
                df, as_of_date,
                wyckoff_entry=wyckoff_entry,
                stop_loss=stop_loss,
                first_target=first_target,
                regime=market_regime,
            )
            if ret is None:
                continue

            # 基准收益
            benchmark_ret = None
            if csi300_df is not None:
                bm_future = csi300_df[csi300_df["date"] > as_of].head(90)
                if len(bm_future) >= 72:
                    bm_entry = float(csi300_df[csi300_df["date"] <= as_of].iloc[-1]["close"])
                    bm_exit = float(bm_future.iloc[-1]["close"])
                    benchmark_ret = round((bm_exit - bm_entry) / bm_entry * 100, 2)

            results.append({
                "symbol": symbol, "name": name, "as_of": as_of_date,
                "phase": phase, "market_regime": market_regime,
                "signal_type": sig, "is_no_trade": is_no_trade,
                "direction": direction, "confidence": confidence,
                "alignment": alignment,
                "total_return": ret["total_return"],
                "total_exit_reason": ret["total_exit_reason"],
                "stage1_return": ret["stage1_return"],
                "stage2_return": ret["stage2_return"],
                "half_exited": ret["half_exited"],
                "hit_stop": ret["hit_stop"],
                "hit_target": ret["hit_target"],
                "time_stop": ret["time_stop_60d"],
                "actual_rr_ratio": ret["actual_rr_ratio"],
                "days_in_trade": ret["days_in_trade"],
                "max_gain_pct": ret["max_gain_pct"],
                "max_drawdown_pct": ret["max_drawdown_pct"],
                "benchmark_return": benchmark_ret,
                "excess_return": round(ret["total_return"] - benchmark_ret, 2) if benchmark_ret is not None else None,
            })
    except Exception:
        pass
    return results


def bootstrap_ci(data: np.ndarray, n=N_BOOTSTRAP, confidence=0.95):
    if len(data) < 10:
        return np.nan, np.nan, np.nan
    means = [np.mean(np.random.choice(data, size=len(data), replace=True)) for _ in range(n)]
    return np.mean(means), np.percentile(means, (1 - confidence) / 2 * 100), np.percentile(means, (1 + confidence) / 2 * 100)


def run():
    print("=" * 70)
    print("Wyckoff v2 三阶段执行逻辑验证")
    print(f"  全量A股 | 时间窗口: {N_WINDOWS} | 最大持有: {MAX_HOLD}天")
    print("=" * 70)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    csv_path = PROJECT_ROOT / "data" / "stock_list.csv"
    stocks = load_stocks(csv_path, N_STOCKS)
    print(f"\n加载 {len(stocks)} 只股票")

    csi300 = load_csi300()
    print(f"沪深300: {len(csi300) if csi300 is not None else 0}行")

    windows = generate_windows(csi300, N_WINDOWS)
    print(f"时间窗口: {len(windows)}个")

    all_results = []
    max_workers = get_optimal_workers()
    batch_size = max_workers * 4
    args_list = [(s, windows, csi300) for s in stocks]

    with ProcessPoolExecutor(max_workers=max_workers, initializer=worker_init) as executor:
        for batch_start in range(0, len(args_list), batch_size):
            batch = args_list[batch_start:batch_start + batch_size]
            futures = {executor.submit(process_stock, a): a[0]["symbol"] for a in batch}
            for future in as_completed(futures):
                try:
                    results = future.result(timeout=300)
                    all_results.extend(results)
                except Exception:
                    pass
            progress = min(batch_start + batch_size, len(args_list))
            print(f"  进度: {progress}/{len(stocks)} 股票, {len(all_results)} 样本")

    print(f"\n总样本: {len(all_results)}")
    if not all_results:
        print("无样本, 退出")
        return

    df = pd.DataFrame(all_results)
    returns = df["total_return"].values
    mean_ret, ci_low, ci_high = bootstrap_ci(returns)

    analysis = {
        "config": {"n_stocks": len(stocks), "n_windows": N_WINDOWS, "max_hold": MAX_HOLD, "version": "v2_three_stage"},
        "overall_stats": {
            "n_samples": len(df),
            "mean_return": round(mean_ret, 2),
            "ci_lower": round(ci_low, 2),
            "ci_upper": round(ci_high, 2),
            "median_return": round(np.median(returns), 2),
            "win_rate": round(sum(returns > 0) / len(returns) * 100, 1),
            "std_return": round(np.std(returns), 2),
        },
        "execution_analysis": {},
        "phase_analysis": {},
        "regime_analysis": {},
        "exit_reason_analysis": {},
        "benchmark_comparison": {},
    }

    # 执行分析
    for col, label in [("half_exited", "阶梯止盈(半仓)"), ("hit_stop", "止损触发"),
                        ("time_stop", "时间止损")]:
        subset = df[df[col] == True]["total_return"].values
        if len(subset) >= 5:
            analysis["execution_analysis"][label] = {
                "n_samples": len(subset),
                "mean_return": round(np.mean(subset), 2),
                "median_return": round(np.median(subset), 2),
                "win_rate": round(sum(subset > 0) / len(subset) * 100, 1),
            }

    # 退出原因
    for reason in df["total_exit_reason"].unique():
        vals = df[df["total_exit_reason"] == reason]["total_return"].values
        if len(vals) >= 5:
            analysis["exit_reason_analysis"][reason] = {
                "n_samples": len(vals),
                "mean_return": round(np.mean(vals), 2),
                "win_rate": round(sum(vals > 0) / len(vals) * 100, 1),
                "pct_of_total": round(len(vals) / len(df) * 100, 1),
            }

    # 阶段分析
    for phase in df["phase"].unique():
        vals = df[df["phase"] == phase]["total_return"].values
        if len(vals) >= 10:
            m, l, h = bootstrap_ci(vals)
            analysis["phase_analysis"][phase] = {
                "n_samples": len(vals), "mean_return": round(m, 2),
                "ci_lower": round(l, 2), "ci_upper": round(h, 2),
                "win_rate": round(sum(vals > 0) / len(vals) * 100, 1),
            }

    # Regime分析
    for regime in df["market_regime"].unique():
        vals = df[df["market_regime"] == regime]["total_return"].values
        if len(vals) >= 10:
            m, l, h = bootstrap_ci(vals)
            analysis["regime_analysis"][regime] = {
                "n_samples": len(vals), "mean_return": round(m, 2),
                "win_rate": round(sum(vals > 0) / len(vals) * 100, 1),
            }

    # 基准
    if "excess_return" in df.columns and df["excess_return"].notna().sum() >= 10:
        excess = df["excess_return"].dropna().values
        analysis["benchmark_comparison"] = {
            "strategy_mean": round(np.mean(returns), 2),
            "benchmark_mean": round(np.mean(df["benchmark_return"].dropna()), 2),
            "excess_mean": round(np.mean(excess), 2),
            "excess_win_rate": round(sum(excess > 0) / len(excess) * 100, 1),
        }

    json_path = OUTPUT_DIR / "v2_test_results.json"
    with json_path.open("w", encoding="utf-8") as f:
        json.dump(analysis, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n结果: {json_path}")

    # 输出
    os = analysis["overall_stats"]
    print(f"\n{'='*70}")
    print("v2 三阶段执行 测试摘要")
    print(f"  总样本: {os['n_samples']}")
    print(f"  平均收益: {os['mean_return']:.2f}%")
    print(f"  95%CI: [{os['ci_lower']:.2f}, {os['ci_upper']:.2f}]")
    print(f"  中位收益: {os['median_return']:.2f}%")
    print(f"  胜率: {os['win_rate']:.1f}%")
    print(f"  标准差: {os['std_return']:.2f}%")

    if analysis["benchmark_comparison"]:
        bc = analysis["benchmark_comparison"]
        print(f"\n  策略: {bc['strategy_mean']:.2f}% vs 沪深300: {bc['benchmark_mean']:.2f}%")
        print(f"  超额: {bc['excess_mean']:.2f}%  超额胜率: {bc['excess_win_rate']:.1f}%")

    print("\n  退出原因分析:")
    for r, s in sorted(analysis["exit_reason_analysis"].items(), key=lambda x: -x[1]["mean_return"]):
        print(f"    {r:40s}: ret={s['mean_return']:6.2f}%  win={s['win_rate']:5.1f}%  {s['pct_of_total']:5.1f}%")

    print("\n  执行机制分析:")
    for r, s in sorted(analysis["execution_analysis"].items(), key=lambda x: -x[1]["mean_return"]):
        print(f"    {r:20s}: ret={s['mean_return']:6.2f}%  median={s['median_return']:5.2f}%  win={s['win_rate']:5.1f}%  n={s['n_samples']}")

    print(f"\n{'='*70}")
    print("完成")
    print(f"{'='*70}")


if __name__ == "__main__":
    run()
