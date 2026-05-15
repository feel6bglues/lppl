"""结果文件 schema 一致性验证

对 output/ 下每个回测结果目录，解析存在的结果文件并验证字段完整。
验证字段组：config、portfolio、reproducibility、strategies。
"""

import json
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]

RESULT_DIRS = [
    "output/dual_strat_backtest_2020",
    "output/dual_strat_wyckoff_ma",
    "output/tristrat_v6_str",
    "output/tristrat_v6_str_2018",
    "output/tristrat_v6_str_2020",
]

LEGACY_NAMES = {"dual_results.json", "v6_results.json"}

REQUIRED_CONFIG = [
    "n_stocks", "n_windows", "mc_seed", "window_seed",
    "min_year", "max_year", "with_costs", "strategies_used",
]
REQUIRED_PORTFOLIO = [
    "multi_strat_sharpe", "method", "formula", "limitation",
]
REQUIRED_REPRO = ["mc_seeded", "mc_seed", "window_seeded", "window_seed"]

DAILY_SIGNALS = ["output/daily_signals/signals_2026-05-13.json"]
REQUIRED_DAILY_TOP = [
    "schema_version", "generated_at", "date", "market_anchor_date",
    "total_signals", "n_stocks_scanned", "summary", "by_strategy",
]


def _resolve(fp_dir: Path) -> Path:
    cand = fp_dir / "results.json"
    if cand.exists():
        return cand
    for n in LEGACY_NAMES:
        p = fp_dir / n
        if p.exists():
            return p
    return fp_dir / "results.json"  # fallback for helpful error


def _load_from_dir(rel_dir: str) -> dict:
    fp = _resolve(PROJECT_ROOT / rel_dir)
    assert fp.exists(), f"{fp} not found (run backtest first)"
    return json.loads(fp.read_text())


def _missing(fp_dir: Path) -> list[Path]:
    return [p for n in LEGACY_NAMES | {"results.json"} if not (fp_dir / n).exists() for p in [fp_dir / n]]


# --- backtest schema parametrized on directories ---
@pytest.mark.parametrize("rel_dir", RESULT_DIRS)
def test_backtest_config_fields(rel_dir):
    d = _load_from_dir(rel_dir)
    c = d.get("config", {})
    for f in REQUIRED_CONFIG:
        assert f in c, f"{rel_dir}: config.{f} missing"
    assert isinstance(c["mc_seed"], int)
    assert isinstance(c["window_seed"], int)
    assert isinstance(c["min_year"], int)
    assert isinstance(c["max_year"], int)
    assert isinstance(c["with_costs"], bool)


@pytest.mark.parametrize("rel_dir", RESULT_DIRS)
def test_backtest_portfolio_fields(rel_dir):
    d = _load_from_dir(rel_dir)
    p = d.get("portfolio", {})
    for f in REQUIRED_PORTFOLIO:
        assert f in p, f"{rel_dir}: portfolio.{f} missing"
    assert isinstance(p["multi_strat_sharpe"], float)


@pytest.mark.parametrize("rel_dir", RESULT_DIRS)
def test_backtest_reproducibility(rel_dir):
    d = _load_from_dir(rel_dir)
    r = d.get("reproducibility", {})
    for f in REQUIRED_REPRO:
        assert f in r, f"{rel_dir}: reproducibility.{f} missing"
    assert r["mc_seeded"] is True
    assert r["mc_seed"] == 42


@pytest.mark.parametrize("rel_dir", RESULT_DIRS)
def test_backtest_strategies_not_empty(rel_dir):
    d = _load_from_dir(rel_dir)
    s = d.get("strategies", {})
    assert len(s) >= 1, f"{rel_dir}: no strategies in results"


# --- daily signals ---
@pytest.mark.parametrize("rel_path", DAILY_SIGNALS)
def test_daily_signals_top_fields(rel_path):
    fp = PROJECT_ROOT / rel_path
    assert fp.exists(), f"{rel_path} not found"
    d = json.loads(fp.read_text())
    for field in REQUIRED_DAILY_TOP:
        assert field in d, f"{rel_path}: top.{field} missing"
    assert d["schema_version"] == "1.0"
    s = d["summary"]
    total = sum(s.get(k, 0) for k in ["signal", "no_signal", "skipped", "error"])
    assert total == d["n_stocks_scanned"]


@pytest.mark.parametrize("rel_path", DAILY_SIGNALS)
def test_daily_signals_no_nan_or_negative_risk(rel_path):
    import math
    fp = PROJECT_ROOT / rel_path
    d = json.loads(fp.read_text())
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


@pytest.mark.parametrize("rel_path", DAILY_SIGNALS)
def test_daily_signals_analysis_date(rel_path):
    d = json.loads((PROJECT_ROOT / rel_path).read_text())
    sigs = d.get("signals", [])
    if sigs:
        assert "analysis_date" in sigs[0]
        anchor = d.get("market_anchor_date")
        if anchor:
            for s in sigs:
                assert s.get("analysis_date", anchor) <= anchor


def test_daily_signals_summary_closure():
    fp = PROJECT_ROOT / "output/daily_signals/signals_2026-05-13.json"
    d = json.loads(fp.read_text())
    s = d["summary"]
    total = s.get("signal", 0) + s.get("no_signal", 0) + s.get("skipped", 0) + s.get("error", 0)
    assert total == d["n_stocks_scanned"]
    assert 0 <= s.get("error", 0) < 50
