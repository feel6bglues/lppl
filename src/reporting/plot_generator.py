# -*- coding: utf-8 -*-
import os
from typing import Dict, Optional

os.environ["MPLCONFIGDIR"] = "/tmp/matplotlib"

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib import font_manager
from matplotlib.patches import Rectangle

from src.constants import PLOTS_OUTPUT_DIR


def _configure_matplotlib_fonts() -> None:
    candidates = [
        "Microsoft YaHei",
        "Droid Sans Fallback",
        "AR PL UMing CN",
        "AR PL UKai CN",
    ]
    available = []
    for font_name in candidates:
        try:
            font_manager.findfont(font_name, fallback_to_default=False)
            available.append(font_name)
        except ValueError:
            continue

    if available:
        plt.rcParams["font.family"] = "sans-serif"
        plt.rcParams["font.sans-serif"] = available + list(plt.rcParams.get("font.sans-serif", []))
    plt.rcParams["axes.unicode_minus"] = False


_configure_matplotlib_fonts()


class PlotGenerator:
    def __init__(self, output_dir: Optional[str] = None):
        self.output_dir = output_dir or PLOTS_OUTPUT_DIR
        os.makedirs(self.output_dir, exist_ok=True)

    def _save_figure(self, fig: plt.Figure, filename: str) -> str:
        file_path = os.path.join(self.output_dir, filename)
        fig.tight_layout()
        fig.savefig(file_path, dpi=150, bbox_inches="tight")
        plt.close(fig)
        return file_path

    def generate_price_timeline_plot(
        self,
        timeline_df: pd.DataFrame,
        metadata: Dict[str, str],
        filename: Optional[str] = None,
    ) -> str:
        timeline_df = timeline_df.copy()
        timeline_df["date"] = pd.to_datetime(timeline_df["date"])

        fig, ax = plt.subplots(figsize=(12, 6))
        ax.plot(
            timeline_df["date"], timeline_df["price"], color="#111827", linewidth=1.5, label="Price"
        )

        if "is_warning" in timeline_df.columns:
            warning_df = timeline_df[timeline_df["is_warning"]]
            if not warning_df.empty:
                ax.scatter(
                    warning_df["date"], warning_df["price"], color="#f59e0b", s=25, label="Warning"
                )

        if "is_danger" in timeline_df.columns:
            danger_df = timeline_df[timeline_df["is_danger"]]
            if not danger_df.empty:
                ax.scatter(
                    danger_df["date"], danger_df["price"], color="#dc2626", s=35, label="Danger"
                )

        peak_date = pd.to_datetime(metadata["peak_date"])
        ax.axvline(peak_date, color="#2563eb", linestyle="--", linewidth=1.2, label="Peak Date")

        first_danger_days = metadata.get("first_danger_days")
        if first_danger_days is not None and "is_danger" in timeline_df.columns:
            danger_df = timeline_df[timeline_df["is_danger"]]
            if not danger_df.empty:
                first_danger = danger_df.sort_values("date").iloc[0]
                ax.scatter(
                    [first_danger["date"]],
                    [first_danger["price"]],
                    color="#7f1d1d",
                    s=80,
                    marker="*",
                    label="First Danger",
                )

        ax.set_title(f"{metadata['name']} {metadata['peak_date']} Price Timeline")
        ax.set_xlabel("Date")
        ax.set_ylabel("Price")
        ax.grid(True, alpha=0.25)
        ax.legend()

        filename = (
            filename
            or f"{metadata['symbol'].replace('.', '_')}_{metadata['mode']}_{metadata['peak_date']}_timeline.png"
        )
        return self._save_figure(fig, filename)

    def generate_consensus_plot(
        self,
        timeline_df: pd.DataFrame,
        metadata: Dict[str, str],
        consensus_threshold: float,
        filename: Optional[str] = None,
    ) -> str:
        timeline_df = timeline_df.copy()
        timeline_df["date"] = pd.to_datetime(timeline_df["date"])

        fig, ax = plt.subplots(figsize=(12, 5))
        ax.plot(
            timeline_df["date"],
            timeline_df["consensus_rate"],
            color="#059669",
            linewidth=2,
            label="Consensus Rate",
        )
        ax.axhline(
            consensus_threshold,
            color="#dc2626",
            linestyle="--",
            linewidth=1.2,
            label="Consensus Threshold",
        )

        if "valid_windows" in timeline_df.columns:
            ax2 = ax.twinx()
            ax2.bar(
                timeline_df["date"],
                timeline_df["valid_windows"],
                alpha=0.15,
                color="#2563eb",
                label="Valid Windows",
            )
            ax2.set_ylabel("Valid Windows")

        ax.set_title(f"{metadata['name']} {metadata['peak_date']} Ensemble Consensus")
        ax.set_xlabel("Date")
        ax.set_ylabel("Consensus Rate")
        ax.grid(True, alpha=0.25)
        ax.legend(loc="upper left")

        filename = (
            filename
            or f"{metadata['symbol'].replace('.', '_')}_{metadata['mode']}_{metadata['peak_date']}_consensus.png"
        )
        return self._save_figure(fig, filename)

    def generate_crash_dispersion_plot(
        self,
        timeline_df: pd.DataFrame,
        metadata: Dict[str, str],
        filename: Optional[str] = None,
    ) -> str:
        timeline_df = timeline_df.copy()
        timeline_df["date"] = pd.to_datetime(timeline_df["date"])

        fig, axes = plt.subplots(2, 1, figsize=(12, 8), sharex=True)
        axes[0].plot(
            timeline_df["date"],
            timeline_df["predicted_crash_days"],
            color="#7c3aed",
            linewidth=1.8,
            label="Predicted Crash Days",
        )
        axes[0].set_ylabel("Crash Days")
        axes[0].grid(True, alpha=0.25)
        axes[0].legend()

        axes[1].fill_between(
            timeline_df["date"],
            0,
            timeline_df["tc_std"],
            color="#f97316",
            alpha=0.35,
            label="tc std",
        )
        axes[1].set_ylabel("tc std")
        axes[1].set_xlabel("Date")
        axes[1].grid(True, alpha=0.25)
        axes[1].legend()

        fig.suptitle(f"{metadata['name']} {metadata['peak_date']} Crash Dispersion")

        filename = (
            filename
            or f"{metadata['symbol'].replace('.', '_')}_{metadata['mode']}_{metadata['peak_date']}_dispersion.png"
        )
        return self._save_figure(fig, filename)

    def generate_summary_statistics_plot(
        self,
        summary_df: pd.DataFrame,
        filename: str = "verification_summary.png",
    ) -> str:
        summary_df = summary_df.copy()
        detect_rate = (
            summary_df.groupby("name")["detected"].mean().sort_values(ascending=False) * 100
        )
        lead_days = (
            summary_df[summary_df["detected"]]
            .groupby("name")["first_danger_days"]
            .apply(lambda s: (-1 * s.dropna()).tolist())
        )

        fig, axes = plt.subplots(2, 1, figsize=(12, 9))

        detect_rate.plot(kind="bar", color="#2563eb", ax=axes[0])
        axes[0].set_title("Detection Rate by Index")
        axes[0].set_ylabel("Detection Rate (%)")
        axes[0].grid(True, axis="y", alpha=0.25)

        boxplot_data = [values for values in lead_days.tolist() if values]
        labels = [name for name, values in lead_days.items() if values]
        if boxplot_data:
            axes[1].boxplot(boxplot_data, tick_labels=labels)
            axes[1].set_title("Lead Days Distribution")
            axes[1].set_ylabel("Lead Days")
            axes[1].tick_params(axis="x", rotation=25)
            axes[1].grid(True, axis="y", alpha=0.25)
        else:
            axes[1].text(0.5, 0.5, "No detected samples", ha="center", va="center")
            axes[1].set_axis_off()

        return self._save_figure(fig, filename)

    def _plot_candlesticks(self, ax: plt.Axes, price_df: pd.DataFrame) -> None:
        candle_width = 0.6
        for row in price_df.itertuples(index=False):
            x_value = mdates.date2num(pd.to_datetime(row.date))
            open_price = float(row.open)
            high_price = float(row.high)
            low_price = float(row.low)
            close_price = float(row.close)
            color = "#16a34a" if close_price >= open_price else "#dc2626"

            ax.vlines(x_value, low_price, high_price, color=color, linewidth=1.0, alpha=0.9)

            lower = min(open_price, close_price)
            body_height = abs(close_price - open_price)
            if body_height < 1e-8:
                body_height = 0.02
            ax.add_patch(
                Rectangle(
                    (x_value - candle_width / 2.0, lower),
                    candle_width,
                    body_height,
                    facecolor=color,
                    edgecolor=color,
                    alpha=0.85,
                )
            )

    def generate_strategy_overview_plot(
        self,
        equity_df: pd.DataFrame,
        trades_df: pd.DataFrame,
        metadata: Dict[str, str],
        filename: Optional[str] = None,
    ) -> str:
        equity_df = equity_df.copy()
        equity_df["date"] = pd.to_datetime(equity_df["date"])
        trades_df = trades_df.copy()
        if "trade_type" not in trades_df.columns:
            trades_df = pd.DataFrame(columns=["date", "trade_type"])
        if not trades_df.empty and "date" in trades_df.columns:
            trades_df["date"] = pd.to_datetime(trades_df["date"])

        fig, axes = plt.subplots(
            2, 1, figsize=(14, 10), sharex=True, gridspec_kw={"height_ratios": [1, 1.2]}
        )

        axes[0].plot(
            equity_df["date"],
            equity_df["strategy_nav"],
            color="#1d4ed8",
            linewidth=2.0,
            label="Strategy NAV",
        )
        axes[0].plot(
            equity_df["date"],
            equity_df["benchmark_nav"],
            color="#64748b",
            linewidth=1.8,
            linestyle="--",
            label="Benchmark NAV",
        )
        axes[0].set_ylabel("NAV")
        axes[0].set_title(
            f"{metadata['name']} ({metadata['symbol']}) | "
            f"{metadata['start_date']} ~ {metadata['end_date']} | "
            f"收益 {metadata['total_return']:.2%} | "
            f"最大回撤 {metadata['max_drawdown']:.2%}"
        )
        axes[0].grid(True, alpha=0.25)
        axes[0].legend(loc="upper left")

        self._plot_candlesticks(axes[1], equity_df[["date", "open", "high", "low", "close"]])

        marker_styles = {
            "buy": ("^", "#16a34a", "Buy"),
            "add": ("^", "#0ea5e9", "Add"),
            "reduce": ("v", "#f59e0b", "Reduce"),
            "sell": ("v", "#dc2626", "Sell"),
        }
        added_labels = set()
        for trade_type, (marker, color, label) in marker_styles.items():
            trade_points = trades_df[trades_df["trade_type"] == trade_type]
            if trade_points.empty:
                continue

            merged = trade_points.merge(
                equity_df[["date", "open", "high", "low", "close"]],
                on="date",
                how="left",
            )
            scatter_label = label if label not in added_labels else None
            axes[1].scatter(
                merged["date"],
                merged["close"],
                marker=marker,
                color=color,
                s=80,
                label=scatter_label,
                zorder=5,
            )
            added_labels.add(label)

        axes[1].set_ylabel("Price")
        axes[1].set_xlabel("Date")
        axes[1].grid(True, alpha=0.2)
        if added_labels:
            axes[1].legend(loc="upper left")
        axes[1].xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d"))
        fig.autofmt_xdate()

        filename = filename or f"{metadata['symbol'].replace('.', '_')}_strategy_overview.png"
        return self._save_figure(fig, filename)

    def generate_strategy_drawdown_plot(
        self,
        equity_df: pd.DataFrame,
        metadata: Dict[str, str],
        filename: Optional[str] = None,
    ) -> str:
        equity_df = equity_df.copy()
        equity_df["date"] = pd.to_datetime(equity_df["date"])

        fig, ax = plt.subplots(figsize=(14, 5))
        ax.fill_between(equity_df["date"], equity_df["drawdown"], 0, color="#dc2626", alpha=0.35)
        ax.plot(equity_df["date"], equity_df["drawdown"], color="#b91c1c", linewidth=1.8)

        trough_idx = equity_df["drawdown"].idxmin()
        peak_idx = equity_df.loc[:trough_idx, "strategy_nav"].idxmax()
        ax.axvspan(
            equity_df.loc[peak_idx, "date"],
            equity_df.loc[trough_idx, "date"],
            color="#fca5a5",
            alpha=0.18,
        )
        ax.scatter(
            [equity_df.loc[trough_idx, "date"]],
            [equity_df.loc[trough_idx, "drawdown"]],
            color="#7f1d1d",
            s=60,
            zorder=5,
        )

        ax.set_title(f"{metadata['name']} ({metadata['symbol']}) 回撤曲线")
        ax.set_ylabel("Drawdown")
        ax.set_xlabel("Date")
        ax.grid(True, alpha=0.25)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d"))
        fig.autofmt_xdate()

        filename = filename or f"{metadata['symbol'].replace('.', '_')}_strategy_drawdown.png"
        return self._save_figure(fig, filename)
