#!/usr/bin/env python3
"""
每日交易信号生成 — Wyckoff + MA5/20 金叉
===========================================
使用最新通达信日线数据，对全量股票生成当前交易信号。

输出:
  - 标准输出: 信号汇总表
  - output/daily_signals/signals_{date}.json: 完整信号数据
  - output/daily_signals/signals_{date}.csv: CSV格式
"""

import csv, json, sys, time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
from src.data.manager import DataManager
from src.data.tdx_loader import load_tdx_data
from src.wyckoff.engine import WyckoffEngine
from src.parallel import get_optimal_workers, worker_init

CSI300_PATH = Path("/home/james/.local/share/tdxcfv/drive_c/tc/vipdoc/sh/lday/sh000300.day")
OUTPUT_DIR = PROJECT_ROOT / "output" / "daily_signals"

# A股交易成本模型
COST_BUY = 0.00075    # 买入: 佣金万2.5 + 滑点万5
COST_SELL = 0.00175   # 卖出: 印花税千1 + 佣金万2.5 + 滑点万5
COST_ROUND_TRIP = COST_BUY + COST_SELL  # 完整回合 0.25%

REGIME_PARAMS_WYCKOFF = {
    "range": {"atr_mult": 1.5, "ts": 45, "mh": 90},
    "bear":  {"atr_mult": 2.5, "ts": 90, "mh": 180},
    "bull":  {"atr_mult": 3.0, "ts": 60, "mh": 120},
    "unknown": {"atr_mult": 2.0, "ts": 60, "mh": 120},
}

# ---------- helpers ----------
def load_stock_list(csv_path: Path) -> List[Dict]:
    syms = []
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            c = row.get("code", "").strip()
            m = row.get("market", "").strip().upper()
            n = row.get("name", "").replace("\x00", "").strip()
            if not (c.isdigit() and len(c) == 6 and m in {"SH", "SZ"}):
                continue
            if c.startswith(("600", "601", "603", "605", "688", "689",
                             "000", "001", "002", "003", "300", "301", "302")):
                syms.append({"symbol": f"{c}.{m}", "code": c, "market": m, "name": n})
    return syms


def load_csi300() -> Optional[pd.DataFrame]:
    if CSI300_PATH.exists():
        df = load_tdx_data(str(CSI300_PATH))
        if df is not None and not df.empty:
            df["date"] = pd.to_datetime(df["date"])
            return df.sort_values("date").reset_index(drop=True)
    return None


def get_latest_date(csi: pd.DataFrame, stock_dates: List[str]) -> str:
    """取沪深300和个股数据的共同最新日期"""
    csi_last = str(csi["date"].max().date()) if csi is not None else ""
    stock_last = max(stock_dates) if stock_dates else ""
    candidates = [d for d in [csi_last, stock_last] if d]
    return min(candidates) if candidates else datetime.now().strftime("%Y-%m-%d")


def get_regime(csi: pd.DataFrame, d: str) -> str:
    if csi is None:
        return "unknown"
    a = pd.Timestamp(d)
    h = csi[csi["date"] <= a]
    if len(h) < 120:
        return "unknown"
    c = float(h.iloc[-1]["close"])
    m120 = float(h.tail(120)["close"].mean())
    m60 = float(h.tail(60)["close"].mean())
    if c > m120 * 1.02 and m60 > m120:
        return "bull"
    if c < m120 * 0.98:
        return "bear"
    return "range"


def get_stock_own_regime(df: pd.DataFrame, as_of_date: str) -> str:
    """判断个股自身的市场制度"""
    a = pd.Timestamp(as_of_date)
    h = df[df["date"] <= a]
    if len(h) < 120:
        return "unknown"
    c = float(h.iloc[-1]["close"])
    ma120 = float(h.tail(120)["close"].mean())
    ma60 = float(h.tail(60)["close"].mean())
    if c > ma120 * 1.03 and ma60 > ma120:
        return "bull"
    if c < ma120 * 0.97:
        return "bear"
    return "range"


