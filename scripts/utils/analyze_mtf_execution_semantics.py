#!/usr/bin/env python3
# RESEARCH ONLY — not production code
# -*- coding: utf-8 -*-
"""
分析多周期组合（月/周/日）与执行语义的对应关系。
"""

from __future__ import annotations

import argparse
import csv
from collections import Counter, defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def load_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def _direction_bucket(direction: str) -> str:
    if direction in {"买入观察 / 轻仓试探", "做多观察 / 轻仓试探"}:
        return "buy_like"
    if "持有观察" in direction:
        return "hold_like"
    if "空仓观望" in direction:
        return "stand_aside"
    return "other"


def write_csv(path: Path, rows: list[dict[str, str | int | float]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def build_mtf_execution_report(summary_csv: Path, output_dir: Path) -> dict[str, int]:
    rows = load_rows(summary_csv)
    analyzed = [row for row in rows if row.get("analysis_status") == "analyzed"]

    combo_groups: dict[tuple[str, str, str, str], list[dict[str, str]]] = defaultdict(list)
    for row in analyzed:
        combo_groups[
            (
                row.get("monthly_phase", ""),
                row.get("weekly_phase", ""),
                row.get("daily_phase", ""),
                row.get("mtf_alignment", ""),
            )
        ].append(row)

    combo_summary_rows: list[dict[str, str | int | float]] = []
    for combo, group in sorted(combo_groups.items(), key=lambda item: len(item[1]), reverse=True):
        monthly_phase, weekly_phase, daily_phase, alignment = combo
        direction_counts = Counter(_direction_bucket(row.get("direction", "")) for row in group)
        combo_summary_rows.append(
            {
                "monthly_phase": monthly_phase,
                "weekly_phase": weekly_phase,
                "daily_phase": daily_phase,
                "mtf_alignment": alignment,
                "count": len(group),
                "stand_aside_count": direction_counts["stand_aside"],
                "hold_like_count": direction_counts["hold_like"],
                "buy_like_count": direction_counts["buy_like"],
                "avg_rr": round(
                    sum(float(row.get("rr_ratio", "0") or 0) for row in group) / len(group),
                    3,
                ),
                "avg_design": round(
                    sum(float(row.get("design_score_ratio", "0") or 0) for row in group) / len(group),
                    3,
                ),
            }
        )

    problematic_rows = [
        row
        for row in analyzed
        if row.get("monthly_phase") == "markup"
        and row.get("weekly_phase") in {"markup", "unknown"}
        and row.get("daily_phase") in {"markup", "unknown", "accumulation"}
        and "空仓观望" in row.get("direction", "")
    ]
    problematic_rows = sorted(
        problematic_rows,
        key=lambda row: float(row.get("rr_ratio", "0") or 0),
        reverse=True,
    )

    combo_csv = output_dir / "mtf_combo_summary.csv"
    issue_csv = output_dir / "mtf_semantic_issue_cohort.csv"
    write_csv(combo_csv, combo_summary_rows)
    write_csv(issue_csv, problematic_rows[:100])

    top_combos = combo_summary_rows[:20]
    report_lines = [
        "# Multi-Timeframe Execution Semantics Report",
        "",
        "- 本报告基于已有批量结果中的 `monthly_phase` / `weekly_phase` / `daily_phase` / `mtf_alignment` 字段统计。",
        "- 这些字段来自日线合成周线和月线后的多周期分析，不是单独日线结论。",
        "",
        f"- analyzed rows: {len(analyzed)}",
        f"- unique mtf combos: {len(combo_summary_rows)}",
        f"- problematic bullish-htf stand-aside rows: {len(problematic_rows)}",
        "",
        "## Top Combos",
        "",
        "| Monthly | Weekly | Daily | Alignment | Count | Stand Aside | Hold | Buy | Avg RR |",
        "|---|---|---|---|---:|---:|---:|---:|---:|",
    ]
    for row in top_combos:
        report_lines.append(
            "| {monthly_phase} | {weekly_phase} | {daily_phase} | {mtf_alignment} | {count} | {stand_aside_count} | {hold_like_count} | {buy_like_count} | {avg_rr} |".format(
                **row
            )
        )

    report_lines.extend(
        [
            "",
            "## Judgment",
            "",
            "- 若 `monthly=markup` 且 `weekly in {markup, unknown}`，但大量结果仍落到 `stand_aside`，问题通常在执行语义映射而不是长期结构。",
            "- 若 `daily=unknown` 在 `monthly/weekly` 偏多时占比高，问题通常在 Phase A/B、SC/AR/ST/UT 细分不足。",
            "",
            "## Files",
            "",
            f"- [mtf_combo_summary.csv]({combo_csv.resolve()})",
            f"- [mtf_semantic_issue_cohort.csv]({issue_csv.resolve()})",
        ]
    )
    (output_dir / "mtf_execution_semantics_report.md").write_text("\n".join(report_lines), encoding="utf-8")

    return {
        "analyzed_count": len(analyzed),
        "combo_count": len(combo_summary_rows),
        "problematic_count": len(problematic_rows),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="分析多周期组合与执行语义")
    parser.add_argument(
        "--summary",
        default="output/wyckoff_stock_list_full_1000d_round2/latest_5199_stock_summary.csv",
        help="批量汇总 CSV",
    )
    parser.add_argument(
        "--output",
        default="output/wyckoff_mtf_semantics_round2",
        help="输出目录",
    )
    args = parser.parse_args()

    stats = build_mtf_execution_report(
        summary_csv=PROJECT_ROOT / args.summary,
        output_dir=PROJECT_ROOT / args.output,
    )
    print(f"saved: {PROJECT_ROOT / args.output / 'mtf_execution_semantics_report.md'}")
    print(stats)


if __name__ == "__main__":
    main()
