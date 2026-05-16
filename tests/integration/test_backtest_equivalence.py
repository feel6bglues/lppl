"""等参回归测试：import 路径 vs CLI 路径输出等价性"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.tdx

PROJECT_ROOT = Path(__file__).resolve().parents[2]

EQUIV_CFGS = [
    ("dual_strat_backtest_2020", "wyckoff,ma_cross",
     ["wyckoff", "ma_cross"], 20, 2020, 2025, True),
    ("tristrat_v6_str", "wyckoff,ma_cross,str_reversal",
     ["wyckoff", "ma_cross", "str_reversal"], 20, 2016, 2026, False),
]

LIMIT = 200


@pytest.mark.slow
@pytest.mark.parametrize("name,strat_str,strat_list,nw,min_y,max_y,costs", EQUIV_CFGS)
def test_cli_equivalence(name, strat_str, strat_list, nw, min_y, max_y, costs):
    """验证 CLI 与 import 两路径产出一致"""
    sys.path.insert(0, str(PROJECT_ROOT))
    from scripts.backtest_core import run_backtest

    imp = run_backtest(
        strategies=strat_list, n_windows=nw,
        min_year=min_y, max_year=max_y,
        with_costs=costs, n_stocks_limit=LIMIT,
    )

    cli_dir = PROJECT_ROOT / "output" / (name + "_cli_eq")
    if cli_dir.exists():
        shutil.rmtree(str(cli_dir))

    cmd = [sys.executable, "scripts/run_backtest.py",
           "--strategies", strat_str,
           "--windows", str(nw),
           "--min-year", str(min_y),
           "--max-year", str(max_y),
           "--name", cli_dir.name,
           "--limit", str(LIMIT)]
    if costs:
        cmd.append("--costs")

    r = subprocess.run(cmd, capture_output=True, text=True,
                       cwd=str(PROJECT_ROOT), timeout=180)
    assert r.returncode == 0, f"CLI failed: {r.stderr[:500]}"

    cli_fp = cli_dir / "results.json"
    assert cli_fp.exists()
    cli = json.loads(cli_fp.read_text())

    # config 字段
    for k in ["n_stocks", "n_windows", "min_year", "max_year",
              "mc_seed", "window_seed", "with_costs"]:
        assert imp["config"][k] == cli["config"][k], \
            f"config.{k} mismatch: import={imp['config'][k]} cli={cli['config'][k]}"
    assert imp["config"]["strategies_used"] == cli["config"]["strategies_used"]

    # portfolio
    for k in ["method", "formula", "limitation"]:
        assert imp["portfolio"][k] == cli["portfolio"][k], \
            f"portfolio.{k} mismatch"

    # reproducibility
    for k in ["mc_seeded", "mc_seed", "window_seeded", "window_seed"]:
        assert imp["reproducibility"][k] == cli["reproducibility"][k], \
            f"reproducibility.{k} mismatch"

    # 交易数量 — 最敏感的退化指标
    all_strats = set(list(imp.get("strategies", {})) + list(cli.get("strategies", {})))
    for sk in all_strats:
        imp_n = imp.get("strategies", {}).get(sk, {}).get("n", 0)
        cli_n = cli.get("strategies", {}).get(sk, {}).get("n", 0)
        assert imp_n == cli_n, \
            f"{sk}: trade count mismatch import={imp_n} cli={cli_n}"

    shutil.rmtree(str(cli_dir))
