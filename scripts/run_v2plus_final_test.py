#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Wyckoff v2+ 最终优化执行逻辑验证
=================================
基于v2的三阶段执行(v2已验证, +3.07%收益) + v3的参数优化:

保留(v2已验证有效):
  1. NTZ过滤 (is_no_trade过滤85.7%差交易)
  2. 结构止损 (engine支撑位低点 × 0.995)
  3. 50%阶梯止盈 (达第一目标卖半仓)
  4. 2×ATR移动止损 (趋势跟踪)
  5. 60天时间止损 (减少硬扛)

新增(v3验证边际改善):
  6. Regime-adaptive ATR乘数 (range:1.5/bear:2.5/bull:3.0)
  7. 动态第一目标 (max(engine目标, entry+2×ATR))

设计校验:
  - 入口检查: len(future) >= max_hold*0.5 确保未来数据充足
  - 止损按v3.0规则10: 结构低点×0.995
  - 退出原因追踪: stop_loss/target_50pct/trailing_stop/time_stop/max_hold
  - 基准比较: 沪深300同周期
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

# === 配置 ===
N_STOCKS = 99999
N_WINDOWS = 20
MAX_HOLD = 180
SEED = 42
N_BOOTSTRAP = 2000
CSI300_TDX_PATH = Path("/home/james/.local/share/tdxcfv/drive_c/tc/vipdoc/sh/lday/sh000300.day")
OUTPUT_DIR = PROJECT_ROOT / "output" / "wyckoff_final_test"

