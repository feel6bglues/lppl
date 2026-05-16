#!/usr/bin/env python3
# RESEARCH ONLY — not production code
# -*- coding: utf-8 -*-
"""
按交易日回放 docs/new 中的三只样本，生成逐日报告，并对连续性样本做验收。
"""

from __future__ import annotations

import csv
import sys
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.data.manager import DataManager
from src.wyckoff import WyckoffAnalyzer, WyckoffPhase
from src.wyckoff.models import WyckoffReport


@dataclass(frozen=True)
class ReplaySpec:
    symbol: str
    name: str
    start_date: str
    baseline_doc: str


@dataclass(frozen=True)
class BaselineExpectation:
    symbol: str
    as_of: str
    expected_phase: WyckoffPhase
    expected_direction_keyword: str
    expected_keywords: tuple[str, ...]


REPLAY_SPECS: tuple[ReplaySpec, ...] = (
    ReplaySpec(
        symbol="002216.SZ",
        name="三全食品",
        start_date="2026-03-06",
        baseline_doc="docs/new/002216_三全食品_连续性完整分析档案.md",
    ),
    ReplaySpec(
        symbol="600859.SH",
        name="王府井",
        start_date="2026-03-06",
        baseline_doc="docs/new/600859_王府井_连续性完整分析档案.md",
    ),
    ReplaySpec(
        symbol="300442.SZ",
        name="润泽科技",
        start_date="2026-03-06",
        baseline_doc="docs/new/300442_润泽科技_连续性完整分析档案.md",
    ),
)


