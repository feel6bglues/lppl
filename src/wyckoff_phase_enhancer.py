# -*- coding: utf-8 -*-
"""
Wyckoff阶段增强引擎 v2

核心发现:
1. markdown准确率完美预测市场方向(90%准确率)，但是事后指标
2. 阶段分布在不同市场环境下表现完全不同:
   - 熊市: 所有阶段都亏损
   - 牛市: markdown阶段盈利(+9%~+30%)
3. unknown占比>15%时市场倾向牛市
4. markdown占比>85%且unknown<5%时市场倾向熊市(2012/2018)

增强方案: 市场宽度检测 + 阶段条件化
"""

from __future__ import annotations
from typing import Dict, List, Tuple
from dataclasses import dataclass
import numpy as np
import pandas as pd


@dataclass
class MarketBreadth:
    """市场宽度指标"""
    date: str
    total_stocks: int
    markdown_pct: float
    markup_pct: float
    unknown_pct: float
    accumulation_pct: float
    distribution_pct: float
    market_direction: str  # "bull" / "bear" / "neutral"
    confidence: float


@dataclass
class EnhancedSignal:
    """增强信号"""
    raw_phase: str
    raw_direction: str
    raw_confidence: str
    raw_mtf: str
    market_direction: str
    market_confidence: float
    enhanced_action: str
    enhanced_score: float
    is_actionable: bool
    phase_in_context: str  # 阶段在市场环境下的重新解读


def detect_market_breadth(
    all_phases: List[str],
    all_returns: List[float] = None,
) -> MarketBreadth:
    """
    基于市场宽度检测市场方向

    逻辑(来自回测数据):
    - unknown占比>15% → 市场倾向牛市(2013:16.7%, 2020:19.2%, 2021:16.3%)
    - markdown占比>85%且unknown<5% → 市场倾向熊市(2012:91.1%/2.9%, 2018:95.5%/3.4%)
    - 其他情况 → 中性
    """
    n = len(all_phases)
    if n == 0:
        return MarketBreadth("", 0, 0, 0, 0, 0, 0, "neutral", 0.0)

    md_pct = sum(1 for p in all_phases if p == "markdown") / n * 100
    mk_pct = sum(1 for p in all_phases if p == "markup") / n * 100
    un_pct = sum(1 for p in all_phases if p == "unknown") / n * 100
    acc_pct = sum(1 for p in all_phases if p == "accumulation") / n * 100
    dis_pct = sum(1 for p in all_phases if p == "distribution") / n * 100

    if un_pct > 15:
        direction = "bull"
        confidence = min(1.0, un_pct / 25)
    elif md_pct > 85 and un_pct < 5:
        direction = "bear"
        confidence = min(1.0, md_pct / 100)
    elif md_pct > 80 and un_pct < 8:
        direction = "bear"
        confidence = 0.6
    elif mk_pct > 40:
        direction = "bear"  # 2015: 59.7% markup = 崩盘
        confidence = min(1.0, mk_pct / 60)
    else:
        direction = "neutral"
        confidence = 0.5

    return MarketBreadth(
        date="",
        total_stocks=n,
        markdown_pct=round(md_pct, 1),
        markup_pct=round(mk_pct, 1),
        unknown_pct=round(un_pct, 1),
        accumulation_pct=round(acc_pct, 1),
        distribution_pct=round(dis_pct, 1),
        market_direction=direction,
        confidence=round(confidence, 3),
    )


def enhance_phase_detection(
    phase: str,
    direction: str,
    confidence: str,
    mtf_alignment: str,
    market_breadth: MarketBreadth,
    spring_detected: bool = False,
) -> EnhancedSignal:
    """
    增强阶段判定

    核心逻辑: 阶段的意义取决于市场环境

    熊市中:
    - markdown → 确认下跌趋势, 不做多
    - markup → 泡沫即将破裂, 做空信号
    - unknown → 趋势不明, 观望

    牛市中:
    - markdown → 超跌反弹机会, 做多候选
    - markup → 上涨趋势确认, 做多
    - unknown → 趋势不明, 观望

    中性市场:
    - markdown → 谨慎观望
    - markup → 谨慎观望
    """
    market_dir = market_breadth.market_direction

    if market_dir == "bear":
        if phase == "markdown":
            enhanced_action = "空仓观望"
            phase_in_context = "熊市markdown: 确认下跌趋势"
            score = 0.0
        elif phase == "markup":
            enhanced_action = "空仓观望"
            phase_in_context = "熊市markup: 泡沫即将破裂"
            score = 0.0
        elif phase == "accumulation" and spring_detected:
            enhanced_action = "观察等待"
            phase_in_context = "熊市accumulation: 可能筑底但需确认"
            score = 0.3
        else:
            enhanced_action = "空仓观望"
            phase_in_context = f"熊市{phase}: 不操作"
            score = 0.0

    elif market_dir == "bull":
        if phase == "markdown":
            if mtf_alignment in ("fully_aligned", "higher_timeframe_aligned") and confidence in ("D", "B"):
                enhanced_action = "轻仓试探"
                phase_in_context = "牛市markdown: 超跌反弹机会"
                score = 0.8
            else:
                enhanced_action = "观察等待"
                phase_in_context = "牛市markdown: 关注但不操作"
                score = 0.4
        elif phase == "markup":
            enhanced_action = "持有观察"
            phase_in_context = "牛市markup: 上涨趋势确认"
            score = 0.5
        elif phase == "accumulation" and spring_detected:
            enhanced_action = "轻仓试探"
            phase_in_context = "牛市accumulation: 筑底成功信号"
            score = 0.7
        else:
            enhanced_action = "观察等待"
            phase_in_context = f"牛市{phase}: 观望"
            score = 0.3

    else:  # neutral
        if phase == "markdown":
            if mtf_alignment == "fully_aligned" and confidence in ("D", "B"):
                enhanced_action = "轻仓试探"
                phase_in_context = "中性市场markdown: 条件性做多"
                score = 0.5
            else:
                enhanced_action = "空仓观望"
                phase_in_context = "中性市场markdown: 观望"
                score = 0.1
        elif phase == "markup":
            enhanced_action = "空仓观望"
            phase_in_context = "中性市场markup: 不操作"
            score = 0.0
        else:
            enhanced_action = "空仓观望"
            phase_in_context = f"中性市场{phase}: 观望"
            score = 0.1

    is_actionable = enhanced_action in ("轻仓试探", "做多")

    return EnhancedSignal(
        raw_phase=phase,
        raw_direction=direction,
        raw_confidence=confidence,
        raw_mtf=mtf_alignment,
        market_direction=market_dir,
        market_confidence=market_breadth.confidence,
        enhanced_action=enhanced_action,
        enhanced_score=round(score, 3),
        is_actionable=is_actionable,
        phase_in_context=phase_in_context,
    )
