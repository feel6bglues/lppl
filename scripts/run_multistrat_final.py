#!/usr/bin/env python3
# RESEARCH ONLY — not production code
# -*- coding: utf-8 -*-
"""
Wyckoff 多策略合成最终验证 (P3)
=================================
策略: v2+ P3 (Wyckoff+NTZ+bear跳过+三阶段执行)
叠加因子:
  F1: Wyckoff基础 (权重0.30)
  F2: MA/ATR趋势   (权重0.35) 
  F3: Market Regime (权重0.15)
  F4: MTF Alignment (权重0.10)
  F5: LPPL泡沫风险  (权重0.10)
"""

import csv
import json
import random
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
from scripts.utils.tdx_config import CSI300_PATH
from src.data.manager import DataManager
from src.data.tdx_loader import load_tdx_data
from src.parallel import get_optimal_workers, worker_init
from src.wyckoff.engine import WyckoffEngine

N_STOCKS = 99999; N_WINDOWS = 20; MAX_HOLD = 180; SEED = 42; N_BOOT = 2000
CSI300_PATH = CSI300_PATH
OUTPUT_DIR = PROJECT_ROOT / "output" / "wyckoff_multistrat_test"

REGIME_PARAMS = {
    "range": {"atr_mult": 1.5, "ts": 45, "mh": 90},
    "bear":  {"atr_mult": 2.5, "ts": 90, "mh": 180},
    "bull":  {"atr_mult": 3.0, "ts": 60, "mh": 120},
    "unknown": {"atr_mult": 2.0, "ts": 60, "mh": 120},
}

# Score threshold (综合评分 > 0.45 才交易)
SCORE_THRESHOLD = 0.45


# ===== Pure scoring functions (no side effects) =====

def score_wyckoff(phase: str) -> float:
    return {"markdown": 0.8, "accumulation": 0.6, "distribution": 0.3, "markup": 0.3}.get(phase, 0.3)

def score_maatr(df: pd.DataFrame, as_of_date: str) -> float:
    as_of = pd.Timestamp(as_of_date)
    h = df[df["date"] <= as_of].tail(100)
    if len(h) < 60: return 0.5
    c = float(h.iloc[-1]["close"])
    m20 = float(h.tail(20)["close"].mean())
    m60 = float(h.tail(60)["close"].mean())
    tr = 0.5 + 0.5 * ((m20 - m60) / m60)
    hi = float(h.tail(60)["high"].max())
    lo = float(h.tail(60)["low"].min())
    pr = (c - lo) / (hi - lo) if hi > lo else 0.5
    return max(0, min(1, 0.6 * tr + 0.4 * pr))

def score_regime(market_regime: str) -> float:
    return {"bull": 0.8, "range": 0.6, "bear": 0.0, "unknown": 0.3}.get(market_regime, 0.3)

def score_alignment(alignment: str) -> float:
    return {"fully_aligned": 0.8, "weekly_daily_aligned": 0.5, "higher_timeframe_aligned": 0.5, "mixed": 0.3}.get(alignment, 0.3)

def score_lppl(lppl_data: Dict, index: str = "000001.SH") -> float:
    """LPPL: 泡沫越严重分数越低(负向因子)"""
    idx = lppl_data.get(index, {})
    if not idx: return 0.5
    conf = idx.get("confidence", 0)
    rmse = idx.get("rmse", 1)
    if conf > 70 and rmse < 0.1: return 0.1  # 严重泡沫→低分
    return 0.5


def load_lppl_params() -> Dict:
    """加载LPPL参数(纯函数, 无状态缓存)"""
    d = {}
    pd_ = PROJECT_ROOT / "output" / "lppl" / "params"
    if pd_.exists():
        for f in sorted(pd_.glob("lppl_params_*.json")):
            try:
                data = json.load(f.open())
                for e in data.get("parameters", []):
                    idx = e.get("symbol", "")
                    p = e.get("params", [])
                    rmse = e.get("rmse", 1)
                    conf = min(100, max(0, (1.0 / max(rmse, 0.01)) * 10))
                    d[idx] = {"confidence": round(conf), "rmse": rmse, "omega": abs(p[2]) if len(p) > 2 else 0}
            except Exception:
                pass
    return d


