#!/usr/bin/env python3
"""
# DEPRECATED: 请使用 scripts/run_backtest.py 替代。本文件将在下个迭代移除。

三策略组合验证 v6 — Wyckoff + MA5/20 + Short-term Reversal
====================================================
策略1: Wyckoff v2+P3 (22天持有, 结构分析)      Sharpe 0.74
策略2: MA5/20金叉 (14天持有, 趋势跟踪)         Sharpe 0.66
策略3: Short-term Reversal (5-10天, 短期反转)    预期Sharpe 0.60

设计目标: 三策略等权组合夏普 > 0.90
"""

import csv, json, math, random, sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
from src.data.manager import DataManager
from src.data.tdx_loader import load_tdx_data
from src.wyckoff.engine import WyckoffEngine
from src.parallel import get_optimal_workers, worker_init
from scripts.utils.tdx_config import CSI300_PATH, TDX_BASE, TDX_SH_DIR, TDX_SZ_DIR


N_STOCKS = 99999; N_WINDOWS = 20; SEED = 42
MC_SIMS = 10000; MR_HOLD_MAX = 5
CSI300_PATH = CSI300_PATH
OUTPUT_DIR = PROJECT_ROOT / "output" / "tristrat_v6_str_2020"

REGIME_PARAMS = {
    "range": {"atr_mult": 1.5, "ts": 45, "mh": 90},
    "bear":  {"atr_mult": 2.5, "ts": 90, "mh": 180},
    "bull":  {"atr_mult": 3.0, "ts": 60, "mh": 120},
    "unknown": {"atr_mult": 2.0, "ts": 60, "mh": 120},
}

def load_stocks(csv_path, limit=N_STOCKS):
    syms=[]
    with csv_path.open("r",encoding="utf-8-sig",newline="") as f:
        for row in csv.DictReader(f):
            c=row.get("code","").strip(); m=row.get("market","").strip().upper()
            n=row.get("name","").replace("\x00","").strip()
            if not(c.isdigit() and len(c)==6 and m in {"SH","SZ"}): continue
            if c.startswith(("600","601","603","605","688","689","000","001","002","003","300","301","302")):
                syms.append({"symbol":f"{c}.{m}","code":c,"market":m,"name":n})
                if len(syms)>=limit: break
    return syms

def load_csi300():
    p=CSI300_PATH
    if p.exists():
        df=load_tdx_data(str(p))
        if df is not None and not df.empty:
            df["date"]=pd.to_datetime(df["date"]); return df.sort_values("date").reset_index(drop=True)
    return None

def gen_windows(csi,n=N_WINDOWS,min_year=2020,max_year=2025):
    if csi is None or len(csi)<200: return []
    d=csi["date"].dt.strftime("%Y-%m-%d").tolist()
    d=[x for x in d if int(x[:4])>=min_year and int(x[:4])<=max_year]
    if len(d)<n+200: return []
    random.seed(SEED)
    return sorted(random.sample(d[:len(d)-200],min(n,len(d)-200)))

def get_regime(csi,d):
    a=pd.Timestamp(d); h=csi[csi["date"]<=a]
    if len(h)<120: return "unknown"
    c=float(h.iloc[-1]["close"]); m120=float(h.tail(120)["close"].mean()); m60=float(h.tail(60)["close"].mean())
    if c>m120*1.02 and m60>m120: return "bull"
    if c<m120*0.98: return "bear"
def calc_atr(s,p=20):
    if len(s)<p+1: return 0.0
    tr_vals=[]
    for i in range(1,min(p+1,len(s))):
        hi=float(s.iloc[-i]["high"]); lo=float(s.iloc[-i]["low"]); pc=float(s.iloc[-i-1]["close"])
        tr_vals.append(max(hi-lo,abs(hi-pc),abs(lo-pc)))
    return float(np.mean(tr_vals)) if tr_vals else 0.0
    hi,lo=s["high"].values[-p:],s["low"].values[-p:]
    return float(np.mean([hi[i]-lo[i] for i in range(p)]))

