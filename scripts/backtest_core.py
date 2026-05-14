#!/usr/bin/env python3
"""
回测核心模块 — 所有回测脚本的共享逻辑
替代 run_tristrat_v6*.py 和 run_dual_strat*.py 中的重复实现
"""

import csv, json, math, random, sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent
_src_path = str(PROJECT_ROOT.parent)
if _src_path not in sys.path:
    sys.path.insert(0, _src_path)
from src.data.manager import DataManager
from src.data.tdx_loader import load_tdx_data
from src.wyckoff.engine import WyckoffEngine
from src.parallel import get_optimal_workers, worker_init
from scripts.utils.tdx_config import CSI300_PATH

MC_SIMS = 10000
COST_BUY = 0.00075
COST_SELL = 0.00175

REGIME_PARAMS = {
    "range": {"atr_mult": 1.5, "ts": 45, "mh": 90},
    "bear":  {"atr_mult": 2.5, "ts": 90, "mh": 180},
    "bull":  {"atr_mult": 3.0, "ts": 60, "mh": 120},
    "unknown": {"atr_mult": 2.0, "ts": 60, "mh": 120},
}

# ---------- 数据加载 ----------
def load_stocks(csv_path: Path, limit: int = 99999) -> List[Dict]:
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
                if len(syms) >= limit:
                    break
    return syms


def load_csi300() -> Optional[pd.DataFrame]:
    p = CSI300_PATH
    if p.exists():
        df = load_tdx_data(str(p))
        if df is not None and not df.empty:
            df["date"] = pd.to_datetime(df["date"])
            return df.sort_values("date").reset_index(drop=True)
    return None


# ---------- 窗口 ----------
def gen_windows(csi: pd.DataFrame, n: int = 20, min_year: int = 0, max_year: int = 9999,
                seed: int = 42) -> List[str]:
    if csi is None or len(csi) < 200:
        return []
    d = csi["date"].dt.strftime("%Y-%m-%d").tolist()
    d = [x for x in d if int(x[:4]) >= min_year and int(x[:4]) <= max_year]
    if len(d) < n + 200:
        return []
    random.seed(seed)
    return sorted(random.sample(d[:len(d) - 200], min(n, len(d) - 200)))


# ---------- 市场制度 ----------
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


# ---------- 指标 ----------
def calc_atr(s: pd.DataFrame, p: int = 20) -> float:
    if len(s) < p + 1:
        return 0.0
    tr_vals = []
    for i in range(1, min(p + 1, len(s))):
        hi = float(s.iloc[-i]["high"])
        lo = float(s.iloc[-i]["low"])
        pc = float(s.iloc[-i - 1]["close"])
        tr_vals.append(max(hi - lo, abs(hi - pc), abs(lo - pc)))
    return float(np.mean(tr_vals)) if tr_vals else 0.0


