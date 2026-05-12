#!/usr/bin/env python3
"""
新因子验证 v3 — 预计算+批量回测, 高效处理5000只

方法:
1. 对每只股票, 预计算每日因子值
2. 每月末截面排序, 做多Top10%/做空Bottom10%
3. 等权持有1月, 计算超额收益
4. 汇总为净值曲线

执行: timeout 600 .venv/bin/python3 validate_new_factors_v3.py
"""
import sys, json, struct, warnings, time
from pathlib import Path
from datetime import datetime
from collections import defaultdict

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
OUT = Path("output/validate_wyckoff"); OUT.mkdir(parents=True, exist_ok=True)
TDXDIR = "/home/james/.local/share/tdxcfv/drive_c/tc/vipdoc"
CB = 0.0015


def rd(market, code):
    fp = Path(TDXDIR)/market/"lday"/f"{market}{code}.day"
    if not fp.exists(): return None
    d=fp.read_bytes(); n=len(d)//32; r=[]
    for i in range(n):
        x=d[i*32:(i+1)*32]
        if len(x)<32: continue
        try: dt,o,h,l,c,_,v,_=struct.unpack('<IIIIIfII',x)
        except: continue
        y,m_,d_=dt//10000,(dt%10000)//100,dt%100
        if y<1990 or y>2030: continue
        r.append({"date":f"{y}-{m_:02d}-{d_:02d}","close":c/10000,"volume":int(v)})
    if not r: return None
    df=pd.DataFrame(r); df["date"]=pd.to_datetime(df["date"])
    return df.sort_values("date").reset_index(drop=True)


print_h=lambda t: print(f"\n{'='*70}\n  {t}\n{'='*70}")

# ═══════════════════════════════════════════════
#  加载
# ═══════════════════════════════════════════════

print_h("新因子验证 v3 — 月度调仓多空")
t0=time.time()

sl=pd.read_csv("data/stock_list.csv",dtype={"code":str})
all_stocks=[]; all_codes=[]
for _,r in sl.iterrows():
    c=r["code"]; m=r["market"].lower()
    if not c.isdigit() or len(c)!=6: continue
    if m=="sh" and not c.startswith("6"): continue
    if m=="sz" and not (c.startswith("0") or c.startswith("3")): continue
    df=rd(m,c)
    if df is None: continue
    df=df[(df["date"]>="2014-10-17")&(df["date"]<="2026-05-11")].reset_index(drop=True)
    if len(df)<252: continue
    all_stocks.append({"code":c,"name":r["name"],"df":df})
    all_codes.append(c)

print(f"[1/3] {len(all_stocks)} stocks in {time.time()-t0:.0f}s")

# ═══════════════════════════════════════════════
#  因子计算 (向量化)
# ═══════════════════════════════════════════════

print("\n[2/3] Computing factors...")
all_dates = sorted(set(str(d)[:10] for s in all_stocks for d in s["df"]["date"]))

# 构建统一日期索引
date_to_idx = {d:i for i,d in enumerate(all_dates)}
n_dates = len(all_dates)

# 预分配因子矩阵: [n_stocks, n_dates]
n_stocks = len(all_stocks)
factor_matrices = {}

def compute_factor_vectorized(fn, name):
    """向量化因子计算"""
    mat = np.full((n_stocks, n_dates), np.nan)
    for si, s in enumerate(all_stocks):
        c = s["df"]["close"].values
        fv = fn(c)
        dates = s["df"]["date"].astype(str).str[:10].values
        for i,d in enumerate(dates):
            di = date_to_idx[d]
            mat[si, di] = fv[i]
    return mat

# 因子1: 短期反转 (过去10天收益的相反数)
def f_reversal(c):
    n=len(c); f=np.full(n,np.nan)
    for i in range(10,n): f[i]=-(c[i]/c[i-10]-1)
    return f

# 因子2: 截面动量 (过去6月skip1月)
def f_momentum(c):
    n=len(c); f=np.full(n,np.nan)
    for i in range(130,n): f[i]=c[i-20]/c[i-130]-1
    return f

# 因子3: 特质波动率
def f_ivol(c):
    n=len(c); f=np.full(n,np.nan)
    for i in range(25,n):
        f[i]=-np.std([c[j]/c[j-1]-1 for j in range(i-24,i+1)])
    return f

# 因子4: 涨跌停动量
def f_limit(c):
    n=len(c); f=np.zeros(n)
    for i in range(1,n):
        r=c[i]/c[i-1]-1
        if r>=0.095: f[i]=1
        elif r<=-0.095: f[i]=-1
    return f

# 因子5: 多因子等权 (Z-score平均)

t1=time.time()
for name, fn in [("短期反转",f_reversal),("截面动量",f_momentum),("特质波动率",f_ivol),("涨跌停动量",f_limit)]:
    factor_matrices[name] = compute_factor_vectorized(fn, name)
    print(f"  {name}: {time.time()-t1:.0f}s"); t1=time.time()

