#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
回放 docs/new 中的威科夫样本，并输出程序结论与样本基线的对照。
"""

from __future__ import annotations

import csv
import sys
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.data.manager import DataManager
from src.wyckoff import WyckoffAnalyzer


@dataclass(frozen=True)
class ReplayBaseline:
    symbol: str
    as_of: str
    sample_phase: str
    sample_direction: str
    sample_bc: float | None = None


BASELINES = [
    ReplayBaseline(
        symbol="002216.SZ",
        as_of="2026-04-03",
        sample_phase="markup",
        sample_direction="空仓观望 / No Trade Zone",
        sample_bc=13.27,
    ),
    ReplayBaseline(
        symbol="600859.SH",
        as_of="2026-04-03",
        sample_phase="markdown",
        sample_direction="空仓观望",
        sample_bc=16.98,
    ),
    ReplayBaseline(
        symbol="300442.SZ",
        as_of="2026-04-03",
        sample_phase="markdown",
        sample_direction="空仓观望 / 放弃观察",
        sample_bc=106.33,
    ),
]


def compute_similarity(
    phase: str,
    direction: str,
    bc_price: float | None,
    baseline: ReplayBaseline,
) -> tuple[int, str]:
    checks: list[str] = []
    score = 0

    if phase == baseline.sample_phase:
        score += 1
        checks.append("phase=match")
    else:
        checks.append(f"phase={phase}!={baseline.sample_phase}")

    if "空仓观望" in direction:
        score += 1
        checks.append("direction=match")
    else:
        checks.append(f"direction={direction}")

    if baseline.sample_bc is None:
        score += 1
        checks.append("bc=n/a")
    elif bc_price is not None and abs(bc_price - baseline.sample_bc) <= 3.5:
        score += 1
        checks.append("bc=close")
    else:
        checks.append(f"bc={bc_price}!~{baseline.sample_bc}")

    return score, "; ".join(checks)


def main() -> None:
    output_dir = PROJECT_ROOT / "output" / "wyckoff_sample_replay"
    output_dir.mkdir(parents=True, exist_ok=True)

    data_manager = DataManager()
    analyzer = WyckoffAnalyzer(lookback_days=120)

    rows: list[dict[str, str | int | float]] = []

    for baseline in BASELINES:
        df = data_manager.get_data(baseline.symbol)
        if df is None or df.empty:
            rows.append(
                {
                    "symbol": baseline.symbol,
                    "as_of": baseline.as_of,
                    "sample_phase": baseline.sample_phase,
                    "program_phase": "load_failed",
                    "sample_direction": baseline.sample_direction,
                    "program_direction": "load_failed",
                    "sample_bc": baseline.sample_bc or "",
                    "program_bc": "",
                    "similarity_score": 0,
                    "notes": "data load failed",
                }
            )
            continue

        sliced = df[df["date"] <= baseline.as_of].copy()
        report = analyzer.analyze(sliced, symbol=baseline.symbol, period="日线", multi_timeframe=True)

        phase = report.structure.phase.value
        direction = report.trading_plan.direction
        bc_price = report.structure.bc_point.price if report.structure.bc_point else None
        similarity_score, notes = compute_similarity(phase, direction, bc_price, baseline)

        rows.append(
            {
                "symbol": baseline.symbol,
                "as_of": baseline.as_of,
                "sample_phase": baseline.sample_phase,
                "program_phase": phase,
                "sample_direction": baseline.sample_direction,
                "program_direction": direction,
                "sample_bc": baseline.sample_bc or "",
                "program_bc": "" if bc_price is None else round(bc_price, 2),
                "similarity_score": similarity_score,
                "notes": notes,
            }
        )

    csv_path = output_dir / "sample_replay_comparison.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    md_path = output_dir / "sample_replay_comparison.md"
    lines = [
        "# Wyckoff Sample Replay Comparison",
        "",
        "| Symbol | Date | Sample Phase | Program Phase | Sample Direction | Program Direction | Sample BC | Program BC | Score | Notes |",
        "|---|---|---|---|---|---|---:|---:|---:|---|",
    ]
    for row in rows:
        lines.append(
            "| {symbol} | {as_of} | {sample_phase} | {program_phase} | {sample_direction} | "
            "{program_direction} | {sample_bc} | {program_bc} | {similarity_score} | {notes} |".format(**row)
        )
    md_path.write_text("\n".join(lines), encoding="utf-8")

    print(f"saved: {csv_path}")
    print(f"saved: {md_path}")


if __name__ == "__main__":
    main()
