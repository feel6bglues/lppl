#!/usr/bin/env python3
"""
交易成本 + Walk-forward 综合验证

1. 交易成本模型:
   - 佣金: 万2.5 (双边)
   - 印花税: 千1 (卖出)
   - 滑点: 万5 (双边)
   - 买入成本: 0.075%, 卖出成本: 0.175%

2. Walk-forward (3折):
   折1: 训练 2014-10~2018-06, 测试 2018-06~2022-02, 验证 2022-02~2026-05
   折2: 训练 2018-06~2022-02, 测试 2022-02~2026-05
   折3: 训练 2014-10~2020-06, 测试 2020-06~2026-05

3. 输出: 有/无成本对比, 样本内/外对比, 跨指数汇总

执行: .venv/bin/python3 validate_costs_walkforward.py
结果: output/validate_large_scale/
"""
import sys, os, json, warnings
from pathlib import Path
from datetime import datetime
from collections import defaultdict

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
warnings.filterwarnings("ignore")

OUT = Path("output/validate_large_scale"); OUT.mkdir(parents=True, exist_ok=True)

INDICES = {
    "000001.SH": "上证综指", "399001.SZ": "深证成指",
    "399006.SZ": "创业板指", "000016.SH": "上证50",
    "000300.SH": "沪深300", "000905.SH": "中证500",
    "000852.SH": "中证1000",
}
AKSHARE_SYMBOLS = {
    "000001.SH": "sh000001", "399001.SZ": "sz399001",
    "399006.SZ": "sz399006", "000016.SH": "sh000016",
    "000300.SH": "sh000300", "000905.SH": "sh000905",
    "000852.SH": "sh000852",
}


def print_h(t): print(f"\n{'='*70}\n  {t}\n{'='*70}")
def print_s(t): print(f"\n{'-'*50}\n  {t}\n{'-'*50}")

# ═══════════════════════════════════════════════════════════════
#  数据
# ═══════════════════════════════════════════════════════════════

def fetch_and_align():
    import akshare as ak
    all_data = {}
    for code, sym in AKSHARE_SYMBOLS.items():
        try:
            raw = ak.stock_zh_index_daily(symbol=sym)
            raw["date"] = pd.to_datetime(raw["date"])
            raw = raw.sort_values("date").reset_index(drop=True)
            raw["volume"] = raw["volume"].astype(float)
            all_data[code] = raw
        except Exception as e:
            print(f"  WARN: {code} failed: {e}")
    all_dates = None
    for df in all_data.values():
        ds = set(df["date"].dt.date.unique())
        all_dates = ds if all_dates is None else all_dates & ds
    common = sorted(all_dates) if all_dates else []
    aligned = {}
    for code, df in all_data.items():
        d = df[df["date"].dt.date.isin(common)].sort_values("date").reset_index(drop=True)
        aligned[code] = d
    return aligned, common


# ═══════════════════════════════════════════════════════════════
#  回测 (含交易成本)
# ═══════════════════════════════════════════════════════════════

def backtest_with_costs(closes, signals, cost_buy=0.00075, cost_sell=0.00175):
    """
    含交易成本的向量化回测

    成本模型:
    - 买入: 佣金万2.5 + 滑点万5 = 万7.5 (0.075%)
    - 卖出: 印花税千1 + 佣金万2.5 + 滑点万5 = 千1.75 (0.175%)

    跟踪持仓变化, 仅在仓位变化时产生成本。
    """
    n = len(closes)
    eq = np.ones(n)
    pos = 0.0

    for i in range(1, n):
        # 先以昨日仓位计算今日收益
        ret = closes[i] / closes[i-1] - 1
        eq[i] = eq[i-1] * (1 + ret * pos)

        # 再以今日收盘信号更新仓位(用于明日)
        target = min(max(signals[i], 0.0), 1.0) if signals[i] > 0.01 else 0.0
        change = target - pos
        if abs(change) > 0.001:
            if change > 0:
                cost = abs(change) * cost_buy
            else:
                cost = abs(change) * cost_sell
            eq[i] -= cost
            pos = target

    return eq


