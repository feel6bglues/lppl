"""验证所有结果文件schema一致性，防止静默退化"""

import json
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]

RESULT_FILES = [
    "output/dual_strat_backtest_2020/dual_results.json",
    "output/dual_strat_wyckoff_ma/dual_results.json",
    "output/tristrat_v6_str/v6_results.json",
    "output/tristrat_v6_str_2018/v6_results.json",
    "output/tristrat_v6_str_2020/v6_results.json",
]

REQUIRED_CONFIG_FIELDS = [
    "n_stocks", "n_windows", "mc_seed", "window_seed",
    "min_year", "max_year", "with_costs", "strategies_used",
]

REQUIRED_PORTFOLIO_FIELDS = [
    "multi_strat_sharpe", "method", "formula", "limitation",
]

REQUIRED_REPRO_FIELDS = ["mc_seeded", "mc_seed", "window_seeded", "window_seed"]

DAILY_SIGNAL_FILES = [
    "output/daily_signals/signals_2026-05-13.json",
]

REQUIRED_DAILY_TOP = [
    "schema_version", "generated_at", "date", "market_anchor_date",
    "total_signals", "n_stocks_scanned", "summary", "by_strategy",
]


@pytest.mark.parametrize("rel_path", RESULT_FILES)
def test_backtest_config_fields(rel_path):
    fp = PROJECT_ROOT / rel_path
    assert fp.exists(), f"{rel_path} not found"
    d = json.loads(fp.read_text())
    c = d.get("config", {})
    for field in REQUIRED_CONFIG_FIELDS:
        assert field in c, f"{rel_path}: config.{field} missing"
    assert isinstance(c["mc_seed"], int)
    assert isinstance(c["window_seed"], int)
    assert isinstance(c["min_year"], int)
    assert isinstance(c["max_year"], int)
    assert isinstance(c["with_costs"], bool)


@pytest.mark.parametrize("rel_path", RESULT_FILES)
def test_backtest_portfolio_fields(rel_path):
    fp = PROJECT_ROOT / rel_path
    d = json.loads(fp.read_text())
    p = d.get("portfolio", {})
    for field in REQUIRED_PORTFOLIO_FIELDS:
        assert field in p, f"{rel_path}: portfolio.{field} missing"
    assert isinstance(p["multi_strat_sharpe"], float)


@pytest.mark.parametrize("rel_path", RESULT_FILES)
def test_backtest_reproducibility(rel_path):
    fp = PROJECT_ROOT / rel_path
    d = json.loads(fp.read_text())
    r = d.get("reproducibility", {})
    for field in REQUIRED_REPRO_FIELDS:
        assert field in r, f"{rel_path}: reproducibility.{field} missing"
    assert r["mc_seeded"] is True
    assert r["mc_seed"] == 42


@pytest.mark.parametrize("rel_path", RESULT_FILES)
def test_backtest_strategies_not_empty(rel_path):
    fp = PROJECT_ROOT / rel_path
    d = json.loads(fp.read_text())
    s = d.get("strategies", {})
    assert len(s) >= 1, f"{rel_path}: no strategies in results"


@pytest.mark.parametrize("rel_path", DAILY_SIGNAL_FILES)
def test_daily_signals_top_fields(rel_path):
    fp = PROJECT_ROOT / rel_path
    assert fp.exists(), f"{rel_path} not found"
    d = json.loads(fp.read_text())
    for field in REQUIRED_DAILY_TOP:
        assert field in d, f"{rel_path}: top.{field} missing"
    assert d["schema_version"] == "1.0"
    # summary totals must match
    s = d["summary"]
    total = sum(s.get(k, 0) for k in ["signal", "no_signal", "skipped", "error"])
    assert total == d["n_stocks_scanned"], f"{rel_path}: summary total {total} != n_stocks_scanned {d['n_stocks_scanned']}"


@pytest.mark.parametrize("rel_path", DAILY_SIGNAL_FILES)
def test_daily_signals_no_nan_or_negative_risk(rel_path):
    import math
    fp = PROJECT_ROOT / rel_path
    d = json.loads(fp.read_text())
    for sig in d["signals"]:
        for v in sig.values():
            if isinstance(v, float):
                assert not math.isnan(v), f"{rel_path}: NaN found in {sig.get('symbol','')}"
        rp = sig.get("risk_pct")
        if rp is not None:
            assert rp >= 0, f"{rel_path}: negative risk_pct {rp} in {sig.get('symbol','')}"
    # Check Wyckoff signals have regime fields
    wyc = [s for s in d["signals"] if s.get("strategy") == "wyckoff"]
    if wyc:
        assert "macro_regime" in wyc[0], f"{rel_path}: missing macro_regime"
        assert "stock_regime" in wyc[0], f"{rel_path}: missing stock_regime"
        assert "analysis_date" in wyc[0], f"{rel_path}: missing analysis_date"


@pytest.mark.parametrize("rel_path", DAILY_SIGNAL_FILES)
def test_daily_signals_analysis_date(rel_path):
    fp = PROJECT_ROOT / rel_path
    d = json.loads(fp.read_text())
    sigs = d["signals"]
    if sigs:
        assert "analysis_date" in sigs[0]
        if "market_anchor_date" in d:
            anchor = d["market_anchor_date"]
            for s in sigs:
                assert s.get("analysis_date", anchor) <= anchor, \
                    f"{rel_path}: {s.get('symbol','')} analysis_date > anchor"


def test_daily_signals_summary_closure():
    """验证 summary 字段闭合：signal+no_signal+skipped+error = n_stocks_scanned"""
    fp = PROJECT_ROOT / "output/daily_signals/signals_2026-05-13.json"
    d = json.loads(fp.read_text())
    s = d["summary"]
    total = s.get("signal", 0) + s.get("no_signal", 0) + s.get("skipped", 0) + s.get("error", 0)
    assert total == d["n_stocks_scanned"], \
        f"summary total {total} != scanned {d['n_stocks_scanned']}"
    assert 0 <= s.get("error", 0) < 50, f"too many errors: {s.get('error',0)}"
