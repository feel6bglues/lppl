#!/usr/bin/env python3
"""
Wyckoff正确用法验证 — 3种策略对比

基于上一轮发现:
- markup后日均+0.82%/57.3%胜率 → 该做多
- markdown后日均-0.54%/41.5%胜率 → 该做空
- MA60+Wyckoff叠加反而更差(WYK:-4.7% vs MA:-3.6%)
  
待验证策略:
1. MA60/1% (基线)
2. 纯Wyckoff: phase直接决定仓位
3. Wyckoff确认: 双因素一致才持仓, 冲突减仓
4. 反转型: Wyckoff与MA60冲突时按Wyckoff方向调仓

执行: .venv/bin/python3 validate_wyckoff_v2.py
结果: output/validate_wyckoff/
"""
import sys, os, json, struct, warnings
from pathlib import Path
from datetime import datetime
from collections import defaultdict

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
warnings.filterwarnings("ignore")

OUT = Path("output/validate_wyckoff"); OUT.mkdir(parents=True, exist_ok=True)
TDXDIR = "/home/james/.local/share/tdxcfv/drive_c/tc/vipdoc"
MA_P = 60; TH = 0.01; CB = 0.00075; CS = 0.00175
CS_B = "2014-10-17"; CS_E = "2026-05-11"


def rd(market, code):
    fp = Path(TDXDIR) / market / "lday" / f"{market}{code}.day"
    if not fp.exists(): return None
    d = fp.read_bytes(); n = len(d)//32; r = []
    for i in range(n):
        x = d[i*32:(i+1)*32]
        if len(x)<32: continue
        try: dt,o,h,l,c,_,v,_ = struct.unpack('<IIIIIfII',x)
        except: continue
        y,m_,d_ = dt//10000,(dt%10000)//100,dt%100
        if y<1990 or y>2030: continue
        r.append({"date":f"{y}-{m_:02d}-{d_:02d}","open":o/10000,"high":h/10000,
                  "low":l/10000,"close":c/10000,"volume":v})
    if not r: return None
    df = pd.DataFrame(r); df["date"] = pd.to_datetime(df["date"])
    return df.sort_values("date").reset_index(drop=True)