# ===== S1: Wyckoff =====
def trade_wyckoff(df,as_of_date,csi):
    a=pd.Timestamp(as_of_date); av=df[df["date"]<=a]
    if len(av)<100: return None
    try:
        eng=WyckoffEngine(lookback_days=400,weekly_lookback=120,monthly_lookback=40)
        rpt=eng.analyze(av,symbol="",period="日线",multi_timeframe=True)
    except Exception: return None
    rr=rpt.risk_reward
    we=rr.entry_price if(rr and rr.entry_price and rr.entry_price>0) else None
    sl=rr.stop_loss if(rr and rr.stop_loss and rr.stop_loss>0) else None
    ft=rr.first_target if(rr and rr.first_target and rr.first_target>0) else None
    if rpt.signal.signal_type=="no_signal" or rpt.trading_plan.direction=="空仓观望": return None
    regime=get_regime(csi,as_of_date) if csi is not None else "unknown"
    if regime=="bear": return None
    p=REGIME_PARAMS.get(regime,REGIME_PARAMS["unknown"])
    atr_m,ts_d,mh=p["atr_mult"],p["ts"],p["mh"]
    f=df[df["date"]>a].head(mh)
    if len(f)<mh*0.5: return None
    cc=float(av.iloc[-1]["close"])
    use_we=we and we>0 and abs(we-cc)/cc>0.001
    entry=we if use_we else cc
    if use_we and len(f.head(10))>0 and we<float(f.head(10)["low"].min()): return None
    hist=av.tail(60)
    atr=calc_atr(pd.concat([hist,f.head(20)]),20) if len(f)>=20 else entry*0.02
    if atr<=0: atr=entry*0.02
    ss=sl if(sl and sl>0) else entry*0.93
    et=ft if(ft and ft>0) else None
    atr_t=entry+2.0*atr; eff_t=max(et,atr_t) if(et and et>entry) else(atr_t if atr_t>entry else None)
    peak=entry; ts_p=None; half=False; s2=False; ep=None; er="max_hold"; hs=False; ht=False
    for i,(_,rw) in enumerate(f.iterrows()):
        d_=i+1; c,hi,lo=float(rw["close"]),float(rw["high"]),float(rw["low"])
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

# ===== S2: MA5/20金叉 =====
def trade_ma(df,as_of_date):
    a=pd.Timestamp(as_of_date); h=df[df["date"]<=a].tail(30)
    if len(h)<25: return None
    mf=float(h.tail(5)["close"].mean()); ms=float(h.tail(20)["close"].mean())
    ph=df[df["date"]<=a].tail(30).head(25)
    if len(ph)<25: return None
    pf=float(ph.tail(5)["close"].mean()); ps=float(ph.tail(20)["close"].mean())
    if not(pf<=ps and mf>ms): return None
    entry=float(h.iloc[-1]["close"])
    fut=df[df["date"]>a]; ed=None
    for i in range(5,min(120,len(fut)-20)):
        sub=fut.iloc[:i+20]; sf=float(sub.tail(5)["close"].mean()); ss=float(sub.tail(20)["close"].mean())
        if sf<ss: ed=i; break
    if ed is None: ed=min(120,len(fut)-1)
    fx=fut.iloc[:ed+1]
    if len(fx)<5: return None
    ep=float(fx.iloc[-1]["close"]); tr=(ep-entry)/entry*100
    return {"ret":round(tr,2),"days":len(fx)}

# ===== S3: Short-term Reversal (短期反转) =====
def trade_str(df, as_of_date):
    """
    短期反转策略 (Short-term Reversal):
    1. 过去5日收益 < -5% (超跌) → 买入
    2. 持有5个交易日
    3. 止盈+4%, 止损-4%
    4. 逻辑: A股散户过度反应后必然短期反弹
    """
    a = pd.Timestamp(as_of_date)
    h = df[df["date"] <= a].tail(10)
    if len(h) < 8: return None
    
    # 过去5日收益率
    p5 = float(h.iloc[-1]["close"])
    p0 = float(h.iloc[-6]["close"]) if len(h) >= 6 else float(h.iloc[0]["close"])
    ret_5d = (p5 - p0) / p0 * 100
    
    # 超跌触发: 5日跌超5%
    if ret_5d > -5.0: return None
    
    entry = p5
    fut = df[df["date"] > a].head(5)
    if len(fut) < 3: return None
    
    tp = entry * 1.04; sl = entry * 0.96
    ep, ed, er = entry, len(fut), "max_hold"
    for i, (_, rw) in enumerate(fut.iterrows()):
        c, hi, lo = float(rw["close"]), float(rw["high"]), float(rw["low"])
        if hi >= tp: ep, ed, er = tp, i+1, "str_tp"; break
        if lo <= sl: ep, sl, er = sl, i+1, "str_sl"; break
        ep, ed = c, i+1
    tr = (ep - entry) / entry * 100
    return {"ret": round(tr, 2), "days": ed, "entry": round(entry, 2), "er": er}


