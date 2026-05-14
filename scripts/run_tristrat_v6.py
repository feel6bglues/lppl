#!/usr/bin/env python3
# DEPRECATED: 请使用 scripts/run_backtest.py 替代。本文件将在下个迭代移除。
# 薄封装

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.backtest_core import run_backtest

N_WINDOWS = 20
N_STOCKS = 99999

result = run_backtest(
    strategies=["wyckoff", "ma_cross"],
    n_windows=N_WINDOWS,
    min_year=2016,
    max_year=2026,
    with_costs=False,
    n_stocks_limit=N_STOCKS,
)

if not result.get("strategies"):
    print("无交易")
else:
    for sn, st in result["strategies"].items():
        print(f"  {sn}: n={st['n']} sharpe={st['sharpe']} ret={st['mean_ret']}%")
    print(f"  组合夏普: {result['portfolio']['multi_strat_sharpe']:.3f}")
