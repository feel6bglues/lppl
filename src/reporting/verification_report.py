# -*- coding: utf-8 -*-
import os
from datetime import datetime
from typing import Dict, List, Optional

import pandas as pd


class VerificationReportGenerator:
    def __init__(self, output_dir: str):
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)

    def generate_markdown_report(
        self,
        summary_df: pd.DataFrame,
        use_ensemble: bool,
        plot_paths: Optional[Dict[str, List[str]]] = None,
        filename: Optional[str] = None,
    ) -> str:
        mode_label = "Ensemble 多窗口共识" if use_ensemble else "单窗口独立"
        filename = filename or (
            "verification_report_ensemble.md" if use_ensemble else "verification_report_single_window.md"
        )
        file_path = os.path.join(self.output_dir, filename)
        plot_paths = plot_paths or {}

        total = len(summary_df)
        detected = int(summary_df["detected"].sum()) if "detected" in summary_df.columns else 0
        detection_rate = detected / total * 100 if total > 0 else 0

        lines = [
            "# LPPL 验证报告",
            "",
            f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"**验证模式**: {mode_label}",
            "",
            "## 一、总体结果",
            "",
            f"- 总样本数: {total}",
            f"- 检测到预警: {detected}",
            f"- 检测率: {detection_rate:.1f}%",
            "",
            "## 二、汇总表",
            "",
        ]

        summary_for_report = summary_df.drop(columns=["timeline"], errors="ignore")
        lines.append(summary_for_report.to_markdown(index=False))
        lines.extend(["", "## 三、图片输出", ""])

        if not plot_paths:
            lines.append("暂无图片输出")
        else:
            for section, paths in plot_paths.items():
                if not paths:
                    continue
                lines.append(f"### {section}")
                lines.append("")
                for path in paths:
                    rel_path = os.path.relpath(path, self.output_dir)
                    lines.append(f"![{os.path.basename(path)}]({rel_path})")
                lines.append("")

        with open(file_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

        return file_path

    def generate_html_report(
        self,
        summary_df: pd.DataFrame,
        use_ensemble: bool,
        plot_paths: Optional[Dict[str, List[str]]] = None,
        filename: Optional[str] = None,
    ) -> str:
        mode_label = "Ensemble 多窗口共识" if use_ensemble else "单窗口独立"
        filename = filename or (
            "verification_report_ensemble.html" if use_ensemble else "verification_report_single_window.html"
        )
        file_path = os.path.join(self.output_dir, filename)
        plot_paths = plot_paths or {}

        total = len(summary_df)
        detected = int(summary_df["detected"].sum()) if "detected" in summary_df.columns else 0
        detection_rate = detected / total * 100 if total > 0 else 0

        cards_html = []
        for _, row in summary_df.iterrows():
            cards_html.append(
                f"""
                <div class="card">
                    <div class="card-title">{row.get('name', '')} ({row.get('symbol', '')})</div>
                    <div class="card-grid">
                        <div><span>Detected</span><strong>{row.get('detected', '')}</strong></div>
                        <div><span>Lead Days</span><strong>{row.get('first_danger_days', '')}</strong></div>
                        <div><span>R²</span><strong>{row.get('first_danger_r2', '')}</strong></div>
                    </div>
                </div>
                """
            )

        plots_html = []
        for section, paths in plot_paths.items():
            if not paths:
                continue
            images = []
            for path in paths:
                rel_path = os.path.relpath(path, self.output_dir)
                images.append(
                    f"""
                    <figure class="plot-item">
                        <img src="{rel_path}" alt="{os.path.basename(path)}" />
                        <figcaption>{os.path.basename(path)}</figcaption>
                    </figure>
                    """
                )
            plots_html.append(
                f"""
                <section class="plot-section">
                    <h2>{section}</h2>
                    <div class="plot-grid">
                        {''.join(images)}
                    </div>
                </section>
                """
            )

        html = f"""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>LPPL 验证报告</title>
  <style>
    body {{
      font-family: "Segoe UI", "PingFang SC", sans-serif;
      margin: 0;
      padding: 32px;
      background: #f8fafc;
      color: #0f172a;
    }}
    .header {{
      background: linear-gradient(135deg, #0f172a, #1d4ed8);
      color: white;
      padding: 24px;
      border-radius: 16px;
      margin-bottom: 24px;
    }}
    .stats {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 16px;
      margin: 24px 0;
    }}
    .stat, .card {{
      background: white;
      border-radius: 14px;
      padding: 18px;
      box-shadow: 0 8px 24px rgba(15, 23, 42, 0.08);
    }}
    .card-title {{
      font-weight: 700;
      margin-bottom: 12px;
    }}
    .card-grid {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 12px;
    }}
    .card-grid span {{
      display: block;
      font-size: 12px;
      color: #64748b;
    }}
    .card-grid strong {{
      font-size: 18px;
    }}
    .plot-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
      gap: 20px;
    }}
    .plot-item {{
      background: white;
      border-radius: 14px;
      padding: 12px;
      box-shadow: 0 8px 24px rgba(15, 23, 42, 0.08);
    }}
    .plot-item img {{
      width: 100%;
      border-radius: 10px;
      display: block;
    }}
    figcaption {{
      margin-top: 8px;
      font-size: 13px;
      color: #475569;
    }}
  </style>
</head>
<body>
  <div class="header">
    <h1>LPPL 验证报告</h1>
    <p>模式: {mode_label}</p>
    <p>生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
  </div>

  <div class="stats">
    <div class="stat"><div>总样本数</div><strong>{total}</strong></div>
    <div class="stat"><div>检测到预警</div><strong>{detected}</strong></div>
    <div class="stat"><div>检测率</div><strong>{detection_rate:.1f}%</strong></div>
  </div>

  <section>
    <h2>案例卡片</h2>
    {''.join(cards_html)}
  </section>

  {''.join(plots_html) if plots_html else '<p>暂无图片输出</p>'}
</body>
</html>
        """

        with open(file_path, "w", encoding="utf-8") as f:
            f.write(html)

        return file_path