# ---------- 策略1: Wyckoff 信号 ----------
def check_wyckoff_signal(df: pd.DataFrame, symbol: str, as_of_date: str,
                         csi: pd.DataFrame) -> Optional[Dict]:
    a = pd.Timestamp(as_of_date)
    av = df[df["date"] <= a]
    if len(av) < 100:
        return None
    try:
        eng = WyckoffEngine(lookback_days=400, weekly_lookback=120, monthly_lookback=40)
        rpt = eng.analyze(av, symbol=symbol, period="日线", multi_timeframe=True)
    except Exception:
        return None

    rr = rpt.risk_reward
    if rpt.signal.signal_type == "no_signal" or rpt.trading_plan.direction == "空仓观望":
        return None

    macro_regime = get_regime(csi, as_of_date)
    stock_regime = get_stock_own_regime(df, as_of_date)
    regime = stock_regime if stock_regime != "unknown" else macro_regime
    if macro_regime == "bear":
        return None

    close_now = float(av.iloc[-1]["close"])
    entry = rr.entry_price if (rr and rr.entry_price and rr.entry_price > 0) else close_now
    stop_loss = rr.stop_loss if (rr and rr.stop_loss and rr.stop_loss > 0) else None
    target = rr.first_target if (rr and rr.first_target and rr.first_target > 0) else None

    phase = rpt.structure.phase.value if rpt.structure else "unknown"
    confidence = rpt.signal.confidence.value if rpt.signal and rpt.signal.confidence else "D"

    gross_upside = (target / entry - 1) * 100 if target and target > entry else 0
    net_upside = gross_upside - COST_ROUND_TRIP * 100 if gross_upside > 0 else gross_upside

    return {
        "symbol": symbol,
        "strategy": "wyckoff",
        "action": "buy",
        "entry_price": round(entry, 3),
        "stop_loss": round(stop_loss, 3) if stop_loss else None,
        "take_profit": round(target, 3) if target else None,
        "confidence": confidence,
        "phase": phase,
        "regime": regime,
        "current_price": round(close_now, 3),
        "upside_pct": round(gross_upside, 2) if target and target > entry else None,
        "net_upside_pct": round(net_upside, 2) if target and target > entry else None,
        "risk_pct": round((1 - stop_loss / entry) * 100, 2) if stop_loss else None,
        "est_cost_pct": round(COST_ROUND_TRIP * 100, 3),
    }


# ---------- 策略2: MA5/20 金叉信号 (含质量过滤) ----------
def check_ma_signal(df: pd.DataFrame, symbol: str, as_of_date: str) -> Optional[Dict]:
    a = pd.Timestamp(as_of_date)
    h = df[df["date"] <= a].tail(30)
    if len(h) < 25:
        return None

    ma5 = float(h.tail(5)["close"].mean())
    ma20 = float(h.tail(20)["close"].mean())

    ph = df[df["date"] <= a].tail(30).head(25)
    if len(ph) < 25:
        return None
    prev_ma5 = float(ph.tail(5)["close"].mean())
    prev_ma20 = float(ph.tail(20)["close"].mean())

    # 金叉: 前一日无金叉, 今日金叉
    if not (prev_ma5 <= prev_ma20 and ma5 > ma20):
        return None

    close_now = float(h.iloc[-1]["close"])

    # 计算ATR(20)和均线斜率
    tr_vals = []
    for i in range(1, min(21, len(h))):
        hi, lo, pc = float(h.iloc[-i]["high"]), float(h.iloc[-i]["low"]), float(h.iloc[-i - 1]["close"])
        tr_vals.append(max(hi - lo, abs(hi - pc), abs(lo - pc)))
    atr = float(np.mean(tr_vals)) if tr_vals else close_now * 0.02

    ma5_10d_ago = float(h.iloc[-10]["close"]) if len(h) >= 10 else ma5
    ma5_slope = (ma5 - ma5_10d_ago) / ma5_10d_ago if ma5_10d_ago > 0 else 0

    # ---- 三层质量过滤器 ----
    filter_atr = atr / close_now >= 0.015
    filter_slope = ma5_slope >= 0.005
    filter_volume = True
    if "amount" in h.columns:
        avg_amount = float(h.tail(20)["amount"].mean())
        curr_amount = float(h.iloc[-1]["amount"])
        filter_volume = curr_amount >= avg_amount * 0.8

    if not filter_atr:
        return None

    filter_score = sum([filter_atr, filter_slope, filter_volume])
    if filter_score >= 2:
        confidence = "B"
    elif filter_score == 1:
        confidence = "C"
    else:
        return None

    gross_upside = 3 * atr / close_now * 100
    net_upside = gross_upside - COST_ROUND_TRIP * 100

    return {
        "symbol": symbol,
        "strategy": "ma_cross",
        "action": "buy",
        "entry_price": round(close_now, 3),
        "ma5": round(ma5, 3),
        "ma20": round(ma20, 3),
        "stop_loss": round(close_now - 2 * atr, 3),
        "take_profit": round(close_now + 3 * atr, 3),
        "confidence": confidence,
        "phase": "golden_cross",
        "regime": "",
        "current_price": round(close_now, 3),
        "upside_pct": round(gross_upside, 2),
        "net_upside_pct": round(net_upside, 2),
        "risk_pct": round(2 * atr / close_now * 100, 2),
        "est_cost_pct": round(COST_ROUND_TRIP * 100, 3),
    }


# ---------- 多进程处理 ----------
def process_stock(args):
    si, as_of_date, csi = args
    sym, name = si["symbol"], si["name"]
    signals = []
    try:
        dm = DataManager()
        df = dm.get_data(sym)
        if df is None or df.empty or len(df) < 300:
            return signals
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)

        w = check_wyckoff_signal(df, sym, as_of_date, csi)
        if w:
            w["name"] = name
            signals.append(w)

        m = check_ma_signal(df, sym, as_of_date)
        if m:
            m["name"] = name
            signals.append(m)
    except Exception:
        pass
    return signals


