#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
对本地通达信股票日线执行最新一日威科夫批量测试。
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.generate_wyckoff_daily_replay import evaluate_design_completeness
from src.constants import TDX_DATA_DIR
from src.data.manager import DataManager
from src.wyckoff import WyckoffAnalyzer

SH_STOCK_PREFIXES = ("600", "601", "603", "605", "688")
SZ_STOCK_PREFIXES = ("000", "001", "002", "003", "300", "301")


def discover_stock_symbols(limit: int) -> list[str]:
    tdx_root = Path(TDX_DATA_DIR)
    candidates: list[str] = []

    for market, prefixes in (("sh", SH_STOCK_PREFIXES), ("sz", SZ_STOCK_PREFIXES)):
        market_dir = tdx_root / market / "lday"
        for path in sorted(market_dir.glob(f"{market}*.day")):
            code = path.stem.replace(market, "", 1)
            if len(code) != 6 or not code.isdigit():
                continue
            if not code.startswith(prefixes):
                continue
            candidates.append(f"{code}.{market.upper()}")
            if len(candidates) >= limit:
                return candidates

    return candidates


def is_supported_stock_code(code: str, market: str) -> bool:
    if market == "SH":
        return code.startswith(SH_STOCK_PREFIXES)
    if market == "SZ":
        return code.startswith(SZ_STOCK_PREFIXES)
    return False


