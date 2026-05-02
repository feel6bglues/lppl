#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
威科夫 (Wyckoff) A 股实战分析工具
基于 Richard Wyckoff 理论的 K 线与量价分析

使用方法:
    python wyckoff_analysis.py --symbol 000001.SH
    python wyckoff_analysis.py --symbol 000001.SH --lookback 120
    python wyckoff_analysis.py --symbol 000300.SH --output output/wyckoff
    python wyckoff_analysis.py --symbol 000001.SH --mode fusion --chart-dir charts/000001
"""

import logging
import os
import sys
from argparse import ArgumentParser
from datetime import datetime
from pathlib import Path
from typing import Dict

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.cli.lppl_verify_v2 import SYMBOLS
from src.data.manager import DataManager
from src.wyckoff import WyckoffAnalyzer, WyckoffReport
from src.wyckoff.fusion_engine import FusionEngine
from src.wyckoff.image_engine import ImageEngine
from src.wyckoff.state import StateManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def resolve_output_dirs(base_output_dir: str) -> Dict[str, str]:
    return {
        "base": base_output_dir,
        "reports": os.path.join(base_output_dir, "reports"),
        "raw": os.path.join(base_output_dir, "raw"),
        "summary": os.path.join(base_output_dir, "summary"),
        "state": os.path.join(base_output_dir, "state"),
        "evidence": os.path.join(base_output_dir, "evidence"),
        "plots": os.path.join(base_output_dir, "plots"),
    }


def ensure_output_dirs(output_dirs: Dict[str, str]) -> None:
    for path in output_dirs.values():
        os.makedirs(path, exist_ok=True)


def _save_all_outputs(
    report: WyckoffReport,
    image_evidence,
    analysis_result,
    output_dirs: Dict[str, str],
    symbol: str,
    mode: str
) -> None:
    """保存所有输出文件"""
    import json
    from datetime import datetime
    
    symbol_slug = symbol.replace(".", "_")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    analysis_date = (
        str(report.structure.current_date)[:10]
        if report.structure and getattr(report.structure, "current_date", None)
        else datetime.now().strftime("%Y-%m-%d")
    )
    
    # 1. raw/analysis_<symbol>.json
    raw_analysis = {
        "symbol": report.symbol,
        "period": report.period,
        "structure": {
            "phase": report.structure.phase.value if hasattr(report.structure.phase, 'value') else str(report.structure.phase),
            "unknown_candidate": report.structure.unknown_candidate if report.structure else "",
            "current_date": analysis_date,
            "bc_point": {
                "date": report.structure.bc_point.date if report.structure.bc_point else None,
                "price": report.structure.bc_point.price if report.structure.bc_point else None,
            } if report.structure else None,
            "sc_point": {
                "date": report.structure.sc_point.date if report.structure and report.structure.sc_point else None,
                "price": report.structure.sc_point.price if report.structure and report.structure.sc_point else None,
            },
            "trading_range_high": report.structure.trading_range_high if report.structure else None,
            "trading_range_low": report.structure.trading_range_low if report.structure else None,
            "current_price": report.structure.current_price if report.structure else None,
        },
        "signal": {
            "signal_type": report.signal.signal_type if report.signal else None,
            "confidence": report.signal.confidence.value if report.signal and hasattr(report.signal.confidence, 'value') else None,
            "description": report.signal.description if report.signal else None,
        },
        "risk_reward": {
            "entry_price": report.risk_reward.entry_price if report.risk_reward else None,
            "stop_loss": report.risk_reward.stop_loss if report.risk_reward else None,
            "first_target": report.risk_reward.first_target if report.risk_reward else None,
            "reward_risk_ratio": report.risk_reward.reward_risk_ratio if report.risk_reward else 0,
        },
        "trading_plan": {
            "direction": report.trading_plan.direction if report.trading_plan else None,
            "trigger_condition": report.trading_plan.trigger_condition if report.trading_plan else None,
            "invalidation_point": report.trading_plan.invalidation_point if report.trading_plan else None,
        } if report.trading_plan else None,
        "multi_timeframe": {
            "enabled": report.multi_timeframe.enabled if report.multi_timeframe else False,
            "alignment": report.multi_timeframe.alignment if report.multi_timeframe else "",
            "summary": report.multi_timeframe.summary if report.multi_timeframe else "",
            "constraint_note": report.multi_timeframe.constraint_note if report.multi_timeframe else "",
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
            "daily_phase": (
                report.multi_timeframe.daily.phase.value
                if report.multi_timeframe and report.multi_timeframe.daily
                else ""
            ),
            "daily_unknown_candidate": (
                report.multi_timeframe.daily.unknown_candidate
                if report.multi_timeframe and report.multi_timeframe.daily
                else ""
            ),
        },
    }
    with open(os.path.join(output_dirs["raw"], f"analysis_{symbol_slug}_{timestamp}.json"), "w", encoding="utf-8") as f:
        json.dump(raw_analysis, f, ensure_ascii=False, indent=2)
    
    # 2. raw/image_evidence_<symbol>.json (如果有图像证据)
    if image_evidence and hasattr(image_evidence, 'files') and image_evidence.files:
        image_evidence_dict = {
            "files": image_evidence.files,
            "detected_timeframe": image_evidence.detected_timeframe,
            "image_quality": image_evidence.image_quality,
            "trust_level": image_evidence.trust_level,
        }
        with open(os.path.join(output_dirs["raw"], f"image_evidence_{symbol_slug}_{timestamp}.json"), "w", encoding="utf-8") as f:
            json.dump(image_evidence_dict, f, ensure_ascii=False, indent=2)
    
    # 3. summary/analysis_summary_<symbol>.csv (增强为SPEC要求)
    summary_data = [
        ["symbol", "asset_type", "analysis_date", "phase", "micro_action", "decision", "confidence", 
         "bc_found", "spring_detected", "rr_assessment", "t1_risk_assessment", "trigger", 
         "invalidation", "target_1", "abandon_reason", "mtf_alignment", "monthly_phase", "weekly_phase", "daily_phase", "daily_unknown_candidate"],
        [
            report.symbol,
            "stock" if symbol.endswith(('.SH', '.SZ')) else "index",
            analysis_date,
            report.structure.phase.value if report.structure and hasattr(report.structure.phase, 'value') else "unknown",
            report.signal.signal_type if report.signal else "N/A",
            analysis_result.decision if analysis_result else (report.trading_plan.direction if report.trading_plan else "N/A"),
            report.signal.confidence.value if report.signal and hasattr(report.signal.confidence, 'value') else "D",
            "Yes" if report.structure and report.structure.bc_point else "No",
            "Yes" if report.signal and report.signal.signal_type == "spring" else "No",
            analysis_result.rr_assessment if analysis_result else ("pass" if report.risk_reward and report.risk_reward.reward_risk_ratio >= 2.5 else "fail"),
            analysis_result.t1_risk_assessment if analysis_result else (report.signal.t1_risk评估 if report.signal and report.signal.t1_risk评估 else "N/A"),
            report.trading_plan.trigger_condition if report.trading_plan else "N/A",
            report.trading_plan.invalidation_point if report.trading_plan else "N/A",
            report.trading_plan.first_target if report.trading_plan else "N/A",
            analysis_result.abandon_reason if analysis_result else "",
            report.multi_timeframe.alignment if report.multi_timeframe else "",
            report.multi_timeframe.monthly.phase.value if report.multi_timeframe and report.multi_timeframe.monthly else "",
            report.multi_timeframe.weekly.phase.value if report.multi_timeframe and report.multi_timeframe.weekly else "",
            report.multi_timeframe.daily.phase.value if report.multi_timeframe and report.multi_timeframe.daily else "",
            report.multi_timeframe.daily.unknown_candidate if report.multi_timeframe and report.multi_timeframe.daily else "",
        ]
    ]
    import csv
    with open(os.path.join(output_dirs["summary"], f"analysis_summary_{symbol_slug}_{timestamp}.csv"), "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerows(summary_data)
    
    # 4. evidence/<symbol>_conflicts.json (如果有冲突)
    if analysis_result and hasattr(analysis_result, 'conflicts') and analysis_result.conflicts:
        conflicts_dict = {
            "symbol": symbol,
            "analysis_date": datetime.now().strftime('%Y-%m-%d'),
            "conflicts": analysis_result.conflicts,
            "conflict_count": len(analysis_result.conflicts),
        }
        with open(os.path.join(output_dirs["evidence"], f"{symbol_slug}_conflicts_{timestamp}.json"), "w", encoding="utf-8") as f:
            json.dump(conflicts_dict, f, ensure_ascii=False, indent=2)
    
    # 4. state/<symbol>_wyckoff_state.json (融合模式时由StateManager生成)
    # 5. evidence/<symbol>_chart_manifest.json (图像扫描时由ImageEngine生成)
    
    # 6. plots - 暂时跳过，需要matplotlib等绘图库
    # 7. reports - 已在上方单独保存
    
    logger.info(f"所有输出文件已保存到：{output_dirs['base']}")


def _generate_html_report(report: WyckoffReport, reports_dir: str, symbol: str, mode: str) -> None:
    """生成HTML报告"""
    from datetime import datetime
    
    symbol_slug = symbol.replace(".", "_")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    markdown_content = report.to_markdown()
    
    html_content = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>威科夫分析报告 - {symbol}</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; max-width: 900px; margin: 0 auto; padding: 20px; background: #f5f5f5; }}
        .container {{ background: white; padding: 30px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
        h1 {{ color: #333; border-bottom: 2px solid #4CAF50; padding-bottom: 10px; }}
        h2 {{ color: #555; margin-top: 25px; }}
        ul {{ list-style: none; padding: 0; }}
        li {{ padding: 8px 0; border-bottom: 1px solid #eee; }}
        .highlight {{ background: #e8f5e9; padding: 10px; border-radius: 4px; margin: 10px 0; }}
        .warning {{ background: #fff3e0; padding: 10px; border-radius: 4px; margin: 10px 0; }}
        .confidence {{ display: inline-block; padding: 4px 12px; border-radius: 4px; font-weight: bold; }}
        .confidence-A {{ background: #4CAF50; color: white; }}
        .confidence-B {{ background: #8BC34A; color: white; }}
        .confidence-C {{ background: #FFC107; color: #333; }}
        .confidence-D {{ background: #f44336; color: white; }}
        .signal {{ display: inline-block; padding: 4px 12px; border-radius: 4px; background: #2196F3; color: white; margin: 4px; }}
        .step {{ margin: 20px 0; }}
    </style>
</head>
<body>
    <div class="container">
        {markdown_to_html(markdown_content)}
    </div>
</body>
</html>"""
    
    filepath = os.path.join(reports_dir, f"wyckoff_{symbol_slug}_{mode}_{timestamp}.html")
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(html_content)
    logger.info(f"HTML报告已保存：{filepath}")


