#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
基于全量批量扫描结果抽取误差样本，辅助威科夫规则优化。
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def load_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def take_top(rows: list[dict[str, str]], size: int, sort_key: str, reverse: bool = False) -> list[dict[str, str]]:
    return sorted(rows, key=lambda row: float(row.get(sort_key, "0") or 0), reverse=reverse)[:size]


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def build_gap_study(
    batch_summary_csv: Path,
    continuity_csv: Path,
    output_dir: Path,
    cohort_size: int = 30,
) -> dict[str, int | float]:
    batch_rows = load_csv_rows(batch_summary_csv)
    continuity_rows = load_csv_rows(continuity_csv)

    analyzed_rows = [row for row in batch_rows if row.get("analysis_status") == "analyzed"]
    unknown_rows = [row for row in analyzed_rows if row.get("phase") == "unknown"]
    markup_stand_aside_rows = [
        row
        for row in analyzed_rows
        if row.get("phase") == "markup" and "空仓观望" in row.get("direction", "")
    ]
    high_rr_no_action_rows = [
        row
        for row in analyzed_rows
        if float(row.get("rr_ratio", "0") or 0) >= 2.5 and "空仓观望" in row.get("direction", "")
    ]
    low_score_rows = [
        row
        for row in continuity_rows
        if float(row.get("score_ratio", "0") or 0) < 1.0
    ]

    unknown_top = take_top(unknown_rows, cohort_size, sort_key="design_score_ratio")
    markup_top = take_top(markup_stand_aside_rows, cohort_size, sort_key="rr_ratio", reverse=True)
    high_rr_top = take_top(high_rr_no_action_rows, cohort_size, sort_key="rr_ratio", reverse=True)
    low_score_top = sorted(low_score_rows, key=lambda row: float(row["score_ratio"]))[:cohort_size]

    write_csv(output_dir / "unknown_cohort.csv", unknown_top)
    write_csv(output_dir / "markup_stand_aside_cohort.csv", markup_top)
    write_csv(output_dir / "high_rr_no_action_cohort.csv", high_rr_top)
    write_csv(output_dir / "sample_mismatch_cohort.csv", low_score_top)

    avg_sample_score = 0.0
    if continuity_rows:
        avg_sample_score = round(
            sum(float(row.get("score_ratio", "0") or 0) for row in continuity_rows) / len(continuity_rows),
            3,
        )

    report_lines = [
        "# Wyckoff Batch Gap Study",
        "",
        f"- 批量样本总数: {len(batch_rows)}",
        f"- 成功分析样本: {len(analyzed_rows)}",
        f"- 连续性样本总数: {len(continuity_rows)}",
        f"- 连续性平均得分: {avg_sample_score}",
        "",
        "## 关键问题规模",
        "",
        f"- `unknown`: {len(unknown_rows)}",
        f"- `markup + 空仓观望`: {len(markup_stand_aside_rows)}",
        f"- `高 RR 但仍空仓观望`: {len(high_rr_no_action_rows)}",
        f"- `连续性未满分样本日`: {len(low_score_rows)}",
        "",
        "## 研究结论",
        "",
        "- `unknown` 样本说明交易区间和 Phase A/B 细分仍然不足。",
        "- `markup + 空仓观望` 样本说明右侧执行语义仍偏保守，尤其是 LPS/BUEC/Phase E 的映射。",
        "- `高 RR 但仍空仓观望` 样本值得优先复判，通常意味着结构赔率已出现，但触发器没有升级。",
        "- `连续性未满分样本日` 直接对应 docs/new 三个基准样本的剩余差距。",
        "",
        "## 文件",
        "",
        f"- [unknown_cohort.csv]({(output_dir / 'unknown_cohort.csv').resolve()})",
        f"- [markup_stand_aside_cohort.csv]({(output_dir / 'markup_stand_aside_cohort.csv').resolve()})",
        f"- [high_rr_no_action_cohort.csv]({(output_dir / 'high_rr_no_action_cohort.csv').resolve()})",
        f"- [sample_mismatch_cohort.csv]({(output_dir / 'sample_mismatch_cohort.csv').resolve()})",
    ]
    (output_dir / "gap_study_report.md").write_text("\n".join(report_lines), encoding="utf-8")

    return {
        "batch_count": len(batch_rows),
        "analyzed_count": len(analyzed_rows),
        "unknown_count": len(unknown_rows),
        "markup_stand_aside_count": len(markup_stand_aside_rows),
        "high_rr_no_action_count": len(high_rr_no_action_rows),
        "sample_mismatch_count": len(low_score_rows),
        "avg_sample_score": avg_sample_score,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="基于批量扫描结果生成威科夫误差样本研究")
    parser.add_argument(
        "--batch-summary",
        default="output/wyckoff_stock_list_full/latest_5199_stock_summary.csv",
        help="全量扫描汇总 CSV",
    )
    parser.add_argument(
        "--continuity",
        default="output/wyckoff_daily_replay/continuity_comparison.csv",
        help="样本连续性对比 CSV",
    )
    parser.add_argument(
        "--output",
        default="output/wyckoff_batch_gap_study",
        help="输出目录",
    )
    parser.add_argument("--cohort-size", type=int, default=30, help="每类误差样本导出数量")
    args = parser.parse_args()

    stats = build_gap_study(
        batch_summary_csv=PROJECT_ROOT / args.batch_summary,
        continuity_csv=PROJECT_ROOT / args.continuity,
        output_dir=PROJECT_ROOT / args.output,
        cohort_size=args.cohort_size,
    )
    print(f"saved: {PROJECT_ROOT / args.output / 'gap_study_report.md'}")
    print(stats)


if __name__ == "__main__":
    main()
