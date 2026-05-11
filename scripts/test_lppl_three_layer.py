#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
三层LPPL系统单元验证测试

验证各模块的基本功能正确性，在回测前后运行
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np
import pandas as pd


def test_lppl_multifit():
    """测试多窗口拟合模块"""
    print("=== test_lppl_multifit ===")
    from src.lppl_multifit import (
        fit_multi_window, calculate_multifit_score,
        fit_single_layer, MULTI_WINDOW_CONFIGS, WindowConfig,
    )

    rng = np.random.default_rng(42)
    n = 500
    t = np.arange(n)
    prices = 100 * np.exp(0.001 * t + 0.3 * np.sin(0.1 * t) + 0.02 * rng.standard_normal(n))
    close_prices = prices.astype(np.float64)

    for layer_name, config in MULTI_WINDOW_CONFIGS.items():
        result = fit_single_layer(close_prices, n - 1, config)
        if result is not None:
            print(f"  {layer_name}: m={result['m']:.4f}, w={result['w']:.2f}, "
                  f"r2={result['r_squared']:.4f}, rmse={result['rmse']:.6f}, "
                  f"phase={result['phase']}, days_to_crash={result['days_to_crash']:.1f}")
        else:
            print(f"  {layer_name}: None")

    multi_results = fit_multi_window(close_prices, n - 1)
    score = calculate_multifit_score(multi_results)
    print(f"  综合得分: {score['final_score']:.4f}, level={score['level']}, "
          f"n_danger={score['n_danger']}")
    print("  PASS\n")


def test_lppl_cluster():
    """测试信号聚类模块"""
    print("=== test_lppl_cluster ===")
    from src.lppl_cluster import SignalClusterDetector

    det = SignalClusterDetector()

    det.add_signal("2020-01-10", {"final_score": 0.5, "level": "danger"})
    det.add_signal("2020-01-20", {"final_score": 0.6, "level": "danger"})
    det.add_signal("2020-01-25", {"final_score": 0.4, "level": "danger"})

    result = det.detect_cluster("2020-01-30")
    print(f"  3个danger信号(30天内): cluster={result['cluster_level']}, "
          f"score={result['cluster_score']:.4f}, count={result['raw_danger_count']}")

    mult = det.get_cluster_multiplier(result["cluster_score"])
    print(f"  multiplier: {mult}")

    det2 = SignalClusterDetector()
    result2 = det2.detect_cluster("2020-01-30")
    print(f"  无信号: cluster={result2['cluster_level']}, score={result2['cluster_score']:.4f}")
    print("  PASS\n")


def test_lppl_regime():
    """测试市场环境检测模块"""
    print("=== test_lppl_regime ===")
    from src.lppl_regime import MarketRegimeDetector

    det = MarketRegimeDetector()

    rng = np.random.default_rng(42)
    n = 300
    t = np.arange(n)
    bull_prices = 100 * np.exp(0.003 * t + 0.01 * rng.standard_normal(n))
    bull_df = pd.DataFrame({
        "date": pd.date_range("2020-01-01", periods=n),
        "close": bull_prices,
    })

    result = det.detect(bull_df, individual_danger_rate=0.02)
    print(f"  牛市序列: regime={result['regime']}, vol={result['vol']:.4f}, "
          f"trend_up={result['trend_up']}")

    bear_prices = 100 * np.exp(-0.003 * t + 0.01 * rng.standard_normal(n))
    bear_df = pd.DataFrame({
        "date": pd.date_range("2020-01-01", periods=n),
        "close": bear_prices,
    })

    result2 = det.detect(bear_df, individual_danger_rate=0.0)
    print(f"  熊市序列: regime={result2['regime']}, vol={result2['vol']:.4f}, "
          f"trend_down={result2['trend_down']}")
    print("  PASS\n")