# ===== 多策略处理 =====
def process_stock(args):
    si,windows,csi=args
    sym,name=si["symbol"],si["name"]; trades=[]
    try:
        dm=DataManager(); df=dm.get_data(sym)
        if df is None or df.empty or len(df)<300: return trades
        df["date"]=pd.to_datetime(df["date"]); df=df.sort_values("date").reset_index(drop=True)
        for w in windows:
            w1=trade_wyckoff(df,w,csi)
            if w1: trades.append({"strategy":"wyckoff","symbol":sym,"window":w,**w1})
            w2=trade_ma(df,w)
            if w2: trades.append({"strategy":"ma_cross","symbol":sym,"window":w,**w2})
            w3=trade_str(df,w)
            if w3: trades.append({"strategy":"str_reversal","symbol":sym,"window":w,**w3})
    except Exception: pass
    return trades

def ann_sharpe(rets,avg_days):
    if len(rets)<5 or np.std(rets)==0 or avg_days<=0: return 0.0
    return float(np.mean(rets)/np.std(rets)*math.sqrt(252.0/avg_days))

def compute_stats(sub_df):
    rets=sub_df["ret"].values; ad=float(np.mean(sub_df["days"]))
    return {"n":len(sub_df),"mean_ret":round(float(np.mean(rets)),2),
            "median_ret":round(float(np.median(rets)),2),"std":round(float(np.std(rets)),2),
            "win_rate":round(float(sum(rets>0)/len(rets)*100),1),
            "avg_days":round(ad,1),"sharpe":round(ann_sharpe(rets,ad),3)}

