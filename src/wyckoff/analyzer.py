# -*- coding: utf-8 -*-
"""
Wyckoff 核心分析引擎（已弃用）

请使用 src.wyckoff.engine.WyckoffEngine（v3.0 唯一入口）替代。
本文件保留仅用于向后兼容，新代码不应直接引用 WyckoffAnalyzer。
"""

import logging
from typing import List, Optional, Tuple

import pandas as pd

from src.wyckoff.models import (
    AnalysisState,
    BCPoint,
    ChipAnalysis,
    ConfidenceLevel,
    ImageEvidenceBundle,
    LimitMove,
    LimitMoveType,
    MultiTimeframeContext,
    RiskRewardProjection,
    SCPoint,
    StressTest,
    SupportResistance,
    TimeframeSnapshot,
    TradingPlan,
    VolumeLevel,
    WyckoffPhase,
    WyckoffReport,
    WyckoffSignal,
    WyckoffStructure,
)

logger = logging.getLogger(__name__)


# --- BC/SC detection scoring thresholds ---
_VOL_HIGH_THRESHOLD = 0.8
_VOL_MEDIUM_THRESHOLD = 0.6
_SHADOW_LONG_THRESHOLD = 0.6
_SHADOW_MEDIUM_THRESHOLD = 0.4
_VOL_LOW_THRESHOLD = 0.2
_CONFIRM_DROP_PCT = 0.05
_CONFIRM_RISE_PCT = 0.05


