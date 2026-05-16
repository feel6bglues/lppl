"""Smoke run 验证：小规模跑生成结果，验证schema一致性"""

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

REQUIRED_CONFIG = ["n_stocks", "n_windows", "mc_seed", "window_seed",
                   "min_year", "max_year", "with_costs", "strategies_used"]
REQUIRED_PORTFOLIO = ["multi_strat_sharpe", "method", "formula", "limitation"]
REQUIRED_REPRO = ["mc_seeded", "mc_seed", "window_seeded", "window_seed"]


def _check_schema(d: dict, label: str):
    c = d.get("config", {})
    for f in REQUIRED_CONFIG:
        assert f in c, f"{label}: config.{f} missing"
    assert isinstance(c["mc_seed"], int)
    assert isinstance(c["min_year"], int)
    assert isinstance(c["max_year"], int)

    p = d.get("portfolio", {})
    for f in REQUIRED_PORTFOLIO:
        assert f in p, f"{label}: portfolio.{f} missing"
    assert isinstance(p["multi_strat_sharpe"], (float, int))

    r = d.get("reproducibility", {})
    for f in REQUIRED_REPRO:
        assert f in r, f"{label}: reproducibility.{f} missing"
    assert r["mc_seeded"] is True
    assert r["mc_seed"] == 42

    # cost_model
    cm = c.get("cost_model", {})
    for f in ["buy_pct", "sell_pct", "round_trip_pct"]:
        assert f in cm, f"{label}: cost_model.{f} missing"

    # strategies not empty
    assert len(d.get("strategies", {})) >= 1


@pytest.mark.slow
def test_smoke_run_dual():
    from scripts.backtest_core import run_backtest
    result = run_backtest(
        strategies=["wyckoff", "ma_cross"],
        n_windows=3,
        min_year=2020,
        max_year=2025,
        with_costs=True,
        n_stocks_limit=200,
    )
    _check_schema(result, "smoke_dual")


@pytest.mark.slow
def test_smoke_run_tri():
    from scripts.backtest_core import run_backtest
    result = run_backtest(
        strategies=["wyckoff", "ma_cross", "str_reversal"],
        n_windows=3,
        min_year=2020,
        max_year=2025,
        with_costs=False,
        n_stocks_limit=100,
    )
    _check_schema(result, "smoke_tri")


@pytest.mark.slow
def test_smoke_run_costs_flag():
    """验证with_costs=False时不扣成本，cost_model.buy_pct=0"""
    from scripts.backtest_core import run_backtest
    result = run_backtest(
        strategies=["ma_cross"],
        n_windows=3,
        min_year=2020,
        max_year=2025,
        with_costs=False,
        n_stocks_limit=50,
    )
    assert result["config"]["with_costs"] is False
    assert result["config"]["cost_model"]["round_trip_pct"] == 0
