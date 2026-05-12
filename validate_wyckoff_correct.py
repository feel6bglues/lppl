#!/usr/bin/env python3
"""
正确Wyckoff + MA60/1%策略大样本验证

从 src/wyckoff/analyzer.py 提取原始Wyckoff相位检测规则:
- total_range_pct: 60日价格区间宽度
- relative_position: 价格在60日区间位置
- short_trend_pct: 近20日vs前20日均价变化
- is_in_trading_range: TR检测
- BC/SC降级: 用relative_position替代

执行: .venv/bin/python3 validate_wyckoff_correct.py
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
TDX_DIR = "/home/james/.local/share/tdxcfv/drive_c/tc/vipdoc"
STOCK_LIST = "data/stock_list.csv"
MA_P = 60; TH = 0.01; COST_B = 0.00075; COST_S = 0.00175
COMMON_START = "2014-10-17"; COMMON_END = "2026-05-11"

def print_h(t): print(f"\n{'='*70}\n  {t}\n{'='*70}")
def print_s(t): print(f"\n{'-'*50}\n  {t}\n{'-'*50}")

# ═══════════════════════════════════════════════════
#  1. TDX读取
# ═══════════════════════════════════════════════════════

def read_tdx(market, code):
    fp = Path(TDX_DIR) / market / "lday" / f"{market}{code}.day"
    if not fp.exists(): return None
    data = fp.read_bytes()
    n = len(data) // 32; recs = []
    for i in range(n):
        d = data[i*32:(i+1)*32]
        if len(d) < 32: continue
        try:
            dt, o, h, l, c, amt, vol, _ = struct.unpack('<IIIIIfII', d)
        except: continue
        y, m, d_ = dt//10000, (dt%10000)//100, dt%100
        if y < 1990 or y > 2030: continue
        recs.append({"date":f"{y}-{m:02d}-{d_:02d}", "open":o/10000, "high":h/10000,
                     "low":l/10000, "close":c/10000, "volume":vol})
    if not recs: return None
    df = pd.DataFrame(recs); df["date"] = pd.to_datetime(df["date"])
    return df.sort_values("date").reset_index(drop=True)

# ═══════════════════════════════════════════════════
#  2. 正确的Wyckoff相位 + MA60策略
# ═══════════════════════════════════════════════════════

def wyckoff_phase_and_signal(closes, highs, lows):
    """
    基于原始analyzer.py:785-903规则计算Wyckoff相位 + MA60信号
    (向量化优化版 v2 — 使用pandas rolling加速)
    """
    n = len(closes)
    ma_sig = np.zeros(n); wyk_sig = np.zeros(n)
    phases = np.full(n, "unknown", dtype=object)

    # ── 向量化计算所有指标 (使用pandas rolling) ──
    s = pd.Series(closes)
    h_s = pd.Series(highs)
    l_s = pd.Series(lows)

    ma = s.rolling(MA_P).mean().values
    ma5 = s.rolling(5).mean().values
    ma20_arr = s.rolling(20).mean().values
    lo60 = l_s.rolling(60).min().values
    hi60 = h_s.rolling(60).max().values

    # total_range_pct & relative_position
    tr_pct = np.full(n, np.nan); rel_pos = np.full(n, np.nan)
    mask = lo60 > 0
    tr_pct[mask] = (hi60[mask] - lo60[mask]) / lo60[mask]
    mask2 = hi60 > lo60
    rel_pos[mask2] = (closes[mask2] - lo60[mask2]) / (hi60[mask2] - lo60[mask2])

    # short_trend_pct: 近20日vs前20日均价
    ma20_avg = ma20_arr.copy()  # 20日均值
    short_trend = np.full(n, np.nan)
    for i in range(39, n):
        if ma20_avg[i-20] > 0:
            short_trend[i] = (ma20_avg[i] - ma20_avg[i-20]) / ma20_avg[i-20]

    # ── 逐日生成信号 ──
    for i in range(max(MA_P, 60), n):
        if np.isnan(ma[i]) or ma[i] <= 0: continue

        # MA60信号
        r = closes[i] / ma[i]
        base_pos = 0.85 if r > 1+TH else (0.0 if r < 1-TH else 0.50)

        # Wyckoff相位
        is_in_tr = (tr_pct[i] <= 0.20) and (abs(short_trend[i]) < 0.05) if not np.isnan(tr_pct[i]) else False

        if is_in_tr:
            prior = closes[i-40]/closes[i-80]-1 if (i >= 80 and closes[i-80] > 0) else 0
            if prior < -0.10:           phase = "accumulation"
            elif prior > 0.10:          phase = "distribution"
            elif rel_pos[i] <= 0.40:    phase = "accumulation"
            else:                       phase = "unknown"
        else:
            cp = closes[i]; m5 = ma5[i]; m20 = ma20_arr[i]; st = short_trend[i]; rp = rel_pos[i]
            if st >= 0.03 and ((cp > m20 and m5 >= m20) or (cp > m5 and rp >= 0.50)):
                phase = "markup"
            elif st >= 0.015 and cp > m20 and m5 >= m20*0.98 and rp >= 0.70:
                phase = "markup"
            elif st >= 0.05 and m5 >= m20 and cp >= m20*0.99 and rp >= 0.65:
                phase = "markup"
            elif st <= -0.03 and cp < m20:
                phase = "markdown"
            else:
                phase = "unknown"

        phases[i] = phase

        # Wyckoff增强
        wyk_pos = base_pos
        if phase == "markup" and base_pos > 0:
            wyk_pos = min(1.0, base_pos + 0.10)
        elif phase == "markdown" and base_pos < 0.85:
            wyk_pos = 0.0
        elif phase == "accumulation" and base_pos == 0.50:
            wyk_pos = 0.60
        elif phase == "distribution" and base_pos == 0.50:
            wyk_pos = 0.30

        ma_sig[i] = base_pos
        wyk_sig[i] = wyk_pos

    return ma_sig, wyk_sig, phases


def backtest(closes, signals):
    """正确回测: 今日信号→明日执行"""
    n = len(closes); eq = np.ones(n); pos = 0.0
    for i in range(1, n):
        ret = closes[i]/closes[i-1]-1
        eq[i] = eq[i-1] * (1 + ret * pos)
        target = min(max(signals[i], 0.0), 1.0) if signals[i] > 0.01 else 0.0
        chg = target - pos; cost = 0.0
        if abs(chg) > 0.001:
            cost = chg * COST_B if chg > 0 else abs(chg) * COST_S
        eq[i] -= cost; pos = target
    return eq


def metrics(eq, closes):
    n = len(eq); tr = eq[-1]/eq[0]-1; yrs = n/245
    ar = (1+tr)**(1/yrs)-1 if yrs > 0 else 0
    dr = np.array([eq[i]/eq[i-1]-1 for i in range(1, n)])
    sh = np.mean(dr)/np.std(dr)*np.sqrt(245) if np.std(dr) > 1e-10 else 0
    pk = np.maximum.accumulate(eq); mdd = np.min((eq-pk)/pk)*100
    ca = ar/(abs(mdd)/100) if mdd < -0.1 else 0
    bh_tr = closes[-1]/closes[0]-1
    bh_ar = (1+bh_tr)**(1/yrs)-1 if yrs > 0 else 0
    return {"ar":round(ar*100,1), "sharpe":round(sh,3), "mdd":round(mdd,1),
            "calmar":round(ca,2), "bh_ar":round(bh_ar*100,1),
            "excess":round((ar-bh_ar)*100,1)}


# ═══════════════════════════════════════════════════
#  3. 主流程
# ═══════════════════════════════════════════════════════

def main():
    print_h("正确Wyckoff + MA60/1% 大样本验证")
    print(f"  执行: {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    # ── 读取股票列表 ──
    sl = pd.read_csv(STOCK_LIST, dtype={"code": str})
    all_stocks = []
    for _, r in sl.iterrows():
        c = r["code"]; m = r["market"].lower()
        if not c.isdigit() or len(c) != 6: continue
        if m == "sh" and not c.startswith("6"): continue
        if m == "sz" and not (c.startswith("0") or c.startswith("3")): continue
        all_stocks.append({"code": c, "market": m, "name": r["name"], "sector": r["sector"]})
    print(f"\n[1/5] 股票列表: {len(all_stocks)}只")

    # ── 逐只处理 ──
    print(f"\n[2/5] 读取数据 & 计算Wyckoff相位 & 回测...")
    results = []; phase_counter = defaultdict(int); phase_rets = defaultdict(list)
    skipped = 0; start_t = datetime.now()

    # 抽样500只做相位收益分析
    import random
    sample_codes = set(random.sample([s["code"] for s in all_stocks], min(500, len(all_stocks))))

    for idx, stk in enumerate(all_stocks):
        if (idx+1) % 500 == 0:
            elap = (datetime.now()-start_t).total_seconds()
            print(f"  {idx+1}/{len(all_stocks)} ({len(results)}ok skip={skipped} {elap:.0f}s)")

        df = read_tdx(stk["market"], stk["code"])
        if df is None: skipped += 1; continue
        df = df[(df["date"]>=COMMON_START)&(df["date"]<=COMMON_END)].reset_index(drop=True)
        if len(df) < 252: skipped += 1; continue

        c = df["close"].values; h = df["high"].values; l = df["low"].values
        n = len(c); yrs = n/245

        ma_sig, wyk_sig, phases = wyckoff_phase_and_signal(c, h, l)
        for p in np.unique(phases): phase_counter[p] += int(np.sum(phases == p))

        # 抽样500只收集相位收益
        if stk["code"] in sample_codes:
            for i in range(60, n):
                ret = c[i]/c[i-1]-1 if i>0 else 0
                phase_rets[phases[i]].append(ret)

        eq_ma = backtest(c, ma_sig)
        eq_wyk = backtest(c, wyk_sig)
        m_ma = metrics(eq_ma, c)
        m_wyk = metrics(eq_wyk, c)
        bh = metrics(np.ones(n), c)

        if np.isnan(m_ma["ar"]) or np.isnan(m_wyk["ar"]): continue
        if abs(m_ma["bh_ar"]) > 200: continue

        results.append({
            "code": stk["code"], "name": stk["name"], "sector": stk["sector"],
            "rows": n,
            "bh_ar": bh["bh_ar"],
            "ma_ar": m_ma["ar"], "ma_sharpe": m_ma["sharpe"],
            "ma_calmar": m_ma["calmar"], "ma_excess": m_ma["excess"],
            "wyk_ar": m_wyk["ar"], "wyk_sharpe": m_wyk["sharpe"],
            "wyk_calmar": m_wyk["calmar"], "wyk_excess": m_wyk["excess"],
        })

    elap = (datetime.now()-start_t).total_seconds()
    print(f"\n  完成: {len(results)}只, {skipped}跳过, {elap:.0f}s")

    # ── 分析 ──
    print_h("[3/5] Wyckoff相位分布")
    total_ph = sum(phase_counter.values())
    print(f"  {'相位':<14} {'出现次数':>10} {'占比':>8}")
    print("  " + "-" * 35)
    for p in ["markup", "markdown", "accumulation", "distribution", "unknown"]:
        print(f"  {p:<14} {phase_counter[p]:>10} {phase_counter[p]/total_ph*100:>7.1f}%")

    print_s("A. 全样本统计")
    ma_ars = [r["ma_ar"] for r in results]
    wyk_ars = [r["wyk_ar"] for r in results]
    bhs = [r["bh_ar"] for r in results]
    ma_shs = [r["ma_sharpe"] for r in results]
    wyk_shs = [r["wyk_sharpe"] for r in results]
    ma_exc = [r["ma_excess"] for r in results]
    wyk_exc = [r["wyk_excess"] for r in results]

    ma_win = sum(1 for r in results if r["ma_ar"] > r["bh_ar"])
    wyk_win = sum(1 for r in results if r["wyk_ar"] > r["bh_ar"])
    wyk_better = sum(1 for r in results if r["wyk_ar"] > r["ma_ar"])

    print(f"  样本: {len(results)}只")
    print(f"  BH:  均值={np.mean(bhs):.1f}% 中位={np.median(bhs):.1f}%")
    print(f"  MA:  均值={np.mean(ma_ars):.1f}% 中位={np.median(ma_ars):.1f}% 夏普={np.mean(ma_shs):.2f}")
    print(f"  WYK: 均值={np.mean(wyk_ars):.1f}% 中位={np.median(wyk_ars):.1f}% 夏普={np.mean(wyk_shs):.2f}")
    print(f"  MA胜BH: {ma_win}/{len(results)} ({ma_win/len(results)*100:.1f}%)")
    print(f"  WYK胜BH: {wyk_win}/{len(results)} ({wyk_win/len(results)*100:.1f}%)")
    print(f"  WYK胜MA: {wyk_better}/{len(results)} ({wyk_better/len(results)*100:.1f}%)")

    print_s("B. 按板块")
    sectors = defaultdict(list)
    for r in results: sectors[r["sector"]].append(r)
    print(f"  {'板块':<10} {'样本':>6} {'BH':>6} {'MA':>6} {'WYK':>8} {'MA夏普':>7} {'WYK夏普':>8} {'WYK>MA':>7}")
    print("  " + "-" * 60)
    for sn in ["上海主板","深圳主板","创业板","科创板"]:
        if sn not in sectors: continue
        g = sectors[sn]
        g_bh = np.mean([r["bh_ar"] for r in g])
        g_ma = np.mean([r["ma_ar"] for r in g])
        g_wyk = np.mean([r["wyk_ar"] for r in g])
        g_sh_ma = np.mean([r["ma_sharpe"] for r in g])
        g_sh_wyk = np.mean([r["wyk_sharpe"] for r in g])
        g_wm = sum(1 for r in g if r["wyk_ar"] > r["ma_ar"])/len(g)*100
        print(f"  {sn:<10} {len(g):>6} {g_bh:>5.1f}% {g_ma:>5.1f}% {g_wyk:>7.1f}% {g_sh_ma:>6.2f} {g_sh_wyk:>7.2f} {g_wm:>6.0f}%")

    print_s("C. 按Wyckoff相位分组收益分析")
    print(f"  {'相位':<14} {'样本(天)':>10} {'日均收益':>8} {'日胜率':>7} {'年化收益':>8}")
    print("  " + "-" * 50)
    for ph in ["markup", "markdown", "accumulation", "distribution", "unknown"]:
        rets = phase_rets.get(ph, [])
        if not rets: continue
        avg = np.mean(rets)*100
        wr = np.mean(np.array(rets)>0)*100
        ann = ((1+avg/100)**245-1)*100
        print(f"  {ph:<14} {len(rets):>10} {avg:>7.3f}% {wr:>6.1f}% {ann:>7.1f}%")

    print_s("D. MA vs WYK 绩效差距分布")
    gaps = [r["wyk_ar"] - r["ma_ar"] for r in results]
    print(f"  Wyckoff增量: 均值={np.mean(gaps):+.2f}% 中位={np.median(gaps):+.2f}%")
    print(f"  P25={np.percentile(gaps,25):+.2f}% P75={np.percentile(gaps,75):+.2f}%")
    print(f"  正增益占比: {sum(1 for g in gaps if g>0)/len(gaps)*100:.1f}%")
    print(f"  |增益|>1%: {sum(1 for g in gaps if abs(g)>1)/len(gaps)*100:.1f}%")

    # ── 结论 ──
    print_h("[4/5] 验证结论")
    wyk_better_pct = wyk_better/len(results)*100
    print(f"""
  1. Wyckoff相位覆盖度:
     markup     {phase_counter['markup']/total_ph*100:.1f}%
     markdown   {phase_counter['markdown']/total_ph*100:.1f}%
     unknown    {phase_counter['unknown']/total_ph*100:.1f}%
     accumulation {phase_counter['accumulation']/total_ph*100:.1f}%
     distribution {phase_counter['distribution']/total_ph*100:.1f}%

  2. MA60/1%纯策略:
     平均年化 {np.mean(ma_ars):.1f}% | 夏普 {np.mean(ma_shs):.2f}
     战胜BH: {ma_win}/{len(results)} ({ma_win/len(results)*100:.0f}%)

  3. MA60 + Wyckoff:
     平均年化 {np.mean(wyk_ars):.1f}% | 夏普 {np.mean(wyk_shs):.2f}
     战胜BH: {wyk_win}/{len(results)} ({wyk_win/len(results)*100:.0f}%)
     优于纯MA: {wyk_better}/{len(results)} ({wyk_better_pct:.0f}%)

  4. Wyckoff增量价值:
     {'✅ Wyckoff相位提供稳定增量(>50%股票正增益)' if wyk_better_pct > 50 else '❌ Wyckoff相位无稳定增量'}
     （注: 基于原始analyzer.py规则, 无BC/SC点降级）
