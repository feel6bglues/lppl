# -*- coding: utf-8 -*-
"""
威科夫多模态分析系统 - CLI 入口

遵循 ARCH_WYCKOFF_MULTIMODAL_ANALYSIS Section 3 规范
支持三种模式:
1. data-only: 仅数值数据分析
2. image-only: 仅图片视觉巡检
3. fusion: 数据 + 图片融合分析
"""

import argparse
import logging
import logging.handlers
import os
import sys
from datetime import datetime

from src.data.manager import DataManager
from src.wyckoff.config import load_config
from src.wyckoff.data_engine import DataEngine
from src.wyckoff.fusion_engine import FusionEngine, StateManager
from src.wyckoff.image_engine import ImageEngine
from src.wyckoff.reporting import WyckoffReportGenerator

logger = logging.getLogger(__name__)


# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.handlers.RotatingFileHandler(
            "wyckoff_analysis.log",
            maxBytes=10 * 1024 * 1024,  # 10MB
            backupCount=5,
            encoding="utf-8",
        ),
    ],
)


def validate_input_file(file_path: str) -> bool:
    """
    验证输入文件安全性 - 防止路径遍历攻击

    Args:
        file_path: 文件路径

    Returns:
        是否合法
    """
    if not file_path:
        return False

    # 检查路径遍历攻击
    if ".." in file_path:
        logger.error(f"路径遍历攻击检测：{file_path}")
        return False

    # 检查扩展名白名单
    ext = os.path.splitext(file_path)[1].lower()
    allowed_extensions = [".csv", ".parquet"]
    if ext not in allowed_extensions:
        logger.error(f"不支持的文件扩展名：{ext}，仅支持 {allowed_extensions}")
        return False

    # 检查文件是否存在
    if not os.path.exists(file_path):
        logger.error(f"文件不存在：{file_path}")
        return False

    return True


def validate_chart_dir(chart_dir: str) -> bool:
    """
    验证图表目录安全性 - 防止目录遍历攻击

    Args:
        chart_dir: 目录路径

    Returns:
        是否合法
    """
    if not chart_dir:
        return False

    # 检查路径遍历
    if ".." in chart_dir:
        logger.error(f"路径遍历攻击检测：{chart_dir}")
        return False

    # 检查目录是否存在
    if not os.path.exists(chart_dir):
        logger.error(f"目录不存在：{chart_dir}")
        return False

    # 检查是否为目录
    if not os.path.isdir(chart_dir):
        logger.error(f"路径不是目录：{chart_dir}")
        return False

    return True


