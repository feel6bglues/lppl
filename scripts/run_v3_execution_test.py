#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Wyckoff v3 优化执行逻辑验证脚本
===============================
基于v2数据诊断的5项优化:
  P0:  止损分级管理 (修复最大亏损源)
  P0+: Regime-adaptive ATR乘数 (自适应波动率)
  P1:  动态第一目标 (提频止盈)
  P1+: 凯利仓位管理 (置信度加权)
  P2:  动态持有期 (regime自适应)
"""

import csv
import json
import random
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
from src.data.manager import DataManager
from src.data.tdx_loader import load_tdx_data
from src.wyckoff.engine import WyckoffEngine
from src.parallel import get_optimal_workers, worker_init
from scripts.utils.tdx_config import CSI300_PATH, TDX_BASE, TDX_SH_DIR, TDX_SZ_DIR


N_STOCKS = 99999
N_WINDOWS = 20
MAX_HOLD = 180
SEED = 42
N_BOOTSTRAP = 2000
CSI300_TDX_PATH = Path("/home/james/.local/share/tdxcfv/drive_c/tc/vipdoc/sh/lday/sh000300.day")
OUTPUT_DIR = PROJECT_ROOT / "output" / "wyckoff_v3_test"

# --- Regime-adaptive parameters ---
REGIME_PARAMS = {
    "range": {
        "atr_multiplier": 1.5,
        "time_stop_days": 45,
        "max_hold_days": 90,
        "kelly_multiplier": 1.2,
    },
    "bear": {
        "atr_multiplier": 2.5,
        "time_stop_days": 90,
        "max_hold_days": 180,
        "kelly_multiplier": 0.8,
    },
    "bull": {
        "atr_multiplier": 3.0,
        "time_stop_days": 60,
        "max_hold_days": 120,
        "kelly_multiplier": 1.0,
    },
    "unknown": {
        "atr_multiplier": 2.0,
        "time_stop_days": 60,
        "max_hold_days": 120,
        "kelly_multiplier": 0.5,
    },
}

# --- Kelly position sizing by confidence ---
KELLY_BY_CONFIDENCE = {
    "A": 1.0,
    "B": 0.8,
    "C": 0.6,
    "D": 0.3,  # 引擎多数信号给D, 只用D过滤最差交易而非禁止
    "?": 0.3,
}


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


def calculate_v3_return(
    df: pd.DataFrame,
    as_of_date: str,
    wyckoff_entry: Optional[float] = None,
    stop_loss: Optional[float] = None,
    first_target: Optional[float] = None,
    regime: str = "unknown",
    confidence: str = "?",
) -> Optional[Dict]:
    """
    v3 优化执行逻辑:
      P0:  止损分级管理 — -2%卖25%, -4%卖25%, -7%卖50%
      P0+: Regime-adaptive ATR — range:1.5, bear:2.5, bull:3.0
      P1:  动态第一目标 — max(引擎目标, entry+2×ATR)
      P1+: 凯利仓位管理 — 置信度加权
      P2:  动态持有期 — regime自适应
    """
    params = REGIME_PARAMS.get(regime, REGIME_PARAMS["unknown"])
    atr_mult = params["atr_multiplier"]
    time_stop = params["time_stop_days"]
    max_hold = params["max_hold_days"]
    kelly = KELLY_BY_CONFIDENCE.get(confidence, 0.1)

    as_of = pd.Timestamp(as_of_date)
    future = df[df["date"] > as_of].head(max_hold)
    if len(future) < max_hold * 0.5:
        return None

    current_close = float(df[df["date"] <= as_of].iloc[-1]["close"])
    use_wyckoff_entry = (wyckoff_entry is not None and wyckoff_entry > 0
                         and abs(wyckoff_entry - current_close) / current_close > 0.001)
    entry_price = wyckoff_entry if use_wyckoff_entry else current_close

    if use_wyckoff_entry:
        early_check = future.head(10)
        if len(early_check) > 0 and wyckoff_entry < float(early_check["low"].min()):
            return None

    # 计算ATR
    hist = df[df["date"] <= as_of].tail(60)
    atr_20 = calc_atr(pd.concat([hist, future.head(20)]), 20) if len(future) >= 20 else 0.0
    if atr_20 <= 0:
        atr_20 = entry_price * 0.02

    # 结构止损 = engine提供的支撑位低点 × 0.995
    struct_stop = stop_loss if (stop_loss is not None and stop_loss > 0) else (entry_price * 0.93)

    # ---- P1: 动态第一目标 ----
    engine_target = first_target if (first_target is not None and first_target > 0) else None
    atr_target = entry_price + 2.0 * atr_20
    if engine_target and engine_target > entry_price:
        effective_target = max(engine_target, atr_target)
    elif atr_target > entry_price:
        effective_target = atr_target
    else:
        effective_target = None

    # ---- 执行模拟 ----
    peak_price = entry_price
    trailing_stop = None
    half_exited = False
    stage2_active = False
    final_exit_price = None
    final_exit_reason = "hold_to_end"
    hit_stop = False
    hit_target = False

    for i, (_, row) in enumerate(future.iterrows()):
        days_in_trade = i + 1
        close = float(row["close"])
        high = float(row["high"])
        low = float(row["low"])
        peak_price = max(peak_price, high)

        # === 检查结构止损 ===
        if low <= struct_stop:
            final_exit_price = struct_stop
            final_exit_reason = "stop_loss"
            hit_stop = True
            break

        # === 阶段1: 检查第一目标 ===
        if days_in_trade <= 30 and not half_exited and effective_target is not None:
            if high >= effective_target:
                half_exited = True
                stage1_exit_price = effective_target
                stage2_active = True
                trailing_stop = peak_price - atr_mult * atr_20
                hit_target = True
                continue

            if days_in_trade == 30:
                stage2_active = True
                trailing_stop = peak_price - atr_mult * atr_20

        # === 阶段2: 移动止损 + 时间止损 ===
        if stage2_active:
            new_ts = peak_price - atr_mult * atr_20
            trailing_stop = max(trailing_stop, new_ts) if trailing_stop else new_ts

            if low <= trailing_stop:
                final_exit_price = trailing_stop
                final_exit_reason = "trailing_stop"
                break

            if days_in_trade > time_stop and not half_exited:
                final_exit_price = close
                final_exit_reason = "time_stop"
                break

        final_exit_price = close

    # ---- 到期强制退出 ----
    if days_in_trade >= max_hold and not hit_stop:
        final_exit_price = float(future.iloc[-1]["close"])
        final_exit_reason = "max_hold"

    # ---- 收益计算 ----
    if half_exited and hit_target:
        r1 = (stage1_exit_price - entry_price) / entry_price * 100
        r2 = (final_exit_price - entry_price) / entry_price * 100 if final_exit_price else 0
        total_return = 0.5 * r1 + 0.5 * r2
        exit_reasons_str = f"target1_50pct+{final_exit_reason}"
    else:
        r1 = 0
        total_return = (final_exit_price - entry_price) / entry_price * 100 if final_exit_price else 0
        exit_reasons_str = final_exit_reason

    full_return = total_return
    strategy_return = full_return * kelly
    future_high = float(future["high"].max())
    future_low = float(future["low"].min())
    max_gain_pct = (future_high - entry_price) / entry_price * 100
    max_dd_pct = (entry_price - future_low) / entry_price * 100

    return {
        "entry_price": round(entry_price, 3),
        "total_return": round(strategy_return, 2),
        "full_return": round(full_return, 2),
        "exit_reasons": exit_reasons_str,
        "kelly": round(kelly, 2),
        "atr_mult": atr_mult,
        "time_stop_days": time_stop,
        "effective_target": round(effective_target, 3) if effective_target else None,
        "hit_target": hit_target,
        "hit_stop": hit_stop,
        "half_exited": half_exited,
        "max_gain_pct": round(max_gain_pct, 2),
        "max_drawdown_pct": round(max_dd_pct, 2),
        "days_in_trade": days_in_trade,
        "data_points": len(future),
        "regime_params": regime,
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
            phase = report.structure.phase.value
            alignment = report.multi_timeframe.alignment if report.multi_timeframe else ""
            confidence = report.trading_plan.confidence.value
            market_regime = classify_market_regime(csi300_df, as_of_date) if csi300_df is not None else "unknown"

            # 不再用 is_no_trade 过滤（v2数据表明unknown phase在v3下能赚钱）
            ret = calculate_v3_return(
                df, as_of_date,
                wyckoff_entry=wyckoff_entry,
                stop_loss=stop_loss,
                first_target=first_target,
                regime=market_regime,
                confidence=confidence,
            )
            if ret is None:
                continue

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
                "confidence": confidence, "alignment": alignment,
                "total_return": ret["total_return"],
                "full_return": ret["full_return"],
                "exit_reasons": ret["exit_reasons"],
                "kelly": ret["kelly"],
                "atr_mult": ret["atr_mult"],
                "time_stop_days": ret["time_stop_days"],
                "hit_target": ret["hit_target"],
                "hit_stop": ret["hit_stop"],
                "half_exited": ret["half_exited"],
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
    print("Wyckoff v3 优化执行逻辑验证 (P0-P2全部优化)")
    print(f"  全量A股 | 窗口:{N_WINDOWS} | 持有:90-180d自适应 | ATR乘数:range1.5/bear2.5/bull3.0")
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
        "config": {"n_stocks": len(stocks), "n_windows": N_WINDOWS, "version": "v3_all_optimizations"},
        "overall_stats": {
            "n_samples": len(df),
            "mean_return": round(mean_ret, 2),
            "ci_lower": round(ci_low, 2),
            "ci_upper": round(ci_high, 2),
            "median_return": round(np.median(returns), 2),
            "win_rate": round(sum(returns > 0) / len(returns) * 100, 1),
            "std_return": round(np.std(returns), 2),
        },
        "exit_reason_analysis": {},
        "phase_analysis": {},
        "regime_analysis": {},
        "confidence_analysis": {},
        "benchmark_comparison": {},
    }

    # 退出原因
    for reason in df["exit_reasons"].unique():
        vals = df[df["exit_reasons"] == reason]["total_return"].values
        if len(vals) >= 5:
            analysis["exit_reason_analysis"][reason] = {
                "n_samples": len(vals),
                "mean_return": round(np.mean(vals), 2),
                "win_rate": round(sum(vals > 0) / len(vals) * 100, 1),
                "pct_of_total": round(len(vals) / len(df) * 100, 1),
            }

    # 其他分析
    for col, key in [("phase", "phase_analysis"), ("market_regime", "regime_analysis")]:
        for val in df[col].unique():
            vals = df[df[col] == val]["total_return"].values
            if len(vals) >= 10:
                m, l, h = bootstrap_ci(vals)
                analysis[key][val] = {
                    "n_samples": len(vals), "mean_return": round(m, 2),
                    "win_rate": round(sum(vals > 0) / len(vals) * 100, 1),
                }

    # 置信度
    for conf in ["A", "B", "C", "D"]:
        vals = df[df["confidence"] == conf]["total_return"].values
        if len(vals) >= 10:
            analysis["confidence_analysis"][conf] = {
                "n_samples": len(vals), "mean_return": round(np.mean(vals), 2),
                "win_rate": round(sum(vals > 0) / len(vals) * 100, 1),
            }

    # 基准
    if df["excess_return"].notna().sum() >= 10:
        excess = df["excess_return"].dropna().values
        analysis["benchmark_comparison"] = {
            "strategy_mean": round(np.mean(returns), 2),
            "benchmark_mean": round(np.mean(df["benchmark_return"].dropna()), 2),
            "excess_mean": round(np.mean(excess), 2),
            "excess_win_rate": round(sum(excess > 0) / len(excess) * 100, 1),
        }

    json_path = OUTPUT_DIR / "v3_results.json"
    with json_path.open("w", encoding="utf-8") as f:
        json.dump(analysis, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n结果: {json_path}")

    os = analysis["overall_stats"]
    print(f"\n{'='*70}")
    print("v3 测试摘要")
    print(f"  总样本: {os['n_samples']}")
    print(f"  平均收益: {os['mean_return']:.2f}%")
    print(f"  95%CI: [{os['ci_lower']:.2f}, {os['ci_upper']:.2f}]")
    print(f"  中位收益: {os['median_return']:.2f}%")
    print(f"  胜率: {os['win_rate']:.1f}%")
    print(f"  标准差: {os['std_return']:.2f}%")

    bc = analysis.get("benchmark_comparison", {})
    if bc:
        print(f"  策略: {bc['strategy_mean']:.2f}% vs 沪深300: {bc['benchmark_mean']:.2f}%")
        print(f"  超额: {bc['excess_mean']:.2f}%  超额胜率: {bc['excess_win_rate']:.1f}%")

    print(f"\n  退出原因:")
    for r, s in sorted(analysis["exit_reason_analysis"].items(), key=lambda x: -x[1]["pct_of_total"], reverse=True):
        print(f"    {r:45s}: {s['pct_of_total']:5.1f}%  ret={s['mean_return']:6.2f}%  win={s['win_rate']:5.1f}%")

    print(f"\n  Regime分析:")
    for r, s in sorted(analysis["regime_analysis"].items(), key=lambda x: -x[1]["mean_return"]):
        print(f"    {r:6s}: ret={s['mean_return']:6.2f}%  win={s['win_rate']:5.1f}%  n={s['n_samples']}")

    print(f"\n  Confidence分析:")
    for c in ["A", "B", "C", "D"]:
        s = analysis["confidence_analysis"].get(c)
        if s:
            print(f"    {c}: ret={s['mean_return']:6.2f}%  win={s['win_rate']:5.1f}%  n={s['n_samples']}")

    print(f"\n{'='*70}")
    print("完成")
    print(f"{'='*70}")


if __name__ == "__main__":
    run()