# ---------- 策略1: Wyckoff ----------
def trade_wyckoff(df: pd.DataFrame, as_of_date: str, csi: pd.DataFrame) -> Optional[Dict]:
    a = pd.Timestamp(as_of_date)
    av = df[df["date"] <= a]
    if len(av) < 100:
        return None
    try:
        eng = WyckoffEngine(lookback_days=400, weekly_lookback=120, monthly_lookback=40)
        rpt = eng.analyze(av, symbol="", period="日线", multi_timeframe=True)
    except Exception:
        return None
    rr = rpt.risk_reward
    we = rr.entry_price if (rr and rr.entry_price and rr.entry_price > 0) else None
    sl = rr.stop_loss if (rr and rr.stop_loss and rr.stop_loss > 0) else None
    ft = rr.first_target if (rr and rr.first_target and rr.first_target > 0) else None
    if rpt.signal.signal_type == "no_signal" or rpt.trading_plan.direction == "空仓观望":
        return None
    regime = get_regime(csi, as_of_date) if csi is not None else "unknown"
    if regime == "bear":
        return None
    p = REGIME_PARAMS.get(regime, REGIME_PARAMS["unknown"])
    atr_m, ts_d, mh = p["atr_mult"], p["ts"], p["mh"]
    f = df[df["date"] > a].head(mh)
    if len(f) < mh * 0.5:
        return None
    cc = float(av.iloc[-1]["close"])
    use_we = we and we > 0 and abs(we - cc) / cc > 0.001
    entry = we if use_we else cc
    if use_we and len(f.head(10)) > 0 and we < float(f.head(10)["low"].min()):
        return None
    hist = av.tail(60)
    atr = calc_atr(pd.concat([hist, f.head(20)]), 20) if len(f) >= 20 else entry * 0.02
    if atr <= 0:
        atr = entry * 0.02
    ss = sl if (sl and sl > 0) else entry * 0.93
    et = ft if (ft and ft > 0) else None
    atr_t = entry + 2.0 * atr
    eff_t = max(et, atr_t) if (et and et > entry) else (atr_t if atr_t > entry else None)
    peak = entry
    ts_p = None
    half = False
    s2 = False
    ep = None
    er = "max_hold"
    hs = False
    ht = False
    d_ = 0
    for _, rw in f.iterrows():
        d_ += 1
        c = float(rw["close"])
        hi = float(rw["high"])
        lo = float(rw["low"])
        peak = max(peak, hi)
        if lo <= ss:
            ep = ss
            er = "stop_loss"
            hs = True
            break
        if d_ <= 30 and not half and eff_t and hi >= eff_t:
            half = True
            s1p = eff_t
            s2 = True
            ts_p = peak - atr_m * atr
            ht = True
            continue
        if d_ == 30:
            s2 = True
            ts_p = peak - atr_m * atr
        if s2:
            t = peak - atr_m * atr
            ts_p = max(ts_p, t) if ts_p else t
            if lo <= ts_p:
                ep = ts_p
                er = "trailing_stop"
                break
            if d_ > ts_d and not half:
                ep = c
                er = "time_stop"
                break
        ep = c
    if not hs and d_ >= mh:
        ep = float(f.iloc[-1]["close"])
        er = "max_hold"
    if half and ht:
        r1 = (s1p - entry) / entry * 100
        r2 = (ep - entry) / entry * 100
        tr = 0.5 * r1 + 0.5 * r2
        er = f"target_50pct+{er}"
    else:
        tr = (ep - entry) / entry * 100
    tr -= (COST_BUY + COST_SELL) * 100
    return {"ret": round(tr, 2), "days": d_}


# ---------- 策略2: MA5/20金叉 ----------
def trade_ma(df: pd.DataFrame, as_of_date: str) -> Optional[Dict]:
    a = pd.Timestamp(as_of_date)
    h = df[df["date"] <= a].tail(30)
    if len(h) < 25:
        return None
    mf = float(h.tail(5)["close"].mean())
    ms = float(h.tail(20)["close"].mean())
    ph = df[df["date"] <= a].tail(30).head(25)
    if len(ph) < 25:
        return None
    pf = float(ph.tail(5)["close"].mean())
    ps = float(ph.tail(20)["close"].mean())
    if not (pf <= ps and mf > ms):
        return None
    entry = float(h.iloc[-1]["close"])
    fut = df[df["date"] > a]
    ed = None
    for i in range(5, min(120, len(fut) - 20)):
        sub = fut.iloc[:i + 20]
        sf = float(sub.tail(5)["close"].mean())
        ss = float(sub.tail(20)["close"].mean())
        if sf < ss:
            ed = i
            break
    if ed is None:
        ed = min(120, len(fut) - 1)
    fx = fut.iloc[:ed + 1]
    if len(fx) < 5:
        return None
    ep = float(fx.iloc[-1]["close"])
    tr = (ep - entry) / entry * 100
    tr -= (COST_BUY + COST_SELL) * 100
    return {"ret": round(tr, 2), "days": len(fx)}


