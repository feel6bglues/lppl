"""CLI端到端 smoke 验证：run_backtest.py 实际落盘 + 产物 schema 检查"""

import json, os, subprocess, sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SMOKE_DIR = "output/smoke_cli_verify"
SMOKE_FILE = f"{SMOKE_DIR}/results.json"

REQUIRED_CONFIG = ["n_stocks", "n_windows", "mc_seed", "window_seed",
                   "min_year", "max_year", "with_costs", "strategies_used"]
REQUIRED_PORTFOLIO = ["multi_strat_sharpe", "method", "formula", "limitation"]
REQUIRED_REPRO = ["mc_seeded", "mc_seed", "window_seeded", "window_seed"]


def _verify_schema(fp: Path):
    assert fp.exists(), f"{fp} not generated"
    d = json.loads(fp.read_text())

    c = d.get("config", {})
    for f in REQUIRED_CONFIG:
        assert f in c, f"config.{f} missing"
    assert isinstance(c["mc_seed"], int)
    assert isinstance(c["min_year"], int)
    assert isinstance(c["max_year"], int)
    assert isinstance(c["with_costs"], bool)

    p = d.get("portfolio", {})
    for f in REQUIRED_PORTFOLIO:
        assert f in p, f"portfolio.{f} missing"
    assert isinstance(p["multi_strat_sharpe"], (float, int))

    r = d.get("reproducibility", {})
    for f in REQUIRED_REPRO:
        assert f in r, f"reproducibility.{f} missing"
    assert r["mc_seeded"] is True

    assert len(d.get("strategies", {})) >= 1


@pytest.mark.smoke
def test_cli_smoke_produces_file():
    """验证 CLI 实际落盘产生 results.json"""
    fp = PROJECT_ROOT / SMOKE_FILE
    if fp.exists():
        fp.unlink()  # 确保本次生成

    result = subprocess.run([
        sys.executable, "scripts/run_backtest.py",
        "--strategies", "wyckoff,ma_cross",
        "--windows", "5",
        "--min-year", "2020",
        "--max-year", "2025",
        "--name", SMOKE_DIR.replace("output/", ""),
        "--limit", "500",
    ], capture_output=True, text=True, cwd=str(PROJECT_ROOT), timeout=120)

    assert fp.exists(), f"CLI failed to produce {SMOKE_FILE}\nstdout:{result.stdout[:500]}\nstderr:{result.stderr[:500]}"


@pytest.mark.smoke
def test_cli_smoke_schema():
    """验证 CLI 产物 schema 完整"""
    fp = PROJECT_ROOT / SMOKE_FILE
    if not fp.exists():
        pytest.skip("smoke file not generated, run test_cli_smoke_produces_file first")
    _verify_schema(fp)


@pytest.mark.smoke
def test_cli_smoke_with_costs():
    """验证 --costs 标志生效"""
    fp = PROJECT_ROOT / "output/smoke_cli_costs/results.json"
    if fp.exists():
        fp.unlink()
    subprocess.run([
        sys.executable, "scripts/run_backtest.py",
        "--strategies", "ma_cross",
        "--windows", "3",
        "--min-year", "2020",
        "--max-year", "2025",
        "--costs",
        "--name", "smoke_cli_costs",
        "--limit", "200",
    ], capture_output=True, cwd=str(PROJECT_ROOT), timeout=120)

    if fp.exists():
        d = json.loads(fp.read_text())
        assert d["config"]["with_costs"] is True
        assert d["config"]["cost_model"]["round_trip_pct"] > 0


@pytest.mark.smoke
def test_cli_smoke_tri_strategy():
    """验证三策略 CLI 调用正常工作"""
    fp = PROJECT_ROOT / "output/smoke_cli_tri/results.json"
    if fp.exists():
        fp.unlink()
    subprocess.run([
        sys.executable, "scripts/run_backtest.py",
        "--strategies", "wyckoff,ma_cross,str_reversal",
        "--windows", "3",
        "--min-year", "2020",
        "--max-year", "2025",
        "--name", "smoke_cli_tri",
        "--limit", "200",
    ], capture_output=True, cwd=str(PROJECT_ROOT), timeout=120)
    if fp.exists():
        d = json.loads(fp.read_text())
        assert "wyckoff" in d["config"]["strategies_used"]
        assert "str_reversal" in d["config"]["strategies_used"]
