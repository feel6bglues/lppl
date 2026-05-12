#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ma_cross_atr_optimization import run_single_backtest
from src.investment.group_rescan import BALANCED_PLAN, execute_group_rescan


def main() -> None:
    parser = argparse.ArgumentParser(description="平衡组 MA 主组合重扫")
    parser.add_argument("--start-date", default="2020-01-01", help="回测起始日期 YYYY-MM-DD")
    parser.add_argument("--end-date", default="2026-03-27", help="回测结束日期 YYYY-MM-DD")
    args = parser.parse_args()

    def backtest_runner(**kwargs):
        return run_single_backtest(
            start_date=args.start_date,
            end_date=args.end_date,
            **kwargs,
        )

    outputs = execute_group_rescan(BALANCED_PLAN, backtest_runner)
    print(f"详细结果已保存: {outputs['raw']}")
    print(f"汇总结果已保存: {outputs['summary']}")
    print(f"报告已保存: {outputs['report']}")


if __name__ == "__main__":
    main()