# ---------- 策略3: 短期反转 ----------
def trade_str_reversal(df: pd.DataFrame, as_of_date: str) -> Optional[Dict]:
    a = pd.Timestamp(as_of_date)
    h = df[df["date"] <= a].tail(10)
    if len(h) < 8:
        return None
    p5 = float(h.iloc[-1]["close"])
    p0 = float(h.iloc[-6]["close"]) if len(h) >= 6 else float(h.iloc[0]["close"])
    ret_5d = (p5 - p0) / p0 * 100
    if ret_5d > -5.0:
        return None
    entry = p5
    fut = df[df["date"] > a].head(5)
    if len(fut) < 3:
        return None
    tp = entry * 1.04
    sl = entry * 0.96
    ep, ed, er = entry, len(fut), "max_hold"
    for i, (_, rw) in enumerate(fut.iterrows()):
        c, hi, lo = float(rw["close"]), float(rw["high"]), float(rw["low"])
        if hi >= tp:
            ep, ed, er = tp, i + 1, "str_tp"
            break
        if lo <= sl:
            ep, sl, er = sl, i + 1, "str_sl"
            break
        ep, ed = c, i + 1
    tr = (ep - entry) / entry * 100
    tr -= (COST_BUY + COST_SELL) * 100
    return {"ret": round(tr, 2), "days": ed}


# ---------- 统计 ----------
STRATEGY_MAP = {
    "wyckoff": trade_wyckoff,
    "ma_cross": trade_ma,
    "str_reversal": trade_str_reversal,
}


def ann_sharpe(rets: np.ndarray, avg_days: float) -> float:
    if len(rets) < 5 or np.std(rets) == 0 or avg_days <= 0:
        return 0.0
    return float(np.mean(rets) / np.std(rets) * math.sqrt(252.0 / avg_days))


def compute_stats(sub_df: pd.DataFrame) -> Dict:
    rets = sub_df["ret"].values
    ad = float(np.mean(sub_df["days"]))
    return {
        "n": len(sub_df),
        "mean_ret": round(float(np.mean(rets)), 2),
        "median_ret": round(float(np.median(rets)), 2),
        "std": round(float(np.std(rets)), 2),
        "win_rate": round(float(sum(rets > 0) / len(rets) * 100), 1),
        "avg_days": round(ad, 1),
        "sharpe": round(ann_sharpe(rets, ad), 3),
    }


def process_stock(args: Tuple) -> List[Dict]:
    si, windows, csi, strategies, with_costs = args
    sym = si["symbol"]
    trades = []
    try:
        dm = DataManager()
        df = dm.get_data(sym)
        if df is None or df.empty or len(df) < 300:
            return trades
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)
        for w in windows:
            for s_name in strategies:
                func = STRATEGY_MAP.get(s_name)
                if func is None:
                    continue
                try:
                    r = func(df, w, csi) if s_name == "wyckoff" else func(df, w)
                    if r:
                        trades.append({"strategy": s_name, "symbol": sym, "window": w, **r})
                except Exception:
                    continue
    except Exception:
        pass
    return trades