# ---------- 主流程 ----------
def run():
    t0 = time.time()
    print("=" * 70)
    print("每日交易信号生成: Wyckoff + MA5/20金叉")
    print("=" * 70)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # 加载数据
    stocks = load_stock_list(PROJECT_ROOT / "data" / "stock_list.csv")
    print(f"股票池: {len(stocks)}只")

    csi = load_csi300()
    csi_last = str(csi["date"].max().date()) if csi is not None else "unknown"
    print(f"沪深300: {len(csi) if csi is not None else 0}行, 最新日期: {csi_last}")

    as_of_date = csi_last
    print(f"分析日期: {as_of_date}")

    # 多进程处理
    all_signals = []
    mw = get_optimal_workers()
    bs = mw * 4
    args_list = [(s, as_of_date, csi) for s in stocks]

    with ProcessPoolExecutor(max_workers=mw, initializer=worker_init) as ex:
        for b in range(0, len(args_list), bs):
            batch = args_list[b:b + bs]
            futures = {ex.submit(process_stock, a): a[0]["symbol"] for a in batch}
            for f in as_completed(futures):
                try:
                    all_signals.extend(f.result(timeout=120))
                except:
                    pass
            n = min(b + bs, len(args_list))
            elapsed = time.time() - t0
            print(f"  [{elapsed:6.1f}s] {n}/{len(stocks)} 股票, {len(all_signals)}信号")

    if not all_signals:
        print("\n无交易信号生成")
        return

    # 整理输出
    df = pd.DataFrame(all_signals)

    # 信号汇总
    wyc = df[df["strategy"] == "wyckoff"]
    ma = df[df["strategy"] == "ma_cross"]

    print(f"\n{'=' * 70}")
    print(f"信号汇总: {len(df)}条")
    print(f"  Wyckoff: {len(wyc)}条")
    print(f"  MA5/20金叉: {len(ma)}条")

    # 输出信号表
    print(f"\n{'=' * 70}")
    print("交易信号清单")
    print(f"{'代码':>10s} {'名称':>8s} {'策略':10s} {'方向':6s} {'当前价':>8s} {'入场价':>8s} {'止损':>8s} {'目标':>8s} {'盈亏比':>6s} {'置信度':6s}")
    print("-" * 90)

    # 按策略分组输出
    if len(wyc) > 0:
        print(f"\n--- Wyckoff 信号 ({len(wyc)}条) ---")
        for _, r in wyc.sort_values("upside_pct", ascending=False).iterrows():
            rr = f"{r['upside_pct']:.1f}/{r['risk_pct']:.1f}" if r.get('upside_pct') and r.get('risk_pct') else "-"
            print(f"  {r['symbol']:>10s} {r.get('name',''):>8s} {'Wyckoff':10s} {'做多':6s} "
                  f"{r['current_price']:>8.2f} {r['entry_price']:>8.2f} "
                  f"{r['stop_loss'] or 0:>8.2f} {r['take_profit'] or 0:>8.2f} "
                  f"{rr:>6s} {r['confidence']:6s}")

    if len(ma) > 0:
        print(f"\n--- MA5/20金叉 信号 ({len(ma)}条) ---")
        for _, r in ma.sort_values("upside_pct", ascending=False).iterrows():
            rr = f"{r['upside_pct']:.1f}/{r['risk_pct']:.1f}"
            print(f"  {r['symbol']:>10s} {r.get('name',''):>8s} {'MA金叉':10s} {'做多':6s} "
                  f"{r['current_price']:>8.2f} {r['entry_price']:>8.2f} "
                  f"{r['stop_loss']:>8.2f} {r['take_profit']:>8.2f} "
                  f"{rr:>6s} {r['confidence']:6s}")

    # 按置信度汇总
    print(f"\n{'=' * 70}")
    print("按置信度分布:")
    if "confidence" in df.columns:
        for lvl in ["A", "B", "C", "D"]:
            cnt = len(df[df["confidence"] == lvl])
            if cnt > 0:
                print(f"  {lvl}级: {cnt}条")

    print(f"\n按策略分布:")
    print(f"  Wyckoff: {len(wyc)}条")
    print(f"  MA5/20金叉: {len(ma)}条")

    # 保存JSON
    ts = as_of_date
    json_path = OUTPUT_DIR / f"signals_{ts}.json"
    csv_path = OUTPUT_DIR / f"signals_{ts}.csv"

    records = df.to_dict("records")
    with json_path.open("w", encoding="utf-8") as f:
        json.dump({
            "date": ts,
            "total_signals": len(records),
            "n_stocks_scanned": len(stocks),
            "by_strategy": {"wyckoff": len(wyc), "ma_cross": len(ma)},
            "signals": records,
        }, f, ensure_ascii=False, indent=2, default=str)

    df.to_csv(csv_path, index=False, encoding="utf-8-sig")

    elapsed = time.time() - t0
    print(f"\n{'=' * 70}")
    print(f"完成. 耗时: {elapsed:.1f}s")
    print(f"JSON: {json_path}")
    print(f"CSV:  {csv_path}")
    print("=" * 70)


if __name__ == "__main__":
    run()
