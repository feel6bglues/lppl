#!/usr/bin/env python3
"""
新因子快速验证 v2 — 月度调仓+预计算, 高效处理5000只股票

方法:
1. 每月最后一个交易日计算因子值
2. 截面标准化(Z-score)
3. 做多Top10%/做空Bottom10%
4. 等权持有1个月

执行: .venv/bin/python3 validate_new_factors_v2.py
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
CB = 0.0015  # 单边成本(含印花税佣金滑点)


def read_tdx(market, code):
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
                  "low":l/10000,"close":c/10000,"volume":int(v)})
    if not r: return None
    df = pd.DataFrame(r); df["date"] = pd.to_datetime(df["date"])
    return df.sort_values("date").reset_index(drop=True)


def load_all_data():
    """加载所有股票数据并返回统一DataFrame字典"""
    sl = pd.read_csv("data/stock_list.csv", dtype={"code":str})
    stocks = []
    for _,r in sl.iterrows():
        c=r["code"]; m=r["market"].lower()
        if not c.isdigit() or len(c)!=6: continue
        if m=="sh" and not c.startswith("6"): continue
        if m=="sz" and not (c.startswith("0") or c.startswith("3")): continue
        df=read_tdx(m,c)
        if df is None: continue
        df=df[(df["date"]>="2014-10-17")&(df["date"]<="2026-05-11")].reset_index(drop=True)
        if len(df)<252: continue
        stocks.append({"code":c,"name":r["name"],"df":df})
    return stocks


# ═══════════════════════════════════════════════
#  因子计算函数 — 返回每日因子值数组
# ═══════════════════════════════════════════════

def compute_factor_reversal(df):
    """短期反转因子: 过去2周收益的相反数"""
    c=df["close"].values; n=len(c); f=np.full(n,np.nan)
    for i in range(10, n): f[i]=-(c[i]/c[i-10]-1)
    return f

def compute_factor_limit_momentum(df):
    """涨跌停动量: 涨停+1, 跌停-1"""
    c=df["close"].values; n=len(c); f=np.zeros(n)
    for i in range(1, n):
        r=c[i]/c[i-1]-1
        if r>=0.095: f[i]=1
        elif r<=-0.095: f[i]=-1
    return f

def compute_factor_momentum(df):
    """截面动量: 过去6月收益(跳过1月)"""
    c=df["close"].values; n=len(c); f=np.full(n,np.nan)
    for i in range(130, n): f[i]=c[i-20]/c[i-130]-1
    return f

def compute_factor_ivol(df):
    """特质波动率(负): 过去1月日收益波动率的相反数"""
    c=df["close"].values; n=len(c); f=np.full(n,np.nan)
    for i in range(25, n):
        rr=np.array([c[j]/c[j-1]-1 for j in range(i-24,i+1)])
        f[i]=-np.std(rr)
    return f

def compute_factor_amihud(df):
    """Amihud非流动性"""
    c=df["close"].values; v=df["volume"].values; n=len(c); f=np.full(n,np.nan)
    for i in range(25, n):
        ill=0; cnt=0
        for j in range(i-24,i+1):
            r=abs(c[j]/c[j-1]-1); vol=c[j]*v[j]
            if vol>0: ill+=r/vol; cnt+=1
        f[i]=ill/cnt if cnt>0 else np.nan
    return f


FACTORS = {
    "短期反转(2周)": compute_factor_reversal,
    "涨跌停动量": compute_factor_limit_momentum,
    "截面动量(6月)": compute_factor_momentum,
    "特质波动率": compute_factor_ivol,
    "非流动性(Amihud)": compute_factor_amihud,
}


# ═══════════════════════════════════════════════
#  回测
# ═══════════════════════════════════════════════

def monthly_backtest(stocks, factor_values, label):
    """
    月度调仓多空回测
    
    Args:
        stocks: [{code, name}]
        factor_values: [{date, code, value}] 预计算因子值列表
        label: 策略名称
    """
    # 按日期分组因子值
    date_groups = defaultdict(dict)
    for fv in factor_values:
        date_groups[fv["date"]][fv["code"]] = fv["value"]
    
    all_dates = sorted(date_groups.keys())
    
    # 找每月最后一个交易日
    monthly_dates = []
    for i,d in enumerate(all_dates):
        dt = datetime.strptime(d, "%Y-%m-%d")
        if i+1 >= len(all_dates) or datetime.strptime(all_dates[i+1], "%Y-%m-%d").month != dt.month:
            monthly_dates.append(d)
    
    # 构建日期→因子值DataFrame加速查找
    date_factor_map = {}
    for d in all_dates:
        codes_vals = [(c,v) for c,v in date_groups[d].items() if not np.isnan(v)]
        if len(codes_vals) < 100: continue
        codes_vals.sort(key=lambda x: x[1])
        
        # 标准化: 构建z-score
        vals = np.array([x[1] for x in codes_vals])
        mean_v, std_v = np.mean(vals), np.std(vals)
        if std_v > 0:
            z_codes = {x[0]:(x[1]-mean_v)/std_v for x in codes_vals}
        else:
            z_codes = {x[0]:0.0 for x in codes_vals}
        date_factor_map[d] = z_codes
    
    # 回测
    equity = 1.0; eq_curve = []; position = {}; n_trades = 0
    pos_weights = {}
    
    for i, date in enumerate(all_dates):
        is_monthly = date in monthly_dates
        factor_map = date_factor_map.get(date, {})
        
        if is_monthly and factor_map:
            # 月度调仓
            codes_sorted = sorted(factor_map.items(), key=lambda x: x[1])
            n_stk = max(1, len(codes_sorted) // 10)
            
            shorts = set(x[0] for x in codes_sorted[:n_stk])
            longs = set(x[0] for x in codes_sorted[-n_stk:])
            
            n_l, n_s = len(longs), len(shorts)
            new_pos = {}
            for c in longs: new_pos[c] = 1.0/n_l
            for c in shorts: new_pos[c] = -1.0/n_s
            
            # 调仓成本
            cost = 0.0
            for c in set(list(position.keys()) + list(new_pos.keys())):
                chg = abs(new_pos.get(c,0.0)-position.get(c,0.0))
                if chg > 0.001: cost += chg * CB
            equity -= cost
            
            position = new_pos
            n_trades += 1
        
        # 计算当日收益
        total_ret = 0.0; n_active = max(1, len(position))
        for c, w in position.items():
            if i+1 >= len(all_dates): continue
            # 找股票当日数据
            s = next((s for s in stocks if s["code"]==c), None)
            if s is None or c not in factor_map: 
                n_active -= 1
                continue
            df = s["df"]
            # 假设dates按date列顺序
            date_idx = df[df["date"].astype(str).str[:10]==date].index
            if len(date_idx) == 0: n_active -= 1; continue
            idx = date_idx[0]
            if idx == 0: n_active -= 1; continue
            ret = df.iloc[idx]["close"]/df.iloc[idx-1]["close"]-1
            total_ret += w * ret
        
        if n_active > 0:
            ret = total_ret / n_active
        else:
            ret = 0.0
        
        equity *= (1 + ret)
        eq_curve.append({"date":date,"equity":float(equity),"ret":float(ret)})
    
    # 统计
    total_ret = equity - 1
    yrs = len(eq_curve) / 245
    ann = (1+total_ret)**(1/yrs)-1 if yrs > 0 else 0
    dr = np.array([e["ret"] for e in eq_curve])
    sh = np.mean(dr)/np.std(dr)*np.sqrt(12) if np.std(dr)>1e-10 else 0  # 月度夏普*√12=年化
    eq_a = np.array([e["equity"] for e in eq_curve])
    pk = np.maximum.accumulate(eq_a); dd = eq_a/pk-1; mdd=np.min(dd)*100
    ca = ann/(abs(mdd)/100) if mdd<-0.1 else 0
    
    return {"label":label,"total":round(total_ret*100,1),"ann":round(ann*100,1),
            "sharpe":round(sh,3),"mdd":round(mdd,1),"calmar":round(ca,2),"ntrades":n_trades}


# ═══════════════════════════════════════════════
#  主流程
# ═══════════════════════════════════════════════

def main():
    print_h("新因子验证v2 — 月度调仓多空对冲")
    print(f"  执行: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    
    t0 = datetime.now()
    print("\n[1/4] 加载数据...")
    stocks = load_all_data()
    print(f"  {len(stocks)}只股票, {datetime.now()-t0}")
    
    print("\n[2/4] 计算因子值...")
    all_factor_data = {}
    for fname, fn in FACTORS.items():
        t1 = datetime.now(); data = []
        for s in stocks:
            fv = fn(s["df"])
            dates = s["df"]["date"].astype(str).str[:10].values
            for i, d in enumerate(dates):
                if not np.isnan(fv[i]):
                    data.append({"date":d,"code":s["code"],"value":float(fv[i])})
        all_factor_data[fname] = data
        print(f"  {fname:<16} {len(data):>8}条 {datetime.now()-t1}")
    
    print(f"\n[3/4] 运行回测...")
    results = []
    for fname, fdata in all_factor_data.items():
        t1 = datetime.now()
        r = monthly_backtest(stocks, fdata, fname)
        results.append(r)
        print(f"  {fname:<16} ar={r['ann']:.1f}% sharpe={r['sharpe']:.2f} mdd={-r['mdd']:.0f}% {datetime.now()-t1}")

    # 多因子组合: 简单平均
    t1 = datetime.now()
    combo_data = []
    # 对每个月合并多因子
    combined_dates = defaultdict(lambda: defaultdict(list))
    for fname, fdata in all_factor_data.items():
        for fv in fdata:
            combined_dates[fv["date"]][fv["code"]].append(fv["value"])
    for d, codes in combined_dates.items():
        for c, vals in codes.items():
            combo_data.append({"date":d,"code":c,"value":np.mean(vals)})
    r_combo = monthly_backtest(stocks, combo_data, "多因子等权")
    results.append(r_combo)
    print(f"  多因子等权            ar={r_combo['ann']:.1f}% sharpe={r_combo['sharpe']:.2f} mdd={-r_combo['mdd']:.0f}% {datetime.now()-t1}")
    
    print_h("[4/4] 结果")
    print(f"  {'因子':<18} {'年化':>7} {'夏普':>7} {'回撤':>6} {'Calmar':>7} {'总收益':>8} {'调仓':>5}")
    print("  " + "-" * 60)
    
    # BH基准
    bh_ret = np.mean([s["df"]["close"].values[-1]/s["df"]["close"].values[0]-1 for s in stocks])
    yrs = len(stocks[0]["df"])/245 if stocks else 1
    bh_ann = (1+bh_ret)**(1/yrs)-1 if yrs>0 else 0
    print(f"  {'等权买入持有':<18} {bh_ann*100:>6.1f}%")
    print(f"  {'MA60/1%(前期测试)':<18} {'-3.7%':>7} {'-0.01':>7} {'':>6}")
    
    for r in sorted(results, key=lambda x: x["sharpe"], reverse=True):
        print(f"  {r['label']:<18} {r['ann']:>6.1f}% {r['sharpe']:>6.2f} "
              f"{-r['mdd']:>5.0f}% {r['calmar']:>6.2f} {r['total']:>7.1f}% {r['ntrades']:>5}")
    
    print(f"\n  总耗时: {datetime.now()-t0}")
    
    # 保存
    out = {"config":{"cost_single":CB},"results":results}
    (OUT/"new_factors.json").write_text(json.dumps(out,ensure_ascii=False,indent=2))
    print(f"\n  结果: {OUT/'new_factors.json'}")


def print_h(t): print(f"\n{'='*70}\n  {t}\n{'='*70}")

if __name__=="__main__":
    main()
