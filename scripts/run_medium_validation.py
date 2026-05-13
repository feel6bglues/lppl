#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Wyckoff 策略中型验证测试
========================
- 1,000只A股 × 20个随机时间窗口 × 180天持有
- 使用修正后的Wyckoff交易逻辑（支撑位入场/止损止盈/NTZ过滤）
- 基准：沪深300指数
- 数据源：本地通达信日线（2012-2025）
"""

import csv
import json
import random
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
from src.data.manager import DataManager
from src.data.tdx_loader import load_tdx_data
from src.wyckoff.engine import WyckoffEngine
from src.wyckoff.trading import calculate_wyckoff_return
from src.parallel import get_optimal_workers, worker_init
from scripts.utils.tdx_config import CSI300_PATH, TDX_BASE, TDX_SH_DIR, TDX_SZ_DIR


OUTPUT_DIR = PROJECT_ROOT / "output" / "wyckoff_full_validation_90d"
N_STOCKS = 99999  # 全量A股
N_WINDOWS = 20
HOLD_DAYS = 90
SEED = 42
N_BOOTSTRAP = 2000
CSI300_TDX_PATH = Path("/home/james/.local/share/tdxcfv/drive_c/tc/vipdoc/sh/lday/sh000300.day")


def load_stocks(csv_path: Path, limit: int = N_STOCKS) -> List[Dict[str, str]]:
    symbols = []
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            code = str(row.get("code", "")).strip()
            market = str(row.get("market", "")).strip().upper()
            name = str(row.get("name", "")).replace("\x00", "").strip()
            if not (code.isdigit() and len(code) == 6 and market in {"SH", "SZ"}):
                continue
            if code.startswith(("600", "601", "603", "605", "688", "689",
                               "000", "001", "002", "003", "300", "301", "302")):
                symbols.append({"symbol": f"{code}.{market}", "code": code, "market": market, "name": name})
            if len(symbols) >= limit:
                break
    return symbols


def generate_windows(csi300_df: pd.DataFrame, n: int = N_WINDOWS, hold_days: int = HOLD_DAYS) -> List[str]:
    """从沪深300实际交易日期中抽取N个时间窗口"""
    if csi300_df is None or len(csi300_df) < hold_days:
        return []
    # 过滤掉最后hold_days个交易日（保留未来数据用于验证）
    trading_dates = csi300_df["date"].dt.strftime("%Y-%m-%d").tolist()
    available = trading_dates[:len(trading_dates) - hold_days]
    random.seed(SEED)
    return sorted(random.sample(available, min(n, len(available))))


def load_csi300() -> Optional[pd.DataFrame]:
    """加载沪深300指数"""
    if CSI300_TDX_PATH.exists():
        df = load_tdx_data(str(CSI300_TDX_PATH))
        if df is not None and not df.empty:
            df["date"] = pd.to_datetime(df["date"])
            df = df.sort_values("date").reset_index(drop=True)
            return df
    return None


def classify_market_regime(index_data: pd.DataFrame, as_of_date: str) -> str:
    as_of = pd.Timestamp(as_of_date)
    hist = index_data[index_data["date"] <= as_of]
    if len(hist) < 120:
        return "unknown"
    close = float(hist.iloc[-1]["close"])
    ma120 = float(hist.tail(120)["close"].mean())
    ma60 = float(hist.tail(60)["close"].mean())
    if close > ma120 * 1.02 and ma60 > ma120:
        return "bull"
    elif close < ma120 * 0.98:
        return "bear"
    else:
        return "range"


def process_stock(args) -> List[Dict]:
    """处理单只股票的所有时间窗口"""
    symbol_info, windows, csi300_df = args
    symbol = symbol_info["symbol"]
    name = symbol_info["name"]
    results = []
    try:
        dm = DataManager()
        df = dm.get_data(symbol)
        if df is None or df.empty or len(df) < 300:
            return results
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)

        engine = WyckoffEngine(lookback_days=400, weekly_lookback=120, monthly_lookback=40)

        for as_of_date in windows:
            as_of = pd.Timestamp(as_of_date)
            available = df[df["date"] <= as_of]
            if len(available) < 100:
                continue

            report = engine.analyze(available, symbol=symbol, period="日线", multi_timeframe=True)

            rr = report.risk_reward
            wyckoff_entry = rr.entry_price if rr and rr.entry_price and rr.entry_price > 0 else None
            stop_loss = rr.stop_loss if rr and rr.stop_loss and rr.stop_loss > 0 else None
            first_target = rr.first_target if rr and rr.first_target and rr.first_target > 0 else None
            sig = report.signal.signal_type
            is_no_trade = sig == "no_signal" or report.trading_plan.direction == "空仓观望"

            phase = report.structure.phase.value
            alignment = report.multi_timeframe.alignment if report.multi_timeframe else ""
            direction = report.trading_plan.direction
            confidence = report.trading_plan.confidence.value

            ret = calculate_wyckoff_return(df, as_of_date, HOLD_DAYS,
                                           wyckoff_entry=wyckoff_entry,
                                           stop_loss=stop_loss,
                                           first_target=first_target)
            if ret is None:
                continue

            # 基准收益（沪深300）
            benchmark_ret = None
            if csi300_df is not None:
                bm_future = csi300_df[csi300_df["date"] > as_of].head(HOLD_DAYS)
                if len(bm_future) >= HOLD_DAYS * 0.8:
                    bm_entry = float(csi300_df[csi300_df["date"] <= as_of].iloc[-1]["close"])
                    bm_exit = float(bm_future.iloc[-1]["close"])
                    benchmark_ret = round((bm_exit - bm_entry) / bm_entry * 100, 2)

            market_regime = classify_market_regime(csi300_df, as_of_date) if csi300_df is not None else "unknown"

            results.append({
                "symbol": symbol, "name": name, "as_of": as_of_date,
                "phase": phase, "signal_type": sig, "is_no_trade": is_no_trade,
                "direction": direction, "confidence": confidence,
                "alignment": alignment, "market_regime": market_regime,
                "wyckoff_entry_price": round(wyckoff_entry, 3) if wyckoff_entry else None,
                "stop_loss": round(stop_loss, 3) if stop_loss else None,
                "first_target": round(first_target, 3) if first_target else None,
                "exit_reason": ret.get("exit_reason", "hold_to_end"),
                "hit_stop": ret.get("hit_stop", False),
                "hit_target": ret.get("hit_target", False),
                "return_180d": ret["return_pct"],
                "max_gain_180d": ret["max_gain_pct"],
                "max_drawdown_180d": ret["max_drawdown_pct"],
                "benchmark_180d_return": benchmark_ret,
                "excess_return": round(ret["return_pct"] - benchmark_ret, 2) if benchmark_ret is not None else None,
            })
    except Exception:
        pass
    return results


def bootstrap_ci(data: np.ndarray, n=N_BOOTSTRAP, confidence=0.95) -> Tuple[float, float, float]:
    if len(data) < 10:
        return np.nan, np.nan, np.nan
    means = [np.mean(np.random.choice(data, size=len(data), replace=True)) for _ in range(n)]
    return np.mean(means), np.percentile(means, (1 - confidence) / 2 * 100), np.percentile(means, (1 + confidence) / 2 * 100)


def run():
    print("=" * 70)
    print("Wyckoff 策略全量验证测试")
    print(f"  全量A股 | 时间窗口: {N_WINDOWS} | 持有期: {HOLD_DAYS}天")
    print(f"  基准: 沪深300 | 数据: 本地通达信日线 2012-2025")
    print("=" * 70)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # 加载股票列表
    csv_path = PROJECT_ROOT / "data" / "stock_list.csv"
    stocks = load_stocks(csv_path, N_STOCKS)
    print(f"\n加载 {len(stocks)} 只股票")

    # 加载沪深300
    csi300 = load_csi300()
    print(f"沪深300数据: {'已加载' if csi300 is not None else '不可用'} ({len(csi300) if csi300 is not None else 0}行)")

    # 生成时间窗口（基于沪深300实际交易日）
    windows = generate_windows(csi300, N_WINDOWS, HOLD_DAYS)
    print(f"生成 {len(windows)} 个时间窗口")
    print(f"沪深300数据: {'已加载' if csi300 is not None else '不可用'} ({len(csi300) if csi300 is not None else 0}行)")
    print()
    all_results = []
    max_workers = get_optimal_workers()
    batch_size = max_workers * 4
    args_list = [(s, windows, csi300) for s in stocks]

    with ProcessPoolExecutor(max_workers=max_workers, initializer=worker_init) as executor:
        for batch_start in range(0, len(args_list), batch_size):
            batch = args_list[batch_start:batch_start + batch_size]
            futures = {executor.submit(process_stock, a): a[0]["symbol"] for a in batch}
            for future in as_completed(futures):
                try:
                    results = future.result(timeout=300)
                    all_results.extend(results)
                except Exception:
                    pass
            progress = min(batch_start + batch_size, len(args_list))
            print(f"  进度: {progress}/{len(stocks)} 只股票, 已收集 {len(all_results)} 样本")

    print(f"\n总样本数: {len(all_results)}")
    if not all_results:
        print("无有效样本，退出")
        return

    df = pd.DataFrame(all_results)
    returns_all = df["return_180d"].values
    mean_ret, ci_low, ci_high = bootstrap_ci(returns_all)
    tradeable = df[~df["is_no_trade"]]
    n_no_trade = int(df["is_no_trade"].sum())

    # 综合统计
    analysis = {
        "config": {"n_stocks": N_STOCKS, "n_windows": N_WINDOWS, "hold_days": HOLD_DAYS},
        "overall_stats": {
            "n_samples": len(df), "mean_return": round(mean_ret, 2),
            "ci_lower": round(ci_low, 2), "ci_upper": round(ci_high, 2),
            "median_return": round(np.median(returns_all), 2),
            "win_rate": round(sum(returns_all > 0) / len(returns_all) * 100, 1),
            "std_return": round(np.std(returns_all), 2),
            "n_no_trade": n_no_trade,
            "no_trade_rate": round(n_no_trade / len(df) * 100, 1),
        },
        "tradeable_stats": {},
        "phase_analysis": {},
        "regime_analysis": {},
        "alignment_analysis": {},
        "exit_reason_analysis": {},
        "benchmark_comparison": {},
        "seed_details": {},
    }

    if len(tradeable) >= 10:
        t_ret = tradeable["return_180d"].values
        t_mean, t_ci_l, t_ci_h = bootstrap_ci(t_ret)
        analysis["tradeable_stats"] = {
            "n_samples": len(tradeable), "mean_return": round(t_mean, 2),
            "ci_lower": round(t_ci_l, 2), "ci_upper": round(t_ci_h, 2),
            "win_rate": round(sum(t_ret > 0) / len(t_ret) * 100, 1),
        }

    # 阶段分析
    for phase in df["phase"].unique():
        vals = df[df["phase"] == phase]["return_180d"].values
        if len(vals) >= 10:
            m, l, h = bootstrap_ci(vals)
            analysis["phase_analysis"][phase] = {
                "n_samples": len(vals), "mean_return": round(m, 2),
                "ci_lower": round(l, 2), "ci_upper": round(h, 2),
                "win_rate": round(sum(vals > 0) / len(vals) * 100, 1),
            }

    # 市场状态分析
    for regime in df["market_regime"].unique():
        vals = df[df["market_regime"] == regime]["return_180d"].values
        if len(vals) >= 10:
            m, l, h = bootstrap_ci(vals)
            analysis["regime_analysis"][regime] = {
                "n_samples": len(vals), "mean_return": round(m, 2),
                "win_rate": round(sum(vals > 0) / len(vals) * 100, 1),
            }

    # 对齐方式分析
    for align in df["alignment"].unique():
        if not align:
            continue
        vals = df[df["alignment"] == align]["return_180d"].values
        if len(vals) >= 10:
            analysis["alignment_analysis"][align] = {
                "n_samples": len(vals), "mean_return": round(np.mean(vals), 2),
                "win_rate": round(sum(vals > 0) / len(vals) * 100, 1),
            }

    # 交叉分析: Phase × Regime
    cross_keys = df["phase"].unique()
    regime_keys = df["market_regime"].unique()
    analysis["phase_regime_cross"] = {}
    for p in cross_keys:
        for r in regime_keys:
            sub = df[(df["phase"] == p) & (df["market_regime"] == r)]
            vals = sub["return_180d"].values
            if len(vals) >= 10:
                m, l, h = bootstrap_ci(vals)
                analysis["phase_regime_cross"][f"{p}_{r}"] = {
                    "n_samples": len(vals), "mean_return": round(m, 2),
                    "ci_lower": round(l, 2), "ci_upper": round(h, 2),
                    "win_rate": round(sum(vals > 0) / len(vals) * 100, 1),
                }

    # 交叉分析: Phase × Alignment
    align_keys = [a for a in df["alignment"].unique() if a]
    analysis["phase_alignment_cross"] = {}
    for p in cross_keys:
        for a in align_keys:
            sub = df[(df["phase"] == p) & (df["alignment"] == a)]
            vals = sub["return_180d"].values
            if len(vals) >= 10:
                analysis["phase_alignment_cross"][f"{p}_{a}"] = {
                    "n_samples": len(vals), "mean_return": round(np.mean(vals), 2),
                    "win_rate": round(sum(vals > 0) / len(vals) * 100, 1),
                }

    # 交叉分析: Regime × Alignment
    analysis["regime_alignment_cross"] = {}
    for r in regime_keys:
        for a in align_keys:
            sub = df[(df["market_regime"] == r) & (df["alignment"] == a)]
            vals = sub["return_180d"].values
            if len(vals) >= 10:
                analysis["regime_alignment_cross"][f"{r}_{a}"] = {
                    "n_samples": len(vals), "mean_return": round(np.mean(vals), 2),
                    "win_rate": round(sum(vals > 0) / len(vals) * 100, 1),
                }

    # 退出原因分析
    for reason in df["exit_reason"].unique():
        vals = df[df["exit_reason"] == reason]["return_180d"].values
        analysis["exit_reason_analysis"][reason] = {
            "n_samples": len(vals), "mean_return": round(np.mean(vals), 2),
            "win_rate": round(sum(vals > 0) / len(vals) * 100, 1),
            "pct_of_total": round(len(vals) / len(df) * 100, 1),
        }

    # 基准对比
    if "excess_return" in df.columns and df["excess_return"].notna().sum() >= 10:
        excess = df["excess_return"].dropna().values
        analysis["benchmark_comparison"] = {
            "strategy_mean_return": round(np.mean(returns_all), 2),
            "benchmark_mean_return": round(np.mean(df["benchmark_180d_return"].dropna()), 2),
            "excess_return_mean": round(np.mean(excess), 2),
            "excess_return_median": round(np.median(excess), 2),
            "excess_return_win_rate": round(sum(excess > 0) / len(excess) * 100, 1),
        }

    # 最佳/最差组合
    top = df.nlargest(5, "return_180d")
    bottom = df.nsmallest(5, "return_180d")
    analysis["best_samples"] = top[["symbol", "phase", "market_regime", "alignment", "return_180d"]].to_dict("records")
    analysis["worst_samples"] = bottom[["symbol", "phase", "market_regime", "alignment", "return_180d"]].to_dict("records")

    # 保存JSON
    json_path = OUTPUT_DIR / "validation_results.json"
    with json_path.open("w", encoding="utf-8") as f:
        json.dump(analysis, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n结果已保存: {json_path}")

    # 输出摘要
    os = analysis["overall_stats"]
    print(f"\n{'='*70}")
    print("测试摘要:")
    print(f"  总样本: {os['n_samples']} | No Trade Zone过滤: {os['n_no_trade']}({os['no_trade_rate']}%)")
    print(f"  {HOLD_DAYS}天平均收益: {os['mean_return']:.2f}%")
    print(f"  95%CI: [{os['ci_lower']:.2f}%, {os['ci_upper']:.2f}%]")
    print(f"  中位收益: {os['median_return']:.2f}%")
    print(f"  胜率: {os['win_rate']:.1f}%")
    print(f"  标准差: {os['std_return']:.2f}%")

    if analysis["tradeable_stats"]:
        ts = analysis["tradeable_stats"]
        print(f"\n  [可交易样本] 收益: {ts['mean_return']:.2f}%  胜率: {ts['win_rate']:.1f}%")

    if analysis["benchmark_comparison"]:
        bc = analysis["benchmark_comparison"]
        print(f"\n  [基准对比] 策略: {bc['strategy_mean_return']:.2f}% vs 沪深300: {bc['benchmark_mean_return']:.2f}%")
        print(f"  超额收益: {bc['excess_return_mean']:.2f}%  超额胜率: {bc['excess_return_win_rate']:.1f}%")

    print(f"\n  阶段分析:")
    for p, s in sorted(analysis["phase_analysis"].items(), key=lambda x: -x[1]["mean_return"]):
        print(f"    {p:15s}: 收益={s['mean_return']:6.2f}%  胜率={s['win_rate']:5.1f}%  n={s['n_samples']}")

    print(f"\n  市场状态分析:")
    for r, s in sorted(analysis["regime_analysis"].items(), key=lambda x: -x[1]["mean_return"]):
        print(f"    {r:6s}: 收益={s['mean_return']:6.2f}%  胜率={s['win_rate']:5.1f}%  n={s['n_samples']}")

    print(f"\n  退出原因分析:")
    for r, s in sorted(analysis["exit_reason_analysis"].items(), key=lambda x: -x[1]["mean_return"]):
        print(f"    {r:15s}: 收益={s['mean_return']:6.2f}%  胜率={s['win_rate']:5.1f}%  占比={s['pct_of_total']:5.1f}%")

    if "phase_regime_cross" in analysis:
        print(f"\n  Phase×Regime交叉分析:")
        cross_sorted = sorted(analysis["phase_regime_cross"].items(), key=lambda x: -x[1]["mean_return"])
        for k, s in cross_sorted[:8]:
            print(f"    {k:25s}: 收益={s['mean_return']:6.2f}%  胜率={s['win_rate']:5.1f}%  n={s['n_samples']}")
        print(f"    ... 共{len(analysis['phase_regime_cross'])}个组合")

    print(f"\n{'='*70}")
    print("测试完成")
    print(f"{'='*70}")


if __name__ == "__main__":
    run()
