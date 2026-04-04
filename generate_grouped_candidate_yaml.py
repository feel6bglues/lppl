#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse

import pandas as pd

from src.investment.group_rescan import write_merged_candidate_yaml


def main() -> None:
    parser = argparse.ArgumentParser(description="生成大盘组三只指数的 YAML 写回草案")
    parser.add_argument(
        "--output",
        default="output/grouped_ma_rescan_candidate_yaml.yaml",
        help="输出 YAML 草案路径",
    )
    parser.add_argument(
        "--balanced-summary",
        default="output/grouped_ma_rescan_balanced/summary.csv",
        help="平衡组重扫 summary.csv 路径",
    )
    args = parser.parse_args()

    try:
        balanced_summary_df = pd.read_csv(args.balanced_summary)
    except Exception:
        balanced_summary_df = None

    output_path = write_merged_candidate_yaml(
        args.output,
        balanced_summary_df=balanced_summary_df,
    )
    print(f"YAML 草案已保存: {output_path}")


if __name__ == "__main__":
    main()
