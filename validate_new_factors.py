#!/usr/bin/env python3
"""
新因子快速验证 — 短期反转 + 涨跌停动量 + 截面多因子

基于5114只个股TDX数据, 周度调仓, 多空对冲, 扣除交易成本

执行: .venv/bin/python3 validate_new_factors.py
结果: output/validate_wyckoff/new_factors.json
"""
import sys, os, json, struct, warnings
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
warnings.filterwarnings("ignore")

OUT = Path("output/validate_wyckoff"); OUT.mkdir(parents=True, exist_ok=True)
TDXDIR = "/home/james/.local/share/tdxcfv/drive_c/tc/vipdoc"
COST = 0.0025  # 双边成本 0.25%
CB = 0.00075; CS = 0.00175


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
        r.append({"date":f"{y}-{m_:02d}-{d_:02d}","open":float(o/10000),"high":float(h/10000),
                  "low":float(l/10000),"close":float(c/10000),"volume":int(v)})
    if not r: return None
    df = pd.DataFrame(r); df["date"] = pd.to_datetime(df["date"])
    return df.sort_values("date").reset_index(drop=True)


def load_all_stocks():
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
        stocks.append({"code":c,"market":m,"name":r["name"],"df":df})
    return stocks


def compute_factor(zscore1, zscore2=None, zscore3=None):
    """等权合成多因子Z-score"""
    if zscore2 is None: return zscore1
    n = np.sum(~np.isnan(zscore1) for d in [zscore1, zscore2, zscore3] if d is not None) if zscore3 else 2
    s = np.nan_to_num(zscore1, 0)
    if zscore2 is not None: s += np.nan_to_num(zscore2, 0)
    if zscore3 is not None: s += np.nan_to_num(zscore3, 0)
    return s / n


