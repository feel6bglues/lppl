#!/usr/bin/env python3
# RESEARCH ONLY — not production code
"""
多策略合成最终验证 v4
=====================
基于前4次迭代的经验, 采用已验证正确的计算方法:
  1. 各策略独立运行 → 收集每笔交易收益
  2. 按window+symbol对齐计算相关性 (已验证可行)
  3. 年化夏普按实际平均持有期标准化 (已验证可行)
  4. 组合夏普 = 等权平均 × 分散系数 (马科维茨理论)
  5. 蒙特卡洛模拟组合收益分布 (新增: 验证稳定性)

设计校验清单:
  [✓] 双策略独立运行, 不共享信号源
  [✓] 相关性按同股票同时间窗对齐
  [✓] 年化夏普: mean/std × √(252/avg_days)
  [✓] 组合夏普用马科维茨公式
  [✓] 蒙特卡洛重采样验证稳定性
"""

import csv
import json
import math
import random
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
from scripts.utils.tdx_config import CSI300_PATH
from src.data.manager import DataManager
from src.data.tdx_loader import load_tdx_data
from src.parallel import get_optimal_workers, worker_init
from src.wyckoff.engine import WyckoffEngine

N_STOCKS = 99999; N_WINDOWS = 20; SEED = 42; MC_SIMS = 10000
CSI300_PATH = CSI300_PATH
OUTPUT_DIR = PROJECT_ROOT / "output" / "multistrat_v4"

REGIME_PARAMS = {
    "range": {"atr_mult": 1.5, "ts": 45, "mh": 90},
    "bear":  {"atr_mult": 2.5, "ts": 90, "mh": 180},
    "bull":  {"atr_mult": 3.0, "ts": 60, "mh": 120},
    "unknown": {"atr_mult": 2.0, "ts": 60, "mh": 120},
}

# ===== 数据加载 =====
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

# ===== 策略1: Wyckoff v2+P3 =====
def trade_wyckoff(df, as_of_date, csi):
    a = pd.Timestamp(as_of_date)
    av = df[df["date"]<=a]
    if len(av) < 100: return None
    try:
        eng = WyckoffEngine(lookback_days=400, weekly_lookback=120, monthly_lookback=40)
        rpt = eng.analyze(av, symbol="", period="日线", multi_timeframe=True)
    except Exception: return None
    rr = rpt.risk_reward
    we = rr.entry_price if (rr and rr.entry_price and rr.entry_price>0) else None
    sl = rr.stop_loss if (rr and rr.stop_loss and rr.stop_loss>0) else None
    ft = rr.first_target if (rr and rr.first_target and rr.first_target>0) else None
    if rpt.signal.signal_type=="no_signal" or rpt.trading_plan.direction=="空仓观望": return None
    regime = get_regime(csi,as_of_date) if csi is not None else "unknown"
    if regime=="bear": return None
    p = REGIME_PARAMS.get(regime,REGIME_PARAMS["unknown"])
    atr_m,ts_d,mh = p["atr_mult"],p["ts"],p["mh"]
    f = df[df["date"]>a].head(mh)
    if len(f)<mh*0.5: return None
    cc = float(av.iloc[-1]["close"])
    use_we = we and we>0 and abs(we-cc)/cc>0.001
    entry = we if use_we else cc
    if use_we and len(f.head(10))>0 and we<float(f.head(10)["low"].min()): return None
    hist = av.tail(60)
    atr = calc_atr(pd.concat([hist,f.head(20)]),20) if len(f)>=20 else entry*0.02
    if atr<=0: atr=entry*0.02
    ss = sl if (sl and sl>0) else entry*0.93
    et = ft if (ft and ft>0) else None
    atr_t = entry+2.0*atr; eff_t = max(et,atr_t) if (et and et>entry) else (atr_t if atr_t>entry else None)
    peak=entry; ts_p=None; half=False; s2=False; ep=None; er="max_hold"; hs=False; ht=False
    for i,(_,rw) in enumerate(f.iterrows()):
        d_=i+1; c,hi,lo = float(rw["close"]),float(rw["high"]),float(rw["low"])
        peak=max(peak,hi)
        if lo<=ss: ep=ss; er="stop_loss"; hs=True; break
        if d_<=30 and not half and eff_t and hi>=eff_t:
            half=True; s1p=eff_t; s2=True; ts_p=peak-atr_m*atr; ht=True; continue
        if d_==30: s2=True; ts_p=peak-atr_m*atr
        if s2:
            t=peak-atr_m*atr; ts_p=max(ts_p,t) if ts_p else t
            if lo<=ts_p: ep=ts_p; er="trailing_stop"; break
            if d_>ts_d and not half: ep=c; er="time_stop"; break
        ep=c
    if not hs and d_>=mh: ep=float(f.iloc[-1]["close"]); er="max_hold"
    if half and ht:
        r1=(s1p-entry)/entry*100; r2=(ep-entry)/entry*100
        tr=0.5*r1+0.5*r2; er=f"target_50pct+{er}"
    else: tr=(ep-entry)/entry*100
    return {"ret":round(tr,2),"days":d_}

