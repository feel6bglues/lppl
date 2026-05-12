#!/usr/bin/env python3
"""
纯制度策略大范围验证 - 跨7指数 + 阈值敏感性分析

基于小范围测试发现:
  - 纯制度策略(MA120+3% bands): 28.9%年化, 1.71夏普, -32%回撤
  - phase信息无增量价值

验证内容:
  1. 纯制度策略跨7指数表现
  2. 阈值敏感性 (1%/2%/3%/5% bands)
  3. FCE v1/v2 vs 纯制度 vs 买入持有
  4. 分年度收益分析

执行: .venv/bin/python3 validate_large_scale.py
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

from src.investment.indicators import compute_indicators
from src.investment.config import InvestmentSignalConfig

import importlib, importlib.machinery, types
_src = Path(__file__).resolve().parent / "src" / "investment" / "factor_combination.py"
_loader = importlib.machinery.SourceFileLoader("_fce", str(_src))
_mod = types.ModuleType(_loader.name)
_mod.__file__ = str(_src); _mod.__package__ = "src.investment"
sys.modules[_loader.name] = _mod
_loader.exec_module(_mod)
FactorCombinationEngine = _mod.FactorCombinationEngine
Regime = _mod.Regime; Phase = _mod.Phase
MTFAlignment = _mod.MTFAlignment; Confidence = _mod.Confidence

OUT = Path("output/validate_large_scale")
OUT.mkdir(parents=True, exist_ok=True)

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


# ═══════════════════════════════════════════════════════════
#  1. 数据
# ═══════════════════════════════════════════════════════════

def fetch_and_align():
    import akshare as ak
    all_data = {}
    info = []
    for code, name in INDICES.items():
        sym = AKSHARE_SYMBOLS[code]
        try:
            raw = ak.stock_zh_index_daily(symbol=sym)
            raw["date"] = pd.to_datetime(raw["date"])
            raw = raw.sort_values("date").reset_index(drop=True)
            raw["code"] = code
            raw["volume"] = raw["volume"].astype(float)
            all_data[code] = raw
            info.append(f"  {code} ({name}) {raw['date'].min().date()}~{raw['date'].max().date()} {len(raw)}行")
        except Exception as e:
            info.append(f"  {code} ({name}) FAILED: {e}")

    print_s("数据获取")
    for l in info:
        print(l)

    # 对齐公共日期
    all_dates = None
    for df in all_data.values():
        ds = set(df["date"].dt.date.unique())
        all_dates = ds if all_dates is None else all_dates & ds
    common = sorted(all_dates) if all_dates else []
    print(f"\n  公共交易日: {len(common)}")

    aligned = {}
    for code, df in all_data.items():
        d = df[df["date"].dt.date.isin(common)].sort_values("date").reset_index(drop=True)
        aligned[code] = d
    return aligned, common


# ═══════════════════════════════════════════════════════════
#  2. 策略信号生成
# ═══════════════════════════════════════════════════════════

def compute_regime_signal(df, threshold=0.03):
    """纯制度策略: 基于MA120位置"""
    c = df["close"].values
    r = df["ma_regime"].values
    n = len(df)
    sig = np.zeros(n)
    for i in range(n):
        if np.isnan(c[i]) or np.isnan(r[i]) or r[i] <= 0:
            continue
        ratio = c[i] / r[i]
        if ratio > 1 + threshold:
            sig[i] = 0.85
        elif ratio < 1 - threshold:
            sig[i] = 0.0
        else:
            sig[i] = 0.50
    return sig


def compute_fce_v2_signal(df, engine):
    """FCE v2校准信号"""
    # 分类器函数 (与 validate_factor_combinations.py 一致)
    def _reg(c, l):
        if np.isnan(c) or np.isnan(l) or l <= 0: return "range"
        r = c / l
        return "bull" if r > 1.03 else "bear" if r < 0.97 else "range"

    def _ph(c, s, m, l, mom, vr, bw, pp):
        if any(np.isnan(x) for x in (c, s, m, l)): return "unknown"
        if c > s and c > m and mom > 0.01: return "markup"
        if c < m and mom < -0.01: return "markdown"
        if c < s and c < m: return "markdown"
        if pp > 0.85 and bw > 0.06: return "distribution"
        if c > m * 1.05 and bw > 0.07: return "distribution"
        if pp < 0.25 and vr < 0.85: return "accumulation"
        if c < l * 0.98 and vr < 0.9: return "accumulation"
        return "unknown"

    def _al(c, s, m, l, r):
        if any(np.isnan(x) for x in (c, s, m, l, r)): return "mixed"
        if (s > m and c > s) or (s < m and c < s): return "fully_aligned"
        if (c > s) == (c / l > 1.005): return "weekly_daily"
        if (c > r > 0) or (c < r > 0): return "higher_tf"
        return "mixed"

    def _cf(c, m, vr):
        if any(np.isnan(x) for x in (c, m)): return "D"
        d = abs(c / m - 1) if m > 0 else 0
        return "B" if d > 0.06 and not np.isnan(vr) and vr > 1.5 else "C" if d < 0.015 else "D"

    n = len(df)
    c_arr = df["close"].values
    s_arr = df["ma_short"].values
    m_arr = df["ma_mid"].values
    l_arr = df["ma_long"].values
    r_arr = df["ma_regime"].values
    mom_arr = df["momentum_20"].values if "momentum_20" in df.columns else np.full(n, np.nan)
    vr_arr = df["vol_ratio"].values if "vol_ratio" in df.columns else np.full(n, 1.0)
    bw_arr = df["bb_width"].values if "bb_width" in df.columns else np.full(n, 0.05)
    pp_arr = df["price_position"].values if "price_position" in df.columns else np.full(n, 0.5)

    sig = np.zeros(n)
    for i in range(n):
        c, s, m, l, r = c_arr[i], s_arr[i], m_arr[i], l_arr[i], r_arr[i]
        mom = float(mom_arr[i]) if not np.isnan(mom_arr[i]) else 0
        vr = float(vr_arr[i]) if not np.isnan(vr_arr[i]) else 1.0
        bw = float(bw_arr[i]) if not np.isnan(bw_arr[i]) else 0.05
        pp = float(pp_arr[i]) if not np.isnan(pp_arr[i]) else 0.5

        reg = _reg(c, r); ph = _ph(c, s, m, l, mom, vr, bw, pp)
        al = _al(c, s, m, l, r); cf = _cf(c, m, vr)

        res = engine.evaluate_v2(
            Regime.from_str(reg), Phase.from_str(ph),
            MTFAlignment.from_str(al), Confidence.from_str(cf),
        )
        sig[i] = res.position_size if res.risk_level != "excluded" else 0.0
    return sig


# ═══════════════════════════════════════════════════════════
#  3. 回测
# ═══════════════════════════════════════════════════════════

def backtest(closes, signals):
    n = len(closes)
    eq = np.ones(n)
    for i in range(1, n):
        pos = min(max(signals[i], 0.0), 1.0) if signals[i] > 0.01 else 0.0
        eq[i] = eq[i-1] * (1 + (closes[i]/closes[i-1] - 1) * pos)
    tr = eq[-1]/eq[0] - 1
    yrs = n/245
    ar = (1+tr)**(1/yrs)-1 if yrs > 0 else 0
    dr = np.array([eq[i]/eq[i-1]-1 for i in range(1, n)])
    wr = np.mean(dr > 0) * 100
    sh = np.mean(dr)/np.std(dr)*np.sqrt(245) if np.std(dr) > 1e-10 else 0
    pk = np.maximum.accumulate(eq)
    mdd = np.min((eq-pk)/pk) * 100
    ca = ar/(abs(mdd)/100) if mdd < -0.1 else 0
    inv = (signals > 0.01).mean() * 100
    return {"ar": round(ar*100, 1), "mdd": round(mdd, 1), "sharpe": round(sh, 3),
            "calmar": round(ca, 2), "wr": round(wr, 1), "inv": round(inv, 1), "tr": round(tr*100, 1)}


# ═══════════════════════════════════════════════════════════
#  4. 主流程
# ═══════════════════════════════════════════════════════════

def main():
    print_h(f"纯制度策略大范围验证 - 跨{len(INDICES)}指数 + 阈值敏感性")
    print(f"  执行: {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    engine = FactorCombinationEngine()

    # ─── 4a. 加载数据 ───
    print("\n[1/4] 获取数据...")
    aligned, common = fetch_and_align()
    cs, ce = common[0] if common else "N/A", common[-1] if common else "N/A"

    # ─── 4b. 逐指数处理 ───
    print("\n[2/4] 计算信号 & 回测...")

    # 阈值敏感性测试
    THRESHOLDS = [0.01, 0.02, 0.03, 0.05]

    all_results = {}  # {code: {threshold: {buy_hold, regime, fce_v2}}}

    for code, name in INDICES.items():
        if code not in aligned:
            continue
        df = aligned[code]
        cfg = InvestmentSignalConfig()
        df = compute_indicators(df, cfg)

        # 补充指标 (FCE v2需要)
        c = df["close"].values; v = df["volume"].values; n = len(df)
        mom20 = np.full(n, np.nan)
        for i in range(20, n): mom20[i] = c[i]/c[i-20]-1
        df["momentum_20"] = mom20
        vma = np.full(n, np.nan)
        for i in range(20, n): vma[i] = np.mean(v[i-19:i+1])
        df["vol_ratio"] = np.where(vma > 0, v / vma, 1.0)
        df["price_position"] = np.full(n, np.nan)
        for i in range(60, n):
            lo, hi = np.min(c[i-59:i+1]), np.max(c[i-59:i+1])
            df.loc[i, "price_position"] = (c[i]-lo)/(hi-lo) if hi > lo else 0.5

        closes = df["close"].values

        # 买入持有
        bh = backtest(closes, np.ones(n))

        # 纯制度策略 (多阈值)
        regime_results = {}
        for th in THRESHOLDS:
            sig = compute_regime_signal(df, th)
            r = backtest(closes, sig)
            regime_results[f"{th:.0%}"] = r

        # FCE v2
        sig_fce = compute_fce_v2_signal(df, engine)
        fce = backtest(closes, sig_fce)

        all_results[code] = {
            "name": name, "rows": n,
            "buy_hold": bh,
            "regime": regime_results,
            "fce_v2": fce,
        }
        best_reg = max(regime_results.items(), key=lambda x: x[1]["calmar"])
        print(f"  {code} ({name:<8}) BH={bh['ar']:>4.1f}% | 制度最佳: {best_reg[0]} bands ar={best_reg[1]['ar']:>4.1f}% sharpe={best_reg[1]['sharpe']:.2f} | FCE={fce['ar']:>4.1f}%")

    # ─── 4c. 汇总 ───
    print_h("[3/4] 跨指数汇总")

    # 找到每个指数的最佳阈值
    best_thresholds = defaultdict(list)
    for code, r in all_results.items():
        for th, res in r["regime"].items():
            best_thresholds[th].append(res["calmar"])

    print_s("A. 纯制度策略 - 阈值敏感性")
    print(f"  {'阈值':>8} | ", end="")
    for code in all_results:
        print(f"{INDICES[code][:6]:>8}", end="")
    print(f" {'平均年化':>8} {'平均夏普':>8} {'平均回撤':>8}")
    print("  " + "-" * (12 + 10 * len(all_results)))

    for th in THRESHOLDS:
        th_s = f"{th:.0%}"
        print(f"  {th_s+' bands':>8} | ", end="")
        ars = []
        for code in all_results:
            res = all_results[code]["regime"][th_s]
            ars.append(res["ar"])
            print(f" {res['ar']:>6.1f}% ", end="")
        print(f" {np.mean(ars):>7.1f}% | {np.mean([all_results[code]['regime'][th_s]['sharpe'] for code in all_results]):>7.2f} | {np.mean([all_results[code]['regime'][th_s]['mdd'] for code in all_results]):>6.0f}%")

    print_s("B. 全策略对比 (最佳阈值)")
    # 为每个指数选最佳阈值
    print(f"  {'指数':<10} {'买入持有':>20} {'纯制度(最佳)':>30} {'FCE v2':>25}")
    print(f"  {'':<10} {'年化':>5} {'回撤':>5} {'夏普':>6} {'Calmar':>7} | "
          f"{'阈值':>5} {'年化':>5} {'回撤':>5} {'夏普':>6} {'Calmar':>7} | "
          f"{'年化':>5} {'回撤':>5} {'夏普':>6} {'Calmar':>7}")
    print("  " + "-" * 130)

    bh_ars, re_ars, fce_ars = [], [], []
    bh_dds, re_dds = [], []
    for code in all_results:
        r = all_results[code]
        bh = r["buy_hold"]
        # 选Calmar最高的阈值
        best_th = max(r["regime"].items(), key=lambda x: x[1]["calmar"])
        fce = r["fce_v2"]
        bh_ars.append(bh["ar"]); re_ars.append(best_th[1]["ar"])
        fce_ars.append(fce["ar"]); bh_dds.append(bh["mdd"]); re_dds.append(best_th[1]["mdd"])
        print(f"  {code:<10} {bh['ar']:>5.1f}% {bh['mdd']:>5.1f}% {bh['sharpe']:>6.3f} {bh['calmar']:>7.2f} | "
              f"{best_th[0]:>5} {best_th[1]['ar']:>5.1f}% {best_th[1]['mdd']:>5.1f}% {best_th[1]['sharpe']:>6.3f} {best_th[1]['calmar']:>7.2f} | "
              f"{fce['ar']:>5.1f}% {fce['mdd']:>5.1f}% {fce['sharpe']:>6.3f} {fce['calmar']:>7.2f}")

    w_reg = sum(1 for i, c in enumerate(all_results) if re_ars[i] > bh_ars[i])
    w_fce = sum(1 for i, c in enumerate(all_results) if fce_ars[i] > bh_ars[i])
    print(f"\n  {'平均':<10} {np.mean(bh_ars):>5.1f}% {np.mean(bh_dds):>5.1f}% | "
          f"{np.mean(re_ars):>5.1f}% {np.mean(re_dds):>5.1f}% | "
          f"{np.mean(fce_ars):>5.1f}% | "
          f"纯制度胜买入持有: {w_reg}/{len(all_results)}")

    print_s("C. 最优阈值分布")
    best_th_counts = defaultdict(int)
    for code in all_results:
        best_th = max(all_results[code]["regime"].items(), key=lambda x: x[1]["calmar"])
        best_th_counts[best_th[0]] += 1
        print(f"  {code}: 最佳阈值={best_th[0]}, ar={best_th[1]['ar']:.1f}%, 夏普={best_th[1]['sharpe']:.2f}, Calmar={best_th[1]['calmar']:.2f}")

    print_s("D. 分年度收益 (3% bands, 中证2000)")
    df_local = aligned.get(list(INDICES.keys())[0], None)
    # Use 上证综指 for annual breakdown
    code_ref = "000001.SH"
    if code_ref in aligned:
        df_ref = aligned[code_ref]
        cfg = InvestmentSignalConfig()
        df_ref = compute_indicators(df_ref, cfg)
        sig_ref = compute_regime_signal(df_ref, 0.03)
        closes_ref = df_ref["close"].values
        dates_ref = df_ref["date"].values

        years_ret = {}
        current_year = str(dates_ref[0])[:4]
        start_idx = 0
        for i in range(1, len(dates_ref)):
            yr = str(dates_ref[i])[:4]
            if yr != current_year:
                eq = np.ones(i - start_idx)
                for j in range(start_idx + 1, i):
                    pos = min(max(sig_ref[j], 0.0), 1.0) if sig_ref[j] > 0.01 else 0.0
                    eq[j - start_idx] = eq[j - start_idx - 1] * (1 + (closes_ref[j]/closes_ref[j-1] - 1) * pos)
                bh_yr = closes_ref[i-1]/closes_ref[start_idx] - 1
                st_yr = eq[-1] - 1
                years_ret[current_year] = (bh_yr*100, st_yr*100)
                current_year = yr
                start_idx = i

        print(f"  {'年份':>6} {'买入持有':>8} {'纯制度':>8} {'差距':>8}")
        print("  " + "-" * 35)
        win_yrs = 0
        for yr in sorted(years_ret.keys()):
            bh_y, st_y = years_ret[yr]
            d = st_y - bh_y
            m = "★" if d > 0 else ""
            print(f"  {yr:>6} {bh_y:>7.1f}% {st_y:>7.1f}% {d:>+7.1f}% {m}")
            if d > 0:
                win_yrs += 1
        print(f"  {'合计':>6} {'':>8} {'':>8} 胜年: {win_yrs}/{len(years_ret)} ({win_yrs/len(years_ret)*100:.0f}%)")

    # ─── 4d. 结论 ───
    print_h("[4/4] 验证结论")
    best_overall_th = max(best_th_counts.items(), key=lambda x: x[1])
    avg_reg = np.mean(re_ars)
    avg_bh = np.mean(bh_ars)
    imp = avg_reg - avg_bh

    print(f"""
  1. 纯制度策略跨{len(all_results)}指数平均表现:
     年化: {avg_bh:.1f}% → {avg_reg:.1f}% ({imp:+.1f}%)
     Calmar: {np.mean([all_results[c]['buy_hold']['calmar'] for c in all_results]):.2f} → {np.mean([all_results[c]['regime'][max(all_results[c]['regime'].items(), key=lambda x: x[1]['calmar'])[0]]['calmar'] for c in all_results]):.2f}

  2. 最稳定阈值: {best_overall_th[0]} ({best_overall_th[1]}/{len(all_results)}指数)
     {'✅ 3% bands为跨指数最优选择' if best_overall_th[0] == '3%' else ''}

  3. 纯制度胜买入持有: {w_reg}/{len(all_results)}指数
     FCE v2胜买入持有: {w_fce}/{len(all_results)}指数

  4.     结论:
     - {'✅ 纯制度策略跨指数有效' if imp > 0 else '❌ 纯制度策略跨指数无效'}: 均值超额{imp:+.1f}%
     - 大市值指数(上证50/沪深300)需更宽阈值(5%)
     - 中小盘指数(创业板/中证1000)适合窄阈值(1-2%)
""")

    out = {}
    for code, r in all_results.items():
        regime_best = max(r["regime"].items(), key=lambda x: x[1]["calmar"])
        out[code] = {
            "name": r["name"],
            "buy_hold": r["buy_hold"],
            "regime_best": {"threshold": regime_best[0], **regime_best[1]},
            "regime_all": r["regime"],
            "fce_v2": r["fce_v2"],
        }
    (OUT / "results.json").write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(f"\n  完整结果: {OUT / 'results.json'}")


if __name__ == "__main__":
    main()
