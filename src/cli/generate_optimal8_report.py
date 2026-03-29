#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import argparse
from pathlib import Path

from src.reporting import Optimal8ReadableReportGenerator


def main() -> None:
    parser = argparse.ArgumentParser(description="生成8指数风控结果可读报告（优化版）")
    parser.add_argument(
        "--summary-csv",
        default="output/MA/summary/walk_forward_optimal_8index_summary_20260329_171845.csv",
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

    summary_path = Path(args.summary_csv)
    if not summary_path.exists():
        raise SystemExit(f"未找到输入文件: {args.summary_csv}")

    generator = Optimal8ReadableReportGenerator(report_dir=args.report_dir, plot_dir=args.plot_dir)
    outputs = generator.generate(summary_csv=args.summary_csv, output_stem=args.output_stem)

    print("报告生成完成:")
    for key, value in outputs.items():
        print(f"- {key}: {value}")


if __name__ == "__main__":
    main()