BASELINE_EXPECTATIONS: tuple[BaselineExpectation, ...] = (
    BaselineExpectation("002216.SZ", "2026-03-06", WyckoffPhase.MARKUP, "做多", ("Markup",)),
    BaselineExpectation("002216.SZ", "2026-03-20", WyckoffPhase.ACCUMULATION, "空仓观望", ("Phase B/Phase C",)),
    BaselineExpectation("002216.SZ", "2026-03-23", WyckoffPhase.ACCUMULATION, "空仓观望", ("Spring",)),
    BaselineExpectation("002216.SZ", "2026-03-24", WyckoffPhase.ACCUMULATION, "空仓观望", ("Spring", "ST")),
    BaselineExpectation("002216.SZ", "2026-03-25", WyckoffPhase.MARKUP, "做多", ("SOS",)),
    BaselineExpectation("002216.SZ", "2026-03-26", WyckoffPhase.MARKUP, "空仓观望", ("Markup",)),
    BaselineExpectation("002216.SZ", "2026-03-27", WyckoffPhase.MARKUP, "空仓观望", ("Markup",)),
    BaselineExpectation("002216.SZ", "2026-03-30", WyckoffPhase.MARKUP, "空仓观望", ("LPS",)),
    BaselineExpectation("002216.SZ", "2026-03-31", WyckoffPhase.MARKUP, "空仓观望", ("Markup",)),
    BaselineExpectation("002216.SZ", "2026-04-03", WyckoffPhase.MARKUP, "空仓观望", ("No Trade Zone",)),
    BaselineExpectation("002216.SZ", "2026-04-07", WyckoffPhase.MARKUP, "做多", ("LPS",)),
    BaselineExpectation("002216.SZ", "2026-04-08", WyckoffPhase.MARKUP, "持有", ("Lack of Supply",)),
    BaselineExpectation("002216.SZ", "2026-04-09", WyckoffPhase.MARKUP, "空仓", ("Lack of Demand",)),
    BaselineExpectation("002216.SZ", "2026-04-13", WyckoffPhase.MARKUP, "买入", ("Test",)),
    BaselineExpectation("002216.SZ", "2026-04-14", WyckoffPhase.MARKUP, "买入", ("Shakeout",)),
    BaselineExpectation("002216.SZ", "2026-04-23", WyckoffPhase.MARKUP, "持有", ("Phase E", "SOS")),
    BaselineExpectation("002216.SZ", "2026-04-24", WyckoffPhase.MARKUP, "持有", ("BUEC",)),
    BaselineExpectation("002216.SZ", "2026-04-27", WyckoffPhase.MARKUP, "持有", ("Phase E",)),
    BaselineExpectation("002216.SZ", "2026-04-28", WyckoffPhase.MARKUP, "持有", ("Phase E",)),
    BaselineExpectation("002216.SZ", "2026-04-29", WyckoffPhase.MARKUP, "持有", ("Phase E",)),
    BaselineExpectation("600859.SH", "2026-03-06", WyckoffPhase.MARKDOWN, "空仓观望", ("Markdown",)),
    BaselineExpectation("600859.SH", "2026-03-20", WyckoffPhase.MARKDOWN, "空仓观望", ("Markdown",)),
    BaselineExpectation("600859.SH", "2026-03-23", WyckoffPhase.MARKDOWN, "空仓观望", ("Markdown",)),
    BaselineExpectation("600859.SH", "2026-03-24", WyckoffPhase.MARKDOWN, "空仓观望", ("Markdown",)),
    BaselineExpectation("600859.SH", "2026-03-25", WyckoffPhase.MARKDOWN, "空仓观望", ("Markdown",)),
    BaselineExpectation("600859.SH", "2026-03-26", WyckoffPhase.MARKDOWN, "空仓观望", ("Markdown",)),
    BaselineExpectation("600859.SH", "2026-03-27", WyckoffPhase.MARKDOWN, "空仓观望", ("Markdown",)),
    BaselineExpectation("600859.SH", "2026-03-30", WyckoffPhase.MARKDOWN, "空仓观望", ("Markdown",)),
    BaselineExpectation("600859.SH", "2026-03-31", WyckoffPhase.MARKDOWN, "空仓观望", ("Markdown",)),
    BaselineExpectation("600859.SH", "2026-04-03", WyckoffPhase.MARKDOWN, "空仓观望", ("Markdown",)),
    BaselineExpectation("600859.SH", "2026-04-07", WyckoffPhase.MARKDOWN, "空仓观望", ("Markdown",)),
    BaselineExpectation("600859.SH", "2026-04-08", WyckoffPhase.MARKDOWN, "空仓观望", ("死猫", "Markdown")),
    BaselineExpectation("600859.SH", "2026-04-09", WyckoffPhase.MARKDOWN, "空仓观望", ("Markdown",)),
    BaselineExpectation("600859.SH", "2026-04-13", WyckoffPhase.MARKDOWN, "空仓观望", ("Markdown",)),
    BaselineExpectation("600859.SH", "2026-04-14", WyckoffPhase.MARKDOWN, "空仓观望", ("Markdown",)),
    BaselineExpectation("600859.SH", "2026-04-23", WyckoffPhase.MARKDOWN, "空仓观望", ("Markdown",)),
    BaselineExpectation("600859.SH", "2026-04-24", WyckoffPhase.MARKDOWN, "空仓观望", ("Markdown",)),
    BaselineExpectation("600859.SH", "2026-04-27", WyckoffPhase.MARKDOWN, "空仓观望", ("Markdown",)),
    BaselineExpectation("600859.SH", "2026-04-28", WyckoffPhase.MARKDOWN, "空仓观望", ("Markdown",)),
    BaselineExpectation("600859.SH", "2026-04-29", WyckoffPhase.MARKDOWN, "空仓观望", ("Markdown",)),
    BaselineExpectation("300442.SZ", "2026-03-30", WyckoffPhase.UNKNOWN, "空仓观望", ("不确定",)),
    BaselineExpectation("300442.SZ", "2026-03-31", WyckoffPhase.UNKNOWN, "空仓观望", ("不确定",)),
    BaselineExpectation("300442.SZ", "2026-04-03", WyckoffPhase.MARKDOWN, "空仓观望", ("Markdown",)),
    BaselineExpectation("300442.SZ", "2026-04-07", WyckoffPhase.UNKNOWN, "空仓观望", ("SC",)),
    BaselineExpectation("300442.SZ", "2026-04-08", WyckoffPhase.UNKNOWN, "空仓观望", ("Phase A", "AR")),
    BaselineExpectation("300442.SZ", "2026-04-09", WyckoffPhase.UNKNOWN, "空仓观望", ("ST",)),
    BaselineExpectation("300442.SZ", "2026-04-13", WyckoffPhase.UNKNOWN, "空仓观望", ("AR",)),
    BaselineExpectation("300442.SZ", "2026-04-14", WyckoffPhase.UNKNOWN, "空仓观望", ("Upthrust",)),
    BaselineExpectation("300442.SZ", "2026-04-23", WyckoffPhase.UNKNOWN, "空仓观望", ("UT",)),
    BaselineExpectation("300442.SZ", "2026-04-24", WyckoffPhase.UNKNOWN, "空仓观望", ("Phase B",)),
    BaselineExpectation("300442.SZ", "2026-04-27", WyckoffPhase.UNKNOWN, "空仓观望", ("Phase B",)),
    BaselineExpectation("300442.SZ", "2026-04-28", WyckoffPhase.UNKNOWN, "空仓观望", ("Phase B",)),
    BaselineExpectation("300442.SZ", "2026-04-29", WyckoffPhase.UNKNOWN, "空仓观望", ("反抽",)),
)


def get_output_dir() -> Path:
    return PROJECT_ROOT / "output" / "wyckoff_daily_replay"


