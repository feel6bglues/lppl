# -*- coding: utf-8 -*-
"""
威科夫多模态分析系统 - 配置管理

管理规则引擎、图像引擎、融合引擎的配置参数
"""

import logging
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import yaml

logger = logging.getLogger(__name__)

from src.constants import (
    BC_LOOKBACK_WINDOW,
    MIN_RR_RATIO,
    MIN_WYCKOFF_DATA_ROWS,
    SPRING_FREEZE_DAYS,
    WYCKOFF_OUTPUT_DIR,
)


@dataclass
class RuleEngineConfig:
    """规则引擎配置 - SPEC_WYCKOFF_RULE_ENGINE"""

    min_data_rows: int = MIN_WYCKOFF_DATA_ROWS
    bc_lookback_window: int = BC_LOOKBACK_WINDOW
    spring_freeze_days: int = SPRING_FREEZE_DAYS
    min_rr_ratio: float = MIN_RR_RATIO

    # BC 检测阈值
    bc_min_price_increase_pct: float = 15.0
    bc_volume_multiplier_high: float = 2.0
    bc_volume_multiplier_avg: float = 1.2

    # 量能标签阈值
    volume_extreme_high_threshold: float = 2.0
    volume_above_avg_threshold: float = 1.2
    volume_contracted_low: float = 0.5

    # 置信度阈值
    confidence_a_rr_min: float = 3.0
    confidence_b_rr_min: float = 2.5


@dataclass
class ImageEngineConfig:
    """图像引擎配置 - SPEC_WYCKOFF_IMAGE_ENGINE"""

    # 支持的图像格式
    supported_formats: List[str] = field(default_factory=lambda: [".png", ".jpg", ".jpeg", ".webp"])

    # 图像质量阈值
    quality_high_min_resolution: int = 1920
    quality_medium_min_resolution: int = 1280
    quality_low_min_resolution: int = 800

    # 模糊度阈值 (Laplacian variance)
    blur_threshold_high: float = 100.0
    blur_threshold_medium: float = 50.0
    blur_threshold_low: float = 20.0

    # 时间周期识别关键词
    weekly_keywords: List[str] = field(default_factory=lambda: ["weekly", "周线", "week"])
    daily_keywords: List[str] = field(default_factory=lambda: ["daily", "日线", "day"])
    minute_keywords: Dict[str, List[str]] = field(
        default_factory=lambda: {
            "60m": ["60m", "60min", "60 分钟", "1h"],
            "30m": ["30m", "30min", "30 分钟"],
            "15m": ["15m", "15min", "15 分钟"],
            "5m": ["5m", "5min", "5 分钟"],
        }
    )


@dataclass
class FusionEngineConfig:
    """融合引擎配置 - SPEC_WYCKOFF_FUSION_AND_STATE"""

    # 冲突权重
    phase_conflict_weight: float = 1.0
    trend_conflict_weight: float = 0.8
    boundary_conflict_weight: float = 0.6

    # 置信度调整系数
    image_quality_weight: float = 0.3
    consistency_weight: float = 0.4
    cross_tf_weight: float = 0.3

    # 保守降级规则
    auto_downgrade_on_conflict: bool = True
    auto_downgrade_on_low_quality: bool = True


@dataclass
class OutputConfig:
    """输出目录配置 - ARCH_WYCKOFF_MULTIMODAL_ANALYSIS Section 6"""

    base_dir: str = WYCKOFF_OUTPUT_DIR
    raw_dir: str = "raw"
    plots_dir: str = "plots"
    reports_dir: str = "reports"
    summary_dir: str = "summary"
    state_dir: str = "state"
    evidence_dir: str = "evidence"

    def get_full_path(self, sub_dir: str, filename: str) -> str:
        """获取完整输出路径"""
        dir_path = os.path.join(self.base_dir, sub_dir)
        os.makedirs(dir_path, exist_ok=True)
        return os.path.join(dir_path, filename)


@dataclass
class WyckoffConfig:
    """威科夫系统总配置"""

    rule_engine: RuleEngineConfig = field(default_factory=RuleEngineConfig)
    image_engine: ImageEngineConfig = field(default_factory=ImageEngineConfig)
    fusion_engine: FusionEngineConfig = field(default_factory=FusionEngineConfig)
    output: OutputConfig = field(default_factory=OutputConfig)

    # LLM 配置 (可选)
    llm_provider: Optional[str] = None
    llm_api_key: Optional[str] = None
    llm_model: Optional[str] = None

    @classmethod
    def from_yaml(cls, yaml_path: str) -> "WyckoffConfig":
        """从 YAML 文件加载配置"""
        try:
            with open(yaml_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
        except yaml.YAMLError as e:
            logger.error(f"YAML parse error in {yaml_path}: {e}")
            return cls()
        except OSError as e:
            logger.error(f"Failed to read {yaml_path}: {e}")
            return cls()

        config = cls()

        if "rule_engine" in data:
            config.rule_engine = RuleEngineConfig(**data["rule_engine"])
        if "image_engine" in data:
            config.image_engine = ImageEngineConfig(**data["image_engine"])
        if "fusion_engine" in data:
            config.fusion_engine = FusionEngineConfig(**data["fusion_engine"])
        if "output" in data:
            config.output = OutputConfig(**data["output"])
        if "llm" in data:
            config.llm_provider = data["llm"].get("provider")
            config.llm_model = data["llm"].get("model")
        # NOTE: llm_api_key 只从环境变量读取，不写入 YAML 解析路径

        return config

    @classmethod
    def from_env(cls) -> "WyckoffConfig":
        """从环境变量加载配置"""
        config = cls()

        if os.environ.get("WYCKOFF_LLM_PROVIDER"):
            config.llm_provider = os.environ.get("WYCKOFF_LLM_PROVIDER")
        if os.environ.get("WYCKOFF_LLM_API_KEY"):
            config.llm_api_key = os.environ.get("WYCKOFF_LLM_API_KEY")
        if os.environ.get("WYCKOFF_LLM_MODEL"):
            config.llm_model = os.environ.get("WYCKOFF_LLM_MODEL")

        return config


def load_config(yaml_path: Optional[str] = None) -> WyckoffConfig:
    """加载配置（优先 YAML，其次环境变量，最后默认值）"""
    if yaml_path and os.path.exists(yaml_path):
        return WyckoffConfig.from_yaml(yaml_path)
    return WyckoffConfig.from_env()
