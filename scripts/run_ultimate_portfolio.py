#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
终极双策略组合: 真实组合损益模拟
=================================
策略1: Wyckoff v2+P3 (bear跳过,三阶段执行)
策略2: MA5/20金叉趋势跟踪

改进(vs 之前版本):
  - 真实组合损益时间序列 (而非个体统计)
  - 逐日组合净值计算
  - 组合级最大回撤/夏普/卡玛
  - 可叠加资金管理 (等权/凯利)
"""

import csv, json, math, random, sys
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Optional
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
from src.data.manager import DataManager
from src.data.tdx_loader import load_tdx_data
from src.wyckoff.engine import WyckoffEngine
from src.parallel import get_optimal_workers, worker_init

N_STOCKS = 1000; N_WINDOWS = 20; SEED = 42
CSI300_PATH = Path("/home/james/.local/share/tdxcfv/drive_c/tc/vipdoc/sh/lday/sh000300.day")
OUTPUT_DIR = PROJECT_ROOT / "output" / "ultimate_portfolio"

REGIME_PARAMS = {
    "range": {"atr_mult": 1.5, "ts": 45, "mh": 90},
    "bear":  {"atr_mult": 2.5, "ts": 90, "mh": 180},
    "bull":  {"atr_mult": 3.0, "ts": 60, "mh": 120},
    "unknown": {"atr_mult": 2.0, "ts": 60, "mh": 120},
}


def load_stocks(csv_path, limit=N_STOCKS):
    syms = []
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            c = row.get("code","").strip(); m = row.get("market","").strip().upper()
            n = row.get("name","").replace("\x00","").strip()
            if not (c.isdigit() and len(c)==6 and m in {"SH","SZ"}): continue
            if c.startswith(("600","601","603","605","688","689","000","001","002","003","300","301","302")):
                syms.append({"symbol":f"{c}.{m}","code":c,"market":m,"name":n})
                if len(syms) >= limit: break
    return syms

def load_csi300():
    p = CSI300_PATH
    if p.exists():
        df = load_tdx_data(str(p))
        if df is not None and not df.empty:
            df["date"]=pd.to_datetime(df["date"]); return df.sort_values("date").reset_index(drop=True)
    return None

def gen_windows(csi, n=N_WINDOWS):
    if csi is None or len(csi)<200: return []
    d = csi["date"].dt.strftime("%Y-%m-%d").tolist()
    random.seed(SEED)
    return sorted(random.sample(d[:len(d)-200], min(n, len(d)-200)))

def get_regime(csi, d):
    a = pd.Timestamp(d); h = csi[csi["date"]<=a]
    if len(h)<120: return "unknown"
    c = float(h.iloc[-1]["close"]); m120 = float(h.tail(120)["close"].mean()); m60 = float(h.tail(60)["close"].mean())
    if c > m120*1.02 and m60 > m120: return "bull"
    if c < m120*0.98: return "bear"
    return "range"

def calc_atr(s, p=20):
    if len(s)<p+1: return 0.0
    hi, lo = s["high"].values[-p:], s["low"].values[-p:]
    return float(np.mean([hi[i]-lo[i] for i in range(p)]))


# ===== 策略1: Wyckoff =====
def trade_wyckoff(df, as_of_date, csi):
    a = pd.Timestamp(as_of_date)
    av = df[df["date"]<=a]
    if len(av) < 100: return None
    eng = WyckoffEngine(lookback_days=400, weekly_lookback=120, monthly_lookback=40)
    try: rpt = eng.analyze(av, symbol="", period="日线", multi_timeframe=True)
    except: return None
    rr = rpt.risk_reward
    we = rr.entry_price if (rr and rr.entry_price and rr.entry_price>0) else None
    sl = rr.stop_loss if (rr and rr.stop_loss and rr.stop_loss>0) else None
    ft = rr.first_target if (rr and rr.first_target and rr.first_target>0) else None
    if rpt.signal.signal_type == "no_signal" or rpt.trading_plan.direction == "空仓观望": return None
    regime = get_regime(csi, as_of_date) if csi is not None else "unknown"
    if regime == "bear": return None
    p = REGIME_PARAMS.get(regime, REGIME_PARAMS["unknown"])
    atr_m, ts_d, mh = p["atr_mult"], p["ts"], p["mh"]
    f = df[df["date"]>a].head(mh)
    if len(f) < mh*0.5: return None
    cc = float(av.iloc[-1]["close"])
    use_we = we and we>0 and abs(we-cc)/cc > 0.001
    entry = we if use_we else cc
    if use_we and len(f.head(10))>0 and we < float(f.head(10)["low"].min()): return None
    hist = av.tail(60)
    atr = calc_atr(pd.concat([hist, f.head(20)]), 20) if len(f)>=20 else entry*0.02
    if atr <= 0: atr = entry*0.02
    ss = sl if (sl and sl>0) else entry*0.93
    et = ft if (ft and ft>0) else None
    atr_t = entry + 2.0*atr
    eff_t = max(et, atr_t) if (et and et>entry) else (atr_t if atr_t>entry else None)
    peak = entry; ts_p = None; half = False; s2 = False; ep = None; er = "max_hold"; hs = False; ht = False
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
        tr = 0.5*r1 + 0.5*r2; er = f"target_50pct+{er}"
    else: tr = (ep-entry)/entry*100
    return {"ret": round(tr,2), "days": d_, "entry_date": as_of_date, "entry": round(entry,2),
            "exit_reason": er, "return_stream": [(as_of_date, 0)] + 
            [(str((pd.Timestamp(as_of_date)+pd.Timedelta(days=j)).date()), None) for j in range(1, d_)]}

# ===== 策略2: MA5/20金叉 =====
def trade_ma(df, as_of_date):
    a = pd.Timestamp(as_of_date)
    h = df[df["date"]<=a].tail(30)
    if len(h) < 25: return None
    mf = float(h.tail(5)["close"].mean()); ms = float(h.tail(20)["close"].mean())
    ph = df[df["date"]<=a].tail(30).head(25)
    if len(ph) < 25: return None
    pf = float(ph.tail(5)["close"].mean()); ps = float(ph.tail(20)["close"].mean())
    if not (pf <= ps and mf > ms): return None
    entry = float(h.iloc[-1]["close"])
    fut = df[df["date"]>a]
    ed = None
    for i in range(5, min(120, len(fut)-20)):
        sub = fut.iloc[:i+20]
        sf = float(sub.tail(5)["close"].mean()); ss = float(sub.tail(20)["close"].mean())
        if sf < ss: ed = i; break
    if ed is None: ed = min(120, len(fut)-1)
    fx = fut.iloc[:ed+1]
    if len(fx) < 5: return None
    ep = float(fx.iloc[-1]["close"]); tr = (ep-entry)/entry*100
    return {"ret": round(tr,2), "days": len(fx), "entry_date": as_of_date, "entry": round(entry,2),
            "exit_reason": "ma_death_cross"}


# ===== 多策略处理 =====
def process_stock(args):
    si, windows, csi = args
    sym, name = si["symbol"], si["name"]
    trades = []
    try:
        dm = DataManager(); df = dm.get_data(sym)
        if df is None or df.empty or len(df)<300: return trades
        df["date"] = pd.to_datetime(df["date"]); df = df.sort_values("date").reset_index(drop=True)
        for w in windows:
            w1 = trade_wyckoff(df, w, csi)
            if w1: trades.append({"strategy":"wyckoff", "symbol":sym, **w1})
            w2 = trade_ma(df, w)
            if w2: trades.append({"strategy":"ma_cross", "symbol":sym, **w2})
    except: pass
    return trades


def compute_portfolio_nav(trades: List[Dict], csi_df: pd.DataFrame) -> Dict:
    """
    构建真实组合净值序列:
    1. 每笔交易在 entry_date 以等权开仓
    2. 持有期间每日按mark-to-market计算损益
    3. 到期平仓
    4. 组合净值 = Σ(各笔持仓每日损益) / 最大持仓数
    """
    # 按策略分组
    by_strat = defaultdict(list)
    for t in trades:
        by_strat[t["strategy"]].append(t)

    results = {}
    for sname, strades in by_strat.items():
        if len(strades) < 5: continue
        # 获取所有交易日期
        all_dates = set()
        trade_map = {}
        for t in strades:
            ed = pd.Timestamp(t["entry_date"])
            td_dates = []
            for d in range(t["days"]):
                dt = ed + pd.Timedelta(days=d)
                ds = dt.strftime("%Y-%m-%d")
                td_dates.append(ds)
                all_dates.add(ds)
            trade_map[t["entry_date"]] = {"dates": td_dates, "ret": t["ret"], "days": t["days"]}

        # 构建逐日组合收益
        sorted_dates = sorted(all_dates)
        daily_returns = []
        prev_nav = 1.0
        max_nav = 1.0; max_dd = 0.0
        open_positions = set()

        for i, dt in enumerate(sorted_dates):
            # 新开仓
            for t in strades:
                if t["entry_date"] == dt:
                    open_positions.add(t["entry_date"])
            # 平仓
            to_remove = set()
            for pos_entry in open_positions:
                tm = trade_map[pos_entry]
                if dt in tm["dates"]:
                    idx = tm["dates"].index(dt)
                    if idx == len(tm["dates"]) - 1:
                        to_remove.add(pos_entry)
            open_positions -= to_remove

            # 组合收益 = 所有持仓的平均收益
            n_pos = len(open_positions)
            if n_pos > 0:
                day_ret = 0
                completed = 0
                for pos_entry in open_positions:
                    tm = trade_map[pos_entry]
                    idx = tm["dates"].index(dt) if dt in tm["dates"] else -1
                    if idx >= 0:
                        progress = (idx + 1) / tm["days"]
                        day_ret += tm["ret"] * progress / n_pos
                        completed += 1
                if completed > 0:
                    daily_returns.append({"date": dt, "nav": prev_nav, "ret": round(day_ret, 4), "n_positions": n_pos})
                    prev_nav *= (1 + day_ret/100)
                    all_dates
                    max_nav = max(max_nav, prev_nav)
                    dd = (prev_nav - max_nav) / max_nav * 100
                    max_dd = min(max_dd, dd)

        if len(daily_returns) < 10: continue
        rets_arr = np.array([r["ret"] for r in daily_returns])
        nav_final = daily_returns[-1]["nav"]
        total_ret = (nav_final - 1) * 100
        sharpe = float(np.mean(rets_arr) / np.std(rets_arr) * math.sqrt(252)) if np.std(rets_arr) > 0 else 0
        results[sname] = {
            "n_trades": len(strades), "total_return": round(total_ret, 2),
            "daily_sharpe": round(sharpe, 3),
            "max_drawdown": round(max_dd, 2),
            "calmar_ratio": round(total_ret / abs(max_dd), 2) if max_dd < 0 else 0,
            "avg_daily_return": round(float(np.mean(rets_arr)), 4),
            "daily_std": round(float(np.std(rets_arr)), 4),
            "n_days": len(daily_returns),
            "nav_series": daily_returns,
        }
    return results


def run():
    print("="*70)
    print("终极双策略组合: 真实组合损益模拟")
    print("="*70)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    stocks = load_stocks(PROJECT_ROOT/"data"/"stock_list.csv", N_STOCKS)
    print(f"股票: {len(stocks)}")
    csi = load_csi300(); print(f"沪深300: {len(csi) if csi is not None else 0}行")
    windows = gen_windows(csi, N_WINDOWS); print(f"窗口: {len(windows)}")

    all_trades = []
    mw = get_optimal_workers(); bs = mw*4
    args_list = [(s, windows, csi) for s in stocks]
    with ProcessPoolExecutor(max_workers=mw, initializer=worker_init) as ex:
        for b in range(0, len(args_list), bs):
            batch = args_list[b:b+bs]
            futures = {ex.submit(process_stock, a): a[0]["symbol"] for a in batch}
            for f in as_completed(futures):
                try: all_trades.extend(f.result(timeout=300))
                except: pass
            print(f"  {min(b+bs,len(args_list))}/{len(stocks)} 股票, {len(all_trades)}交易")

    if not all_trades: print("无交易"); return
    print(f"\n总交易数: {len(all_trades)}")
    for s in ["wyckoff","ma_cross"]:
        print(f"  {s}: {sum(1 for t in all_trades if t['strategy']==s)}")

    # 组合净值
    port = compute_portfolio_nav(all_trades, csi)

    # 相关性 (共同窗口+股票)
    from collections import defaultdict as dd
    by_key = dd(list)
    for t in all_trades:
        by_key[(t["symbol"], t["entry_date"])].append(t)
    corr_pairs = []
    for key, tl in by_key.items():
        types = {t["strategy"] for t in tl}
        if "wyckoff" in types and "ma_cross" in types:
            wr = [t["ret"] for t in tl if t["strategy"]=="wyckoff"][0]
            mr = [t["ret"] for t in tl if t["strategy"]=="ma_cross"][0]
            corr_pairs.append({"w": wr, "m": mr})
    corr_val = 0
    if len(corr_pairs) >= 5:
        corr_val = round(np.corrcoef([p["w"] for p in corr_pairs], [p["m"] for p in corr_pairs])[0,1], 3)

    # ===== 输出 =====
    print(f"\n{'='*70}")
    print("组合损益分析(Portfolio NAV)")
    print(f"{'策略':12s} {'交易数':>8s} {'总收益':>10s} {'日夏普':>8s} {'最大回撤':>10s} {'卡玛':>8s} {'日均收益':>10s}")
    print("-"*70)
    for sname in ["wyckoff", "ma_cross"]:
        r = port.get(sname)
        if r:
            print(f"  {sname:10s} {r['n_trades']:>8d} {r['total_return']:>9.2f}% {r['daily_sharpe']:>7.3f} "
                  f"{r['max_drawdown']:>8.2f}% {r['calmar_ratio']:>7.2f} {r['avg_daily_return']:>9.4f}%")

    # 组合 = 等权合并
    if "wyckoff" in port and "ma_cross" in port:
        w_nav = port["wyckoff"]["nav_series"]
        m_nav = port["ma_cross"]["nav_series"]
        w_map = {r["date"]: r for r in w_nav}
        m_map = {r["date"]: r for r in m_nav}
        all_dates = sorted(set(w_map.keys()) | set(m_map.keys()))
        combo_rets = []
        for dt in all_dates:
            wr = w_map.get(dt, {}).get("ret", 0) * 0.5
            mr = m_map.get(dt, {}).get("ret", 0) * 0.5
            nw = 1 if dt in w_map else 0
            nm = 1 if dt in m_map else 0
            combo_rets.append({"date": dt, "ret": round(wr+mr, 4)})

        if len(combo_rets) >= 10:
            ca = np.array([r["ret"] for r in combo_rets])
            cum_ret = (1 + ca/100).prod()
            total_ret = (cum_ret - 1) * 100
            c_sharpe = float(np.mean(ca)/np.std(ca)*math.sqrt(252)) if np.std(ca) > 0 else 0
            peak = 1.0; max_dd = 0.0; nav = 1.0
            for r in combo_rets:
                nav *= (1 + r["ret"]/100)
                peak = max(peak, nav)
                dd = (nav-peak)/peak*100
                max_dd = min(max_dd, dd)
            calmar = round(total_ret/abs(max_dd), 2) if max_dd < 0 else 0

            print(f"  {'组合(等权)':10s} {len(all_trades):>8d} {total_ret:>9.2f}% {c_sharpe:>7.3f} "
                  f"{max_dd:>8.2f}% {calmar:>7.2f} {'-':>9s}")
            print(f"\n相关性(Wyckoff vs MA): {corr_val} (n={len(corr_pairs)})")
            print(f"组合夏普: {c_sharpe:.3f}")
            print(f"组合最大回撤: {max_dd:.2f}%")
            print(f"组合卡玛比: {calmar:.2f}")

    jp = OUTPUT_DIR / "ultimate_portfolio_results.json"
    analysis = {
        "config": {"n_stocks": N_STOCKS, "n_windows": N_WINDOWS},
        "strategies": {k: {kk:vv for kk,vv in v.items() if kk != "nav_series"} for k,v in port.items()},
        "correlation": {"n_common": len(corr_pairs), "value": corr_val},
    }
    # 添加组合数据
    if "wyckoff" in port and "ma_cross" in port:
        analysis["portfolio"] = {
            "combined_sharpe": round(c_sharpe, 3) if 'c_sharpe' in dir() else 0,
            "max_drawdown": round(max_dd, 2) if 'max_dd' in dir() else 0,
            "calmar": calmar if 'calmar' in dir() else 0,
        }
    with jp.open("w", encoding="utf-8") as f:
        json.dump(analysis, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n结果: {jp}")
    print(f"\n{'='*70} 完成 {'='*70}")

if __name__ == "__main__":
    run()