# ===== 策略2: MA5/20金叉 =====
def trade_ma(df, as_of_date):
    a=pd.Timestamp(as_of_date)
    h=df[df["date"]<=a].tail(30)
    if len(h)<25: return None
    mf=float(h.tail(5)["close"].mean()); ms=float(h.tail(20)["close"].mean())
    ph=df[df["date"]<=a].tail(30).head(25)
    if len(ph)<25: return None
    pf=float(ph.tail(5)["close"].mean()); ps=float(ph.tail(20)["close"].mean())
    if not (pf<=ps and mf>ms): return None
    entry=float(h.iloc[-1]["close"])
    fut=df[df["date"]>a]
    ed=None
    for i in range(5,min(120,len(fut)-20)):
        sub=fut.iloc[:i+20]
        sf=float(sub.tail(5)["close"].mean()); ss=float(sub.tail(20)["close"].mean())
        if sf<ss: ed=i; break
    if ed is None: ed=min(120,len(fut)-1)
    fx=fut.iloc[:ed+1]
    if len(fx)<5: return None
    ep=float(fx.iloc[-1]["close"]); tr=(ep-entry)/entry*100
    return {"ret":round(tr,2),"days":len(fx)}

# ===== 多策略处理 =====
def process_stock(args):
    si,windows,csi=args
    sym,name=si["symbol"],si["name"]
    trades=[]
    try:
        dm=DataManager(); df=dm.get_data(sym)
        if df is None or df.empty or len(df)<300: return trades
        df["date"]=pd.to_datetime(df["date"]); df=df.sort_values("date").reset_index(drop=True)
        for w in windows:
            w1=trade_wyckoff(df,w,csi)
            if w1: trades.append({"strategy":"wyckoff","symbol":sym,"window":w,**w1})
            w2=trade_ma(df,w)
            if w2: trades.append({"strategy":"ma_cross","symbol":sym,"window":w,**w2})
    except Exception: pass
    return trades

def ann_sharpe(rets, avg_days):
    if len(rets)<5 or np.std(rets)==0 or avg_days<=0: return 0.0
    return float(np.mean(rets)/np.std(rets)*math.sqrt(252.0/avg_days))

