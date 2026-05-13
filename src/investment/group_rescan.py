# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List

import pandas as pd

from src.investment.tuning import score_signal_tuning_results

LARGE_CAP_SYMBOLS: tuple[str, ...] = ("000001.SH", "000016.SH", "000300.SH")
LARGE_CAP_YAML_PARAMS: Dict[str, Any] = {
    "signal_model": "ma_cross_atr_v1",
    "trend_fast_ma": 20,
    "trend_slow_ma": 250,
    "atr_period": 14,
    "atr_ma_window": 20,
    "buy_volatility_cap": 1.05,
    "vol_breakout_mult": 1.15,
    "enable_volatility_scaling": True,
    "target_volatility": 0.12,
}
BALANCED_SYMBOLS: tuple[str, ...] = ("399001.SZ", "000905.SH")
HIGH_BETA_SYMBOLS: tuple[str, ...] = ("399006.SZ", "000852.SH", "932000.SH")


@dataclass(frozen=True)
class GroupRescanPlan:
    name: str
    symbols: tuple[str, ...]
    ma_combos: tuple[tuple[int, int], ...]
    atr_periods: tuple[int, ...]
    atr_ma_windows: tuple[int, ...]
    buy_volatility_caps: tuple[float, ...]
    vol_breakout_mults: tuple[float, ...]
    enable_volatility_scaling_options: tuple[bool, ...]
    target_volatilities: tuple[float, ...]
    min_trade_count: int
    max_drawdown_cap: float
    turnover_cap: float
    whipsaw_cap: float
    scoring_profile: str
    objective_note: str
    output_dir: str
    pass_threshold: int


BALANCED_PLAN = GroupRescanPlan(
    name="balanced",
    symbols=("399001.SZ", "000905.SH"),
    ma_combos=((20, 120), (30, 120), (30, 250), (10, 120), (5, 250)),
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
    objective_note="优先寻找 annualized_excess_return > 0，且回撤不超过 -35% 的 MA 主组合。",
    output_dir="output/grouped_ma_rescan_balanced",
    pass_threshold=1,
)

HIGH_BETA_PLAN = GroupRescanPlan(
    name="high_beta",
    symbols=("399006.SZ", "000852.SH", "932000.SH"),
    ma_combos=((5, 250), (10, 250), (20, 120), (5, 120), (30, 250)),
    atr_periods=(14, 20),
    atr_ma_windows=(20, 40, 60),
    buy_volatility_caps=(1.00, 1.05),
    vol_breakout_mults=(1.05, 1.10, 1.15),
    enable_volatility_scaling_options=(False, True),
    target_volatilities=(0.18, 0.20),
    min_trade_count=3,
    max_drawdown_cap=-0.40,
    turnover_cap=8.0,
    whipsaw_cap=0.35,
    scoring_profile="risk_reduction",
    objective_note="优先寻找正超额；若仍无法转正，则保留回撤明显收敛且交易次数恢复到 >= 3 的组合。",
    output_dir="output/grouped_ma_rescan_high_beta",
    pass_threshold=1,
)


def build_candidate_yaml_lines() -> List[str]:
    lines = ["symbols:"]
    for symbol in LARGE_CAP_SYMBOLS:
        lines.append(f'  "{symbol}":')
        for key, value in LARGE_CAP_YAML_PARAMS.items():
            if isinstance(value, bool):
                rendered = "true" if value else "false"
            elif isinstance(value, float):
                rendered = f"{value:.2f}"
            else:
                rendered = value
            lines.append(f"    {key}: {rendered}")
    return lines


def _append_symbol_block(lines: List[str], symbol: str, params: Dict[str, Any]) -> None:
    lines.append(f'  "{symbol}":')
    for key, value in params.items():
        if isinstance(value, bool):
            rendered = "true" if value else "false"
        elif isinstance(value, float):
            rendered = f"{value:.2f}"
        else:
            rendered = value
        lines.append(f"    {key}: {rendered}")


def _candidate_row_to_params(row: pd.Series) -> Dict[str, Any]:
    return {
        "signal_model": "ma_cross_atr_v1",
        "trend_fast_ma": int(row["fast_ma"]),
        "trend_slow_ma": int(row["slow_ma"]),
        "atr_period": int(row["atr_period"]),
        "atr_ma_window": int(row["atr_ma_window"]),
        "buy_volatility_cap": float(row["buy_volatility_cap"]),
        "vol_breakout_mult": float(row["vol_breakout_mult"]),
        "enable_volatility_scaling": bool(row["enable_volatility_scaling"]),
        "target_volatility": float(row["target_volatility"]),
    }


