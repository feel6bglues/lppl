#!/usr/bin/env python3
# DEPRECATED: 请使用 scripts/run_backtest.py 替代。本文件将在下个迭代移除。
# CLI 参数透传 — 100% 同一代码路径

import sys, subprocess, shutil
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
NAME = "dual_strat_wyckoff_ma"

ret = subprocess.call([sys.executable, "scripts/run_backtest.py",
    "--strategies", "wyckoff,ma_cross",
    "--windows", "30",
    "--min-year", "2020", "--max-year", "2026",
    "--name", NAME,
])

old = PROJECT_ROOT / "output" / NAME / "results.json"
new = PROJECT_ROOT / "output" / NAME / "dual_results.json"
if old.exists():
    shutil.move(str(old), str(new))
sys.exit(ret)