def load_symbols_from_csv(csv_path: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    with csv_path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            code = str(row.get("code", "")).strip()
            market = str(row.get("market", "")).strip().upper()
            name = str(row.get("name", "")).replace("\x00", "").strip()
            if not (code.isdigit() and len(code) == 6 and market in {"SH", "SZ"}):
                continue
            rows.append(
                {
                    "symbol": f"{code}.{market}",
                    "code": code,
                    "market": market,
                    "name": name,
                    "sector": str(row.get("sector", "")).strip(),
                    "supported": "1" if is_supported_stock_code(code, market) else "0",
                }
            )
    return rows


def tdx_day_path(symbol: str) -> Path:
    code, market = symbol.split(".")
    market_lower = market.lower()
    return Path(TDX_DATA_DIR) / market_lower / "lday" / f"{market_lower}{code}.day"


def build_failure_row(
    symbol_meta: dict[str, str],
    status: str,
    reason: str,
) -> dict[str, str | int | float]:
    return {
        "symbol": symbol_meta["symbol"],
        "code": symbol_meta["code"],
        "market": symbol_meta["market"],
        "name": symbol_meta["name"],
        "sector": symbol_meta["sector"],
        "analysis_status": status,
        "failure_reason": reason,
        "latest_date": "",
        "phase": status,
        "signal_type": status,
        "signal_description": reason,
        "direction": status,
        "current_qualification": reason,
        "trigger_condition": "",
        "invalidation_point": "",
        "first_target_text": "",
        "current_price": 0.0,
        "bc_price": "",
        "sc_price": "",
        "trading_range_low": 0.0,
        "trading_range_high": 0.0,
        "entry_price": 0.0,
        "stop_loss": 0.0,
        "first_target_price": 0.0,
        "rr_ratio": 0.0,
        "design_score_ratio": 0.0,
        "monthly_phase": "",
        "weekly_phase": "",
        "daily_phase": "",
        "unknown_candidate": "",
        "daily_unknown_candidate": "",
        "mtf_alignment": "",
        "report_path": "",
    }


def save_report(report_dir: Path, symbol: str, markdown: str) -> str:
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"{symbol.replace('.', '_')}.md"
    report_path.write_text(markdown, encoding="utf-8")
    try:
        return str(report_path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(report_path)


def default_worker_count(reserved_threads: int = 4) -> int:
    cpu_total = os.cpu_count() or 1
    return max(1, cpu_total - reserved_threads)


def analyze_single_symbol(
    symbol_meta: dict[str, str],
    report_dir: Path,
    lookback_days: int,
) -> dict[str, str | int | float]:
    symbol = symbol_meta["symbol"]
    if symbol_meta.get("supported") != "1":
        return build_failure_row(
            symbol_meta,
            status="unsupported_prefix",
            reason="not supported by current stock-prefix universe",
        )

    day_path = tdx_day_path(symbol)
    if not day_path.exists():
        return build_failure_row(
            symbol_meta,
            status="missing_tdx_file",
            reason=f"missing local TDX day file: {day_path}",
        )

    data_manager = DataManager()
    analyzer = WyckoffAnalyzer(lookback_days=lookback_days)
    df = data_manager.get_data(symbol)
    if df is None or df.empty:
        return build_failure_row(
            symbol_meta,
            status="load_failed",
            reason="DataManager returned no usable dataframe",
        )

    frame = df.copy()
    frame["date"] = frame["date"].astype("datetime64[ns]")
    frame = frame.sort_values("date").reset_index(drop=True)
    if len(frame) < 100:
        return build_failure_row(
            symbol_meta,
            status="insufficient_history",
            reason=f"insufficient data rows: {len(frame)} < 100",
        )

    report = analyzer.analyze(frame, symbol=symbol, period="日线", multi_timeframe=True)
    design = evaluate_design_completeness(report)

    return {
        "symbol": symbol,
        "code": symbol_meta["code"],
        "market": symbol_meta["market"],
        "name": symbol_meta["name"],
        "sector": symbol_meta["sector"],
        "analysis_status": "analyzed",
        "failure_reason": "",
        "latest_date": str(frame["date"].iloc[-1].date()),
        "phase": report.structure.phase.value,
        "monthly_phase": (
            report.multi_timeframe.monthly.phase.value
            if report.multi_timeframe and report.multi_timeframe.monthly
            else ""
        ),
        "weekly_phase": (
            report.multi_timeframe.weekly.phase.value
            if report.multi_timeframe and report.multi_timeframe.weekly
            else ""
        ),
        "daily_phase": (
            report.multi_timeframe.daily.phase.value
            if report.multi_timeframe and report.multi_timeframe.daily
            else report.structure.phase.value
        ),
        "unknown_candidate": report.structure.unknown_candidate,
        "daily_unknown_candidate": (
            report.multi_timeframe.daily.unknown_candidate
            if report.multi_timeframe and report.multi_timeframe.daily
            else report.structure.unknown_candidate
        ),
        "mtf_alignment": report.multi_timeframe.alignment if report.multi_timeframe else "",
        "signal_type": report.signal.signal_type,
        "signal_description": report.signal.description,
        "direction": report.trading_plan.direction,
        "current_qualification": report.trading_plan.current_qualification,
        "trigger_condition": report.trading_plan.trigger_condition,
        "invalidation_point": report.trading_plan.invalidation_point,
        "first_target_text": report.trading_plan.first_target,
        "current_price": round(report.structure.current_price, 3),
        "bc_price": round(report.structure.bc_point.price, 3) if report.structure.bc_point else "",
        "sc_price": round(report.structure.sc_point.price, 3) if report.structure.sc_point else "",
        "trading_range_low": round(report.structure.trading_range_low, 3),
        "trading_range_high": round(report.structure.trading_range_high, 3),
        "entry_price": round((report.risk_reward.entry_price or 0), 3),
        "stop_loss": round((report.risk_reward.stop_loss or 0), 3),
        "first_target_price": round((report.risk_reward.first_target or 0), 3),
        "rr_ratio": round(report.risk_reward.reward_risk_ratio, 3),
        "design_score_ratio": round(design["score"] / design["max_score"], 3),
        "report_path": save_report(report_dir, symbol, report.to_markdown()),
    }


def analyze_symbol_batch(
    symbol_items: Iterable[dict[str, str]],
    output_dir: Path,
    lookback_days: int = 120,
    workers: int = 1,
) -> list[dict[str, str | int | float]]:
    symbol_list = list(symbol_items)
    report_dir = output_dir / "reports"
    max_workers = max(1, workers)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        return list(
            executor.map(
                lambda item: analyze_single_symbol(item, report_dir, lookback_days),
                symbol_list,
            )
        )


def analyze_latest_batch(
    limit: int,
    output_dir: Path,
    lookback_days: int = 120,
    workers: int = 1,
) -> list[dict[str, str | int | float]]:
    symbols = discover_stock_symbols(limit)
    if len(symbols) < limit:
        raise RuntimeError(f"only discovered {len(symbols)} stock symbols, expected at least {limit}")
    symbol_items = [
        {
            "symbol": symbol,
            "code": symbol.split(".")[0],
            "market": symbol.split(".")[1],
            "name": "",
            "sector": "",
            "supported": "1",
        }
        for symbol in symbols
    ]
    return analyze_symbol_batch(symbol_items, output_dir, lookback_days=lookback_days, workers=workers)


def write_outputs(output_dir: Path, rows: list[dict[str, str | int | float]]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    total_count = len(rows)
    csv_path = output_dir / f"latest_{total_count}_stock_summary.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    jsonl_path = output_dir / f"latest_{total_count}_stock_raw.jsonl"
    with jsonl_path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    phase_counts = Counter(str(row["phase"]) for row in rows)
    direction_counts = Counter(str(row["direction"]) for row in rows)
    latest_date_counts = Counter(str(row["latest_date"]) for row in rows)
    avg_design = round(sum(float(row["design_score_ratio"]) for row in rows) / len(rows), 3)
    phase_direction_counts = Counter((str(row["phase"]), str(row["direction"])) for row in rows)
    low_design_rows = sorted(rows, key=lambda row: float(row["design_score_ratio"]))[:20]
    high_rr_rows = sorted(rows, key=lambda row: float(row["rr_ratio"]), reverse=True)[:20]

    md_lines = [
        f"# Wyckoff Latest {total_count} Stock Batch",
        "",
        f"- 样本数量: {len(rows)}",
        f"- 平均设计完整度: {avg_design}",
        f"- 最新日期分布: {dict(latest_date_counts)}",
        "",
        "## 阶段分布",
        "",
    ]
    for phase, phase_count in sorted(phase_counts.items()):
        md_lines.append(f"- `{phase}`: {phase_count}")

    md_lines.extend(["", "## 方向分布", ""])
    for direction, direction_count in sorted(direction_counts.items()):
        md_lines.append(f"- `{direction}`: {direction_count}")

    md_lines.extend(["", "## 阶段 x 方向", ""])
    for (phase, direction), value in sorted(phase_direction_counts.items()):
        md_lines.append(f"- `{phase}` / `{direction}`: {value}")

    md_lines.extend(
        [
            "",
            "## 低完整度样本",
            "",
            "| Symbol | Latest Date | Phase | Direction | Design | Signal |",
            "|---|---|---|---|---:|---|",
        ]
    )
    for row in low_design_rows:
        md_lines.append(
            "| {symbol} | {latest_date} | {phase} | {direction} | {design_score_ratio} | {signal_type} |".format(
                **row
            )
        )

    md_lines.extend(
        [
            "",
            "## 高盈亏比样本",
            "",
            "| Symbol | Latest Date | Phase | Direction | RR | Signal | Qualification |",
            "|---|---|---|---|---:|---|---|",
        ]
    )
    for row in high_rr_rows:
        md_lines.append(
            "| {symbol} | {latest_date} | {phase} | {direction} | {rr_ratio} | {signal_type} | {current_qualification} |".format(
                **row
            )
        )

    md_lines.extend(
        [
            "",
            "## 样本明细",
            "",
            "| Symbol | Latest Date | Phase | Signal | Direction | RR | Design | BC | SC | Report |",
            "|---|---|---|---|---|---:|---:|---:|---:|---|",
        ]
    )
    for row in rows:
        md_lines.append(
            "| {symbol} | {latest_date} | {phase} | {signal_type} | {direction} | {rr_ratio} | {design_score_ratio} | {bc_price} | {sc_price} | {report_path} |".format(
                **row
            )
        )

    (output_dir / f"latest_{total_count}_stock_summary.md").write_text("\n".join(md_lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="运行股票最新日线威科夫批量测试")
    parser.add_argument("--limit", type=int, default=100, help="批量测试股票数量")
    parser.add_argument("--csv", help="从 CSV 读取股票列表，如 data/stock_list.csv")
    parser.add_argument("--lookback", type=int, default=120, help="威科夫分析使用的日线回看根数")
    parser.add_argument(
        "--workers",
        type=int,
        default=default_worker_count(),
        help="并行线程数，默认使用 CPU 总线程数减 4",
    )
    parser.add_argument(
        "--output",
        default="output/wyckoff_latest_100",
        help="输出目录",
    )
    args = parser.parse_args()

    output_dir = PROJECT_ROOT / args.output
    if args.csv:
        csv_path = PROJECT_ROOT / args.csv
        symbol_items = load_symbols_from_csv(csv_path)
        rows = analyze_symbol_batch(
            symbol_items,
            output_dir,
            lookback_days=args.lookback,
            workers=args.workers,
        )
        symbol_export_path = output_dir / "stock_symbols_from_csv.json"
        symbol_export_path.parent.mkdir(parents=True, exist_ok=True)
        symbol_export_path.write_text(
            json.dumps(symbol_items, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    else:
        rows = analyze_latest_batch(
            args.limit,
            output_dir,
            lookback_days=args.lookback,
            workers=args.workers,
        )
    write_outputs(output_dir, rows)

    total_count = len(rows)
    print(f"saved: {output_dir / f'latest_{total_count}_stock_summary.csv'}")
    print(f"saved: {output_dir / f'latest_{total_count}_stock_summary.md'}")
    print(f"saved: {output_dir / f'latest_{total_count}_stock_raw.jsonl'}")
    print(f"reports: {output_dir / 'reports'}")
    print(f"rows: {len(rows)}")


if __name__ == "__main__":
    main()
