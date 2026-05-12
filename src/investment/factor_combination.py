from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd


class Regime(Enum):
    BULL = "bull"
    BEAR = "bear"
    RANGE = "range"

    @classmethod
    def from_str(cls, s: str) -> "Regime":
        mapping = {"bull": cls.BULL, "bear": cls.BEAR, "range": cls.RANGE}
        return mapping.get(s.lower(), cls.RANGE)


class Phase(Enum):
    MARKDOWN = "markdown"
    MARKUP = "markup"
    ACCUMULATION = "accumulation"
    DISTRIBUTION = "distribution"
    UNKNOWN = "unknown"

    @classmethod
    def from_str(cls, s: str) -> "Phase":
        mapping = {
            "markdown": cls.MARKDOWN, "markup": cls.MARKUP,
            "accumulation": cls.ACCUMULATION, "distribution": cls.DISTRIBUTION,
            "unknown": cls.UNKNOWN,
        }
        return mapping.get(s.lower(), cls.UNKNOWN)


class MTFAlignment(Enum):
    MIXED = "mixed"
    FULLY_ALIGNED = "fully_aligned"
    WEEKLY_DAILY = "weekly_daily"
    HIGHER_TF = "higher_tf"

    @classmethod
    def from_str(cls, s: str) -> "MTFAlignment":
        mapping = {
            "mixed": cls.MIXED, "fully_aligned": cls.FULLY_ALIGNED,
            "weekly_daily": cls.WEEKLY_DAILY, "higher_tf": cls.HIGHER_TF,
            "weekly_daily_aligned": cls.WEEKLY_DAILY,
            "higher_timeframe_aligned": cls.HIGHER_TF,
        }
        return mapping.get(s.lower().replace("_aligned", ""), cls.MIXED)


class Confidence(Enum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"

    @classmethod
    def from_str(cls, s: str) -> "Confidence":
        mapping = {"a": cls.A, "b": cls.B, "c": cls.C, "d": cls.D}
        return mapping.get(s.strip().upper(), cls.D)


class Direction(Enum):
    WAIT = "空仓观望"
    HOLD = "持有观察"
    OBSERVE = "观察等待"
    LIGHT = "轻仓试探"
    LONG = "做多"


@dataclass
class FactorComboResult:
    regime: Regime
    phase: Phase
    alignment: MTFAlignment
    confidence: Confidence
    holding_days: int

    expected_return_60d: Optional[float] = None
    win_rate: Optional[float] = None
    sample_size: Optional[int] = None
    score: int = 0
    risk_level: str = "unknown"
    direction: Optional[str] = None
    position_size: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "combo": f"{self.regime.value}+{self.phase.value}+{self.alignment.value}+{self.confidence.value}+{self.holding_days}d",
            "regime": self.regime.value,
            "phase": self.phase.value,
            "alignment": self.alignment.value,
            "confidence": self.confidence.value,
            "holding_days": self.holding_days,
            "return_60d": self.expected_return_60d,
            "win_rate": self.win_rate,
            "sample_size": self.sample_size,
            "score": self.score,
            "risk": self.risk_level,
            "direction": self.direction,
            "position": self.position_size,
        }


