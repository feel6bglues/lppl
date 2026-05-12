#!/usr/bin/env python3
"""
新因子验证 v4 — 全量5000只, 向量化计算

因子: 短期反转, 截面动量, 涨跌停动量, 多因子等权
回测: 月度调仓多空对冲(扣成本)
输出: output/validate_wyckoff/new_factors_final.json

执行: timeout 600 .venv/bin/python3 validate_new_factors_final.py
"""
import numpy as np, pandas as pd, struct, json, time
from pathlib import Path
from collections import defaultdict

import warnings
OUT=Path("output/validate_wyckoff"); OUT.mkdir(parents=True,exist_ok=True)
TDXDIR="/home/james/.local/share/tdxcfv/drive_c/tc/vipdoc"


def rd(m,c):
    fp=Path(TDXDIR)/m/"lday"/f"{m}{c}.day"
    if not fp.exists(): return None
    d=fp.read_bytes(); n=len(d)//32; r=[]
    for i in range(n):
        x=d[i*32:(i+1)*32]
        if len(x)<32: continue
        try: dt,o,h,l,cl,_,v,_=struct.unpack('<IIIIIfII',x)
        except: continue
        y,mm,dd=dt//10000,(dt%10000)//100,dt%100
        if y<1990 or y>2030: continue
        r.append({"date":f"{y}-{mm:02d}-{dd:02d}","close":cl/10000})
    if not r: return None
    df=pd.DataFrame(r); df["date"]=pd.to_datetime(df["date"])
    return df.sort_values("date").reset_index(drop=True)


def load(n_max=5000):
    sl=pd.read_csv("data/stock_list.csv",dtype={"code":str})
    stocks=[]; seen=set()
    for _,r in sl.iterrows():
        c=r["code"]; m=r["market"].lower()
        if not c.isdigit() or len(c)!=6: continue
        if m=="sh" and not c.startswith("6"): continue
        if m=="sz" and not (c.startswith("0") or c.startswith("3")): continue
        if c in seen: continue; seen.add(c)
        df=rd(m,c)
        if df is None: continue
        df=df[(df["date"]>="2014-10-17")&(df["date"]<="2026-05-11")].reset_index(drop=True)
        if len(df)<252: continue
        stocks.append({"close_arr":df["close"].values,"date_arr":df["date"].astype(str).str[:10].values})
        if len(stocks)>=n_max: break
    return stocks


def build_date_index(stocks):
    all_d=sorted(set(d for s in stocks for d in s["date_arr"]))
    d2i={d:i for i,d in enumerate(all_d)}
    return all_d, d2i


def build_close_matrix(stocks, d2i, all_d):
    n_s,n_d=len(stocks),len(all_d)
    cm=np.full((n_s,n_d),np.nan)
    for si,s in enumerate(stocks):
        for i,d in enumerate(s["date_arr"]): cm[si,d2i[d]]=s["close_arr"][i]
    return cm


def compute_factors(cm):
    n_s,n_d=cm.shape
    rev=np.full((n_s,n_d),np.nan); mom=np.full((n_s,n_d),np.nan); lim=np.zeros((n_s,n_d))
    for di in range(10,n_d): rev[:,di]=-(cm[:,di]/cm[:,di-10]-1)
    for di in range(130,n_d): mom[:,di]=cm[:,di-20]/cm[:,di-130]-1
    for di in range(1,n_d):
        r=cm[:,di]/cm[:,di-1]-1
        lim[:,di]=np.where(r>=0.095,1,np.where(r<=-0.095,-1,0))
    return rev, mom, lim


def get_monthly_dates(all_d):
    md=[]; seen=set()
    for di in range(len(all_d)-1,-1,-1):
        m=all_d[di][:7]
        if m not in seen: md.append(di); seen.add(m)
    return sorted(md)


