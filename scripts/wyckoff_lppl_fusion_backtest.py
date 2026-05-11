#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Wyckoff阶段 + LPPL环境过滤 融合回测

路线B: LPPL作为Wyckoff系统的辅助环境过滤器

对比四组:
A. 纯Wyckoff markdown (phase==markdown)
B. 纯LPPL multifit (score>=0.3)
C. 融合: Wyckoff阶段权重 × LPPL得分
D. 融合+环境: Wyckoff阶段权重 × LPPL环境权重 × LPPL得分
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

PHASE_WEIGHTS = {
    "markdown": 1.0,
    "accumulation": 0.5,
    "unknown": 0.3,
    "distribution": 0.0,
    "markup": 0.0,
}

REGIME_WEIGHTS = {
    "strong_bull": 0.7,
    "weak_bull": 1.0,
    "range": 0.7,
    "weak_bear": 0.3,
    "strong_bear": 0.2,
    "unknown": 0.5,
}


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


def get_optimal_workers() -> int:
    cpu_count = psutil.cpu_count(logical=True)
    memory = psutil.virtual_memory()
    available_mb = memory.available / (1024 ** 2)
    max_by_memory = int(available_mb / 500)
    return max(2, min(max_by_memory, max(1, cpu_count - 2), 10))


def load_stock_symbols(csv_path: Path, limit: int = 99999) -> List[Dict[str, str]]:
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


def detect_bubble_periods(index_df: pd.DataFrame) -> List[Tuple[str, str]]:
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


def is_in_bubble_period(date_str: str, bubble_periods: List[Tuple[str, str]]) -> bool:
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


_INDEX_DF_CACHE = None

def _get_index_df():
    global _INDEX_DF_CACHE
    if _INDEX_DF_CACHE is not None:
        return _INDEX_DF_CACHE
    tdx_path = Path("/home/james/.local/share/tdxcfv/drive_c/tc/vipdoc/sh/lday/sh000001.day")
    if not tdx_path.exists():
        return None
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
            records.append({
                "date": f"{year}-{month:02d}-{day:02d}",
                "open": o / 100.0, "high": h / 100.0,
                "low": l / 100.0, "close": c / 100.0,
                "volume": volume, "amount": amount,
            })
    df = pd.DataFrame(records)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    _INDEX_DF_CACHE = df
    return df


