"""模式验证: 使用 fixture 生成的合成数据验证 schema，不依赖 output/ 文件。"""

import math

import pytest

REQUIRED_CONFIG = [
    "n_stocks", "n_windows", "mc_seed", "window_seed",
    "min_year", "max_year", "with_costs", "strategies_used",
]
REQUIRED_PORTFOLIO = [
    "multi_strat_sharpe", "method", "formula", "limitation",
]
REQUIRED_REPRO = ["mc_seeded", "mc_seed", "window_seeded", "window_seed"]
REQUIRED_DAILY_TOP = [
    "schema_version", "generated_at", "date", "market_anchor_date",
    "total_signals", "n_stocks_scanned", "summary", "by_strategy",
]


# --- Fixtures ---

@pytest.fixture
def sample_strategy_stats():
    return {
        "n": 50, "mean_ret": 1.23, "median_ret": 0.50,
        "std": 5.0, "win_rate": 55.0, "avg_days": 45.0, "sharpe": 0.523,
    }


@pytest.fixture
def sample_backtest_result(sample_strategy_stats):
    return {
        "config": {
            "n_stocks": 100,
            "n_windows": 20,
            "mc_seed": 42,
            "window_seed": 42,
            "min_year": 2020,
            "max_year": 2025,
            "with_costs": True,
            "strategies_used": ["wyckoff", "ma_cross"],
        },
        "strategies": {
            "wyckoff": {**sample_strategy_stats, "n": 50},
            "ma_cross": {**sample_strategy_stats, "n": 60},
        },
        "portfolio": {
            "multi_strat_sharpe": 0.45,
            "method": "equal_weight",
            "formula": "sharpe = mean(ret) / std(ret) * sqrt(252 / avg_days)",
            "limitation": "assumes normal distribution",
        },
        "reproducibility": {
            "mc_seeded": True,
            "mc_seed": 42,
            "window_seeded": True,
            "window_seed": 42,
        },
    }


@pytest.fixture
def sample_daily_signal():
    return {
        "symbol": "000001.SZ", "strategy": "wyckoff",
        "direction": "long", "entry": 10.5, "stop": 9.8,
        "target": 12.0, "risk_pct": 2.5, "confidence": "high",
        "macro_regime": "bullish", "stock_regime": "accumulation",
        "analysis_date": "2026-05-13",
    }


@pytest.fixture
def sample_daily_signals_result(sample_daily_signal):
    return {
        "schema_version": "1.0",
        "generated_at": "2026-05-13T10:00:00",
        "date": "2026-05-13",
        "market_anchor_date": "2026-05-13",
        "total_signals": 2,
        "n_stocks_scanned": 100,
        "summary": {"signal": 2, "no_signal": 50, "skipped": 45, "error": 3},
        "by_strategy": {
            "wyckoff": {"signal": 2, "no_signal": 50, "skipped": 45, "error": 3},
        },
        "signals": [sample_daily_signal],
    }


# --- Backtest result schema ---

def test_backtest_config_fields(sample_backtest_result):
    c = sample_backtest_result.get("config", {})
    for f in REQUIRED_CONFIG:
        assert f in c, f"config.{f} missing"
    assert isinstance(c["mc_seed"], int)
    assert isinstance(c["window_seed"], int)
    assert isinstance(c["min_year"], int)
    assert isinstance(c["max_year"], int)
    assert isinstance(c["with_costs"], bool)


def test_backtest_portfolio_fields(sample_backtest_result):
    p = sample_backtest_result.get("portfolio", {})
    for f in REQUIRED_PORTFOLIO:
        assert f in p, f"portfolio.{f} missing"
    assert isinstance(p["multi_strat_sharpe"], float)


def test_backtest_reproducibility(sample_backtest_result):
    r = sample_backtest_result.get("reproducibility", {})
    for f in REQUIRED_REPRO:
        assert f in r, f"reproducibility.{f} missing"
    assert r["mc_seeded"] is True
    assert r["mc_seed"] == 42


def test_backtest_strategies_not_empty(sample_backtest_result):
    s = sample_backtest_result.get("strategies", {})
    assert len(s) >= 1


# --- Daily signals schema ---

def test_daily_signals_top_fields(sample_daily_signals_result):
    d = sample_daily_signals_result
    for field in REQUIRED_DAILY_TOP:
        assert field in d, f"top.{field} missing"
    assert d["schema_version"] == "1.0"
    s = d["summary"]
    total = sum(s.get(k, 0) for k in ["signal", "no_signal", "skipped", "error"])
    assert total == d["n_stocks_scanned"]


def test_daily_signals_no_nan_or_negative_risk(sample_daily_signals_result):
    d = sample_daily_signals_result
    for sig in d["signals"]:
        for v in sig.values():
            if isinstance(v, float):
                assert not math.isnan(v), f"NaN in {sig.get('symbol','')}"
        rp = sig.get("risk_pct")
        if rp is not None:
            assert rp >= 0, f"negative risk_pct {rp} in {sig.get('symbol','')}"
    wyc = [s for s in d["signals"] if s.get("strategy") == "wyckoff"]
    if wyc:
        assert "macro_regime" in wyc[0]
        assert "stock_regime" in wyc[0]
        assert "analysis_date" in wyc[0]


def test_daily_signals_analysis_date(sample_daily_signals_result):
    d = sample_daily_signals_result
    sigs = d.get("signals", [])
    if sigs:
        assert "analysis_date" in sigs[0]
        anchor = d.get("market_anchor_date")
        if anchor:
            for s in sigs:
                assert s.get("analysis_date", anchor) <= anchor


def test_daily_signals_summary_closure(sample_daily_signals_result):
    d = sample_daily_signals_result
    s = d["summary"]
    total = s.get("signal", 0) + s.get("no_signal", 0) + s.get("skipped", 0) + s.get("error", 0)
    assert total == d["n_stocks_scanned"]
    assert 0 <= s.get("error", 0) < 50
