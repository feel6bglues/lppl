"""验证所有结果文件schema一致性，防止静默退化"""

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


def _resolve(fp_dir: Path) -> list[Path]:
    """解析目录下的结果文件：优先 results.json，回退 legacy 命名"""
    cand = fp_dir / "results.json"
    if cand.exists():
        return [cand]
    return [fp_dir / n for n in LEGACY_NAMES if (fp_dir / n).exists()]


def _result_files() -> list[Path]:
    files = []
    for d in RESULT_DIRS:
        files.extend(_resolve(PROJECT_ROOT / d))
    return files


def _load_and_require(rel_path: str) -> dict:
    fp = PROJECT_ROOT / rel_path
    assert fp.exists(), f"{rel_path} not found (run the thin wrapper first)"
    return json.loads(fp.read_text())


@pytest.mark.parametrize("rel_path", [str(p.relative_to(PROJECT_ROOT)) for p in _result_files()])
def test_backtest_config_fields(rel_path):
    d = _load_and_require(rel_path)
    c = d.get("config", {})
    for field in REQUIRED_CONFIG_FIELDS:
        assert field in c, f"{rel_path}: config.{field} missing"
    assert isinstance(c["mc_seed"], int)
    assert isinstance(c["window_seed"], int)
    assert isinstance(c["min_year"], int)
    assert isinstance(c["max_year"], int)
    assert isinstance(c["with_costs"], bool)


@pytest.mark.parametrize("rel_path", [str(p.relative_to(PROJECT_ROOT)) for p in _result_files()])
def test_backtest_portfolio_fields(rel_path):
    d = _load_and_require(rel_path)
    p = d.get("portfolio", {})
    for field in REQUIRED_PORTFOLIO_FIELDS:
        assert field in p, f"{rel_path}: portfolio.{field} missing"
    assert isinstance(p["multi_strat_sharpe"], float)


@pytest.mark.parametrize("rel_path", [str(p.relative_to(PROJECT_ROOT)) for p in _result_files()])
def test_backtest_reproducibility(rel_path):
    d = _load_and_require(rel_path)
    r = d.get("reproducibility", {})
    for field in REQUIRED_REPRO_FIELDS:
        assert field in r, f"{rel_path}: reproducibility.{field} missing"
    assert r["mc_seeded"] is True
    assert r["mc_seed"] == 42


@pytest.mark.parametrize("rel_path", [str(p.relative_to(PROJECT_ROOT)) for p in _result_files()])
def test_backtest_strategies_not_empty(rel_path):
    d = _load_and_require(rel_path)
    s = d.get("strategies", {})
    assert len(s) >= 1, f"{rel_path}: no strategies in results"


@pytest.mark.parametrize("rel_path", DAILY_SIGNAL_FILES)
def test_daily_signals_top_fields(rel_path):
    d = _load_and_require(rel_path)
    for field in REQUIRED_DAILY_TOP:
        assert field in d, f"{rel_path}: top.{field} missing"
    assert d["schema_version"] == "1.0"
    s = d["summary"]
    total = sum(s.get(k, 0) for k in ["signal", "no_signal", "skipped", "error"])
    assert total == d["n_stocks_scanned"], f"{rel_path}: summary total {total} != n_stocks_scanned {d['n_stocks_scanned']}"


@pytest.mark.parametrize("rel_path", DAILY_SIGNAL_FILES)
def test_daily_signals_no_nan_or_negative_risk(rel_path):
    import math
    d = _load_and_require(rel_path)
    for sig in d["signals"]:
        for v in sig.values():
            if isinstance(v, float):
                assert not math.isnan(v), f"{rel_path}: NaN found in {sig.get('symbol','')}"
        rp = sig.get("risk_pct")
        if rp is not None:
            assert rp >= 0, f"{rel_path}: negative risk_pct {rp} in {sig.get('symbol','')}"
    wyc = [s for s in d["signals"] if s.get("strategy") == "wyckoff"]
    if wyc:
        assert "macro_regime" in wyc[0], f"{rel_path}: missing macro_regime"
        assert "stock_regime" in wyc[0], f"{rel_path}: missing stock_regime"
        assert "analysis_date" in wyc[0], f"{rel_path}: missing analysis_date"


@pytest.mark.parametrize("rel_path", DAILY_SIGNAL_FILES)
def test_daily_signals_analysis_date(rel_path):
    d = _load_and_require(rel_path)
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
    d = _load_and_require("output/daily_signals/signals_2026-05-13.json")
    s = d["summary"]
    total = s.get("signal", 0) + s.get("no_signal", 0) + s.get("skipped", 0) + s.get("error", 0)
    assert total == d["n_stocks_scanned"], \
        f"summary total {total} != scanned {d['n_stocks_scanned']}"
    assert 0 <= s.get("error", 0) < 50, f"too many errors: {s.get('error',0)}"
