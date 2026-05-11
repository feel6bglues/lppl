#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
三层LPPL系统回测结果深度分析

在 backtest 完成后运行，对 raw_results.jsonl 进行深度统计分析
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def load_results(output_dir: Path) -> pd.DataFrame:
    jsonl_path = output_dir / "backtest_raw_results.jsonl"
    records = []
    with jsonl_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return pd.DataFrame(records)


def threshold_sensitivity_analysis(df: pd.DataFrame) -> Dict:
    """阈值敏感性分析: 不同阈值下的F1变化"""
    results = {}
    for col, label in [
        ("baseline_score", "A_baseline"),
        ("multifit_score", "B_multifit"),
        ("final_score", "D_regime_filtered"),
    ]:
        thresholds = [0.3, 0.4, 0.5, 0.6, 0.7, 0.8]
        threshold_results = {}
        for t in thresholds:
            signals = df[df[col] >= t]
            non_signals = df[df[col] < t]
            actual_declines = df[df["future_return_pct"] < 0]

            n_sig = len(signals)
            if n_sig == 0:
                threshold_results[t] = {"precision": 0, "recall": 0, "f1": 0, "n_signals": 0}
                continue

            precision = len(signals[signals["future_return_pct"] < 0]) / n_sig
            recall = len(signals[signals["future_return_pct"] < 0]) / len(actual_declines) if len(actual_declines) > 0 else 0
            f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0

            threshold_results[t] = {
                "precision": round(precision, 4),
                "recall": round(recall, 4),
                "f1": round(f1, 4),
                "n_signals": n_sig,
                "signal_rate": round(n_sig / len(df), 4),
            }
        results[label] = threshold_results
    return results


def parameter_distribution_analysis(df: pd.DataFrame) -> Dict:
    """LPPL参数分布分析"""
    layers = {}
    for layer in ["short", "medium", "long"]:
        m_col = f"layer_{layer}_m"
        r2_col = f"layer_{layer}_r2"
        danger_col = f"layer_{layer}_danger"

        if m_col not in df.columns:
            continue

        m_vals = df[m_col][df[m_col] > 0]
        r2_vals = df[r2_col][df[r2_col] > 0]

        layers[layer] = {
            "m_mean": round(float(m_vals.mean()), 4) if len(m_vals) > 0 else None,
            "m_std": round(float(m_vals.std()), 4) if len(m_vals) > 0 else None,
            "m_median": round(float(m_vals.median()), 4) if len(m_vals) > 0 else None,
            "m_p10": round(float(m_vals.quantile(0.1)), 4) if len(m_vals) > 0 else None,
            "m_p90": round(float(m_vals.quantile(0.9)), 4) if len(m_vals) > 0 else None,
            "r2_mean": round(float(r2_vals.mean()), 4) if len(r2_vals) > 0 else None,
            "r2_std": round(float(r2_vals.std()), 4) if len(r2_vals) > 0 else None,
            "r2_gt_05_pct": round(float((r2_vals > 0.5).sum() / len(r2_vals) * 100), 1) if len(r2_vals) > 0 else None,
            "r2_gt_07_pct": round(float((r2_vals > 0.7).sum() / len(r2_vals) * 100), 1) if len(r2_vals) > 0 else None,
            "danger_count": int(df[danger_col].sum()),
            "danger_pct": round(float(df[danger_col].sum() / len(df) * 100), 2) if len(df) > 0 else 0,
            "total_valid": int(len(m_vals)),
        }
    return layers


def cross_layer_consistency_analysis(df: pd.DataFrame) -> Dict:
    """跨层一致性分析: 多层同时danger时的表现"""
    results = {}

    for n_layers in [0, 1, 2, 3]:
        if n_layers == 0:
            mask = (df["layer_short_danger"] == False) & (df["layer_medium_danger"] == False) & (df["layer_long_danger"] == False)
            label = "0层danger"
        elif n_layers == 1:
            mask = ((df["layer_short_danger"] == True).astype(int) + (df["layer_medium_danger"] == True).astype(int) + (df["layer_long_danger"] == True).astype(int)) == 1
            label = "1层danger"
        elif n_layers == 2:
            mask = ((df["layer_short_danger"] == True).astype(int) + (df["layer_medium_danger"] == True).astype(int) + (df["layer_long_danger"] == True).astype(int)) == 2
            label = "2层danger"
        else:
            mask = (df["layer_short_danger"] == True) & (df["layer_medium_danger"] == True) & (df["layer_long_danger"] == True)
            label = "3层danger"

        subset = df[mask]
        if len(subset) == 0:
            results[label] = {"count": 0}
            continue

        results[label] = {
            "count": len(subset),
            "avg_return": round(float(subset["future_return_pct"].mean()), 2),
            "median_return": round(float(subset["future_return_pct"].median()), 2),
            "win_rate": round(float((subset["future_return_pct"] > 0).sum() / len(subset) * 100), 1),
            "avg_max_gain": round(float(subset["future_max_gain_pct"].mean()), 2),
            "avg_max_dd": round(float(subset["future_max_dd_pct"].mean()), 2),
            "precision": round(float((subset["future_return_pct"] < 0).sum() / len(subset)), 4),
        }
    return results


