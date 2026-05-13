#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import argparse
from pathlib import Path

from src.reporting import Optimal8ReadableReportGenerator


def _resolve_summary_csv(requested_path: str) -> Path:
    summary_path = Path(requested_path)
    if summary_path.exists():
        return summary_path

    summary_dir = summary_path.parent
    pattern = "walk_forward_optimal_8index_summary_*.csv"
    candidates = sorted(
        summary_dir.glob(pattern), key=lambda item: item.stat().st_mtime, reverse=True
    )
    if candidates:
        return candidates[0]

    raise FileNotFoundError(f"未找到输入文件: {requested_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="生成8指数风控结果可读报告（优化版）")
    parser.add_argument(
        "--summary-csv",
        default="output/MA/summary/latest_walk_forward_optimal_8index_summary.csv",
        help="输入汇总CSV路径",
    )
    parser.add_argument(
        "--report-dir",
        default="output/MA/reports",
        help="输出报告目录",
    )
    parser.add_argument(
        "--plot-dir",
        default="output/MA/plots",
        help="输出图表目录",
    )
    parser.add_argument(
        "--output-stem",
        default="optimal8_human_friendly_report_v2",
        help="输出文件名前缀",
    )
    args = parser.parse_args()

    try:
        summary_path = _resolve_summary_csv(args.summary_csv)
    except FileNotFoundError as exc:
        raise SystemExit(str(exc))

    generator = Optimal8ReadableReportGenerator(report_dir=args.report_dir, plot_dir=args.plot_dir)
    outputs = generator.generate(summary_csv=str(summary_path), output_stem=args.output_stem)

    print("报告生成完成:")
    for key, value in outputs.items():
        print(f"- {key}: {value}")


if __name__ == "__main__":
    main()
