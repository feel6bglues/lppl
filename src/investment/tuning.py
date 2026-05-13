# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Dict

import pandas as pd

SCORING_PROFILES: Dict[str, Dict[str, float]] = {
    "balanced": {
        "calmar_ratio": 0.30,
        "annualized_excess_return": 0.25,
        "max_drawdown": 0.20,
        "trade_count": 0.10,
        "turnover_rate": 0.10,
        "whipsaw_rate": 0.05,
    },
    "signal_release": {
        "calmar_ratio": 0.20,
        "annualized_excess_return": 0.25,
        "max_drawdown": 0.10,
        "trade_count": 0.25,
        "turnover_rate": 0.10,
        "whipsaw_rate": 0.10,
    },
    "risk_reduction": {
        "calmar_ratio": 0.35,
        "annualized_excess_return": 0.15,
        "max_drawdown": 0.25,
        "trade_count": 0.05,
        "turnover_rate": 0.15,
        "whipsaw_rate": 0.05,
    },
}


def _rank_metric(series: pd.Series, higher_is_better: bool) -> pd.Series:
    if len(series) <= 1:
        return pd.Series([1.0] * len(series), index=series.index, dtype=float)
    return series.rank(pct=True, ascending=higher_is_better).astype(float)


def _risk_band(row: pd.Series) -> str:
    max_drawdown = float(row.get("max_drawdown", 0.0))
    annualized_excess_return = float(row.get("annualized_excess_return", 0.0))
    calmar_ratio = float(row.get("calmar_ratio", 0.0))

    if max_drawdown <= -0.25 or annualized_excess_return <= 0.0:
        return "DANGER"
    if max_drawdown <= -0.18 or calmar_ratio < 0.20:
        return "Warning"
    if max_drawdown <= -0.10 or calmar_ratio < 0.50:
        return "Watch"
    return "Safe"


def _suggest_position(risk_band: str) -> str:
    mapping = {
        "DANGER": "0-20%",
        "Warning": "20-40%",
        "Watch": "60-80%",
        "Safe": "80-100%",
    }
    return mapping.get(risk_band, "60-80%")


def _build_reject_reason(
    row: pd.Series,
    min_trade_count: int,
    max_drawdown_cap: float,
    turnover_cap: float,
    whipsaw_cap: float,
) -> str:
    reasons = []
    if float(row.get("trade_count", 0.0)) < float(min_trade_count):
        reasons.append("trade_count")
    if float(row.get("annualized_excess_return", 0.0)) <= 0.0:
        reasons.append("non_positive_excess")
    if float(row.get("max_drawdown", 0.0)) <= float(max_drawdown_cap):
        reasons.append("max_drawdown_cap")

    turnover_to_check = row.get("annualized_turnover_rate", row.get("turnover_rate", 0.0))
    if float(turnover_to_check) >= float(turnover_cap):
        reasons.append("turnover_cap")
    if float(row.get("whipsaw_rate", 0.0)) > float(whipsaw_cap):
        reasons.append("whipsaw_cap")
    return ",".join(reasons)


def score_signal_tuning_results(
    results_df: pd.DataFrame,
    min_trade_count: int = 3,
    max_drawdown_cap: float = -0.35,
    turnover_cap: float = 8.0,
    whipsaw_cap: float = 0.35,
    scoring_profile: str = "balanced",
    hard_reject: bool = True,
) -> pd.DataFrame:
    if results_df.empty:
        return results_df.copy()
    if scoring_profile not in SCORING_PROFILES:
        raise ValueError(f"未知 scoring_profile: {scoring_profile}")

    scored = results_df.copy().reset_index(drop=True)
    profile = SCORING_PROFILES[scoring_profile]

    scored["reject_reason"] = scored.apply(
        _build_reject_reason,
        axis=1,
        min_trade_count=min_trade_count,
        max_drawdown_cap=max_drawdown_cap,
        turnover_cap=turnover_cap,
        whipsaw_cap=whipsaw_cap,
    )
    scored["eligible"] = scored["reject_reason"] == ""

    required_columns = [
        "calmar_ratio",
        "annualized_excess_return",
        "max_drawdown",
        "trade_count",
        "turnover_rate",
        "whipsaw_rate",
    ]
    for column in required_columns:
        if column not in scored.columns:
            scored[column] = 0.0

    scored["turnover_for_ranking"] = scored.get(
        "annualized_turnover_rate", scored.get("turnover_rate", 0.0)
    )

    metric_ranks = pd.DataFrame(index=scored.index)
    metric_ranks["calmar_ratio_rank"] = _rank_metric(scored["calmar_ratio"], higher_is_better=True)
    metric_ranks["annualized_excess_return_rank"] = _rank_metric(
        scored["annualized_excess_return"], higher_is_better=True
    )
    metric_ranks["max_drawdown_rank"] = _rank_metric(scored["max_drawdown"], higher_is_better=True)
    metric_ranks["trade_count_rank"] = _rank_metric(scored["trade_count"], higher_is_better=True)
    metric_ranks["turnover_rate_rank"] = _rank_metric(
        scored["turnover_for_ranking"], higher_is_better=False
    )
    metric_ranks["whipsaw_rate_rank"] = _rank_metric(scored["whipsaw_rate"], higher_is_better=False)

    scored["objective_score"] = (
        metric_ranks["calmar_ratio_rank"] * profile["calmar_ratio"]
        + metric_ranks["annualized_excess_return_rank"] * profile["annualized_excess_return"]
        + metric_ranks["max_drawdown_rank"] * profile["max_drawdown"]
        + metric_ranks["trade_count_rank"] * profile["trade_count"]
        + metric_ranks["turnover_rate_rank"] * profile["turnover_rate"]
        + metric_ranks["whipsaw_rate_rank"] * profile["whipsaw_rate"]
    )
    if hard_reject:
        scored.loc[~scored["eligible"], "objective_score"] = -1.0

    scored["risk_band"] = scored.apply(_risk_band, axis=1)
    scored["suggest_position"] = scored["risk_band"].map(_suggest_position)
    scored["objective_score"] = scored["objective_score"].astype(float)
    return scored.sort_values(
        ["objective_score", "eligible", "calmar_ratio", "annualized_excess_return"],
        ascending=[False, False, False, False],
    ).reset_index(drop=True)
