#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""纯Wyckoff优化验证测试"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def test_optimizer_logic():
    print("=== test_optimizer_logic ===")
    from src.wyckoff_optimizer import optimize_signal

    r = optimize_signal("markdown", "空仓观望", "D", "mixed")
    assert r.optimized_direction == "空仓观望", f"markdown+D+mixed应为空仓观望, got {r.optimized_direction}"
    assert r.is_actionable == False

    r = optimize_signal("markdown", "空仓观望", "B", "fully_aligned")
    assert r.optimized_direction == "做多", f"markdown+空仓+B+fully应为做多, got {r.optimized_direction}"
    assert r.is_actionable == True

    r = optimize_signal("markup", "持有观察", "D", "fully_aligned")
    assert r.optimized_direction == "空仓观望", f"markup应为空仓观望, got {r.optimized_direction}"
    assert r.is_actionable == False

    r = optimize_signal("markdown", "空仓观望", "D", "fully_aligned")
    assert r.optimized_direction == "轻仓试探", f"markdown+D+fully应为轻仓试探, got {r.optimized_direction}"
    assert r.is_actionable == True

    r = optimize_signal("distribution", "空仓观望", "D", "mixed")
    assert r.optimized_direction == "空仓观望"
    assert r.is_actionable == False

    r = optimize_signal("accumulation", "空仓观望", "D", "mixed", spring_detected=True)
    assert r.optimized_direction == "轻仓试探"
    assert r.is_actionable == True

    r = optimize_signal("accumulation", "空仓观望", "D", "mixed", spring_detected=False)
    assert r.optimized_direction == "观察等待"
    assert r.is_actionable == False

    r = optimize_signal("markdown", "空仓观望", "D", "higher_timeframe_aligned")
    assert r.optimized_direction == "轻仓试探"
    assert r.is_actionable == True

    print("  8/8 信号优化逻辑验证通过")
    print("  PASS\n")


def test_composite_score():
    print("=== test_composite_score ===")
    from src.wyckoff_optimizer import optimize_signal

    r = optimize_signal("markdown", "空仓观望", "D", "fully_aligned")
    assert abs(r.composite_score - 1.0 * 1.0 * 1.0) < 1e-10, f"markdown+D+fully应=1.0, got {r.composite_score}"

    r = optimize_signal("markdown", "空仓观望", "C", "mixed")
    expected = 1.0 * 0.1 * 0.3
    assert abs(r.composite_score - expected) < 1e-10, f"markdown+C+mixed应={expected}, got {r.composite_score}"

    r = optimize_signal("markup", "空仓观望", "D", "fully_aligned")
    assert r.composite_score == 0.0, f"markup应=0.0, got {r.composite_score}"

    print("  composite_score验证通过")
    print("  PASS\n")


def test_output_structure():
    print("=== test_output_structure ===")
    import json
    path = PROJECT_ROOT / "output" / "wyckoff_optimizer" / "optimizer_analysis.json"
    if not path.exists():
        print("  跳过: 文件不存在")
        return

    with path.open() as f:
        data = json.load(f)

    assert "total_samples" in data
    assert "comparison" in data
    comp = data["comparison"]
    for name in ["A_raw_all", "A_raw_markdown_only", "B_opt_actionable", "B_opt_markdown_only"]:
        assert name in comp, f"缺少 {name}"

    print(f"  总样本: {data['total_samples']}")
    for name in ["A_raw_all", "A_raw_markdown_only", "B_opt_actionable", "B_opt_markdown_only"]:
        c = comp[name]
        n = c.get("n_signals", 0)
        if n > 0:
            print(f"  {name}: n={n} p={c.get('precision',0)*100:.1f}% f1={c.get('f1',0):.3f} spread={c.get('return_spread',0):.2f}%")
        else:
            print(f"  {name}: 0 signals")
    print("  PASS\n")


if __name__ == "__main__":
    print("=" * 60)
    print("纯Wyckoff优化验证测试")
    print("=" * 60)
    print()

    tests = [test_optimizer_logic, test_composite_score, test_output_structure]
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