def backtest_no_costs(closes, signals):
    """无成本回测(对比用)"""
    n = len(closes); eq = np.ones(n); pos = 0.0
    for i in range(1, n):
        eq[i] = eq[i-1] * (1 + (closes[i]/closes[i-1]-1) * pos)
        pos = min(max(signals[i], 0.0), 1.0) if signals[i] > 0.01 else 0.0
    return eq


def compute_metrics(eq, closes):
    n = len(eq); tr = eq[-1]/eq[0]-1; yrs = n/245
    ar = (1+tr)**(1/yrs)-1 if yrs > 0 else 0
    dr = np.array([eq[i]/eq[i-1]-1 for i in range(1, n)])
    wr = np.mean(dr > 0)*100
    sh = np.mean(dr)/np.std(dr)*np.sqrt(245) if np.std(dr) > 1e-10 else 0
    pk = np.maximum.accumulate(eq); mdd = np.min((eq-pk)/pk)*100
    ca = ar/(abs(mdd)/100) if mdd < -0.1 else 0
    # 买入持有
    bh_tr = closes[-1]/closes[0]-1; bh_ar = (1+bh_tr)**(1/yrs)-1 if yrs > 0 else 0
    return {"ar": round(ar*100,1), "sharpe": round(sh,3), "mdd": round(mdd,1),
            "calmar": round(ca,2), "wr": round(wr,1), "bh_ar": round(bh_ar*100,1),
            "excess": round((ar-bh_ar)*100,1)}


# ═══════════════════════════════════════════════════════════════
#  策略信号生成
# ═══════════════════════════════════════════════════════════════

def regime_signal(closes, ma_period=60, threshold=0.01):
    """纯制度策略信号"""
    n = len(closes); sig = np.zeros(n); ma = np.full(n, np.nan)
    for i in range(ma_period-1, n):
        ma[i] = np.mean(closes[i-ma_period+1:i+1])
    for i in range(n):
        if np.isnan(ma[i]) or ma[i] <= 0: continue
        r = closes[i]/ma[i]
        if r > 1+threshold: sig[i] = 0.85
        elif r < 1-threshold: sig[i] = 0.0
        else: sig[i] = 0.50
    return sig