def load_stocks(csv_path: Path, limit: int = N_STOCKS) -> List[Dict]:
    symbols = []
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            code = str(row.get("code", "")).strip()
            market = str(row.get("market", "")).strip().upper()
            name = str(row.get("name", "")).replace("\x00", "").strip()
            if not (code.isdigit() and len(code) == 6 and market in {"SH", "SZ"}):
                continue
            if code.startswith(("600","601","603","605","688","689","000","001","002","003","300","301","302")):
                symbols.append({"symbol": f"{code}.{market}", "code": code, "market": market, "name": name})
            if len(symbols) >= limit: break
    return symbols

def load_csi300() -> Optional[pd.DataFrame]:
    if CSI300_PATH.exists():
        df = load_tdx_data(str(CSI300_PATH))
        if df is not None and not df.empty:
            df["date"] = pd.to_datetime(df["date"]); df = df.sort_values("date").reset_index(drop=True)
            return df
    return None

def gen_windows(csi300: pd.DataFrame, n: int = N_WINDOWS) -> List[str]:
    if csi300 is None or len(csi300) < 200: return []
    d = csi300["date"].dt.strftime("%Y-%m-%d").tolist()
    random.seed(SEED)
    return sorted(random.sample(d[:len(d)-MAX_HOLD], min(n, len(d)-MAX_HOLD)))

def get_regime(csi300: pd.DataFrame, d: str) -> str:
    as_of = pd.Timestamp(d)
    h = csi300[csi300["date"] <= as_of]
    if len(h) < 120: return "unknown"
    c = float(h.iloc[-1]["close"])
    m120 = float(h.tail(120)["close"].mean())
    m60 = float(h.tail(60)["close"].mean())
    if c > m120 * 1.02 and m60 > m120: return "bull"
    if c < m120 * 0.98: return "bear"
    return "range"

def calc_atr(s: pd.DataFrame, p: int = 20) -> float:
    n = len(s)
    if n < p + 1: return 0.0
    hi, lo, cl = s["high"].values[-p:], s["low"].values[-p:], s["close"].values
    tr = [hi[i]-lo[i] for i in range(p)]
    tr += [max(hi[i]-lo[i], abs(hi[i]-cl[-(p-i+1)]), abs(lo[i]-cl[-(p-i+1)])) for i in range(min(p, n-1))]
    return float(np.mean(tr[-p:]))


def calc_trade_return(df, as_of_date, entry_p, stop_l, target_p, regime):
    p = REGIME_PARAMS.get(regime, REGIME_PARAMS["unknown"])
    atr_m, ts, mh = p["atr_mult"], p["ts"], p["mh"]
    as_of = pd.Timestamp(as_of_date)
    f = df[df["date"] > as_of].head(mh)
    if len(f) < mh * 0.5: return None
    cc = float(df[df["date"] <= as_of].iloc[-1]["close"])
    use_we = entry_p and entry_p > 0 and abs(entry_p - cc) / cc > 0.001
    entry = entry_p if use_we else cc
    if use_we:
        e = f.head(10)
        if len(e) > 0 and entry < float(e["low"].min()): return None
    hist = df[df["date"] <= as_of].tail(60)
    atr = calc_atr(pd.concat([hist, f.head(20)]), 20) if len(f) >= 20 else entry * 0.02
    if atr <= 0: atr = entry * 0.02
    ss = stop_l if (stop_l and stop_l > 0) else entry * 0.93
    et = target_p if (target_p and target_p > 0) else None
    atr_t = entry + 2.0 * atr
    eff_t = max(et, atr_t) if (et and et > entry) else (atr_t if atr_t > entry else None)
    peak = entry; ts_ = None; half = False; s2 = False; ep = None; er_ = "max_hold"
    hs = False; ht = False
    for i, (_, r) in enumerate(f.iterrows()):
        d_ = i + 1
        c, hi, lo = float(r["close"]), float(r["high"]), float(r["low"])
        peak = max(peak, hi)
        if lo <= ss: ep = ss; er_ = "stop_loss"; hs = True; break
        if d_ <= 30 and not half and eff_t and hi >= eff_t:
            half = True; s1p = eff_t; s2 = True; ts_ = peak - atr_m * atr; ht = True; continue
        if d_ == 30: s2 = True; ts_ = peak - atr_m * atr
        if s2:
            t = peak - atr_m * atr
            ts_ = max(ts_, t) if ts_ else t
            if lo <= ts_: ep = ts_; er_ = "trailing_stop"; break
            if d_ > ts and not half: ep = c; er_ = "time_stop"; break
        ep = c
    if not hs and d_ >= mh: ep = float(f.iloc[-1]["close"]); er_ = "max_hold"
    if half and ht:
        r1 = (s1p - entry) / entry * 100; r2 = (ep - entry) / entry * 100
        tr = 0.5 * r1 + 0.5 * r2; er_ = f"target_50pct+{er_}"
    else:
        tr = (ep - entry) / entry * 100; er_ = er_
    fh = float(f["high"].max()); fl = float(f["low"].min())
    return {"entry": round(entry,3), "ret": round(tr,2), "er": er_,
            "ht": ht, "hs": hs, "half": half, "mg": round((fh-entry)/entry*100,2),
            "md": round((entry-fl)/entry*100,2), "days": d_}


