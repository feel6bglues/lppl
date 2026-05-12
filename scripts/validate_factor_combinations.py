#!/usr/bin/env python3
"""
因子组合验证脚本 v3 — 修复相位分类器, 优化策略执行

v3 改进:
  1. 补充 momentum_20 / vol_ratio 计算
  2. 重写 phase 分类器 (4类相位全覆盖)
  3. 移除60d锁仓, 改为信号确认机制 (连续N天)
  4. 制度持久化作为默认策略
  5. 对比5+种策略变体

执行: .venv/bin/python3 validate_factor_combinations.py
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
_mod.__file__ = str(_src)
_mod.__package__ = "src.investment"
sys.modules[_loader.name] = _mod
_loader.exec_module(_mod)
FactorCombinationEngine = _mod.FactorCombinationEngine
Regime = _mod.Regime; Phase = _mod.Phase
MTFAlignment = _mod.MTFAlignment; Confidence = _mod.Confidence


# ═══════════════════════════════════════════════════════════
#  1. 数据
# ═══════════════════════════════════════════════════════════

def load_and_prepare(path="data/932000.SH.parquet"):
    df = pd.read_parquet(path)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    df = df.rename(columns={"涨跌幅": "pct_change", "成交金额": "amount", "成交量": "volume"})
    return df


def add_extra_indicators(df):
    """补充 momentum 和 volume 指标"""
    c = df["close"].values
    v = df["volume"].values
    n = len(df)

    mom20 = np.full(n, np.nan)
    for i in range(20, n):
        mom20[i] = c[i] / c[i-20] - 1
    df["momentum_20"] = mom20

    vol_ma = np.full(n, np.nan)
    for i in range(20, n):
        vol_ma[i] = np.mean(v[i-19:i+1])
    df["vol_ma"] = vol_ma
    df["vol_ratio"] = np.where(vol_ma > 0, v / vol_ma, 1.0)

    # 新增: 价格相对位置 (用于相位判断)
    df["price_position"] = np.full(n, np.nan)
    for i in range(60, n):
        lo, hi = np.min(c[i-59:i+1]), np.max(c[i-59:i+1])
        df.loc[i, "price_position"] = (c[i] - lo) / (hi - lo) if hi > lo else 0.5

    return df


# ═══════════════════════════════════════════════════════════
#  2. 因子分类器 (重写, 覆盖全部4类相位)
# ═══════════════════════════════════════════════════════════

def classify_regime_row(c, l):
    if np.isnan(c) or np.isnan(l) or l <= 0:
        return "range"
    r = c / l
    if r > 1.03:   return "bull"
    elif r < 0.97: return "bear"
    else:          return "range"


def classify_phase_row(c, s, m, l, mom20, vr, bw, pp):
    """宽松阈值覆盖全部4类相位, 优先顺序: 趋势 > 盘整"""
    if any(np.isnan(x) for x in (c, s, m, l)):
        return "unknown"

    # 1. Markup: 价格在MA之上 + 正动量
    if c > s > m and mom20 > 0.01:
        return "markup"
    if c > s and c > m and mom20 > 0.02:
        return "markup"

    # 2. Markdown: 价格在MA之下 + 负动量
    if c < m and mom20 < -0.01:
        return "markdown"
    if c < s and c < m:
        return "markdown"

    # 3. Distribution: 价格在高位 + 宽幅震荡
    if pp > 0.85 and bw > 0.06:
        return "distribution"
    if c > m * 1.05 and bw > 0.07:
        return "distribution"

    # 4. Accumulation: 价格在低位 + 缩量
    if pp < 0.25 and vr < 0.85:
        return "accumulation"
    if c < l * 0.98 and vr < 0.9:
        return "accumulation"

    return "unknown"


def classify_alignment_row(c, s, m, l, r):
    if any(np.isnan(x) for x in (c, s, m, l, r)):
        return "mixed"
    bull_aligned = s > m and c > s
    bear_aligned = s < m and c < s
    if bull_aligned or bear_aligned:
        return "fully_aligned"
    if (c > s) == (c / l > 1.005):
        return "weekly_daily"
    if (c > r > 0) or (c < r > 0):
        return "higher_tf"
    return "mixed"


def classify_confidence_row(c, m, vr):
    if any(np.isnan(x) for x in (c, m)):
        return "D"
    dist = abs(c / m - 1) if m > 0 else 0
    if dist > 0.06 and (not np.isnan(vr) and vr > 1.5):
        return "B"
    elif dist < 0.015:
        return "C"
    return "D"


# ═══════════════════════════════════════════════════════════
#  3. 信号生成
# ═══════════════════════════════════════════════════════════

def generate_signals(df):
    """生成多组信号用于对比"""
    engine = FactorCombinationEngine()
    n = len(df)

    c_arr = df["close"].values
    s_arr = df["ma_short"].values
    m_arr = df["ma_mid"].values
    l_arr = df["ma_long"].values
    r_arr = df["ma_regime"].values
    mom_arr = df["momentum_20"].values
    vr_arr = df["vol_ratio"].values
    bw_arr = df["bb_width"].values
    pp_arr = df["price_position"].values

    regimes = []; phases = []; alignments = []; confs = []
    sig_raw    = np.zeros(n)   # FCE v1引擎信号
    sig_v2     = np.zeros(n)   # FCE v2引擎信号(校准版)
    sig_trend  = np.zeros(n)   # 纯趋势: bull+fully_aligned
    sig_markup = np.zeros(n)   # 纯markup做多
    sig_markdn = np.zeros(n)   # 纯markdown做多
    sig_allpos = np.zeros(n)   # 任意正信号(不做空)

    for i in range(n):
        c, s, m, l, r = c_arr[i], s_arr[i], m_arr[i], l_arr[i], r_arr[i]
        mom = float(mom_arr[i]) if not np.isnan(mom_arr[i]) else 0
        vr  = float(vr_arr[i])  if not np.isnan(vr_arr[i]) else 1.0
        bw  = float(bw_arr[i])  if not np.isnan(bw_arr[i]) else 0.05
        pp  = float(pp_arr[i])  if not np.isnan(pp_arr[i]) else 0.5

        reg = classify_regime_row(c, r)
        ph  = classify_phase_row(c, s, m, l, mom, vr, bw, pp)
        al  = classify_alignment_row(c, s, m, l, r)
        cf  = classify_confidence_row(c, m, vr)

        regimes.append(reg); phases.append(ph)
        alignments.append(al); confs.append(cf)

        # ── FCE引擎 v1 (原始权重) ──
        res1 = engine.evaluate(
            Regime.from_str(reg), Phase.from_str(ph),
            MTFAlignment.from_str(al), Confidence.from_str(cf),
            holding_days=90,
        )
        # ── FCE引擎 v2 (校准版) ──
        res2 = engine.evaluate_v2(
            Regime.from_str(reg), Phase.from_str(ph),
            MTFAlignment.from_str(al), Confidence.from_str(cf),
        )

        if res1.risk_level == "excluded":
            sig_raw[i] = 0.0
        elif res1.direction in ("做多", "观察等待"):
            sig_raw[i] = res1.position_size
        else:
            sig_raw[i] = 0.0

        # ── FCE v2 (校准版) ──
        if res2.risk_level == "excluded":
            sig_v2[i] = 0.0
        else:
            sig_v2[i] = res2.position_size

        # ── 其他信号 ──
        if reg == "bull" and al == "fully_aligned":
            sig_trend[i] = 0.9
        if ph == "markup":
            sig_markup[i] = 0.8
        if ph == "markdown":
            sig_markdn[i] = 0.7

    # 任意正信号 = max of all positive signals (原版, 保留对比)
    sig_allpos = np.maximum(sig_v2, sig_trend)
    sig_allpos = np.maximum(sig_allpos, sig_markup * 0.5)
    sig_allpos = np.maximum(sig_allpos, sig_markdn * 0.5)

    # sig_v3: 纯制度策略 (验证phase是否有增量价值)
    sig_v3 = np.zeros(n)
    for i in range(n):
        r = regimes[i]
        if r == "bull":
            sig_v3[i] = 0.85
        elif r == "range":
            sig_v3[i] = 0.50
        # bear = 0.0

    # 写回df
    df["regime"] = regimes; df["phase"] = phases
    df["alignment"] = alignments; df["confidence"] = confs
    df["sig_raw"] = sig_raw
    df["sig_v2"] = sig_v2
    df["sig_trend"] = sig_trend
    df["sig_markup"] = sig_markup
    df["sig_markdown"] = sig_markdn
    df["sig_allpos"] = sig_allpos
    df["sig_v3"] = sig_v3

    return df, regimes, phases, alignments, confs


# ═══════════════════════════════════════════════════════════
#  4. 带确认机制的回测
# ═══════════════════════════════════════════════════════════

def backtest_with_confirmation(df, signal_col, label,
                               enter_days=3, exit_days=3,
                               max_exit_days=None):
    """
    带 N日确认 的回测:
    - 连续 enter_days 天信号>阈值 → 买入
    - 连续 exit_days 天信号≤阈值 → 卖出
    - 持仓期间仓位=信号值
    - max_exit_days: 持仓最长天数, 超过后强制退出
    """
    n = len(df)
    closes = df["close"].values
    signals = df[signal_col].values
    dates = df["date"].values

    equity = np.ones(n)
    position = 0.0
    pos_days = 0   # 当前持仓天数
    trades = []

    def _in(p, d):
        """连续 d 天中信号>阈值的比例 > 50%?"""
        if p < d: return False
        cnt = sum(1 for j in range(p-d, p) if signals[j] > 0.05)
        return cnt >= d - 1  # 宽松: d-1天信号有效即可

    def _out(p, d):
        if p < d: return True
        cnt = sum(1 for j in range(p-d, p) if signals[j] <= 0.05)
        return cnt >= d - 1

    for i in range(1, n):
        pos_days = i - trades[-1]["idx"] if trades and trades[-1]["type"] == "buy" else 0

        if position == 0:
            if _in(i, enter_days):
                position = min(float(signals[i]), 1.0)
                if position < 0.2:
                    position = 0.0
                    continue
                trades.append({"date": str(dates[i])[:10], "type": "buy",
                               "price": closes[i], "size": position, "idx": i})
        else:
            exit_reason = None
            if max_exit_days and pos_days >= max_exit_days:
                exit_reason = f"max_hold_{max_exit_days}d"
            elif _out(i, exit_days):
                exit_reason = "signal_lost"

            if exit_reason:
                trades.append({"date": str(dates[i])[:10], "type": "sell",
                               "price": closes[i], "size": position, "reason": exit_reason, "idx": i})
                position = 0.0
            else:
                position = min(float(signals[i]), 1.0)

        daily_ret = closes[i] / closes[i-1] - 1
        equity[i] = equity[i-1] * (1 + daily_ret * position)

    # 清算
    if position > 0:
        trades.append({"date": str(dates[-1])[:10], "type": "sell_force",
                       "price": closes[-1], "size": position, "idx": n-1})

    return _calc_metrics(equity, n, closes, trades, label), trades, equity


def _calc_metrics(equity, n, closes, trades, label):
    total_ret = equity[-1] / equity[0] - 1
    years = n / 245
    annual_ret = (1 + total_ret) ** (1 / years) - 1 if years > 0 else 0
    daily_rets = np.array([equity[i] / equity[i-1] - 1 for i in range(1, n)])
    win_rate = float(np.mean(daily_rets > 0)) * 100
    sharpe = float(np.mean(daily_rets) / np.std(daily_rets) * np.sqrt(245)) if np.std(daily_rets) > 1e-10 else 0
    peak = np.maximum.accumulate(equity)
    dd = (equity - peak) / peak
    max_dd = float(np.min(dd)) * 100
    calmar = annual_ret / (abs(max_dd) / 100) if max_dd < 0 and abs(max_dd) > 0.1 else 0

    invested_days = sum(1 for i in range(1, n) if equity[i] != equity[i-1] and daily_rets[i-1] != 0)
    invested_pct = invested_days / n * 100 if n > 0 else 0

    return {
        "label": label,
        "total_return": round(total_ret * 100, 1),
        "annual_return": round(annual_ret * 100, 1),
        "win_rate": round(win_rate, 1),
        "sharpe": round(sharpe, 3),
        "max_drawdown": round(max_dd, 1),
        "calmar": round(calmar, 2),
        "invested_pct": round(invested_pct, 1),
        "trades": sum(1 for t in trades if t["type"] in ("buy","sell")),
        "n_trades": len([t for t in trades if t["type"] in ("buy",)]),
    }


# ═══════════════════════════════════════════════════════════
#  5. 主流程
# ═══════════════════════════════════════════════════════════

def main():
    print("=" * 70)
    print("  因子组合实盘验证 v3")
    print("  ======================")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 70)

    # ─── 5a. 加载 & 指标 ───
    print("\n[1/5] 加载数据 & 计算指标...")
    df = load_and_prepare()
    cfg = InvestmentSignalConfig()
    df = compute_indicators(df, cfg)
    df = add_extra_indicators(df)
    n = len(df)
    print(f"  932000.SH, {n} 行, {df['date'].min().date()} ~ {df['date'].max().date()}")
    print(f"  列数: {len(df.columns)}")

    # ─── 5b. 因子分类 & 信号生成 ───
    print("\n[2/5] 因子分类 & 信号生成...")
    df, regimes, phases, alignments, confs = generate_signals(df)
    c_arr = df["close"].values

    # 分类统计
    regime_dist = pd.Series(regimes).value_counts()
    phase_dist  = pd.Series(phases).value_counts()
    align_dist  = pd.Series(alignments).value_counts()
    conf_dist   = pd.Series(confs).value_counts()

    print(f"  制度: {regime_dist.to_dict()}")
    print(f"  相位: {phase_dist.to_dict()}")
    print(f"  对齐: {align_dist.to_dict()}")
    print(f"  置信度: {conf_dist.to_dict()}")

    # ─── 5c. 因子组合收益分解 ───
    print("\n[3/5] 因子组合收益分解...")
    combo_rets = defaultdict(list)
    for i in range(1, n):
        dr = c_arr[i] / c_arr[i-1] - 1
        if df["sig_raw"].iloc[i] > 0:
            key = f"{regimes[i]}+{phases[i]}+{alignments[i]}+{confs[i]}"
            combo_rets[key].append(dr * df["sig_raw"].iloc[i])

    combo_stats = []
    for combo, rets in combo_rets.items():
        if len(rets) < 10:
            continue
        arr = np.array(rets)
        combo_stats.append({
            "combo": combo, "days": len(rets),
            "avg_daily": round(float(np.mean(arr)) * 100, 3),
            "cum_return": round((np.prod(1 + arr) - 1) * 100, 1),
            "win_rate": round(float(np.mean(arr > 0)) * 100, 1),
        })
    combo_stats.sort(key=lambda x: x["cum_return"], reverse=True)

    print(f"  {'组合':<45} {'天数':>5} {'日均%':>7} {'累积%':>8} {'胜率':>6}")
    print("  " + "-" * 78)
    for cs in combo_stats[:12]:
        flag = " ★" if cs["cum_return"] > 50 else ""
        print(f"  {cs['combo']:<45} {cs['days']:>5} {cs['avg_daily']:>6.3f}% {cs['cum_return']:>7.1f}% {cs['win_rate']:>5.1f}%{flag}")

    # ─── 5d. 回测 ───
    print("\n[4/5] 回测 (确认机制: 入场3天, 出场3天)...")

    # 基线: 买入持有
    bh_ret = c_arr[-1] / c_arr[0] - 1
    bh_yrs = n / 245
    bh_ann = (1 + bh_ret) ** (1 / bh_yrs) - 1
    bh_daily = np.array([c_arr[i] / c_arr[i-1] - 1 for i in range(1, n)])
    bh_win = float(np.mean(bh_daily > 0)) * 100
    bh_sharpe = float(np.mean(bh_daily) / np.std(bh_daily) * np.sqrt(245)) if np.std(bh_daily) > 1e-10 else 0
    bh_eq = np.cumprod(1 + bh_daily)
    bh_dd = (bh_eq - np.maximum.accumulate(bh_eq)) / np.maximum.accumulate(bh_eq)
    bh_mdd = float(np.min(bh_dd)) * 100
    bh_calmar = bh_ann / (abs(bh_mdd)/100) if bh_mdd < -0.1 else 0

    bh_result = {
        "label": "买入持有", "total_return": round(bh_ret*100,1),
        "annual_return": round(bh_ann*100,1), "win_rate": round(bh_win,1),
        "sharpe": round(bh_sharpe,3), "max_drawdown": round(bh_mdd,1),
        "calmar": round(bh_calmar,2), "invested_pct": 100.0,
        "trades": 0, "n_trades": 0,
    }

    # 策略回测
    # 带确认 vs 无确认对比
    strategies = [
        ("sig_raw",     "FCE v1(原始)"),
        ("sig_v2",      "FCE v2(校准)"),
        ("sig_v3",      "纯制度策略"),
        ("sig_trend",   "趋势跟踪"),
        ("sig_allpos",  "任意正信号"),
        ("sig_markup",  "牛市做多"),
        ("sig_markdown","熊市做多"),
    ]

    results = [bh_result]
    eq_curves = {"买入持有": bh_eq}

    for col, label in strategies:
        r, trades, eq = backtest_with_confirmation(df, col, label + "(确认)")
        results.append(r)
        eq_curves[label + "(确认)"] = eq

    # 无确认对比: 仅做"任意正信号"无确认版本
    def backtest_naive(df, signal_col, label):
        """无确认: 每天根据信号调整仓位"""
        n = len(df)
        closes = df["close"].values
        signals = df[signal_col].values
        equity = np.ones(n)
        position = 0.0
        for i in range(1, n):
            sig = signals[i]
            target = min(max(sig, 0.0), 1.0) if sig > 0.01 else 0.0
            position = target
            daily_ret = closes[i] / closes[i-1] - 1
            equity[i] = equity[i-1] * (1 + daily_ret * position)
        return _calc_metrics(equity, n, closes, [], label), equity

    r_naive_v1, eq_n_v1 = backtest_naive(df, "sig_raw", "FCE v1(无确认)")
    r_naive_v2, eq_n_v2 = backtest_naive(df, "sig_v2", "FCE v2(无确认)")
    r_naive_v3, eq_n_v3 = backtest_naive(df, "sig_v3", "纯制度策略(无确认)")
    r_naive_a, eq_n_a = backtest_naive(df, "sig_allpos", "任意正信号(无确认)")
    results.extend([r_naive_v1, r_naive_v2, r_naive_v3, r_naive_a])
    eq_curves["FCE v1(无确认)"] = eq_n_v1
    eq_curves["FCE v2(无确认)"] = eq_n_v2
    eq_curves["纯制度策略(无确认)"] = eq_n_v3
    eq_curves["任意正信号(无确认)"] = eq_n_a

    # 输出
    print(f"\n  {'策略':<34} {'总收益':>7} {'年化':>6} {'胜率':>5} {'夏普':>6} {'回撤':>6} {'Calmar':>7} {'持仓%':>6} {'交易':>5}")
    print("  " + "-" * 90)
    sorted_res = sorted(results, key=lambda x: x["calmar"], reverse=True)
    for r in sorted_res:
        best = " <<<" if r == sorted_res[0] else ""
        print(f"  {r['label']:<34} {r['total_return']:>6.1f}% {r['annual_return']:>5.1f}% "
              f"{r['win_rate']:>4.1f}% {r['sharpe']:>5.3f} {r['max_drawdown']:>5.1f}% "
              f"{r['calmar']:>6.2f} {r['invested_pct']:>5.1f}% {r['n_trades']:>4}{best}")

    # ─── 5e. 月度分析 & 信号诊断 ───
    print("\n[5/5] 月度分析 & 信号诊断...")

    # 信号诊断: 各信号列的统计
    signal_cols = ["sig_raw", "sig_v2", "sig_v3", "sig_trend", "sig_markup", "sig_markdown", "sig_allpos"]
    print(f"\n  信号列统计 (均值 > 0 占比):")
    for col in signal_cols:
        arr = df[col].values
        active = (arr > 0.01).mean() * 100
        mean_val = arr.mean()
        print(f"  {col:<20} 激活率: {active:5.1f}% | 均值: {mean_val:.3f}")

    # 月度分析
    months = [str(d)[:7] for d in df["date"].values[1:]]
    best_label = sorted_res[0]["label"]
    if best_label not in eq_curves:
        for k in ["买入持有", "趋势跟踪(bull+fully_aligned)(确认)", "趋势跟踪"]:
            if k in eq_curves:
                best_label = k
                break
    best_eq = eq_curves.get(best_label, bh_eq)
    # 确保长度一致
    min_len = min(len(months), len(bh_daily), len(best_eq) - 1)
    best_daily = np.array([best_eq[i] / best_eq[i-1] - 1 for i in range(1, min_len + 1)])
    df_m = pd.DataFrame({
        "month": months[:min_len],
        "buy_hold": bh_daily[:min_len],
        "best": best_daily,
    })
    monthly = df_m.groupby("month").sum()
    bh_pos = (monthly["buy_hold"] > 0).sum()
    st_pos = (monthly["best"] > 0).sum()
    print(f"\n  最佳策略: {best_label}")
    print(f"  买入持有正月: {bh_pos}/{len(monthly)} ({bh_pos/len(monthly)*100:.1f}%)")
    print(f"  策略正月:     {st_pos}/{len(monthly)} ({st_pos/len(monthly)*100:.1f}%)")
    print(f"  月均(买持): {monthly['buy_hold'].mean()*100:+.2f}%")
    print(f"  月均(策略): {monthly['best'].mean()*100:+.2f}%")

    # ─── 结论 ───
    print("\n" + "=" * 70)
    print("  验证结论")
    print("=" * 70)

    bh_r = bh_result

    def _find_r(label_sub):
        for r in sorted_res:
            if label_sub in r["label"]:
                return r
        return None

    r_v1 = _find_r("FCE v1(无确认)") or bh_r
    r_v2 = _find_r("FCE v2(无确认)") or bh_r
    r_v3 = _find_r("纯制度策略(无确认)") or bh_r
    r_ap = _find_r("任意正信号(无确认)") or bh_r

    print(f"""
  1. 策略排名 (Calmar排序):

     {'策略':<28} {'年化':>6} {'回撤':>6} {'夏普':>6} {'Calmar':>7} {'持仓':>5}
     {'-'*65}
