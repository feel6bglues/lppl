# -*- coding: utf-8 -*-
"""
Wyckoff 融合引擎
负责融合数据引擎和图像引擎的分析结果，处理冲突，输出最终决策
"""

import logging
from typing import List, Optional

from src.wyckoff.models import AnalysisResult, ImageEvidenceBundle, WyckoffReport

logger = logging.getLogger(__name__)


class FusionEngine:
    """融合引擎 - 融合数据与图像分析结果"""
    
    def __init__(self):
        # 冲突矩阵定义
        self.conflict_matrix = {
            ('accumulation', 'possible_distribution'): 'high',
            ('markup', 'possible_markdown'): 'high',
            ('distribution', 'possible_accumulation'): 'high',
            ('markdown', 'possible_markup'): 'high',
        }
    
    def fuse(
        self,
        report: WyckoffReport,
        image_evidence: Optional[ImageEvidenceBundle] = None
    ) -> AnalysisResult:
        """
        融合数据与图像分析结果
        
        Args:
            report: 数据引擎分析报告
            image_evidence: 图像证据包（可选）
            
        Returns:
            AnalysisResult 融合分析结果
        """
        # 初始化结果
        result = AnalysisResult()
        
        # 从报告中提取核心字段
        result.symbol = report.symbol
        if report.structure and getattr(report.structure, "current_date", None):
            result.analysis_date = str(report.structure.current_date)[:10]
        else:
            result.analysis_date = ""
        result.input_sources = ["data"]
        
        # 处理图像证据
        if image_evidence:
            result.input_sources.append("images")
            result.timeframes_seen = self._extract_timeframes(image_evidence)
            
            # 检查冲突
            conflicts = self._detect_conflicts(report, image_evidence)
            result.conflicts = conflicts
        
        # 核心分析字段
        result.bc_found = report.structure.bc_point is not None if report.structure else False
        result.phase = self._map_phase(report.signal.phase.value if hasattr(report.signal.phase, 'value') else str(report.signal.phase) if report.signal and report.signal.phase else "unknown")
        result.micro_action = report.signal.signal_type if report.signal and hasattr(report.signal, 'signal_type') else ""
        
        # 边界与量能
        if report.structure:
            result.boundary_upper_zone = str(report.structure.trading_range_high) if report.structure.trading_range_high else ""
            result.boundary_lower_zone = str(report.structure.trading_range_low) if report.structure.trading_range_low else ""
        if report.signal and report.signal.volume_confirmation:
            result.volume_profile_label = report.signal.volume_confirmation.value if hasattr(report.signal.volume_confirmation, 'value') else str(report.signal.volume_confirmation)
        
        # 特殊信号
        result.spring_detected = report.signal.signal_type == "spring" if report.signal and hasattr(report.signal, 'signal_type') else False
        result.utad_detected = report.signal.signal_type == "utad" if report.signal and hasattr(report.signal, 'signal_type') else False
        
        # 风险评估
        result.counterfactual_summary = "压力测试通过" if report.stress_tests else "未执行压力测试"
        result.t1_risk_assessment = self._assess_t1_risk(report)
        result.rr_assessment = "pass" if report.risk_reward and hasattr(report.risk_reward, 'reward_risk_ratio') and report.risk_reward.reward_risk_ratio >= 2.5 else "fail"
        
        # 交易计划
        result.decision = self._determine_decision(report, image_evidence)
        if report.trading_plan:
            result.trigger = report.trading_plan.trigger_condition if hasattr(report.trading_plan, 'trigger_condition') else ""
            result.invalidation = report.trading_plan.invalidation_point if hasattr(report.trading_plan, 'invalidation_point') else ""
            result.target_1 = report.trading_plan.first_target if hasattr(report.trading_plan, 'first_target') else ""
        result.confidence = report.signal.confidence.value if report.signal and hasattr(report.signal.confidence, 'value') else (report.signal.confidence if report.signal and report.signal.confidence else "D")
        result.abandon_reason = self._get_abandon_reason(report, image_evidence)
        
        return result
    
    def _extract_timeframes(self, image_evidence: ImageEvidenceBundle) -> List[str]:
        """从图像证据提取时间周期"""
        tf = image_evidence.detected_timeframe
        if tf and tf != "unknown_tf":
            return [tf]
        return []
    
    def _detect_conflicts(
        self,
        report: WyckoffReport,
        image_evidence: ImageEvidenceBundle
    ) -> List[str]:
        """检测数据与图像之间的冲突"""
        conflicts = []
        
        # 阶段冲突检测
        data_phase = (
            report.signal.phase.value
            if hasattr(report.signal, "phase") and hasattr(report.signal.phase, "value")
            else str(getattr(report.signal, "phase", "unknown"))
        )
        image_phase_hint = image_evidence.visual_phase_hint
        
        conflict_key = (data_phase, image_phase_hint)
        if conflict_key in self.conflict_matrix:
            severity = self.conflict_matrix[conflict_key]
            conflicts.append(f"阶段冲突：数据={data_phase}, 图像={image_phase_hint}, 严重程度={severity}")
        
        # 趋势冲突检测
        if image_evidence.visual_trend != "unclear":
            # 简单逻辑：数据看多 vs 图像看空
            if data_phase in ['accumulation', 'markup'] and image_evidence.visual_trend == 'downtrend':
                conflicts.append("趋势冲突：数据看多，图像显示下降趋势")
            elif data_phase in ['distribution', 'markdown'] and image_evidence.visual_trend == 'uptrend':
                conflicts.append("趋势冲突：数据看空，图像显示上升趋势")
        
        # 图像质量警告
        if image_evidence.image_quality in ['low', 'unusable']:
            conflicts.append(f"图像质量警告：{image_evidence.image_quality}，可能影响判断")
        
        return conflicts
    
    def _map_phase(self, phase: str) -> str:
        """映射阶段到标准格式"""
        phase_map = {
            'accumulation': 'accumulation',
            'markup': 'markup',
            'distribution': 'distribution',
            'markdown': 'markdown',
            'unknown': 'no_trade_zone',
        }
        return phase_map.get(phase, 'no_trade_zone')
    
    def _assess_t1_risk(self, report: WyckoffReport) -> str:
        """评估 T+1 风险"""
        if not report.stress_tests:
            return "未评估"
        
        # 检查压力测试是否有高风险场景未通过
        # 注意：不得检查 outcome 字符串，应检查 passes 和 risk_level 字段
        for test in report.stress_tests:
            if not test.passes and getattr(test, 'risk_level', '') == '高':
                return "高风险"
        
        # 次级检查：任意场景未通过则标记为中等风险
        any_fail = any(not test.passes for test in report.stress_tests)
        return "中等风险" if any_fail else "可接受"
    
    def _determine_decision(
        self,
        report: WyckoffReport,
        image_evidence: Optional[ImageEvidenceBundle]
    ) -> str:
        """确定最终交易决策"""
        # T+1 零容错阻止：最高优先级，直接返回
        if report.trading_plan and getattr(report.trading_plan, 't1_blocked', False):
            return 'no_trade_zone'

        # 盈亏比硬门槛：不足 1:2.5 一律不准入场
        if report.risk_reward and getattr(report.risk_reward, "reward_risk_ratio", 0) < 2.5:
            return "no_trade_zone"
        
        # 数据引擎主判：从 trading_plan.direction 与 signal.signal_type 推导决策
        # WyckoffSignal 没有 action 字段，必须通过 signal_type 和 phase 判断
        base_decision = 'no_trade_zone'
        if report.signal and report.trading_plan:
            signal_type = getattr(report.signal, 'signal_type', 'no_signal')
            direction = getattr(report.trading_plan, 'direction', '')
            phase_val = getattr(report.signal.phase, 'value', '') if report.signal.phase else ''
            
            if phase_val in ('distribution', 'markdown'):
                # A 股铁律：派发 / 下跌阶段只能空仓或放弃
                base_decision = 'no_trade_zone'
            elif signal_type == 'spring':
                # Spring 信号：T+3 冷冻期内只允许观察，冷冻期结束才可执行
                base_decision = 'watch_only'
            elif signal_type in ('sos_candidate', 'accumulation'):
                base_decision = 'watch_only'
            elif signal_type == 'no_signal' or phase_val == 'unknown':
                base_decision = 'no_trade_zone'
            elif '做多' in direction:
                base_decision = 'long_setup'
        
        # 图像证据降级（图像只能降级，不能升级置信度）
        if image_evidence:
            if image_evidence.image_quality == 'unusable':
                if base_decision == 'long_setup':
                    base_decision = 'watch_only'
            
            if image_evidence.trust_level == 'low':
                if base_decision == 'long_setup':
                    base_decision = 'watch_only'
        
        # 冲突降级
        if image_evidence and len(self._detect_conflicts(report, image_evidence)) > 0:
            if base_decision == 'long_setup':
                base_decision = 'watch_only'
        
        return base_decision
    
    def _get_abandon_reason(
        self,
        report: WyckoffReport,
        image_evidence: Optional[ImageEvidenceBundle]
    ) -> str:
        """获取放弃原因"""
        reasons = []
        
        # 检查 BC 是否找到
        if not (report.structure and report.structure.bc_point):
            reasons.append("未找到 BC 点")
        
        # 检查盈亏比：PRD 要求 R:R >= 1:2.5，不足则放弃
        if report.risk_reward and hasattr(report.risk_reward, 'reward_risk_ratio'):
            if not report.risk_reward.reward_risk_ratio or report.risk_reward.reward_risk_ratio < 2.5:
                reasons.append("盈亏比不足 1:2.5")
        
        # 检查图像质量
        if image_evidence and image_evidence.image_quality == 'unusable':
            reasons.append("图像质量不可用")
        
        # 检查冲突
        if image_evidence and len(self._detect_conflicts(report, image_evidence)) > 0:
            reasons.append("数据与图像结论冲突")
        
        return "; ".join(reasons) if reasons else ""
