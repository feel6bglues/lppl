#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
按指数分组优化 MA20/250 + ATR + 波动率缩放。

目标：
1. 以 MA20/250 作为固定主组合
2. 按大盘组 / 平衡组 / 高弹性组分别搜索小网格
3. 对比基线（关闭波动率缩放）与候选（开启波动率缩放）
4. 输出适合写回 YAML 的候选参数
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from typing import Any, Dict, List

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ma_cross_atr_optimization import run_single_backtest

OUTPUT_DIR = "output/grouped_ma_atr_optimization"
START_DATE = "2020-01-01"
END_DATE = "2026-03-27"
FAST_MA = 20
SLOW_MA = 250


@dataclass(frozen=True)
class SymbolGroup:
    name: str
    symbols: tuple[str, ...]
    drawdown_cap: float
    target_vol_grid: tuple[float, ...]


GROUPS: tuple[SymbolGroup, ...] = (
    SymbolGroup(
        name="large_cap",
        symbols=("000001.SH", "000016.SH", "000300.SH"),
        drawdown_cap=-0.35,
        target_vol_grid=(0.12, 0.15),
    ),
    SymbolGroup(
        name="balanced",
        symbols=("399001.SZ", "000905.SH"),
        drawdown_cap=-0.35,
        target_vol_grid=(0.15, 0.18),
    ),
    SymbolGroup(
        name="high_beta",
        symbols=("399006.SZ", "000852.SH", "932000.SH"),
        drawdown_cap=-0.40,
        target_vol_grid=(0.18, 0.20),
    ),
)

ATR_GRID: tuple[Dict[str, float], ...] = (
    {"atr_period": 14, "atr_ma_window": 20, "buy_volatility_cap": 1.00, "vol_breakout_mult": 1.15},
    {"atr_period": 14, "atr_ma_window": 20, "buy_volatility_cap": 1.05, "vol_breakout_mult": 1.15},
    {"atr_period": 14, "atr_ma_window": 60, "buy_volatility_cap": 1.00, "vol_breakout_mult": 1.05},
    {"atr_period": 14, "atr_ma_window": 60, "buy_volatility_cap": 1.05, "vol_breakout_mult": 1.05},
    {"atr_period": 20, "atr_ma_window": 40, "buy_volatility_cap": 1.00, "vol_breakout_mult": 1.05},
    {"atr_period": 20, "atr_ma_window": 40, "buy_volatility_cap": 1.05, "vol_breakout_mult": 1.05},
)


def build_group_candidates(group: SymbolGroup) -> List[Dict[str, Any]]:
    candidates: List[Dict[str, Any]] = []

    for atr_cfg in ATR_GRID:
        candidates.append(
            {
                "enable_volatility_scaling": False,
                "target_volatility": 0.15,
                **atr_cfg,
            }
        )
        for target_volatility in group.target_vol_grid:
            candidates.append(
                {
                    "enable_volatility_scaling": True,
                    "target_volatility": target_volatility,
                    **atr_cfg,
                }
            )

    return candidates


def is_group_eligible(summary: Dict[str, Any], drawdown_cap: float) -> bool:
    return (
        float(summary.get("annualized_excess_return", 0.0)) > 0.0
        and float(summary.get("max_drawdown", 0.0)) > drawdown_cap
        and int(summary.get("trade_count", 0)) >= 3
        and float(summary.get("turnover_rate", 0.0)) < 8.0
        and float(summary.get("whipsaw_rate", 0.0)) <= 0.35
    )


def _candidate_key(candidate: Dict[str, Any]) -> str:
    scaling = "vol_on" if candidate["enable_volatility_scaling"] else "vol_off"
    return (
        f"{scaling}|tv={candidate['target_volatility']:.2f}|"
        f"atr={candidate['atr_period']}/{candidate['atr_ma_window']}|"
        f"buy={candidate['buy_volatility_cap']:.2f}|sell={candidate['vol_breakout_mult']:.2f}"
    )


def run_group_optimization(group: SymbolGroup) -> pd.DataFrame:
    rows: List[Dict[str, Any]] = []
    candidates = build_group_candidates(group)

    for candidate in candidates:
        candidate_key = _candidate_key(candidate)
        failed_symbols: List[str] = []
        symbol_rows: List[Dict[str, Any]] = []

        for symbol in group.symbols:
            result = run_single_backtest(
                symbol=symbol,
                fast_ma=FAST_MA,
                slow_ma=SLOW_MA,
                atr_period=int(candidate["atr_period"]),
                atr_ma_window=int(candidate["atr_ma_window"]),
                buy_volatility_cap=float(candidate["buy_volatility_cap"]),
                vol_breakout_mult=float(candidate["vol_breakout_mult"]),
                enable_volatility_scaling=bool(candidate["enable_volatility_scaling"]),
                target_volatility=float(candidate["target_volatility"]),
                start_date=START_DATE,
                end_date=END_DATE,
            )
            if result is None:
                failed_symbols.append(symbol)
                continue

            result["group"] = group.name
            result["candidate_key"] = candidate_key
            result["group_eligible"] = is_group_eligible(result, group.drawdown_cap)
            symbol_rows.append(result)

        if failed_symbols or len(symbol_rows) != len(group.symbols):
            continue

        rows.extend(symbol_rows)

    return pd.DataFrame(rows)


