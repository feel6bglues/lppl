# -*- coding: utf-8 -*-
import os
from typing import Dict, Optional

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from src.constants import PLOTS_OUTPUT_DIR


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
        ax.plot(timeline_df["date"], timeline_df["price"], color="#111827", linewidth=1.5, label="Price")

        if "is_warning" in timeline_df.columns:
            warning_df = timeline_df[timeline_df["is_warning"]]
            if not warning_df.empty:
                ax.scatter(warning_df["date"], warning_df["price"], color="#f59e0b", s=25, label="Warning")

        if "is_danger" in timeline_df.columns:
            danger_df = timeline_df[timeline_df["is_danger"]]
            if not danger_df.empty:
                ax.scatter(danger_df["date"], danger_df["price"], color="#dc2626", s=35, label="Danger")

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

        filename = filename or f"{metadata['symbol'].replace('.', '_')}_{metadata['mode']}_{metadata['peak_date']}_timeline.png"
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
        ax.plot(timeline_df["date"], timeline_df["consensus_rate"], color="#059669", linewidth=2, label="Consensus Rate")
        ax.axhline(consensus_threshold, color="#dc2626", linestyle="--", linewidth=1.2, label="Consensus Threshold")

        if "valid_windows" in timeline_df.columns:
            ax2 = ax.twinx()
            ax2.bar(timeline_df["date"], timeline_df["valid_windows"], alpha=0.15, color="#2563eb", label="Valid Windows")
            ax2.set_ylabel("Valid Windows")

        ax.set_title(f"{metadata['name']} {metadata['peak_date']} Ensemble Consensus")
        ax.set_xlabel("Date")
        ax.set_ylabel("Consensus Rate")
        ax.grid(True, alpha=0.25)
        ax.legend(loc="upper left")

        filename = filename or f"{metadata['symbol'].replace('.', '_')}_{metadata['mode']}_{metadata['peak_date']}_consensus.png"
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

        filename = filename or f"{metadata['symbol'].replace('.', '_')}_{metadata['mode']}_{metadata['peak_date']}_dispersion.png"
        return self._save_figure(fig, filename)

    def generate_summary_statistics_plot(
        self,
        summary_df: pd.DataFrame,
        filename: str = "verification_summary.png",
    ) -> str:
        summary_df = summary_df.copy()
        detect_rate = summary_df.groupby("name")["detected"].mean().sort_values(ascending=False) * 100
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
            axes[1].boxplot(boxplot_data, labels=labels)
            axes[1].set_title("Lead Days Distribution")
            axes[1].set_ylabel("Lead Days")
            axes[1].tick_params(axis="x", rotation=25)
            axes[1].grid(True, axis="y", alpha=0.25)
        else:
            axes[1].text(0.5, 0.5, "No detected samples", ha="center", va="center")
            axes[1].set_axis_off()

        return self._save_figure(fig, filename)
