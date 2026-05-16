# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

import pandas as pd

EXPECTED_SECTIONS: List[Tuple[str, str]] = [
    ("Template A 样本内", "a_is"),
    ("Template B 样本内", "b_is"),
    ("Template A 样本外", "a_oos"),
    ("Template B 样本外", "b_oos"),
    ("全量 7 指数复核", "full"),
]


def _latest_summary_file(summary_dir: Path) -> Path:
    files = sorted(summary_dir.glob("ma_atr_stage4_best_*.csv"))
    if not files:
        raise FileNotFoundError(f"未找到 stage4_best 文件: {summary_dir}")
    return files[-1]


def _load_frame(base_dir: Path) -> Tuple[pd.DataFrame, Path]:
    summary_dir = base_dir / "summary"
    csv_path = _latest_summary_file(summary_dir)
    df = pd.read_csv(csv_path)
    if df.empty:
        raise ValueError(f"汇总文件为空: {csv_path}")
    return df, csv_path


def _format_pct(value: float, digits: int = 2) -> str:
    return f"{float(value) * 100:.{digits}f}%"


def _format_rate(value: float, digits: int = 2) -> str:
    return f"{float(value):.{digits}f}%"


def _mean_row(df: pd.DataFrame) -> Dict[str, float]:
    annualized_turnover_rate = 0.0
    if "annualized_turnover_rate" in df.columns and not df["annualized_turnover_rate"].isna().all():
        annualized_turnover_rate = float(df["annualized_turnover_rate"].mean())
    elif "turnover_rate" in df.columns and "start_date" in df.columns and "end_date" in df.columns and not df.empty:
        try:
            start = pd.to_datetime(df["start_date"].iloc[0])
            end = pd.to_datetime(df["end_date"].iloc[0])
            years = (end - start).days / 365.25
            if years > 0:
                annualized_turnover_rate = float(df["turnover_rate"].mean() / years)
        except Exception:
            annualized_turnover_rate = 0.0

    return {
        "annualized_return": float(df["annualized_return"].mean()) if "annualized_return" in df.columns else 0.0,
        "annualized_excess_return": float(df["annualized_excess_return"].mean())
        if "annualized_excess_return" in df.columns
        else 0.0,
        "max_drawdown": float(df["max_drawdown"].mean()) if "max_drawdown" in df.columns else 0.0,
        "trade_count": float(df["trade_count"].mean()) if "trade_count" in df.columns else 0.0,
        "turnover_rate": float(df["turnover_rate"].mean()) if "turnover_rate" in df.columns else 0.0,
        "annualized_turnover_rate": annualized_turnover_rate,
        "whipsaw_rate": float(df["whipsaw_rate"].mean()) if "whipsaw_rate" in df.columns else 0.0,
        "eligible": int(df["eligible"].sum()) if "eligible" in df.columns else 0,
        "count": int(len(df)),
    }


def _dataset_section(title: str, df: pd.DataFrame, csv_path: Path, turnover_cap: float = 8.0) -> List[str]:
    summary = _mean_row(df)
    lines = [f"## {title}", "", f"- 数据源: `{csv_path}`", ""]

    detail_cols = [
        c
        for c in [
            "symbol",
            "annualized_return",
            "annualized_excess_return",
            "max_drawdown",
            "trade_count",
            "turnover_rate",
            "annualized_turnover_rate",
            "whipsaw_rate",
            "eligible",
            "objective_score",
        ]
        if c in df.columns
    ]
    if detail_cols:
        detail_df = df[detail_cols].copy()
        if "annualized_return" in detail_df.columns:
            detail_df["annualized_return"] = detail_df["annualized_return"].map(lambda x: _format_pct(x, 2))
        if "annualized_excess_return" in detail_df.columns:
            detail_df["annualized_excess_return"] = detail_df["annualized_excess_return"].map(
                lambda x: _format_pct(x, 2)
            )
        if "max_drawdown" in detail_df.columns:
            detail_df["max_drawdown"] = detail_df["max_drawdown"].map(lambda x: _format_pct(x, 2))
        if "turnover_rate" in detail_df.columns:
            detail_df["turnover_rate"] = detail_df["turnover_rate"].map(lambda x: _format_rate(x, 2))
        if "annualized_turnover_rate" in detail_df.columns:
            detail_df["annualized_turnover_rate"] = detail_df["annualized_turnover_rate"].map(
                lambda x: _format_rate(x, 2)
            )
        if "whipsaw_rate" in detail_df.columns:
            detail_df["whipsaw_rate"] = detail_df["whipsaw_rate"].map(lambda x: f"{float(x):.4f}")
        if "eligible" in detail_df.columns:
            detail_df["eligible"] = detail_df["eligible"].map(lambda x: "✅" if bool(x) else "❌")
        if "objective_score" in detail_df.columns:
            detail_df["objective_score"] = detail_df["objective_score"].map(lambda x: f"{float(x):.4f}")
        lines.extend([detail_df.to_markdown(index=False), ""])

    turnover_gap = summary["annualized_turnover_rate"] - turnover_cap
    lines.extend(
        [
            f"- 平均年化收益: {_format_pct(summary['annualized_return'])}",
            f"- 平均年化超额收益: {_format_pct(summary['annualized_excess_return'])}",
            f"- 平均最大回撤: {_format_pct(summary['max_drawdown'])}",
            f"- 平均交易次数: {summary['trade_count']:.2f}",
            f"- 平均换手率(累计): {_format_rate(summary['turnover_rate'])}",
            f"- 平均换手率(年化): {_format_rate(summary['annualized_turnover_rate'])}",
            f"- turnover_cap: {turnover_cap:.1f}%",
            f"- turnover_gap: {_format_rate(turnover_gap)} (年化换手 - turnover_cap)",
            f"- 平均 whipsaw_rate: {summary['whipsaw_rate']:.4f}",
            f"- Eligible: {summary['eligible']}/{summary['count']}",
            "",
        ]
    )
    return lines


