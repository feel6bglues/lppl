# -*- coding: utf-8 -*-
"""
纯Wyckoff优化引擎

基于6组回测数据的五项优化:
1. 做多方向反转 → 轻仓试探(除非fully_aligned+B)
2. markup阶段完全屏蔽
3. 置信度反转: D加分, C降级
4. MTF对齐作为信号过滤器
5. Accumulation窗口切换至800d
"""

from __future__ import annotations

from dataclasses import dataclass

PHASE_FILTER = {
    "markdown": 1.0,
    "accumulation": 0.5,
    "unknown": 0.2,
    "distribution": 0.0,
    "markup": 0.0,
}

MTF_FILTER = {
    "fully_aligned": 1.0,
    "higher_timeframe_aligned": 0.8,
    "weekly_daily_aligned": 0.3,
    "mixed": 0.1,
    "markdown_override": 0.0,
    "distribution_override": 0.0,
}

CONFIDENCE_ADJUSTMENT = {
    "D": 1.0,
    "C": 0.3,
    "B": 1.2,
    "A": 0.0,
}

OPTIMAL_WINDOWS = {
    "accumulation": 800,
    "markdown": None,
    "markup": None,
    "distribution": 400,
    "unknown": None,
}


@dataclass
class OptimizedSignal:
    raw_phase: str
    raw_direction: str
    raw_confidence: str
    raw_mtf: str
    optimized_direction: str
    phase_weight: float
    mtf_weight: float
    confidence_weight: float
    composite_score: float
    is_actionable: bool


def optimize_signal(
    phase: str,
    direction: str,
    confidence: str,
    mtf_alignment: str,
    spring_detected: bool = False,
) -> OptimizedSignal:
    """
    优化Wyckoff信号

    输入:
      phase: Wyckoff阶段 (markdown/markup/accumulation/distribution/unknown)
      direction: 原始方向 (做多/空仓观望/持有观察/观察等待/轻仓试探)
      confidence: 置信度 (A/B/C/D)
      mtf_alignment: MTF对齐 (fully_aligned/higher_timeframe_aligned/weekly_daily_aligned/mixed)
      spring_detected: 是否检测到spring

    输出:
      OptimizedSignal
    """
    phase_weight = PHASE_FILTER.get(phase, 0.2)
    mtf_weight = MTF_FILTER.get(mtf_alignment, 0.1)
    confidence_weight = CONFIDENCE_ADJUSTMENT.get(confidence, 0.5)

    composite_score = phase_weight * mtf_weight * confidence_weight

    if phase == "markup":
        optimized_direction = "空仓观望"
        is_actionable = False
    elif phase == "distribution":
        optimized_direction = "空仓观望"
        is_actionable = False
    elif phase == "markdown":
        if mtf_alignment in ("fully_aligned", "higher_timeframe_aligned") and confidence in ("D", "B"):
            if confidence == "B" and mtf_alignment == "fully_aligned":
                optimized_direction = "做多"
            else:
                optimized_direction = "轻仓试探"
            is_actionable = True
        elif mtf_alignment == "fully_aligned" and confidence == "C":
            optimized_direction = "观察等待"
            is_actionable = False
        else:
            optimized_direction = "空仓观望"
            is_actionable = False
    elif phase == "accumulation":
        if spring_detected and confidence in ("D", "B"):
            optimized_direction = "轻仓试探"
            is_actionable = True
        else:
            optimized_direction = "观察等待"
            is_actionable = False
    else:
        optimized_direction = "空仓观望"
        is_actionable = False

    return OptimizedSignal(
        raw_phase=phase,
        raw_direction=direction,
        raw_confidence=confidence,
        raw_mtf=mtf_alignment,
        optimized_direction=optimized_direction,
        phase_weight=phase_weight,
        mtf_weight=mtf_weight,
        confidence_weight=confidence_weight,
        composite_score=round(composite_score, 4),
        is_actionable=is_actionable,
    )
