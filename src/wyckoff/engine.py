# -*- coding: utf-8 -*-
"""
v3.0 威科夫分析引擎 - 唯一入口
合并 analyzer.py + data_engine.py，100% 实现 Promote_v3.0.md
"""

from __future__ import annotations

import logging
from typing import List, Optional, Tuple

import numpy as np
import pandas as pd

from src.wyckoff.models import (
    BCPoint,
    ChipAnalysis,
    ConfidenceLevel,
    ConfidenceResult,
    ImageEvidenceBundle,
    LimitMove,
    LimitMoveType,
    MultiTimeframeContext,
    RiskRewardProjection,
    RiskRewardResult,
    Rule0Result,
    SCPoint,
    Step1Result,
    Step2Result,
    Step3Result,
    StressTest,
    TimeframeSnapshot,
    TradingPlan,
    V3CounterfactualResult,
    V3TradingPlan,
    VolumeLevel,
    WyckoffPhase,
    WyckoffReport,
    WyckoffSignal,
    WyckoffStructure,
)
from src.wyckoff.rules import V3Rules

logger = logging.getLogger(__name__)


class WyckoffEngine:
    """v3.0 威科夫分析引擎 - 唯一入口"""

    def __init__(
        self, lookback_days: int = 120, weekly_lookback: int = 180, monthly_lookback: int = 120
    ):
        self.lookback_days = lookback_days
        self.weekly_min_rows = 20
        self.monthly_min_rows = 12
        self.weekly_lookback = weekly_lookback  # 周线回看行数
        self.monthly_lookback = monthly_lookback  # 月线回看行数
        # 计算多周期分析所需的日线数据量
        # 周线: weekly_lookback周 × 7天
        # 月线: monthly_lookback月 × 30天
        weekly_days = weekly_lookback * 7
        monthly_days = monthly_lookback * 30
        self.multi_timeframe_lookback_days = max(lookback_days, weekly_days, monthly_days)
        self.rules = V3Rules()

    def _normalize_input_frame(self, df: pd.DataFrame) -> pd.DataFrame:
        frame = df.copy()
        frame["date"] = pd.to_datetime(frame["date"])
        return frame.sort_values("date").reset_index(drop=True)

    def _resample_ohlcv(self, df: pd.DataFrame, rule: str) -> pd.DataFrame:
        frame = self._normalize_input_frame(df).set_index("date")
        agg_dict = {
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        }
        if "amount" in frame.columns:
            agg_dict["amount"] = "sum"
        resampled = (
            frame.resample(rule, label="right", closed="right")
            .agg(agg_dict)
            .dropna(subset=["open", "high", "low", "close"])
            .reset_index()
        )
        return resampled

    def analyze(
        self,
        df: pd.DataFrame,
        symbol: str = "UNKNOWN",
        period: str = "日线",
        multi_timeframe: bool = False,
        image_evidence: Optional[ImageEvidenceBundle] = None,
    ) -> WyckoffReport:
        """主入口 - 严格按 v3.0 九步执行"""
        if multi_timeframe and period == "日线":
            return self._analyze_multiframe(df, symbol, image_evidence)
        return self._analyze_single(df, symbol, period, image_evidence)

    def _analyze_single(
        self,
        df: pd.DataFrame,
        symbol: str,
        period: str,
        image_evidence: Optional[ImageEvidenceBundle] = None,
    ) -> WyckoffReport:
        """单周期 - Step 0→5"""
        frame = self._normalize_input_frame(df)

        # 根据周期设置正确的最小行数
        if period == "日线":
            min_rows = 100
        elif period == "周线":
            min_rows = self.weekly_min_rows
        else:  # 月线
            min_rows = self.monthly_min_rows

        if frame is None or len(frame) < min_rows:
            reason = f"数据不足，需要至少 {min_rows} 根 K 线，当前只有 {len(frame) if frame is not None else 0} 根"
            return self._create_no_signal_report(symbol, period, reason)

        # 根据周期设置正确的回看行数
        if period == "日线":
            lookback = self.lookback_days
        elif period == "周线":
            lookback = min(len(frame), self.weekly_lookback)
        else:  # 月线
            lookback = min(len(frame), self.monthly_lookback)

        frame = frame.tail(lookback).reset_index(drop=True)

        # Step 0: BC/TR 定位扫描
        rule0 = self._step0_bc_tr_scan(frame)

        if rule0.validity == "insufficient":
            return self._create_no_signal_report(symbol, period, "BC和TR均不可见，结构不足")

        # Step 1: 大局观与阶段判定
        step1 = self._step1_phase_determine(frame, rule0)

        # 规则4: 诚实不作为原则 - 检测信号矛盾
        contradictions = 0
        if step1.phase == WyckoffPhase.UNKNOWN:
            contradictions += 1
        if rule0.validity in ("partial", "tr_fallback"):
            contradictions += 1

        struct_clarity = "清晰"
        if step1.phase == WyckoffPhase.UNKNOWN:
            struct_clarity = "混沌"
        elif contradictions >= 2:
            struct_clarity = "矛盾"

        if self.rules.rule4_no_trade_zone(contradictions, struct_clarity):
            return self._create_no_signal_report(
                symbol, period, "信号矛盾或结构混沌，进入No Trade Zone"
            )

        # Step 2: 努力与结果
        step2 = self._step2_effort_result(frame, step1)

        # Step 3: Spring/UTAD + T+1
        step3 = self._step3_phase_c_t1(frame, step1, rule0)

        # Step 3.5: 反事实
        step35 = self._step35_counterfactual(frame, step1, step2, step3, rule0)

        # Step 4: 盈亏比
        rr_result = self._step4_risk_reward(frame, step1, step3, rule0)

        # 置信度计算
        confidence = self._calc_confidence(rule0, step3, step35, rr_result, False)

        # Step 5: 交易计划
        v3_plan = self._step5_trading_plan(step1, step3, step35, rr_result, confidence, df=frame)

        # A 股铁律最终检查
        v3_plan = self._apply_a_stock_rules(step1, v3_plan)

        # 构建最终报告
        return self._build_report(
            symbol,
            period,
            frame,
            rule0,
            step1,
            step2,
            step3,
            step35,
            rr_result,
            confidence,
            v3_plan,
        )

    def _step0_bc_tr_scan(self, df: pd.DataFrame) -> Rule0Result:
        """Step 0: BC/TR 定位扫描"""
        bc_point, sc_point = self._scan_bc_sc(df)

        # 计算 TR 边界
        recent_60 = df.tail(60)
        tr_upper = float(recent_60["high"].max())
        tr_lower = float(recent_60["low"].min())

        bc_found = bc_point is not None
        sc_found = sc_point is not None
        tr_defined = (tr_upper - tr_lower) / tr_lower <= 0.25 if tr_lower > 0 else False

        # 使用规则5进行降级策略
        fallback = self.rules.rule5_bc_tr_fallback(bc_found, tr_defined)

        return Rule0Result(
            bc_found=bc_found,
            bc_position=bc_point,
            sc_found=sc_found,
            sc_position=sc_point,
            bc_in_chart=bc_found,
            tr_upper=tr_upper if tr_defined else None,
            tr_lower=tr_lower if tr_defined else None,
            tr_source="bc_ar"
            if bc_found
            else ("sc_spring" if sc_found else ("rolling_range" if tr_defined else "none")),
            validity=fallback["validity"],
            confidence_base=fallback["confidence_base"],
        )

    def _step1_phase_determine(self, df: pd.DataFrame, rule0: Rule0Result) -> Step1Result:
        """Step 1: 大局观与阶段判定（保留 analyzer.py 核心逻辑）"""
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

        # 近 20 日 vs 前 20 日均价变化
        if len(df) >= 40:
            recent_mean = float(df.tail(20)["close"].mean())
            prev_mean = float(df.iloc[-40:-20]["close"].mean())
        else:
            recent_mean = float(df.tail(10)["close"].mean())
            prev_mean = float(df.head(10)["close"].mean())
        short_trend_pct = (recent_mean - prev_mean) / prev_mean if prev_mean > 0 else 0.0

        is_in_trading_range = (total_range_pct <= 0.20) and (abs(short_trend_pct) < 0.05)

        phase = WyckoffPhase.UNKNOWN
        unknown_candidate = ""

        if is_in_trading_range:
            # TR 内，看 TR 前的方向
            prior_window = df.iloc[:-60] if len(df) > 60 else pd.DataFrame()
            if len(prior_window) >= 10:
                prior_first = float(prior_window["close"].iloc[0])
                prior_last = float(prior_window["close"].iloc[-1])
                prior_trend_pct = (
                    (prior_last - prior_first) / prior_first if prior_first > 0 else 0.0
                )
            else:
                prior_trend_pct = 0.0

            # 使用最佳版本阈值(a438a32)
            # 1. 前趋势下跌>10%
            # 2. 或 relative_position<=0.40 + BC定位
            if prior_trend_pct < -0.10:
                phase = WyckoffPhase.ACCUMULATION
            elif prior_trend_pct > 0.10:
                phase = WyckoffPhase.DISTRIBUTION
            else:
                if relative_position <= 0.40 and rule0.bc_found:
                    phase = WyckoffPhase.ACCUMULATION
                elif (relative_position >= 0.55 or short_trend_pct >= 0.03) and (
                    (current_price > ma20 * 0.97 and ma5 >= ma20 * 0.97)
                    or (current_price > ma5 and relative_position >= 0.50)
                ):
                    phase = WyckoffPhase.MARKUP
                elif (
                    rule0.bc_found
                    and rule0.bc_position is not None
                    and current_price <= rule0.bc_position.price * 0.85
                    and current_price < ma20 * 0.95
                    and ma5 <= ma20
                    and short_trend_pct <= -0.02
                ):
                    phase = WyckoffPhase.MARKDOWN
                else:
                    phase = WyckoffPhase.UNKNOWN
        else:
            # 非 TR，按短期趋势方向判定
            if short_trend_pct >= 0.03 and (
                (current_price > ma20 and ma5 >= ma20)
                or (current_price > ma5 and relative_position >= 0.50)
            ):
                phase = WyckoffPhase.MARKUP
            elif (
                short_trend_pct >= 0.015
                and current_price > ma20
                and ma5 >= ma20 * 0.98
                and relative_position >= 0.70
            ):
                phase = WyckoffPhase.MARKUP
            elif (
                short_trend_pct >= 0.05
                and ma5 >= ma20
                and current_price >= ma20 * 0.99
                and relative_position >= 0.65
            ):
                phase = WyckoffPhase.MARKUP
            # 使用最佳版本阈值(a438a32)
            elif short_trend_pct <= -0.05 and current_price < ma20 * 0.95:
                phase = WyckoffPhase.MARKDOWN
            elif (
                rule0.bc_found
                and rule0.bc_position is not None
                and current_price <= rule0.bc_position.price * 0.90
                and current_price < ma20
                and ma5 <= ma20
                and short_trend_pct <= 0
            ):
                phase = WyckoffPhase.MARKDOWN
            elif (
                rule0.bc_found
                and rule0.bc_position is not None
                and short_trend_pct <= -0.04
                and relative_position <= 0.25
                and current_price <= rule0.bc_position.price * 0.75
            ):
                phase = WyckoffPhase.MARKDOWN
            # 新增：非TR分支的Accumulation检测
            # 捕捉从下跌转向积累的早期形态
            elif (
                short_trend_pct <= -0.02
                and relative_position <= 0.40
                and current_price < ma20
                and ma5 <= ma20
                and (rule0.bc_found or rule0.sc_found)
            ):
                phase = WyckoffPhase.ACCUMULATION
            else:
                phase = WyckoffPhase.UNKNOWN

        # UNKNOWN 子状态分类
        if phase == WyckoffPhase.UNKNOWN:
            unknown_candidate = self._classify_unknown_candidate(df, phase, rule0)

        # Phase A/B/C/D/E 细分（创建临时Step1Result用于分类）
        sub_phase = ""
        temp_step1 = Step1Result(
            phase=phase,
            boundary_upper=rule0.tr_upper if rule0.tr_upper else price_high,
            boundary_lower=rule0.tr_lower if rule0.tr_lower else price_low,
        )
        if phase == WyckoffPhase.ACCUMULATION:
            sub_phase = self._classify_accumulation_sub_phase(df, temp_step1, rule0)
        elif phase == WyckoffPhase.DISTRIBUTION:
            sub_phase = self._classify_distribution_sub_phase(df, temp_step1, rule0)

        # 边界锚定
        boundary_upper = rule0.tr_upper if rule0.tr_upper else price_high
        boundary_lower = rule0.tr_lower if rule0.tr_lower else price_low
        boundary_source = []
        if rule0.bc_found:
            boundary_source.append("BC")
        if rule0.tr_source == "rolling_range":
            boundary_source.append("rolling_30d")

        return Step1Result(
            phase=phase,
            sub_phase=sub_phase,
            unknown_candidate=unknown_candidate,
            prior_trend_pct=0.0,
            is_in_tr=is_in_trading_range,
            short_trend_pct=short_trend_pct,
            relative_position=relative_position,
            ma5=ma5,
            ma20=ma20,
            boundary_upper=boundary_upper,
            boundary_lower=boundary_lower,
            boundary_source=boundary_source,
        )

    def _step2_effort_result(self, df: pd.DataFrame, step1: Step1Result) -> Step2Result:
        """Step 2: 努力与结果（含跳空缺口检测）"""
        phenomena = []
        accumulation_evidence = 0.0
        distribution_evidence = 0.0

        recent_20 = df.tail(20)
        if len(recent_20) < 10:
            return Step2Result()

        avg_vol = recent_20["volume"].mean()
        price_change = (recent_20["close"].iloc[-1] - recent_20["close"].iloc[0]) / recent_20[
            "close"
        ].iloc[0]
        vol_change = (recent_20["volume"].iloc[-1] - avg_vol) / avg_vol if avg_vol > 0 else 0

        # 成交额维度分析（基于amount）
        if "amount" in recent_20.columns and recent_20["amount"].notna().all():
            avg_amt = recent_20["amount"].mean()
            amt_change = (recent_20["amount"].iloc[-1] - avg_amt) / avg_amt if avg_amt > 0 else 0

            # 金额与成交量同步放大 → 确认异常
            if amt_change > 0.3 and vol_change > 0.3 and abs(price_change) < 0.02:
                distribution_evidence += 0.4
                phenomena.append("量额双放大滞涨")

            # 金额放大但量缩 → 大单交易（金额主导的吸筹/派发）
            if amt_change > 0.2 and vol_change < -0.2:
                if price_change > 0.02:
                    accumulation_evidence += 0.3
                    phenomena.append("大单推升（金额放量但量能萎缩）")
                elif price_change < -0.02:
                    distribution_evidence += 0.3
                    phenomena.append("大单砸盘（金额放量但量能萎缩）")

            # 金额萎缩但量放大 → 散户化交易
            if amt_change < -0.2 and vol_change > 0.2:
                phenomena.append("散户化交易（量增额缩）")

        # 放量滞涨 → 派发倾向
        if vol_change > 0.3 and abs(price_change) < 0.02:
            distribution_evidence += 0.3
            phenomena.append("放量滞涨")

        # 缩量上推 → 吸筹倾向
        if vol_change < -0.3 and price_change > 0.02:
            accumulation_evidence += 0.2
            phenomena.append("缩量上推")

        # 下边界供给枯竭
        if step1.boundary_lower > 0:
            recent_low = float(recent_20["low"].min())
            if recent_low <= step1.boundary_lower * 1.02:
                low_vol = recent_20[recent_20["low"] <= step1.boundary_lower * 1.02][
                    "volume"
                ].mean()
                if low_vol < avg_vol * 0.7:
                    accumulation_evidence += 0.3
                    phenomena.append("下边界供给枯竭")

        # 高位炸板遗迹
        for row in recent_20.itertuples():
            pct = (row.close - row.open) / row.open if row.open > 0 else 0
            if pct > 0.09 and row.high > row.close * 1.02:
                distribution_evidence += 0.3
                phenomena.append("高位炸板遗迹")
                break

        # 跳空缺口检测
        for i in range(1, len(recent_20)):
            prev_row = recent_20.iloc[i - 1]
            curr_row = recent_20.iloc[i]

            # 向上跳空缺口：当前最低价 > 前一天最高价
            if curr_row["low"] > prev_row["high"]:
                gap_size = (curr_row["low"] - prev_row["high"]) / prev_row["high"] * 100
                if gap_size > 1.0:  # 缺口大于1%
                    # 判断缺口类型
                    if curr_row["close"] > curr_row["open"]:  # 阳线
                        phenomena.append(f"向上突破缺口({gap_size:.1f}%)")
                        accumulation_evidence += 0.2
                    else:  # 阴线
                        phenomena.append(f"向上竭尽缺口({gap_size:.1f}%)")
                        distribution_evidence += 0.2

            # 向下跳空缺口：当前最高价 < 前一天最低价
            elif curr_row["high"] < prev_row["low"]:
                gap_size = (prev_row["low"] - curr_row["high"]) / prev_row["low"] * 100
                if gap_size > 1.0:  # 缺口大于1%
                    # 判断缺口类型
                    if curr_row["close"] < curr_row["open"]:  # 阴线
                        phenomena.append(f"向下逃逸缺口({gap_size:.1f}%)")
                        distribution_evidence += 0.3
                    else:  # 阳线
                        phenomena.append(f"向下竭尽缺口({gap_size:.1f}%)")
                        accumulation_evidence += 0.2

        net_bias = "neutral"
        if accumulation_evidence > distribution_evidence + 0.1:
            net_bias = "accumulation"
        elif distribution_evidence > accumulation_evidence + 0.1:
            net_bias = "distribution"

        return Step2Result(
            phenomena=phenomena,
            accumulation_evidence=round(accumulation_evidence, 2),
            distribution_evidence=round(distribution_evidence, 2),
            net_bias=net_bias,
        )

    def _step3_phase_c_t1(
        self, df: pd.DataFrame, step1: Step1Result, rule0: Rule0Result
    ) -> Step3Result:
        """Step 3: Spring/UTAD + T+1 风险"""
        spring_detected = False
        spring_quality = "无"
        spring_date = None
        spring_low_price = None
        utad_detected = False
        st_detected = False
        lps_confirmed = False
        spring_volume = ""

        # Spring 检测（在 ACCUMULATION 和 UNKNOWN 阶段都可能有效）
        if (
            step1.phase in (WyckoffPhase.ACCUMULATION, WyckoffPhase.UNKNOWN)
            and step1.boundary_lower > 0
        ):
            low_bound = step1.boundary_lower
            recent_20 = df.tail(20)

            for row in recent_20.itertuples():
                # 使用最佳版本阈值(a438a32)
                # 1. 允许3%的误差
                # 2. 收回到边界附近（97%）
                if row.low < low_bound * 1.03:  # 允许3%的误差
                    # 检查是否快速收回
                    if row.close >= low_bound * 0.97:  # 收回到边界附近
                        spring_detected = True
                        spring_date = str(row.date)
                        spring_low_price = float(row.low)

                        # 量能质量评估
                        vol_level = self.rules.rule1_relative_volume(row.volume, df["volume"])
                        spring_volume = vol_level

                        if vol_level in ("地量", "萎缩"):
                            spring_quality = "一级(缩量)"
                        else:
                            spring_quality = "二级(放量需ST)"

                        # LPS 验证（规则6）- 检查后续K线
                        post_spring_idx = df.index.get_loc(row.Index)
                        if post_spring_idx < len(df) - 3:
                            post_spring_df = df.iloc[post_spring_idx + 1 :]
                            lps_result = self.rules.rule6_spring_validation(
                                True, post_spring_df, spring_low_price
                            )
                            lps_confirmed = lps_result["lps_confirmed"]
                            if lps_confirmed:
                                spring_quality = lps_result["quality"]
                        break

            # 如果没有检测到Spring，检查是否有SOS信号
            if not spring_detected and step1.phase == WyckoffPhase.ACCUMULATION:
                # 优化：放宽SOS检测条件
                # 1. 价格突破上边界95%（原98%）
                # 2. 量能配合条件放宽
                if step1.boundary_upper > 0:
                    recent_5 = df.tail(5)
                    for row in recent_5.itertuples():
                        if row.close > step1.boundary_upper * 0.95:
                            # 检查量能配合（放宽条件）
                            vol_level = self.rules.rule1_relative_volume(
                                row.volume, df["volume"]
                            )
                            if vol_level in (
                                "高于平均",
                                "天量",
                                "平均",
                            ):  # 原：仅"高于平均"和"天量"
                                st_detected = True
                                break

        # UTAD 检测（DISTRIBUTION 阶段）
        if step1.phase == WyckoffPhase.DISTRIBUTION and step1.boundary_upper > 0:
            high_bound = step1.boundary_upper
            recent_10 = df.tail(10)

            for row in recent_10.itertuples():
                if row.high > high_bound * 1.02 and row.close <= high_bound * 1.01:
                    utad_detected = True
                    break

        # T+1 压力测试（含涨跌停流动性警告）
        current_price = float(df.iloc[-1]["close"])
        recent_30_low = float(df.tail(30)["low"].min())
        limit_moves = self._detect_limit_moves(df)
        limit_moves_data = [{"price": lm.price, "type": lm.move_type.value} for lm in limit_moves]
        t1_result = self.rules.rule3_t1_risk_test(current_price, recent_30_low, limit_moves_data)

        return Step3Result(
            spring_detected=spring_detected,
            spring_quality=spring_quality,
            spring_date=spring_date,
            spring_low_price=spring_low_price,
            utad_detected=utad_detected,
            utad_quality="无",
            utad_date=None,
            st_detected=st_detected,
            lps_confirmed=lps_confirmed,
            spring_volume=spring_volume,
            t1_max_drawdown_pct=t1_result["pct"],
            t1_verdict=t1_result["verdict"],
            t1_description=t1_result["desc"],
        )

    def _step35_counterfactual(
        self,
        df: pd.DataFrame,
        step1: Step1Result,
        step2: Step2Result,
        step3: Step3Result,
        rule0: Rule0Result,
    ) -> V3CounterfactualResult:
        """Step 3.5: 反事实压力测试"""
        forward_evidence = []
        backward_evidence = []

        # 正证：吸筹证据
        if step2.net_bias == "accumulation":
            forward_evidence.extend(step2.phenomena)

        # 反证：派发证据
        if step2.net_bias == "distribution":
            backward_evidence.extend(step2.phenomena)

        # 正证：Spring 确认
        if step3.spring_detected and step3.lps_confirmed:
            forward_evidence.append("Spring+LPS确认")

        # 反证：UTAD 或假突破
        if step3.utad_detected:
            backward_evidence.append("UTAD假突破")

        pro_score = len(forward_evidence) * 2.0
        con_score = len(backward_evidence) * 2.0

        # 使用规则7仲裁
        cf_result = self.rules.rule7_counterfactual(pro_score, con_score)

        # 生成反事实场景描述
        scenario = ""
        if cf_result["overturned"]:
            scenario = (
                f"反证({con_score:.1f})占优，原判断被推翻。反证：{', '.join(backward_evidence)}"
            )
        elif cf_result["verdict"] == "降档":
            scenario = f"反证({con_score:.1f})接近正证({pro_score:.1f})，降档处理。需进一步验证。"
        else:
            scenario = f"正证({pro_score:.1f})占优，维持判断。正证：{', '.join(forward_evidence)}"

        return V3CounterfactualResult(
            utad_not_breakout="是" if not step3.utad_detected else "否",
            distribution_not_accumulation="是" if step2.net_bias != "distribution" else "否",
            chaos_not_phase_c="是" if step1.phase != WyckoffPhase.UNKNOWN else "否",
            liquidity_vacuum_risk="低" if step3.t1_verdict == "安全" else "高",
            total_pro_score=pro_score,
            total_con_score=con_score,
            conclusion_overturned=cf_result["overturned"],
            counterfactual_scenario=scenario,
            forward_evidence=forward_evidence,
            backward_evidence=backward_evidence,
        )

    def _step4_risk_reward(
        self, df: pd.DataFrame, step1: Step1Result, step3: Step3Result, rule0: Rule0Result
    ) -> RiskRewardResult:
        """Step 4: 盈亏比投影（规则10精度，多种目标位来源）"""
        current_price = float(df.iloc[-1]["close"])

        # 止损价 = 关键结构低点 × 0.995
        key_low = step3.spring_low_price if step3.spring_low_price else step1.boundary_lower
        if key_low <= 0:
            key_low = float(df.tail(30)["low"].min())

        stop_loss_result = self.rules.rule10_stop_loss(key_low)
        stop_loss = stop_loss_result.stop_loss_price

        # 目标位：多种来源
        first_target = step1.boundary_upper
        first_target_source = "tr_upper"

        # 尝试其他目标位来源
        recent_20 = df.tail(20)

        # 1. 大阴线起跌点（前一天收盘价 > 当天收盘价 * 1.03）
        for i in range(len(recent_20) - 1, 0, -1):
            prev_close = float(recent_20.iloc[i - 1]["close"])
            curr_close = float(recent_20.iloc[i]["close"])
            if prev_close > curr_close * 1.03:
                # 大阴线起跌点
                bearish_target = prev_close
                if bearish_target > current_price and bearish_target < first_target:
                    first_target = bearish_target
                    first_target_source = "bearish_candle"
                    break

        # 2. 跳空缺口下沿
        for i in range(1, len(recent_20)):
            prev_row = recent_20.iloc[i - 1]
            curr_row = recent_20.iloc[i]
            # 向上跳空缺口
            if curr_row["low"] > prev_row["high"]:
                gap_target = float(curr_row["low"])
                if gap_target > current_price and gap_target < first_target:
                    first_target = gap_target
                    first_target_source = "gap_lower"
                    break

        # 计算盈亏比
        risk = current_price - stop_loss
        reward = first_target - current_price

        if risk > 0:
            rr_ratio = reward / risk
        else:
            rr_ratio = 0.0

        # 判定 - v3.0要求盈亏比 >= 1:2.5
        if rr_ratio >= 2.5:
            rr_verdict = "excellent"
        elif rr_ratio >= 2.0:
            rr_verdict = "pass"
        elif rr_ratio >= 1.5:
            rr_verdict = "marginal"
        else:
            rr_verdict = "fail"

        gain_pct = (first_target - current_price) / current_price * 100 if current_price > 0 else 0

        return RiskRewardResult(
            entry_price=current_price,
            stop_loss=stop_loss,
            first_target=first_target,
            first_target_source=first_target_source,
            rr_ratio=round(rr_ratio, 2),
            rr_verdict=rr_verdict,
            gain_pct=round(gain_pct, 2),
        )

    def _calc_confidence(
        self,
        rule0: Rule0Result,
        step3: Step3Result,
        cf: V3CounterfactualResult,
        rr: RiskRewardResult,
        multiframe: bool,
    ) -> ConfidenceResult:
        """规则8: 置信度矩阵 - 5项条件"""
        # 条件① BC已定位
        bc_located = rule0.bc_found

        # 条件② Spring/LPS结构完整且已验证
        spring_lps_verified = step3.spring_detected and step3.lps_confirmed

        # 条件③ 反事实推演无法推翻正向判断
        counterfactual_passed = not cf.conclusion_overturned

        # 条件④ 盈亏比 ≥ 1:2.5
        rr_qualified = rr.rr_ratio >= 2.5

        # 条件⑤ 多周期方向一致
        multiframe_aligned = multiframe

        # 特殊情况：如果处于ACCUMULATION且有Spring信号，即使LPS未验证也可降级处理
        if step3.spring_detected and not spring_lps_verified:
            # Spring已检测但LPS未验证，降级到C
            return ConfidenceResult(
                level="C",
                bc_located=bc_located,
                spring_lps_verified=False,
                counterfactual_passed=counterfactual_passed,
                rr_qualified=rr_qualified,
                multiframe_aligned=multiframe_aligned,
                position_size="试仓",
                reason="Spring已检测但LPS未验证，降级到C",
            )

        # 特殊情况：如果处于MARKUP且盈亏比达标，可给B级
        if rr_qualified and not bc_located:
            return ConfidenceResult(
                level="C",
                bc_located=False,
                spring_lps_verified=spring_lps_verified,
                counterfactual_passed=counterfactual_passed,
                rr_qualified=True,
                multiframe_aligned=multiframe_aligned,
                position_size="试仓",
                reason="盈亏比达标但BC未定位，降级到C",
            )

        return self.rules.rule8_confidence_matrix(
            bc_located, spring_lps_verified, counterfactual_passed, rr_qualified, multiframe_aligned
        )

    def _step5_trading_plan(
        self,
        step1: Step1Result,
        step3: Step3Result,
        cf: V3CounterfactualResult,
        rr: RiskRewardResult,
        confidence: ConfidenceResult,
        df: Optional[pd.DataFrame] = None,
    ) -> V3TradingPlan:
        """Step 5: 交易计划（完整字段填充）"""
        # 基本方向 - 根据阶段和信号确定
        direction = "空仓观望"

        # 规则2: Markdown禁止做多
        if step1.phase == WyckoffPhase.MARKDOWN:
            direction = "空仓观望"
        elif step1.phase == WyckoffPhase.DISTRIBUTION:
            direction = "空仓观望"
        elif step1.phase == WyckoffPhase.ACCUMULATION:
            # ACCUMULATION阶段：Spring+LPS确认后可做多
            if step3.spring_detected and step3.lps_confirmed:
                if rr.rr_ratio >= 2.5:
                    direction = "做多"
                else:
                    direction = "轻仓试探"
            elif step3.spring_detected:
                # Spring已检测但LPS未确认，可观察
                direction = "观察等待"
            else:
                direction = "空仓观望"
        elif step1.phase == WyckoffPhase.MARKUP:
            # MARKUP阶段：有信号且盈亏比达标可做多
            if rr.rr_ratio >= 2.5:
                direction = "做多"
            elif rr.rr_ratio >= 1.5:
                direction = "轻仓试探"
            else:
                direction = "持有观察"
        elif step1.phase == WyckoffPhase.UNKNOWN:
            # UNKNOWN阶段：根据子状态判断
            if step1.unknown_candidate in ("phase_a_candidate", "sc_st_candidate"):
                if step3.spring_detected:
                    direction = "观察等待"
                else:
                    direction = "空仓观望"
            else:
                direction = "空仓观望"

        # 止损结果（含涨跌停流动性警告）
        key_low = step3.spring_low_price if step3.spring_low_price else step1.boundary_lower
        limit_moves = self._detect_limit_moves(df if df is not None else pd.DataFrame())
        limit_moves_data = [{"price": lm.price, "type": lm.move_type.value} for lm in limit_moves]
        stop_loss_result = self.rules.rule10_stop_loss(key_low, limit_moves_data)

        # 多周期一致性声明
        multi_timeframe_statement = "本次分析未提供周线图，置信度已自动降一级"

        # 执行前提
        execution_preconditions = [
            "大盘指数未出现单边系统性暴跌",
            "所属板块未出现重大利空政策消息",
        ]

        return V3TradingPlan(
            current_assessment=f"当前处于{step1.phase.value}阶段",
            multi_timeframe_statement=multi_timeframe_statement,
            execution_preconditions=execution_preconditions,
            direction=direction,
            entry_trigger=f"价格站稳{step1.boundary_upper:.2f}上方"
            if step1.boundary_upper > 0
            else "",
            observation_window="3-5个交易日",
            stop_loss=stop_loss_result,
            target=rr,
            confidence=confidence,
        )

    def _apply_a_stock_rules(self, step1: Step1Result, plan: V3TradingPlan) -> V3TradingPlan:
        """A 股铁律最终检查"""
        # 规则2: Markdown 禁止做多
        blocked, reason = self.rules.rule2_no_long_in_markdown(step1.phase, "")
        if blocked:
            plan.direction = "空仓观望"
            plan.current_assessment = reason

        return plan

    def _build_report(
        self,
        symbol: str,
        period: str,
        df: pd.DataFrame,
        rule0: Rule0Result,
        step1: Step1Result,
        step2: Step2Result,
        step3: Step3Result,
        step35: V3CounterfactualResult,
        rr: RiskRewardResult,
        confidence: ConfidenceResult,
        v3_plan: V3TradingPlan,
    ) -> WyckoffReport:
        """构建最终报告"""
        current_price = float(df.iloc[-1]["close"])
        current_date = str(df.iloc[-1]["date"])

        # 构建结构
        structure = WyckoffStructure(
            phase=step1.phase,
            unknown_candidate=step1.unknown_candidate,
            bc_point=rule0.bc_position,
            sc_point=None,
            support_levels=[],
            resistance_levels=[],
            trading_range_high=step1.boundary_upper,
            trading_range_low=step1.boundary_lower,
            current_price=current_price,
            current_date=current_date,
        )

        # 构建信号
        signal_type = "no_signal"
        signal_description = ""

        if step3.spring_detected:
            signal_type = "spring"
            signal_description = f"检测到Spring信号，质量：{step3.spring_quality}"
            if step3.lps_confirmed:
                signal_description += "，LPS已确认"
        elif step3.utad_detected:
            signal_type = "utad"
            signal_description = "检测到UTAD假突破信号"
        elif step3.st_detected:
            signal_type = "sos_candidate"
            signal_description = "检测到SOS候选信号"
        elif step1.phase == WyckoffPhase.ACCUMULATION:
            signal_type = "accumulation"
            signal_description = "处于积累阶段，等待Spring/SOS信号"
        elif step1.phase == WyckoffPhase.MARKUP:
            signal_type = "markup"
            signal_description = "处于上涨阶段"
        elif step1.phase == WyckoffPhase.MARKDOWN:
            signal_type = "markdown"
            signal_description = "处于下跌阶段，空仓观望"
        elif step1.phase == WyckoffPhase.DISTRIBUTION:
            signal_type = "distribution"
            signal_description = "处于派发阶段，空仓观望"
        else:
            signal_type = "no_signal"
            signal_description = "阶段不明确，空仓观望"

        signal = WyckoffSignal(
            signal_type=signal_type,
            trigger_price=current_price,
            volume_confirmation=VolumeLevel.AVERAGE,
            confidence=ConfidenceLevel[confidence.level],
            phase=step1.phase,
            description=signal_description if signal_description else v3_plan.current_assessment,
            t1_risk评估=step3.t1_description,
        )

        # 盈亏比投影
        risk_reward = RiskRewardProjection(
            entry_price=rr.entry_price,
            stop_loss=rr.stop_loss,
            first_target=rr.first_target,
            reward_risk_ratio=rr.rr_ratio,
            risk_amount=rr.entry_price - rr.stop_loss,
            reward_amount=rr.first_target - rr.entry_price,
            structure_based=rr.first_target_source,
        )

        # 交易计划
        trading_plan = TradingPlan(
            direction=v3_plan.direction,
            trigger_condition=v3_plan.entry_trigger,
            invalidation_point=v3_plan.stop_loss.stop_logic if v3_plan.stop_loss else "",
            first_target=f"{rr.first_target:.2f}" if rr.first_target > 0 else "",
            confidence=ConfidenceLevel[confidence.level],
            preconditions="; ".join(v3_plan.execution_preconditions)
            if v3_plan.execution_preconditions
            else "",
            current_qualification=v3_plan.current_assessment,
        )

        # 压力测试
        stress_tests = []
        for evidence in step35.forward_evidence:
            stress_tests.append(
                StressTest(
                    scenario_name="正证",
                    scenario_description=evidence,
                    outcome="支持判断",
                    passes=True,
                    risk_level="低",
                )
            )
        for evidence in step35.backward_evidence:
            stress_tests.append(
                StressTest(
                    scenario_name="反证",
                    scenario_description=evidence,
                    outcome="质疑判断",
                    passes=False,
                    risk_level="高",
                )
            )

        # 涨跌停检测
        limit_moves = self._detect_limit_moves(df)

        # 筹码分析
        chip_analysis = self._analyze_chips(df, structure)

        return WyckoffReport(
            symbol=symbol,
            period=period,
            structure=structure,
            signal=signal,
            risk_reward=risk_reward,
            trading_plan=trading_plan,
            limit_moves=limit_moves,
            stress_tests=stress_tests,
            chip_analysis=chip_analysis,
            engine_version="v3.0",
            ruleset_version="v3.0",
        )

    def _classify_unknown_candidate(
        self, df: pd.DataFrame, phase: WyckoffPhase, rule0: Rule0Result
    ) -> str:
        """UNKNOWN 子状态分类"""
        if phase != WyckoffPhase.UNKNOWN or df.empty:
            return ""

        if rule0.tr_upper is None or rule0.tr_lower is None:
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

        range_low = rule0.tr_lower
        range_high = rule0.tr_upper
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

    def _classify_accumulation_sub_phase(
        self, df: pd.DataFrame, step1: Step1Result, rule0: Rule0Result
    ) -> str:
        """Accumulation Phase A/B/C/D/E 细分"""
        if df.empty:
            return ""

        recent_20 = df.tail(20)
        if len(recent_20) < 10:
            return ""

        current_price = float(df.iloc[-1]["close"])
        boundary_lower = step1.boundary_lower
        boundary_upper = step1.boundary_upper

        if boundary_lower <= 0 or boundary_upper <= 0:
            return ""

        range_span = boundary_upper - boundary_lower
        relative_position = (current_price - boundary_lower) / range_span

        # 检查是否有Spring信号
        has_spring = False
        for row in recent_20.itertuples():
            if row.low < boundary_lower * 1.03 and row.close >= boundary_lower * 0.97:
                has_spring = True
                break

        # 检查是否有SOS信号
        has_sos = False
        for row in recent_20.tail(5).itertuples():
            if row.close > boundary_upper * 0.98:
                vol_level = self.rules.rule1_relative_volume(row.volume, df["volume"])
                if vol_level in ("高于平均", "天量"):
                    has_sos = True
                    break

        # Phase分类
        if has_spring and has_sos:
            return "Phase D"  # Spring + SOS = Phase D
        elif has_spring:
            return "Phase C"  # Spring = Phase C
        elif relative_position <= 0.40:
            # 检查是否有SC信号
            for row in recent_20.itertuples():
                if row.low < boundary_lower * 1.05:
                    vol_level = self.rules.rule1_relative_volume(row.volume, df["volume"])
                    if vol_level in ("天量", "高于平均"):
                        return "Phase A"  # SC = Phase A
            return "Phase B"  # 区间下部但无SC
        elif relative_position >= 0.60:
            return "Phase B"  # 区间上部
        else:
            return "Phase B"  # 区间中部

    def _classify_distribution_sub_phase(
        self, df: pd.DataFrame, step1: Step1Result, rule0: Rule0Result
    ) -> str:
        """Distribution Phase A/B/C/D/E 细分"""
        if df.empty:
            return ""

        recent_20 = df.tail(20)
        if len(recent_20) < 10:
            return ""

        current_price = float(df.iloc[-1]["close"])
        boundary_lower = step1.boundary_lower
        boundary_upper = step1.boundary_upper

        if boundary_lower <= 0 or boundary_upper <= 0:
            return ""

        range_span = boundary_upper - boundary_lower
        relative_position = (current_price - boundary_lower) / range_span

        # 检查是否有UTAD信号
        has_utad = False
        for row in recent_20.itertuples():
            if row.high > boundary_upper * 1.02 and row.close <= boundary_upper * 1.01:
                has_utad = True
                break

        # 检查是否有BC信号
        has_bc = rule0.bc_found

        # Phase分类
        if has_utad:
            return "Phase C"  # UTAD = Phase C
        elif has_bc:
            if relative_position >= 0.60:
                return "Phase B"  # BC后高位震荡
            else:
                return "Phase D"  # BC后下跌
        elif relative_position >= 0.70:
            return "Phase A"  # 高位
        elif relative_position <= 0.30:
            return "Phase D"  # 低位
        else:
            return "Phase B"  # 中部震荡

    def _classify_volume(self, volume: float, volume_series: pd.Series) -> VolumeLevel:
        """相对量能分类"""
        return VolumeLevel(self.rules.rule1_relative_volume(volume, volume_series))

    def _scan_bc_sc(self, df: pd.DataFrame) -> Tuple[Optional[BCPoint], Optional[SCPoint]]:
        """BC/SC 评分系统"""
        bc_point = None
        sc_point = None

        df = df.copy()
        df["vol_rank"] = df["volume"].rank(pct=True)
        df["range"] = df["high"] - df["low"]
        df["upper_shadow"] = df["high"] - df["close"]
        df["lower_shadow"] = df["close"] - df["low"]
        df["shadow_ratio"] = df["upper_shadow"] / (df["range"] + 1e-9)
        df["lower_shadow_ratio"] = df["lower_shadow"] / (df["range"] + 1e-9)

        peak_idx = df["high"].idxmax()
        trough_idx = df["low"].idxmin()

        # BC 点识别
        bc_candidates = []
        for idx in df.nlargest(5, "high").index:
            row = df.loc[idx]
            vol_rank = row["vol_rank"]
            shadow_ratio = row["shadow_ratio"]

            score = 0
            if vol_rank > 0.8:
                score += 2
            elif vol_rank > 0.6:
                score += 1

            if shadow_ratio > 0.6:
                score += 2
            elif shadow_ratio > 0.4:
                score += 1

            peak_pos = df.index.get_loc(idx)
            if peak_pos < len(df) - 5:
                subsequent_low = df.iloc[peak_pos + 1 : peak_pos + 10]["close"].min()
                peak_price = row["high"]
                if (peak_price - subsequent_low) / peak_price > 0.05:
                    score += 2

            bc_candidates.append((idx, score, row))

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
                confidence_score=score,
            )

        # SC 点识别
        sc_candidates = []
        for idx in df.nsmallest(5, "low").index:
            row = df.loc[idx]
            vol_rank = row["vol_rank"]
            lower_shadow_ratio = row["lower_shadow_ratio"]

            score = 0
            if vol_rank > 0.8:
                score += 2
            elif vol_rank < 0.2:
                score += 1

            if lower_shadow_ratio > 0.6:
                score += 2
            elif lower_shadow_ratio > 0.4:
                score += 1

            trough_pos = df.index.get_loc(idx)
            if trough_pos < len(df) - 5:
                subsequent_high = df.iloc[trough_pos + 1 : trough_pos + 10]["close"].max()
                trough_price = row["low"]
                if (subsequent_high - trough_price) / trough_price > 0.05:
                    score += 2

            sc_candidates.append((idx, score, row))

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

    def _detect_limit_moves(self, df: pd.DataFrame) -> List[LimitMove]:
        """检测涨跌停与炸板异动"""
        limit_moves = []
        recent = df.tail(20)

        for row in recent.itertuples():
            pct_change = (row.close - row.open) / row.open
            is_limit_up = pct_change > 0.095
            is_limit_down = pct_change < -0.095

            if not is_limit_up and not is_limit_down:
                continue

            high_change = (row.high - row.open) / row.open
            low_change = (row.low - row.open) / row.open

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
        """
        筹码微观分析（v2: 加入成交额维度的量价背离检测）

        核心改进:
        1. 同时使用volume和amount检测背离
        2. 计算连续背离评分而非仅bool
        3. 检测收盘价偏离均价的幅度
        4. 计算资金流向趋势
        """
        analysis = ChipAnalysis()
        recent = df.tail(20)

        if len(recent) < 10:
            return analysis

        # ---- 1. 价格与成交量变化 ----
        price_change = (recent["close"].iloc[-1] - recent["close"].iloc[0]) / recent["close"].iloc[
            0
        ]
        volume_change = (recent["volume"].iloc[-1] - recent["volume"].iloc[0]) / recent[
            "volume"
        ].iloc[0]

        # 量价背离 (volume-based)
        if price_change > 0.05 and volume_change < -0.3:
            analysis.volume_price_divergence = True
            analysis.warnings.append("量价背离：价格上涨但量能萎缩")

        if price_change < -0.05 and volume_change > 0.3:
            analysis.distribution_signature = True

        if price_change > 0.05 and volume_change > 0.2:
            analysis.absorption_signature = True
            analysis.institutional_footprint = True

        # ---- 2. 成交额维度分析 (amount-based) ----
        if "amount" in recent.columns and recent["amount"].notna().all():
            amount_change = (recent["amount"].iloc[-1] - recent["amount"].iloc[0]) / max(
                recent["amount"].iloc[0], 1
            )

            # 金额背离: 价格与成交额方向不一致
            if price_change > 0.05 and amount_change < -0.3:
                analysis.amount_price_divergence = True
                analysis.warnings.append("金额背离：价格上涨但成交额萎缩（买方力量衰竭）")

            # 机构吸筹痕迹: 价格微跌但成交额放大
            if -0.05 < price_change < 0 and amount_change > 0.2:
                analysis.absorption_signature = True
                analysis.institutional_footprint = True
                analysis.warnings.append("机构吸筹迹象：价格微跌但成交额放大")

            # 派发痕迹: 价格微涨但成交额异常放大
            if 0 < price_change < 0.05 and amount_change > 0.3:
                analysis.distribution_signature = True
                analysis.warnings.append("派发迹象：价格微涨但成交额异常放大")

            # 计算平均成交价偏离度
            analysis.avg_price_deviation = self._compute_avg_price_deviation(recent)

            # 计算资金流向趋势
            analysis.money_flow_trend = self._compute_money_flow_trend(recent)

        # ---- 3. 连续背离评分（滑动窗口） ----
        divergence_scores = []
        amount_div_scores = []
        window = 5
        for i in range(window, len(recent)):
            p = (recent["close"].iloc[i] - recent["close"].iloc[i - window]) / recent["close"].iloc[
                i - window
            ]
            v = (recent["volume"].iloc[i] - recent["volume"].iloc[i - window]) / recent[
                "volume"
            ].iloc[i - window]
            # 背离评分: 正值=正价格负量能(熊背离), 负值=负价格正量能(牛背离)
            ds = p * (1 - v) if abs(v) > 0.1 else 0
            divergence_scores.append(ds)

            if "amount" in recent.columns:
                a = (recent["amount"].iloc[i] - recent["amount"].iloc[i - window]) / max(
                    recent["amount"].iloc[i - window], 1
                )
                ad = p * (1 - a) if abs(a) > 0.1 else 0
                amount_div_scores.append(ad)

        analysis.divergence_score = (
            round(np.mean(divergence_scores), 4) if divergence_scores else 0.0
        )
        analysis.amount_divergence_score = (
            round(np.mean(amount_div_scores), 4) if amount_div_scores else 0.0
        )

        return analysis

    def _compute_avg_price_deviation(self, df: pd.DataFrame) -> float:
        """计算收盘价偏离成交均价的程度"""
        if "amount" not in df.columns:
            return 0.0
        recent = df.tail(5)
        avg_prices = recent["amount"] / recent["volume"].replace(0, 1)
        current_avg = avg_prices.iloc[-1]
        if current_avg == 0:
            return 0.0
        deviation = (recent["close"].iloc[-1] - current_avg) / current_avg
        return round(float(deviation), 4)

    def _compute_money_flow_trend(self, df: pd.DataFrame) -> float:
        """计算资金流向趋势 [-1, 1]"""
        if "amount" not in df.columns:
            return 0.0
        recent = df.tail(10)
        if len(recent) < 5:
            return 0.0
        # 资金流向: (close - avg_price) * volume，正值表示资金流入
        avg_prices = recent["amount"] / recent["volume"].replace(0, 1)
        money_flows = (recent["close"] - avg_prices) * recent["volume"]
        total_flow = money_flows.sum()
        total_volume = recent["volume"].sum()
        if total_volume == 0:
            return 0.0
        # 归一化到 [-1, 1]
        trend = total_flow / (total_volume * recent["close"].mean())
        return round(float(np.clip(trend, -1, 1)), 4)

    def _analyze_multiframe(
        self, df: pd.DataFrame, symbol: str, image_evidence: Optional[ImageEvidenceBundle] = None
    ) -> WyckoffReport:
        """多周期分析"""
        frame = self._normalize_input_frame(df)
        if frame is None or len(frame) < 100:
            reason = f"数据不足，需要至少 100 根 K 线，当前只有 {len(frame) if frame is not None else 0} 根"
            return self._create_no_signal_report(symbol, "日线+周线+月线", reason)

        long_frame = frame.tail(self.multi_timeframe_lookback_days).reset_index(drop=True)
        weekly_df = self._resample_ohlcv(long_frame, "W-FRI")
        monthly_df = self._resample_ohlcv(long_frame, "ME")

        daily_report = self._analyze_single(frame, symbol, "日线", image_evidence)
        weekly_report = self._analyze_single(weekly_df, symbol, "周线")
        monthly_report = self._analyze_single(monthly_df, symbol, "月线")

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
        """多周期融合"""
        final_report = daily_report
        monthly_phase = monthly_report.structure.phase
        weekly_phase = weekly_report.structure.phase
        daily_phase = daily_report.structure.phase

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

        # 使用规则9进行多周期一致性判断
        alignment_type, alignment_desc = self.rules.rule9_multiframe_alignment(
            daily_phase, weekly_phase, monthly_phase
        )

        if alignment_type == "markdown_override":
            final_report.structure.phase = WyckoffPhase.MARKDOWN
            final_report.signal.signal_type = "no_signal"
            final_report.signal.confidence = ConfidenceLevel.D
            final_report.signal.description = alignment_desc
            final_report.trading_plan.direction = "空仓观望"
            final_report.trading_plan.current_qualification = alignment_desc
            final_report.trading_plan.confidence = ConfidenceLevel.D
            constraint_note = alignment_desc
        elif alignment_type == "distribution_override":
            final_report.structure.phase = WyckoffPhase.DISTRIBUTION
            final_report.signal.signal_type = "no_signal"
            final_report.signal.confidence = ConfidenceLevel.D
            final_report.signal.description = alignment_desc
            final_report.trading_plan.direction = "空仓观望"
            final_report.trading_plan.confidence = ConfidenceLevel.D
            constraint_note = alignment_desc
        elif alignment_type == "degraded":
            final_report.signal.confidence = ConfidenceLevel.C
            final_report.trading_plan.confidence = ConfidenceLevel.C
            constraint_note = alignment_desc
        elif alignment_type == "aligned":
            if final_report.signal.confidence == ConfidenceLevel.A:
                final_report.signal.confidence = ConfidenceLevel.B
            final_report.trading_plan.confidence = final_report.signal.confidence
            constraint_note = alignment_desc

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

        return final_report

    def _build_timeframe_snapshot(self, report: WyckoffReport) -> TimeframeSnapshot:
        """构建周期快照"""
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

    def _create_no_signal_report(self, symbol: str, period: str, reason: str) -> WyckoffReport:
        """创建无信号报告"""
        structure = WyckoffStructure(
            phase=WyckoffPhase.UNKNOWN,
            unknown_candidate="",
            bc_point=None,
            sc_point=None,
            current_price=0.0,
            current_date="",
        )

        signal = WyckoffSignal(
            signal_type="no_signal",
            confidence=ConfidenceLevel.D,
            description=reason,
        )

        risk_reward = RiskRewardProjection()
        trading_plan = TradingPlan(
            direction="空仓观望",
            current_qualification=reason,
            confidence=ConfidenceLevel.D,
        )

        return WyckoffReport(
            symbol=symbol,
            period=period,
            structure=structure,
            signal=signal,
            risk_reward=risk_reward,
            trading_plan=trading_plan,
            engine_version="v3.0",
            ruleset_version="v3.0",
        )