def m_value_return_correlation(df: pd.DataFrame) -> Dict:
    """m参数与收益率的相关性分析"""
    results = {}
    for layer in ["short", "medium", "long"]:
        m_col = f"layer_{layer}_m"
        if m_col not in df.columns:
            continue
        valid = df[(df[m_col] > 0) & (df[m_col] < 1.0)]
        if len(valid) < 10:
            results[layer] = {"correlation": None, "n": len(valid)}
            continue
        corr = valid[m_col].corr(valid["future_return_pct"])
        results[layer] = {
            "correlation": round(float(corr), 4),
            "n": len(valid),
            "m_low_return": round(float(valid[valid[m_col] < valid[m_col].median()]["future_return_pct"].mean()), 2),
            "m_high_return": round(float(valid[valid[m_col] >= valid[m_col].median()]["future_return_pct"].mean()), 2),
        }
    return results


def optimal_holding_period_analysis(df: pd.DataFrame) -> Dict:
    """按regime分组的收益分布"""
    results = {}
    for regime in ["strong_bull", "weak_bull", "range", "weak_bear", "strong_bear", "unknown"]:
        subset = df[df["regime"] == regime]
        if len(subset) == 0:
            results[regime] = {"count": 0}
            continue
        results[regime] = {
            "count": len(subset),
            "avg_return": round(float(subset["future_return_pct"].mean()), 2),
            "median_return": round(float(subset["future_return_pct"].median()), 2),
            "win_rate": round(float((subset["future_return_pct"] > 0).sum() / len(subset) * 100), 1),
            "return_std": round(float(subset["future_return_pct"].std()), 2),
            "return_p25": round(float(subset["future_return_pct"].quantile(0.25)), 2),
            "return_p75": round(float(subset["future_return_pct"].quantile(0.75)), 2),
        }
    return results


def train_test_split_analysis(df: pd.DataFrame, train_end_year: int = 2021) -> Dict:
    """训练/测试分割验证: 防止过拟合"""
    train = df[df["cycle_year"] <= train_end_year]
    test = df[df["cycle_year"] > train_end_year]

    def _calc_stats(subset):
        if len(subset) == 0:
            return {"n": 0}
        signals = subset[subset["final_score"] >= 0.3]
        n_sig = len(signals)
        precision = len(signals[signals["future_return_pct"] < 0]) / n_sig if n_sig > 0 else 0
        sig_ret = float(signals["future_return_pct"].mean()) if n_sig > 0 else 0
        return {
            "n": len(subset),
            "n_signals": n_sig,
            "signal_rate": round(n_sig / len(subset), 4) if len(subset) > 0 else 0,
            "precision": round(precision, 4),
            "avg_return": round(float(subset["future_return_pct"].mean()), 2),
            "signal_return": round(sig_ret, 2),
        }

    return {
        "train": _calc_stats(train),
        "test": _calc_stats(test),
        "train_end_year": train_end_year,
    }


def main():
    output_dir = PROJECT_ROOT / "output" / "lppl_three_layer_backtest"

    print("=" * 60)
    print("三层LPPL系统回测深度分析")
    print("=" * 60)

    print("\n1. 加载数据...")
    df = load_results(output_dir)
    print(f"   {len(df)} 条记录")

    print("\n2. 阈值敏感性分析...")
    threshold_analysis = threshold_sensitivity_analysis(df)

    print("\n3. 参数分布分析...")
    param_analysis = parameter_distribution_analysis(df)

    print("\n4. 跨层一致性分析...")
    consistency_analysis = cross_layer_consistency_analysis(df)

    print("\n5. m参数与收益相关性...")
    m_correlation = m_value_return_correlation(df)

    print("\n6. Regime分组收益分布...")
    regime_return = optimal_holding_period_analysis(df)

    print("\n7. 训练/测试分割验证...")
    train_test = train_test_split_analysis(df)

    full_analysis = {
        "total_samples": len(df),
        "threshold_sensitivity": threshold_analysis,
        "parameter_distribution": param_analysis,
        "cross_layer_consistency": consistency_analysis,
        "m_value_correlation": m_correlation,
        "cluster_return_distribution": regime_return,
        "train_test_split": train_test,
    }

    analysis_path = output_dir / "deep_analysis.json"
    with analysis_path.open("w", encoding="utf-8") as f:
        json.dump(full_analysis, f, ensure_ascii=False, indent=2)

    print(f"\n深度分析结果已保存: {analysis_path}")

    print("\n" + "=" * 60)
    print("关键发现:")
    print()

    for label, data in threshold_analysis.items():
        if not data:
            continue
        best_threshold = max(data.keys(), key=lambda t: data[t].get("f1", 0))
        best_f1 = data[best_threshold]["f1"]
        best_n = data[best_threshold]["n_signals"]
        print(f"  {label}: 最优阈值={best_threshold}, F1={best_f1:.3f}, n={best_n}")

    print()
    for n_layers, data in consistency_analysis.items():
        if data.get("count", 0) == 0:
            continue
        print(f"  {n_layers}: n={data['count']}, 收益={data.get('avg_return', 'N/A')}%, "
              f"胜率={data.get('win_rate', 'N/A')}%, 精确率={data.get('precision', 'N/A')}")

    print()
    print(f"  训练集(<=2021): n={train_test['train']['n']}, signals={train_test['train'].get('n_signals', 0)}, "
          f"precision={train_test['train'].get('precision', 0):.4f}")
    print(f"  测试集(>2021):  n={train_test['test']['n']}, signals={train_test['test'].get('n_signals', 0)}, "
          f"precision={train_test['test'].get('precision', 0):.4f}")
    if train_test['test'].get('n', 0) > 0:
        print(f"  样本外信号收益: {train_test['test'].get('signal_return', 'N/A')}%")
    print("=" * 60)


if __name__ == "__main__":
    main()