class WyckoffAnalyzer:
    """威科夫分析器"""

    def __init__(self, lookback_days: int = 120):
        self.lookback_days = lookback_days
        self.weekly_min_rows = 20
        self.monthly_min_rows = 12
        self.multi_timeframe_lookback_days = max(lookback_days, 800)

    def _normalize_input_frame(self, df: pd.DataFrame) -> pd.DataFrame:
        frame = df.copy()
        frame["date"] = pd.to_datetime(frame["date"])
        return frame.sort_values("date").reset_index(drop=True)

    def _resample_ohlcv(self, df: pd.DataFrame, rule: str) -> pd.DataFrame:
        frame = self._normalize_input_frame(df).set_index("date")
        resampled = (
            frame.resample(rule, label="right", closed="right")
            .agg(
                {
                    "open": "first",
                    "high": "max",
                    "low": "min",
                    "close": "last",
                    "volume": "sum",
                }
            )
            .dropna(subset=["open", "high", "low", "close"])
            .reset_index()
        )
        return resampled

    def _build_timeframe_snapshot(self, report: WyckoffReport) -> TimeframeSnapshot:
        return TimeframeSnapshot(
            period=report.period,
            phase=report.structure.phase,
            unknown_candidate=report.structure.unknown_candidate,
            current_price=report.structure.current_price,
            current_date=report.structure.current_date,
            trading_range_high=report.structure.trading_range_high,
            trading_range_low=report.structure.trading_range_low,
            bc_price=report.structure.bc_point.price if report.structure.bc_point else None,
            sc_price=report.structure.sc_point.price if report.structure.sc_point else None,
            signal_type=report.signal.signal_type,
            signal_description=report.signal.description,
        )

    def _analyze_timeframe(
        self,
        df: pd.DataFrame,
        symbol: str,
        period: str,
        min_rows: int,
        lookback: int,
        image_evidence: Optional[ImageEvidenceBundle] = None,
    ) -> WyckoffReport:
        frame = self._normalize_input_frame(df)
        if frame is None or len(frame) < min_rows:
            reason = f"数据不足，需要至少 {min_rows} 根 K 线，当前只有 {len(frame) if frame is not None else 0} 根"
            return self._create_no_signal_report(symbol, period, reason)

        frame = frame.tail(lookback).reset_index(drop=True)

        bc_point, sc_point = self._scan_bc_sc(frame)

        if bc_point is None and sc_point is None:
            return self._create_no_signal_report(symbol, period, "未找到BC/SC点")

        structure = self._determine_wyckoff_structure(frame, bc_point, sc_point)
        signal = self._detect_wyckoff_signals(frame, structure)
        limit_moves = self._detect_limit_moves(frame)
        chip_analysis = self._analyze_chips(frame, structure)
        stress_tests = self._run_stress_tests(frame, structure, signal)
        risk_reward = self._calculate_risk_reward(frame, structure, signal)
        trading_plan = self._build_trading_plan(structure, signal, risk_reward, stress_tests)
        self._apply_t1_enforcement(signal, trading_plan, stress_tests)

        report = WyckoffReport(
            symbol=symbol,
            period=period,
            structure=structure,
            signal=signal,
            risk_reward=risk_reward,
            trading_plan=trading_plan,
            limit_moves=limit_moves,
            stress_tests=stress_tests,
            chip_analysis=chip_analysis,
        )

        if image_evidence is not None and period == "日线":
            from src.wyckoff.fusion_engine import FusionEngine

            fusion_engine = FusionEngine()
            analysis_result = fusion_engine.fuse(report, image_evidence)
            report.analysis_result = analysis_result

            if hasattr(analysis_result, "confidence") and analysis_result.confidence:
                try:
                    conf_map = {
                        "A": ConfidenceLevel.A,
                        "B": ConfidenceLevel.B,
                        "C": ConfidenceLevel.C,
                        "D": ConfidenceLevel.D,
                    }
                    if analysis_result.confidence in conf_map:
                        report.trading_plan.confidence = conf_map[analysis_result.confidence]
                        report.signal.confidence = conf_map[analysis_result.confidence]
                except Exception as e:
                    logger.warning(f"无法更新置信度: {e}")

            from datetime import datetime

            analysis_state = AnalysisState(
                symbol=symbol,
                asset_type="stock" if symbol.endswith(".SH") or symbol.endswith(".SZ") else "index",
                analysis_date=datetime.now().strftime("%Y-%m-%d"),
                last_phase=report.structure.phase.value,
                last_micro_action=report.signal.signal_type,
                last_confidence=report.signal.confidence.value,
                bc_found=report.structure.bc_point is not None,
                spring_detected=report.signal.signal_type == "spring",
                weekly_context="",
                intraday_context="",
                last_decision=report.trading_plan.direction,
            )
            report.analysis_state = analysis_state

        return report

    def analyze(
        self,
        df: pd.DataFrame,
        symbol: str = "UNKNOWN",
        period: str = "日线",
        image_evidence: Optional[ImageEvidenceBundle] = None,
        multi_timeframe: bool = False,
    ) -> WyckoffReport:
        """
        执行完整威科夫分析

        Args:
            df: K线数据 DataFrame，需要包含 date, open, high, low, close, volume 列
            symbol: 指数/股票代码
            period: 分析周期
            image_evidence: 可选的图像证据包

        Returns:
            WyckoffReport: 完整的分析报告
        """
        if multi_timeframe and period == "日线":
            return self.analyze_multiframe(df, symbol=symbol, image_evidence=image_evidence)

        min_rows = 100 if period == "日线" else self.weekly_min_rows
        lookback = (
            self.lookback_days
            if period == "日线"
            else max(min_rows, min(len(df), self.lookback_days))
        )
        return self._analyze_timeframe(
            df=df,
            symbol=symbol,
            period=period,
            min_rows=min_rows,
            lookback=lookback,
            image_evidence=image_evidence,
        )

    def analyze_multiframe(
        self,
        df: pd.DataFrame,
        symbol: str = "UNKNOWN",
        image_evidence: Optional[ImageEvidenceBundle] = None,
    ) -> WyckoffReport:
        frame = self._normalize_input_frame(df)
        if frame is None or len(frame) < 100:
            reason = f"数据不足，需要至少 100 根 K 线，当前只有 {len(frame) if frame is not None else 0} 根"
            return self._create_no_signal_report(symbol, "日线+周线+月线", reason)

        long_frame = frame.tail(self.multi_timeframe_lookback_days).reset_index(drop=True)
        weekly_df = self._resample_ohlcv(long_frame, "W-FRI")
        monthly_df = self._resample_ohlcv(long_frame, "ME")

        daily_report = self._analyze_timeframe(
            df=frame,
            symbol=symbol,
            period="日线",
            min_rows=100,
            lookback=self.lookback_days,
            image_evidence=image_evidence,
        )
        weekly_report = self._analyze_timeframe(
            df=weekly_df,
            symbol=symbol,
            period="周线",
            min_rows=self.weekly_min_rows,
            lookback=min(len(weekly_df), 180),
        )
        monthly_report = self._analyze_timeframe(
            df=monthly_df,
            symbol=symbol,
            period="月线",
            min_rows=self.monthly_min_rows,
            lookback=min(len(monthly_df), 120),
        )

        return self._merge_multitimeframe_reports(
            symbol=symbol,
            daily_report=daily_report,
            weekly_report=weekly_report,
            monthly_report=monthly_report,
        )

    def _merge_multitimeframe_reports(
        self,
        symbol: str,
        daily_report: WyckoffReport,
        weekly_report: WyckoffReport,
        monthly_report: WyckoffReport,
    ) -> WyckoffReport:
        final_report = daily_report
        monthly_phase = monthly_report.structure.phase
        weekly_phase = weekly_report.structure.phase
        daily_phase = daily_report.structure.phase
        rr_ratio = final_report.risk_reward.reward_risk_ratio or 0.0

        alignment = "mixed"
        if monthly_phase == weekly_phase == daily_phase:
            alignment = "fully_aligned"
        elif weekly_phase == daily_phase:
            alignment = "weekly_daily_aligned"
        elif monthly_phase == weekly_phase:
            alignment = "higher_timeframe_aligned"

        summary = (
            f"月线={monthly_phase.value} / 周线={weekly_phase.value} / 日线={daily_phase.value}"
        )
        constraint_note = "维持日线结论"
        markup_keywords = (
            "Spring→ST→SOS",
            "Lack of Supply",
            "Test",
            "Shakeout",
            "BUEC",
            "Phase E",
            "SOS",
        )
        markup_context = final_report.signal.description or ""

        if monthly_phase == WyckoffPhase.MARKDOWN or weekly_phase == WyckoffPhase.MARKDOWN:
            final_report.structure.phase = WyckoffPhase.MARKDOWN
            final_report.signal.signal_type = "no_signal"
            final_report.signal.confidence = ConfidenceLevel.D
            final_report.signal.description = (
                f"上级周期压制明确：月线={monthly_phase.value}，周线={weekly_phase.value}，"
                "当前按 Markdown 风险处理，A股禁止做空，维持空仓观望"
            )
            final_report.trading_plan.direction = "空仓观望"
            final_report.trading_plan.current_qualification = final_report.signal.description
            final_report.trading_plan.preconditions = "等待周线止跌或重新进入可定义的积累结构"
            final_report.trading_plan.confidence = ConfidenceLevel.D
            constraint_note = "上级周期为 Markdown，覆盖日线做多倾向"
        elif (
            monthly_phase == WyckoffPhase.DISTRIBUTION or weekly_phase == WyckoffPhase.DISTRIBUTION
        ):
            final_report.structure.phase = WyckoffPhase.DISTRIBUTION
            final_report.signal.signal_type = "no_signal"
            final_report.signal.confidence = ConfidenceLevel.D
            final_report.signal.description = (
                f"上级周期派发风险未解除：月线={monthly_phase.value}，周线={weekly_phase.value}，"
                "当前仅允许空仓观察"
            )
            final_report.trading_plan.direction = "空仓观望"
            final_report.trading_plan.current_qualification = final_report.signal.description
            final_report.trading_plan.preconditions = "等待周线重新完成止跌或积累验证"
            final_report.trading_plan.confidence = ConfidenceLevel.D
            constraint_note = "上级周期派发压力覆盖日线信号"
        elif weekly_phase == WyckoffPhase.UNKNOWN and daily_phase == WyckoffPhase.MARKUP:
            final_report.signal.confidence = ConfidenceLevel.C
            final_report.trading_plan.confidence = ConfidenceLevel.C
            if (
                monthly_phase == WyckoffPhase.MARKUP
                and rr_ratio >= 2.5
                and any(keyword in markup_context for keyword in markup_keywords)
            ):
                if "Phase E" in markup_context or "Lack of Supply" in markup_context:
                    final_report.trading_plan.direction = "持有观察 / 空仓者观望"
                else:
                    final_report.trading_plan.direction = "买入观察 / 轻仓试探"
                final_report.trading_plan.preconditions = (
                    "周线结构仍未完全确认，只允许沿日线右侧结构做观察或轻仓试探，"
                    "不得脱离 LPS/Test/BUEC 纪律追价"
                )
                constraint_note = "周线未确认，但月线仍偏多，保留日线右侧观察语义"
            else:
                final_report.trading_plan.direction = "空仓观望"
                final_report.trading_plan.preconditions = "周线结构未确认，日线信号仅作观察"
                constraint_note = "周线未确认，日线做多信号自动降级"
        elif monthly_phase == WyckoffPhase.MARKUP and weekly_phase == WyckoffPhase.MARKUP:
            if (
                final_report.trading_plan.direction == "空仓观望"
                and "Phase E" in final_report.signal.description
                and rr_ratio > 0
            ):
                final_report.trading_plan.direction = "持有观察"
            elif rr_ratio <= 0:
                final_report.trading_plan.direction = "空仓观望"
                final_report.trading_plan.current_qualification = (
                    "多周期上涨结构成立，但当前位置已明显脱离低风险击球区，"
                    "短线盈亏比不再有效，按 No Trade Zone 处理"
                )
                final_report.trading_plan.preconditions = (
                    "等待回踩 LPS/BUEC 或重新形成可定义低风险结构"
                )
            elif final_report.trading_plan.direction == "空仓观望" and rr_ratio >= 2.5:
                if "Lack of Supply / Test" in markup_context or "Shakeout/Test" in markup_context:
                    final_report.trading_plan.direction = "买入观察 / 轻仓试探"
                    final_report.trading_plan.preconditions = (
                        "月线与周线同向偏多，日线处于回踩测试区，仅允许围绕 LPS/Test 轻仓试探"
                    )
                elif "Lack of Supply" in markup_context or "SOS" in markup_context:
                    final_report.trading_plan.direction = "持有观察 / 空仓者观望"
                    final_report.trading_plan.preconditions = "月线与周线同向偏多，日线处于推进或蓄势段，优先持有观察，空仓者等待更优击球点"
            if final_report.signal.confidence == ConfidenceLevel.A:
                final_report.signal.confidence = ConfidenceLevel.B
            final_report.trading_plan.confidence = final_report.signal.confidence
            constraint_note = "月线与周线共振支持日线上涨结构"

        if (
            daily_phase == WyckoffPhase.MARKDOWN
            and monthly_phase == WyckoffPhase.MARKUP
            and weekly_phase == WyckoffPhase.MARKUP
            and final_report.structure.trading_range_low is not None
            and final_report.structure.current_price is not None
            and final_report.structure.current_price
            <= final_report.structure.trading_range_low * 1.03
        ):
            final_report.structure.phase = WyckoffPhase.UNKNOWN
            final_report.signal.signal_type = "no_signal"
            final_report.signal.confidence = ConfidenceLevel.C
            final_report.signal.description = (
                "上级周期仍偏多，但日线在区间下沿附近出现 SC / Phase A 候选扰动，"
                "当前保持不确定性观察"
            )
            final_report.trading_plan.direction = "空仓观望"
            final_report.trading_plan.current_qualification = final_report.signal.description
            final_report.trading_plan.preconditions = "等待 AR / ST / Phase B 结构补全"
            final_report.trading_plan.trigger_condition = "观察是否出现 SC 后的 AR 反弹与 ST 回测"
            final_report.trading_plan.invalidation_point = (
                f"若继续失守 {final_report.structure.trading_range_low:.2f} 则回归 Markdown"
            )
            final_report.trading_plan.first_target = "第一观察目标 AR 反弹确认"
            final_report.trading_plan.confidence = ConfidenceLevel.C
            constraint_note = "高周期未破坏，但日线正在测试潜在 SC / Phase A 低点"
        elif (
            final_report.structure.phase == WyckoffPhase.UNKNOWN
            and monthly_phase == WyckoffPhase.MARKUP
            and weekly_phase in {WyckoffPhase.MARKUP, WyckoffPhase.UNKNOWN}
        ):
            unknown_candidate = final_report.structure.unknown_candidate
            trigger_parts = ["等待 ST 缩量确认"]
            if final_report.structure.trading_range_high is not None:
                trigger_parts.append(
                    f"或放量突破 {final_report.structure.trading_range_high:.2f} 后再确认"
                )
            qualification = "上级周期仍偏多，"
            if unknown_candidate == "phase_a_candidate":
                qualification += "日线按再积累 / Phase A-AR 反弹观察区处理，暂不追价，等待 ST 或 Phase B 边界清晰"
            elif unknown_candidate == "sc_st_candidate":
                qualification += "日线按再积累 / SC-ST 候选扰动区处理，等待吸收完成后的二次确认"
            elif unknown_candidate == "upthrust_candidate":
                qualification += (
                    "日线按再积累 / Phase B-Upthrust 候选区处理，优先等待假突破失败后的回落确认"
                )
            else:
                qualification += "日线按再积累 / Phase B 观察区处理，等待更清晰的 TR 结构"
            final_report.trading_plan.current_qualification = qualification
            final_report.trading_plan.trigger_condition = "，".join(trigger_parts)
            final_report.trading_plan.invalidation_point = (
                f"失守 {final_report.structure.trading_range_low:.2f} 则回到更弱结构"
                if final_report.structure.trading_range_low is not None
                else "失守近期低点则放弃观察"
            )
            final_report.trading_plan.first_target = (
                f"第一观察目标 {final_report.structure.trading_range_high:.2f}"
                if final_report.structure.trading_range_high is not None
                else "第一观察目标 TR 上沿确认"
            )
            final_report.trading_plan.preconditions = (
                "上级周期偏多，但日线尚未给出可执行的 LPS/Breakout 触发"
            )
            final_report.trading_plan.confidence = ConfidenceLevel.C
            if (
                weekly_phase == WyckoffPhase.MARKUP
                and rr_ratio >= 2.5
                and unknown_candidate in {"phase_a_candidate", "sc_st_candidate"}
            ):
                final_report.trading_plan.direction = "买入观察 / 轻仓试探"
                final_report.trading_plan.preconditions = (
                    "上级周期偏多，日线已进入 Phase A/AR 或 SC/ST 低位候选区，"
                    "仅允许围绕 ST/AR 确认做轻仓试探"
                )
            constraint_note = "上级周期偏多，保留日线 Phase A/B 结构化等待计划"

        if (
            final_report.structure.phase == WyckoffPhase.ACCUMULATION
            and final_report.signal.signal_type == "no_signal"
            and rr_ratio >= 2.5
            and monthly_phase not in {WyckoffPhase.MARKDOWN, WyckoffPhase.DISTRIBUTION}
            and weekly_phase not in {WyckoffPhase.MARKDOWN, WyckoffPhase.DISTRIBUTION}
        ):
            trigger_note = (
                "日线处于积累/再积累结构且赔率充足，但周线事件触发不足，"
                "当前仅跟踪 Spring/Test/LPS 触发"
            )
            if final_report.trading_plan.current_qualification:
                if trigger_note not in final_report.trading_plan.current_qualification:
                    final_report.trading_plan.current_qualification = (
                        f"{final_report.trading_plan.current_qualification}；{trigger_note}"
                    )
            else:
                final_report.trading_plan.current_qualification = trigger_note
            final_report.trading_plan.preconditions = (
                "等待日线出现 Spring 后缩量测试、LPS 站稳或 TR 上沿有效突破"
            )
            if "等待触发" not in final_report.signal.description:
                final_report.signal.description = (
                    f"{final_report.signal.description}；多周期未压制，但需等待触发确认"
                )

        final_report.period = "日线+周线+月线"
        final_report.multi_timeframe = MultiTimeframeContext(
            enabled=True,
            monthly=self._build_timeframe_snapshot(monthly_report),
            weekly=self._build_timeframe_snapshot(weekly_report),
            daily=self._build_timeframe_snapshot(daily_report),
            alignment=alignment,
            summary=summary,
            constraint_note=constraint_note,
        )

        if final_report.analysis_state is not None:
            final_report.analysis_state.weekly_context = (
                f"月线={monthly_phase.value}; 周线={weekly_phase.value}; 日线={daily_phase.value}"
            )

        return final_report

    def _scan_bc_sc(self, df: pd.DataFrame) -> Tuple[Optional[BCPoint], Optional[SCPoint]]:
        """
        扫描 BC 和 SC 点（增强版）

        BC 识别逻辑：
        1. 阶段性高点（50 日内最高或次高）
        2. 放量（>1.5 倍均量或百分位>0.7）
        3. 长上影线（high-close > 0.5*(high-low)）
        4. 后续有回调确认（高点后价格下跌>5%）

        SC 识别逻辑：
        1. 阶段性低点（50 日内最低或次低）
        2. 放量或极度缩量
        3. 长下影线（close-low > 0.5*(high-low)）
        4. 后续有反弹确认
        """
        bc_point = None
        sc_point = None

        df = df.copy()
        df["vol_rank"] = df["volume"].rank(pct=True)
        df["range"] = df["high"] - df["low"]
        df["upper_shadow"] = df["high"] - df["close"]
        df["lower_shadow"] = df["close"] - df["low"]
        df["shadow_ratio"] = df["upper_shadow"] / (df["range"] + 1e-9)
        df["lower_shadow_ratio"] = df["lower_shadow"] / (df["range"] + 1e-9)

        # 寻找峰值和谷值
        peak_idx = df["high"].idxmax()
        trough_idx = df["low"].idxmin()

        # BC 点增强识别
        bc_candidates = []
        for idx in df.nlargest(5, "high").index:
            row = df.loc[idx]
            vol_rank = row["vol_rank"]
            shadow_ratio = row["shadow_ratio"]

            # 评分系统
            score = 0
            if vol_rank > _VOL_HIGH_THRESHOLD:
                score += 2
            elif vol_rank > _VOL_MEDIUM_THRESHOLD:
                score += 1

            if shadow_ratio > _SHADOW_LONG_THRESHOLD:  # 长上影
                score += 2
            elif shadow_ratio > _SHADOW_MEDIUM_THRESHOLD:
                score += 1

            # 检查后续回调
            peak_pos = df.index.get_loc(idx)
            if peak_pos < len(df) - 5:
                subsequent_low = df.iloc[peak_pos + 1 : peak_pos + 10]["close"].min()
                peak_price = row["high"]
                if (peak_price - subsequent_low) / peak_price > _CONFIRM_DROP_PCT:
                    score += 2  # 有确认回调

            bc_candidates.append((idx, score, row))

        # 选择最佳 BC 候选
        bc_candidates.sort(key=lambda x: x[1], reverse=True)
        if bc_candidates:
            best_bc = bc_candidates[0]
            idx, score, row = best_bc
            volume_level = self._classify_volume(row["volume"], df["volume"])
            bc_point = BCPoint(
                date=str(row["date"]),
                price=float(row["high"]),
                volume_level=volume_level,
                is_extremum=(idx == peak_idx),
                confidence_score=score,  # 自定义字段，用于置信度计算
            )

        # SC 点增强识别
        sc_candidates = []
        for idx in df.nsmallest(5, "low").index:
            row = df.loc[idx]
            vol_rank = row["vol_rank"]
            lower_shadow_ratio = row["lower_shadow_ratio"]

            # 评分系统
            score = 0
            if vol_rank > _VOL_HIGH_THRESHOLD:  # 放量
                score += 2
            elif vol_rank < _VOL_LOW_THRESHOLD:  # 极度缩量（恐慌后无人卖出）
                score += 1

            if lower_shadow_ratio > _SHADOW_LONG_THRESHOLD:  # 长下影
                score += 2
            elif lower_shadow_ratio > _SHADOW_MEDIUM_THRESHOLD:
                score += 1

            # 检查后续反弹
            trough_pos = df.index.get_loc(idx)
            if trough_pos < len(df) - 5:
                subsequent_high = df.iloc[trough_pos + 1 : trough_pos + 10]["close"].max()
                trough_price = row["low"]
                if (subsequent_high - trough_price) / trough_price > _CONFIRM_RISE_PCT:
                    score += 2  # 有确认反弹

            sc_candidates.append((idx, score, row))

        # 选择最佳 SC 候选
        sc_candidates.sort(key=lambda x: x[1], reverse=True)
        if sc_candidates:
            best_sc = sc_candidates[0]
            idx, score, row = best_sc
            volume_level = self._classify_volume(row["volume"], df["volume"])
            sc_point = SCPoint(
                date=str(row["date"]),
                price=float(row["low"]),
                volume_level=volume_level,
                is_extremum=(idx == trough_idx),
                confidence_score=score,
            )

        return bc_point, sc_point

    def _classify_volume(self, volume: float, volume_series: pd.Series) -> VolumeLevel:
        """相对量能分类"""
        mean_vol = volume_series.mean()
        vol_ratio = volume / mean_vol

        if vol_ratio > 2.0:
            return VolumeLevel.EXTREME_HIGH
        elif vol_ratio > 1.5:
            return VolumeLevel.HIGH
        elif vol_ratio > 0.7:
            return VolumeLevel.AVERAGE
        elif vol_ratio > 0.4:
            return VolumeLevel.LOW
        else:
            return VolumeLevel.EXTREME_LOW

    def _detect_limit_moves(self, df: pd.DataFrame) -> List[LimitMove]:
        """检测涨跌停与炸板异动"""
        limit_moves = []

        recent = df.tail(20)

        for idx, row in recent.iterrows():
            pct_change = (row["close"] - row["open"]) / row["open"]
            is_limit_up = pct_change > 0.095
            is_limit_down = pct_change < -0.095

            if not is_limit_up and not is_limit_down:
                continue

            high_change = (row["high"] - row["open"]) / row["open"]
            low_change = (row["low"] - row["open"]) / row["open"]

            if is_limit_up:
                if high_change < 0.095:
                    move_type = LimitMoveType.BREAK_LIMIT_UP
                    is_broken = True
                else:
                    move_type = LimitMoveType.LIMIT_UP
                    is_broken = False
            else:
                if low_change > -0.095:
                    move_type = LimitMoveType.BREAK_LIMIT_DOWN
                    is_broken = True
                else:
                    move_type = LimitMoveType.LIMIT_DOWN
                    is_broken = False

            volume_level = self._classify_volume(row["volume"], df["volume"])

            limit_moves.append(
                LimitMove(
                    date=str(row["date"]),
                    move_type=move_type,
                    price=float(row["close"]),
                    volume_level=volume_level,
                    is_broken=is_broken,
                )
            )

        return limit_moves

    def _analyze_chips(self, df: pd.DataFrame, structure: WyckoffStructure) -> ChipAnalysis:
        """筹码微观分析"""
        analysis = ChipAnalysis()

        recent = df.tail(20)

        price_change = (recent["close"].iloc[-1] - recent["close"].iloc[0]) / recent["close"].iloc[
            0
        ]
        volume_change = (recent["volume"].iloc[-1] - recent["volume"].iloc[0]) / recent[
            "volume"
        ].iloc[0]

        if price_change > 0.05 and volume_change < -0.3:
            analysis.volume_price_divergence = True
            analysis.warnings.append("量价背离：价格上涨但量能萎缩")

        if price_change < -0.05 and volume_change > 0.3:
            analysis.distribution_signature = True

        if price_change > 0.05 and volume_change > 0.2:
            analysis.absorption_signature = True
            analysis.institutional_footprint = True

        if structure.phase == WyckoffPhase.MARKUP:
            vol_trend = pd.Series(recent["volume"].values).corr(pd.Series(range(len(recent))))
            if vol_trend < -0.3:
                analysis.warnings.append("上涨中量能递减，需警惕")

        return analysis

    def _run_stress_tests(
        self, df: pd.DataFrame, structure: WyckoffStructure, signal: WyckoffSignal
    ) -> List[StressTest]:
        """反事实压力测试"""
        stress_tests = []

        if structure.trading_range_low is None or structure.current_price is None:
            return stress_tests

        current = structure.current_price
        low = structure.trading_range_low

        test1 = StressTest(
            scenario_name="假突破跌破",
            scenario_description=f"如果价格跌破支撑位 {low:.2f} 会怎样",
            outcome="",
            passes=False,
        )
        break_scenario = current * 0.97
        if break_scenario < low:
            test1.outcome = "支撑失守，可能加速下跌"
            test1.risk_level = "高"
            test1.passes = False
        else:
            test1.outcome = "仍在支撑上方运行"
            test1.risk_level = "低"
            test1.passes = True
        stress_tests.append(test1)

        test2 = StressTest(
            scenario_name="恶劣天气",
            scenario_description="如果大盘暴跌 5% 会怎样",
            outcome="",
            passes=False,
        )
        adverse_scenario = current * 0.95
        if adverse_scenario < low:
            test2.outcome = "可能被拖累跌破支撑"
            test2.risk_level = "高"
            test2.passes = False
        else:
            test2.outcome = "有支撑保护"
            test2.risk_level = "中"
            test2.passes = True
        stress_tests.append(test2)

        test3 = StressTest(
            scenario_name="假突破高",
            scenario_description="如果现在入场后假突破怎么办",
            outcome="",
            passes=False,
        )
        if signal.signal_type == "spring":
            test3.outcome = "需等待二次确认"
            test3.risk_level = "中"
            test3.passes = True
        else:
            test3.outcome = "未到Spring，等待信号"
            test3.risk_level = "低"
            test3.passes = True
        stress_tests.append(test3)

        return stress_tests

    def _apply_t1_enforcement(
        self,
        signal: WyckoffSignal,
        trading_plan: Optional[TradingPlan],
        stress_tests: List[StressTest],
    ) -> None:
        """T+1 零容错强制执行"""
        if trading_plan is None:
            return

        if signal.signal_type == "spring":
            signal.description += " [Spring冷静期3天]"
            trading_plan.spring_cooldown_days = 3
            trading_plan.direction = "空仓观望"

        has_high_risk = any(st.risk_level == "高" for st in stress_tests)

        if has_high_risk and signal.signal_type == "spring":
            trading_plan.t1_blocked = True
            trading_plan.direction = "T+1零容错阻止，空仓观望"
            trading_plan.trigger_condition = "风险过高，禁止入场"

    def _determine_wyckoff_structure(
        self, df: pd.DataFrame, bc_point: Optional[BCPoint], sc_point: Optional[SCPoint]
    ) -> WyckoffStructure:
        """
        确定威科夫宏观阶段与结构边界

        阶段判断顺序：
        1. 先检测最近 60 日是否处于横盘震荡区间（TR）
           - 判定标准：(最高-最低)/最低 <= 20%，且近期短趋势幅度 < 5%
        2. 若处于 TR，则看 TR 前的趋势方向：
           - TR 前有明显下跌（>10%） → ACCUMULATION
           - TR 前有明显上涨（>10%） → DISTRIBUTION
           - 前期趋势不明显 → UNKNOWN（保守处理）
        3. 若不处于 TR，则按近期短趋势方向判定：
           - 上行趋势 → MARKUP
           - 下行趋势 → MARKDOWN
           - 趋势不明 → UNKNOWN
        4. BC / SC 位置仅用于支撑阻力与边界辅助，不主导阶段判断
        """
        structure = WyckoffStructure()
        structure.bc_point = bc_point
        structure.sc_point = sc_point

        # --- Step 1：计算近 60 日价格振幅，判断是否处于 TR ---
        recent_60 = df.tail(60)
        price_high = float(recent_60["high"].max())
        price_low = float(recent_60["low"].min())
        current_price = float(df.iloc[-1]["close"])
        ma5 = float(df.tail(5)["close"].mean())
        ma20 = float(df.tail(20)["close"].mean())
        total_range_pct = (price_high - price_low) / price_low if price_low > 0 else 1.0
        relative_position = (
            (current_price - price_low) / (price_high - price_low)
            if price_high > price_low
            else 0.5
        )

        # 近 20 日 vs 前 20 日均价变化，衡量短期趋势
        if len(df) >= 40:
            recent_mean = float(df.tail(20)["close"].mean())
            prev_mean = float(df.iloc[-40:-20]["close"].mean())
        else:
            recent_mean = float(df.tail(10)["close"].mean())
            prev_mean = float(df.head(10)["close"].mean())
        short_trend_pct = (recent_mean - prev_mean) / prev_mean if prev_mean > 0 else 0.0

        is_in_trading_range = (total_range_pct <= 0.20) and (abs(short_trend_pct) < 0.05)

        if is_in_trading_range:
            # --- Step 2：TR 内，看 TR 前的方向来区分 Accumulation vs Distribution ---
            # 用 TR 起点前 40 根 K 线的头尾收盘价判断先前趋势
            prior_window = df.iloc[:-60] if len(df) > 60 else pd.DataFrame()
            if len(prior_window) >= 10:
                prior_first = float(prior_window["close"].iloc[0])
                prior_last = float(prior_window["close"].iloc[-1])
                prior_trend_pct = (
                    (prior_last - prior_first) / prior_first if prior_first > 0 else 0.0
                )
            else:
                prior_trend_pct = 0.0

            if prior_trend_pct < -0.10:
                # TR 前有明显下跌：主力可能正在低位吸筹 → Accumulation
                structure.phase = WyckoffPhase.ACCUMULATION
            elif prior_trend_pct > 0.10:
                # TR 前有明显上涨：主力可能正在高位派发 → Distribution
                structure.phase = WyckoffPhase.DISTRIBUTION
            else:
                # 前期趋势不明显时，结合 BC/SC、均线位置和当前相对位置做回退判定。
                if relative_position <= 0.40 and bc_point is not None:
                    structure.phase = WyckoffPhase.ACCUMULATION
                elif (relative_position >= 0.55 or short_trend_pct >= 0.03) and (
                    (current_price > ma20 * 0.97 and ma5 >= ma20 * 0.97)
                    or (current_price > ma5 and relative_position >= 0.50)
                ):
                    structure.phase = WyckoffPhase.MARKUP
                elif (
                    bc_point is not None
                    and current_price <= bc_point.price * 0.90
                    and current_price < ma20
                    and ma5 <= ma20
                    and short_trend_pct <= 0
                ):
                    structure.phase = WyckoffPhase.MARKDOWN
                else:
                    structure.phase = WyckoffPhase.UNKNOWN
                    logger.debug(
                        "TR 前趋势幅度不足 10%%（prior_trend=%.2f%%），且 BC/SC "
                        "回退判定不足，降级为 UNKNOWN",
                        prior_trend_pct * 100,
                    )
        else:
            # --- Step 3：非 TR，按短期趋势方向判定 Markup / Markdown ---
            if short_trend_pct >= 0.03 and (
                (current_price > ma20 and ma5 >= ma20)
                or (current_price > ma5 and relative_position >= 0.50)
            ):
                structure.phase = WyckoffPhase.MARKUP
            elif (
                short_trend_pct >= 0.015
                and current_price > ma20
                and ma5 >= ma20 * 0.98
                and relative_position >= 0.70
            ):
                structure.phase = WyckoffPhase.MARKUP
            elif (
                short_trend_pct >= 0.05
                and ma5 >= ma20
                and current_price >= ma20 * 0.99
                and relative_position >= 0.65
            ):
                # 强势上涨过程中的正常回撤不应直接降级为 UNKNOWN。
                structure.phase = WyckoffPhase.MARKUP
            elif short_trend_pct <= -0.03 and current_price < ma20:
                structure.phase = WyckoffPhase.MARKDOWN
            elif (
                bc_point is not None
                and current_price <= bc_point.price * 0.90
                and current_price < ma20
                and ma5 <= ma20
                and short_trend_pct <= 0
            ):
                structure.phase = WyckoffPhase.MARKDOWN
            elif (
                bc_point is not None
                and short_trend_pct <= -0.04
                and relative_position <= 0.20
                and current_price <= bc_point.price * 0.78
            ):
                structure.phase = WyckoffPhase.MARKDOWN
            elif (
                sc_point is not None
                and short_trend_pct >= 0.03
                and total_range_pct <= 0.60
                and relative_position >= 0.75
                and current_price >= sc_point.price * 1.20
                and current_price > ma20
                and ma5 >= ma20 * 0.99
            ):
                structure.phase = WyckoffPhase.MARKUP
            else:
                structure.phase = WyckoffPhase.UNKNOWN

        # --- 区间边界计算（取近 30 日极值） ---
        recent_df = df.tail(30)
        structure.trading_range_high = float(recent_df["high"].max())
        structure.trading_range_low = float(recent_df["low"].min())
        structure.current_price = current_price
        structure.current_date = str(df.iloc[-1]["date"])

        if structure.phase == WyckoffPhase.UNKNOWN:
            structure.unknown_candidate = self._classify_unknown_candidate(
                df=df,
                structure=structure,
            )
        else:
            structure.unknown_candidate = ""

        # --- 支撑 / 阻力位（BC/SC 作为关键锚点） ---
        if bc_point is not None:
            structure.support_levels.append(
                SupportResistance(
                    level=bc_point.price,
                    type="support",
                    source="BC",
                    strength=0.8,
                )
            )
        if sc_point is not None:
            structure.resistance_levels.append(
                SupportResistance(
                    level=sc_point.price,
                    type="resistance",
                    source="SC",
                    strength=0.8,
                )
            )

        return structure

    def _classify_unknown_candidate(
        self,
        df: pd.DataFrame,
        structure: WyckoffStructure,
    ) -> str:
        if structure.phase != WyckoffPhase.UNKNOWN or df.empty:
            return ""

        if structure.trading_range_low is None or structure.trading_range_high is None:
            return "unknown_range"

        last_row = df.iloc[-1]
        close_price = float(last_row["close"])
        open_price = float(last_row["open"])
        high_price = float(last_row["high"])
        low_price = float(last_row["low"])
        body = abs(close_price - open_price)
        upper_wick = high_price - max(close_price, open_price)
        lower_wick = min(close_price, open_price) - low_price
        avg_vol20 = float(df.tail(min(20, len(df)))["volume"].mean())
        vol_ratio = float(last_row["volume"]) / avg_vol20 if avg_vol20 > 0 else 1.0

        range_low = structure.trading_range_low
        range_high = structure.trading_range_high
        if range_high <= range_low:
            return "unknown_range"

        range_span = range_high - range_low
        relative_position = (close_price - range_low) / range_span
        close_location = (close_price - low_price) / max(high_price - low_price, 0.01)

        if (
            relative_position <= 0.38
            and close_location >= 0.58
            and (lower_wick > max(body, 0.01) or vol_ratio >= 1.05)
        ):
            return "sc_st_candidate"
        if (
            relative_position <= 0.50
            and close_price >= open_price
            and close_location >= 0.62
            and vol_ratio >= 0.95
        ):
            return "phase_a_candidate"
        if relative_position >= 0.62 and upper_wick > max(body * 1.2, 0.01) and vol_ratio >= 1.0:
            return "upthrust_candidate"
        if 0.38 < relative_position < 0.68:
            return "phase_b_range"
        return "unknown_range"

    def _detect_wyckoff_signals(
        self, df: pd.DataFrame, structure: WyckoffStructure
    ) -> WyckoffSignal:
        """
        检测威科夫事件信号

        产出的 signal_type 为结构事件枚举，只允许：
        spring / utad / sos_candidate / no_signal
        严禁将宏观阶段名（如 'accumulation'）写入 signal_type。
        """
        signal = WyckoffSignal()
        signal.phase = structure.phase

        last_price = structure.current_price
        last_vol = df.iloc[-1]["volume"]
        last_low = float(df.iloc[-1]["low"])
        last_high = float(df.iloc[-1]["high"])
        volume_level = self._classify_volume(last_vol, df["volume"])
        signal.volume_confirmation = volume_level

        # A 股铁律：Distribution / Markdown 阶段禁止给任何做多方向信号
        if structure.phase in [WyckoffPhase.MARKDOWN, WyckoffPhase.DISTRIBUTION]:
            signal.signal_type = "no_signal"
            signal.confidence = ConfidenceLevel.D
            signal.description = self._describe_markdown_context(df, structure)
            return signal

        # 阶段不明确：保守处理
        if structure.phase == WyckoffPhase.UNKNOWN:
            signal.signal_type = "no_signal"
            signal.confidence = ConfidenceLevel.D
            signal.description = self._describe_unknown_context(df, structure)
            return signal

        # BC 未定位：无法做任何方向推演（SPEC RC §4.3 强制规则）
        if structure.bc_point is None:
            signal.signal_type = "no_signal"
            signal.confidence = ConfidenceLevel.D
            signal.description = "未找到 BC 点，无法确认趋势方向，放弃"
            return signal

        # --- Spring 检测：仅在 ACCUMULATION 阶段有效 ---
        # Spring = 价格刺穿或接近区间下边界，且随即快速收回
        if structure.phase == WyckoffPhase.ACCUMULATION and structure.trading_range_low is not None:
            low_bound = structure.trading_range_low
            close_near_low = last_price <= low_bound * 1.018
            intraday_spring = last_low <= low_bound * 1.01 and last_price >= last_low * 1.015
            if close_near_low or intraday_spring:
                signal.signal_type = "spring"
                signal.trigger_price = last_price
                signal.confidence = ConfidenceLevel.B
                signal.description = (
                    f"价格回踩震荡区间下边界 {low_bound:.2f} 附近，"
                    "检测到日线 Spring 候选信号，需等待 T+3 冷冻期后二次确认"
                )
                signal.t1_risk评估 = self._assess_t1_risk(df, structure, last_price)
                return signal

            if len(df) >= 3:
                recent3 = df.tail(3)
                prior_close = float(df.iloc[-2]["close"])
                recent_low3 = float(recent3["low"].min())
                spring_cluster = recent_low3 <= low_bound * 1.02
                bullish_reclaim = last_price >= prior_close * 1.02
                last_close_strong = last_price >= (last_high + last_low) / 2
                volume_contracting = last_vol <= float(recent3.iloc[:-1]["volume"].max())
                if spring_cluster and bullish_reclaim and last_close_strong and volume_contracting:
                    structure.phase = WyckoffPhase.MARKUP
                    signal.phase = WyckoffPhase.MARKUP
                    signal.signal_type = "sos_candidate"
                    signal.trigger_price = last_price
                    signal.confidence = ConfidenceLevel.B
                    signal.description = (
                        "Spring→ST→SOS 三步确认完成，结构从 Phase C/Phase D 观察区"
                        "转入右侧 Markup 启动段"
                    )
                    return signal

        # --- SOS 候选：价格接近区间上边界，可能进入 Markup ---
        if signal.signal_type == "no_signal" and structure.trading_range_high is not None:
            high_bound = structure.trading_range_high
            recent_breakout = last_price >= df.tail(5)["close"].max() * 0.995
            close_strong = last_price >= last_high * 0.985
            if last_price >= high_bound * 0.98 or (
                structure.phase == WyckoffPhase.MARKUP and recent_breakout and close_strong
            ):
                signal.signal_type = "sos_candidate"
                signal.trigger_price = last_price
                signal.confidence = (
                    ConfidenceLevel.B
                    if structure.phase == WyckoffPhase.MARKUP
                    else ConfidenceLevel.C
                )
                signal.description = (
                    f"价格向震荡区间上边界 {high_bound:.2f} 发起攻击，"
                    "出现日线 SOS/LPS 观察信号，仅允许按 V3.0 纪律等待确认"
                )
                if structure.phase == WyckoffPhase.MARKUP:
                    signal.description = self._describe_markup_context(
                        df, structure, default=signal.description
                    )
                return signal

        # --- 无明确事件信号：保守降级为空仓观望（不得编造方向结论）---
        # SPEC §12 强制保守降级清单：信号不明确时输出 no_signal，置信度 D
        signal.signal_type = "no_signal"
        signal.confidence = ConfidenceLevel.D
        if structure.phase == WyckoffPhase.MARKUP:
            signal.description = self._describe_markup_context(df, structure)
        else:
            signal.description = (
                f"当前处于 {structure.phase.value} 阶段，"
                "价格在区间内部运行，无明确事件信号，建议空仓观望，等待 Spring 或 SOS 确认"
            )
        return signal

    def _describe_markdown_context(self, df: pd.DataFrame, structure: WyckoffStructure) -> str:
        last_row = df.iloc[-1]
        open_price = float(last_row["open"])
        close_price = float(last_row["close"])
        low_price = float(last_row["low"])
        body = abs(close_price - open_price)
        lower_wick = min(close_price, open_price) - low_price
        avg_vol20 = float(df.tail(min(20, len(df)))["volume"].mean())
        vol_ratio = float(last_row["volume"]) / avg_vol20 if avg_vol20 > 0 else 1.0
        recent_low = float(df.tail(min(20, len(df)))["low"].min())

        if (
            lower_wick > max(body * 1.5, 0.01)
            and vol_ratio >= 1.5
            and low_price <= recent_low * 1.01
        ):
            return "当前处于 Markdown 延续阶段，但日线出现 SC 候选异动，仍需空仓观望，等待 AR/ST 结构补全"

        return "当前处于 Markdown/派发下跌阶段，A 股禁止做空，建议空仓观望"

    def _describe_unknown_context(self, df: pd.DataFrame, structure: WyckoffStructure) -> str:
        if structure.unknown_candidate == "phase_a_candidate":
            return (
                "阶段不明确，但正在演化为 Phase A/AR 反弹观察区，建议继续空仓等待 ST 或 TR 边界明确"
            )
        if structure.unknown_candidate == "sc_st_candidate":
            return "阶段不明确，当前出现 SC/ST 候选扰动，但证据不足，建议空仓观望"
        if structure.unknown_candidate == "upthrust_candidate":
            return "阶段不明确，当前更像 Phase B / Upthrust 观察区，建议空仓等待方向重新选择"
        if structure.unknown_candidate == "phase_b_range":
            return "阶段不明确，当前更像 Phase B 震荡观察区，建议等待 TR 边界和 ST/UT 进一步清晰"

        last_row = df.iloc[-1]
        avg_vol20 = float(df.tail(min(20, len(df)))["volume"].mean())
        vol_ratio = float(last_row["volume"]) / avg_vol20 if avg_vol20 > 0 else 1.0
        close_price = float(last_row["close"])
        open_price = float(last_row["open"])
        high_price = float(last_row["high"])
        low_price = float(last_row["low"])
        body = abs(close_price - open_price)
        upper_wick = high_price - max(close_price, open_price)
        lower_wick = min(close_price, open_price) - low_price
        range_low = structure.trading_range_low
        range_high = structure.trading_range_high
        relative_position = 0.5
        close_location = 0.5
        if range_low is not None and range_high is not None and range_high > range_low:
            range_span = range_high - range_low
            relative_position = (close_price - range_low) / range_span
            close_location = (close_price - low_price) / max(high_price - low_price, 0.01)

        if (
            structure.sc_point is not None
            and close_price >= structure.sc_point.price * 1.08
            and vol_ratio >= 1.2
        ):
            return (
                "阶段不明确，但正在演化为 Phase A/AR 反弹观察区，建议继续空仓等待 ST 或 TR 边界明确"
            )
        if relative_position >= 0.62 and upper_wick > max(body * 1.2, 0.01) and vol_ratio >= 1.0:
            return "阶段不明确，当前更像 Phase B / Upthrust 观察区，建议空仓等待方向重新选择"
        if (
            relative_position <= 0.38
            and close_location >= 0.58
            and (lower_wick > max(body, 0.01) or vol_ratio >= 1.05)
        ):
            return "阶段不明确，当前出现 SC/ST 候选扰动，但证据不足，建议空仓观望"
        if (
            relative_position <= 0.50
            and close_price >= open_price
            and close_location >= 0.62
            and vol_ratio >= 0.95
        ):
            return (
                "阶段不明确，但正在演化为 Phase A/AR 反弹观察区，建议继续空仓等待 ST 或 TR 边界明确"
            )
        if 0.38 < relative_position < 0.68:
            return "阶段不明确，当前更像 Phase B 震荡观察区，建议等待 TR 边界和 ST/UT 进一步清晰"
        return "阶段不明确，当前存在较强不确定性，建议空仓观望"

    def _describe_markup_context(
        self,
        df: pd.DataFrame,
        structure: WyckoffStructure,
        default: Optional[str] = None,
    ) -> str:
        last_row = df.iloc[-1]
        open_price = float(last_row["open"])
        close_price = float(last_row["close"])
        high_price = float(last_row["high"])
        low_price = float(last_row["low"])
        body = abs(close_price - open_price)
        upper_wick = high_price - max(close_price, open_price)
        lower_wick = min(close_price, open_price) - low_price
        avg_vol20 = float(df.tail(min(20, len(df)))["volume"].mean())
        vol_ratio = float(last_row["volume"]) / avg_vol20 if avg_vol20 > 0 else 1.0
        recent_5 = df.tail(min(5, len(df)))
        recent_10 = df.tail(min(10, len(df)))
        prior_window = df.iloc[:-5] if len(df) > 5 else pd.DataFrame()
        prior_ceiling = (
            float(prior_window.tail(min(40, len(prior_window)))["high"].max())
            if not prior_window.empty
            else None
        )
        recent_low5 = float(recent_5["low"].min())
        recent_high10 = float(recent_10["high"].max())
        recent_spread_avg = float((recent_10["high"] - recent_10["low"]).mean())
        spread = high_price - low_price
        bc_price = (
            structure.bc_point.price
            if structure.bc_point is not None
            else structure.trading_range_high
        )

        if prior_ceiling is not None and close_price > prior_ceiling * 1.01:
            if low_price <= prior_ceiling * 1.01 and close_price >= prior_ceiling * 1.02:
                return (
                    f"当前处于 Phase E 突破后的 BUEC/LPS 回踩确认区，"
                    f"价格回测 {prior_ceiling:.2f} 一线后重新站稳"
                )
            if vol_ratio >= 1.0:
                return (
                    f"当前处于 Phase E Markup 延续段，价格已跃过前高 {prior_ceiling:.2f}，"
                    "出现 Phase E / SOS 动能扩张信号"
                )
            return "当前处于 Phase E（主升浪）延续段，趋势仍由多头掌控，优先按持仓保护思路处理"

        if bc_price is not None and close_price > bc_price * 1.01:
            if low_price <= bc_price * 1.01 and vol_ratio < 1.0:
                return (
                    f"当前处于 Phase E 突破后的 BUEC/LPS 回踩确认区，"
                    f"价格回测 {bc_price:.2f} 一线后重新站稳"
                )
            if vol_ratio >= 1.05:
                return (
                    f"当前处于 Phase E Markup 延续段，价格已跃过 BC {bc_price:.2f}，"
                    "出现 Phase E / SOS 动能扩张信号"
                )
            return "当前处于 Phase E Markup 延续段，趋势保持强势，优先按持仓保护思路处理"

        if lower_wick > max(body * 1.0, 0.01) and low_price <= recent_low5 * 1.005:
            return "当前处于 Markup 回踩中的 Shakeout/Test 观察区，轻仓试探需等待确认下影吸收有效"

        if close_price <= recent_low5 * 1.05 and vol_ratio < 0.95:
            return "当前处于 Markup 回踩中的 Lack of Supply / Test 观察区，等待缩量测试结束"

        if (
            spread <= recent_spread_avg * 0.90
            and vol_ratio <= 1.15
            and close_price < recent_high10 * 0.995
        ):
            return (
                "当前处于 Markup 中段的 Lack of Supply 蓄势区，持有者继续观察，空仓者等待更优击球点"
            )

        if (
            upper_wick > max(body * 1.5, 0.01)
            and vol_ratio < 1.0
            and bc_price is not None
            and high_price >= bc_price * 0.97
        ):
            return "当前处于 Markup 上沿的 Lack of Demand 警戒区，需防冲高受阻后的再平衡"

        return default or (
            "当前处于 Markup 过程中，价格在区间内部运行，无明确事件信号，"
            "建议空仓观望，等待 LPS、Test 或突破后的 BUEC 结构"
        )

    def _assess_t1_risk(
        self, df: pd.DataFrame, structure: WyckoffStructure, entry_price: float
    ) -> str:
        """T+1 风险评估"""
        recent = df.tail(10)

        avg_daily_range = (recent["high"] - recent["low"]).mean()
        range_pct = avg_daily_range / entry_price

        if range_pct > 0.05:
            risk_level = "高"
        elif range_pct > 0.03:
            risk_level = "中"
        else:
            risk_level = "低"

        if structure.bc_point is not None:
            distance = abs(entry_price - structure.bc_point.price) / structure.bc_point.price
            if distance < 0.10:
                support_strength = "强"
            elif distance < 0.20:
                support_strength = "中"
            else:
                support_strength = "弱"
        else:
            support_strength = "未确定"

        return f"基于10日平均振幅{range_pct * 100:.1f}%，风险等级{risk_level}，支撑强度{support_strength}"

    def _calculate_risk_reward(
        self, df: pd.DataFrame, structure: WyckoffStructure, signal: WyckoffSignal
    ) -> RiskRewardProjection:
        """计算盈亏比"""
        proj = RiskRewardProjection()

        current_price = structure.current_price
        proj.entry_price = current_price

        if current_price is None:
            return proj

        if structure.phase in {WyckoffPhase.ACCUMULATION, WyckoffPhase.MARKUP}:
            if structure.trading_range_low is not None:
                proj.stop_loss = structure.trading_range_low * 0.98
            elif structure.sc_point is not None:
                proj.stop_loss = structure.sc_point.price * 0.99
            if structure.bc_point is not None:
                proj.first_target = structure.bc_point.price
            elif structure.trading_range_high is not None:
                proj.first_target = structure.trading_range_high
        elif signal.signal_type != "no_signal":
            if structure.trading_range_low is not None:
                proj.stop_loss = structure.trading_range_low * 0.98
            if structure.trading_range_high is not None:
                proj.first_target = structure.trading_range_high
        elif (
            structure.phase == WyckoffPhase.UNKNOWN
            and structure.trading_range_low is not None
            and structure.trading_range_high is not None
            and any(keyword in signal.description for keyword in ("Phase A/AR", "SC/ST"))
        ):
            proj.stop_loss = structure.trading_range_low * 0.98
            proj.first_target = structure.trading_range_high

        if proj.stop_loss is not None:
            proj.risk_amount = current_price - proj.stop_loss
        if proj.first_target is not None:
            proj.reward_amount = proj.first_target - current_price

        if proj.risk_amount and proj.risk_amount > 0:
            proj.reward_risk_ratio = proj.reward_amount / proj.risk_amount
            if structure.phase == WyckoffPhase.UNKNOWN:
                if "Phase A/AR" in signal.description:
                    proj.structure_based = f"基于 Phase A/AR 候选结构边界 {structure.trading_range_low} - {structure.trading_range_high}"
                elif "SC/ST" in signal.description:
                    proj.structure_based = f"基于 SC/ST 候选结构边界 {structure.trading_range_low} - {structure.trading_range_high}"
                else:
                    proj.structure_based = f"基于结构边界 {structure.trading_range_low} - {structure.trading_range_high}"
            else:
                proj.structure_based = (
                    f"基于结构边界 {structure.trading_range_low} - {structure.trading_range_high}"
                )

        return proj

    def _build_trading_plan(
        self,
        structure: WyckoffStructure,
        signal: WyckoffSignal,
        risk_reward: RiskRewardProjection,
        stress_tests: Optional[List[StressTest]] = None,
    ) -> TradingPlan:
        """构建交易计划"""
        plan = TradingPlan()

        if signal.signal_type == "no_signal":
            plan.direction = "空仓观望"
            plan.confidence = signal.confidence
            plan.preconditions = "需等待明确信号"

            if structure.phase == WyckoffPhase.ACCUMULATION:
                plan.current_qualification = (
                    "当前处于 Phase B/Phase C 过渡观察区，优先等待 Spring、ST 或 SOS 确认"
                )
                plan.trigger_condition = (
                    f"关注 {structure.trading_range_low:.2f} 附近是否出现 Spring，"
                    "或确认阳线拉离下沿后的二次缩量回踩"
                    if structure.trading_range_low is not None
                    else "等待 Spring 或 SOS 明确信号"
                )
                plan.invalidation_point = (
                    f"有效跌破 {structure.trading_range_low:.2f} 则继续观望"
                    if structure.trading_range_low is not None
                    else "N/A"
                )
                plan.first_target = (
                    f"第一观察目标 {structure.bc_point.price:.2f}"
                    if structure.bc_point is not None
                    else "待确认"
                )
            elif structure.phase == WyckoffPhase.MARKUP:
                markup_context = signal.description or ""
                is_generic_markup_context = markup_context.startswith("当前处于 Markup 过程中")
                near_bc = (
                    structure.bc_point is not None
                    and structure.current_price is not None
                    and structure.current_price >= structure.bc_point.price * 0.93
                )
                if not is_generic_markup_context and any(
                    keyword in markup_context
                    for keyword in (
                        "Phase E",
                        "BUEC",
                        "Lack of Supply",
                        "Lack of Demand",
                        "Shakeout",
                        "Test",
                    )
                ):
                    plan.current_qualification = markup_context
                elif near_bc or (
                    risk_reward.reward_risk_ratio and risk_reward.reward_risk_ratio < 2.5
                ):
                    plan.current_qualification = (
                        "当前处于 Phase D/Markup 推进阶段，但已逼近 BC 压力区，"
                        "按 V3.0 纪律属于 No Trade Zone"
                    )
                else:
                    plan.current_qualification = "当前处于 Markup 早中段，等待更优 LPS/Backup 位置"
                lower_hint = (
                    structure.trading_range_low if structure.trading_range_low is not None else 0.0
                )
                bc_hint = (
                    structure.bc_point.price
                    if structure.bc_point is not None
                    else structure.trading_range_high
                )
                plan.trigger_condition = (
                    f"等待回踩 {lower_hint:.2f} 一带出现缩量 LPS，"
                    f"或放量突破 {bc_hint:.2f} 后回踩确认"
                )
                plan.invalidation_point = (
                    f"跌破 {structure.trading_range_low:.2f} 则放弃追踪当前上涨节奏"
                    if structure.trading_range_low is not None
                    else "N/A"
                )
                plan.first_target = (
                    f"第一目标 {structure.bc_point.price:.2f}"
                    if structure.bc_point is not None
                    else "待确认"
                )
                if not is_generic_markup_context and "Phase E" in markup_context:
                    plan.direction = "持有观察 / 空仓者观望"
                elif not is_generic_markup_context and (
                    "Shakeout" in markup_context or "BUEC" in markup_context
                ):
                    if risk_reward.reward_risk_ratio and risk_reward.reward_risk_ratio >= 0.3:
                        plan.direction = "买入观察 / 轻仓试探"
                elif not is_generic_markup_context and "Lack of Supply / Test" in markup_context:
                    if risk_reward.reward_risk_ratio and risk_reward.reward_risk_ratio < 0.5:
                        plan.current_qualification = (
                            "当前处于 Markup / Phase D 推进段的回踩测试区，"
                            "但按 V3.0 纪律仍属于 No Trade Zone"
                        )
                    plan.direction = "空仓观望"
                elif not is_generic_markup_context and "Lack of Supply" in markup_context:
                    plan.direction = "持有观察 / 空仓者观望"
            else:
                plan.current_qualification = signal.description
                if "Phase A/AR" in signal.description:
                    plan.trigger_condition = (
                        f"等待 {structure.trading_range_low:.2f} 一带完成 ST 缩量确认，"
                        f"或重新放量攻击 {structure.trading_range_high:.2f}"
                        if structure.trading_range_low is not None
                        and structure.trading_range_high is not None
                        else "等待 ST 缩量确认或 TR 上沿重新发起攻击"
                    )
                    plan.invalidation_point = (
                        f"有效失守 {structure.trading_range_low:.2f} 则放弃 Phase A/AR 设想"
                        if structure.trading_range_low is not None
                        else "失守近期低点则放弃 Phase A/AR 设想"
                    )
                    plan.first_target = (
                        f"第一观察目标 {structure.trading_range_high:.2f}"
                        if structure.trading_range_high is not None
                        else "第一观察目标 TR 上沿"
                    )
                elif "SC/ST" in signal.description:
                    plan.trigger_condition = (
                        "等待 SC 后的 AR 反弹出现，并观察 ST 二次回测是否缩量止跌"
                    )
                    plan.invalidation_point = (
                        f"若继续跌破 {structure.trading_range_low:.2f} 则回归更弱结构"
                        if structure.trading_range_low is not None
                        else "若继续跌破近期低点则回归更弱结构"
                    )
                    plan.first_target = (
                        f"第一观察目标 {structure.trading_range_high:.2f}"
                        if structure.trading_range_high is not None
                        else "第一观察目标 AR 高点确认"
                    )
                elif "Upthrust" in signal.description:
                    plan.trigger_condition = (
                        f"等待价格从 {structure.trading_range_high:.2f} 一带回落并重新选择方向"
                        if structure.trading_range_high is not None
                        else "等待上沿假突破回落后重新选择方向"
                    )
                    plan.invalidation_point = (
                        f"若继续站稳 {structure.trading_range_high:.2f} 上方，则当前 Upthrust 假设失效"
                        if structure.trading_range_high is not None
                        else "若继续强势上攻，则当前 Upthrust 假设失效"
                    )
                    plan.first_target = (
                        f"第一观察目标回到区间中枢，关注 {((structure.trading_range_low or 0.0) + (structure.trading_range_high or 0.0)) / 2:.2f}"
                        if structure.trading_range_low is not None
                        and structure.trading_range_high is not None
                        else "第一观察目标为区间中枢确认"
                    )
                elif "Phase B" in signal.description:
                    plan.trigger_condition = (
                        f"等待 {structure.trading_range_low:.2f}-{structure.trading_range_high:.2f} 区间边界被明确测试"
                        if structure.trading_range_low is not None
                        and structure.trading_range_high is not None
                        else "等待 TR 边界被再次明确测试"
                    )
                    plan.invalidation_point = "区间边界未明确前不执行"
                    plan.first_target = (
                        f"第一观察目标 {structure.trading_range_high:.2f}"
                        if structure.trading_range_high is not None
                        else "第一观察目标 TR 上沿"
                    )
                else:
                    plan.trigger_condition = "N/A"
                    plan.invalidation_point = "N/A"
                    plan.first_target = "N/A"
            return plan

        if structure.phase == WyckoffPhase.MARKDOWN:
            plan.direction = "空仓观望"
            plan.trigger_condition = "N/A"
            plan.invalidation_point = "N/A"
            plan.first_target = "N/A"
            plan.confidence = ConfidenceLevel.D
            plan.current_qualification = "当前处于 Markdown 阶段"
            plan.preconditions = "禁止做空"
            return plan

        plan.confidence = signal.confidence
        plan.current_qualification = signal.description
        plan.preconditions = "需大盘指数/所属板块不出现系统性单边暴跌"

        if risk_reward.reward_risk_ratio and risk_reward.reward_risk_ratio < 2.5:
            if structure.phase == WyckoffPhase.MARKUP:
                if "Spring→ST→SOS" in signal.description and risk_reward.reward_risk_ratio >= 1.2:
                    plan.direction = "做多观察 / 轻仓试探"
                elif "Phase E" in signal.description or "Lack of Supply" in signal.description:
                    plan.direction = "持有观察 / 空仓者观望"
                elif any(keyword in signal.description for keyword in ("BUEC", "Shakeout", "Test")):
                    plan.direction = "买入观察 / 轻仓试探"
                else:
                    plan.direction = "空仓观望"
            else:
                plan.direction = "空仓观望"
            plan.trigger_condition = "当前盈亏比不足 1:2.5，继续等待更优入场位置"
            plan.invalidation_point = "N/A"
            plan.first_target = "N/A"
            plan.preconditions = "仅当后续回踩或突破回踩使盈亏比达到 1:2.5 以上时再评估"
            return plan

        if signal.signal_type == "spring":
            plan.direction = "空仓观望"
            plan.trigger_condition = (
                f"T+3 冷冻期结束后，若价格仍守住 {structure.trading_range_low} "
                f"且出现放量确认，再等待缩量回踩不破后评估入场"
            )
            plan.invalidation_point = f"跌破 {structure.trading_range_low} 放弃 Spring 设想"
        else:
            plan.direction = "空仓观望"
            plan.trigger_condition = "等待价格突破震荡区间上边界并回踩确认"
            plan.invalidation_point = f"跌破 {structure.current_price * 0.95} 止损"

        if risk_reward.first_target is not None:
            plan.first_target = f"第一目标位 {risk_reward.first_target}"
        else:
            plan.first_target = "待确认"

        return plan

    def _create_no_signal_report(self, symbol: str, period: str, reason: str) -> WyckoffReport:
        """创建无信号报告"""
        structure = WyckoffStructure()
        structure.phase = WyckoffPhase.UNKNOWN

        signal = WyckoffSignal()
        signal.signal_type = "no_signal"
        signal.confidence = ConfidenceLevel.D
        signal.description = (
            f"当前图表信号杂乱，处于不可交易区（No Trade Zone），建议放弃。原因: {reason}"
        )

        risk_reward = RiskRewardProjection()

        plan = TradingPlan()
        plan.direction = "空仓观望"
        plan.trigger_condition = "N/A"
        plan.invalidation_point = "N/A"
        plan.first_target = "N/A"
        plan.confidence = ConfidenceLevel.D
        plan.current_qualification = signal.description

        return WyckoffReport(
            symbol=symbol,
            period=period,
            structure=structure,
            signal=signal,
            risk_reward=risk_reward,
            trading_plan=plan,
        )