def select_balanced_yaml_candidate(summary_df: pd.DataFrame) -> pd.Series | None:
    if summary_df.empty:
        return None
    eligible_mask = (summary_df["eligible_count"] >= 1) & (
        summary_df["annualized_excess_return"] > 0.0
    )
    if "eligible" in summary_df.columns:
        eligible_mask = eligible_mask & summary_df["eligible"].fillna(False).astype(bool)
    eligible_df = summary_df[eligible_mask].copy()
    if eligible_df.empty:
        return None
    if "objective_score" not in eligible_df.columns:
        eligible_df["objective_score"] = 0.0
    ranked = eligible_df.sort_values(
        ["eligible_count", "annualized_excess_return", "max_drawdown", "objective_score"],
        ascending=[False, False, False, False],
    )
    return ranked.iloc[0]


def build_merged_candidate_yaml_lines(
    balanced_summary_df: pd.DataFrame | None = None,
    high_beta_summary_df: pd.DataFrame | None = None,
) -> List[str]:
    lines = ["symbols:"]
    for symbol in LARGE_CAP_SYMBOLS:
        _append_symbol_block(lines, symbol, LARGE_CAP_YAML_PARAMS)

    if balanced_summary_df is not None and not balanced_summary_df.empty:
        candidate = select_balanced_yaml_candidate(balanced_summary_df)
        if candidate is not None:
            params = _candidate_row_to_params(candidate)
            for symbol in BALANCED_SYMBOLS:
                _append_symbol_block(lines, symbol, params)

    if high_beta_summary_df is not None and not high_beta_summary_df.empty:
        eligible_mask = high_beta_summary_df["eligible_count"] >= 1
        if "eligible" in high_beta_summary_df.columns:
            eligible_mask = eligible_mask & high_beta_summary_df["eligible"].fillna(False).astype(
                bool
            )
        eligible_df = high_beta_summary_df[eligible_mask].copy()
        if not eligible_df.empty:
            if "objective_score" not in eligible_df.columns:
                eligible_df["objective_score"] = 0.0
            ranked = eligible_df.sort_values(
                ["eligible_count", "annualized_excess_return", "max_drawdown", "objective_score"],
                ascending=[False, False, False, False],
            )
            candidate = ranked.iloc[0]
            params = _candidate_row_to_params(candidate)
            for symbol in HIGH_BETA_SYMBOLS:
                _append_symbol_block(lines, symbol, params)

    return lines


def write_candidate_yaml(path: str | Path) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(build_candidate_yaml_lines()) + "\n", encoding="utf-8")
    return output_path


def write_merged_candidate_yaml(
    path: str | Path,
    balanced_summary_df: pd.DataFrame | None = None,
    high_beta_summary_df: pd.DataFrame | None = None,
) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        "\n".join(build_merged_candidate_yaml_lines(balanced_summary_df, high_beta_summary_df))
        + "\n",
        encoding="utf-8",
    )
    return output_path


def build_rescan_grid(plan: GroupRescanPlan) -> List[Dict[str, Any]]:
    candidates: List[Dict[str, Any]] = []
    for fast_ma, slow_ma in plan.ma_combos:
        for atr_period in plan.atr_periods:
            for atr_ma_window in plan.atr_ma_windows:
                for buy_volatility_cap in plan.buy_volatility_caps:
                    for vol_breakout_mult in plan.vol_breakout_mults:
                        for enable_volatility_scaling in plan.enable_volatility_scaling_options:
                            target_vol_grid = (
                                plan.target_volatilities
                                if enable_volatility_scaling
                                else (plan.target_volatilities[0],)
                            )
                            for target_volatility in target_vol_grid:
                                candidates.append(
                                    {
                                        "fast_ma": fast_ma,
                                        "slow_ma": slow_ma,
                                        "atr_period": atr_period,
                                        "atr_ma_window": atr_ma_window,
                                        "buy_volatility_cap": buy_volatility_cap,
                                        "vol_breakout_mult": vol_breakout_mult,
                                        "enable_volatility_scaling": enable_volatility_scaling,
                                        "target_volatility": target_volatility,
                                    }
                                )
    return candidates


