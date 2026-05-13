#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
多策略组合验证 (Multi-Strategy Portfolio)
=========================================
策略1: Wyckoff (v2+P3, 90-180天持有)       Sharpe≈0.33
策略2: RSI均值回归 (5天RSI, 10天持有)      理论Sharpe≈0.15-0.20
策略3: MA双均线交叉 (5日/20日, 趋势跟踪)   理论Sharpe≈0.15-0.20

验证目标: 三策略低相关性 → 组合Sharpe > 单策略
设计校验:
  - 各策略使用独立信号源 → 降低相关性
  - 不同时间尺度 → 降低同步性
  - 等权组合 → 分散风险
"""

import csv, json, random, sys, math
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

N_STOCKS = 1000; N_WINDOWS = 20; SEED = 42; N_BOOT = 2000
CSI300_PATH = Path("/home/james/.local/share/tdxcfv/drive_c/tc/vipdoc/sh/lday/sh000300.day")
OUTPUT_DIR = PROJECT_ROOT / "output" / "multistrat_portfolio"

# === 策略1: Wyckoff 参数 ===
REGIME_PARAMS = {
    "range": {"atr_mult": 1.5, "ts": 45, "mh": 90},
    "bear":  {"atr_mult": 2.5, "ts": 90, "mh": 180},
    "bull":  {"atr_mult": 3.0, "ts": 60, "mh": 120},
    "unknown": {"atr_mult": 2.0, "ts": 60, "mh": 120},
}

# === 策略2: RSI均值回归 参数 ===
RSI_PERIOD = 5
RSI_OVERSOLD = 25
RSI_OVERBOUGHT = 75
MR_HOLD_DAYS = 10

# === 策略3: MA Crossover 参数 ===
MA_FAST = 5
MA_SLOW = 20


def load_stocks(csv_path: Path, limit: int = N_STOCKS) -> List[Dict]:
    symbols = []
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            code = str(row.get("code","")).strip()
            market = str(row.get("market","")).strip().upper()
            name = str(row.get("name","")).replace("\x00","").strip()
            if not (code.isdigit() and len(code)==6 and market in {"SH","SZ"}): continue
            if code.startswith(("600","601","603","605","688","689","000","001","002","003","300","301","302")):
                symbols.append({"symbol":f"{code}.{market}","code":code,"market":market,"name":name})
                if len(symbols) >= limit: break
    return symbols

def load_csi300() -> Optional[pd.DataFrame]:
    if CSI300_PATH.exists():
        df = load_tdx_data(str(CSI300_PATH))
        if df is not None and not df.empty:
            df["date"]=pd.to_datetime(df["date"]); df=df.sort_values("date").reset_index(drop=True); return df
    return None

def gen_windows(csi300: pd.DataFrame, n: int = N_WINDOWS) -> List[str]:
    if csi300 is None or len(csi300) < 200: return []
    d = csi300["date"].dt.strftime("%Y-%m-%d").tolist()
    random.seed(SEED)
    return sorted(random.sample(d[:len(d)-200], min(n, len(d)-200)))

def get_regime(csi300: pd.DataFrame, d: str) -> str:
    as_of = pd.Timestamp(d); h = csi300[csi300["date"] <= as_of]
    if len(h) < 120: return "unknown"
    c = float(h.iloc[-1]["close"]); m120 = float(h.tail(120)["close"].mean()); m60 = float(h.tail(60)["close"].mean())
    if c > m120*1.02 and m60 > m120: return "bull"
    if c < m120*0.98: return "bear"
    return "range"

def calc_atr(s: pd.DataFrame, p: int = 20) -> float:
    if len(s) < p+1: return 0.0
    hi, lo = s["high"].values[-p:], s["low"].values[-p:]
    tr = [hi[i]-lo[i] for i in range(p)]
    return float(np.mean(tr))

def calc_returns(future_df: pd.DataFrame, entry_price: float) -> Dict:
    """通用收益计算"""
    if future_df is None or len(future_df) < 5: return None
    exit_price = float(future_df.iloc[-1]["close"])
    ret = (exit_price - entry_price) / entry_price * 100
    fh = float(future_df["high"].max()); fl = float(future_df["low"].min())
    return {"ret": round(ret,2), "mg": round((fh-entry_price)/entry_price*100,2),
            "md": round((entry_price-fl)/entry_price*100,2), "days": len(future_df)}


# ===== 策略1: Wyckoff =====
def strat_wyckoff(df, as_of_date, csi300):
    as_of = pd.Timestamp(as_of_date)
    av = df[df["date"] <= as_of]
    if len(av) < 100: return None
    eng = WyckoffEngine(lookback_days=400, weekly_lookback=120, monthly_lookback=40)
    rpt = eng.analyze(av, symbol="", period="日线", multi_timeframe=True)
    rr = rpt.risk_reward
    we = rr.entry_price if (rr and rr.entry_price and rr.entry_price>0) else None
    sl = rr.stop_loss if (rr and rr.stop_loss and rr.stop_loss>0) else None
    ft = rr.first_target if (rr and rr.first_target and rr.first_target>0) else None
    sig = rpt.signal.signal_type; dr = rpt.trading_plan.direction
    if sig == "no_signal" or dr == "空仓观望": return None
    regime = get_regime(csi300, as_of_date) if csi300 is not None else "unknown"
    if regime == "bear": return None
    p = REGIME_PARAMS.get(regime, REGIME_PARAMS["unknown"])
    atr_m, ts_d, mh = p["atr_mult"], p["ts"], p["mh"]
    f = df[df["date"] > as_of].head(mh)
    if len(f) < mh * 0.5: return None
    cc = float(av.iloc[-1]["close"])
    use_we = we and we > 0 and abs(we-cc)/cc > 0.001
    entry = we if use_we else cc
    if use_we and len(f.head(10))>0 and we < float(f.head(10)["low"].min()): return None
    hist = av.tail(60)
    atr = calc_atr(pd.concat([hist, f.head(20)]), 20) if len(f)>=20 else entry*0.02
    if atr <= 0: atr = entry*0.02
    ss = sl if (sl and sl>0) else entry*0.93
    et = ft if (ft and ft>0) else None
    atr_t = entry + 2.0*atr
    eff_t = max(et, atr_t) if (et and et>entry) else (atr_t if atr_t>entry else None)
    peak = entry; ts_p = None; half = False; s2 = False; ep = None; er = "max_hold"
    hs = False; ht = False
    for i, (_, rw) in enumerate(f.iterrows()):
        d_ = i+1; c, hi, lo = float(rw["close"]), float(rw["high"]), float(rw["low"])
        peak = max(peak, hi)
        if lo <= ss: ep = ss; er = "stop_loss"; hs = True; break
        if d_ <= 30 and not half and eff_t and hi >= eff_t:
            half = True; s1p = eff_t; s2 = True; ts_p = peak - atr_m*atr; ht = True; continue
        if d_ == 30: s2 = True; ts_p = peak - atr_m*atr
        if s2:
            t = peak - atr_m*atr; ts_p = max(ts_p, t) if ts_p else t
            if lo <= ts_p: ep = ts_p; er = "trailing_stop"; break
            if d_ > ts_d and not half: ep = c; er = "time_stop"; break
        ep = c
    if not hs and d_ >= mh: ep = float(f.iloc[-1]["close"]); er = "max_hold"
    if half and ht:
        r1 = (s1p-entry)/entry*100; r2 = (ep-entry)/entry*100
        tr = round(0.5*r1 + 0.5*r2, 2); er = f"target_50pct+{er}"
    else:
        tr = round((ep-entry)/entry*100, 2)
    return {"ret": tr, "exit": er, "days": d_, "type": "wyckoff"}


# ===== 策略2: RSI均值回归 =====
def strat_rsi(df, as_of_date):
    as_of = pd.Timestamp(as_of_date)
    h = df[df["date"] <= as_of].tail(RSI_PERIOD + 10)
    if len(h) < RSI_PERIOD + 5: return None
    closes = h["close"].values.astype(float)
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i-1]
        gains.append(max(d, 0)); losses.append(max(-d, 0))
    avg_gain = np.mean(gains[-RSI_PERIOD:]) if len(gains) >= RSI_PERIOD else np.mean(gains)
    avg_loss = np.mean(losses[-RSI_PERIOD:]) if len(losses) >= RSI_PERIOD else np.mean(losses)
    if avg_loss == 0: return None
    rs = avg_gain / avg_loss; rsi = 100 - 100/(1+rs)
    if rsi > RSI_OVERBOUGHT:
        # 超买: 做空(在A股只能做空相关etf, 这里仅做卖出标记)
        return None  # A股做空受限
    if rsi < RSI_OVERSOLD:
        # 超卖: 做多
        entry = float(h.iloc[-1]["close"])
        f = df[df["date"] > as_of].head(MR_HOLD_DAYS)
        if len(f) < MR_HOLD_DAYS * 0.6: return None
        ret = calc_returns(f, entry)
        if ret is None: return None
        return {"ret": ret["ret"], "exit": "rsi_oversold", "days": ret["days"], "type": "rsi"}
    return None


# ===== 策略3: MA双均线交叉 =====
def strat_ma(df, as_of_date):
    as_of = pd.Timestamp(as_of_date)
    h = df[df["date"] <= as_of].tail(MA_SLOW + 5)
    if len(h) < MA_SLOW + 2: return None
    if len(h) < 2: return None
    ma_fast = float(h.tail(MA_FAST)["close"].mean())
    ma_slow = float(h.tail(MA_SLOW)["close"].mean())
    # 前一天的MA
    prev_h = df[df["date"] <= as_of].tail(MA_SLOW + 6).head(MA_SLOW + 5)
    if len(prev_h) < MA_SLOW + 2: return None
    prev_fast = float(prev_h.tail(MA_FAST)["close"].mean())
    prev_slow = float(prev_h.tail(MA_SLOW)["close"].mean())
    # 金叉: fast上穿slow
    if prev_fast <= prev_slow and ma_fast > ma_slow:
        entry = float(h.iloc[-1]["close"])
        # 持有到死叉或120天
        future_h = df[df["date"] > as_of]
        exit_idx = None
        for i in range(1, min(120, len(future_h))):
            sub = future_h.head(i + MA_SLOW)
            if len(sub) < MA_SLOW + 2: continue
            sf = float(sub.tail(MA_FAST)["close"].mean())
            ss = float(sub.tail(MA_SLOW)["close"].mean())
            if sf < ss:
                exit_idx = i
                break
        if exit_idx:
            f = future_h.head(exit_idx + 1)
        else:
            f = future_h.head(120)
        if len(f) < 5: return None
        ret = calc_returns(f, entry)
        if ret is None: return None
        return {"ret": ret["ret"], "exit": "ma_cross", "days": ret["days"], "type": "ma"}
    return None


def process_stock(args) -> Dict:
    """运行一个股票的所有策略"""
    si, windows, csi300 = args
    symbol, name = si["symbol"], si["name"]
    res = {"symbol": symbol, "name": name, "trades": []}
    try:
        dm = DataManager(); df = dm.get_data(symbol)
        if df is None or df.empty or len(df) < 300: return res
        df["date"] = pd.to_datetime(df["date"]); df = df.sort_values("date").reset_index(drop=True)
        for w in windows:
            # 策略1: Wyckoff
            w1 = strat_wyckoff(df, w, csi300)
            if w1: res["trades"].append({"window": w, "symbol": symbol, **w1})
            w2 = strat_rsi(df, w)
            if w2: res["trades"].append({"window": w, "symbol": symbol, **w2})
            w3 = strat_ma(df, w)
            if w3: res["trades"].append({"window": w, "symbol": symbol, **w3})
    except Exception:
        pass
    return res


def run():
    print("=" * 70)
    print("多策略组合验证 (Multi-Strategy Portfolio)")
    print("  S1: Wyckoff (v2+P3, 90-180d)  S2: RSI均值回归(10d)  S3: MA双均线(趋势)")
    print("=" * 70)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    stocks = load_stocks(PROJECT_ROOT/"data"/"stock_list.csv", N_STOCKS)
    print(f"\n股票: {len(stocks)}只 (1000只验证)")
    csi300 = load_csi300(); print(f"沪深300: {len(csi300) if csi300 is not None else 0}行")
    windows = gen_windows(csi300, N_WINDOWS); print(f"窗口: {len(windows)}个")
    mw = get_optimal_workers(); bs = mw * 4
    args_list = [(s, windows, csi300) for s in stocks]
    all_trades = []
    with ProcessPoolExecutor(max_workers=mw, initializer=worker_init) as ex:
        for b in range(0, len(args_list), bs):
            batch = args_list[b:b+bs]
            futures = {ex.submit(process_stock, a): a[0]["symbol"] for a in batch}
            for f in as_completed(futures):
                try:
                    r = f.result(timeout=300)
                    all_trades.extend(r["trades"])
                except: pass
            print(f"  {min(b+bs, len(args_list))}/{len(stocks)} 股票")
    if not all_trades:
        print("无交易样本"); return
    df = pd.DataFrame(all_trades)
    print(f"\n总交易: {len(df)}笔")
    print(f"  其中 Wyckoff: {sum(df['type']=='wyckoff')}笔")
    print(f"  其中 RSI:     {sum(df['type']=='rsi')}笔")
    print(f"  其中 MA:      {sum(df['type']=='ma')}笔")
    # 按策略分组
    results = {}
    for strat_type in ["wyckoff", "rsi", "ma"]:
        sub = df[df["type"] == strat_type]
        if len(sub) < 5: continue
        rets = sub["ret"].values; mr = np.mean(rets); st = np.std(rets) if len(rets) > 1 else 1
        sharpe = mr / st * math.sqrt(252/max(np.mean(sub["days"]), 1)) if st > 0 else 0
        results[strat_type] = {"n": len(sub), "ret": round(mr,2), "std": round(st,2),
                               "sharpe": round(sharpe,3), "win": round(sum(rets>0)/len(rets)*100,1),
                               "avg_days": round(np.mean(sub["days"]),1)}
    # 相关性矩阵
    print(f"\n{'='*70}")
    print("单策略表现:")
    print(f"{'策略':<12} {'样本':>6} {'收益':>8} {'标准差':>8} {'夏普':>8} {'胜率':>6} {'平均持有':>8}")
    print("-" * 60)
    for s in ["wyckoff", "rsi", "ma"]:
        r = results.get(s)
        if r: print(f"  {s:<10} {r['n']:>6} {r['ret']:>7.2f}% {r['std']:>7.2f}% {r['sharpe']:>7.3f} {r['win']:>5.1f}% {r['avg_days']:>7.1f}d")
    # 相关性
    print(f"\n策略相关性矩阵:")
    types = [t for t in ["wyckoff", "rsi", "ma"] if t in results]
    if len(types) >= 2:
        corr_matrix = {}
        for t1 in types:
            for t2 in types:
                if t1 < t2:
                    # 按 window+symbol 对齐
                    d1 = df[df["type"]==t1][["window","symbol","ret"]].drop_duplicates(subset=["window","symbol"])
                    d2 = df[df["type"]==t2][["window","symbol","ret"]].drop_duplicates(subset=["window","symbol"])
                    merged = d1.merge(d2, on=["window","symbol"], suffixes=(f"_{t1}", f"_{t2}"))
                    if len(merged) >= 5:
                        c = np.corrcoef(merged[f"ret_{t1}"], merged[f"ret_{t2}"])[0,1]
                        corr_matrix[f"{t1}_{t2}"] = round(c, 3)
                        print(f"  {t1} vs {t2}: {c:.3f} (共同样本: {len(merged)})")
                    else:
                        print(f"  {t1} vs {t2}: 样本不足({len(merged)})")
        # 组合夏普 (等权, 假设分散投资)
        if len(types) >= 2:
            n_types = len(types)
            avg_sharpe = sum(results[t]["sharpe"] for t in types) / n_types
            avg_corr = np.mean(list(corr_matrix.values())) if corr_matrix else 0.5
            portfolio_sharpe = avg_sharpe * math.sqrt(n_types / (1 + (n_types-1) * max(avg_corr, 0.01)))
            print(f"\n  平均夏普: {avg_sharpe:.3f}")
            print(f"  平均相关: {avg_corr:.3f}")
            print(f"  组合夏普({n_types}策略等权): {portfolio_sharpe:.3f}")
    # 保存
    jp = OUTPUT_DIR / "portfolio_results.json"
    analysis = {
        "config": {"n_stocks": N_STOCKS, "n_windows": N_WINDOWS},
        "strategies": results, "correlations": corr_matrix if 'corr_matrix' in dir() else {}}
    with jp.open("w", encoding="utf-8") as f:
        json.dump(analysis, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n结果: {jp}")
    print(f"\n{'='*70}")
    print("完成")
    print(f"{'='*70}")

if __name__ == "__main__":
    run()