def summarize_group_results(group_df: pd.DataFrame) -> pd.DataFrame:
    if group_df.empty:
        return pd.DataFrame()

    summary = (
        group_df.groupby(
            [
                "group",
                "candidate_key",
                "enable_volatility_scaling",
                "target_volatility",
                "atr_period",
                "atr_ma_window",
                "buy_volatility_cap",
                "vol_breakout_mult",
            ],
            as_index=False,
        )
        .agg(
            group_eligible=("group_eligible", "sum"),
            avg_excess=("annualized_excess_return", "mean"),
            avg_drawdown=("max_drawdown", "mean"),
            avg_trades=("trade_count", "mean"),
            avg_turnover=("turnover_rate", "mean"),
            avg_whipsaw=("whipsaw_rate", "mean"),
        )
        .sort_values(
            ["group_eligible", "avg_excess", "avg_drawdown"],
            ascending=[False, False, False],
        )
        .reset_index(drop=True)
    )
    return summary


def generate_yaml_suggestions(summary_df: pd.DataFrame) -> List[str]:
    lines = ["symbols:"]
    if summary_df.empty:
        return lines

    best_per_group = summary_df.groupby("group", as_index=False).first()
    symbol_map = {group.name: group.symbols for group in GROUPS}

    for _, row in best_per_group.iterrows():
        for symbol in symbol_map[row["group"]]:
            lines.append(f'  "{symbol}":')
            lines.append("    signal_model: ma_cross_atr_v1")
            lines.append(f"    trend_fast_ma: {FAST_MA}")
            lines.append(f"    trend_slow_ma: {SLOW_MA}")
            lines.append(f"    atr_period: {int(row['atr_period'])}")
            lines.append(f"    atr_ma_window: {int(row['atr_ma_window'])}")
            lines.append(f"    buy_volatility_cap: {float(row['buy_volatility_cap']):.2f}")
            lines.append(f"    vol_breakout_mult: {float(row['vol_breakout_mult']):.2f}")
            lines.append(
                f"    enable_volatility_scaling: {'true' if bool(row['enable_volatility_scaling']) else 'false'}"
            )
            if bool(row["enable_volatility_scaling"]):
                lines.append(f"    target_volatility: {float(row['target_volatility']):.2f}")
    return lines


def save_outputs(group_results: pd.DataFrame, summary_df: pd.DataFrame) -> None:
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    raw_path = os.path.join(OUTPUT_DIR, "group_results.csv")
    summary_path = os.path.join(OUTPUT_DIR, "group_summary.csv")
    yaml_path = os.path.join(OUTPUT_DIR, "yaml_suggestions.yaml")

    group_results.to_csv(raw_path, index=False)
    summary_df.to_csv(summary_path, index=False)
    with open(yaml_path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(generate_yaml_suggestions(summary_df)))

    print(f"详细结果已保存: {raw_path}")
    print(f"汇总结果已保存: {summary_path}")
    print(f"YAML 建议已保存: {yaml_path}")


def print_top_results(summary_df: pd.DataFrame) -> None:
    if summary_df.empty:
        print("无可用结果")
        return

    for group_name, group_slice in summary_df.groupby("group"):
        print(f"\n=== {group_name} ===")
        top_rows = group_slice.head(5)
        for _, row in top_rows.iterrows():
            scaling = "on" if bool(row["enable_volatility_scaling"]) else "off"
            print(
                f"{scaling} tv={float(row['target_volatility']):.2f} "
                f"ATR{int(row['atr_period'])}/{int(row['atr_ma_window'])} "
                f"buy={float(row['buy_volatility_cap']):.2f} sell={float(row['vol_breakout_mult']):.2f} "
                f"eligible={int(row['group_eligible'])} "
                f"avg_excess={float(row['avg_excess']):.2%} "
                f"avg_dd={float(row['avg_drawdown']):.2%} "
                f"avg_trades={float(row['avg_trades']):.1f}"
            )


def main() -> None:
    all_rows: List[pd.DataFrame] = []
    for group in GROUPS:
        group_df = run_group_optimization(group)
        all_rows.append(group_df)

    combined = pd.concat(all_rows, ignore_index=True) if all_rows else pd.DataFrame()
    summary_df = summarize_group_results(combined)
    print_top_results(summary_df)
    save_outputs(combined, summary_df)


if __name__ == "__main__":
    main()
