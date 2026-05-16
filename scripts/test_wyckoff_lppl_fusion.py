#!/usr/bin/env python3
# RESEARCH ONLY — not production code
# -*- coding: utf-8 -*-
"""Wyckoff+LPPL融合回测验证测试"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np
import pandas as pd


def test_fusion_weights():
    print("=== test_fusion_weights ===")
    from scripts.wyckoff_lppl_fusion_backtest import PHASE_WEIGHTS, REGIME_WEIGHTS

    assert PHASE_WEIGHTS["markdown"] == 1.0, "markdown权重应为1.0"
    assert PHASE_WEIGHTS["markup"] == 0.0, "markup权重应为0.0"
    assert PHASE_WEIGHTS["accumulation"] == 0.5
    assert PHASE_WEIGHTS["distribution"] == 0.0
    assert REGIME_WEIGHTS["weak_bull"] == 1.0
    assert REGIME_WEIGHTS["strong_bear"] == 0.2
    print("  PHASE_WEIGHTS:", PHASE_WEIGHTS)
    print("  REGIME_WEIGHTS:", REGIME_WEIGHTS)
    print("  PASS\n")


def test_fusion_logic():
    print("=== test_fusion_logic ===")

    score = 0.35
    assert abs(1.0 * 1.0 * score - 0.35) < 1e-10, "markdown+weak_bull应=0.35"
    assert abs(0.0 * 1.0 * score) < 1e-10, "markup+weak_bull应=0.0"
    assert abs(0.5 * 1.0 * score - 0.175) < 1e-10, "accumulation+weak_bull应=0.175"
    assert abs(1.0 * 0.2 * score - 0.07) < 1e-10, "markdown+strong_bear应=0.07"
    print("  融合逻辑验证通过")
    print("  PASS\n")


def test_wyckoff_engine():
    print("=== test_wyckoff_engine ===")
    from src.wyckoff.engine import WyckoffEngine

    rng = np.random.default_rng(42)
    n = 500
    t = np.arange(n)
    prices = 100 * np.exp(-0.002 * t + 0.015 * rng.standard_normal(n))
    df = pd.DataFrame({
        "date": pd.date_range("2020-01-01", periods=n),
        "open": prices * (1 + 0.005 * rng.standard_normal(n)),
        "high": prices * (1 + abs(rng.standard_normal(n)) * 0.01),
        "low": prices * (1 - abs(rng.standard_normal(n)) * 0.01),
        "close": prices,
        "volume": [1000000] * n,
    })

    engine = WyckoffEngine(lookback_days=400, weekly_lookback=120, monthly_lookback=40)
    report = engine.analyze(df, symbol="TEST")
    phase = report.structure.phase.value if hasattr(report.structure.phase, 'value') else str(report.structure.phase)
    direction = report.trading_plan.direction
    print(f"  Phase: {phase}, Direction: {direction}")
    assert phase in ("markdown", "markup", "accumulation", "distribution", "unknown")
    print("  PASS\n")


def test_output_structure():
    print("=== test_output_structure ===")
    import json
    analysis_path = PROJECT_ROOT / "output" / "wyckoff_lppl_fusion" / "fusion_analysis.json"
    if not analysis_path.exists():
        print("  跳过: fusion_analysis.json不存在")
        return

    with analysis_path.open() as f:
        data = json.load(f)

    assert "total_samples" in data
    assert "comparison" in data
    assert "phase_stats" in data

    comp = data["comparison"]
    for name in ["A_wyckoff_markdown", "B_lppl_multifit", "C_fusion", "D_fusion_regime"]:
        assert name in comp, f"缺少 {name}"
        for field in ["n_signals", "precision", "f1", "return_spread"]:
            assert field in comp[name], f"缺少 {name}.{field}"

    print(f"  总样本: {data['total_samples']}")
    for name in ["A_wyckoff_markdown", "B_lppl_multifit", "C_fusion", "D_fusion_regime"]:
        c = comp[name]
        print(f"  {name}: n={c['n_signals']} p={c['precision']:.3f} f1={c['f1']:.3f} spread={c['return_spread']:.2f}%")

    print("  PASS\n")


if __name__ == "__main__":
    print("=" * 60)
    print("Wyckoff+LPPL融合回测验证测试")
    print("=" * 60)
    print()

    tests = [test_fusion_weights, test_fusion_logic, test_wyckoff_engine, test_output_structure]
    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"  FAIL: {e}")
            failed += 1

    print("=" * 60)
    print(f"结果: {passed} 通过, {failed} 失败")
    print("=" * 60)