class FactorCombinationEngine:
    """三层过滤因子组合引擎

    Layer 1: 硬性排除 (Hard Exclusion)
    Layer 2: 信号增强 (Signal Enhancement)
    Layer 3: 主动交易策略 (Active Signal Strategies)
    """

    # 基于49866样本数据的交叉分析结果
    COMBO_LOOKUP = {
        ("bear", "markdown", "higher_tf"): (6.83, 56.9, 3667),
        ("bear", "markdown", "fully_aligned"): (6.31, 53.7, 2498),
        ("bear", "markdown", "weekly_daily"): (4.40, 57.9, 2626),
        ("bear", "markdown", "mixed"): (3.48, 54.7, 3828),
        ("bear", "accumulation", "higher_tf"): (6.00, 69.2, 52),
        ("bear", "accumulation", "mixed"): (None, None, 66),
        ("bear", "distribution", "mixed"): (1.61, 58.0, 81),
        ("bear", "distribution", "higher_tf"): (-0.55, 38.9, 54),
        ("bear", "unknown", "mixed"): (7.23, 63.0, 265),
        ("bear", "unknown", "fully_aligned"): (2.70, 51.6, 587),
        ("bear", "unknown", "weekly_daily"): (0.40, 51.5, 425),
        ("bear", "unknown", "higher_tf"): (-3.12, 39.9, 363),
        ("bear", "markup", "mixed"): (-1.18, 46.3, 300),
        ("bear", "markup", "fully_aligned"): (-2.73, 36.3, 375),
        ("bear", "markup", "weekly_daily"): (2.69, 50.5, 392),
        ("bear", "markup", "higher_tf"): (2.41, 46.3, 421),

        ("bull", "markdown", "mixed"): (6.91, 51.4, 953),
        ("bull", "markdown", "fully_aligned"): (2.03, 50.3, 183),
        ("bull", "markdown", "weekly_daily"): (6.64, 51.3, 427),
        ("bull", "markdown", "higher_tf"): (3.09, 47.6, 578),
        ("bull", "markup", "mixed"): (10.19, 64.3, 140),
        ("bull", "markup", "fully_aligned"): (12.35, 56.2, 192),
        ("bull", "markup", "weekly_daily"): (20.64, 68.1, 188),
        ("bull", "markup", "higher_tf"): (3.72, 49.4, 156),
        ("bull", "unknown", "mixed"): (17.54, 66.1, 180),
        ("bull", "unknown", "fully_aligned"): (12.77, 63.4, 153),
        ("bull", "unknown", "weekly_daily"): (18.56, 63.2, 133),
        ("bull", "unknown", "higher_tf"): (15.50, 55.1, 127),
        ("bull", "accumulation", "higher_tf"): (3.95, 42.9, 28),
        ("bull", "distribution", "higher_tf"): (20.62, 69.6, 23),
    }

    # 衰减曲线乘数 (基于decay_analysis)
    DECAY_MULTIPLIER = {
        30: 0.0,    # 30d负收益, 不交易
        60: 1.0,    # 基准
        90: 2.23,   # 4.33/1.94
        120: 2.97,  # 5.77/1.94
        150: 3.52,  # 6.82/1.94
        180: 4.55,  # 8.82/1.94
    }

    # 置信度权重 (基于confidence factor analysis)
    CONFIDENCE_WEIGHTS = {
        Confidence.B: 1.0,
        Confidence.D: 0.75,
        Confidence.C: -0.3,
        Confidence.A: 0.0,
    }

    def evaluate(
        self,
        regime: Regime,
        phase: Phase,
        alignment: MTFAlignment,
        confidence: Confidence,
        holding_days: int = 120,
    ) -> FactorComboResult:
        return self._evaluate_v1(regime, phase, alignment, confidence, holding_days)

    def evaluate_v2(
        self,
        regime: Regime,
        phase: Phase,
        alignment: MTFAlignment,
        confidence: Confidence,
    ) -> FactorComboResult:
        """v2: 基于大范围验证(7指数)校准的简化版评估

        关键改进 (vs v1):
        - 不排除range制度(占35%交易日, 在牛市中=盘整, 应持仓)
        - regime占主导(70%), phase+alignment做微调
        - 简单规则取代复杂权重评分
        """
        result = FactorComboResult(
            regime=regime, phase=phase, alignment=alignment,
            confidence=confidence, holding_days=90,
        )

        # ── 硬排除条件 ──
        if phase == Phase.MARKUP and regime == Regime.RANGE:
            return self._exclude(result, "markup_range_bad")
        if regime == Regime.RANGE and phase == Phase.UNKNOWN and confidence == Confidence.C:
            return self._exclude(result, "range_unknown_c")
        if regime == Regime.BEAR and phase == Phase.MARKUP:
            return self._exclude(result, "bear_markup")

        # ── 仓位计算 ──
        if regime == Regime.BULL:
            if phase == Phase.DISTRIBUTION:
                result.direction = "持有观察"
                pos = 0.60
            elif alignment == MTFAlignment.FULLY_ALIGNED:
                result.direction = "做多"
                pos = 0.95
            else:
                result.direction = "做多"
                pos = 0.80

        elif regime == Regime.RANGE:
            if phase in (Phase.MARKDOWN, Phase.UNKNOWN):
                result.direction = "空仓观望"
                pos = 0.50
            elif phase == Phase.DISTRIBUTION:
                result.direction = "持有观察"
                pos = 0.30
            else:
                result.direction = "空仓观望"
                pos = 0.40

        elif regime == Regime.BEAR:
            if phase == Phase.MARKDOWN:
                result.direction = "做多"
                pos = 0.70
                if alignment == MTFAlignment.HIGHER_TF:
                    pos = 0.80
            elif phase == Phase.ACCUMULATION:
                result.direction = "轻仓试探"
                pos = 0.50
            else:
                result.direction = "空仓观望"
                pos = 0.0
        else:
            result.direction = "空仓观望"
            pos = 0.0

        # ── 置信度微调 ──
        if confidence == Confidence.B:
            pos = min(1.0, pos + 0.10)
        elif confidence == Confidence.C:
            pos = max(0.0, pos - 0.15)

        result.score = int(pos * 100)
        result.position_size = round(pos, 2)
        result.risk_level = "low" if pos >= 0.7 else "medium" if pos > 0 else "excluded"
        return result

    def _exclude(self, result, reason):
        result.score = 0
        result.risk_level = "excluded"
        result.direction = "空仓"
        result.position_size = 0.0
        return result

    def _evaluate_v1(
        self,
        regime: Regime,
        phase: Phase,
        alignment: MTFAlignment,
        confidence: Confidence,
        holding_days: int = 120,
    ) -> FactorComboResult:
        result = FactorComboResult(
            regime=regime, phase=phase, alignment=alignment,
            confidence=confidence, holding_days=holding_days,
        )

        # === Layer 1: Hard Exclusion ===
        exclusion, reason = self._check_exclusion(regime, phase, alignment, holding_days)
        if exclusion:
            result.score = -abs(len(reason))
            result.risk_level = "excluded"
            result.direction = "空仓"
            result.position_size = 0.0
            result.expected_return_60d = None
            result.win_rate = None
            return result

        # === Layer 2+3: Scoring & Strategy ===
        score = 0

        # Regime scoring (权重35/100)
        regime_scores = {Regime.BULL: 35, Regime.BEAR: 25, Regime.RANGE: 0}
        score += regime_scores.get(regime, 0)

        # Phase scoring (权重30/100)
        phase_scores_bull = {
            Phase.MARKDOWN: 20, Phase.MARKUP: 25, Phase.UNKNOWN: 28,
            Phase.ACCUMULATION: 10, Phase.DISTRIBUTION: 20,
        }
        phase_scores_bear = {
            Phase.MARKDOWN: 30, Phase.MARKUP: 5, Phase.UNKNOWN: 15,
            Phase.ACCUMULATION: 25, Phase.DISTRIBUTION: 10,
        }
        phase_scores = {
            Regime.BULL: phase_scores_bull,
            Regime.BEAR: phase_scores_bear,
        }
        score += phase_scores.get(regime, {}).get(phase, 10)

        # Alignment scoring (权重20/100)
        mtf_scores = {
            (Regime.BULL, MTFAlignment.MIXED): 18,
            (Regime.BULL, MTFAlignment.WEEKLY_DAILY): 20,
            (Regime.BULL, MTFAlignment.FULLY_ALIGNED): 15,
            (Regime.BULL, MTFAlignment.HIGHER_TF): 10,
            (Regime.BEAR, MTFAlignment.HIGHER_TF): 20,
            (Regime.BEAR, MTFAlignment.FULLY_ALIGNED): 18,
            (Regime.BEAR, MTFAlignment.WEEKLY_DAILY): 16,
            (Regime.BEAR, MTFAlignment.MIXED): 12,
        }
        score += mtf_scores.get((regime, alignment), 10)

        # Confidence scoring (权重15/100)
        conf_scores = {Confidence.B: 15, Confidence.D: 12, Confidence.C: 5, Confidence.A: 0}
        score += conf_scores.get(confidence, 5)

        result.score = score

        # === Lookup empirical data ===
        expiry_factor = self.COMBO_LOOKUP.get(
            (regime.value, phase.value, alignment.value), None
        )

        if expiry_factor:
            ret_60d, wr, n = expiry_factor
            result.expected_return_60d = ret_60d
            result.win_rate = wr
            result.sample_size = n

            # Adjust for holding period
            if holding_days >= 60 and ret_60d is not None:
                mult = self.DECAY_MULTIPLIER.get(holding_days, 1.0)
                result.expected_return_60d = round(ret_60d * mult, 2)

        # === Determine direction ===
        result.direction = self._determine_direction(regime, phase, alignment, confidence)
        result.position_size = self._calc_position_size(result)
        result.risk_level = self._determine_risk(score, result.sample_size)
        return result

    def _check_exclusion(
        self, regime: Regime, phase: Phase,
        alignment: MTFAlignment, holding_days: int,
    ) -> Tuple[bool, str]:
        if regime == Regime.RANGE:
            return True, "range_regime_excluded"
        if holding_days < 60:
            return True, "holding_period_too_short"
        if regime == Regime.BEAR and phase == Phase.MARKUP and alignment != MTFAlignment.WEEKLY_DAILY:
            return True, "bear_markup_non_weekly_daily"
        if regime == Regime.BEAR and phase == Phase.UNKNOWN and alignment == MTFAlignment.HIGHER_TF:
            return True, "bear_unknown_higher_tf_negative"
        if phase == Phase.MARKUP and alignment == MTFAlignment.MIXED and regime != Regime.BULL:
            return True, "markup_mixed_non_bull"
        return False, ""

    def _determine_direction(
        self, regime: Regime, phase: Phase,
        alignment: MTFAlignment, confidence: Confidence,
    ) -> str:
        if regime == Regime.RANGE:
            return "空仓"
        if confidence == Confidence.C:
            return "持有观察" if phase in (Phase.MARKUP, Phase.DISTRIBUTION) else "空仓观望"
        if regime == Regime.BULL:
            # 大范围验证: bull+markup = 783%累积, 7/7指数最强组合
            if phase in (Phase.MARKUP, Phase.UNKNOWN, Phase.MARKDOWN):
                return "做多"
            if phase == Phase.DISTRIBUTION:
                return "持有观察"
            if phase == Phase.ACCUMULATION:
                return "轻仓试探"
            return "做多"
        if regime == Regime.BEAR:
            if phase in (Phase.MARKDOWN, Phase.ACCUMULATION):
                return "做多"
            if phase == Phase.MARKUP:
                return "持有观察"
            return "空仓观望"
        return "空仓观望"

    def _calc_position_size(self, result: FactorComboResult) -> float:
        base_size = self.CONFIDENCE_WEIGHTS.get(result.confidence, 0.75)

        sample_penalty = 1.0
        if result.sample_size is not None:
            if result.sample_size < 50:
                sample_penalty = 0.50
            elif result.sample_size < 200:
                sample_penalty = 0.70
            elif result.sample_size < 1000:
                sample_penalty = 0.85

        score_bonus = min(1.8, result.score / 60)
        return round(min(1.0, base_size * score_bonus * sample_penalty), 2)

    def _determine_risk(self, score: int, sample_size: Optional[int]) -> str:
        if score >= 75 and (sample_size or 0) >= 500:
            return "low"
        if score >= 60:
            return "medium"
        return "high"

    def scan_all(self, min_score: int = 50) -> List[Dict[str, Any]]:
        regimes = list(Regime)
        phases = list(Phase)
        alignments = list(MTFAlignment)
        confidences = [Confidence.B, Confidence.D]
        holdings = [60, 90, 120, 150, 180]

        results = []
        for r in regimes:
            for p in phases:
                for a in alignments:
                    for c in confidences:
                        for h in holdings:
                            res = self.evaluate(r, p, a, c, h)
                            if res.score >= min_score:
                                results.append(res.to_dict())

        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:50]