def weekly_backtest(stocks, factor_fn, label, rebalance_weekly=True):
    """
    周度调仓多空回测
    
    Args:
        stocks: [{code, df, ...}] 
        factor_fn: (df, date_idx) → 该股票在当前周的因子值
        rebalance_weekly: 每周五调仓
    Returns:
        策略净值曲线, 统计指标
    """
    # 构建完整日期序列
    all_dates = set()
    for s in stocks:
        all_dates.update(s["df"]["date"].dt.date.unique())
    all_dates = sorted(all_dates)
    
    # 周度调仓日 (每周最后一个交易日)
    rebalance_dates = []
    for i,d in enumerate(all_dates):
        # 找到每周最后一个交易日 (周五或最后一个)
        dow = d.weekday()
        if dow >= 4 or (i+1<len(all_dates) and all_dates[i+1].weekday() < dow):
            rebalance_dates.append(d)
    
    dates_set = set(all_dates)
    daily_values = []  # (date, portfolio_return)
    
    # 初始化持仓
    position = {}  # code → weight (-1 to 1)
    
    for di, date in enumerate(all_dates):
        date = all_dates[di]
        
        # 检查是否是调仓日
        is_rebalance = date in rebalance_dates
        
        if is_rebalance:
            # 计算所有股票当前因子值
            factor_values = []
            for s in stocks:
                df = s["df"]
                # 找到日期索引
                mask = df["date"].dt.date == date
                if not mask.any(): continue
                idx = df[mask].index[0]
                if idx < 60: continue  # 需要至少60个数据点
                
                fv = factor_fn(df, idx)
                if fv is None or np.isnan(fv): continue
                factor_values.append((s["code"], fv))
            
            if len(factor_values) < 100:  # 至少100只股票
                continue
            
            # 排序并选多空各10%
            factor_values.sort(key=lambda x: x[1])
            n_stocks = max(1, len(factor_values) // 10)
            shorts = set(x[0] for x in factor_values[:n_stocks])
            longs = set(x[0] for x in factor_values[-n_stocks:])
            
            # 建新仓位: 多头+1/n, 空头-1/n
            n_long = len(longs); n_short = len(shorts)
            new_pos = {}
            for c in longs: new_pos[c] = 1.0 / n_long
            for c in shorts: new_pos[c] = -1.0 / n_short
            
            # 计算调仓成本
            cost = 0.0
            for c in set(list(position.keys()) + list(new_pos.keys())):
                old_w = position.get(c, 0.0)
                new_w = new_pos.get(c, 0.0)
                chg = abs(new_w - old_w)
                if chg > 0.001:
                    cost += chg * CB
            
            # 更新持仓
            position = new_pos
            daily_values.append((date, 0.0, cost))  # 当日收益为0, 扣除调仓成本
            continue
        
        # 非调仓日: 计算持仓收益
        total_ret = 0.0
        for c, w in position.items():
            # 找到该股票当日数据
            s = next((s for s in stocks if s["code"] == c), None)
            if s is None: continue
            df = s["df"]
            mask = df["date"].dt.date == date
            if not mask.any(): continue
            idx = df[mask].index[0]
            if idx == 0: continue
            ret = df.iloc[idx]["close"] / df.iloc[idx-1]["close"] - 1
            total_ret += w * ret
        
        if position:
            daily_values.append((date, total_ret / len(position) if position else 0.0, 0.0))
    
    # 计算净值
    equity = 1.0; eq_curve = []
    for date, ret, cost in daily_values:
        equity *= (1 + ret)
        equity -= cost
        eq_curve.append({"date":str(date), "equity":float(equity), "ret":float(ret), "cost":float(cost)})
    
    total_ret = equity - 1
    yrs = len(daily_values) / 245
    ann = (1+total_ret)**(1/yrs)-1 if yrs > 0 else 0
    dr = np.array([e["ret"] for e in eq_curve])
    sh = np.mean(dr)/np.std(dr)*np.sqrt(52) if np.std(dr) > 1e-10 else 0  # 周度夏普
    pk = np.maximum.accumulate([e["equity"] for e in eq_curve])
    dd = np.array([e["equity"] for e in eq_curve]) / pk - 1
    mdd = np.min(dd) * 100
    ca = ann/(abs(mdd)/100) if mdd < -0.1 else 0
    
    return {
        "label": label,
        "total_return": round(total_ret*100, 1),
        "annual_return": round(ann*100, 1),
        "sharpe": round(sh, 3),
        "max_drawdown": round(mdd, 1),
        "calmar": round(ca, 2),
        "n_trades": len(daily_values),
    }, eq_curve


# ═══════════════════════════════════════════════
#  因子函数
# ═══════════════════════════════════════════════

def factor_short_term_reversal(df, idx):
    """短期反转: 过去2周涨幅越大的股票, 因子值越低(预期反转下跌)"""
    if idx < 15: return None
    ret_2w = df.iloc[idx]["close"] / df.iloc[idx-10]["close"] - 1 if idx >= 10 else 0
    return -ret_2w  # 反转: 过去涨→因子低→空头; 过去跌→因子高→多头


def factor_limit_up_momentum(df, idx):
    """涨跌停动量: 涨停后继续涨, 跌停后继续跌"""
    if idx < 1: return None
    # 计算昨日至今日涨跌幅
    ret = df.iloc[idx]["close"] / df.iloc[idx-1]["close"] - 1
    # 今日是否涨停/跌停 (A股10%限制)
    limit_up = ret >= 0.095  # 接近涨停
    limit_down = ret <= -0.095  # 接近跌停
    
    if limit_up: return 1.0  # 涨停→做多
    if limit_down: return -1.0  # 跌停→做空
    return 0.0  # 其他→中性


def factor_momentum_6m_skip_1m(df, idx):
    """截面动量: 过去6个月收益(跳过最近1个月)"""
    if idx < 130: return None
    ret_6m = df.iloc[idx-20]["close"] / df.iloc[idx-130]["close"] - 1  # skip 1 month
    return ret_6m


def factor_ivol(df, idx):
    """特质波动率: 过去1个月日收益标准差"""
    if idx < 25: return None
    rets = [df.iloc[j]["close"]/df.iloc[j-1]["close"]-1 for j in range(idx-24, idx+1)]
    return -np.std(rets)  # 低IVOL→高因子


def factor_amihud(df, idx):
    """Amihud非流动性: |收益|/成交额, 越高越非流动"""
    if idx < 25: return None
    illiq = 0.0; cnt = 0
    for j in range(idx-24, idx+1):
        ret = abs(df.iloc[j]["close"]/df.iloc[j-1]["close"]-1)
        vol = df.iloc[j]["volume"] * df.iloc[j]["close"]  # 成交额≈成交量×价格
        if vol > 0:
            illiq += ret / vol
            cnt += 1
    return illiq / cnt if cnt > 0 else None


def factor_combined_zscore(df, idx):
    """多因子等权合成"""
    f1 = factor_momentum_6m_skip_1m(df, idx)
    f2 = factor_short_term_reversal(df, idx)
    f3 = factor_ivol(df, idx)
    
    if f1 is None and f2 is None and f3 is None: return None
    
    # Z-score标准化 (用截面标准化, 但在个股上无法做, 用简单rank)
    # 这里直接返回原始值, 由backtest做截面排序
    vals = [v for v in [f1, f2, f3] if v is not None]
    return np.mean(vals)


# ═══════════════════════════════════════════════
#  主流程
# ═══════════════════════════════════════════════

def print_h(t): print(f"\n{'='*70}\n  {t}\n{'='*70}")
def print_s(t): print(f"\n{'-'*50}\n  {t}\n{'-'*50}")


def main():
    print_h("新因子大样本验证 — 周度调仓多空对冲")
    print(f"  执行: {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    print("\n[1/4] 加载数据...")
    stocks = load_all_stocks()
    print(f"  有效股票: {len(stocks)}只")

    print("\n[2/4] 运行因子回测...")
    results = {}
    
    # 因子列表
    factors = [
        ("短期反转(2周)", factor_short_term_reversal),
        ("涨跌停动量", factor_limit_up_momentum),
        ("截面动量(6M)", factor_momentum_6m_skip_1m),
        ("特质波动率", factor_ivol),
        ("多因子等权", factor_combined_zscore),
    ]
    
    for label, fn in factors:
        print(f"  运行: {label}...")
        res, curve = weekly_backtest(stocks, fn, label)
        results[label] = {"stats": res}
        # 保存明细略 (太大)
        print(f"    年化={res['annual_return']:.1f}% 夏普={res['sharpe']:.2f} "
              f"回撤={res['max_drawdown']:.1f}% Calmar={res['calmar']:.2f}")

    # ── 汇总 ──
    print_h("[3/4] 结果汇总")
    print(f"  {'因子':<20} {'年化':>7} {'夏普':>7} {'回撤':>7} {'Calmar':>7} {'总收益':>8}")
    print("  " + "-" * 60)
    
    # Benchmark: 买入持有 (等权)
    bh_rets = []
    for s in stocks:
        c = s["df"]["close"].values
        bh_rets.append(c[-1]/c[0]-1)
    bh_ann = (1+np.mean(bh_rets))**(245/len(stocks[0]["df"]))-1 if stocks else 0
    print(f"  {'等权买入持有':<20} {bh_ann*100:>6.1f}%")

    for label, r in results.items():
        s = r["stats"]
        print(f"  {label:<20} {s['annual_return']:>6.1f}% {s['sharpe']:>6.2f} "
              f"{-s['max_drawdown']:>5.0f}% {s['calmar']:>6.2f} {s['total_return']:>7.1f}%")

    print_h("[4/4] 分析结论")
    print(f"""
  1. 已测试因子表现对比:

     因子                   预期IR    实测年化    结论
     ─────────────────────────────────────────────
     短期反转(2周)          0.5-0.8   待定       {'✅ 可能有效' if any(r['stats']['annual_return']>5 for r in results.values()) else '❌ 无效'}
     涨跌停动量             0.6-1.0   待定       A股特有机制
     截面动量(6M)           0.3-0.5   待定       经典因子
     特质波动率             0.4-0.7   待定       低波异象
     多因子等权             0.6-1.0   待定       组合效应

  2. 与MA60/1%对比:
     MA60/1%(时间序列, 纯多): -3.7%年化
     新因子(截面, 多空):   待定

  3. 关键区别:
     - 横截面选股(新因子) vs 时间序列择时(MA60)
     - 多空对冲(新因子) vs 纯多头(MA60)
     - 周度调仓(新因子) vs 日频交易(MA60)
     - 截面动量 vs 时间序列MA: 完全不同的信号来源

  4. 如需继续:
     - 实现真正的截面标准化 (Z-score by date)
     - 加入IC/IR检验
     - 分层回测(decile portfolio)
     - 排除ST/新股/停牌影响
""")


if __name__ == "__main__":
    main()
