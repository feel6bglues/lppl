"""失败路径测试：统一入口在非法输入下逐层失败"""

import subprocess, sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENTRY = "scripts/run_backtest.py"


def _run(extra: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, ENTRY] + extra, capture_output=True, text=True,
        cwd=str(PROJECT_ROOT), timeout=60,
    )


# --- 纯函数单元测试（通过 backtest_core 验证 validate_*）---
# 实际验证逻辑在 run_backtest.py 顶层，这里 CLI 端到端只保留代表路径


def test_cli_rejects_unknown_strategy():
    r = _run(["--strategies", "bogus", "--windows", "3", "--name", "ut"])
    assert r.returncode != 0
    assert "未知策略" in r.stderr


def test_cli_rejects_inverted_years():
    r = _run(["--strategies", "ma_cross", "--windows", "3",
              "--min-year", "2030", "--max-year", "2020", "--name", "ut"])
    assert r.returncode != 0
    assert "min-year" in r.stderr


def test_cli_rejects_negative_windows():
    r = _run(["--strategies", "ma_cross", "--windows", "-1", "--name", "ut"])
    assert r.returncode != 0
    assert "windows" in r.stderr


def test_cli_rejects_empty_name():
    r = _run(["--strategies", "ma_cross", "--name", ""])
    assert r.returncode != 0