def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description="威科夫多模态分析系统 - A 股威科夫分析引擎",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 数据-only 模式 (指数)
  python -m src.cli.wyckoff_multimodal_analysis --symbol 000300.SH
  
  # 数据-only 模式 (个股)
  python -m src.cli.wyckoff_multimodal_analysis --symbol 600519.SH
  
  # 数据 + 图片融合模式
  python -m src.cli.wyckoff_multimodal_analysis --symbol 600519.SH --chart-dir output/MA/plots
  
  # 图片-only 模式
  python -m src.cli.wyckoff_multimodal_analysis --chart-dir output/MA/plots
  
  # 文件输入模式
  python -m src.cli.wyckoff_multimodal_analysis --input-file data/600519.parquet
        """,
    )

    # 输入参数
    parser.add_argument("--symbol", "-s", type=str, help="标的代码 (如 000300.SH 或 600519.SH)")
    parser.add_argument("--input-file", "-f", type=str, help="OHLCV 文件路径 (CSV/Parquet)")
    parser.add_argument("--chart-dir", type=str, help="图表目录路径")
    parser.add_argument("--chart-files", nargs="+", help="图表文件列表")

    # 输出参数
    parser.add_argument(
        "--output", "-o", type=str, default="output/wyckoff", help="输出目录 (默认：output/wyckoff)"
    )

    # 运行模式
    parser.add_argument(
        "--mode",
        choices=["auto", "data_only", "image_only", "fusion"],
        default="auto",
        help="运行模式 (默认：auto 自动判断)",
    )

    # LLM 配置 (可选)
    parser.add_argument("--llm-provider", type=str, help="LLM 提供商 (可选)")
    parser.add_argument("--llm-model", type=str, help="LLM 模型 (可选)")
    # NOTE: LLM API Key 只从 WYCKOFF_LLM_API_KEY 环境变量读取，不支持 CLI 参数

    # 其他配置
    parser.add_argument("--config", type=str, help="YAML 配置文件路径")
    parser.add_argument("--verbose", "-v", action="store_true", help="详细输出")

    return parser.parse_args()


def determine_mode(args) -> str:
    """
    自动判断运行模式

    - 有 symbol/input_file + 有 chart_dir/chart_files → fusion
    - 有 symbol/input-file 但无图片 → data_only
    - 只有 chart_dir/chart-files → image_only
    """
    if args.mode != "auto":
        return args.mode

    has_data = args.symbol or args.input_file
    has_images = args.chart_dir or args.chart_files

    if has_data and has_images:
        return "fusion"
    elif has_data:
        return "data_only"
    elif has_images:
        return "image_only"
    else:
        logger.error("必须提供 symbol/input-file 或 chart-dir/chart-files")
        sys.exit(1)


def run_data_only_mode(args, config, output_dir: str) -> None:
    """数据-only 模式"""
    logger.info("=" * 60)
    logger.info("威科夫多模态分析 - 数据-only 模式")
    logger.info("=" * 60)

    # 1. 数据获取
    data_manager = DataManager()
    df, asset_type, input_source = data_manager.get_wyckoff_data(
        symbol=args.symbol,
        input_file=args.input_file,
    )

    symbol = args.symbol or "file_input"
    if symbol == "file_input":
        symbol = (
            args.input_file.replace("/", "_")
            .replace("\\", "_")
            .replace(".parquet", "")
            .replace(".csv", "")
        )

    logger.info(f"数据获取成功：{len(df)} rows, {asset_type}")

    # 2. 规则引擎
    data_engine = DataEngine(config)
    data_result = data_engine.run(df, symbol, asset_type)

    logger.info(
        f"规则引擎完成：phase={data_result.phase_result.phase}, "
        f"decision={data_result.plan.direction}, confidence={data_result.confidence}"
    )

    # 3. 融合引擎 (透传)
    fusion_engine = FusionEngine(config)
    analysis_result = fusion_engine.fuse(data_result, None)

    # 4. 状态管理
    state_manager = StateManager(output_dir)
    state = state_manager.create_state_from_result(analysis_result)
    state_manager.save_state(state)

    # 5. 报告生成
    report_gen = WyckoffReportGenerator(output_dir)
    report_gen.generate_markdown_report(analysis_result, state, None)
    report_gen.generate_html_report(analysis_result, state, None)
    report_gen.generate_summary_csv(analysis_result)
    report_gen.generate_raw_json(analysis_result)

    logger.info("=" * 60)
    logger.info("分析完成！输出目录：" + output_dir)
    logger.info("=" * 60)


def run_image_only_mode(args, config, output_dir: str) -> None:
    """图片-only 模式"""
    logger.info("=" * 60)
    logger.info("威科夫多模态分析 - 图片-only 模式")
    logger.info("=" * 60)

    # 1. 图像引擎
    image_engine = ImageEngine(config)
    image_bundle = image_engine.run(
        chart_dir=args.chart_dir,
        chart_files=args.chart_files,
    )

    logger.info(
        f"图像扫描完成：{image_bundle.manifest.total_count} files, "
        f"{image_bundle.manifest.usable_count} usable, "
        f"quality={image_bundle.overall_image_quality}"
    )

    # 2. 融合引擎 (低置信)
    fusion_engine = FusionEngine(config)

    # 创建虚拟 data_result (无数据)
    from src.wyckoff.models import (
        BCResult,
        CounterfactualResult,
        DailyRuleResult,
        EffortResult,
        PhaseCTestResult,
        PhaseResult,
        PreprocessingResult,
        RiskAssessment,
        TradingPlan,
    )

    data_result = DailyRuleResult(
        symbol="image_only",
        asset_type="unknown",
        analysis_date=datetime.now().strftime("%Y-%m-%d"),
        input_source="images",
        preprocessing=PreprocessingResult(
            trend_direction="unclear",
            volume_label="unclear",
            volatility_layer="unclear",
            local_highs=[],
            local_lows=[],
            gap_candidates=[],
            long_wick_candidates=[],
            limit_anomalies=[],
        ),
        bc_result=BCResult(
            found=False,
            candidate_index=-1,
            candidate_date="",
            candidate_price=0.0,
            volume_label="unknown",
            enhancement_signals=[],
        ),
        phase_result=PhaseResult(
            phase="no_trade_zone",
            boundary_upper_zone="0",
            boundary_lower_zone="0",
            boundary_sources=[],
        ),
        effort_result=EffortResult(
            phenomena=[],
            accumulation_evidence=0.0,
            distribution_evidence=0.0,
            net_bias="neutral",
        ),
        phase_c_test=PhaseCTestResult(
            spring_detected=False,
            utad_detected=False,
            st_detected=False,
            false_breakout_detected=False,
            spring_date=None,
            utad_date=None,
        ),
        counterfactual=CounterfactualResult(
            is_utad_not_breakout="unknown",
            is_distribution_not_accumulation="unknown",
            is_chaos_not_phase_c="unknown",
            liquidity_vacuum_risk="unknown",
            total_pro_score=0.0,
            total_con_score=0.0,
            conclusion_overturned=False,
        ),
        risk=RiskAssessment(
            t1_risk_level="unknown",
            t1_structural_description="",
            rr_ratio=0.0,
            rr_assessment="fail",
            freeze_until=None,
        ),
        plan=TradingPlan(
            current_assessment="图片-only 模式",
            execution_preconditions=[],
            direction="watch_only",
            entry_trigger="",
            invalidation="",
            target_1="",
        ),
        confidence="C",  # 图片-only 最高 C 级
        decision="watch_only",
        abandon_reason="",
    )

    analysis_result = fusion_engine.fuse(data_result, image_bundle)

    # 3. 状态管理
    state_manager = StateManager(output_dir)
    state = state_manager.create_state_from_result(analysis_result)
    state_manager.save_state(state)

    # 4. 报告生成
    report_gen = WyckoffReportGenerator(output_dir)
    report_gen.generate_markdown_report(analysis_result, state, image_bundle)
    report_gen.generate_html_report(analysis_result, state, image_bundle)
    report_gen.generate_evidence_json(image_bundle)

    logger.info("=" * 60)
    logger.info("分析完成！输出目录：" + output_dir)
    logger.info("注意：图片-only 模式仅生成视觉证据报告，不给出生成执行级交易计划")
    logger.info("=" * 60)


def run_fusion_mode(args, config, output_dir: str) -> None:
    """数据 + 图片融合模式"""
    logger.info("=" * 60)
    logger.info("威科夫多模态分析 - 融合模式")
    logger.info("=" * 60)

    # 1. 数据获取
    data_manager = DataManager()
    df, asset_type, input_source = data_manager.get_wyckoff_data(
        symbol=args.symbol,
        input_file=args.input_file,
    )

    symbol = args.symbol or "file_input"
    if symbol == "file_input":
        symbol = (
            args.input_file.replace("/", "_")
            .replace("\\", "_")
            .replace(".parquet", "")
            .replace(".csv", "")
        )

    logger.info(f"数据获取成功：{len(df)} rows, {asset_type}")

    # 2. 规则引擎
    data_engine = DataEngine(config)
    data_result = data_engine.run(df, symbol, asset_type)

    logger.info(
        f"规则引擎完成：phase={data_result.phase_result.phase}, "
        f"decision={data_result.plan.direction}, confidence={data_result.confidence}"
    )

    # 3. 图像引擎
    image_engine = ImageEngine(config)
    image_bundle = image_engine.run(
        chart_dir=args.chart_dir,
        chart_files=args.chart_files,
        explicit_symbol=args.symbol,
    )

    logger.info(
        f"图像扫描完成：{image_bundle.manifest.total_count} files, "
        f"{image_bundle.manifest.usable_count} usable"
    )

    # 4. 融合引擎
    fusion_engine = FusionEngine(config)
    analysis_result = fusion_engine.fuse(data_result, image_bundle)

    logger.info(
        f"融合完成：final_confidence={analysis_result.confidence}, "
        f"consistency={analysis_result.consistency_score}"
    )

    # 5. 状态管理
    state_manager = StateManager(output_dir)

    # 加载历史状态
    previous_state = state_manager.load_state(symbol)
    if previous_state:
        logger.info(
            f"加载历史状态：phase={previous_state.last_phase}, "
            f"decision={previous_state.last_decision}"
        )

    # 保存新状态
    state = state_manager.create_state_from_result(analysis_result)
    state_manager.save_state(state)

    # 生成连续性追踪模板
    continuity = state_manager.generate_continuity_template(analysis_result, previous_state)
    logger.info(
        f"连续性追踪：phase_changed={continuity['phase_changed']}, "
        f"freeze_ended={continuity['freeze_period_ended']}"
    )

    # 6. 报告生成
    report_gen = WyckoffReportGenerator(output_dir)
    report_gen.generate_markdown_report(analysis_result, state, image_bundle)
    report_gen.generate_html_report(analysis_result, state, image_bundle)
    report_gen.generate_summary_csv(analysis_result)
    report_gen.generate_raw_json(analysis_result)
    report_gen.generate_evidence_json(image_bundle)

    logger.info("=" * 60)
    logger.info("分析完成！输出目录：" + output_dir)
    logger.info("=" * 60)


def main():
    """主函数"""
    args = parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # 安全验证：输入文件
    if args.input_file and not validate_input_file(args.input_file):
        logger.error("输入文件验证失败，程序退出")
        sys.exit(1)

    # 安全验证：图表目录
    if args.chart_dir and not validate_chart_dir(args.chart_dir):
        logger.error("图表目录验证失败，程序退出")
        sys.exit(1)

    # 安全验证：图表文件列表
    if args.chart_files:
        for file_path in args.chart_files:
            if not validate_input_file(file_path):
                logger.error(f"图表文件验证失败：{file_path}")
                sys.exit(1)

    # 加载配置
    config = load_config(args.config)

    # 覆盖 LLM 配置
    if args.llm_provider:
        config.llm_provider = args.llm_provider
    if args.llm_model:
        config.llm_model = args.llm_model
    # NOTE: LLM API Key 只从 WYCKOFF_LLM_API_KEY 环境变量读取

    # 确定输出目录
    if args.symbol:
        output_dir = os.path.join(args.output, args.symbol.replace(".", "_"))
    else:
        output_dir = os.path.join(args.output, datetime.now().strftime("%Y%m%d_%H%M%S"))

    os.makedirs(output_dir, exist_ok=True)

    # 确定运行模式
    mode = determine_mode(args)
    logger.info(f"运行模式：{mode}")
    logger.info(f"输出目录：{output_dir}")

    # 执行对应模式
    if mode == "data_only":
        run_data_only_mode(args, config, output_dir)
    elif mode == "image_only":
        run_image_only_mode(args, config, output_dir)
    elif mode == "fusion":
        run_fusion_mode(args, config, output_dir)
    else:
        logger.error(f"未知模式：{mode}")
        sys.exit(1)


if __name__ == "__main__":
    main()
