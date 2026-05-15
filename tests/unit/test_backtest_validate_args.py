"""纯函数校验：run_backtest 参数验证（非 subprocess，毫秒级）"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.run_backtest import validate_args, VALID_STRATEGIES


def test_valid_args_returns_empty():
    assert validate_args(["ma_cross"], 20, 2020, 2025, 100, "test") == []


def test_valid_all_strategies():
    assert validate_args(["wyckoff", "ma_cross", "str_reversal"], 20, 2020, 2025, 100, "t") == []


@pytest.mark.parametrize("strategies,expect", [
    (["bogus"],                        "未知策略"),
    (["wyckoff", "bogus"],             "未知策略"),
    (["bogus1", "bogus2"],             "未知策略"),
])
def test_unknown_strategies(strategies, expect):
    errs = validate_args(strategies, 20, 2020, 2025, 100, "t")
    assert any(expect in e for e in errs)


@pytest.mark.parametrize("windows,expect", [
    (0, "windows"),
    (-1, "windows"),
    (-999, "windows"),
])
def test_invalid_windows(windows, expect):
    errs = validate_args(["ma_cross"], windows, 2020, 2025, 100, "t")
    assert any(expect in e for e in errs)


def test_inverted_years():
    errs = validate_args(["ma_cross"], 20, 2030, 2020, 100, "t")
    assert any("min-year" in e for e in errs)


@pytest.mark.parametrize("limit,expect", [
    (0, "limit"),
    (-1, "limit"),
])
def test_invalid_limit(limit, expect):
    errs = validate_args(["ma_cross"], 20, 2020, 2025, limit, "t")
    assert any(expect in e for e in errs)


def test_empty_name():
    errs = validate_args(["ma_cross"], 20, 2020, 2025, 100, "")
    assert any("name" in e for e in errs)


def test_multiple_errors():
    errs = validate_args(["bogus"], 0, 2030, 2020, 0, "")
    assert len(errs) >= 4


def test_valid_strategies_constant():
    assert "wyckoff" in VALID_STRATEGIES
    assert "ma_cross" in VALID_STRATEGIES
    assert "str_reversal" in VALID_STRATEGIES


@pytest.mark.slow
def test_run_function_importable():
    """验证 run() 可作为 API 导入（非 subprocess）"""
    from scripts.run_backtest import run
    result = run(["ma_cross"], 3, 2020, 2025, False, "", 200)
    assert isinstance(result, dict)
    assert "config" in result
    # limit=200 应有足够交易产生 strategies 字段
    assert "strategies" in result, f"no strategies with limit=200: {result.get('config')}"