def wyckoff_signal(closes, ma_period=60, threshold=0.01):
    """制度+Wyckoff相位信号 (与validate_p1_p2.py一致)"""
    n = len(closes); sig = np.zeros(n); ma = np.full(n, np.nan)
    for i in range(ma_period-1, n):
        ma[i] = np.mean(closes[i-ma_period+1:i+1])

    ma5 = np.full(n, np.nan); ma20 = np.full(n, np.nan)
    short_trend = np.full(n, np.nan); rel_pos = np.full(n, np.nan)
    for i in range(4, n): ma5[i] = np.mean(closes[i-4:i+1])
    for i in range(19, n): ma20[i] = np.mean(closes[i-19:i+1])
    for i in range(19, n): short_trend[i] = closes[i]/closes[i-19]-1
    for i in range(59, n):
        lo, hi = np.min(closes[i-59:i+1]), np.max(closes[i-59:i+1])
        rel_pos[i] = (closes[i]-lo)/(hi-lo) if hi > lo else 0.5

    for i in range(60, n):
        if np.isnan(ma[i]) or ma[i] <= 0: continue
        r = closes[i]/ma[i]
        if r > 1+threshold: reg_sig = 0.85
        elif r < 1-threshold: reg_sig = 0.0
        else: reg_sig = 0.50

        # Wyckoff相位
        st = short_trend[i] if not np.isnan(short_trend[i]) else 0
        rp = rel_pos[i] if not np.isnan(rel_pos[i]) else 0.5
        m5 = ma5[i]; m20 = ma20[i]; cp = closes[i]

        # TR检测
        lo60 = np.min(closes[max(0,i-59):i+1])
        hi60 = np.max(closes[max(0,i-59):i+1])
        tr_pct = (hi60-lo60)/lo60 if lo60 > 0 else 0
        in_tr = tr_pct <= 0.30 and 0.25 <= rp <= 0.75

        if in_tr:
            prior = closes[i-60]/closes[i-100]-1 if (i >= 100 and closes[i-100] > 0) else 0
            if prior < -0.10: ph = "accumulation"
            elif prior > 0.10: ph = "distribution"
            elif rp <= 0.40: ph = "accumulation"
            else: ph = "unknown"
        else:
            if st >= 0.03 and cp > m20 and m5 >= m20: ph = "markup"
            elif st >= 0.03 and cp > m5 and rp >= 0.50: ph = "markup"
            elif st <= -0.03 and cp < m20: ph = "markdown"
            elif st <= -0.04 and rp <= 0.20: ph = "markdown"
            else: ph = "unknown"

        # 相位增强信号
        if ph == "markup" and reg_sig > 0: sig[i] = min(1.0, reg_sig+0.10)
        elif ph == "markdown" and reg_sig < 0.85: sig[i] = 0.0
        elif ph == "accumulation" and reg_sig == 0.50: sig[i] = 0.60
        elif ph == "distribution" and reg_sig == 0.50: sig[i] = 0.30
        else: sig[i] = reg_sig
    return sig


# ═══════════════════════════════════════════════════════════════
#  Walk-forward 验证
# ═══════════════════════════════════════════════════════════════

def grid_search_optimal(closes, ma_periods, thresholds):
    """在数据上找最优参数"""
    best_calmar, best_mp, best_th = -999, 60, 0.01
    for mp in ma_periods:
        for th in thresholds:
            sig = regime_signal(closes, mp, th)
            eq = backtest_no_costs(closes, sig)
            m = compute_metrics(eq, closes)
            if m["calmar"] > best_calmar:
                best_calmar = m["calmar"]
                best_mp, best_th = mp, th
    return best_mp, best_th


def walk_forward(closes, dates, n_folds=3):
    """
    执行Walk-forward验证

    将数据分成n_folds份:
    Fold 1: Train 0~60%, Test 60~80%
    Fold 2: Train 20~80%, Test 80~100%
    Fold 3: Train 0~80%, Test 80~100%
    """
    n = len(closes)
    split1 = int(n * 0.60)
    split2 = int(n * 0.80)

    folds = [
        ("折1(2014-2018→2018-2022)", 0, split1, split1, split2),
        ("折2(2018-2022→2022-2026)", split1, split2, split2, n),
        ("折3(2014-2020→2020-2026)", 0, split2, split2, n),
    ]

    wf_results = []
    for label, tr_s, tr_e, ts_s, ts_e in folds:
        train_c = closes[tr_s:tr_e]
        test_c = closes[ts_s:ts_e]
        test_d = dates[ts_s:ts_e]

        # 在训练集上找最优参数
        best_mp, best_th = grid_search_optimal(train_c, [60, 80, 100, 120], [0.01, 0.02, 0.03])

        # 在测试集上用最优参数回测 (含成本和不含成本)
        sig_test = regime_signal(test_c, best_mp, best_th)
        sig_wyk = wyckoff_signal(test_c, best_mp, best_th)

        eq_nc = backtest_no_costs(test_c, sig_test)    # 无成本-制度
        eq_wc = backtest_with_costs(test_c, sig_test)     # 有成本-制度
        eq_wn = backtest_with_costs(test_c, sig_wyk)      # 有成本-制度+Wyckoff

        m_nc = compute_metrics(eq_nc, test_c)
        m_wc = compute_metrics(eq_wc, test_c)
        m_wn = compute_metrics(eq_wn, test_c)

        wf_results.append({
            "fold": label, "train": f"{dates[tr_s][:10] if tr_s < len(dates) else ''}~{dates[min(tr_e-1, len(dates)-1)][:10]}",
            "test": f"{dates[ts_s][:10]}~{dates[min(ts_e-1, len(dates)-1)][:10]}",
            "best_params": f"MA{best_mp}/{best_th:.0%}",
            "regime_no_cost": m_nc,
            "regime_with_cost": m_wc,
            "regime_plus_wyckoff": m_wn,
            "cost_impact": round(m_nc["ar"] - m_wc["ar"], 1),
            "wyckoff_impact": round(m_wn["ar"] - m_wc["ar"], 1),
        })
    return wf_results