def run_backtest(strategies: List[str], n_windows: int = 20,
                 min_year: int = 0, max_year: int = 9999,
                 with_costs: bool = True, output_dir: str = "",
                 n_stocks_limit: int = 99999) -> Dict:
    """统一回测入口"""
    np.random.seed(42)

    # 根据成本标志设置全局成本常量（在fork前设置，子进程继承）
    global COST_BUY, COST_SELL
    if not with_costs:
        COST_BUY = 0.0
        COST_SELL = 0.0

    stocks = load_stocks(PROJECT_ROOT.parent / "data" / "stock_list.csv", n_stocks_limit)
    csi = load_csi300()
    windows = gen_windows(csi, n_windows, min_year, max_year)

    all_trades = []
    mw = get_optimal_workers()
    bs = mw * 4
    args_list = [(s, windows, csi, strategies, with_costs) for s in stocks]

    with ProcessPoolExecutor(max_workers=mw, initializer=worker_init) as ex:
        for b in range(0, len(args_list), bs):
            batch = args_list[b:b + bs]
            futures = {ex.submit(process_stock, a): a[0]["symbol"] for a in batch}
            for f in as_completed(futures):
                try:
                    all_trades.extend(f.result(timeout=300))
                except Exception:
                    pass

    if not all_trades:
        return {"config": {"strategies": strategies, "n_trades": 0}}

    df = pd.DataFrame(all_trades)

    # 单策略统计
    results = {}
    for sn in strategies:
        sub = df[df["strategy"] == sn]
        if len(sub) >= 5:
            results[sn] = compute_stats(sub)

    # 相关性矩阵
    corr_data = {}
    strats = list(results.keys())
    for i, t1 in enumerate(strats):
        for t2 in strats[i + 1:]:
            merged = df[df["strategy"] == t1][["window", "symbol", "ret"]].merge(
                df[df["strategy"] == t2][["window", "symbol", "ret"]],
                on=["window", "symbol"], suffixes=("_1", "_2"))
            if len(merged) >= 5:
                corr_data[f"{t1}_vs_{t2}"] = {
                    "corr": round(float(merged["ret_1"].corr(merged["ret_2"])), 3),
                    "n": len(merged)}

    # 组合夏普
    n_strat = len(strats)
    if n_strat >= 2:
        s_vals = [results[s]["sharpe"] for s in strats]
        avg_s = np.mean(s_vals)
        rho_matrix = np.ones((n_strat, n_strat))
        for i in range(n_strat):
            for j in range(n_strat):
                if i < j:
                    k = f"{strats[i]}_vs_{strats[j]}"
                    if k in corr_data:
                        rho_matrix[i][j] = rho_matrix[j][i] = corr_data[k]["corr"]
        avg_rho = (np.sum(rho_matrix) - n_strat) / (n_strat * (n_strat - 1))
        combo = avg_s * math.sqrt(n_strat / (1 + (n_strat - 1) * avg_rho))
    elif n_strat == 1:
        combo = results[strats[0]]["sharpe"]
    else:
        combo = 0

    # 蒙特卡洛
    mc = {}
    for sn in strats:
        sub = df[df["strategy"] == sn]
        if len(sub) < 20:
            continue
        rets = sub["ret"].values
        ad = float(np.mean(sub["days"]))
        sims = [ann_sharpe(np.random.choice(rets, size=len(rets), replace=True), ad)
                for _ in range(MC_SIMS)]
        mc[sn] = {
            "mean": round(float(np.mean(sims)), 3),
            "ci_5": round(float(np.percentile(sims, 5)), 3),
            "ci_95": round(float(np.percentile(sims, 95)), 3),
            "p_pos": round(float(sum(s > 0 for s in sims) / len(sims) * 100), 1),
        }

    return {
        "config": {
            "n_stocks": len(stocks),
            "n_windows": n_windows,
            "min_year": min_year,
            "max_year": max_year,
            "mc_seed": 42,
            "window_seed": 42,
            "with_costs": with_costs,
            "cost_model": {"buy_pct": COST_BUY * 100, "sell_pct": COST_SELL * 100,
                           "round_trip_pct": (COST_BUY + COST_SELL) * 100},
            "strategies_used": strategies,
        },
        "strategies": results,
        "correlations": corr_data,
        "portfolio": {
            "multi_strat_sharpe": round(combo, 3),
            "method": "estimated_from_correlation",
            "formula": "avg(sharpe) * sqrt(n / (1 + (n-1) * avg(corr)))",
            "limitation": "基于各策略独立夏普和平均相关性估算, 非真实组合净值序列",
        },
        "monte_carlo": mc,
        "reproducibility": {
            "mc_seeded": True,
            "mc_seed": 42,
            "window_seeded": True,
            "window_seed": 42,
        },
    }