def markdown_to_html(md_text: str) -> str:
    """简单的Markdown转HTML"""
    import re
    html = md_text
    html = re.sub(r'^# (.+)$', r'<h1>\1</h1>', html, flags=re.MULTILINE)
    html = re.sub(r'^## (.+)$', r'<h2>\1</h2>', html, flags=re.MULTILINE)
    html = re.sub(r'^### (.+)$', r'<h3>\1</h3>', html, flags=re.MULTILINE)
    html = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', html)
    html = re.sub(r'\*\*(.+)\*\*', r'<strong>\1</strong>', html)
    html = re.sub(r'^- (.+)$', r'<li>\1</li>', html, flags=re.MULTILINE)
    html = re.sub(r'^(.+)$', r'<p>\1</p>', html)
    return html


def main() -> None:
    parser = ArgumentParser(description="威科夫 A 股实战分析")
    parser.add_argument("--symbol", "-s", default="000001.SH", help="指数代码")
    parser.add_argument("--lookback", "-l", type=int, default=120, help="回看天数")
    parser.add_argument("--output", "-o", default="output/wyckoff", help="输出目录")
    parser.add_argument("--verbose", "-v", action="store_true", help="详细输出")
    parser.add_argument("--as-of", default=None, help="历史回放截止日期，格式 YYYY-MM-DD")
    # 多模态分析参数 (PRD第7节输入模式)
    parser.add_argument("--input-file", default=None, help="标准OHLCV文件路径")
    parser.add_argument("--chart-dir", default=None, help="图表文件夹路径（可选）")
    parser.add_argument("--chart-files", default=None, help="显式图片文件列表（逗号分隔）")
    parser.add_argument("--mode", choices=["data-only", "images-only", "fusion"], default="data-only", help="分析模式")
    parser.add_argument("--multi-timeframe", action="store_true", help="使用日线合成周线/月线进行多周期分析")
    args = parser.parse_args()

    # 数据源选择 (PRD第7节: 数据-only / 图片-only / 数据+图片融合)
    df = None
    if args.input_file:
        # 从文件加载OHLCV数据
        logger.info(f"正在从文件加载数据：{args.input_file}")
        if not os.path.exists(args.input_file):
            raise SystemExit(f"数据文件不存在：{args.input_file}")
        df = pd.read_csv(args.input_file)
        if 'date' in df.columns:
            df['date'] = pd.to_datetime(df['date'])
        symbol_from_file = os.path.basename(args.input_file).split('.')[0]
        if not args.symbol or args.symbol == "000001.SH":
            args.symbol = symbol_from_file
    elif args.symbol:
        # 从DataManager加载
        symbol_label = SYMBOLS.get(args.symbol, args.symbol)
        logger.info(f"正在加载 {args.symbol} ({symbol_label}) 数据...")
        data_manager = DataManager()
        df = data_manager.get_data(args.symbol)
    else:
        raise SystemExit("请提供 --symbol 或 --input-file")
    
    if df is None or df.empty:
        raise SystemExit(f"无法获取 {args.symbol} 数据，请检查数据源")

    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)

    if args.as_of:
        as_of = pd.to_datetime(args.as_of)
        df = df[df["date"] <= as_of].copy().reset_index(drop=True)
        if df.empty:
            raise SystemExit(f"{args.symbol} 在 {args.as_of} 之前无可用数据")

    logger.info(f"数据加载完成，共 {len(df)} 条记录，最新日期：{df['date'].iloc[-1].date()}")
    
    # 初始化输出目录
    output_dirs = resolve_output_dirs(args.output)
    ensure_output_dirs(output_dirs)

    # 多模态分析
    image_evidence = None
    analysis_result = None
    
    # 图像输入 (支持 --chart-dir 或 --chart-files，参考SPEC_IMAGE_ENGINE第1-2节)
    if args.mode in ["images-only", "fusion"] and (args.chart_dir or args.chart_files):
        logger.info("正在扫描图表...")
        image_engine = ImageEngine()
        
        if args.chart_files:
            # 显式文件列表模式
            file_list = [f.strip() for f in args.chart_files.split(',')]
            manifest = image_engine.scan_chart_files(file_list, args.symbol)
        else:
            # 文件夹模式
            manifest = image_engine.scan_chart_directory(args.chart_dir, args.symbol)
        
        image_evidence = image_engine.extract_visual_evidence(manifest)
        
        # 保存chart_manifest
        image_engine.generate_chart_manifest_json(
            manifest, 
            os.path.join(output_dirs["evidence"], f"{args.symbol.replace('.', '_')}_chart_manifest.json")
        )
        
        logger.info(f"图像扫描完成：{len(manifest['files'])} 张图片，时间周期：{image_evidence.detected_timeframe}")
    
    logger.info("正在执行威科夫分析...")
    
    analyzer = WyckoffAnalyzer(lookback_days=args.lookback)
    report = analyzer.analyze(
        df,
        symbol=args.symbol,
        period="日线",
        image_evidence=image_evidence,
        multi_timeframe=args.multi_timeframe,
    )
    
    if args.mode == "fusion":
        logger.info("正在执行融合分析...")
        fusion_engine = FusionEngine()
        analysis_result = fusion_engine.fuse(
            report=report,
            image_evidence=image_evidence
        )
        
        # 状态管理
        state_manager = StateManager()
        state_manager.update_state(
            symbol=args.symbol,
            analysis_result=analysis_result,
            output_path=os.path.join(output_dirs["state"], f"{args.symbol.replace('.', '_')}_wyckoff_state.json")
        )
        logger.info(f"融合分析完成：决策={analysis_result.decision}, 置信度={analysis_result.confidence}")
        
    # 生成所有输出文件
    _save_all_outputs(report, image_evidence, analysis_result, output_dirs, args.symbol, args.mode)
    
    # 生成HTML报告
    _generate_html_report(report, output_dirs["reports"], args.symbol, args.mode)

    print("\n" + "=" * 60)
    print("威科夫分析报告")
    print("=" * 60)
    print(report.to_markdown())
    
    if analysis_result:
        print("\n" + "=" * 60)
        print("融合分析结果")
        print("=" * 60)
        print(f"决策：{analysis_result.decision}")
        print(f"置信度：{analysis_result.confidence}")
        print(f"触发条件：{analysis_result.trigger}")
        print(f"失效位：{analysis_result.invalidation}")
        print(f"目标位：{analysis_result.target_1}")
        print("=" * 60)

    mode_slug = args.mode
    symbol_slug = args.symbol.replace(".", "_")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"wyckoff_{symbol_slug}_{mode_slug}_{timestamp}.md"
    filepath = os.path.join(output_dirs["reports"], filename)

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(report.to_markdown())

    logger.info(f"报告已保存：{filepath}")


if __name__ == "__main__":
    main()
