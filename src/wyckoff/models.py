# -*- coding: utf-8 -*-
"""
Wyckoff Analysis Data Models
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class WyckoffPhase(Enum):
    """威科夫周期阶段"""
    ACCUMULATION = "accumulation"      # 积累阶段
    MARKUP = "markup"                  # 上涨阶段
    DISTRIBUTION = "distribution"      # 派发阶段
    MARKDOWN = "markdown"              # 下跌阶段
    UNKNOWN = "unknown"                # 未知/不可交易


class ConfidenceLevel(Enum):
    """置信度等级"""
    A = "A"    # 高置信度 - 信号清晰
    B = "B"    # 中置信度 - 信号较明确
    C = "C"    # 低置信度 - 信号模糊
    D = "D"    # 放弃 - 信号杂乱/无法辨认


class VolumeLevel(Enum):
    """量能等级（相对描述）"""
    EXTREME_HIGH = "天量/爆量"          # 显著高于平均
    HIGH = "高于平均"                   # 明显高于平均
    AVERAGE = "平均"                   # 接近平均
    LOW = "萎缩"                       # 低于平均
    EXTREME_LOW = "地量"               # 极度萎缩


@dataclass
class BCPoint:
    """买入高潮点 (Buying Climax)"""
    date: str
    price: float
    volume_level: VolumeLevel
    is_extremum: bool = True
    confidence_score: int = 0  # BC 置信度评分（0-10）


@dataclass
class SCPoint:
    """卖出高潮点 (Selling Climax)"""
    date: str
    price: float
    volume_level: VolumeLevel
    is_extremum: bool = True
    confidence_score: int = 0  # SC 置信度评分（0-10）


@dataclass
class SupportResistance:
    """支撑/阻力位"""
    level: float
    type: str  # "support" or "resistance"
    source: str  # "BC", "SC", "AR", "自然回撤"
    strength: float = 1.0  # 0-1, 强度


@dataclass
class WyckoffStructure:
    """威科夫结构"""
    phase: WyckoffPhase = WyckoffPhase.UNKNOWN
    bc_point: Optional[BCPoint] = None
    sc_point: Optional[SCPoint] = None
    support_levels: List[SupportResistance] = field(default_factory=list)
    resistance_levels: List[SupportResistance] = field(default_factory=list)
    trading_range_high: Optional[float] = None
    trading_range_low: Optional[float] = None
    current_price: Optional[float] = None
    current_date: Optional[str] = None


@dataclass
class WyckoffSignal:
    """威科夫交易信号"""
    signal_type: str = "no_signal"  # "spring", "utad", "sos", "lps", "bc", "sc", "no_signal"
    trigger_price: Optional[float] = None
    volume_confirmation: Optional[VolumeLevel] = None
    confidence: ConfidenceLevel = ConfidenceLevel.D
    phase: WyckoffPhase = WyckoffPhase.UNKNOWN
    description: str = ""
    t1_risk评估: str = ""  # T+1 风险评估


@dataclass
class RiskRewardProjection:
    """盈亏比投影"""
    entry_price: Optional[float] = None
    stop_loss: Optional[float] = None
    first_target: Optional[float] = None
    reward_risk_ratio: float = 0.0
    risk_amount: float = 0.0
    reward_amount: float = 0.0
    structure_based: str = ""  # 结构描述


@dataclass
class TradingPlan:
    """交易计划"""
    direction: str = "空仓观望"  # "long" or "empty" (空仓观望)
    trigger_condition: str = ""  # 入场触发条件
    invalidation_point: str = ""  # 失效点/止损点
    first_target: str = ""  # 第一目标位
    confidence: ConfidenceLevel = ConfidenceLevel.D
    preconditions: str = ""  # 执行前提
    current_qualification: str = ""  # 当前定性
    spring_cooldown_days: int = 0  # Spring 冷静期
    t1_blocked: bool = False  # T+1 零容错阻止


class LimitMoveType(Enum):
    """涨跌停类型"""
    LIMIT_UP = "涨停"
    LIMIT_DOWN = "跌停"
    BREAK_LIMIT_UP = "炸板"  # 涨停被砸
    BREAK_LIMIT_DOWN = "撬板"  # 跌停被撬
    NONE = "无"


@dataclass
class LimitMove:
    """涨跌停事件"""
    date: str
    move_type: LimitMoveType
    price: float
    volume_level: VolumeLevel
    is_broken: bool = False


@dataclass
class StressTest:
    """反事实压力测试"""
    scenario_name: str = ""
    scenario_description: str = ""
    outcome: str = ""
    passes: bool = False
    risk_level: str = ""  # "低", "中", "高"


@dataclass
class ChipAnalysis:
    """筹码微观分析"""
    absorption_signature: bool = False  # 吸筹痕迹
    distribution_signature: bool = False  # 派发痕迹
    volume_price_divergence: bool = False  # 量价背离
    institutional_footprint: bool = False  # 机构痕迹
    warnings: List[str] = field(default_factory=list)


@dataclass
class ImageEvidenceBundle:
    """图像证据包 - 图像引擎输出"""
    files: List[str] = field(default_factory=list)  # 图片文件列表
    detected_timeframe: str = "unknown_tf"  # 检测到的时间周期 (weekly/daily/60m/30m/15m/5m/unknown_tf)
    image_quality: str = "medium"  # 图像质量 (high/medium/low/unusable)
    visual_trend: str = "unclear"  # 视觉趋势 (uptrend/downtrend/range/unclear)
    visual_phase_hint: str = "unclear"  # 视觉阶段提示 (possible_accumulation/possible_markup/possible_distribution/possible_markdown/unclear)
    visual_boundaries: List[dict] = field(default_factory=list)  # 视觉边界 [{'type': 'upper/lower', 'level': float}]
    visual_anomalies: List[str] = field(default_factory=list)  # 视觉异常 (长上影/长下影/跳空/假突破/快速收回/放量滞涨)
    visual_volume_labels: str = "unclear"  # 视觉量能标签 (extreme_high/above_average/contracted/extreme_contracted/unclear)
    trust_level: str = "medium"  # 信任级别 (high/medium/low)


@dataclass
class AnalysisResult:
    """分析结果 - 融合引擎输出"""
    symbol: str = ""
    asset_type: str = "stock"  # "stock" or "index"
    analysis_date: str = ""
    input_sources: List[str] = field(default_factory=list)  # ["data", "images"]
    timeframes_seen: List[str] = field(default_factory=list)  # ["daily", "weekly", "60m"]
    
    # 核心字段
    bc_found: bool = False
    phase: str = "unknown"  # accumulation/markup/distribution/markdown/no_trade_zone
    micro_action: str = ""
    
    # 边界与量能
    boundary_upper_zone: str = ""  # 上边界区域
    boundary_lower_zone: str = ""  # 下边界区域
    volume_profile_label: str = ""  # 量能标签
    
    # 特殊信号
    spring_detected: bool = False
    utad_detected: bool = False
    
    # 风险评估
    counterfactual_summary: str = ""  # 反事实总结
    t1_risk_assessment: str = ""  # T+1 风险评估
    rr_assessment: str = ""  # 盈亏比评估 (pass/fail)
    
    # 交易计划字段
    decision: str = "no_trade_zone"  # long_setup/watch_only/no_trade_zone/abandon
    trigger: str = ""
    invalidation: str = ""
    target_1: str = ""
    confidence: str = "D"  # A/B/C/D
    abandon_reason: str = ""  # 放弃原因
    conflicts: List[str] = field(default_factory=list)  # 冲突列表


@dataclass
class AnalysisState:
    """分析状态 - 状态持久化"""
    symbol: str = ""
    asset_type: str = "stock"
    analysis_date: str = ""
    
    # 上次分析结果
    last_phase: str = ""
    last_micro_action: str = ""
    last_confidence: str = "D"
    
    # 关键状态
    bc_found: bool = False
    spring_detected: bool = False
    freeze_until: Optional[str] = None  # Spring 冷冻期截止日期
    watch_status: str = "none"  # none/watching/cooling_down
    
    # 触发器状态
    trigger_armed: bool = False
    trigger_text: str = ""
    invalid_level: str = ""
    target_1: str = ""
    
    # 上下文
    weekly_context: str = ""
    intraday_context: str = ""
    conflict_summary: str = ""
    
    # 决策记录
    last_decision: str = ""
    abandon_reason: str = ""


@dataclass
class TimeframeSnapshot:
    """单一周期快照"""
    period: str
    phase: WyckoffPhase = WyckoffPhase.UNKNOWN
    current_price: Optional[float] = None
    current_date: Optional[str] = None
    trading_range_high: Optional[float] = None
    trading_range_low: Optional[float] = None
    bc_price: Optional[float] = None
    sc_price: Optional[float] = None
    signal_type: str = "no_signal"
    signal_description: str = ""


@dataclass
class MultiTimeframeContext:
    """多周期上下文"""
    enabled: bool = False
    monthly: Optional[TimeframeSnapshot] = None
    weekly: Optional[TimeframeSnapshot] = None
    daily: Optional[TimeframeSnapshot] = None
    alignment: str = "single_timeframe"
    summary: str = ""
    constraint_note: str = ""


@dataclass
class WyckoffReport:
    """威科夫分析报告"""
    symbol: str
    period: str  # "daily", "weekly", etc.
    structure: WyckoffStructure
    signal: WyckoffSignal
    risk_reward: RiskRewardProjection
    trading_plan: TradingPlan
    limit_moves: List[LimitMove] = field(default_factory=list)
    stress_tests: List[StressTest] = field(default_factory=list)
    chip_analysis: Optional[ChipAnalysis] = None
    
    # 多模态扩展字段
    image_evidence: Optional[ImageEvidenceBundle] = None
    analysis_result: Optional[AnalysisResult] = None
    analysis_state: Optional[AnalysisState] = None
    multi_timeframe: Optional[MultiTimeframeContext] = None
    
    def to_markdown(self) -> str:
        """转换为 Markdown 格式"""
        lines = [
            f"# 威科夫分析报告 - {self.symbol}",
            f"**分析周期**: {self.period}",
            "",
        ]

        if self.multi_timeframe and self.multi_timeframe.enabled:
            lines.extend([
                "## Step -1: 多周期总览",
                f"- **一致性**: {self.multi_timeframe.alignment}",
                f"- **结论摘要**: {self.multi_timeframe.summary}",
                f"- **约束说明**: {self.multi_timeframe.constraint_note}",
            ])
            if self.multi_timeframe.monthly:
                lines.append(
                    f"- **月线**: {self.multi_timeframe.monthly.phase.value} @ {self.multi_timeframe.monthly.current_date}"
                )
            if self.multi_timeframe.weekly:
                lines.append(
                    f"- **周线**: {self.multi_timeframe.weekly.phase.value} @ {self.multi_timeframe.weekly.current_date}"
                )
            if self.multi_timeframe.daily:
                lines.append(
                    f"- **日线**: {self.multi_timeframe.daily.phase.value} @ {self.multi_timeframe.daily.current_date}"
                )
            lines.append("")

        lines.extend([
            "## Step 0: BC 定位扫描",
            f"- **BC点**: {self.structure.bc_point.date if self.structure.bc_point else '未找到'} @ {self.structure.bc_point.price if self.structure.bc_point else 'N/A'}",
            f"- **SC点**: {self.structure.sc_point.date if self.structure.sc_point else '未找到'} @ {self.structure.sc_point.price if self.structure.sc_point else 'N/A'}",
            "",
            "## Step 1: 大局观与宏观定调",
            f"- **当前阶段**: {self.structure.phase.value}",
            f"- **震荡区间**: {self.structure.trading_range_low} - {self.structure.trading_range_high}",
            f"- **当前价格**: {self.structure.current_price}",
            "",
        ])
        
        limit_moves_str = ""
        if self.limit_moves:
            lm_lines = [f"- **{lm.move_type.value}** @ {lm.date} ${lm.price}" for lm in self.limit_moves[:3]]
            limit_moves_str = "\n".join(["## Step 1.5: 涨跌停与炸板异动"] + lm_lines)
            lines.append(limit_moves_str)
        
        lines.extend([
            "",
            "## Step 2: 极端流动性与筹码微观扫描",
            f"- **量能状态**: {self.signal.volume_confirmation.value if self.signal.volume_confirmation else 'N/A'}",
        ])
        
        if self.chip_analysis:
            chip_lines = []
            if self.chip_analysis.absorption_signature:
                chip_lines.append("检测到吸筹痕迹")
            if self.chip_analysis.distribution_signature:
                chip_lines.append("检测到派发痕迹")
            if self.chip_analysis.volume_price_divergence:
                chip_lines.append("⚠️ 量价背离警告")
            if self.chip_analysis.warnings:
                chip_lines.extend([f"⚠️ {w}" for w in self.chip_analysis.warnings])
            if chip_lines:
                lines.append("- " + "; ".join(chip_lines))
        
        lines.extend([
            "",
            "## Step 3: T+1 风险评估",
            f"- **T+1风险**: {self.signal.t1_risk评估}",
            "",
            "## Step 3.5: 反事实压力测试",
        ])
        
        if self.stress_tests:
            for st in self.stress_tests:
                status = "✅" if st.passes else "❌"
                lines.append(f"- {status} **{st.scenario_name}**: {st.outcome}")
        else:
            lines.append("- 无压力测试结果")
        
        lines.extend([
            "",
            "## Step 4: 盈亏比投影",
            f"- **入场价**: {self.risk_reward.entry_price}",
            f"- **止损位**: {self.risk_reward.stop_loss}",
            f"- **第一目标**: {self.risk_reward.first_target}",
            f"- **盈亏比**: {self.risk_reward.reward_risk_ratio:.2f}",
            "",
            "## Step 5: 交易计划",
            f"- **【当前定性】**: {self.trading_plan.current_qualification}",
            f"- **【执行前提】**: {self.trading_plan.preconditions}",
            f"- **【操作方向】**: {self.trading_plan.direction}",
            f"- **【精确入场 Trigger】**: {self.trading_plan.trigger_condition}",
            f"- **【铁律止损点】**: {self.trading_plan.invalidation_point}",
            f"- **【第一目标位】**: {self.trading_plan.first_target}",
            "",
        ])
        
        if self.trading_plan.spring_cooldown_days > 0:
            lines.append(f"- **【Spring冷静期】**: {self.trading_plan.spring_cooldown_days}天")
        
        if self.trading_plan.t1_blocked:
            lines.append("- **【T+1零容错】**: ❌ 阻止入场")
        
        lines.append(f"**【置信度等级】**: {self.trading_plan.confidence.value}")
        
        return "\n".join(lines)
