# -*- coding: utf-8 -*-
import os
from datetime import datetime
from typing import Dict, List, Optional

import pandas as pd


class InvestmentReportGenerator:
    def __init__(self, output_dir: str):
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)

    def generate_markdown_report(
        self,
        summary_df: pd.DataFrame,
        plot_paths: Optional[Dict[str, List[str]]] = None,
        filename: str = "investment_analysis_report.md",
    ) -> str:
        file_path = os.path.join(self.output_dir, filename)
        plot_paths = plot_paths or {}

        lines = [
            "# 指数投资分析报告",
            "",
            f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "## 一、策略摘要",
            "",
        ]

        for _, row in summary_df.iterrows():
            lines.extend(
                [
                    f"### {row.get('name', '')} ({row.get('symbol', '')})",
                    "",
                    f"- 回测区间: {row.get('start_date', '')} ~ {row.get('end_date', '')}",
                    f"- 最新信号: {row.get('latest_signal', '')}",
                    f"- 最新动作: {row.get('latest_action', '')}",
                    f"- 最终净值: {row.get('final_nav', 0.0):.4f}",
                    f"- 策略收益: {row.get('total_return', 0.0):.2%}",
                    f"- 基准收益: {row.get('benchmark_return', 0.0):.2%}",
                    f"- 最大回撤: {row.get('max_drawdown', 0.0):.2%}",
                    f"- 交易次数: {int(row.get('trade_count', 0))}",
                    "",
                ]
            )

        lines.extend(["## 二、汇总表", "", summary_df.to_markdown(index=False), "", "## 三、图表", ""])
        if not plot_paths:
            lines.append("暂无图表输出")
        else:
            for section, paths in plot_paths.items():
                lines.extend([f"### {section}", ""])
                for path in paths:
                    rel_path = os.path.relpath(path, self.output_dir)
                    lines.append(f"![{os.path.basename(path)}]({rel_path})")
                lines.append("")

        with open(file_path, "w", encoding="utf-8") as handle:
            handle.write("\n".join(lines))

        return file_path

    def generate_html_report(
        self,
        summary_df: pd.DataFrame,
        plot_paths: Optional[Dict[str, List[str]]] = None,
        filename: str = "investment_analysis_report.html",
    ) -> str:
        file_path = os.path.join(self.output_dir, filename)
        plot_paths = plot_paths or {}

        cards = []
        for _, row in summary_df.iterrows():
            cards.append(
                f"""
                <div class="card">
                  <h2>{row.get('name', '')} ({row.get('symbol', '')})</h2>
                  <div class="grid">
                    <div><span>回测区间</span><strong>{row.get('start_date', '')} ~ {row.get('end_date', '')}</strong></div>
                    <div><span>最新信号</span><strong>{row.get('latest_signal', '')}</strong></div>
                    <div><span>最新动作</span><strong>{row.get('latest_action', '')}</strong></div>
                    <div><span>最终净值</span><strong>{row.get('final_nav', 0.0):.4f}</strong></div>
                    <div><span>策略收益</span><strong>{row.get('total_return', 0.0):.2%}</strong></div>
                    <div><span>最大回撤</span><strong>{row.get('max_drawdown', 0.0):.2%}</strong></div>
                  </div>
                </div>
                """
            )

        sections = []
        for section, paths in plot_paths.items():
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
            sections.append(
                f"""
                <section>
                  <h2>{section}</h2>
                  <div class="plot-grid">{''.join(images)}</div>
                </section>
                """
            )

        html = f"""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>指数投资分析报告</title>
  <style>
    body {{
      font-family: "Segoe UI", "PingFang SC", sans-serif;
      background: #f8fafc;
      color: #0f172a;
      margin: 0;
      padding: 32px;
    }}
    .hero {{
      background: linear-gradient(135deg, #0f172a, #1d4ed8);
      color: white;
      border-radius: 18px;
      padding: 24px;
      margin-bottom: 24px;
    }}
    .card {{
      background: white;
      border-radius: 16px;
      padding: 20px;
      box-shadow: 0 8px 24px rgba(15, 23, 42, 0.08);
      margin-bottom: 16px;
    }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 12px;
    }}
    span {{
      display: block;
      font-size: 12px;
      color: #64748b;
    }}
    strong {{
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
    }}
  </style>
</head>
<body>
  <div class="hero">
    <h1>指数投资分析报告</h1>
    <p>生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
  </div>
  {''.join(cards)}
  {''.join(sections) if sections else '<p>暂无图表输出</p>'}
</body>
</html>
        """

        with open(file_path, "w", encoding="utf-8") as handle:
            handle.write(html)

        return file_path
