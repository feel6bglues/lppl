# -*- coding: utf-8 -*-
"""
威科夫报告生成器 - Markdown/HTML/CSV/JSON 报告输出

遵循 SPEC_WYCKOFF_OUTPUT_SCHEMA Section 4-5 规范
"""

import json
import logging
import os
from datetime import datetime
from typing import List, Optional

import pandas as pd

from src.wyckoff.models import (
    AnalysisResult,
    AnalysisState,
    ImageEvidenceBundle,
)

logger = logging.getLogger(__name__)


class WyckoffReportGenerator:
    """
    威科夫报告生成器 - 生成 Markdown/HTML/CSV/JSON 报告

    SPEC_WYCKOFF_OUTPUT_SCHEMA Section 5 映射:
    - Step 0: BC 定位
    - Step 1: 大局观与阶段
    - Step 2: 努力与结果
    - Step 3: Phase C 终极测试
    - Step 3.5: 反事实压力测试
    - Step 4: T+1 与盈亏比
    - Step 5: 交易计划
    - 附录 A: 连续性追踪
    - 附录 B: 视觉证据摘要
    """

    def __init__(self, output_dir: str):
        self.output_dir = output_dir
        self.raw_dir = os.path.join(output_dir, "raw")
        self.reports_dir = os.path.join(output_dir, "reports")
        self.summary_dir = os.path.join(output_dir, "summary")
        self.evidence_dir = os.path.join(output_dir, "evidence")

        for dir_path in [self.raw_dir, self.reports_dir, self.summary_dir, self.evidence_dir]:
            os.makedirs(dir_path, exist_ok=True)

    def generate_markdown_report(
        self,
        result: AnalysisResult,
        state: Optional[AnalysisState] = None,
        image_bundle: Optional[ImageEvidenceBundle] = None,
    ) -> str:
        """生成 Markdown 报告"""
        report_lines = []

        # 标题
        report_lines.append(f"# 威科夫多模态分析报告 - {result.symbol}")
        report_lines.append(f"\n**分析日期**: {result.analysis_date}")
        report_lines.append(f"**资产类型**: {result.asset_type}")
        report_lines.append(f"**输入来源**: {', '.join(result.input_sources)}")
        report_lines.append("")

        # Step 0: BC 定位
        report_lines.append("## Step 0: BC 定位")
        report_lines.append(f"- **BC 是否找到**: {'是' if result.bc_found else '否'}")
        if result.bc_found:
            report_lines.append(f"- **置信度**: {result.confidence}")
        else:
            report_lines.append(f"- **放弃原因**: {result.abandon_reason}")
        report_lines.append("")

        # Step 1: 大局观与阶段
        report_lines.append("## Step 1: 大局观与阶段")
        report_lines.append(f"- **当前阶段**: {result.phase}")
        report_lines.append(f"- **时间周期**: {', '.join(result.timeframes_seen)}")
        report_lines.append(f"- **上边界**: {result.boundary_upper_zone}")
        report_lines.append(f"- **下边界**: {result.boundary_lower_zone}")
        report_lines.append("")

        # Step 2: 努力与结果
        report_lines.append("## Step 2: 努力与结果")
        report_lines.append(f"- **量能标签**: {result.volume_profile_label}")
        report_lines.append(f"- **微观行为**: {result.micro_action}")
        if result.conflicts:
            report_lines.append(f"- **冲突**: {', '.join(result.conflicts)}")
        report_lines.append("")

        # Step 3: Phase C 终极测试
        report_lines.append("## Step 3: Phase C 终极测试")
        report_lines.append(f"- **Spring 检测**: {'是' if result.spring_detected else '否'}")
        report_lines.append(f"- **UTAD 检测**: {'是' if result.utad_detected else '否'}")
        report_lines.append(f"- **T+1 风险**: {result.t1_risk_assessment}")
        report_lines.append("")

        # Step 3.5: 反事实压力测试
        report_lines.append("## Step 3.5: 反事实压力测试")
        report_lines.append(f"- **反证摘要**: {result.counterfactual_summary}")
        report_lines.append(f"- **一致性评分**: {result.consistency_score}")
        report_lines.append("")

        # Step 4: T+1 与盈亏比
        report_lines.append("## Step 4: T+1 与盈亏比")
        report_lines.append(f"- **R:R 评估**: {result.rr_assessment}")
        report_lines.append(f"- **止损位**: {result.invalidation}")
        report_lines.append(f"- **目标位**: {result.target_1}")
        report_lines.append("")

        # Step 5: 交易计划
        report_lines.append("## Step 5: 交易计划")
        report_lines.append(f"- **当前评估**: {result.micro_action}")
        report_lines.append(f"- **方向**: {result.decision}")
        report_lines.append(f"- **触发条件**: {result.trigger}")
        report_lines.append(f"- **止损**: {result.invalidation}")
        report_lines.append(f"- **目标**: {result.target_1}")
        report_lines.append(f"- **置信度**: {result.confidence}")
        if result.abandon_reason:
            report_lines.append(f"- **放弃原因**: {result.abandon_reason}")
        report_lines.append("")

        # 附录 A: 连续性追踪
        report_lines.append("## 附录 A: 连续性追踪")
        if state:
            report_lines.append(f"- **上次阶段**: {state.last_phase}")
            report_lines.append(f"- **上次决策**: {state.last_decision}")
            report_lines.append(f"- **周线背景**: {result.weekly_context}")
            report_lines.append(f"- **盘中背景**: {result.intraday_context}")
        else:
            report_lines.append("*首次分析，无历史状态*")
        report_lines.append("")

        # 附录 B: 视觉证据摘要
        report_lines.append("## 附录 B: 视觉证据摘要")
        if image_bundle:
            report_lines.append(f"- **图像总数**: {image_bundle.manifest.total_count}")
            report_lines.append(f"- **可用图像**: {image_bundle.manifest.usable_count}")
            report_lines.append(f"- **整体质量**: {image_bundle.overall_image_quality}")
            report_lines.append(f"- **信任等级**: {image_bundle.trust_level}")
            report_lines.append(f"- **检测周期**: {', '.join(image_bundle.detected_timeframes)}")
        else:
            report_lines.append("*无图像数据*")
        report_lines.append("")

        report_text = "\n".join(report_lines)

        # 保存报告
        report_path = os.path.join(self.reports_dir, f"{result.symbol}_wyckoff_report.md")
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(report_text)

        logger.info(f"Markdown 报告已保存：{report_path}")
        return report_path

    def generate_html_report(
        self,
        result: AnalysisResult,
        state: Optional[AnalysisState] = None,
        image_bundle: Optional[ImageEvidenceBundle] = None,
    ) -> str:
        """生成 HTML 报告"""
        html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>威科夫多模态分析报告 - {result.symbol}</title>
    <style>
        body {{ font-family: Arial, sans-serif; max-width: 900px; margin: 0 auto; padding: 20px; }}
        h1 {{ color: #2c3e50; border-bottom: 2px solid #3498db; padding-bottom: 10px; }}
        h2 {{ color: #34495e; margin-top: 30px; }}
        .section {{ background: #f8f9fa; padding: 15px; margin: 15px 0; border-radius: 5px; }}
        .metric {{ display: inline-block; margin: 10px 20px; }}
        .metric-label {{ font-weight: bold; color: #7f8c8d; }}
        .metric-value {{ color: #2c3e50; font-size: 1.1em; }}
        .positive {{ color: #27ae60; }}
        .negative {{ color: #e74c3c; }}
        .neutral {{ color: #f39c12; }}
        table {{ width: 100%; border-collapse: collapse; margin: 15px 0; }}
        th, td {{ padding: 10px; text-align: left; border-bottom: 1px solid #ddd; }}
        th {{ background: #3498db; color: white; }}
    </style>
</head>
<body>
    <h1>威科夫多模态分析报告 - {result.symbol}</h1>
    <p><strong>分析日期</strong>: {result.analysis_date} | <strong>资产类型</strong>: {result.asset_type}</p>
    
    <div class="section">
        <h2>Step 0: BC 定位</h2>
        <div class="metric">
            <span class="metric-label">BC 是否找到:</span>
            <span class="metric-value {"positive" if result.bc_found else "negative"}">{"是" if result.bc_found else "否"}</span>
        </div>
        <div class="metric">
            <span class="metric-label">置信度:</span>
            <span class="metric-value">{result.confidence}</span>
        </div>
    </div>
    
    <div class="section">
        <h2>Step 1: 大局观与阶段</h2>
        <table>
            <tr><th>指标</th><th>值</th></tr>
            <tr><td>当前阶段</td><td>{result.phase}</td></tr>
            <tr><td>时间周期</td><td>{", ".join(result.timeframes_seen)}</td></tr>
            <tr><td>上边界</td><td>{result.boundary_upper_zone}</td></tr>
            <tr><td>下边界</td><td>{result.boundary_lower_zone}</td></tr>
        </table>
    </div>
    
    <div class="section">
        <h2>Step 2: 努力与结果</h2>
        <table>
            <tr><th>指标</th><th>值</th></tr>
            <tr><td>量能标签</td><td>{result.volume_profile_label}</td></tr>
            <tr><td>微观行为</td><td>{result.micro_action}</td></tr>
        </table>
    </div>
    
    <div class="section">
        <h2>Step 3: Phase C 终极测试</h2>
        <table>
            <tr><th>检测项</th><th>结果</th></tr>
            <tr><td>Spring</td><td class="{"positive" if result.spring_detected else "negative"}">{"是" if result.spring_detected else "否"}</td></tr>
            <tr><td>UTAD</td><td class="{"positive" if result.utad_detected else "negative"}">{"是" if result.utad_detected else "否"}</td></tr>
            <tr><td>T+1 风险</td><td>{result.t1_risk_assessment}</td></tr>
        </table>
    </div>
    
    <div class="section">
        <h2>Step 4: T+1 与盈亏比</h2>
        <table>
            <tr><th>指标</th><th>值</th></tr>
            <tr><td>R:R 评估</td><td class="{"positive" if result.rr_assessment == "excellent" else "neutral"}">{result.rr_assessment}</td></tr>
            <tr><td>止损位</td><td>{result.invalidation}</td></tr>
            <tr><td>目标位</td><td>{result.target_1}</td></tr>
        </table>
    </div>
    
    <div class="section">
        <h2>Step 5: 交易计划</h2>
        <table>
            <tr><th>字段</th><th>值</th></tr>
            <tr><td>当前评估</td><td>{result.micro_action}</td></tr>
            <tr><td>方向</td><td class="{"positive" if result.decision == "long_setup" else "negative"}">{result.decision}</td></tr>
            <tr><td>触发条件</td><td>{result.trigger}</td></tr>
            <tr><td>止损</td><td>{result.invalidation}</td></tr>
            <tr><td>目标</td><td>{result.target_1}</td></tr>
            <tr><td>置信度</td><td>{result.confidence}</td></tr>
        </table>
    </div>
    
    <div class="section">
        <h2>附录 A: 连续性追踪</h2>
        <p>{"周线背景：" + result.weekly_context if result.weekly_context else "首次分析，无历史状态"}</p>
    </div>
    
    <div class="section">
        <h2>附录 B: 视觉证据摘要</h2>
        <p>{"图像总数：" + str(image_bundle.manifest.total_count) if image_bundle else "无图像数据"}</p>
    </div>
    
    <footer style="margin-top: 40px; padding-top: 20px; border-top: 1px solid #ddd; color: #7f8c8d; font-size: 0.9em;">
        生成时间：{datetime.now().strftime("%Y-%m-%d %H:%M:%S")} | 威科夫多模态分析系统 v1.0
    </footer>
</body>
</html>"""

        # 保存报告
        report_path = os.path.join(self.reports_dir, f"{result.symbol}_wyckoff_report.html")
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(html)

        logger.info(f"HTML 报告已保存：{report_path}")
        return report_path

    def generate_summary_csv(self, result: AnalysisResult) -> str:
        """生成 CSV Summary - SPEC Section 4"""
        df = pd.DataFrame(
            [
                {
                    "symbol": result.symbol,
                    "asset_type": result.asset_type,
                    "analysis_date": result.analysis_date,
                    "phase": result.phase,
                    "micro_action": result.micro_action,
                    "decision": result.decision,
                    "confidence": result.confidence,
                    "bc_found": result.bc_found,
                    "spring_detected": result.spring_detected,
                    "rr_assessment": result.rr_assessment,
                    "t1_risk_assessment": result.t1_risk_assessment,
                    "trigger": result.trigger,
                    "invalidation": result.invalidation,
                    "target_1": result.target_1,
                    "abandon_reason": result.abandon_reason,
                }
            ]
        )

        csv_path = os.path.join(self.summary_dir, f"analysis_summary_{result.symbol}.csv")
        df.to_csv(csv_path, index=False, encoding="utf-8-sig")

        logger.info(f"CSV Summary 已保存：{csv_path}")
        return csv_path

    def generate_raw_json(self, result: AnalysisResult) -> str:
        """生成原始 JSON - SPEC Section 1"""
        json_path = os.path.join(self.raw_dir, f"analysis_{result.symbol}.json")

        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(self._result_to_dict(result), f, indent=2, ensure_ascii=False)

        logger.info(f"原始 JSON 已保存：{json_path}")
        return json_path

    def generate_evidence_json(self, bundle: ImageEvidenceBundle) -> str:
        """生成图像证据 JSON - SPEC Section 2"""
        json_path = os.path.join(
            self.evidence_dir,
            f"image_evidence_{bundle.manifest.files[0].symbol if bundle.manifest.files else 'unknown'}.json",
        )

        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(self._bundle_to_dict(bundle), f, indent=2, ensure_ascii=False)

        logger.info(f"图像证据 JSON 已保存：{json_path}")
        return json_path

    def generate_conflicts_json(self, conflicts: List[dict]) -> str:
        """生成冲突清单 JSON"""
        json_path = os.path.join(self.evidence_dir, "conflicts.json")

        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(conflicts, f, indent=2, ensure_ascii=False)

        logger.info(f"冲突清单 JSON 已保存：{json_path}")
        return json_path

    def _result_to_dict(self, result: AnalysisResult) -> dict:
        """将 AnalysisResult 转换为字典"""
        return {
            "symbol": result.symbol,
            "asset_type": result.asset_type,
            "analysis_date": result.analysis_date,
            "input_sources": result.input_sources,
            "timeframes_seen": result.timeframes_seen,
            "bc_found": result.bc_found,
            "phase": result.phase,
            "micro_action": result.micro_action,
            "boundary_upper_zone": result.boundary_upper_zone,
            "boundary_lower_zone": result.boundary_lower_zone,
            "volume_profile_label": result.volume_profile_label,
            "spring_detected": result.spring_detected,
            "utad_detected": result.utad_detected,
            "counterfactual_summary": result.counterfactual_summary,
            "t1_risk_assessment": result.t1_risk_assessment,
            "rr_assessment": result.rr_assessment,
            "decision": result.decision,
            "trigger": result.trigger,
            "invalidation": result.invalidation,
            "target_1": result.target_1,
            "confidence": result.confidence,
            "abandon_reason": result.abandon_reason,
            "conflicts": result.conflicts,
            "consistency_score": result.consistency_score,
            "weekly_context": result.weekly_context,
            "intraday_context": result.intraday_context,
        }

    def _bundle_to_dict(self, bundle: ImageEvidenceBundle) -> dict:
        """将 ImageEvidenceBundle 转换为字典"""
        return {
            "manifest": {
                "total_count": bundle.manifest.total_count,
                "usable_count": bundle.manifest.usable_count,
                "scan_time": bundle.manifest.scan_time,
                "files": [
                    {
                        "file_path": f.file_path,
                        "file_name": f.file_name,
                        "symbol": f.symbol,
                        "inferred_timeframe": f.inferred_timeframe,
                        "image_quality": f.image_quality,
                    }
                    for f in bundle.manifest.files
                ],
            },
            "detected_timeframes": bundle.detected_timeframes,
            "overall_image_quality": bundle.overall_image_quality,
            "trust_level": bundle.trust_level,
            "visual_evidence_count": len(bundle.visual_evidence_list),
        }
