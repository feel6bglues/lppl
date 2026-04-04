# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Dict

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


def _set_chinese_font() -> None:
    mpl.rcParams["font.sans-serif"] = [
        "Noto Sans CJK SC",
        "Microsoft YaHei",
        "AR PL UKai CN",
        "DejaVu Sans",
    ]
    mpl.rcParams["axes.unicode_minus"] = False


class Optimal8ReadableReportGenerator:
    def __init__(self, report_dir: str, plot_dir: str):
        self.report_dir = Path(report_dir)
        self.plot_dir = Path(plot_dir)
        self.report_dir.mkdir(parents=True, exist_ok=True)
        self.plot_dir.mkdir(parents=True, exist_ok=True)

    def generate(self, summary_csv: str, output_stem: str = "optimal8_human_friendly_report_v2") -> Dict[str, str]:
        _set_chinese_font()
        summary_path = Path(summary_csv)
        if not summary_path.exists():
            raise FileNotFoundError(f"未找到汇总文件: {summary_csv}")

        df = pd.read_csv(summary_path).sort_values("objective_score", ascending=False).reset_index(drop=True)
        if df.empty:
            raise ValueError(f"汇总文件为空: {summary_csv}")

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        band_colors = {"DANGER": "#dc2626", "Warning": "#f59e0b", "Watch": "#2563eb", "Safe": "#16a34a"}
        colors = [band_colors.get(x, "#6b7280") for x in df["risk_band"]]

        chart1 = self._plot_priority(df, colors, stamp)
        if {"precision", "recall"}.issubset(df.columns):
            chart2 = self._plot_precision_recall(df, stamp)
        else:
            chart2 = self._plot_trade_quality(df, stamp)

        if {"true_positive", "false_positive"}.issubset(df.columns):
            chart3 = self._plot_signal_structure(df, stamp)
        else:
            chart3 = self._plot_drawdown_trade_count(df, stamp)
        chart4 = self._plot_param_profile(df, stamp)
        report = self._write_markdown(df, [chart1, chart2, chart3, chart4], output_stem, stamp)

        return {
            "report_path": str(report),
            "chart_priority": str(chart1),
            "chart_precision_recall": str(chart2),
            "chart_signal_structure": str(chart3),
            "chart_param_profile": str(chart4),
        }

    def _plot_priority(self, df: pd.DataFrame, colors, stamp: str) -> Path:
        fig, ax = plt.subplots(figsize=(12, 6))
        y = np.arange(len(df))
        ax.barh(y, df["objective_score"], color=colors)
        ax.set_yticks(y)
        ax.set_yticklabels(df["symbol"])
        ax.invert_yaxis()
        ax.set_xlabel("综合评分（objective_score）")
        ax.set_title("图1｜8指数风险控制优先级（从高到低）")
        for i, (v, band) in enumerate(zip(df["objective_score"], df["risk_band"])):
            ax.text(v + 0.004, i, f"{v:.3f}  {band}", va="center", fontsize=9)
        ax.grid(axis="x", alpha=0.25)
        fig.tight_layout()
        out = self.plot_dir / f"optimal8_priority_score_readable_{stamp}.png"
        fig.savefig(out, dpi=160)
        plt.close(fig)
        return out

    def _plot_precision_recall(self, df: pd.DataFrame, stamp: str) -> Path:
        fig, ax = plt.subplots(figsize=(12, 6))
        x = np.arange(len(df))
        width = 0.36
        ax.bar(x - width / 2, df["precision"] * 100, width, label="Precision(%)", color="#1d4ed8")
        ax.bar(x + width / 2, df["recall"] * 100, width, label="Recall(%)", color="#16a34a")
        ax.set_xticks(x)
        ax.set_xticklabels(df["symbol"])
        ax.set_ylim(0, 105)
        ax.set_ylabel("百分比（%）")
        ax.set_title("图2｜命中质量对比（Precision vs Recall）")
        for i, (p, r) in enumerate(zip(df["precision"] * 100, df["recall"] * 100)):
            ax.text(i - width / 2, p + 1.5, f"{p:.1f}", ha="center", fontsize=8)
            ax.text(i + width / 2, r + 1.5, f"{r:.1f}", ha="center", fontsize=8)
        ax.legend()
        ax.grid(axis="y", alpha=0.25)
        fig.tight_layout()
        out = self.plot_dir / f"optimal8_precision_recall_readable_{stamp}.png"
        fig.savefig(out, dpi=160)
        plt.close(fig)
        return out

    def _plot_signal_structure(self, df: pd.DataFrame, stamp: str) -> Path:
        fig, ax = plt.subplots(figsize=(12, 6))
        ax.bar(df["symbol"], df["true_positive"], label="TP", color="#16a34a")
        ax.bar(df["symbol"], df["false_positive"], bottom=df["true_positive"], label="FP", color="#ef4444")
        ax.set_title("图3｜信号结构（TP/FP）")
        ax.set_ylabel("次数")
        for i, (tp, fp) in enumerate(zip(df["true_positive"], df["false_positive"])):
            ax.text(i, tp + fp + 0.08, f"{int(tp)}/{int(fp)}", ha="center", fontsize=8)
        ax.legend()
        ax.grid(axis="y", alpha=0.25)
        fig.tight_layout()
        out = self.plot_dir / f"optimal8_signal_structure_readable_{stamp}.png"
        fig.savefig(out, dpi=160)
        plt.close(fig)
        return out

    def _plot_trade_quality(self, df: pd.DataFrame, stamp: str) -> Path:
        fig, ax = plt.subplots(figsize=(12, 6))
        x = np.arange(len(df))
        width = 0.36
        calmar = df.get("calmar_ratio", pd.Series([0.0] * len(df))).astype(float)
        excess = df.get("annualized_excess_return", pd.Series([0.0] * len(df))).astype(float) * 100.0
        ax.bar(x - width / 2, calmar, width, label="Calmar", color="#1d4ed8")
        ax.bar(x + width / 2, excess, width, label="Annualized Excess(%)", color="#16a34a")
        ax.set_xticks(x)
        ax.set_xticklabels(df["symbol"])
        ax.set_title("图2｜交易质量对比（Calmar vs 年化超额）")
        for i, (c_val, e_val) in enumerate(zip(calmar, excess)):
            ax.text(i - width / 2, c_val + 0.03, f"{c_val:.2f}", ha="center", fontsize=8)
            ax.text(i + width / 2, e_val + 0.30, f"{e_val:.1f}", ha="center", fontsize=8)
        ax.legend()
        ax.grid(axis="y", alpha=0.25)
        fig.tight_layout()
        out = self.plot_dir / f"optimal8_trade_quality_readable_{stamp}.png"
        fig.savefig(out, dpi=160)
        plt.close(fig)
        return out

    def _plot_drawdown_trade_count(self, df: pd.DataFrame, stamp: str) -> Path:
        fig, ax1 = plt.subplots(figsize=(12, 6))
        trade_count = df.get("trade_count", pd.Series([0] * len(df))).astype(float)
        max_drawdown = df.get("max_drawdown", pd.Series([0.0] * len(df))).astype(float) * 100.0
        ax1.bar(df["symbol"], trade_count, color="#2563eb", alpha=0.78)
        ax1.set_ylabel("trade_count", color="#2563eb")
        ax1.tick_params(axis="y", labelcolor="#2563eb")
        ax1.set_title("图3｜交易结构（交易次数 vs 最大回撤）")
        ax1.grid(axis="y", alpha=0.2)
        ax2 = ax1.twinx()
        ax2.plot(df["symbol"], max_drawdown, color="#dc2626", marker="o", linewidth=2)
        ax2.set_ylabel("max_drawdown(%)", color="#dc2626")
        ax2.tick_params(axis="y", labelcolor="#dc2626")
        fig.tight_layout()
        out = self.plot_dir / f"optimal8_trade_structure_readable_{stamp}.png"
        fig.savefig(out, dpi=160)
        plt.close(fig)
        return out

    def _plot_param_profile(self, df: pd.DataFrame, stamp: str) -> Path:
        fig, ax1 = plt.subplots(figsize=(12, 6))
        ax1.bar(df["symbol"], df["step"], color="#7c3aed", alpha=0.78)
        ax1.set_ylabel("step", color="#7c3aed")
        ax1.tick_params(axis="y", labelcolor="#7c3aed")
        ax1.set_title("图4｜参数画像（step 与窗口数量）")
        ax1.grid(axis="y", alpha=0.2)
        ax2 = ax1.twinx()
        ax2.plot(df["symbol"], df["window_count"], color="#f97316", marker="o", linewidth=2)
        ax2.set_ylabel("window_count", color="#f97316")
        ax2.tick_params(axis="y", labelcolor="#f97316")
        fig.tight_layout()
        out = self.plot_dir / f"optimal8_param_profile_readable_{stamp}.png"
        fig.savefig(out, dpi=160)
        plt.close(fig)
        return out

    def _write_markdown(self, df: pd.DataFrame, charts, output_stem: str, stamp: str) -> Path:
        d = df.copy()
        for c in ["precision", "recall", "false_positive_rate", "annualized_excess_return", "max_drawdown"]:
            if c in d.columns:
                d[c] = (d[c].astype(float) * 100).map(lambda x: f"{x:.1f}%")
        d["objective_score"] = d["objective_score"].map(lambda x: f"{x:.3f}")
        for c in ["step", "window_count", "signal_count", "true_positive", "false_positive", "trade_count"]:
            if c in d.columns:
                d[c] = d[c].astype(int)
        if "calmar_ratio" in d.columns:
            d["calmar_ratio"] = d["calmar_ratio"].map(lambda x: f"{float(x):.2f}")
        if "turnover_rate" in d.columns:
            d["turnover_rate"] = (d["turnover_rate"].astype(float) * 100).map(lambda x: f"{x:.1f}%")
        if "whipsaw_rate" in d.columns:
            d["whipsaw_rate"] = (d["whipsaw_rate"].astype(float) * 100).map(lambda x: f"{x:.1f}%")

        detail_columns = [
            "symbol",
            "risk_band",
            "suggest_position",
            "objective_score",
            "annualized_excess_return",
            "calmar_ratio",
            "max_drawdown",
            "trade_count",
            "turnover_rate",
            "whipsaw_rate",
            "precision",
            "recall",
            "false_positive_rate",
            "signal_count",
            "true_positive",
            "false_positive",
            "step",
            "window_count",
        ]
        detail_columns = [column for column in detail_columns if column in d.columns]

        report = self.report_dir / f"{output_stem}_{stamp}.md"
        lines = [
            "# 8指数风控结果可读报告（优化版）",
            "",
            f"- 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "- 读取模式: `optimal_yaml`（已按指数生效）",
            "",
            "## 阅读顺序（30秒）",
            "",
            "1. 先看图1确定风险优先级。",
            "2. 再看图2判断误报/漏报平衡。",
            "3. 图3确认信号结构是否健康。",
            "4. 图4用于参数复盘与稳定性观察。",
            "",
            "## 执行摘要",
            "",
            f"- DANGER: {', '.join(df[df['risk_band'] == 'DANGER']['symbol'].tolist()) or '无'}",
            f"- Warning: {', '.join(df[df['risk_band'] == 'Warning']['symbol'].tolist()) or '无'}",
            f"- Watch: {', '.join(df[df['risk_band'] == 'Watch']['symbol'].tolist()) or '无'}",
            "",
            "## 图表",
            "",
            f"### 图1 风险优先级\n![图1](../plots/{charts[0].name})",
            "",
            f"### 图2 命中质量\n![图2](../plots/{charts[1].name})",
            "",
            f"### 图3 信号结构\n![图3](../plots/{charts[2].name})",
            "",
            f"### 图4 参数画像\n![图4](../plots/{charts[3].name})",
            "",
            "## 指数明细（用于执行）",
            "",
            d[detail_columns].to_markdown(index=False),
            "",
            "## 输出可读性优化点",
            "",
            "- 所有指标统一百分比展示，降低换算负担。",
            "- 图题和字段中文化，减少术语跳转。",
            "- 指标、图和行动建议保持同一排序。",
        ]
        report.write_text("\n".join(lines), encoding="utf-8")
        return report