""")

    # ── 保存 ──
    print_h("[5/5] 保存结果")
    out = {
        "config": {"ma_period": MA_P, "threshold": TH, "cost_buy": COST_B, "cost_sell": COST_S,
                   "period": f"{COMMON_START}~{COMMON_END}"},
        "phase_distribution": {k: int(v) for k, v in phase_counter.items()},
        "summary": {
            "n_stocks": len(results),
            "bh_avg": round(np.mean(bhs), 1), "bh_med": round(np.median(bhs), 1),
            "ma_avg": round(np.mean(ma_ars), 1), "ma_med": round(np.median(ma_ars), 1),
            "ma_sharpe": round(np.mean(ma_shs), 2),
            "wyk_avg": round(np.mean(wyk_ars), 1), "wyk_med": round(np.median(wyk_ars), 1),
            "wyk_sharpe": round(np.mean(wyk_shs), 2),
            "ma_win_rate": round(ma_win/len(results)*100, 1),
            "wyk_win_rate": round(wyk_win/len(results)*100, 1),
            "wyk_better_rate": round(wyk_better/len(results)*100, 1),
        },
        "by_sector": {},
        "phase_returns": {},
    }
    for sn in ["上海主板","深圳主板","创业板","科创板"]:
        if sn not in sectors: continue
        g = sectors[sn]
        out["by_sector"][sn] = {
            "n": len(g),
            "bh_avg": round(np.mean([r["bh_ar"] for r in g]), 1),
            "ma_avg": round(np.mean([r["ma_ar"] for r in g]), 1),
            "wyk_avg": round(np.mean([r["wyk_ar"] for r in g]), 1),
            "wyk_better": round(sum(1 for r in g if r["wyk_ar"]>r["ma_ar"])/len(g)*100, 1),
        }
    for ph in ["markup", "markdown", "accumulation", "distribution", "unknown"]:
        rets = phase_rets.get(ph, [])
        if rets:
            out["phase_returns"][ph] = {
                "days": len(rets), "avg_daily": round(np.mean(rets), 6),
                "win_rate": round(np.mean(np.array(rets)>0)*100, 1),
            }
    (OUT / "results.json").write_text(json.dumps(out, ensure_ascii=False, indent=2, default=str))
    print(f"  结果: {OUT / 'results.json'}")


if __name__ == "__main__":
    main()
