#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
纯Wyckoff优化回测

对比两组:
A. 原始Wyckoff (当前引擎)
B. 优化Wyckoff (五项优化)

基于6组回测数据的优化:
1. 做多方向反转
2. markup阶段屏蔽
3. 置信度反转(D加分/C降级)
4. MTF对齐过滤
5. Accumulation窗口切换
"""

from __future__ import annotations

import csv
import json
import os
import random
import struct
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import psutil

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@dataclass(frozen=True)
class CycleSpec:
    cycle_id: int
    year: int
    as_of_date: str
    description: str


@dataclass
class BacktestConfig:
    start_date: str = "2012-01-01"
    end_date: str = "2025-12-31"
    n_cycles: int = 10
    future_days: int = 120
    seed: int = 42
    lookback_min: int = 400
    max_workers: int = -1

    def __post_init__(self):
        if self.max_workers == -1:
            self.max_workers = max(2, (os.cpu_count() or 4) - 2)


def get_optimal_workers():
    cpu_count = psutil.cpu_count(logical=True)
    memory = psutil.virtual_memory()
    available_mb = memory.available / (1024 ** 2)
    max_by_memory = int(available_mb / 500)
    return max(2, min(max_by_memory, max(1, cpu_count - 2), 10))


def load_stock_symbols(csv_path, limit=99999):
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


def detect_bubble_periods(index_df):
    df = index_df.copy()
    df["ma60"] = df["close"].rolling(60).mean()
    df["returns"] = df["close"].pct_change()
    df["volatility"] = df["returns"].rolling(20).std()
    df["high_120"] = df["close"].rolling(120).max()
    df["low_120"] = df["close"].rolling(120).min()
    df["relative_position"] = (df["close"] - df["low_120"]) / (df["high_120"] - df["low_120"])
    bubble_periods = []
    for i in range(120, len(df)):
        row = df.iloc[i]
        is_bubble = False
        if pd.notna(row["ma60"]) and row["ma60"] > 0 and (row["close"] - row["ma60"]) / row["ma60"] > 0.20:
            is_bubble = True
        if pd.notna(row["volatility"]) and row["volatility"] > 0.03:
            is_bubble = True
        if pd.notna(row["relative_position"]) and row["relative_position"] > 0.95:
            is_bubble = True
        if is_bubble:
            start_idx = max(0, i - 30)
            end_idx = min(len(df) - 1, i + 30)
            bubble_periods.append((str(df.iloc[start_idx]["date"]), str(df.iloc[end_idx]["date"])))
    if not bubble_periods:
        return []
    merged = []
    cur_start, cur_end = bubble_periods[0]
    for start, end in bubble_periods[1:]:
        if start <= cur_end:
            cur_end = max(cur_end, end)
        else:
            merged.append((cur_start, cur_end))
            cur_start, cur_end = start, end
    merged.append((cur_start, cur_end))
    return merged


def is_in_bubble_period(date_str, bubble_periods):
    date = pd.Timestamp(date_str)
    for start, end in bubble_periods:
        if pd.Timestamp(start) <= date <= pd.Timestamp(end):
            return True
    return False


def generate_cycle_specs(bubble_periods, n_cycles=10, seed=42):
    random.seed(seed)
    all_years = list(range(2012, 2026))
    specs = []
    used_dates = set()
    for year in all_years:
        for _ in range(100):
            month = random.randint(3, 11)
            day = random.randint(5, 25)
            date_str = f"{year}-{month:02d}-{day:02d}"
            if date_str not in used_dates and not is_in_bubble_period(date_str, bubble_periods):
                specs.append(CycleSpec(0, year, date_str, f"Y{year}"))
                used_dates.add(date_str)
                break
    selected = random.sample(specs, min(n_cycles, len(specs)))
    selected.sort(key=lambda x: x.as_of_date)
    return [CycleSpec(i + 1, s.year, s.as_of_date, s.description) for i, s in enumerate(selected)]


def calculate_future_return(df, current_idx, future_days):
    end_idx = current_idx + future_days
    if end_idx >= len(df):
        return None
    entry_price = float(df.iloc[current_idx]["close"])
    if entry_price <= 0:
        return None
    future_data = df.iloc[current_idx + 1: end_idx + 1]
    if len(future_data) < future_days * 0.8:
        return None
    close = float(future_data.iloc[-1]["close"])
    high = float(future_data["high"].max())
    low = float(future_data["low"].min())
    return {
        "future_return_pct": round((close - entry_price) / entry_price * 100, 2),
        "future_max_gain_pct": round((high - entry_price) / entry_price * 100, 2),
        "future_max_dd_pct": round((entry_price - low) / entry_price * 100, 2),
        "entry_price": round(entry_price, 3),
        "close_price": round(close, 3),
    }


def _get_mtf_alignment(report):
    if report.multi_timeframe and report.multi_timeframe.enabled:
        alignment = report.multi_timeframe.alignment
        if alignment:
            return alignment
    return "mixed"


def _get_mtf_phase(report, timeframe):
    if report.multi_timeframe and report.multi_timeframe.enabled:
        if timeframe == "daily" and report.multi_timeframe.daily:
            return report.multi_timeframe.daily.phase.value if hasattr(report.multi_timeframe.daily.phase, 'value') else str(report.multi_timeframe.daily.phase)
        if timeframe == "weekly" and report.multi_timeframe.weekly:
            return report.multi_timeframe.weekly.phase.value if hasattr(report.multi_timeframe.weekly.phase, 'value') else str(report.multi_timeframe.weekly.phase)
        if timeframe == "monthly" and report.multi_timeframe.monthly:
            return report.multi_timeframe.monthly.phase.value if hasattr(report.multi_timeframe.monthly.phase, 'value') else str(report.multi_timeframe.monthly.phase)
    return "unknown"


def _get_spring_detected(report):
    if hasattr(report, 'signal') and hasattr(report.signal, 'signal_type'):
        return report.signal.signal_type in ("spring", "lps")
    return False


def process_single_stock(args):
    symbol_info, cycle_specs, config = args
    symbol = symbol_info["symbol"]
    name = symbol_info["name"]

    try:
        from src.data.manager import DataManager
        from src.wyckoff.engine import WyckoffEngine
        from src.wyckoff_optimizer import optimize_signal

        dm = DataManager()
        df = dm.get_data(symbol)
        if df is None or df.empty:
            return []

        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)
        df["ret_60d"] = df["close"].pct_change(60)

        engine = WyckoffEngine(lookback_days=400, weekly_lookback=120, monthly_lookback=40)
        results = []

        for spec in cycle_specs:
            as_of = pd.Timestamp(spec.as_of_date)
            mask = df["date"] <= as_of
            if mask.sum() < config.lookback_min:
                continue

            idx = int(mask.sum()) - 1
            wyckoff_slice = df.iloc[max(0, idx - config.lookback_min):idx + 1].copy().reset_index(drop=True)

            raw_phase = "unknown"
            raw_direction = "空仓观望"
            raw_confidence = "D"
            raw_mtf = "mixed"
            spring_detected = False

            try:
                report = engine.analyze(wyckoff_slice, symbol=symbol, multi_timeframe=True)
                raw_phase = report.structure.phase.value if hasattr(report.structure.phase, 'value') else str(report.structure.phase)
                raw_direction = report.trading_plan.direction
                raw_confidence = report.signal.confidence.value if hasattr(report.signal.confidence, 'value') else str(report.signal.confidence)
                raw_mtf = _get_mtf_alignment(report)
                spring_detected = _get_spring_detected(report)
            except Exception:
                pass

            stock_momentum_60d = float(df.iloc[idx]["ret_60d"]) if pd.notna(df.iloc[idx].get("ret_60d", np.nan)) else None

            future = calculate_future_return(df, idx, config.future_days)
            if future is None:
                continue

            results.append({
                "cycle_id": spec.cycle_id,
                "cycle_year": spec.year,
                "as_of_date": spec.as_of_date,
                "symbol": symbol,
                "name": name,
                "raw_phase": raw_phase,
                "raw_direction": raw_direction,
                "raw_confidence": raw_confidence,
                "raw_mtf": raw_mtf,
                "spring_detected": spring_detected,
                "stock_momentum_60d": stock_momentum_60d,
                "future_return_pct": future["future_return_pct"],
                "future_max_gain_pct": future["future_max_gain_pct"],
                "future_max_dd_pct": future["future_max_dd_pct"],
            })
    except Exception:
        pass

    return results


def convert_keys(obj):
    if isinstance(obj, dict):
        return {str(k): convert_keys(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [convert_keys(i) for i in obj]
    elif isinstance(obj, (np.int64, np.int32)):
        return int(obj)
    elif isinstance(obj, (np.float64, np.float32)):
        return float(obj)
    return obj


def run_backtest(symbols, cycle_specs, config, output_dir):
    max_workers = get_optimal_workers()
    total_tests = len(symbols) * len(cycle_specs)
    print(f"\n开始回测: {len(symbols)} x {len(cycle_specs)} = {total_tests}")
    print(f"多进程: {max_workers} workers")
    print("=" * 60)

    all_results = []
    completed = 0
    start_time = time.time()
    output_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = output_dir / "optimizer_raw_results.jsonl"
    checkpoint_path = output_dir / "checkpoint.json"

    processed_symbols = set()
    if checkpoint_path.exists():
        try:
            with checkpoint_path.open("r") as f:
                ckpt = json.load(f)
            processed_symbols = set(ckpt.get("processed_symbols", []))
            print(f"  断点恢复: {len(processed_symbols)} 只")
        except Exception:
            pass

    args_list = [(si, cycle_specs, config) for si in symbols if si["symbol"] not in processed_symbols]
    print(f"  待处理: {len(args_list)} 只")

    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(process_single_stock, args): args[0] for args in args_list}
        batch = []
        for future in as_completed(futures):
            completed += 1
            si = futures[future]
            try:
                results = future.result(timeout=600)
                batch.extend(results)
                processed_symbols.add(si["symbol"])
            except Exception:
                processed_symbols.add(si["symbol"])

            if len(batch) >= 200:
                with jsonl_path.open("a", encoding="utf-8") as f:
                    for row in batch:
                        f.write(json.dumps(convert_keys(row), ensure_ascii=False) + "\n")
                all_results.extend(batch)
                batch = []

            if completed % 100 == 0:
                elapsed = time.time() - start_time
                rate = completed / elapsed if elapsed > 0 else 0
                eta = (len(args_list) - completed) / rate if rate > 0 else 0
                mem = psutil.virtual_memory()
                print(f"  [{completed}/{len(args_list)}] {len(all_results)} 条 | "
                      f"{rate:.1f}/s | ETA {eta/60:.1f}min | MEM {mem.percent:.0f}%")
                with checkpoint_path.open("w") as f:
                    json.dump({"processed_symbols": list(processed_symbols), "total": len(all_results)}, f)

        if batch:
            with jsonl_path.open("a", encoding="utf-8") as f:
                for row in batch:
                    f.write(json.dumps(convert_keys(row), ensure_ascii=False) + "\n")
            all_results.extend(batch)

    elapsed = time.time() - start_time
    print(f"\n回测完成: {len(all_results)} 条 ({elapsed/60:.1f}分钟)")
    return all_results


def analyze_results(results):
    if not results:
        return {}
    df = pd.DataFrame(results)
    total = len(df)

    from src.wyckoff_optimizer import optimize_signal
    from src.wyckoff_phase_enhancer import detect_market_breadth, enhance_phase_detection

    date_breadths = {}
    for (cid, date), grp in df.groupby(["cycle_id", "as_of_date"]):
        phases = grp["raw_phase"].tolist()
        bd = detect_market_breadth(phases)
        bd.date = date
        date_breadths[(cid, date)] = bd

    df["market_direction"] = df.apply(
        lambda r: date_breadths.get((r["cycle_id"], r["as_of_date"]), MarketBreadth("", 0, 0, 0, 0, 0, 0, "neutral", 0.5)).market_direction
        if hasattr(MarketBreadth, "__call__") else "neutral", axis=1
    )

    from src.wyckoff_phase_enhancer import MarketBreadth as MB
    df["market_direction"] = df.apply(
        lambda r: date_breadths.get((r["cycle_id"], r["as_of_date"]), MB("", 0, 0, 0, 0, 0, 0, "neutral", 0.5)).market_direction,
        axis=1
    )
    df["market_md_pct"] = df.apply(
        lambda r: date_breadths.get((r["cycle_id"], r["as_of_date"]), MB("", 0, 0, 0, 0, 0, 0, "neutral", 0.5)).markdown_pct,
        axis=1
    )

    enhanced_records = []
    for _, row in df.iterrows():
        bd = date_breadths.get((row["cycle_id"], row["as_of_date"]), MB("", 0, 0, 0, 0, 0, 0, "neutral", 0.5))
        sig = enhance_phase_detection(
            phase=row["raw_phase"],
            direction=row["raw_direction"],
            confidence=row["raw_confidence"],
            mtf_alignment=row["raw_mtf"],
            market_breadth=bd,
            spring_detected=row.get("spring_detected", False),
        )
        enhanced_records.append({
            "enhanced_action": sig.enhanced_action,
            "enhanced_score": sig.enhanced_score,
            "enhanced_actionable": sig.is_actionable,
            "phase_in_context": sig.phase_in_context,
        })

    enh_df = pd.DataFrame(enhanced_records)
    for col in enh_df.columns:
        df[col] = enh_df[col].values

    opt_records = []
    for _, row in df.iterrows():
        sig = optimize_signal(
            phase=row["raw_phase"],
            direction=row["raw_direction"],
            confidence=row["raw_confidence"],
            mtf_alignment=row["raw_mtf"],
            spring_detected=row.get("spring_detected", False),
        )
        opt_records.append({
            "opt_actionable": sig.is_actionable,
        })
    df["opt_actionable"] = pd.DataFrame(opt_records)["opt_actionable"].values

    def _stats(signal_mask, label):
        sig = df[signal_mask]
        nsig = df[~signal_mask]
        ad = df[df["future_return_pct"] < 0]
        n = len(sig)
        if n == 0:
            return {"label": label, "n_signals": 0}
        p = len(sig[sig["future_return_pct"] < 0]) / n
        r = len(sig[sig["future_return_pct"] < 0]) / len(ad) if len(ad) > 0 else 0
        f1 = 2 * p * r / (p + r) if (p + r) > 0 else 0
        sr = float(sig["future_return_pct"].mean())
        nr = float(nsig["future_return_pct"].mean()) if len(nsig) > 0 else 0
        return {
            "label": label, "n_signals": n,
            "signal_rate": round(n / total, 4),
            "precision": round(p, 4), "recall": round(r, 4), "f1": round(f1, 4),
            "signal_return": round(sr, 2), "non_signal_return": round(nr, 2),
            "return_spread": round(sr - nr, 2),
            "signal_win_rate": round(len(sig[sig["future_return_pct"] > 0]) / n * 100, 1),
            "signal_median": round(float(sig["future_return_pct"].median()), 2),
        }

    comparison = {
        "A_raw_markdown": _stats(df["raw_phase"] == "markdown", "A_raw_markdown"),
        "B_opt_actionable": _stats(df["opt_actionable"] == True, "B_opt_actionable"),
        "C_enhanced_actionable": _stats(df["enhanced_actionable"] == True, "C_enhanced_actionable"),
    }

    date_comparison = {}
    for (cid, date), grp in df.groupby(["cycle_id", "as_of_date"]):
        bd = date_breadths.get((cid, date), MB("", 0, 0, 0, 0, 0, 0, "neutral", 0.5))
        year = grp["cycle_year"].iloc[0]
        opt_n = len(grp[grp["opt_actionable"] == True])
        enh_n = len(grp[grp["enhanced_actionable"] == True])
        opt_ret = grp[grp["opt_actionable"] == True]["future_return_pct"].mean() if opt_n > 0 else 0
        enh_ret = grp[grp["enhanced_actionable"] == True]["future_return_pct"].mean() if enh_n > 0 else 0
        date_comparison[f"C{cid}_{date}"] = {
            "year": int(year),
            "market_direction": bd.market_direction,
            "md_pct": bd.markdown_pct,
            "mk_pct": bd.markup_pct,
            "un_pct": bd.unknown_pct,
            "opt_signals": opt_n,
            "opt_return": round(opt_ret, 2),
            "enhanced_signals": enh_n,
            "enhanced_return": round(enh_ret, 2),
        }

    yearly = {}
    for year in sorted(df["cycle_year"].unique()):
        ydf = df[df["cycle_year"] == year]
        opt_sig = ydf[ydf["opt_actionable"] == True]
        enh_sig = ydf[ydf["enhanced_actionable"] == True]
        yearly[int(year)] = {
            "n_samples": len(ydf),
            "avg_return": round(float(ydf["future_return_pct"].mean()), 2),
            "market_direction": ydf["market_direction"].mode().iloc[0] if len(ydf) > 0 else "unknown",
            "opt_signals": len(opt_sig),
            "opt_signal_return": round(float(opt_sig["future_return_pct"].mean()), 2) if len(opt_sig) > 0 else None,
            "enhanced_signals": len(enh_sig),
            "enhanced_signal_return": round(float(enh_sig["future_return_pct"].mean()), 2) if len(enh_sig) > 0 else None,
            "enhanced_signal_win_rate": round(len(enh_sig[enh_sig["future_return_pct"] > 0]) / len(enh_sig) * 100, 1) if len(enh_sig) > 0 else None,
        }

    phase_stats = {}
    for phase in ["markdown", "markup", "accumulation", "distribution", "unknown"]:
        pdf = df[df["raw_phase"] == phase]
        if len(pdf) == 0:
            continue
        enh_sig = pdf[pdf["enhanced_actionable"] == True]
        phase_stats[phase] = {
            "count": len(pdf),
            "avg_return": round(float(pdf["future_return_pct"].mean()), 2),
            "enhanced_signals": len(enh_sig),
            "enhanced_signal_return": round(float(enh_sig["future_return_pct"].mean()), 2) if len(enh_sig) > 0 else None,
        }

    return {
        "total_samples": total,
        "overall_avg_return": round(float(df["future_return_pct"].mean()), 2),
        "overall_win_rate": round(len(df[df["future_return_pct"] > 0]) / total * 100, 1),
        "comparison": comparison,
        "phase_stats": phase_stats,
        "yearly_stats": yearly,
        "date_comparison": date_comparison,
    }

    comparison = {
        "A_raw_all": _stats(df["raw_direction"].isin(["做多", "轻仓试探", "观察等待"]), "A_raw_all_directions"),
        "A_raw_markdown_only": _stats(df["raw_phase"] == "markdown", "A_raw_markdown"),
        "B_opt_actionable": _stats(df["opt_actionable"] == True, "B_opt_actionable"),
        "B_opt_markdown_only": _stats((df["opt_actionable"] == True) & (df["raw_phase"] == "markdown"), "B_opt_markdown"),
    }

    phase_stats = {}
    for phase in ["markdown", "markup", "accumulation", "distribution", "unknown"]:
        pdf = df[df["raw_phase"] == phase]
        if len(pdf) == 0:
            continue
        opt_sig = pdf[pdf["opt_actionable"] == True]
        phase_stats[phase] = {
            "count": len(pdf),
            "avg_return": round(float(pdf["future_return_pct"].mean()), 2),
            "win_rate": round(len(pdf[pdf["future_return_pct"] > 0]) / len(pdf) * 100, 1),
            "opt_signals": len(opt_sig),
            "opt_signal_return": round(float(opt_sig["future_return_pct"].mean()), 2) if len(opt_sig) > 0 else None,
            "opt_signal_win_rate": round(len(opt_sig[opt_sig["future_return_pct"] > 0]) / len(opt_sig) * 100, 1) if len(opt_sig) > 0 else None,
        }

    mtf_stats = {}
    for mtf in ["fully_aligned", "higher_timeframe_aligned", "weekly_daily_aligned", "mixed"]:
        mdf = df[df["raw_mtf"] == mtf]
        if len(mdf) == 0:
            continue
        opt_sig = mdf[mdf["opt_actionable"] == True]
        mtf_stats[mtf] = {
            "count": len(mdf),
            "avg_return": round(float(mdf["future_return_pct"].mean()), 2),
            "opt_signals": len(opt_sig),
            "opt_signal_return": round(float(opt_sig["future_return_pct"].mean()), 2) if len(opt_sig) > 0 else None,
        }

    yearly = {}
    for year in sorted(df["cycle_year"].unique()):
        ydf = df[df["cycle_year"] == year]
        opt_sig = ydf[ydf["opt_actionable"] == True]
        yearly[int(year)] = {
            "n_samples": len(ydf),
            "avg_return": round(float(ydf["future_return_pct"].mean()), 2),
            "win_rate": round(len(ydf[ydf["future_return_pct"] > 0]) / len(ydf) * 100, 1),
            "opt_signals": len(opt_sig),
            "opt_signal_return": round(float(opt_sig["future_return_pct"].mean()), 2) if len(opt_sig) > 0 else None,
            "opt_signal_win_rate": round(len(opt_sig[opt_sig["future_return_pct"] > 0]) / len(opt_sig) * 100, 1) if len(opt_sig) > 0 else None,
        }

    return {
        "total_samples": total,
        "overall_avg_return": round(float(df["future_return_pct"].mean()), 2),
        "overall_win_rate": round(len(df[df["future_return_pct"] > 0]) / total * 100, 1),
        "comparison": comparison,
        "phase_stats": phase_stats,
        "mtf_stats": mtf_stats,
        "yearly_stats": yearly,
    }


def write_outputs(output_dir, results, analysis, bubble_periods, config):
    output_dir.mkdir(parents=True, exist_ok=True)
    with (output_dir / "optimizer_raw_results.jsonl").open("w", encoding="utf-8") as f:
        for row in results:
            f.write(json.dumps(convert_keys(row), ensure_ascii=False) + "\n")
    if results:
        pd.DataFrame(results).to_csv(output_dir / "optimizer_results.csv", index=False, encoding="utf-8-sig")
    with (output_dir / "optimizer_analysis.json").open("w", encoding="utf-8") as f:
        json.dump(convert_keys(analysis), f, ensure_ascii=False, indent=2)
    with (output_dir / "bubble_periods.json").open("w", encoding="utf-8") as f:
        json.dump(bubble_periods, f, ensure_ascii=False, indent=2)

    comp = analysis.get("comparison", {})
    lines = [
        "# Wyckoff阶段增强回测报告 (v3 市场宽度+阶段条件化)",
        f"- 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 总样本: {analysis.get('total_samples', 0)}",
        f"- 平均收益: {analysis.get('overall_avg_return', 0):.2f}%",
        f"- 胜率: {analysis.get('overall_win_rate', 0):.1f}%",
        "",
        "## 三组对比",
        "",
        "| 配置 | 信号数 | 精确率 | F1 | 信号收益 | 收益差 | 信号胜率 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for name in ["A_raw_markdown", "B_opt_actionable", "C_enhanced_actionable"]:
        c = comp.get(name, {})
        if c.get("n_signals", 0) == 0:
            lines.append(f"| {name} | 0 | - | - | - | - | - |")
        else:
            lines.append(
                f"| {name} | {c.get('n_signals', 0)} | {c.get('precision', 0)*100:.1f}% | "
                f"{c.get('f1', 0):.3f} | {c.get('signal_return', 0):.2f}% | "
                f"{c.get('return_spread', 0):.2f}% | {c.get('signal_win_rate', 0):.1f}% |"
            )

    lines.extend(["", "## 每日市场宽度与信号效果", ""])
    lines.append("| 日期 | 年份 | 市场方向 | md% | mk% | un% | B信号 | B收益 | C信号 | C收益 |")
    lines.append("|---|---:|---|---:|---:|---:|---:|---:|---:|---:|")
    for key, dc in sorted(analysis.get("date_comparison", {}).items()):
        lines.append(
            f"| {key.split('_',1)[1]} | {dc['year']} | {dc['market_direction']} | "
            f"{dc['md_pct']:.1f}% | {dc['mk_pct']:.1f}% | {dc['un_pct']:.1f}% | "
            f"{dc['opt_signals']} | {dc['opt_return']:+.2f}% | "
            f"{dc['enhanced_signals']} | {dc['enhanced_return']:+.2f}% |"
        )

    lines.extend(["", "## 年份分析", ""])
    lines.append("| 年份 | 样本 | 平均收益 | 市场方向 | B信号 | B收益 | C信号 | C收益 | C胜率 |")
    lines.append("|---|---:|---:|---|---:|---:|---:|---:|---:|")
    for year, ys in sorted(analysis.get("yearly_stats", {}).items()):
        b_ret = f"{ys['opt_signal_return']:+.2f}%" if ys.get("opt_signal_return") is not None else "N/A"
        c_ret = f"{ys['enhanced_signal_return']:+.2f}%" if ys.get("enhanced_signal_return") is not None else "N/A"
        c_wr = f"{ys['enhanced_signal_win_rate']:.1f}%" if ys.get("enhanced_signal_win_rate") is not None else "N/A"
        lines.append(
            f"| {year} | {ys['n_samples']} | {ys['avg_return']:+.2f}% | {ys['market_direction']} | "
            f"{ys['opt_signals']} | {b_ret} | {ys['enhanced_signals']} | {c_ret} | {c_wr} |"
        )

    lines.extend(["", "## 阶段条件化效果", ""])
    lines.append("| 阶段 | 样本 | 阶段收益 | C信号数 | C信号收益 |")
    lines.append("|---|---:|---:|---:|---:|")
    for phase, ps in analysis.get("phase_stats", {}).items():
        c_ret = f"{ps['enhanced_signal_return']:+.2f}%" if ps.get("enhanced_signal_return") is not None else "N/A"
        lines.append(f"| {phase} | {ps['count']} | {ps['avg_return']:+.2f}% | {ps['enhanced_signals']} | {c_ret} |")

    lines.extend(["", "## 增强规则", ""])
    lines.append("1. 市场宽度检测: unknown占比>15%→牛市, markdown>85%且unknown<5%→熊市, markup>40%→熊市")
    lines.append("2. 熊市: 所有阶段→空仓观望(不操作)")
    lines.append("3. 牛市: markdown+fully_aligned+D/B→轻仓试探, markup→持有观察")
    lines.append("4. 中性: markdown+fully_aligned+D/B→轻仓试探, 其他→空仓观望")

    (output_dir / "optimizer_report.md").write_text("\n".join(lines), encoding="utf-8")

    print(f"\n输出文件:")
    for f in sorted(output_dir.iterdir()):
        if f.is_file():
            size = f.stat().st_size
            print(f"  {f.name}: {size / 1024:.1f} KB" if size < 1024 * 1024 else f"  {f.name}: {size / 1024 / 1024:.1f} MB")


def main():
    output_dir = PROJECT_ROOT / "output" / "wyckoff_optimizer"
    csv_path = PROJECT_ROOT / "data" / "stock_list.csv"
    config = BacktestConfig()

    print("=" * 60)
    print("纯Wyckoff优化回测 (五项优化)")
    print("A: 原始Wyckoff | B: 优化Wyckoff")
    print("=" * 60)

    print("\n1. 加载股票...")
    symbols = load_stock_symbols(csv_path)
    print(f"   {len(symbols)} 只")

    print("\n2. 加载指数...")
    tdx_path = Path("/home/james/.local/share/tdxcfv/drive_c/tc/vipdoc/sh/lday/sh000001.day")
    index_data = None
    if tdx_path.exists():
        records = []
        with open(tdx_path, "rb") as f:
            while True:
                data = f.read(32)
                if len(data) < 32:
                    break
                date_int, o, h, l, c, amount, volume, _ = struct.unpack("<IIIIIfII", data)
                year = date_int // 10000
                month = (date_int % 10000) // 100
                day = date_int % 100
                records.append({"date": f"{year}-{month:02d}-{day:02d}",
                               "open": o/100, "high": h/100, "low": l/100, "close": c/100,
                               "volume": volume, "amount": amount})
        index_data = pd.DataFrame(records)
        index_data["date"] = pd.to_datetime(index_data["date"])
        index_data = index_data.sort_values("date").reset_index(drop=True)
    print(f"   {len(index_data) if index_data is not None else 0} 条")

    print("\n3. 泡沫检测...")
    bubble_periods = detect_bubble_periods(index_data) if index_data is not None else []
    print(f"   {len(bubble_periods)} 个")

    print("\n4. 生成周期...")
    cycle_specs = generate_cycle_specs(bubble_periods, config.n_cycles, config.seed)
    for s in cycle_specs:
        print(f"   Cycle {s.cycle_id:2d}: {s.as_of_date} (Y{s.year})")

    print("\n5. 运行回测...")
    results = run_backtest(symbols, cycle_specs, config, output_dir)

    print("\n6. 分析...")
    analysis = analyze_results(results)

    print("\n7. 输出...")
    write_outputs(output_dir, results, analysis, bubble_periods, config)

    comp = analysis.get("comparison", {})
    print("\n" + "=" * 60)
    print("摘要:")
    for name in ["A_raw_markdown", "B_opt_actionable", "C_enhanced_actionable"]:
        c = comp.get(name, {})
        n = c.get("n_signals", 0)
        if n == 0:
            print(f"  {name}: 0 signals")
        else:
            print(f"  {name}: n={n} p={c.get('precision',0)*100:.1f}% "
                  f"f1={c.get('f1',0):.3f} spread={c.get('return_spread',0):.2f}% wr={c.get('signal_win_rate',0):.1f}%")
    print("=" * 60)


if __name__ == "__main__":
    main()