def build_trading_days(df: pd.DataFrame, start_date: str) -> list[pd.Timestamp]:
    dates = df.loc[df["date"] >= pd.Timestamp(start_date), "date"].drop_duplicates().sort_values()
    return [pd.Timestamp(value) for value in dates.tolist()]


def analyze_until(
    analyzer: WyckoffAnalyzer,
    df: pd.DataFrame,
    symbol: str,
    as_of: pd.Timestamp,
) -> WyckoffReport:
    sliced = df[df["date"] <= as_of].copy()
    return analyzer.analyze(sliced, symbol=symbol, period="日线", multi_timeframe=True)


def save_daily_report(
    output_dir: Path,
    spec: ReplaySpec,
    as_of: pd.Timestamp,
    report: WyckoffReport,
) -> Path:
    symbol_dir = output_dir / spec.symbol.replace(".", "_") / "daily_reports"
    symbol_dir.mkdir(parents=True, exist_ok=True)
    output_path = symbol_dir / f"{as_of.date()}.md"
    output_path.write_text(report.to_markdown(), encoding="utf-8")
    return output_path


def evaluate_design_completeness(report: WyckoffReport) -> dict[str, int]:
    entry_price = report.risk_reward.entry_price or 0
    stop_loss = report.risk_reward.stop_loss or 0
    first_target = report.risk_reward.first_target or 0
    direction = report.trading_plan.direction or ""
    is_no_trade = any(keyword in direction for keyword in ("空仓", "观望", "放弃"))
    checks = {
        "has_bc_or_tr": int(report.structure.bc_point is not None or report.structure.trading_range_high > 0),
        "has_phase": int(bool(report.structure.phase.value)),
        "has_t1_risk": int(bool(report.signal.t1_risk评估)),
        "has_entry": int(entry_price > 0 or is_no_trade),
        "has_stop": int(stop_loss > 0 or is_no_trade),
        "has_target": int(first_target > 0 or is_no_trade),
        "has_qualification": int(bool(report.trading_plan.current_qualification)),
        "has_direction": int(bool(direction)),
        "has_trigger": int(bool(report.trading_plan.trigger_condition)),
        "has_invalidation": int(bool(report.trading_plan.invalidation_point)),
    }
    max_score = len(checks)
    checks["score"] = sum(checks.values())
    checks["max_score"] = max_score
    return checks


def compare_with_baseline(
    report: WyckoffReport,
    baseline: BaselineExpectation,
) -> dict[str, str | int | float]:
    combined_text = " ".join(
        [
            report.signal.description,
            report.trading_plan.current_qualification,
            report.trading_plan.direction,
            report.trading_plan.trigger_condition,
        ]
    )
    phase_match = int(report.structure.phase == baseline.expected_phase)
    direction_match = int(baseline.expected_direction_keyword in report.trading_plan.direction)
    keyword_hits = sum(1 for keyword in baseline.expected_keywords if keyword in combined_text)
    keyword_target = len(baseline.expected_keywords)
    score = phase_match + direction_match + keyword_hits
    max_score = 2 + keyword_target
    return {
        "symbol": baseline.symbol,
        "as_of": baseline.as_of,
        "expected_phase": baseline.expected_phase.value,
        "actual_phase": report.structure.phase.value,
        "phase_match": phase_match,
        "expected_direction_keyword": baseline.expected_direction_keyword,
        "actual_direction": report.trading_plan.direction,
        "direction_match": direction_match,
        "expected_keywords": " | ".join(baseline.expected_keywords),
        "keyword_hits": keyword_hits,
        "keyword_target": keyword_target,
        "score": score,
        "max_score": max_score,
        "score_ratio": round(score / max_score, 3) if max_score else 0.0,
    }