def backtest(cm, mat, md, label=""):
    n_s=cm.shape[0]; eq=1.0; pos=np.zeros(n_s); rets=[]; nt=0
    for di in range(max(130,md[0]), len(all_d)):
        if di in md:
            col=mat[:,di]; m=~np.isnan(col)
            if m.sum()>=20:
                si=np.argsort(col[m]); ai=np.where(m)[0][si]
                npick=max(1,m.sum()//10); new=np.zeros(n_s)
                for j in range(npick):
                    new[ai[-(j+1)]]=1.0/npick
                    new[ai[j]]=-1.0/npick
                eq-=np.sum(np.abs(new-pos))*0.0015; pos=new; nt+=1
        used=np.where(np.abs(pos)>0)[0]
        if len(used)==0: rets.append(0.0); continue
        r=np.nansum(pos[used]*(cm[used,di]/cm[used,di-1]-1))/len(used)
        rets.append(r); eq*=(1+r)
    tr=eq-1; yrs=len(rets)/245
    ann=(1+tr)**(1/yrs)-1 if yrs>0 else 0
    dr=np.array(rets); sh=np.mean(dr)/np.std(dr)*np.sqrt(245) if np.std(dr)>1e-10 else 0
    ec=np.cumprod(1+dr); pk=np.maximum.accumulate(ec); dd=ec/pk-1; mdd=np.min(dd)*100
    ca=ann/(abs(mdd)/100) if mdd<-0.1 else 0
    return {"label":label,"ann":round(ann*100,1),"sharpe":round(sh,3),
            "mdd":round(mdd,1),"calmar":round(ca,2),"total":round(tr*100,1)}


def multi_factor_bt(cm, rev, mom, lim, md):
    """多因子等权: 月度Z-score平均"""
    n_s,n_d=cm.shape; eq=1.0; pos=np.zeros(n_s); rets=[]; nt=0
    for di in range(max(130,md[0]), n_d):
        if di in md:
            combo=np.zeros(n_s)
            for mat in [rev,mom,lim]:
                col=mat[:,di]; m=~np.isnan(col)
                if m.sum()<20: continue
                z=(col[m]-np.nanmean(col))/max(np.nanstd(col),1e-10)
                combo[m]+=z
            combo/=3
            # 只有有效值
            m=combo!=0
            if m.sum()>=20:
                si=np.argsort(combo[m]); ai=np.where(m)[0][si]
                npick=max(1,m.sum()//10); new=np.zeros(n_s)
                for j in range(npick):
                    new[ai[-(j+1)]]=1.0/npick
                    new[ai[j]]=-1.0/npick
                eq-=np.sum(np.abs(new-pos))*0.0015; pos=new; nt+=1
        used=np.where(np.abs(pos)>0)[0]
        if len(used)==0: rets.append(0.0); continue
        r=np.nansum(pos[used]*(cm[used,di]/cm[used,di-1]-1))/len(used)
        rets.append(r); eq*=(1+r)
    tr=eq-1; yrs=len(rets)/245
    ann=(1+tr)**(1/yrs)-1 if yrs>0 else 0
    dr=np.array(rets); sh=np.mean(dr)/np.std(dr)*np.sqrt(245) if np.std(dr)>1e-10 else 0
    ec=np.cumprod(1+dr); pk=np.maximum.accumulate(ec); dd=ec/pk-1; mdd=np.min(dd)*100
    ca=ann/(abs(mdd)/100) if mdd<-0.1 else 0
    return {"label":"多因子等权","ann":round(ann*100,1),"sharpe":round(sh,3),
            "mdd":round(mdd,1),"calmar":round(ca,2),"total":round(tr*100,1)}


if __name__=="__main__":
    print("="*70)
    print("  新因子验证 v4 — 月度调仓多空")
    t0=time.time()

    print("\n[1/3] Loading...")
    stocks=load(5000); all_d,d2i=build_date_index(stocks)
    cm=build_close_matrix(stocks,d2i,all_d)
    n_s,n_d=cm.shape; print(f"  {n_s}x{n_d} in {time.time()-t0:.0f}s")

    print("\n[2/3] Factors...")
    rev,mom,lim=compute_factors(cm)
    md=get_monthly_dates(all_d)
    print(f"  {len(md)} monthly dates, first={all_d[md[0]]}")

    print("\n[3/3] Backtesting...")
    res=[]
    for mat,name in [(rev,"短期反转(2周)"),(mom,"截面动量(6月)"),(lim,"涨跌停动量")]:
        r=backtest(cm,mat,md,name); res.append(r)
        print(f"  {name}: {r['ann']:.1f}% sharpe={r['sharpe']:.2f} calmar={r['calmar']:.2f}")
    r=multi_factor_bt(cm,rev,mom,lim,md); res.append(r)
    print(f"  多因子等权: {r['ann']:.1f}% sharpe={r['sharpe']:.2f} calmar={r['calmar']:.2f}")

    # BH
    bh_r=np.mean([cm[si,-1]/cm[si,0]-1 for si in range(n_s) if not np.isnan(cm[si,-1])])
    yrs=n_d/245; bh_ann=(1+bh_r)**(1/yrs)-1
    print(f"  BH(等权): {bh_ann*100:.1f}%")
    print(f"  MA60/1%(前期个股测试): -3.7%")

    print("\n"+"="*70)
    print("  最终结果")
    print("="*70)
    print(f"  {'因子':<16} {'年化':>7} {'夏普':>7} {'回撤':>7} {'Calmar':>7}")
    print("  "+"-"*50)
    for r in sorted(res, key=lambda x: -x["sharpe"]):
        print(f"  {r['label']:<16} {r['ann']:>6.1f}% {r['sharpe']:>6.2f} {-r['mdd']:>5.0f}% {r['calmar']:>6.2f}")
    print(f"  {'买入持有(等权)':<16} {bh_ann*100:>6.1f}%")
    print(f"  {'MA60/1%(前期)':<16} {'-3.7%':>7}")
    print(f"\n  总耗时: {time.time()-t0:.0f}s")

    json.dump({"results":res}, open(OUT/"new_factors_final.json","w"), ensure_ascii=False, indent=2)
    print(f"\n  结果: {OUT/'new_factors_final.json'}")