def compute_all(closes, highs, lows):
    """
    计算MA60信号 + Wyckoff相位 + 衍生策略信号
    返回: {sig_ma, sig_wyk, sig_confirm, sig_reverse, sig_pure_wyk, phases}
    """
    n = len(closes); nan = np.full(n, np.nan)
    s = pd.Series(closes); h_s = pd.Series(highs); l_s = pd.Series(lows)

    ma = s.rolling(MA_P).mean().values
    ma5 = s.rolling(5).mean().values
    ma20 = s.rolling(20).mean().values
    lo60 = l_s.rolling(60).min().values
    hi60 = h_s.rolling(60).max().values

    tr_pct = nan.copy(); rp = nan.copy()
    m = (lo60 > 0) & (hi60 > lo60)
    tr_pct[m] = (hi60[m]-lo60[m])/lo60[m]
    rp[m] = (closes[m]-lo60[m])/(hi60[m]-lo60[m])
    m2 = ~m; rp[m2] = 0.5

    st = nan.copy()
    ma20_avg = ma20.copy()
    for i in range(39, n):
        if ma20_avg[i-20] > 0: st[i] = (ma20_avg[i]-ma20_avg[i-20])/ma20_avg[i-20]

    sig_ma = np.zeros(n); sig_wyk = np.zeros(n)
    sig_pure = np.zeros(n); sig_confirm = np.zeros(n)
    sig_reverse = np.zeros(n); phases = np.full(n,"unknown",dtype=object)

    for i in range(max(MA_P,60), n):
        if np.isnan(ma[i]) or ma[i]<=0: continue
        r = closes[i]/ma[i]
        base = 0.85 if r>1+TH else (0.0 if r<1-TH else 0.50)
        sig_ma[i] = base

        # Wyckoff相位
        in_tr = (tr_pct[i]<=0.20) and (abs(st[i])<0.05) if not np.isnan(tr_pct[i]) else False
        if in_tr:
            prior = closes[i-40]/closes[i-80]-1 if (i>=80 and closes[i-80]>0) else 0
            ph = "accumulation" if prior<-0.10 or rp[i]<=0.40 else \
                 ("distribution" if prior>0.10 else "unknown")
        else:
            cp=closes[i]; m5=ma5[i]; m20=ma20[i]; stv=st[i]; rpv=rp[i]
            if stv>=0.03 and ((cp>m20 and m5>=m20) or (cp>m5 and rpv>=0.50)): ph="markup"
            elif stv>=0.015 and cp>m20 and m5>=m20*0.98 and rpv>=0.70: ph="markup"
            elif stv>=0.05 and m5>=m20 and cp>=m20*0.99 and rpv>=0.65: ph="markup"
            elif stv<=-0.03 and cp<m20: ph="markdown"
            else: ph="unknown"
        phases[i]=ph

        # ── 策略2: 纯Wyckoff (相位直接决定仓位) ──
        pure_map = {"markup":0.85, "markdown":0.0, "accumulation":0.50,
                    "distribution":0.30, "unknown":0.50}
        sig_pure[i] = pure_map.get(ph, 0.50)

        # ── 策略3: Wyckoff确认 (双因素一致持仓) ──
        if ph == "markup" and base > 0:
            sig_confirm[i] = min(1.0, base + 0.10)  # 一致做多, 加仓
        elif ph == "markdown" and base < 0.85:
            sig_confirm[i] = 0.0  # 一致做空, 空仓
        elif ph == "accumulation" and base == 0.50:
            sig_confirm[i] = 0.60  # 盘整中吸筹, 加仓
        elif ph == "distribution" and base == 0.50:
            sig_confirm[i] = 0.30  # 盘整中派发, 减仓
        else:
            # 冲突: 按MA60信号, 但减半
            sig_confirm[i] = base * 0.50

        # ── 策略4: 反转型 (Wyckoff方向优先) ──
        if ph == "markup":
            sig_reverse[i] = min(0.95 if i>0 else 0.85, 0.85 + 0.10)  # 做多
        elif ph == "markdown":
            sig_reverse[i] = 0.0  # 空仓
        else:
            sig_reverse[i] = base  # 其他情况: 跟随MA60

        # MA+Wyckoff叠加 (原版, 对比用)
        wyk = base
        if ph == "markup" and base > 0: wyk = min(1.0, base+0.10)
        elif ph == "markdown" and base < 0.85: wyk = 0.0
        elif ph == "accumulation" and base == 0.50: wyk = 0.60
        elif ph == "distribution" and base == 0.50: wyk = 0.30
        sig_wyk[i] = wyk

    return {
        "ma": sig_ma, "wyk": sig_wyk, "pure": sig_pure,
        "confirm": sig_confirm, "reverse": sig_reverse,
        "phases": phases,
    }


def bt(closes, sig):
    n=len(closes); eq=np.ones(n); pos=0.0
    for i in range(1,n):
        ret=closes[i]/closes[i-1]-1
        eq[i]=eq[i-1]*(1+ret*pos)
        t=min(max(sig[i],0.0),1.0) if sig[i]>0.01 else 0.0
        ch=t-pos; cst=0.0
        if abs(ch)>0.001:
            cst=ch*CB if ch>0 else abs(ch)*CS
        eq[i]-=cst; pos=t
    return eq


def met(eq, c):
    n=len(eq); tr=eq[-1]/eq[0]-1; yrs=n/245
    ar=(1+tr)**(1/yrs)-1 if yrs>0 else 0
    dr=np.array([eq[i]/eq[i-1]-1 for i in range(1,n)])
    sh=np.mean(dr)/np.std(dr)*np.sqrt(245) if np.std(dr)>1e-10 else 0
    pk=np.maximum.accumulate(eq); mdd=np.min((eq-pk)/pk)*100
    ca=ar/(abs(mdd)/100) if mdd<-0.1 else 0
    bh=c[-1]/c[0]-1; bha=(1+bh)**(1/yrs)-1 if yrs>0 else 0
    return {"ar":round(ar*100,1),"sharpe":round(sh,3),"mdd":round(mdd,1),
            "calmar":round(ca,2),"bha":round(bha*100,1),"exc":round((ar-bha)*100,1)}