""")
    for r in sorted_res[:8]:
        print(f"     {r['label']:<28} {r['annual_return']:>5.1f}% {-r['max_drawdown']:>4.0f}% {r['sharpe']:>5.3f} {r['calmar']:>6.2f} {r['invested_pct']:>4.0f}%")
    print(f"""
  2. 策略对比 (无确认):
     v1 (原始权重):   {r_v1['annual_return']:.1f}%年化 | {-r_v1['max_drawdown']:.0f}%回撤 | 夏普{r_v1['sharpe']:.2f}
     v2 (校准+range): {r_v2['annual_return']:.1f}%年化 | {-r_v2['max_drawdown']:.0f}%回撤 | 夏普{r_v2['sharpe']:.2f}
     v3 (纯制度):     {r_v3['annual_return']:.1f}%年化 | {-r_v3['max_drawdown']:.0f}%回撤 | 夏普{r_v3['sharpe']:.2f}
     任意正信号:      {r_ap['annual_return']:.1f}%年化 | {-r_ap['max_drawdown']:.0f}%回撤 | 夏普{r_ap['sharpe']:.2f}
     {'✅ v2校准有效(+range不排除)' if r_v2['annual_return'] > r_v1['annual_return'] else '❌ v2未改善'}
     {'✅ v3纯制度说明phase有增量价值' if r_v3['annual_return'] < r_v2['annual_return'] else '❌ phase无增量价值'}

  3. vs买入持有:
     买入持有: {bh_r['annual_return']:.1f}%年化 | {-bh_r['max_drawdown']:.0f}%回撤 | 夏普{bh_r['sharpe']:.2f}
     最佳策略: {r_ap['label']} {r_ap['annual_return']:.1f}%年化 | {-r_ap['max_drawdown']:.0f}%回撤 | 夏普{r_ap['sharpe']:.2f}

  4. 因子组合有效性:
     有效组合数: {len(combo_stats)} 个
     最强组合: {combo_stats[0]['combo'] if combo_stats else 'N/A'} ({combo_stats[0]['cum_return']}% / {combo_stats[0]['win_rate']}%胜率)
     相位覆盖率: {sum(1 for p in phases if p != 'unknown')}/{n} ({sum(1 for p in phases if p != 'unknown')/n*100:.1f}%)
""")

    output = {
        "config": {"data": "932000.SH", "rows": n,
                   "period": f"{df['date'].min().date()}~{df['date'].max().date()}"},
        "factor_distribution": {
            "regime": regime_dist.to_dict(), "phase": phase_dist.to_dict(),
            "alignment": align_dist.to_dict(), "confidence": conf_dist.to_dict(),
        },
        "backtest": [
            {k: v for k, v in r.items() if k != "trades"}
            for r in sorted_res
        ],
        "top_combos": combo_stats[:10],
    }
    Path("output/validate_factor_combinations.json").write_text(
        json.dumps(output, ensure_ascii=False, indent=2))
    print(f"\n  结果已保存: output/validate_factor_combinations.json")


if __name__ == "__main__":
    main()