def process_single_stock(args: tuple) -> List[Dict]:
    symbol_info, cycle_specs, config = args
    symbol = symbol_info["symbol"]
    name = symbol_info["name"]

    try:
        from src.data.manager import DataManager
        from src.wyckoff.engine import WyckoffEngine
        from src.lppl_multifit import fit_multi_window, calculate_multifit_score
        from src.lppl_regime import MarketRegimeDetector

        dm = DataManager()
        df = dm.get_data(symbol)
        if df is None or df.empty:
            return []

        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)
        close_prices = df["close"].values.astype(float)

        wyckoff_engine = WyckoffEngine(lookback_days=400, weekly_lookback=120, monthly_lookback=40)
        index_df = _get_index_df()
        regime_detector = MarketRegimeDetector()
        results = []

        for spec in cycle_specs:
            as_of = pd.Timestamp(spec.as_of_date)
            mask = df["date"] <= as_of
            if mask.sum() < config.lookback_min:
                continue

            idx = int(mask.sum()) - 1

            wyckoff_slice = df.iloc[max(0, idx - config.lookback_min):idx + 1].copy().reset_index(drop=True)
            try:
                report = wyckoff_engine.analyze(wyckoff_slice, symbol=symbol)
                wyckoff_phase = report.structure.phase.value if hasattr(report.structure.phase, 'value') else str(report.structure.phase)
                wyckoff_direction = report.trading_plan.direction
                wyckoff_confidence = report.signal.confidence.value if hasattr(report.signal.confidence, 'value') else str(report.signal.confidence)
                wyckoff_signal_type = report.signal.signal_type
            except Exception:
                wyckoff_phase = "unknown"
                wyckoff_direction = "空仓观望"
                wyckoff_confidence = "D"
                wyckoff_signal_type = "no_signal"

            multi_results = fit_multi_window(close_prices, idx)
            multifit_score = calculate_multifit_score(multi_results)

            regime_result = regime_detector.detect(index_df, individual_danger_rate=0.0)
            regime = regime_result["regime"]
            regime_weight = REGIME_WEIGHTS.get(regime, 0.5)

            phase_weight = PHASE_WEIGHTS.get(wyckoff_phase, 0.3)
            lppl_score = multifit_score["final_score"]

            fusion_score = phase_weight * lppl_score
            fusion_score_regime = phase_weight * regime_weight * lppl_score

            future = calculate_future_return(df, idx, config.future_days)
            if future is None:
                continue

            results.append({
                "cycle_id": spec.cycle_id,
                "cycle_year": spec.year,
                "as_of_date": spec.as_of_date,
                "symbol": symbol,
                "name": name,
                "data_rows": len(df),
                "wyckoff_phase": wyckoff_phase,
                "wyckoff_direction": wyckoff_direction,
                "wyckoff_confidence": wyckoff_confidence,
                "wyckoff_signal_type": wyckoff_signal_type,
                "lppl_score": lppl_score,
                "lppl_level": multifit_score["level"],
                "n_danger_layers": multifit_score["n_danger"],
                "regime": regime,
                "regime_weight": regime_weight,
                "phase_weight": phase_weight,
                "fusion_score": round(fusion_score, 4),
                "fusion_score_regime": round(fusion_score_regime, 4),
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
    print(f"\n开始融合回测: {len(symbols)} 只股票 x {len(cycle_specs)} 个周期 = {total_tests} 次分析")
    print(f"多进程: {max_workers} workers")
    print("=" * 60)

    all_results = []
    completed = 0
    start_time = time.time()
    output_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = output_dir / "fusion_raw_results.jsonl"
    checkpoint_path = output_dir / "checkpoint.json"

    processed_symbols = set()
    if checkpoint_path.exists():
        try:
            with checkpoint_path.open("r") as f:
                ckpt = json.load(f)
            processed_symbols = set(ckpt.get("processed_symbols", []))
            print(f"  从断点恢复: {len(processed_symbols)} 只")
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
                    json.dump({"processed": list(processed_symbols), "total": len(all_results)}, f)

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

    def _stats(score_col, threshold):
        sig = df[df[score_col] >= threshold]
        nsig = df[df[score_col] < threshold]
        ad = df[df["future_return_pct"] < 0]
        n = len(sig)
        p = len(sig[sig["future_return_pct"] < 0]) / n if n > 0 else 0
        r = len(sig[sig["future_return_pct"] < 0]) / len(ad) if len(ad) > 0 else 0
        f1 = 2 * p * r / (p + r) if (p + r) > 0 else 0
        sr = float(sig["future_return_pct"].mean()) if n > 0 else 0
        nr = float(nsig["future_return_pct"].mean()) if len(nsig) > 0 else 0
        return {
            "n_signals": n, "signal_rate": round(n / total, 4) if total else 0,
            "precision": round(p, 4), "recall": round(r, 4), "f1": round(f1, 4),
            "signal_return": round(sr, 2), "non_signal_return": round(nr, 2),
            "return_spread": round(sr - nr, 2),
            "signal_win_rate": round(len(sig[sig["future_return_pct"] > 0]) / n * 100, 1) if n > 0 else 0,
            "signal_median": round(float(sig["future_return_pct"].median()), 2) if n > 0 else 0,
        }

    df["wyckoff_markdown_flag"] = (df["wyckoff_phase"] == "markdown").astype(float)

    T = 0.15
    comparison = {
        "A_wyckoff_markdown": _stats("wyckoff_markdown_flag", 0.5),
        "B_lppl_multifit": _stats("lppl_score", 0.3),
        "C_fusion": _stats("fusion_score", T),
        "D_fusion_regime": _stats("fusion_score_regime", T),
    }

    yearly = {}
    for year in sorted(df["cycle_year"].unique()):
        ydf = df[df["cycle_year"] == year]
        sig_d = ydf[ydf["fusion_score_regime"] >= T]
        yearly[int(year)] = {
            "n_samples": len(ydf),
            "avg_return": round(float(ydf["future_return_pct"].mean()), 2),
            "win_rate": round(len(ydf[ydf["future_return_pct"] > 0]) / len(ydf) * 100, 1),
            "d_signals": len(sig_d),
            "d_signal_return": round(float(sig_d["future_return_pct"].mean()), 2) if len(sig_d) > 0 else None,
            "d_signal_win_rate": round(len(sig_d[sig_d["future_return_pct"] > 0]) / len(sig_d) * 100, 1) if len(sig_d) > 0 else None,
        }

    phase_stats = {}
    for phase in ["markdown", "markup", "accumulation", "distribution", "unknown"]:
        pdf = df[df["wyckoff_phase"] == phase]
        if len(pdf) == 0:
            continue
        sig = pdf[pdf["lppl_score"] >= 0.3]
        phase_stats[phase] = {
            "count": len(pdf),
            "avg_return": round(float(pdf["future_return_pct"].mean()), 2),
            "n_lppl_signals": len(sig),
            "lppl_signal_return": round(float(sig["future_return_pct"].mean()), 2) if len(sig) > 0 else None,
            "lppl_signal_win_rate": round(len(sig[sig["future_return_pct"] > 0]) / len(sig) * 100, 1) if len(sig) > 0 else None,
        }

    return {
        "total_samples": total,
        "overall_avg_return": round(float(df["future_return_pct"].mean()), 2),
        "overall_win_rate": round(len(df[df["future_return_pct"] > 0]) / total * 100, 1),
        "comparison": comparison,
        "yearly_stats": yearly,
        "phase_stats": phase_stats,
    }


def write_outputs(output_dir, results, analysis, bubble_periods, config):
    output_dir.mkdir(parents=True, exist_ok=True)
    with (output_dir / "fusion_raw_results.jsonl").open("w", encoding="utf-8") as f:
        for row in results:
            f.write(json.dumps(convert_keys(row), ensure_ascii=False) + "\n")
    if results:
        pd.DataFrame(results).to_csv(output_dir / "fusion_results.csv", index=False, encoding="utf-8-sig")
    with (output_dir / "fusion_analysis.json").open("w", encoding="utf-8") as f:
        json.dump(convert_keys(analysis), f, ensure_ascii=False, indent=2)
    with (output_dir / "bubble_periods.json").open("w", encoding="utf-8") as f:
        json.dump(bubble_periods, f, ensure_ascii=False, indent=2)

    comp = analysis.get("comparison", {})
    lines = [
        "# Wyckoff+LPPL融合回测报告",
        f"- 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 总样本: {analysis.get('total_samples', 0)}",
        f"- 平均收益: {analysis.get('overall_avg_return', 0):.2f}%",
        f"- 胜率: {analysis.get('overall_win_rate', 0):.1f}%",
        "",
        "## 四组对比",
        "",
        "| 配置 | 信号数 | 精确率 | F1 | 信号收益 | 收益差 | 信号胜率 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for name in ["A_wyckoff_markdown", "B_lppl_multifit", "C_fusion", "D_fusion_regime"]:
        c = comp.get(name, {})
        lines.append(
            f"| {name} | {c.get('n_signals', 0)} | {c.get('precision', 0)*100:.1f}% | "
            f"{c.get('f1', 0):.3f} | {c.get('signal_return', 0):.2f}% | "
            f"{c.get('return_spread', 0):.2f}% | {c.get('signal_win_rate', 0):.1f}% |"
        )

    lines.extend(["", "## 阶段×LPPL信号效果", ""])
    lines.append("| 阶段 | 样本 | 平均收益 | LPPL信号数 | LPPL信号收益 | LPPL信号胜率 |")
    lines.append("|---|---:|---:|---:|---:|---:|")
    for phase, ps in analysis.get("phase_stats", {}).items():
        ls_ret = f"{ps['lppl_signal_return']:.2f}%" if ps.get("lppl_signal_return") is not None else "N/A"
        ls_wr = f"{ps['lppl_signal_win_rate']:.1f}%" if ps.get("lppl_signal_win_rate") is not None else "N/A"
        lines.append(
            f"| {phase} | {ps['count']} | {ps['avg_return']:.2f}% | "
            f"{ps['n_lppl_signals']} | {ls_ret} | {ls_wr} |"
        )

    lines.extend(["", "## 年份分析", ""])
    lines.append("| 年份 | 样本 | 平均收益 | D信号数 | D信号收益 | D信号胜率 |")
    lines.append("|---|---:|---:|---:|---:|---:|")
    for year, ys in sorted(analysis.get("yearly_stats", {}).items()):
        d_ret = f"{ys['d_signal_return']:.2f}%" if ys.get("d_signal_return") is not None else "N/A"
        d_wr = f"{ys['d_signal_win_rate']:.1f}%" if ys.get("d_signal_win_rate") is not None else "N/A"
        lines.append(
            f"| {year} | {ys['n_samples']} | {ys['avg_return']:.2f}% | "
            f"{ys['d_signals']} | {d_ret} | {d_wr} |"
        )

    lines.extend(["", "## 融合公式", ""])
    lines.append("- C_fusion = phase_weight × lppl_score (阈值0.15)")
    lines.append("- D_fusion_regime = phase_weight × regime_weight × lppl_score (阈值0.15)")
    lines.append("- phase_weight: markdown=1.0, accumulation=0.5, unknown=0.3, distribution=0.0, markup=0.0")
    lines.append("- regime_weight: weak_bull=1.0, range=0.7, weak_bear=0.3, strong_bear=0.2")

    (output_dir / "fusion_report.md").write_text("\n".join(lines), encoding="utf-8")

    print(f"\n输出文件:")
    for f in sorted(output_dir.iterdir()):
        if f.is_file():
            size = f.stat().st_size
            print(f"  {f.name}: {size / 1024:.1f} KB" if size < 1024 * 1024 else f"  {f.name}: {size / 1024 / 1024:.1f} MB")


def main():
    output_dir = PROJECT_ROOT / "output" / "wyckoff_lppl_fusion"
    csv_path = PROJECT_ROOT / "data" / "stock_list.csv"
    config = BacktestConfig()

    print("=" * 60)
    print("Wyckoff + LPPL 融合回测 (路线B)")
    print("A: 纯Wyckoff | B: 纯LPPL | C: 融合 | D: 融合+环境")
    print("=" * 60)

    print("\n1. 加载股票...")
    symbols = load_stock_symbols(csv_path)
    print(f"   {len(symbols)} 只")

    print("\n2. 加载指数...")
    index_data = _get_index_df()
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
    for name in ["A_wyckoff_markdown", "B_lppl_multifit", "C_fusion", "D_fusion_regime"]:
        c = comp.get(name, {})
        print(f"  {name}: n={c.get('n_signals',0)} p={c.get('precision',0)*100:.1f}% "
              f"f1={c.get('f1',0):.3f} spread={c.get('return_spread',0):.2f}% wr={c.get('signal_win_rate',0):.1f}%")
    print("=" * 60)


if __name__ == "__main__":
    main()
