# -*- coding: utf-8 -*-
"""
v3.0 规则执行器 - 10 条规则的独立验证层
基于 Promote_v3.0.md 的规则体系
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import numpy as np

from src.wyckoff.models import (
    ConfidenceResult,
    RiskRewardResult,
    StopLossResult,
    VolumeLevel,
    WyckoffPhase,
)


class V3Rules:
    """v3.0 规则执行器 - 10 条规则的独立验证"""

    @staticmethod
    def rule1_relative_volume(volume: float, volume_series: pd.Series) -> str:
        """规则1: 相对量能分类"""
        if volume_series.empty or volume <= 0:
            return VolumeLevel.AVERAGE.value
        
        avg_vol = volume_series.rolling(window=20, min_periods=5).mean().iloc[-1]
        if pd.isna(avg_vol) or avg_vol <= 0:
            return VolumeLevel.AVERAGE.value
        
        ratio = volume / avg_vol
        
        if ratio >= 3.0:
            return VolumeLevel.EXTREME_HIGH.value
        elif ratio >= 1.5:
            return VolumeLevel.HIGH.value
        elif ratio >= 0.7:
            return VolumeLevel.AVERAGE.value
        elif ratio >= 0.3:
            return VolumeLevel.LOW.value
        else:
            return VolumeLevel.EXTREME_LOW.value

    @staticmethod
    def rule2_no_long_in_markdown(phase: WyckoffPhase, signal_type: str) -> Tuple[bool, str]:
        """规则2: Markdown 禁止做多"""
        if phase == WyckoffPhase.MARKDOWN:
            return True, "Markdown阶段禁止做多"
        if signal_type in ("markdown", "downward_thrust"):
            return True, "下跌信号禁止做多"
        return False, ""

    @staticmethod
    def rule3_t1_risk_test(entry_price: float, support_low: float) -> Dict[str, Any]:
        """规则3: T+1 极限回撤测试"""
        if entry_price <= 0 or support_low <= 0:
            return {"verdict": "超限", "pct": 100.0, "desc": "无效价格"}
        
        max_drawdown_pct = (entry_price - support_low) / entry_price * 100
        
        if max_drawdown_pct < 3.0:
            return {"verdict": "安全", "pct": round(max_drawdown_pct, 2), 
                    "desc": f"极限回撤{max_drawdown_pct:.1f}%，安全"}
        elif max_drawdown_pct < 5.0:
            return {"verdict": "偏薄", "pct": round(max_drawdown_pct, 2),
                    "desc": f"极限回撤{max_drawdown_pct:.1f}%，偏薄"}
        else:
            return {"verdict": "超限", "pct": round(max_drawdown_pct, 2),
                    "desc": f"极限回撤{max_drawdown_pct:.1f}%，超限"}

    @staticmethod
    def rule4_no_trade_zone(contradictions_count: int, struct_clarity: str) -> bool:
        """规则4: 诚实不作为 - 信号矛盾时强制空仓"""
        if contradictions_count >= 3:
            return True
        if struct_clarity in ("混沌", "unclear", "矛盾"):
            return True
        return False

    @staticmethod
    def rule5_bc_tr_fallback(bc_found: bool, tr_defined: bool) -> Dict[str, Any]:
        """规则5: BC/TR 降级策略"""
        if bc_found and tr_defined:
            return {"validity": "full", "confidence_base": "A", "desc": "BC+TR完整"}
        elif bc_found:
            return {"validity": "partial", "confidence_base": "B", "desc": "BC可见但TR不明"}
        elif tr_defined:
            return {"validity": "tr_fallback", "confidence_base": "C", "desc": "TR明确但BC不可见"}
        else:
            return {"validity": "insufficient", "confidence_base": "D", "desc": "BC和TR均不可见"}

    @staticmethod
    def rule6_spring_validation(
        spring_detected: bool,
        post_spring_df: pd.DataFrame,
        spring_low: float,
    ) -> Dict[str, Any]:
        """规则6: Spring 结构事件验证（v3.0 核心）"""
        if not spring_detected:
            return {"lps_confirmed": False, "quality": "无", "desc": "未检测到Spring"}
        
        if post_spring_df.empty or len(post_spring_df) < 3:
            return {"lps_confirmed": False, "quality": "二级(放量需ST)", 
                    "desc": "Spring后数据不足，需ST验证"}
        
        # 检查LPS确认条件
        # 1. 后续地量K线出现（< 天量柱的30%）
        if "volume" in post_spring_df.columns:
            max_vol = post_spring_df["volume"].max()
            recent_vol = post_spring_df["volume"].iloc[-3:].mean()
            low_volume = recent_vol < max_vol * 0.3
        else:
            low_volume = False
        
        # 2. 价格未破Spring极低点
        price_held = post_spring_df["low"].min() >= spring_low * 0.995
        
        # 3. 出现反弹收阳
        if len(post_spring_df) >= 2:
            last_close = post_spring_df["close"].iloc[-1]
            last_open = post_spring_df["open"].iloc[-1]
            bounce = last_close > last_open
        else:
            bounce = False
        
        lps_confirmed = low_volume and price_held and bounce
        
        if lps_confirmed:
            return {"lps_confirmed": True, "quality": "一级(缩量)", 
                    "desc": "缩量Spring+LPS确认，供给枯竭"}
        else:
            return {"lps_confirmed": False, "quality": "二级(放量需ST)", 
                    "desc": "Spring后需ST验证"}

    @staticmethod
    def rule7_counterfactual(pro_score: float, con_score: float) -> Dict[str, Any]:
        """规则7: 反事实仲裁"""
        if con_score > pro_score:
            return {"overturned": True, "verdict": "推翻", 
                    "desc": f"反证({con_score:.1f})>正证({pro_score:.1f})，结论被推翻"}
        elif con_score > pro_score * 0.7:
            return {"overturned": False, "verdict": "降档",
                    "desc": f"反证({con_score:.1f})接近正证({pro_score:.1f})，降档处理"}
        else:
            return {"overturned": False, "verdict": "维持",
                    "desc": f"正证({pro_score:.1f})占优，维持判断"}

    @staticmethod
    def rule8_confidence_matrix(
        bc_located: bool,
        spring_lps_verified: bool,
        counterfactual_passed: bool,
        rr_qualified: bool,
        multiframe_aligned: bool,
    ) -> ConfidenceResult:
        """规则8: 置信度矩阵（5项条件）"""
        conditions = [bc_located, spring_lps_verified, counterfactual_passed, 
                      rr_qualified, multiframe_aligned]
        met_count = sum(conditions)
        
        if met_count == 5:
            level = "A"
            reason = "5项条件全部满足"
            position_size = "标准仓位"
        elif met_count == 4:
            level = "B"
            reason = "4项条件满足"
            position_size = "轻仓"
        elif met_count == 3:
            level = "C"
            reason = "3项条件满足"
            position_size = "试仓"
        else:
            level = "D"
            reason = f"仅{met_count}项条件满足"
            position_size = "空仓"
        
        return ConfidenceResult(
            level=level,
            bc_located=bc_located,
            spring_lps_verified=spring_lps_verified,
            counterfactual_passed=counterfactual_passed,
            rr_qualified=rr_qualified,
            multiframe_aligned=multiframe_aligned,
            position_size=position_size,
            reason=reason,
        )

    @staticmethod
    def rule9_multiframe_alignment(
        daily_phase: WyckoffPhase,
        weekly_phase: WyckoffPhase,
        monthly_phase: WyckoffPhase,
    ) -> Tuple[str, str]:
        """规则9: 多周期一致性"""
        # 月线/周线 Markdown → 覆盖日线，强制空仓
        if monthly_phase == WyckoffPhase.MARKDOWN:
            return "markdown_override", "月线Markdown，强制空仓"
        if weekly_phase == WyckoffPhase.MARKDOWN:
            return "markdown_override", "周线Markdown，强制空仓"
        
        # 月线/周线 Distribution → 覆盖日线
        if monthly_phase == WyckoffPhase.DISTRIBUTION:
            return "distribution_override", "月线Distribution，降级"
        if weekly_phase == WyckoffPhase.DISTRIBUTION:
            return "distribution_override", "周线Distribution，降级"
        
        # 三周期共振
        if daily_phase == weekly_phase == monthly_phase:
            return "fully_aligned", f"三周期共振{daily_phase.value}"
        
        # 月线+周线同时 Markup → 支持日线
        if weekly_phase == WyckoffPhase.MARKUP and monthly_phase == WyckoffPhase.MARKUP:
            return "aligned", "月线+周线Markup支持日线"
        
        # 周线 Unknown + 日线 Markup → 降级
        if weekly_phase == WyckoffPhase.UNKNOWN and daily_phase == WyckoffPhase.MARKUP:
            return "degraded", "周线Unknown，日线Markup降级"
        
        return "mixed", "多周期信号混合"

    @staticmethod
    def rule10_stop_loss(key_low: float) -> StopLossResult:
        """规则10: 止损精度（关键低点 × 0.995）"""
        if key_low <= 0:
            return StopLossResult(
                entry_price=0.0,
                stop_loss_price=0.0,
                stop_pct=0.0,
                precision_warning=True,
                liquidity_risk_warning="无效关键低点",
                stop_logic="无法计算止损",
            )
        
        stop_loss_price = key_low * 0.995
        stop_pct = 0.5  # 固定0.5%
        
        precision_warning = stop_pct < 1.5
        
        return StopLossResult(
            entry_price=key_low,
            stop_loss_price=round(stop_loss_price, 3),
            stop_pct=stop_pct,
            precision_warning=precision_warning,
            liquidity_risk_warning="止损区间窄，注意流动性" if precision_warning else "",
            stop_logic=f"关键低点{key_low:.2f}×0.995={stop_loss_price:.2f}",
        )