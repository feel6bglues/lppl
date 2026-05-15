"""失败路径测试：统一入口在非法输入下逐层失败"""

import subprocess, sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENTRY = "scripts/run_backtest.py"
BASE = [sys.executable, ENTRY, "--limit", "1", "--name", "err_test"]


def _run(extra: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        BASE + extra, capture_output=True, text=True,
        cwd=str(PROJECT_ROOT), timeout=60,
    )


PARSE_ERRORS = [
    ("无效策略名",         ["--strategies", "bogus"],          "未知策略"),
    ("部分有效部分无效",   ["--strategies", "wyckoff,bogus"],  "未知策略"),
    ("年份倒置",           ["--windows", "3", "--min-year", "2030", "--max-year", "2020"], "min-year"),
    ("windows=0",          ["--windows", "0"],                  "windows"),
    ("windows 负数",       ["--windows", "-1"],                 "windows"),
    ("limit=0",            ["--limit", "0"],                    "limit"),
    ("limit 负数",         ["--limit", "-5"],                   "limit"),
]


@pytest.mark.parametrize("desc,extra,expect", PARSE_ERRORS)
def test_cli_validation_errors(desc, extra, expect):
    r = _run(extra)
    assert r.returncode != 0, f"{desc}: expected nonzero exit"
    assert expect in r.stderr or expect in r.stdout, \
        f"{desc}: expected '{expect}' in output, got stderr={r.stderr[:200]} stdout={r.stdout[:200]}"


def test_empty_strategies_not_accepted():
    """argparse 拒绝空字符串策略"""
    r = _run(["--strategies", ""])
    assert r.returncode != 0


def test_missing_name():
    """argparse 不允许空 --name"""
    r = subprocess.run(
        [sys.executable, ENTRY, "--name", ""],
        capture_output=True, text=True,
        cwd=str(PROJECT_ROOT), timeout=30,
    )
    assert r.returncode != 0