def process_stock(args) -> List[Dict]:
    si, windows, csi300, lppl_data = args
    symbol, name = si["symbol"], si["name"]
    res = []
    try:
        dm = DataManager(); df = dm.get_data(symbol)
        if df is None or df.empty or len(df) < 300: return res
        df["date"] = pd.to_datetime(df["date"]); df = df.sort_values("date").reset_index(drop=True)
        eng = WyckoffEngine(lookback_days=400, weekly_lookback=120, monthly_lookback=40)

        for as_of_date in windows:
            as_of = pd.Timestamp(as_of_date)
            av = df[df["date"] <= as_of]
            if len(av) < 100: continue
            rpt = eng.analyze(av, symbol=symbol, period="日线", multi_timeframe=True)
            rr = rpt.risk_reward
            we_ = rr.entry_price if (rr and rr.entry_price and rr.entry_price > 0) else None
            sl_ = rr.stop_loss if (rr and rr.stop_loss and rr.stop_loss > 0) else None
            ft_ = rr.first_target if (rr and rr.first_target and rr.first_target > 0) else None
            sig = rpt.signal.signal_type; ph = rpt.structure.phase.value
            al_ = rpt.multi_timeframe.alignment if rpt.multi_timeframe else ""
            dr = rpt.trading_plan.direction
            if sig == "no_signal" or dr == "空仓观望": continue

            market_regime = get_regime(csi300, as_of_date) if csi300 is not None else "unknown"
            if market_regime == "bear": continue  # P2 bear跳过

            # === 5因子评分 ===
            s1 = score_wyckoff(ph)
            s2 = score_maatr(df, as_of_date)
            s3 = score_regime(market_regime)
            s4 = score_alignment(al_)
            s5 = score_lppl(lppl_data, "000001.SH")

            # 综合评分 (权重动态调整: bear→regime权重归零)
            w1, w2, w3, w4, w5 = 0.30, 0.35, 0.15, 0.10, 0.10
            score = w1*s1 + w2*s2 + w3*s3 + w4*s4 + w5*s5
            if score < SCORE_THRESHOLD: continue

            tr = calc_trade_return(df, as_of_date, we_, sl_, ft_, market_regime)
            if tr is None: continue

            bm = None
            if csi300 is not None:
                bf = csi300[csi300["date"] > as_of].head(90)
                if len(bf) >= 72:
                    be = float(csi300[csi300["date"] <= as_of].iloc[-1]["close"])
                    bx = float(bf.iloc[-1]["close"])
                    bm = round((bx - be) / be * 100, 2)

            res.append({"symbol": symbol, "name": name, "as_of": as_of_date,
                        "phase": ph, "regime": market_regime, "alignment": al_,
                        "s_wyckoff": round(s1,3), "s_maatr": round(s2,3),
                        "s_regime": round(s3,3), "s_alignment": round(s4,3),
                        "s_lppl": round(s5,3), "score": round(score,3),
                        "ret": tr["ret"], "er": tr["er"], "ht": tr["ht"],
                        "hs": tr["hs"], "days": tr["days"], "mg": tr["mg"],
                        "md": tr["md"], "bm": bm,
                        "excess": round(tr["ret"] - bm, 2) if bm is not None else None})
    except Exception:
        pass
    return res