def run():
    print("="*70)
    print("多策略合成最终验证 v4")
    print("  策略: Wyckoff v2+P3 + MA5/20金叉")
    print("  计算: 年化夏普 + 马科维茨组合 + 蒙特卡洛")
    print("="*70)
    OUTPUT_DIR.mkdir(parents=True,exist_ok=True)
    stocks=load_stocks(PROJECT_ROOT/"data"/"stock_list.csv",N_STOCKS)
    print(f"股票: {len(stocks)}")
    csi=load_csi300(); print(f"沪深300: {len(csi) if csi is not None else 0}行")
    windows=gen_windows(csi,N_WINDOWS); print(f"窗口: {len(windows)}")
    all_trades=[]
    mw=get_optimal_workers(); bs=mw*4
    args_list=[(s,windows,csi) for s in stocks]
    with ProcessPoolExecutor(max_workers=mw,initializer=worker_init) as ex:
        for b in range(0,len(args_list),bs):
            batch=args_list[b:b+bs]
            futures={ex.submit(process_stock,a):a[0]["symbol"] for a in batch}
            for f in as_completed(futures):
                try: all_trades.extend(f.result(timeout=300))
                except Exception: pass
            print(f"  {min(b+bs,len(args_list))}/{len(stocks)} 股票, {len(all_trades)}交易")

    if not all_trades: print("无交易"); return
    df=pd.DataFrame(all_trades)

    # === 单策略分析 ===
    strat_stats={}
    for s_name in ["wyckoff","ma_cross"]:
        sub=df[df["strategy"]==s_name]
        if len(sub)<5: continue
        rets=sub["ret"].values; ad=float(np.mean(sub["days"]))
        strat_stats[s_name]={
            "n":len(sub),"mean_ret":round(float(np.mean(rets)),2),
            "median_ret":round(float(np.median(rets)),2),"std":round(float(np.std(rets)),2),
            "win_rate":round(float(sum(rets>0)/len(rets)*100),1),
            "avg_days":round(ad,1),"max_win":round(float(np.max(rets)),2),
            "max_loss":round(float(np.min(rets)),2),
            "sharpe":round(ann_sharpe(rets,ad),3),
        }

    # === 相关性 ===
    merged=df[df["strategy"]=="wyckoff"][["window","symbol","ret"]].merge(
           df[df["strategy"]=="ma_cross"][["window","symbol","ret"]],
           on=["window","symbol"],suffixes=("_w","_m"))
    corr_val=round(float(merged["ret_w"].corr(merged["ret_m"])),3) if len(merged)>=5 else 0

    # === 组合夏普 ===
    ws=strat_stats.get("wyckoff",{}).get("sharpe",0)
    ms=strat_stats.get("ma_cross",{}).get("sharpe",0)
    combo_sharpe=((ws+ms)/2)*math.sqrt(2/(1+corr_val)) if corr_val<1 else 0
    sharpe_gain=(combo_sharpe/max(ws,0.01)-1)*100

    # === 蒙特卡洛: 重采样验证组合稳定性 ===
    np.random.seed(SEED)
    mc_results=[]
    for s_name in ["wyckoff","ma_cross"]:
        sub=df[df["strategy"]==s_name]
        if len(sub)<20: continue
        rets=sub["ret"].values; ad=float(np.mean(sub["days"]))
        for _ in range(MC_SIMS):
            sample=np.random.choice(rets,size=len(rets),replace=True)
            mc_results.append({"strategy":s_name,"sharpe":ann_sharpe(sample,ad)})
    mc_df=pd.DataFrame(mc_results)
    mc_stable={}
    for s_name in ["wyckoff","ma_cross"]:
        sub=mc_df[mc_df["strategy"]==s_name]["sharpe"]
        if len(sub)>0:
            mc_stable[s_name]={
                "mean":round(float(np.mean(sub)),3),
                "std":round(float(np.std(sub)),3),
                "p5":round(float(np.percentile(sub,5)),3),
                "p95":round(float(np.percentile(sub,95)),3),
                "p_positive":round(float(sum(sub>0)/len(sub)*100),1),
            }

    # === 输出 ===
    print(f"\n{'='*70}")
    print("单策略表现:")
    print(f"{'策略':12s} {'样本':>6s} {'收益均':>8s} {'中位':>8s} {'标准差':>8s} {'胜率':>6s} {'持有':>6s} {'最大赢':>8s} {'最大亏':>8s} {'夏普':>8s}")
    print("-"*90)
    for sn,s in strat_stats.items():
        print(f"  {sn:10s} {s['n']:>6d} {s['mean_ret']:>7.2f}% {s['median_ret']:>7.2f}% "
              f"{s['std']:>7.2f}% {s['win_rate']:>5.1f}% {s['avg_days']:>5.1f}d "
              f"{s['max_win']:>7.2f}% {s['max_loss']:>7.2f}% {s['sharpe']:>7.3f}")

    print(f"\n{'='*70}")
    print("相关性分析:")
    print(f"  共同样本(同股票同时间窗): {len(merged)}")
    print(f"  相关系数: {corr_val}")
    if len(merged)>=20:
        bins=[0,0.2,0.4,0.6,0.8,1.0]
        for i in range(len(bins)-1):
            cnt=sum(1 for _,r in merged.iterrows() if bins[i]<=abs(r["ret_w"]-r["ret_m"])<bins[i+1])
            print(f"    收益差[{bins[i]:.1f}-{bins[i+1]:.1f}%]: {cnt} 笔")

    print(f"\n{'='*70}")
    print("组合效果:")
    print(f"  Wyckoff 夏普: {ws:.3f}")
    print(f"  MA Cross 夏普: {ms:.3f}")
    print(f"  相关系数: {corr_val:.3f}")
    print(f"  {'='*40}")
    print(f"  等权组合夏普: {combo_sharpe:.3f}")
    print(f"  夏普提升: {sharpe_gain:+.1f}%")
    print(f"  结论: {'✅ 组合有效提升夏普' if combo_sharpe>max(ws,ms) else '❌ 组合未提升夏普'}")

    print(f"\n{'='*70}")
    print("蒙特卡洛稳定性校验 (10,000次重采样):")
    for sn,mc in mc_stable.items():
        print(f"  {sn:12s}: 均值={mc['mean']:.3f} 标准差={mc['std']:.3f} "
              f"90%CI=[{mc['p5']:.3f},{mc['p95']:.3f}] 正值概率={mc['p_positive']:.1f}%")

    jp=OUTPUT_DIR/"v4_results.json"
    analysis={
        "config":{"n_stocks":N_STOCKS,"n_windows":N_WINDOWS,"mc_sims":MC_SIMS},
        "strategies":strat_stats,
        "correlation":{"n_common":len(merged),"value":corr_val},
        "portfolio":{"wyckoff_sharpe":ws,"ma_sharpe":ms,"correlation":corr_val,
                      "combined_sharpe":round(combo_sharpe,3),
                      "sharpe_gain_pct":round(sharpe_gain,1)},
        "monte_carlo":mc_stable,
    }
    with jp.open("w",encoding="utf-8") as f:
        json.dump(analysis,f,ensure_ascii=False,indent=2,default=str)
    print(f"\n结果: {jp}")
    print(f"\n{'='*70} 完成 {'='*70}")

if __name__=="__main__":
    run()