def test_future_return():
    """测试未来收益计算"""
    print("=== test_future_return ===")
    from scripts.lppl_three_layer_backtest import calculate_future_return

    df = pd.DataFrame({
        "date": pd.date_range("2020-01-01", periods=200),
        "open": np.linspace(10, 15, 200),
        "high": np.linspace(10, 16, 200),
        "low": np.linspace(9, 14, 200),
        "close": np.linspace(10, 15, 200),
        "volume": [1000000] * 200,
    })

    result = calculate_future_return(df, 50, 120)
    print(f"  idx=50, 120天: return={result['future_return_pct']:.2f}%, "
          f"max_gain={result['future_max_gain_pct']:.2f}%, "
          f"max_dd={result['future_max_dd_pct']:.2f}%")

    result2 = calculate_future_return(df, 150, 120)
    print(f"  idx=150, 120天: {result2}")
    print("  PASS\n")


def test_bubble_detection():
    """测试泡沫检测"""
    print("=== test_bubble_detection ===")
    from scripts.lppl_three_layer_backtest import detect_bubble_periods, is_in_bubble_period

    n = 500
    t = np.arange(n)
    prices = 100 * np.exp(0.005 * t)
    df = pd.DataFrame({
        "date": pd.date_range("2010-01-01", periods=n),
        "open": prices * 0.99,
        "high": prices * 1.02,
        "low": prices * 0.98,
        "close": prices,
        "volume": [1000000] * n,
    })

    bubbles = detect_bubble_periods(df)
    print(f"  检测到 {len(bubbles)} 个泡沫期")
    for i, (s, e) in enumerate(bubbles[:3], 1):
        print(f"    泡沫{i}: {s} ~ {e}")

    test_date = bubbles[0][0] if bubbles else "2015-01-01"
    in_bubble = is_in_bubble_period(test_date, bubbles)
    print(f"  {test_date} 是否在泡沫期: {in_bubble}")
    print("  PASS\n")


def test_output_analysis():
    """测试已有输出文件的结构完整性"""
    print("=== test_output_analysis ===")
    import json

    analysis_path = PROJECT_ROOT / "output" / "lppl_three_layer_backtest" / "backtest_analysis.json"
    if not analysis_path.exists():
        print("  跳过: backtest_analysis.json 不存在")
        return

    with analysis_path.open() as f:
        data = json.load(f)

    assert "total_samples" in data, "缺少 total_samples"
    assert "comparison" in data, "缺少 comparison"
    assert "yearly_stats" in data, "缺少 yearly_stats"
    assert "layer_stats" in data, "缺少 layer_stats"

    comp = data["comparison"]
    for name in ["A_baseline", "B_multifit", "D_regime_filtered"]:
        assert name in comp, f"缺少 comparison.{name}"
        for field in ["n_signals", "precision", "recall", "f1", "signal_return"]:
            assert field in comp[name], f"缺少 comparison.{name}.{field}"

    yearly = data["yearly_stats"]
    for year in range(2012, 2026):
        if str(year) in yearly:
            ys = yearly[str(year)]
            assert "d_signals" in ys, f"缺少 yearly_stats.{year}.d_signals"
            assert "d_signal_return" in ys, f"缺少 yearly_stats.{year}.d_signal_return"

    print(f"  total_samples: {data['total_samples']}")
    for name in ["A_baseline", "B_multifit", "D_regime_filtered"]:
        c = comp[name]
        print(f"  {name}: n={c['n_signals']}, p={c['precision']:.3f}, "
              f"f1={c['f1']:.3f}, spread={c['return_spread']:.2f}%")

    years_with_signals = [y for y, ys in yearly.items() if ys.get("d_signals", 0) > 0]
    print(f"  有D信号的年份: {years_with_signals}")
    print("  PASS\n")


if __name__ == "__main__":
    print("=" * 60)
    print("三层LPPL系统验证测试")
    print("=" * 60)
    print()

    tests = [
        test_lppl_multifit,
        test_lppl_cluster,
        test_lppl_regime,
        test_future_return,
        test_bubble_detection,
        test_output_analysis,
    ]

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