def batch_evaluate_from_df(
    df: pd.DataFrame,
    regime_col: str = "regime",
    phase_col: str = "phase",
    alignment_col: str = "mtf_alignment",
    confidence_col: str = "wyckoff_confidence",
    holding_days: int = 120,
) -> pd.DataFrame:
    """批量评估DataFrame中每行的因子组合"""
    engine = FactorCombinationEngine()
    outputs = []
    for _, row in df.iterrows():
        regime = Regime.from_str(str(row.get(regime_col, "range")))
        phase = Phase.from_str(str(row.get(phase_col, "unknown")))
        alignment = MTFAlignment.from_str(str(row.get(alignment_col, "mixed")))
        confidence = Confidence.from_str(str(row.get(confidence_col, "D")))
        res = engine.evaluate(regime, phase, alignment, confidence, holding_days)
        outputs.append(res.to_dict())
    return pd.DataFrame(outputs)


def integrate_into_signal(
    regime: str, phase: str, alignment: str,
    confidence: str, holding_days: int = 120,
) -> Dict[str, Any]:
    """生成可直接用于信号模型的组合评分"""
    engine = FactorCombinationEngine()
    r = Regime.from_str(regime)
    p = Phase.from_str(phase)
    a = MTFAlignment.from_str(alignment)
    c = Confidence.from_str(confidence)
    res = engine.evaluate(r, p, a, c, holding_days)
    return {
        "factor_score": res.score,
        "factor_return_est": res.expected_return_60d,
        "factor_win_rate": res.win_rate,
        "factor_risk": res.risk_level,
        "factor_direction": res.direction,
        "factor_position": res.position_size,
        "factor_sample_size": res.sample_size,
    }


def create_signal_multiplier(
    regime: str, phase: str, alignment: str, confidence: str,
) -> float:
    """基于因子组合生成信号乘数 [-1.0, 2.0]"""
    result = integrate_into_signal(regime, phase, alignment)
    if result["factor_risk"] == "excluded":
        return 0.0
    base = 1.0
    if result["factor_direction"] == "做多":
        base = 1.5
    elif result["factor_direction"] == "持有观察":
        base = -0.5
    elif result["factor_direction"] == "空仓观望":
        base = 0.3
    elif result["factor_direction"] == "观察等待":
        base = 0.8
    return round(base * result["factor_position"], 2)