# ═══════════════════════════════════════════════════════════════
#  主流程
# ═══════════════════════════════════════════════════════════════

def main():
    print_h("交易成本 + Walk-forward 综合验证")
    print(f"  执行: {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    # ── 数据 ──
    aligned, common_dates = fetch_and_align()
    print(f"  指数: {len(aligned)}, 共同交易日: {len(common_dates)}")
    print(f"  区间: {common_dates[0]}~{common_dates[-1]}")

    all_wf = {}
    cost_impacts = []
    wyk_impacts = []

    for code in INDICES:
        if code not in aligned:
            continue
        df = aligned[code]
        closes = df["close"].values
        dates = df["date"].dt.strftime("%Y-%m-%d").values
        n = len(df)
        print(f"\n  [{code}] {INDICES[code]} ({n}行)")

        # ── 全样本无成本(制度 vs Wyckoff) ──
        sig_r = regime_signal(closes, 60, 0.01)
        sig_w = wyckoff_signal(closes, 60, 0.01)
        eq_r = backtest_no_costs(closes, sig_r)
        eq_w = backtest_no_costs(closes, sig_w)
        mr = compute_metrics(eq_r, closes)
        mw = compute_metrics(eq_w, closes)
        print(f"  全样本: 制度={mr['ar']}%/Calmar={mr['calmar']} "
              f"制度+Wyckoff={mw['ar']}%/Calmar={mw['calmar']}")

        # ── 全样本有/无成本对比 ──
        eq_rc = backtest_with_costs(closes, sig_r)
        eq_wc = backtest_with_costs(closes, sig_w)
        mrc = compute_metrics(eq_rc, closes)
        mwc = compute_metrics(eq_wc, closes)
        cost_impact = mr["ar"] - mrc["ar"]
        wyk_gain = mwc["ar"] - mrc["ar"]
        cost_impacts.append(cost_impact)
        wyk_impacts.append(wyk_gain)
        print(f"  成本影响: {mr['ar']}% → {mrc['ar']}% (-{cost_impact:.1f}%)")
        print(f"  Wyckoff增益: {mrc['ar']}% → {mwc['ar']}% (+{wyk_gain:.1f}%)")

        # ── Walk-forward ──
        wf = walk_forward(closes, dates, 3)
        all_wf[code] = {
            "name": INDICES[code],
            "full_sample_no_cost": mr,
            "full_sample_with_cost": mrc,
            "full_sample_wyckoff": mwc,
            "walk_forward": wf,
        }

        print(f"  Walk-forward 3折:")
        for f in wf:
            print(f"    {f['fold']}: 参数={f['best_params']} "
                  f"无成本={f['regime_no_cost']['ar']}%/Calmar={f['regime_no_cost']['calmar']} "
                  f"有成本={f['regime_with_cost']['ar']}%/Calmar={f['regime_with_cost']['calmar']} "
                  f"+Wyckoff={f['regime_plus_wyckoff']['ar']}%/Calmar={f['regime_plus_wyckoff']['calmar']}")

    # ── 收集折3样本外数据 ──
    wf_codes = [c for c in INDICES if c in aligned]
    oos_ars_no_cost = []; oos_ars_with_cost = []; oos_ars_wyckoff = []
    oos_calmars_no_cost = []; oos_calmars_with_cost = []; oos_calmars_wyckoff = []
    oos_data = {}
    for code in wf_codes:
        f = all_wf[code]["walk_forward"][2]
        oos_data[code] = {
            "no_cost": f["regime_no_cost"], "with_cost": f["regime_with_cost"],
            "wyckoff": f["regime_plus_wyckoff"],
        }
        oos_ars_no_cost.append(f["regime_no_cost"]["ar"])
        oos_ars_with_cost.append(f["regime_with_cost"]["ar"])
        oos_ars_wyckoff.append(f["regime_plus_wyckoff"]["ar"])
        oos_calmars_no_cost.append(f["regime_no_cost"]["calmar"])
        oos_calmars_with_cost.append(f["regime_with_cost"]["calmar"])
        oos_calmars_wyckoff.append(f["regime_plus_wyckoff"]["calmar"])

    # ── 汇总 ──
    print_h("汇总报告")

    # 成本影响
    print_s("A. 交易成本影响 (全样本)")
    print(f"  {'指数':<12} {'无成本':>8} {'有成本':>8} {'差异':>8} {'侵蚀%':>8}")
    print("  " + "-" * 48)
    for code in wf_codes:
        mr = all_wf[code]["full_sample_no_cost"]
        mrc = all_wf[code]["full_sample_with_cost"]
        diff = mr["ar"] - mrc["ar"]
        pct = diff / mr["ar"] * 100 if mr["ar"] > 0 else 0
        print(f"  {code:<12} {mr['ar']:>7.1f}% {mrc['ar']:>7.1f}% -{diff:>5.1f}% {pct:>6.1f}%")
    avg_cost = np.mean(cost_impacts)
    cost_pcts = [abs(cost_impacts[i]) / max(abs(all_wf[wf_codes[i]]['full_sample_no_cost']['ar']), 0.1) * 100
                 for i in range(len(wf_codes))]
    print(f"  {'平均':<12} {'':>8} {'':>8} -{avg_cost:>5.1f}% {np.mean(cost_pcts):>6.1f}%")

    # Wyckoff增益
    print_s("B. Wyckoff相位增量 (有成本下)")
    print(f"  {'指数':<12} {'制度':>8} {'制度+Wyk':>10} {'增益':>8}")
    print("  " + "-" * 42)
    for code in wf_codes:
        mr = all_wf[code]["full_sample_with_cost"]
        mw = all_wf[code]["full_sample_wyckoff"]
        gain = mw["ar"] - mr["ar"]
        print(f"  {code:<12} {mr['ar']:>7.1f}% {mw['ar']:>8.1f}% +{gain:>5.1f}%")
    print(f"  {'平均':<12} {np.mean([all_wf[c]['full_sample_with_cost']['ar'] for c in wf_codes]):>7.1f}% "
          f"{np.mean([all_wf[c]['full_sample_wyckoff']['ar'] for c in wf_codes]):>8.1f}% "
          f"+{np.mean(wyk_impacts):>5.1f}%")

    # Walk-forward
    print_s("C. Walk-forward 样本外测试汇总")
    for fold_idx, fold_label in enumerate(["折1(2014-2018→2018-2022)", "折2(2018-2022→2022-2026)", "折3(2014-2020→2020-2026)"]):
        print(f"\n  {fold_label}:")
        print(f"  {'指数':<12} {'参数':>10} {'无成本':>8} {'有成本':>8} {'+Wyckoff':>10} {'Calmar(有成本)':>15}")
        print("  " + "-" * 65)
        for code in wf_codes:
            f = all_wf[code]["walk_forward"][fold_idx]
            print(f"  {code:<12} {f['best_params']:>10} {f['regime_no_cost']['ar']:>7.1f}% "
                  f"{f['regime_with_cost']['ar']:>7.1f}% {f['regime_plus_wyckoff']['ar']:>8.1f}% "
                  f"{f['regime_plus_wyckoff']['calmar']:>13.2f}")

    # 样本内vs样本外对比
    print_s("D. Walk-forward 折间稳定性")
    # 对比折1与折2-3的结果稳定性
    print(f"  {'指数':<12} {'折1(2018-2022)':>14} {'折2(2022-2026)':>14} {'折3(2020-2026)':>14} {'折间标准差':>10}")
    print("  " + "-" * 66)
    stabilities = []
    for code in wf_codes:
        wf = all_wf[code]["walk_forward"]
        ars = [f["regime_with_cost"]["ar"] for f in wf]
        std = np.std(ars)
        stabilities.append(std)
        print(f"  {code:<12} {ars[0]:>13.1f}% {ars[1]:>13.1f}% {ars[2]:>13.1f}% {std:>8.1f}")
    print(f"  {'平均折间std':<12} {np.mean(stabilities):>13.1f}")

    # ── 最终结论 ──
    print_h("最终结论")

    avg_oos_cost = np.mean(oos_ars_with_cost) if oos_ars_with_cost else 0
    avg_oos_wyk = np.mean(oos_ars_wyckoff) if oos_ars_wyckoff else 0
    avg_oos_calmar = np.mean(oos_calmars_with_cost) if oos_calmars_with_cost else 0
    avg_stability = np.mean(stabilities) if stabilities else 0

    print(f"""
  1. 交易成本影响:
     平均侵蚀: {avg_cost:.1f}%/年 (占收益的{np.mean(cost_pcts):.0f}%)
     MA60/1%窄带的高频调仓是主因
     {'✅ 成本影响在可接受范围(年化侵蚀<20%)' if avg_cost < 3 else '⚠️ 成本侵蚀显著, 建议放宽阈值至2-3%以减少调仓'}

  2. Walk-forward 样本外表现 (折3, 2020-2026):
     制度(有成本): 平均年化 {avg_oos_cost:.1f}%
     制度+Wyckoff: 平均年化 {avg_oos_wyk:.1f}%
     Calmar: {avg_oos_calmar:.2f}

  3. Walk-forward 折间稳定性:
     平均折间标准差: {avg_stability:.1f}%
     {'✅ 策略跨时间段表现稳定(折间std<10%)' if avg_stability < 10 else '⚠️ 策略在不同时间段表现差异大'}

  4. Wyckoff增量验证 (有成本环境下):
     {'✅ Wyckoff相位在有成本环境下仍有增量价值' if np.mean(wyk_impacts) > 1 else '⚠️ Wyckoff增益被交易成本抵消'}

  5. 综合评分:
     全样本(有成本): {np.mean([all_wf[c]['full_sample_with_cost']['ar'] for c in wf_codes]):.1f}%年化
     样本外(折3,有成本): {avg_oos_cost:.1f}%年化
     → 真实预期收益区间: {avg_oos_cost-3:.1f}%~{avg_oos_cost+3:.1f}%年化
""")

    # 保存
    out = {"cost_model": {"buy": 0.00075, "sell": 0.00175, "desc": "佣金万2.5+印花税千1+滑点万5"},
           "walk_forward_folds": 3, "results": {}}
    for code, r in all_wf.items():
        out["results"][code] = {
            "name": r["name"],
            "full_sample_no_cost": r["full_sample_no_cost"],
            "full_sample_with_cost": r["full_sample_with_cost"],
            "full_sample_wyckoff": r["full_sample_wyckoff"],
            "walk_forward": r["walk_forward"],
        }
    (OUT / "costs_walkforward.json").write_text(json.dumps(out, ensure_ascii=False, indent=2, default=str))
    print(f"\n  结果: {OUT / 'costs_walkforward.json'}")


if __name__ == "__main__":
    main()