def write_csv(path: Path, rows: list[dict[str, str | int | float]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def render_markdown_summary(
    output_dir: Path,
    replay_rows: list[dict[str, str | int | float]],
    comparison_rows: list[dict[str, str | int | float]],
) -> Path:
    md_path = output_dir / "continuity_verification.md"
    design_rows = [row for row in replay_rows if int(row["is_baseline_day"]) == 1]
    avg_design = round(sum(float(row["design_score_ratio"]) for row in replay_rows) / len(replay_rows), 3)
    avg_baseline = round(sum(float(row["score_ratio"]) for row in comparison_rows) / len(comparison_rows), 3)
    low_days = [
        row
        for row in comparison_rows
        if float(row["score_ratio"]) < 0.6
    ]

    lines = [
        "# Wyckoff Daily Replay Verification",
        "",
        f"- 回放交易日报总数: {len(replay_rows)}",
        f"- 样本基线对照总数: {len(comparison_rows)}",
        f"- 日报设计指标平均完成度: {avg_design}",
        f"- 样本连续性平均相似度: {avg_baseline}",
        "",
        "## 基线较弱日期",
        "",
        "| Symbol | Date | Expected Phase | Actual Phase | Direction Match | Keyword Hits | Score |",
        "|---|---|---|---|---:|---:|---:|",
    ]

    if low_days:
        for row in low_days:
            lines.append(
                "| {symbol} | {as_of} | {expected_phase} | {actual_phase} | {direction_match} | "
                "{keyword_hits}/{keyword_target} | {score}/{max_score} |".format(**row)
            )
    else:
        lines.append("| - | - | - | - | - | - | - |")

    lines.extend(
        [
            "",
            "## 样本日期设计指标",
            "",
            "| Symbol | Date | Design Score | Phase | Direction | Report |",
            "|---|---|---:|---|---|---|",
        ]
    )
    for row in design_rows:
        lines.append(
            "| {symbol} | {as_of} | {design_score}/{design_max_score} | {phase} | {direction} | {report_path} |".format(
                **row
            )
        )

    md_path.write_text("\n".join(lines), encoding="utf-8")
    return md_path


def load_data_frame(data_manager: DataManager, symbol: str) -> pd.DataFrame:
    df = data_manager.get_data(symbol)
    if df is None or df.empty:
        raise RuntimeError(f"failed to load data for {symbol}")
    frame = df.copy()
    frame["date"] = pd.to_datetime(frame["date"])
    return frame.sort_values("date").reset_index(drop=True)


def display_report_path(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def baseline_index() -> dict[tuple[str, str], BaselineExpectation]:
    return {(item.symbol, item.as_of): item for item in BASELINE_EXPECTATIONS}


def generate_daily_replay(output_dir: Path | None = None) -> tuple[list[dict[str, str | int | float]], list[dict[str, str | int | float]]]:
    base_output_dir = output_dir or get_output_dir()
    base_output_dir.mkdir(parents=True, exist_ok=True)

    data_manager = DataManager()
    analyzer = WyckoffAnalyzer(lookback_days=120)
    expectations = baseline_index()

    replay_rows: list[dict[str, str | int | float]] = []
    comparison_rows: list[dict[str, str | int | float]] = []

    for spec in REPLAY_SPECS:
        df = load_data_frame(data_manager, spec.symbol)
        for as_of in build_trading_days(df, spec.start_date):
            report = analyze_until(analyzer, df, spec.symbol, as_of)
            report_path = save_daily_report(base_output_dir, spec, as_of, report)
            design = evaluate_design_completeness(report)

            replay_rows.append(
                {
                    "symbol": spec.symbol,
                    "name": spec.name,
                    "as_of": str(as_of.date()),
                    "phase": report.structure.phase.value,
                    "monthly_phase": (
                        report.multi_timeframe.monthly.phase.value
                        if report.multi_timeframe and report.multi_timeframe.monthly
                        else ""
                    ),
                    "weekly_phase": (
                        report.multi_timeframe.weekly.phase.value
                        if report.multi_timeframe and report.multi_timeframe.weekly
                        else ""
                    ),
                    "direction": report.trading_plan.direction,
                    "current_price": round(report.structure.current_price, 2),
                    "rr_ratio": round(report.risk_reward.reward_risk_ratio, 3),
                    "design_score": design["score"],
                    "design_max_score": design["max_score"],
                    "design_score_ratio": round(design["score"] / design["max_score"], 3),
                    "is_baseline_day": int((spec.symbol, str(as_of.date())) in expectations),
                    "report_path": display_report_path(report_path),
                }
            )

            baseline = expectations.get((spec.symbol, str(as_of.date())))
            if baseline is not None:
                comparison_rows.append(compare_with_baseline(report, baseline))

    if not replay_rows:
        raise RuntimeError("no replay rows generated")
    if not comparison_rows:
        raise RuntimeError("no comparison rows generated")

    write_csv(base_output_dir / "daily_replay_summary.csv", replay_rows)
    write_csv(base_output_dir / "continuity_comparison.csv", comparison_rows)
    render_markdown_summary(base_output_dir, replay_rows, comparison_rows)

    return replay_rows, comparison_rows


def main() -> None:
    output_dir = get_output_dir()
    replay_rows, comparison_rows = generate_daily_replay(output_dir)
    print(f"saved: {output_dir / 'daily_replay_summary.csv'}")
    print(f"saved: {output_dir / 'continuity_comparison.csv'}")
    print(f"saved: {output_dir / 'continuity_verification.md'}")
    print(f"daily rows: {len(replay_rows)}")
    print(f"baseline rows: {len(comparison_rows)}")


if __name__ == "__main__":
    main()