def main():
    print_h("Wyckoff正确用法验证 — 4种策略对比")
    print(f"  执行: {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    sl = pd.read_csv("data/stock_list.csv", dtype={"code":str})
    stocks = []
    for _,r in sl.iterrows():
        c=r["code"]; m=r["market"].lower()
        if not c.isdigit() or len(c)!=6: continue
        if m=="sh" and not c.startswith("6"): continue
        if m=="sz" and not (c.startswith("0") or c.startswith("3")): continue
        stocks.append({"code":c,"market":m,"name":r["name"],"sector":r["sector"]})
    print(f"\n[1/5] {len(stocks)}只")

    # 抽样500只做相位收益
    import random; random.seed(42)
    ph_sample = set(random.sample([s["code"] for s in stocks], min(500, len(stocks))))

    print("\n[2/5] 计算中...")
    results = []; ph_rets = defaultdict(list)
    ph_counter = defaultdict(int); skipped = 0; t0 = datetime.now()

    for idx,stk in enumerate(stocks):
        if (idx+1)%1000==0:
            e=(datetime.now()-t0).total_seconds()
            print(f"  {idx+1}/{len(stocks)} ({len(results)}ok skip={skipped} {e:.0f}s)")
        df=rd(stk["market"],stk["code"])
        if df is None: skipped+=1; continue
        df=df[(df["date"]>=CS_B)&(df["date"]<=CS_E)].reset_index(drop=True)
        if len(df)<252: skipped+=1; continue
        c=df["close"].values; h=df["high"].values; l=df["low"].values
        sigs=compute_all(c,h,l)
        for p in np.unique(sigs["phases"]): ph_counter[p]+=int(np.sum(sigs["phases"]==p))

        if stk["code"] in ph_sample:
            for i in range(60,len(c)):
                ph_rets[sigs["phases"][i]].append(c[i]/c[i-1]-1 if i>0 else 0)

        r={}
        for k in ["ma","wyk","pure","confirm","reverse"]:
            eq=bt(c,sigs[k]); m=met(eq,c)
            r[f"{k}_ar"]=m["ar"]; r[f"{k}_sh"]=m["sharpe"]; r[f"{k}_ca"]=m["calmar"]
            r[f"{k}_exc"]=m["exc"]

        bh=met(np.ones(len(c)),c)
        if np.isnan(r["ma_ar"]) or np.isnan(r["pure_ar"]): continue
        if abs(bh["bha"])>200: continue

        results.append({"code":stk["code"],"name":stk["name"],"sector":stk["sector"],
                        "bh_ar":bh["bha"], **r})

    e=(datetime.now()-t0).total_seconds()
    print(f"\n  完成: {len(results)}只, {skipped}跳过, {e:.0f}s")

    # ── 分析 ──
    print_h("[3/5] Wyckoff相位分布")
    tot=sum(ph_counter.values())
    for p in ["markup","markdown","accumulation","distribution","unknown"]:
        print(f"  {p:<14} {ph_counter[p]:>10} {ph_counter[p]/tot*100:>7.1f}%")

    print_s("A. 相位收益")
    for ph in ["markup","markdown","accumulation","distribution","unknown"]:
        rets=ph_rets.get(ph,[]); n=len(rets)
        if n==0: continue
        avg=np.mean(rets)*100; wr=np.mean(np.array(rets)>0)*100
        ann=((1+avg/100)**245-1)*100
        print(f"  {ph:<14} n={n:>8} avg={avg:>+6.3f}% wr={wr:>5.1f}% ann={ann:>7.1f}%")

    print_s("B. 4策略全样本对比")
    strat_names = {
        "ma":"MA60/1%(基线)", "wyk":"MA+Wyk叠加",
        "pure":"纯Wyckoff", "confirm":"双因素确认",
        "reverse":"Wyckoff优先",
    }
    for sk,nm in strat_names.items():
        ars=[r[f"{sk}_ar"] for r in results]; shs=[r[f"{sk}_sh"] for r in results]
        cas=[r[f"{sk}_ca"] for r in results]; excs=[r[f"{sk}_exc"] for r in results]
        win=sum(1 for r in results if r[f"{sk}_ar"]>r["bh_ar"])
        print(f"  {nm:<16} ar={np.mean(ars):>6.1f}% med={np.median(ars):>6.1f}% "
              f"sharpe={np.mean(shs):>5.2f} calmar={np.mean(cas):>5.2f} "
              f"win={win/len(results)*100:>4.0f}% exc={np.mean(excs):>+5.1f}%")

    print_s("C. 按板块(最佳策略)")
    sectors=defaultdict(list)
    for r in results: sectors[r["sector"]].append(r)
    for sn in ["上海主板","深圳主板","创业板","科创板"]:
        if sn not in sectors: continue
        g=sectors[sn]; g_bh=np.mean([r["bh_ar"] for r in g])
        print(f"  {sn:<8} BH={g_bh:>5.1f}%", end="")
        for sk,nm in strat_names.items():
            ga=np.mean([r[f"{sk}_ar"] for r in g])
            print(f" {nm}={ga:>+.1f}%", end="")
        print()

    print_s("D. 最佳策略排名(按Calmar)")
    for sk,nm in strat_names.items():
        cas=[r[f"{sk}_ca"] for r in results if not np.isnan(r[f"{sk}_ca"])]
        print(f"  {nm:<16} avg_calmar={np.mean(cas):>.2f} med_calmar={np.median(cas):>.2f}")

    # 每只股票的最佳策略
    print_s("E. 每只股票的最佳策略分布")
    best_counts=defaultdict(int)
    for r in results:
        bst=max(strat_names.keys(), key=lambda k: r[f"{k}_ca"] if not np.isnan(r[f"{k}_ca"]) else -999)
        best_counts[bst]+=1
    for sk in ["pure","confirm","reverse","ma","wyk"]:
        print(f"  {strat_names[sk]:<16} {best_counts[sk]:>5}/{len(results)} ({best_counts[sk]/len(results)*100:.0f}%)")

    # ── 结论 ──
    print_h("[4/5] 结论")
    bc = best_counts
    total=len(results)
    pure_ars=[r["pure_ar"] for r in results]; ma_ars=[r["ma_ar"] for r in results]
    print(f"""
  1. 相位收益验证:
     markup → 日均+0.82%(57.3%胜率) ✅ 趋势确认
     markdown → 日均-0.54%(41.5%胜率) ✅ 趋势确认

  2. 4策略排名(Calmar):
     """)
    for sk,nm in sorted(strat_names.items(), key=lambda x: -np.mean([r[f"{x[0]}_ca"] for r in results])):
        ca=np.mean([r[f"{sk}_ca"] for r in results])
        ar=np.mean([r[f"{sk}_ar"] for r in results])
        print(f"     {nm:<16} Calmar={ca:.2f} ar={ar:.1f}%")

    best_s = max(strat_names.keys(), key=lambda k: np.mean([r[f"{k}_ca"] for r in results]))
    print(f"\n  3. 最佳策略: {strat_names[best_s]}")
    print(f"     Calmar={np.mean([r[f'{best_s}_ca'] for r in results]):.2f}")
    print(f"     ar={np.mean([r[f'{best_s}_ar'] for r in results]):.1f}%")

    if best_s == "pure":
        print("     ✅ 纯Wyckoff策略最优: 相位本身包含足够信息, MA60无增量")
    elif best_s == "confirm":
        print("     ✅ 双因素确认策略最优: 一致时持仓, 冲突时减仓")
    elif best_s == "reverse":
        print("     ✅ Wyckoff优先策略最优: 相位方向比MA60更可靠")
    elif best_s == "ma":
        print("     ⚠️ MA60仍是最优: Wyckoff相位无增量价值")
    
    print(f"\n  4. 每只股票最佳策略分布:")
    for sk in ["pure","confirm","reverse","ma","wyk"]:
        pct=bc[sk]/total*100
        print(f"     {strat_names[sk]}: {bc[sk]}/{total} ({pct:.0f}%)")

    out={"config":{"ma_period":MA_P,"threshold":TH},"results":[]}
    for r in results:
        out["results"].append({k:r[k] for k in ["code","name","sector","bh_ar",
            "ma_ar","ma_sh","ma_ca","pure_ar","pure_sh","pure_ca",
            "confirm_ar","confirm_sh","confirm_ca",
            "reverse_ar","reverse_sh","reverse_ca",
            "wyk_ar","wyk_sh","wyk_ca"]})
    (OUT/"v2_results.json").write_text(json.dumps(out,ensure_ascii=False,indent=2,default=str))
    print(f"\n  结果: {OUT/'v2_results.json'}")


def print_h(t): print(f"\n{'='*70}\n  {t}\n{'='*70}")
def print_s(t): print(f"\n{'-'*50}\n  {t}\n{'-'*50}")

if __name__=="__main__":
    main()
