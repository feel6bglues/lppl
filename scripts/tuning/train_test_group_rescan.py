#!/usr/bin/env python3
# RESEARCH ONLY — not production code
# -*- coding: utf-8 -*-
"""
训练集/测试集分离的分组 MA 重扫脚本

用法:
    python scripts/train_test_group_rescan.py --mode train --group large_cap
    python scripts/train_test_group_rescan.py --mode test --group large_cap
    python scripts/train_test_group_rescan.py --mode all
    python scripts/train_test_group_rescan.py --mode all --group balanced

训练集: 2012-01-01 ~ 2019-12-31
测试集: 2020-01-01 ~ 2026-01-01
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import argparse
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import pandas as pd

from src.data.manager import DataManager
from src.investment.backtest import (
    BacktestConfig,
    InvestmentSignalConfig,
    generate_investment_signals,
    run_strategy_backtest,
    summarize_strategy_performance,
)
from src.investment.group_rescan import (
    BALANCED_SYMBOLS,
    HIGH_BETA_SYMBOLS,
    LARGE_CAP_SYMBOLS,
    LARGE_CAP_YAML_PARAMS,
    GroupRescanPlan,
    candidate_key,
)
from src.investment.tuning import score_signal_tuning_results

TRAIN_START = "2012-01-01"
TRAIN_END = "2019-12-31"
TEST_START = "2020-01-01"
TEST_END = "2026-01-01"


def make_plans() -> Dict[str, Tuple[GroupRescanPlan, Optional[Dict[str, Any]]]]:
    return {
        "large_cap": (
            GroupRescanPlan(
                name="large_cap",
                symbols=LARGE_CAP_SYMBOLS,
                ma_combos=((20, 250), (30, 250), (20, 120)),
                atr_periods=(14,),
                atr_ma_windows=(20, 40),
                buy_volatility_caps=(1.00, 1.05),
                vol_breakout_mults=(1.05, 1.15),
                enable_volatility_scaling_options=(False, True),
                target_volatilities=(0.12, 0.15),
                min_trade_count=3,
                max_drawdown_cap=-0.35,
                turnover_cap=10.0,
                whipsaw_cap=0.35,
                scoring_profile="balanced",
                objective_note="大盘组：寻找 3/3 eligible 的 MA 组合",
                output_dir="output/train_test_rescan_large_cap",
                pass_threshold=3,
            ),
            LARGE_CAP_YAML_PARAMS,
        ),
        "balanced": (
            GroupRescanPlan(
                name="balanced",
                symbols=BALANCED_SYMBOLS,
                ma_combos=((10, 120), (20, 120), (5, 120), (10, 250), (20, 250)),
                atr_periods=(14,),
                atr_ma_windows=(20, 40, 60),
                buy_volatility_caps=(1.00, 1.05),
                vol_breakout_mults=(1.05, 1.10, 1.15),
                enable_volatility_scaling_options=(False, True),
                target_volatilities=(0.15, 0.18),
                min_trade_count=3,
                max_drawdown_cap=-0.35,
                turnover_cap=10.0,
                whipsaw_cap=0.35,
                scoring_profile="balanced",
                objective_note="平衡组：寻找 2/2 eligible 的 MA 组合",
                output_dir="output/train_test_rescan_balanced",
                pass_threshold=2,
            ),
            None,
        ),
        "high_beta": (
            GroupRescanPlan(
                name="high_beta",
                symbols=HIGH_BETA_SYMBOLS,
                ma_combos=((20, 120), (10, 120), (5, 120), (20, 250), (30, 250)),
                atr_periods=(14, 20),
                atr_ma_windows=(20, 40, 60),
                buy_volatility_caps=(1.00, 1.05),
                vol_breakout_mults=(1.05, 1.10, 1.15),
                enable_volatility_scaling_options=(False, True),
                target_volatilities=(0.18, 0.20),
                min_trade_count=3,
                max_drawdown_cap=-0.40,
                turnover_cap=10.0,
                whipsaw_cap=0.35,
                scoring_profile="high_beta_recovery",
                objective_note="高弹性组：寻找正超额，若无法转正则保留回撤收敛的组合",
                output_dir="output/train_test_rescan_high_beta",
                pass_threshold=1,
            ),
            None,
        ),
    }


def _single_backtest(
    symbol: str,
    data_mgr: DataManager,
    start_date: str,
    end_date: str,
    signal_kwargs: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    df = data_mgr.get_data(symbol)
    if df is None or df.empty:
        return None

    sig_cfg = InvestmentSignalConfig(**{
        k: v for k, v in signal_kwargs.items()
        if k in InvestmentSignalConfig.__dataclass_fields__
    })

    signal_df = generate_investment_signals(
        df, symbol,
        signal_config=sig_cfg,
        use_ensemble=False,
        start_date=start_date,
        end_date=end_date,
    )
    if signal_df is None or signal_df.empty:
        return None

    bt_cfg = BacktestConfig(start_date=start_date, end_date=end_date)
    equity_df, trades_df, _ = run_strategy_backtest(signal_df, bt_cfg)
    if equity_df.empty:
        return None

    perf = summarize_strategy_performance(equity_df, trades_df)
    perf["symbol"] = symbol
    return perf


def run_train_scan(group_name: str) -> Tuple[pd.DataFrame, pd.DataFrame]:
    plans = make_plans()
    plan, _ = plans[group_name]
    data_mgr = DataManager()

    combos = []
    for fast_ma, slow_ma in plan.ma_combos:
        for atr_period in plan.atr_periods:
            for atr_ma_window in plan.atr_ma_windows:
                for buy_cap in plan.buy_volatility_caps:
                    for sell_mult in plan.vol_breakout_mults:
                        for vol_scale in plan.enable_volatility_scaling_options:
                            for target_vol in plan.target_volatilities:
                                combos.append({
                                    "fast_ma": fast_ma,
                                    "slow_ma": slow_ma,
                                    "atr_period": atr_period,
                                    "atr_ma_window": atr_ma_window,
                                    "buy_volatility_cap": buy_cap,
                                    "vol_breakout_mult": sell_mult,
                                    "enable_volatility_scaling": vol_scale,
                                    "target_volatility": target_vol,
                                })

    total = len(combos) * len(plan.symbols)
    done = 0
    rows = []

    print(f"[TRAIN] {group_name}: {len(plan.symbols)} indices x {len(combos)} combos = {total} runs")

    for ci, candidate in enumerate(combos):
        key = candidate_key(candidate)
        sig_kwargs = {
            "signal_model": "ma_cross_atr_v1",
            "trend_fast_ma": candidate["fast_ma"],
            "trend_slow_ma": candidate["slow_ma"],
            "atr_period": candidate["atr_period"],
            "atr_ma_window": candidate["atr_ma_window"],
            "buy_volatility_cap": candidate["buy_volatility_cap"],
            "vol_breakout_mult": candidate["vol_breakout_mult"],
            "enable_volatility_scaling": candidate["enable_volatility_scaling"],
            "target_volatility": candidate["target_volatility"],
        }

        for symbol in plan.symbols:
            done += 1
            if done % 20 == 0:
                print(f"  Progress: {done}/{total} ({done/total:.0%})")

            result = _single_backtest(symbol, data_mgr, TRAIN_START, TRAIN_END, sig_kwargs)
            if result is None:
                continue
            result["group"] = plan.name
            result["candidate_key"] = key
            for k, v in candidate.items():
                result[k] = v
            rows.append(result)

    raw_df = pd.DataFrame(rows)
    if raw_df.empty:
        return raw_df, pd.DataFrame()

    # Compute eligible per-row before aggregation
    raw_df["eligible"] = (
        (raw_df["annualized_excess_return"] > 0.0)
        & (raw_df["max_drawdown"] > plan.max_drawdown_cap)
        & (raw_df["trade_count"] >= plan.min_trade_count)
        & (raw_df["turnover_rate"] < plan.turnover_cap)
        & (raw_df["whipsaw_rate"] <= plan.whipsaw_cap)
    )

    summary_df = (
        raw_df.groupby(
            ["group", "candidate_key", "fast_ma", "slow_ma", "atr_period",
             "atr_ma_window", "buy_volatility_cap", "vol_breakout_mult",
             "enable_volatility_scaling", "target_volatility"],
            as_index=False,
        )
        .agg(
            eligible_count=("eligible", "sum"),
            symbol_count=("symbol", "nunique"),
            avg_excess=("annualized_excess_return", "mean"),
            avg_drawdown=("max_drawdown", "mean"),
            avg_trade_count=("trade_count", "mean"),
            avg_turnover=("turnover_rate", "mean"),
            avg_whipsaw=("whipsaw_rate", "mean"),
            avg_calmar_ratio=("calmar_ratio", "mean"),
            min_excess=("annualized_excess_return", "min"),
            max_drawdown_worst=("max_drawdown", "min"),
            min_trade_count=("trade_count", "min"),
        )
        .reset_index(drop=True)
    )

    scored = score_signal_tuning_results(
        summary_df.rename(columns={
            "avg_excess": "annualized_excess_return",
            "avg_drawdown": "max_drawdown",
            "avg_trade_count": "trade_count",
            "avg_turnover": "turnover_rate",
            "avg_whipsaw": "whipsaw_rate",
            "avg_calmar_ratio": "calmar_ratio",
        }),
        min_trade_count=plan.min_trade_count,
        max_drawdown_cap=plan.max_drawdown_cap,
        turnover_cap=plan.turnover_cap,
        whipsaw_cap=plan.whipsaw_cap,
        scoring_profile=plan.scoring_profile,
        hard_reject=False,
    )

    if "min_excess" in scored.columns:
        negative_min_penalty = scored["min_excess"].clip(upper=0).abs() * 0.01
        scored["objective_score"] = scored["objective_score"] - negative_min_penalty

    scored.loc[scored["eligible_count"] == 0, "objective_score"] = scored.loc[
        scored["eligible_count"] == 0, "objective_score"
    ].clip(upper=-0.01)

    scored["group_pass"] = scored["eligible_count"] >= plan.pass_threshold
    summary_df = scored.sort_values(
        ["group_pass", "eligible_count", "objective_score", "annualized_excess_return", "max_drawdown"],
        ascending=[False, False, False, False, False],
    ).reset_index(drop=True)

    return raw_df, summary_df


def run_test_validation(group_name: str, train_summary_df: pd.DataFrame) -> pd.DataFrame:
    plans = make_plans()
    plan, _ = plans[group_name]
    data_mgr = DataManager()

    top_candidates = train_summary_df.head(5)
    if top_candidates.empty:
        print(f"[TEST] No train candidates for {group_name}")
        return pd.DataFrame()

    print(f"[TEST] {group_name}: validating {len(top_candidates)} candidates")

    rows = []
    for _, candidate in top_candidates.iterrows():
        sig_kwargs = {
            "signal_model": "ma_cross_atr_v1",
            "trend_fast_ma": int(candidate["fast_ma"]),
            "trend_slow_ma": int(candidate["slow_ma"]),
            "atr_period": int(candidate["atr_period"]),
            "atr_ma_window": int(candidate["atr_ma_window"]),
            "buy_volatility_cap": float(candidate["buy_volatility_cap"]),
            "vol_breakout_mult": float(candidate["vol_breakout_mult"]),
            "enable_volatility_scaling": bool(candidate["enable_volatility_scaling"]),
            "target_volatility": float(candidate["target_volatility"]),
        }

        for symbol in plan.symbols:
            result = _single_backtest(symbol, data_mgr, TEST_START, TEST_END, sig_kwargs)
            if result is None:
                continue
            result["group"] = plan.name
            result["candidate_key"] = candidate["candidate_key"]
            result["fast_ma"] = int(candidate["fast_ma"])
            result["slow_ma"] = int(candidate["slow_ma"])
            result["atr_period"] = int(candidate["atr_period"])
            result["atr_ma_window"] = int(candidate["atr_ma_window"])
            result["buy_volatility_cap"] = float(candidate["buy_volatility_cap"])
            result["vol_breakout_mult"] = float(candidate["vol_breakout_mult"])
            result["enable_volatility_scaling"] = bool(candidate["enable_volatility_scaling"])
            result["target_volatility"] = float(candidate["target_volatility"])
            result["train_eligible_count"] = int(candidate["eligible_count"])
            result["train_objective_score"] = float(candidate["objective_score"])
            rows.append(result)

    test_df = pd.DataFrame(rows)
    if test_df.empty:
        return test_df

    test_df["eligible"] = (
        (test_df["annualized_excess_return"] > 0.0)
        & (test_df["max_drawdown"] > plan.max_drawdown_cap)
        & (test_df["trade_count"] >= plan.min_trade_count)
        & (test_df["turnover_rate"] < plan.turnover_cap)
        & (test_df["whipsaw_rate"] <= plan.whipsaw_cap)
    )

    return test_df


def generate_comparison_report(group_name: str, train_summary: pd.DataFrame, test_raw: pd.DataFrame) -> str:
    lines = [
        f"# {group_name} Train/Test Comparison Report",
        "",
        f"- 训练集: {TRAIN_START} ~ {TRAIN_END}",
        f"- 测试集: {TEST_START} ~ {TEST_END}",
        "",
        "## Train Set Top 5",
        "",
    ]

    for _, row in train_summary.head(5).iterrows():
        lines.append(
            f"- {row['candidate_key']} "
            f"eligible={int(row['eligible_count'])}/{int(row['symbol_count'])} "
            f"excess={float(row['annualized_excess_return']):.2%} "
            f"dd={float(row['max_drawdown']):.2%} "
            f"trades={float(row['trade_count']):.1f} "
            f"score={float(row['objective_score']):.3f}"
        )

    lines.extend(["", "## Test Set Results", ""])

    if not test_raw.empty:
        test_agg = (
            test_raw.groupby(["candidate_key"], as_index=False)
            .agg(
                eligible_count=("eligible", "sum"),
                symbol_count=("symbol", "nunique"),
                avg_excess=("annualized_excess_return", "mean"),
                avg_drawdown=("max_drawdown", "mean"),
                avg_trade_count=("trade_count", "mean"),
            )
        )
        for _, row in test_agg.iterrows():
            lines.append(
                f"- {row['candidate_key']} "
                f"eligible={int(row['eligible_count'])}/{int(row['symbol_count'])} "
                f"excess={float(row['avg_excess']):.2%} "
                f"dd={float(row['avg_drawdown']):.2%} "
                f"trades={float(row['avg_trade_count']):.1f}"
            )
    else:
        lines.append("无测试集结果。")

    lines.extend(["", "## Overfitting Check", ""])
    if not test_raw.empty and not train_summary.empty:
        test_agg = (
            test_raw.groupby(["candidate_key"], as_index=False)
            .agg(avg_excess=("annualized_excess_return", "mean"))
        )
        for _, train_row in train_summary.head(3).iterrows():
            match = test_agg[test_agg["candidate_key"] == train_row["candidate_key"]]
            if not match.empty:
                test_excess = float(match.iloc[0]["avg_excess"])
                train_excess = float(train_row["annualized_excess_return"])
                diff = test_excess - train_excess
                status = "OVERFIT" if diff < -0.02 else ("ROBUST" if diff >= -0.01 else "BORDERLINE")
                lines.append(
                    f"- {train_row['candidate_key']}: train={train_excess:.2%}, test={test_excess:.2%}, diff={diff:+.2%} [{status}]"
                )

    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description="Train/Test split group rescan")
    parser.add_argument("--mode", choices=["train", "test", "all"], default="all")
    parser.add_argument("--group", choices=["large_cap", "balanced", "high_beta"], default=None,
                        help="Run only one group (default: all)")
    args = parser.parse_args()

    plans = make_plans()
    groups = [args.group] if args.group else list(plans.keys())

    for group_name in groups:
        print(f"\n{'='*60}")
        print(f"Group: {group_name}")
        print(f"{'='*60}")

        train_summary = pd.DataFrame()

        if args.mode in ("train", "all"):
            train_raw, train_summary = run_train_scan(group_name)
            output_dir = Path(plans[group_name][0].output_dir)
            output_dir.mkdir(parents=True, exist_ok=True)
            if not train_raw.empty:
                train_raw.to_csv(output_dir / "train_raw_results.csv", index=False)
            if not train_summary.empty:
                train_summary.to_csv(output_dir / "train_summary.csv", index=False)
                print("\n[TRAIN] Top 3:")
                for _, row in train_summary.head(3).iterrows():
                    print(f"  {row['candidate_key']} -> eligible={int(row['eligible_count'])}/{int(row['symbol_count'])}, "
                          f"excess={float(row['annualized_excess_return']):.2%}, "
                          f"dd={float(row['max_drawdown']):.2%}")

        if args.mode in ("test", "all"):
            if train_summary.empty:
                train_summary_path = Path(plans[group_name][0].output_dir) / "train_summary.csv"
                if train_summary_path.exists():
                    train_summary = pd.read_csv(train_summary_path)
                else:
                    print(f"[TEST] No train summary found, skipping test for {group_name}")
                    continue

            test_raw = run_test_validation(group_name, train_summary)
            if not test_raw.empty:
                output_dir = Path(plans[group_name][0].output_dir)
                output_dir.mkdir(parents=True, exist_ok=True)
                test_raw.to_csv(output_dir / "test_raw_results.csv", index=False)

            report = generate_comparison_report(group_name, train_summary, test_raw)
            output_dir = Path(plans[group_name][0].output_dir)
            output_dir.mkdir(parents=True, exist_ok=True)
            report_path = output_dir / "train_test_comparison.md"
            report_path.write_text(report, encoding="utf-8")
            print(f"\n[REPORT] Saved to {report_path}")

    print(f"\n{'='*60}")
    print("All groups completed")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