# 多因子等权: 每日期截面Z-score的平均
print("  多因子等权: ", end="")
combo = np.zeros((n_stocks, n_dates))
for name in ["短期反转","截面动量","特质波动率","涨跌停动量"]:
    mat = factor_matrices[name]
    # 每日截面Z-score
    for di in range(n_dates):
        col = mat[:, di]
        mask = ~np.isnan(col)
        if mask.sum() < 10: continue
        mean_v, std_v = np.nanmean(col), np.nanstd(col)
        if std_v > 0:
            combo[mask, di] += (col[mask] - mean_v) / std_v
combo /= 4
factor_matrices["多因子等权"] = combo
print(f"{time.time()-t1:.0f}s")

# ═══════════════════════════════════════════════
#  回测
# ═══════════════════════════════════════════════

print("\n[3/3] Backtesting...")

def backtest_factor(fmat, label):
    """月度调仓多空回测"""
    n_stk, n_d = fmat.shape
    eq = 1.0; pos = np.zeros(n_stk)

    # 找每月最后一个交易日
    months = []; cur_m = ""
    for di in range(n_d-1, -1, -1):
        m = all_dates[di][:7]
        if m != cur_m: months.append(di); cur_m = m
    months = months[::-1]  # 升序

    daily_rets = []
    for di in range(1, n_d):
        is_rebal = di in months

        if is_rebal:
            # 调仓
            vals = fmat[:, di]
            mask = ~np.isnan(vals)
            n_valid = mask.sum()
            if n_valid >= 20:
                sorted_idx = np.argsort(vals[mask])
                actual_idx = np.where(mask)[0][sorted_idx]
                n_pick = max(1, n_valid // 10)
                new_pos = np.zeros(n_stk)
                for j in range(n_pick):
                    new_pos[actual_idx[j]] = -1.0 / n_pick  # short
                    new_pos[actual_idx[-(j+1)]] = 1.0 / n_pick  # long
                # 成本
                chg = np.sum(np.abs(new_pos - pos))
                eq -= chg * CB
                pos = new_pos

        # 计算当日收益
        used = np.where(np.abs(pos) > 0)[0]
        if len(used) == 0:
            daily_rets.append(0.0)
            continue

        total_ret = 0.0
        for si in used:
            # 找第si只股票当日收盘
            s = all_stocks[si]
            dt = all_dates[di]
            match = s["df"]["date"].astype(str).str[:10] == dt
            idx = match.values.argmax() if match.any() else -1
            if idx <= 0: continue
            ret = s["df"].iloc[idx]["close"] / s["df"].iloc[idx-1]["close"] - 1
            total_ret += pos[si] * ret

        ret = total_ret / len(used)
        eq *= (1 + ret)
        daily_rets.append((eq, ret))

    # 统计
    vals = [(e,r) for e,r in daily_rets]
    final_eq = vals[-1][0] if vals else 1.0
    total_ret = final_eq - 1
    yrs = len(vals) / 245
    ann = (1+total_ret)**(1/yrs)-1 if yrs>0 else 0
    dr = np.array([r for _,r in vals])
    sh = np.mean(dr)/np.std(dr)*np.sqrt(245) if np.std(dr)>1e-10 else 0
    eq_c = np.array([e for e,_ in vals])
    pk = np.maximum.accumulate(eq_c)
    dd = eq_c/pk-1
    mdd = np.min(dd)*100
    ca = ann/(abs(mdd)/100) if mdd < -0.1 else 0
    return {"label":label,"ann":round(ann*100,1),"sharpe":round(sh,3),
            "mdd":round(mdd,1),"calmar":round(ca,2),"total":round(total_ret*100,1)}

results = []
for name, fmat in factor_matrices.items():
    t1 = time.time()
    r = backtest_factor(fmat, name)
    results.append(r)
    print(f"  {name:<12} ar={r['ann']:>5.1f}% sharpe={r['sharpe']:>5.2f} "
          f"mdd={-r['mdd']:>4.0f}% calmar={r['calmar']:>5.2f} {time.time()-t1:.0f}s")

# BH
bh_rets = []
for s in all_stocks:
    c=s["df"]["close"].values; bh_rets.append(c[-1]/c[0]-1)
yrs2 = len(all_stocks[0]["df"]) / 245 if all_stocks else 1
bh_ann = (1+np.mean(bh_rets))**(1/yrs2)-1
print(f"  {'买入持有(等权)':<12} ar={bh_ann*100:>5.1f}%")

# 输出
print_h("最终结果")
print(f"  {'因子':<14} {'年化':>7} {'夏普':>7} {'回撤':>6} {'Calmar':>7}")
print("  " + "-" * 45)
for r in sorted(results, key=lambda x: -x["sharpe"]):
    print(f"  {r['label']:<14} {r['ann']:>6.1f}% {r['sharpe']:>6.2f} {-r['mdd']:>5.0f}% {r['calmar']:>6.2f}")
print(f"  {'MA60/1%(前期)':<14} {'-3.7%':>7}")

out={"results":results}
(OUT/"new_factors_v3.json").write_text(json.dumps(out,ensure_ascii=False,indent=2,default=str))
print(f"\n  结果: {OUT/'new_factors_v3.json'}")
print(f"  总耗时: {time.time()-t0:.0f}s")