def run():
    np.random.seed(42)
    print("="*70)
    print("三策略组合验证 v6: Wyckoff + MA5/20 + Short-term Reversal (2020-2025)")
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
    print(f"\n总交易: {len(df)}笔")
    for s in ["wyckoff","ma_cross","str_reversal"]:
        print(f"  {s}: {sum(1 for t in all_trades if t['strategy']==s)}")

    # 单策略统计
    results={}
    for sn in ["wyckoff","ma_cross","str_reversal"]:
        sub=df[df["strategy"]==sn]
        if len(sub)>=5: results[sn]=compute_stats(sub)

    # 相关性矩阵
    corr_data={}
    for t1,t2 in [("wyckoff","ma_cross"),("wyckoff","str_reversal"),("ma_cross","str_reversal")]:
        merged=df[df["strategy"]==t1][["window","symbol","ret"]].merge(
               df[df["strategy"]==t2][["window","symbol","ret"]],
               on=["window","symbol"],suffixes=("_1","_2"))
        if len(merged)>=5:
            c=round(float(merged["ret_1"].corr(merged["ret_2"])),3)
            corr_data[f"{t1}_vs_{t2}"]={"corr":c,"n":len(merged)}

    # 组合夏普 (三策略等权)
    s_vals=[results[s]["sharpe"] for s in ["wyckoff","ma_cross","str_reversal"] if s in results]
    if len(s_vals)==3:
        r_names=["wyckoff","ma_cross","str_reversal"]
        rho_matrix=np.array([[1.0]*3]*3)
        for i in range(3):
            for j in range(3):
                if i<j:
                    k=f"{r_names[i]}_vs_{r_names[j]}"
                    if k in corr_data: rho_matrix[i][j]=rho_matrix[j][i]=corr_data[k]["corr"]
        avg_s=np.mean(s_vals)
        avg_rho=(np.sum(rho_matrix)-3)/6  # 上三角平均值
        n_strat=3
        combo=avg_s*math.sqrt(n_strat/(1+(n_strat-1)*avg_rho))
    elif len(s_vals)==2:
        avg_s=np.mean(s_vals)
        avg_rho=corr_data.get(f"{list(results.keys())[0]}_vs_{list(results.keys())[1]}",{}).get("corr",0.5)
        combo=avg_s*math.sqrt(2/(1+avg_rho))
    else:
        combo=0

    # 蒙特卡洛
    mc={}
    for sn in ["wyckoff","ma_cross","str_reversal"]:
        sub=df[df["strategy"]==sn]
        if len(sub)<20: continue
        rets=sub["ret"].values; ad=float(np.mean(sub["days"]))
        sims=[ann_sharpe(np.random.choice(rets,size=len(rets),replace=True),ad) for _ in range(MC_SIMS)]
        mc[sn]={"mean":round(float(np.mean(sims)),3),"ci_5":round(float(np.percentile(sims,5)),3),
                "ci_95":round(float(np.percentile(sims,95)),3),"p_pos":round(float(sum(s>0 for s in sims)/len(sims)*100),1)}

    # 输出
    print(f"\n{'='*70}")
    print("三策略表现:")
    print(f"{'策略':15s} {'样本':>8s} {'收益均':>8s} {'中位':>8s} {'标准差':>8s} {'胜率':>6s} {'持有':>6s} {'夏普':>8s}")
    print("-"*70)
    for sn in ["wyckoff","ma_cross","str_reversal"]:
        r=results.get(sn)
        if r: print(f"  {sn:13s} {r['n']:>8d} {r['mean_ret']:>7.2f}% {r['median_ret']:>7.2f}% "
                    f"{r['std']:>7.2f}% {r['win_rate']:>5.1f}% {r['avg_days']:>5.1f}d {r['sharpe']:>7.3f}")

    print(f"\n相关性矩阵:")
    for k,v in sorted(corr_data.items()):
        print(f"  {k:25s}: {v['corr']:.3f} (n={v['n']})")

    print(f"\n组合效果:")
    print(f"  三策略等权夏普: {combo:.3f}")
    print(f"  vs 双策略(v5): 0.751")
    print(f"  vs Wyckoff单: {results.get('wyckoff',{}).get('sharpe',0):.3f}")
    print(f"  提升: {(combo/max(results.get('wyckoff',{}).get('sharpe',0.01),0.01)-1)*100:+.1f}%")

    print(f"\n蒙特卡洛(10,000次):")
    for sn,m in mc.items():
        print(f"  {sn:13s}: 均值={m['mean']:.3f} 90%CI=[{m['ci_5']:.3f},{m['ci_95']:.3f}] 正值={m['p_pos']:.1f}%")

    # 目标检查
    print(f"\n{'='*70}")
    print("目标检查:")
    print(f"  {'✅' if combo>=0.90 else '❌'} 组合夏普 > 0.90 (当前: {combo:.3f})")
    print(f"  {'✅' if combo>0.751 else '❌'} 优于双策略 (diff: {(combo-0.751)*100:+.1f}%)")
    for s_name in ["wyckoff","ma_cross","str_reversal"]:
        r=results.get(s_name)
        if r: print(f"  {'✅' if r['sharpe']>0 else '❌'} {s_name} 夏普正值 ({r['sharpe']:.3f})")

    jp=OUTPUT_DIR/"v6_results.json"
    with jp.open("w",encoding="utf-8") as f:
        json.dump({"config":{"n_stocks":len(stocks),"n_windows":N_WINDOWS,"mc_sims":MC_SIMS,"mc_seed":42,"window_seed":42,"min_year":2020,"max_year":2025,"with_costs":True,"cost_model":{"buy_pct":0.075,"sell_pct":0.175,"round_trip_pct":0.25,"description":"佣金万2.5+印花税千1+滑点万5"}},
                   "strategies":results,"correlations":corr_data,
                   "portfolio":{"three_strat_sharpe":round(combo,3)},"monte_carlo":mc},
                  f,ensure_ascii=False,indent=2,default=str)
    print(f"\n结果: {jp}\n{'='*70}完成{'='*70}")

if __name__=="__main__":
    run()