def candidate_key(candidate: Dict[str, Any]) -> str:
    scaling = "vol_on" if bool(candidate["enable_volatility_scaling"]) else "vol_off"
    return (
        f"ma={int(candidate['fast_ma'])}/{int(candidate['slow_ma'])}|"
        f"atr={int(candidate['atr_period'])}/{int(candidate['atr_ma_window'])}|"
        f"buy={float(candidate['buy_volatility_cap']):.2f}|"
        f"sell={float(candidate['vol_breakout_mult']):.2f}|"
        f"{scaling}|tv={float(candidate['target_volatility']):.2f}"
    )


def _normalize_result(
    result: Dict[str, Any],
    plan: GroupRescanPlan,
    candidate: Dict[str, Any],
) -> Dict[str, Any]:
    normalized = dict(result)
    normalized["group"] = plan.name
    normalized["candidate_key"] = candidate_key(candidate)
    normalized["fast_ma"] = int(candidate["fast_ma"])
    normalized["slow_ma"] = int(candidate["slow_ma"])
    normalized["atr_period"] = int(candidate["atr_period"])
    normalized["atr_ma_window"] = int(candidate["atr_ma_window"])
    normalized["buy_volatility_cap"] = float(candidate["buy_volatility_cap"])
    normalized["vol_breakout_mult"] = float(candidate["vol_breakout_mult"])
    normalized["enable_volatility_scaling"] = bool(candidate["enable_volatility_scaling"])
    normalized["target_volatility"] = float(candidate["target_volatility"])
    annualized_excess_return = float(normalized.get("annualized_excess_return", 0.0))
    max_drawdown = float(normalized.get("max_drawdown", 0.0))
    calmar_ratio = normalized.get("calmar_ratio")
    if calmar_ratio is None:
        calmar_ratio = annualized_excess_return / abs(max_drawdown) if max_drawdown < 0 else 0.0
    normalized["calmar_ratio"] = float(calmar_ratio)
    return normalized


def run_group_rescan(
    plan: GroupRescanPlan,
    backtest_runner: Callable[..., Dict[str, Any] | None],
) -> pd.DataFrame:
    rows: List[Dict[str, Any]] = []
    for candidate in build_rescan_grid(plan):
        for symbol in plan.symbols:
            result = backtest_runner(
                symbol=symbol,
                fast_ma=int(candidate["fast_ma"]),
                slow_ma=int(candidate["slow_ma"]),
                atr_period=int(candidate["atr_period"]),
                atr_ma_window=int(candidate["atr_ma_window"]),
                buy_volatility_cap=float(candidate["buy_volatility_cap"]),
                vol_breakout_mult=float(candidate["vol_breakout_mult"]),
                enable_volatility_scaling=bool(candidate["enable_volatility_scaling"]),
                target_volatility=float(candidate["target_volatility"]),
            )
            if result is None:
                continue
            rows.append(_normalize_result(result, plan, candidate))
    return pd.DataFrame(rows)


def summarize_rescan_results(raw_df: pd.DataFrame, plan: GroupRescanPlan) -> pd.DataFrame:
    if raw_df.empty:
        return pd.DataFrame()

    summary_df = (
        raw_df.groupby(
            [
                "group",
                "candidate_key",
                "fast_ma",
                "slow_ma",
                "atr_period",
                "atr_ma_window",
                "buy_volatility_cap",
                "vol_breakout_mult",
                "enable_volatility_scaling",
                "target_volatility",
            ],
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
            # worst-case 指标
            min_excess=("annualized_excess_return", "min"),
            max_drawdown_worst=("max_drawdown", "min"),
            min_trade_count=("trade_count", "min"),
        )
        .reset_index(drop=True)
    )

    summary_df["group_pass"] = summary_df["eligible_count"] >= plan.pass_threshold
    scored = score_signal_tuning_results(
        summary_df.rename(
            columns={
                "avg_excess": "annualized_excess_return",
                "avg_drawdown": "max_drawdown",
                "avg_trade_count": "trade_count",
                "avg_turnover": "turnover_rate",
                "avg_whipsaw": "whipsaw_rate",
                "avg_calmar_ratio": "calmar_ratio",
            }
        ),
        min_trade_count=plan.min_trade_count,
        max_drawdown_cap=plan.max_drawdown_cap,
        turnover_cap=plan.turnover_cap,
        whipsaw_cap=plan.whipsaw_cap,
        scoring_profile=plan.scoring_profile,
        hard_reject=False,
    )
    scored["group_pass"] = scored["eligible_count"] >= plan.pass_threshold

    # worst-case 惩罚：组内最小超额为负时扣减分数（系数 0.01，避免过度压制）
    if "min_excess" in scored.columns:
        negative_min_penalty = scored["min_excess"].clip(upper=0).abs() * 0.01
        scored["objective_score"] = scored["objective_score"] - negative_min_penalty

    # eligible_count=0 的候选强制设置最低分数，确保排在合格候选之后
    # 注意：此操作在 worst-case 惩罚之后，但 clip 只限制上限，不影响已低于 -0.01 的分数
    scored.loc[scored["eligible_count"] == 0, "objective_score"] = scored.loc[
        scored["eligible_count"] == 0, "objective_score"
    ].clip(upper=-0.01)

    return scored.sort_values(
        [
            "group_pass",
            "eligible_count",
            "objective_score",
            "annualized_excess_return",
            "max_drawdown",
        ],
        ascending=[False, False, False, False, False],
    ).reset_index(drop=True)