def bootstrap_ci(data, n=N_BOOT, conf=0.95):
    if len(data) < 10: return np.nan, np.nan, np.nan
    m = [np.mean(np.random.choice(data, size=len(data), replace=True)) for _ in range(n)]
    return np.mean(m), np.percentile(m, (1-conf)/2*100), np.percentile(m, (1+conf)/2*100)


def run():
    print("="*70)
    print("Wyckoff 多策略合成最终验证")
    print("  因子: Wyckoff(30%) MA/ATR(35%) Regime(15%) Alignment(10%) LPPL(10%)")
    print("  + bear跳过 + v2+三阶段执行")
    print("="*70)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    stocks = load_stocks(PROJECT_ROOT/"data"/"stock_list.csv", N_STOCKS)
    print(f"\n股票: {len(stocks)}只")
    csi300 = load_csi300(); print(f"沪深300: {len(csi300) if csi300 is not None else 0}行")
    windows = gen_windows(csi300, N_WINDOWS); print(f"窗口: {len(windows)}个")
    lppl_data = load_lppl_params(); print(f"LPPL: {len(lppl_data)}指数")

    all_res = []
    mw = get_optimal_workers(); bs = mw * 4
    args_list = [(s, windows, csi300, lppl_data) for s in stocks]

    with ProcessPoolExecutor(max_workers=mw, initializer=worker_init) as ex:
        for b in range(0, len(args_list), bs):
            batch = args_list[b:b+bs]
            futures = {ex.submit(process_stock, a): a[0]["symbol"] for a in batch}
            for f in futures:
                try: all_res.extend(f.result(timeout=300))
                except Exception: pass
            print(f"  {min(b+bs, len(args_list))}/{len(stocks)} 股票, {len(all_res)}样本")

    print(f"\n总样本: {len(all_res)}")
    if not all_res: print("无样本"); return
    df = pd.DataFrame(all_res)
    rets = df["ret"].values; mr, cl, ch = bootstrap_ci(rets)
    st = float(np.std(rets)) if len(rets) > 1 else 0
    sp = mr / st * (252/90)**0.5 if st > 0 else 0

    analysis = {"config": {"version": "multistrat_v1", "weights": {"wyckoff":0.30,"maatr":0.35,"regime":0.15,"alignment":0.10,"lppl":0.10}},
                "overall": {"n": len(df), "mean": round(mr,2), "ci_l": round(cl,2), "ci_h": round(ch,2),
                           "median": round(np.median(rets),2), "win": round(sum(rets>0)/len(rets)*100,1),
                           "std": round(st,2), "sharpe": round(sp,3)}}

    for r in df["er"].unique():
        v = df[df["er"]==r]["ret"].values
        if len(v)>=3: analysis.setdefault("exit",{})[r] = {"n":len(v), "m":round(np.mean(v),2), "w":round(sum(v>0)/len(v)*100,1), "pct":round(len(v)/len(df)*100,1)}

    if df["excess"].notna().sum()>=10:
        ex = df["excess"].dropna().values
        analysis["benchmark"] = {"strat":round(np.mean(rets),2), "bm":round(np.mean(df["bm"].dropna()),2),
                                 "excess":round(np.mean(ex),2), "ex_win":round(sum(ex>0)/len(ex)*100,1)}

    jp = OUTPUT_DIR/"multistrat_results.json"
    with jp.open("w", encoding="utf-8") as f: json.dump(analysis, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n结果: {jp}")
    o = analysis["overall"]
    print(f"\n{'='*70}")
    print(f"多策略合成测试摘要: 样本={o['n']} 收益={o['mean']}% 中位={o['median']}%")
    print(f"  胜率={o['win']}% 标准差={o['std']}% 夏普={o['sharpe']}")
    bc = analysis.get("benchmark",{})
    if bc: print(f"  策略={bc['strat']}% vs 基准={bc['bm']}% 超额={bc['excess']}% 超额胜率={bc['ex_win']}%")
    print("\n  退出原因:")
    for r,s in sorted(analysis.get("exit",{}).items(), key=lambda x: -x[1]["pct"]):
        print(f"    {r:35s}: {s['pct']:5.1f}%  ret={s['m']:6.2f}%  win={s['w']:5.1f}%")
    print(f"\n{'='*70}")
    print("完成")
    print(f"{'='*70}")

if __name__ == "__main__":
    run()