def generate_report(base_dir: Path, output_path: Path, turnover_cap: float = 8.0) -> Path:
    sections = []
    loaded: Dict[str, Tuple[pd.DataFrame, Path]] = {}
    for title, suffix in EXPECTED_SECTIONS:
        section_dir = base_dir / suffix
        if not section_dir.exists():
            raise FileNotFoundError(f"未找到目录: {section_dir}")
        loaded[suffix] = _load_frame(section_dir)

    report_lines = [
        "# MA+ATR 下一轮测试报告（修正版）",
        "",
        f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## 一、口径说明",
        "",
        "- 本报告中的“年化收益”使用 `annualized_return`",
        "- 本报告中的“年化超额收益”使用 `annualized_excess_return`",
        "- 本报告中的 turnover_rate 为累计换手率",
        "- 本报告中的 annualized_turnover_rate 为年化换手率（累计换手 / 投资年数）",
        "- turnover_cap 门槛用于判断 eligible，使用 annualized_turnover_rate",
        "- turnover_gap = annualized_turnover_rate - turnover_cap",
        "- 报告生成时不再混用收益口径",
        "",
        "## 二、执行结果",
        "",
    ]

    for title, suffix in EXPECTED_SECTIONS:
        df, csv_path = loaded[suffix]
        report_lines.extend(_dataset_section(title, df, csv_path, turnover_cap))

    full_df, _ = loaded["full"]
    full_summary = _mean_row(full_df)
    full_turnover_gap = full_summary["annualized_turnover_rate"] - turnover_cap
    a_oos_summary = _mean_row(loaded["a_oos"][0])
    b_oos_summary = _mean_row(loaded["b_oos"][0])
    report_lines.extend(
        [
            "## 三、关键结论",
            "",
            f"- Template A 样本外平均年化超额收益: {_format_pct(a_oos_summary['annualized_excess_return'])}",
            f"- Template A 样本外平均年化换手率: {_format_rate(a_oos_summary['annualized_turnover_rate'])}",
            f"- Template B 样本外平均年化超额收益: {_format_pct(b_oos_summary['annualized_excess_return'])}",
            f"- Template B 样本外平均年化换手率: {_format_rate(b_oos_summary['annualized_turnover_rate'])}",
            f"- 全量平均年化超额收益: {_format_pct(full_summary['annualized_excess_return'])}",
            f"- 全量平均最大回撤: {_format_pct(full_summary['max_drawdown'])}",
            f"- 全量平均年化换手率: {_format_rate(full_summary['annualized_turnover_rate'])}",
            f"- turnover_cap: {turnover_cap:.1f}%",
            f"- 全量 turnover_gap: {_format_rate(full_turnover_gap)}",
            "",
        ]
    )

    output_path.write_text("\n".join(report_lines), encoding="utf-8")
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description="生成 MA+ATR 下一轮测试报告（修正版）")
    parser.add_argument("--base-dir", default="output/ma_atr_next_round_no932", help="各阶段输出的基础目录前缀")
    parser.add_argument("--output", required=True, help="报告输出路径")
    args = parser.parse_args()

    base_dir = Path(args.base_dir)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    generate_report(base_dir, output_path)
    print(f"SAVED {output_path}")


if __name__ == "__main__":
    main()