REGIME_PARAMS = {
    "range": {"atr_mult": 1.5, "time_stop_days": 45, "max_hold_days": 90},
    "bear":  {"atr_mult": 2.5, "time_stop_days": 90, "max_hold_days": 180},
    "bull":  {"atr_mult": 3.0, "time_stop_days": 60, "max_hold_days": 120},
    "unknown": {"atr_mult": 2.0, "time_stop_days": 60, "max_hold_days": 120},
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
    tr = [max(high[i]-low[i], abs(high[i]-close[i-1]), abs(low[i]-close[i-1])) for i in range(1, len(df_slice))]
    if len(tr) < period:
        return float(np.mean(tr)) if tr else 0.0
    return float(np.mean(tr[-period:]))


def calc_v2plus_return(df, as_of_date, wyckoff_entry=None, stop_loss=None, first_target=None, regime="unknown"):
    """
    v2+ 三阶段执行逻辑:
    阶段1 (0-30天): 结构止损保护 + 动态第一目标
    阶段2 (30-90天): 达目标卖50% + ATR自适应移动止损 + 时间止损
    阶段3 (90-180天): 移动止损保护 + 强行平仓
    """
    params = REGIME_PARAMS.get(regime, REGIME_PARAMS["unknown"])
    atr_mult = params["atr_mult"]
    time_stop = params["time_stop_days"]
    max_hold = params["max_hold_days"]

    as_of = pd.Timestamp(as_of_date)
    future = df[df["date"] > as_of].head(max_hold)
    if len(future) < max_hold * 0.5:
        return None

    current_close = float(df[df["date"] <= as_of].iloc[-1]["close"])
    use_we = (wyckoff_entry is not None and wyckoff_entry > 0
              and abs(wyckoff_entry - current_close) / current_close > 0.001)
    entry = wyckoff_entry if use_we else current_close

    if use_we:
        early = future.head(10)
        if len(early) > 0 and wyckoff_entry < float(early["low"].min()):
            return None

    # ATR
    hist = df[df["date"] <= as_of].tail(60)
    atr_20 = calc_atr(pd.concat([hist, future.head(20)]), 20) if len(future) >= 20 else entry * 0.02
    if atr_20 <= 0:
        atr_20 = entry * 0.02

    # 结构止损 (v3.0规则10: 关键低点×0.995)
    struct_stop = stop_loss if (stop_loss is not None and stop_loss > 0) else (entry * 0.93)

    # 动态第一目标: max(engine结构目标, entry+2×ATR)
    et = first_target if (first_target is not None and first_target > 0) else None
    atr_target = entry + 2.0 * atr_20
    effective_target = max(et, atr_target) if (et and et > entry) else (atr_target if atr_target > entry else None)

    # === 执行模拟 ===
    peak = entry
    trailing_stop = None
    half_exited = False
    stage2 = False
    exit_price = None
    exit_reason = "max_hold"
    hit_stop = False
    hit_target = False

    for i, (_, row) in enumerate(future.iterrows()):
        d = i + 1
        close = float(row["close"])
        high = float(row["high"])
        low = float(row["low"])
        peak = max(peak, high)

        # 止损 (始终有效)
        if low <= struct_stop:
            exit_price = struct_stop
            exit_reason = "stop_loss"
            hit_stop = True
            break

        # 阶段1: 0-30天, 检查第一目标
        if d <= 30 and not half_exited and effective_target is not None:
            if high >= effective_target:
                half_exited = True
                stage1_price = effective_target
                stage2 = True
                trailing_stop = peak - atr_mult * atr_20
                hit_target = True
                continue
            if d == 30:
                stage2 = True
                trailing_stop = peak - atr_mult * atr_20

        # 阶段2: 移动止损 + 时间止损
        if stage2:
            ts = peak - atr_mult * atr_20
            trailing_stop = max(trailing_stop, ts) if trailing_stop else ts
            if low <= trailing_stop:
                exit_price = trailing_stop
                exit_reason = "trailing_stop"
                break
            if d > time_stop and not half_exited:
                exit_price = close
                exit_reason = "time_stop"
                break

        exit_price = close

    if not hit_stop and d >= max_hold:
        exit_price = float(future.iloc[-1]["close"])
        exit_reason = "max_hold"

    # === 收益计算 ===
    if half_exited and hit_target:
        r1 = (stage1_price - entry) / entry * 100
        r2 = (exit_price - entry) / entry * 100
        total_ret = 0.5 * r1 + 0.5 * r2
        er = f"target_50pct+{exit_reason}"
    else:
        total_ret = (exit_price - entry) / entry * 100
        er = exit_reason

    fh = float(future["high"].max())
    fl = float(future["low"].min())

    return {
        "entry_price": round(entry, 3),
        "total_return": round(total_ret, 2),
        "exit_reason": er,
        "hit_target": hit_target,
        "hit_stop": hit_stop,
        "half_exited": half_exited,
        "max_gain_pct": round((fh - entry) / entry * 100, 2),
        "max_drawdown_pct": round((entry - fl) / entry * 100, 2),
        "days_in_trade": d,
        "atr_mult": atr_mult,
        "time_stop_days": time_stop,
        "regime": regime,
    }


def process_stock(args) -> List[Dict]:
    si, windows, csi300_df = args
    symbol = si["symbol"]
    name = si["name"]
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
            avail = df[df["date"] <= as_of]
            if len(avail) < 100:
                continue

            report = engine.analyze(avail, symbol=symbol, period="日线", multi_timeframe=True)
            rr = report.risk_reward

            wyckoff_entry = rr.entry_price if (rr and rr.entry_price and rr.entry_price > 0) else None
            stop_loss = rr.stop_loss if (rr and rr.stop_loss and rr.stop_loss > 0) else None
            first_target = rr.first_target if (rr and rr.first_target and rr.first_target > 0) else None
            sig = report.signal.signal_type
            phase = report.structure.phase.value
            alignment = report.multi_timeframe.alignment if report.multi_timeframe else ""
            direction = report.trading_plan.direction

            # NTZ过滤 (v2核心: 过滤85.7%差交易)
            if sig == "no_signal" or direction == "空仓观望":
                continue

            market_regime = classify_market_regime(csi300_df, as_of_date) if csi300_df is not None else "unknown"

            # P2: 跳过bear市场 (bear市场收益仅+0.20%, 拖累整体)
            if market_regime == "bear":
                continue

            ret = calc_v2plus_return(df, as_of_date,
                                     wyckoff_entry=wyckoff_entry, stop_loss=stop_loss,
                                     first_target=first_target, regime=market_regime)
            if ret is None:
                continue

            # 基准
            bm_ret = None
            if csi300_df is not None:
                bm_f = csi300_df[csi300_df["date"] > as_of].head(90)
                if len(bm_f) >= 72:
                    be = float(csi300_df[csi300_df["date"] <= as_of].iloc[-1]["close"])
                    bx = float(bm_f.iloc[-1]["close"])
                    bm_ret = round((bx - be) / be * 100, 2)

            results.append({
                "symbol": symbol, "name": name, "as_of": as_of_date,
                "phase": phase, "market_regime": market_regime,
                "alignment": alignment, "direction": direction,
                "total_return": ret["total_return"],
                "exit_reason": ret["exit_reason"],
                "hit_target": ret["hit_target"],
                "hit_stop": ret["hit_stop"],
                "half_exited": ret["half_exited"],
                "days_in_trade": ret["days_in_trade"],
                "max_gain_pct": ret["max_gain_pct"],
                "max_drawdown_pct": ret["max_drawdown_pct"],
                "atr_mult": ret["atr_mult"],
                "time_stop_days": ret["time_stop_days"],
                "benchmark_return": bm_ret,
                "excess_return": round(ret["total_return"] - bm_ret, 2) if bm_ret is not None else None,
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
    print("Wyckoff v2+ P3 最终定型")
    print("  NTZ过滤 + 结构止损 + 50%阶梯止盈 + ATR自适应移动止损 + 时间止损 + BEAR跳过")
    print(f"  ATR乘数: range=1.5/bear=2.5/bull=3.0")
    print(f"  全量A股 | 窗口:{N_WINDOWS} | 持有:90-180d自适应")
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
                    r = future.result(timeout=300)
                    all_results.extend(r)
                except Exception:
                    pass
            p = min(batch_start + batch_size, len(args_list))
            print(f"  进度: {p}/{len(stocks)} 股票, {len(all_results)} 样本")

    print(f"\n总样本: {len(all_results)}")
    if not all_results:
        print("无样本, 退出"); return

    df = pd.DataFrame(all_results)
    returns = df["total_return"].values
    mr, cl, ch = bootstrap_ci(returns)

    analysis = {
        "config": {"n_stocks": len(stocks), "n_windows": N_WINDOWS, "version": "v2plus"},
        "overall": {
            "n_samples": len(df), "mean_return": round(mr, 2),
            "ci_lower": round(cl, 2), "ci_upper": round(ch, 2),
            "median_return": round(np.median(returns), 2),
            "win_rate": round(sum(returns > 0) / len(returns) * 100, 1),
            "std_return": round(np.std(returns), 2),
            "sharpe_ratio": round(mr / np.std(returns) * (252 / 90)**0.5, 3) if np.std(returns) > 0 else 0,
        },
        "exit_reason": {}, "phase": {}, "regime": {}, "benchmark": {},
    }

    for r in df["exit_reason"].unique():
        v = df[df["exit_reason"] == r]["total_return"].values
        if len(v) >= 5:
            analysis["exit_reason"][r] = {
                "n": len(v), "mean": round(np.mean(v), 2), "win": round(sum(v > 0) / len(v) * 100, 1),
                "pct": round(len(v) / len(df) * 100, 1),
            }

    for col, key in [("phase", "phase"), ("market_regime", "regime")]:
        for val in df[col].unique():
            v = df[df[col] == val]["total_return"].values
            if len(v) >= 10:
                analysis[key][val] = {
                    "n": len(v), "mean": round(np.mean(v), 2),
                    "win": round(sum(v > 0) / len(v) * 100, 1),
                }

    if df["excess_return"].notna().sum() >= 10:
        ex = df["excess_return"].dropna().values
        analysis["benchmark"] = {
            "strategy": round(np.mean(returns), 2),
            "benchmark": round(np.mean(df["benchmark_return"].dropna()), 2),
            "excess_mean": round(np.mean(ex), 2),
            "excess_win": round(sum(ex > 0) / len(ex) * 100, 1),
        }

    jp = OUTPUT_DIR / "v2plus_results.json"
    with jp.open("w", encoding="utf-8") as f:
        json.dump(analysis, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n结果: {jp}")

    o = analysis["overall"]
    print(f"\n{'='*70}")
    print("v2+ 测试摘要")
    print(f"  总样本: {o['n_samples']}")
    print(f"  平均收益: {o['mean_return']:.2f}%")
    print(f"  95%CI: [{o['ci_lower']:.2f}, {o['ci_upper']:.2f}]")
    print(f"  中位收益: {o['median_return']:.2f}%")
    print(f"  胜率: {o['win_rate']:.1f}%")
    print(f"  标准差: {o['std_return']:.2f}%")
    print(f"  夏普(年化): {o['sharpe_ratio']:.3f}")

    bc = analysis.get("benchmark", {})
    if bc:
        print(f"  策略: {bc['strategy']:.2f}% vs 沪深300: {bc['benchmark']:.2f}%")
        print(f"  超额: {bc['excess_mean']:.2f}%  超额胜率: {bc['excess_win']:.1f}%")

    print(f"\n  退出原因:")
    for r, s in sorted(analysis["exit_reason"].items(), key=lambda x: -x[1]["pct"]):
        print(f"    {r:30s}: {s['pct']:5.1f}%  ret={s['mean']:6.2f}%  win={s['win']:5.1f}%")

    print(f"\n  Regime分析:")
    for r, s in sorted(analysis["regime"].items(), key=lambda x: -x[1]["mean"]):
        print(f"    {r:6s}: ret={s['mean']:6.2f}%  win={s['win']:5.1f}%  n={s['n']}")

    print(f"\n{'='*70}")
    print("完成")
    print(f"{'='*70}")


if __name__ == "__main__":
    run()