def build_group_report(path: str | Path, plan: GroupRescanPlan, summary_df: pd.DataFrame) -> Path:
    report_path = Path(path)
    report_path.parent.mkdir(parents=True, exist_ok=True)

    lines = [
        f"# {plan.name} MA rescan report",
        "",
        f"- 覆盖指数: {', '.join(plan.symbols)}",
        f"- 目标通过线: 至少 {plan.pass_threshold}/{len(plan.symbols)} eligible",
        f"- 约束: excess>0, max_drawdown>{plan.max_drawdown_cap:.0%}, trade_count>={plan.min_trade_count}, turnover<{plan.turnover_cap:.1f}, whipsaw<={plan.whipsaw_cap:.2f}",
        f"- 说明: {plan.objective_note}",
        "",
    ]

    if summary_df.empty:
        lines.extend(["## Top Candidates", "", "无结果。"])
    else:
        lines.extend(["## Top Candidates", ""])
        for _, row in summary_df.head(10).iterrows():
            avg_excess = float(row.get("annualized_excess_return", row.get("avg_excess", 0.0)))
            avg_drawdown = float(row.get("max_drawdown", row.get("avg_drawdown", 0.0)))
            lines.append(
                (
                    f"- MA{int(row['fast_ma'])}/{int(row['slow_ma'])} "
                    f"ATR{int(row['atr_period'])}/{int(row['atr_ma_window'])} "
                    f"buy={float(row['buy_volatility_cap']):.2f} "
                    f"sell={float(row['vol_breakout_mult']):.2f} "
                    f"vol_scale={'on' if bool(row['enable_volatility_scaling']) else 'off'} "
                    f"tv={float(row['target_volatility']):.2f} "
                    f"eligible_count={int(row['eligible_count'])}/{int(row['symbol_count'])} "
                    f"avg_excess={avg_excess:.2%} "
                    f"avg_dd={avg_drawdown:.2%} "
                    f"score={float(row['objective_score']):.3f}"
                )
            )

    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report_path


def save_rescan_outputs(
    plan: GroupRescanPlan,
    raw_df: pd.DataFrame,
    summary_df: pd.DataFrame,
) -> Dict[str, Path]:
    output_dir = Path(plan.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_path = output_dir / "raw_results.csv"
    summary_path = output_dir / "summary.csv"
    report_path = output_dir / "report.md"

    raw_df.to_csv(raw_path, index=False)
    summary_df.to_csv(summary_path, index=False)
    build_group_report(report_path, plan, summary_df)
    return {"raw": raw_path, "summary": summary_path, "report": report_path}


def execute_group_rescan(
    plan: GroupRescanPlan,
    backtest_runner: Callable[..., Dict[str, Any] | None],
) -> Dict[str, Path]:
    raw_df = run_group_rescan(plan, backtest_runner)
    summary_df = summarize_rescan_results(raw_df, plan)
    return save_rescan_outputs(plan, raw_df, summary_df)


def iter_plans() -> Iterable[GroupRescanPlan]:
    return (BALANCED_PLAN, HIGH_BETA_PLAN)
