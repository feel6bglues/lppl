"""旧脚本透传回归测试：验证 run_*.py 薄封装稳定性

对每个旧脚本做小样本 smoke，单次执行覆盖三项断言：
  - 退出码为 0
  - 只生成 legacy 文件名（不残留 results.json）
  - 产物 schema 合法
"""

import json, shutil, subprocess, sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]

WRAPPER_CFGS = [
    ("scripts/run_dual_strat_backtest.py",   "dual_strat_backtest_2020", "dual_results.json"),
    ("scripts/run_dual_strat_wyckoff_ma.py", "dual_strat_wyckoff_ma",    "dual_results.json"),
    ("scripts/run_tristrat_v6_str.py",       "tristrat_v6_str",          "v6_results.json"),
    ("scripts/run_tristrat_v6_str_2018.py",  "tristrat_v6_str_2018",     "v6_results.json"),
    ("scripts/run_tristrat_v6_str_2020.py",  "tristrat_v6_str_2020",     "v6_results.json"),
]

LIMIT = 200


def _verify_schema(fp: Path):
    assert fp.exists(), f"{fp} not generated"
    d = json.loads(fp.read_text())

    c = d.get("config", {})
    for f in ["n_stocks", "n_windows", "mc_seed", "window_seed",
              "min_year", "max_year", "with_costs", "strategies_used"]:
        assert f in c, f"config.{f} missing"
    assert isinstance(c["min_year"], int)
    assert isinstance(c["max_year"], int)
    assert isinstance(c["with_costs"], bool)
    assert isinstance(c["strategies_used"], list)

    p = d.get("portfolio", {})
    for f in ["multi_strat_sharpe", "method", "formula", "limitation"]:
        assert f in p, f"portfolio.{f} missing"
    assert isinstance(p["multi_strat_sharpe"], (float, int))

    r = d.get("reproducibility", {})
    for f in ["mc_seeded", "mc_seed", "window_seeded", "window_seed"]:
        assert f in r, f"reproducibility.{f} missing"
    assert r["mc_seeded"] is True

    assert len(d.get("strategies", {})) >= 1


@pytest.mark.slow
@pytest.mark.parametrize("script,outdir,legacy_name", WRAPPER_CFGS)
def test_legacy_wrapper_passthrough(script, outdir, legacy_name):
    """单次执行旧脚本，验证退出码、文件名、schema 三件事"""
    output_dir = PROJECT_ROOT / "output" / outdir
    if output_dir.exists():
        shutil.rmtree(str(output_dir))

    r = subprocess.run(
        [sys.executable, script, "--limit", str(LIMIT)],
        capture_output=True, text=True, timeout=180,
        cwd=str(PROJECT_ROOT),
    )

    # 1. 退出码
    assert r.returncode == 0, \
        f"{script} exit {r.returncode}: {r.stderr[:300]}"

    # 2. 只生成 legacy 文件名，不残留 results.json
    assert output_dir.exists(), f"output dir {outdir} not created"
    results_json = output_dir / "results.json"
    legacy_json = output_dir / legacy_name
    assert not results_json.exists(), \
        f"stray results.json in {outdir} (should only have {legacy_name})"
    assert legacy_json.exists(), \
        f"legacy file {legacy_name} not found in {outdir}"

    # 3. 产物 schema 合法
    _verify_schema(legacy_json)
