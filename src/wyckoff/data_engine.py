# -*- coding: utf-8 -*-
"""
威科夫规则引擎 - 日线规则链实现

严格遵循 SPEC_WYCKOFF_RULE_ENGINE 定义的 Step 0 ~ Step 5 顺序
"""
import logging
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from src.constants import (
    MIN_WYCKOFF_DATA_ROWS,
    WYCKOFF_PHASES,
    WYCKOFF_DIRECTIONS,
    WYCKOFF_CONFIDENCE_LEVELS,
    VOLUME_LABELS,
)
from src.exceptions import InvalidInputDataError, BCNotFoundError

from src.wyckoff.config import WyckoffConfig, RuleEngineConfig
from src.wyckoff.models import (
    DailyRuleResult,
    PreprocessingResult,
    BCResult,
    PhaseResult,
    EffortResult,
    PhaseCTestResult,
    CounterfactualResult,
    RiskAssessment,
    TradingPlan,
)

logger = logging.getLogger(__name__)


class DataEngine:
    """
    威科夫数据引擎 - 实现 Step 0 ~ Step 5 完整规则链
    
    SPEC_WYCKOFF_RULE_ENGINE Section 2 强制顺序:
    1. 输入校验 → 2. 预处理 → 3. Step 0 BC 定位 → 4. Step 1 阶段识别
    → 5. Step 2 努力结果 → 6. Step 3 Phase C 测试 → 7. Step 3.5 反事实
    → 8. Step 4 风险评估 → 9. Step 5 交易计划
    """
    
    def __init__(self, config: Optional[WyckoffConfig] = None):
        self.config = config or WyckoffConfig()
        self.rule_config = self.config.rule_engine
    
    def run(
        self,
        df: pd.DataFrame,
        symbol: str,
        asset_type: str,
        analysis_date: Optional[str] = None,
    ) -> DailyRuleResult:
        """
        规则引擎主入口 - 严格按 Step 0→5 顺序执行
        
        Args:
            df: OHLCV DataFrame
            symbol: 标的代码
            asset_type: 资产类型 ("index" 或 "stock")
            analysis_date: 分析日期（可选，默认使用 df 最后日期）
            
        Returns:
            DailyRuleResult
        """
        # Step 1: 输入校验
        self._step_validate(df)
        
        # Step 2: 预处理
        preprocessing = self._step_preprocess(df)
        
        # Step 0: BC 定位扫描 (必须在方向性判断前执行)
        bc_result = self._step0_bc_scan(df, preprocessing)
        
        # BC 未找到 → 直接返回 D 级 + abandon
        if not bc_result.found:
            return self._create_abandon_result(
                df, symbol, asset_type, analysis_date,
                preprocessing, bc_result,
                reason="bc_not_found"
            )
        
        # Step 1: 阶段识别
        phase_result = self._step1_phase_identify(df, bc_result, preprocessing)
        
        # Step 2: 努力与结果
        effort_result = self._step2_effort_result(df, phase_result, preprocessing)
        
        # Step 3: Phase C 终极测试
        phase_c_test = self._step3_phase_c_test(df, phase_result, bc_result, preprocessing)
        
        # Step 3.5: 反事实压力测试
        counterfactual = self._step35_counterfactual(
            df, bc_result, phase_result, effort_result, phase_c_test
        )
        
        # Step 4: T+1 与盈亏比评估
        risk_assessment = self._step4_risk_assessment(
            df, phase_result, phase_c_test, counterfactual
        )
        
        # Step 5: 交易计划
        trading_plan = self._step5_trading_plan(
            bc_result, phase_result, effort_result, phase_c_test,
            counterfactual, risk_assessment
        )
        
        # 计算置信度
        confidence = self._calc_confidence(
            bc_result, phase_result, phase_c_test,
            counterfactual, risk_assessment
        )
        
        # 构建最终结果
        return DailyRuleResult(
            symbol=symbol,
            asset_type=asset_type,
            analysis_date=analysis_date or str(df['date'].max().date()),
            input_source="data",
            preprocessing=preprocessing,
            bc_result=bc_result,
            phase_result=phase_result,
            effort_result=effort_result,
            phase_c_test=phase_c_test,
            counterfactual=counterfactual,
            risk=risk_assessment,
            plan=trading_plan,
            confidence=confidence,
            decision=trading_plan.direction,
            abandon_reason="" if trading_plan.direction != "abandon" else "unfavorable_rr_or_structure",
        )
    
    def _step_validate(self, df: pd.DataFrame) -> None:
        """
        Step 1: 输入校验 - SPEC Section 1
        
        强制要求:
        - 至少 100 根 K 线
        - 时间升序
        - 无负成交量
        - 开高低收为正
        """
        if df is None or df.empty:
            raise InvalidInputDataError("DataFrame is None or empty")
        
        if len(df) < MIN_WYCKOFF_DATA_ROWS:
            raise InvalidInputDataError(
                f"Insufficient data rows: {len(df)} < {MIN_WYCKOFF_DATA_ROWS}"
            )
        
        required_cols = ['date', 'open', 'high', 'low', 'close', 'volume']
        missing_cols = [col for col in required_cols if col not in df.columns]
        if missing_cols:
            raise InvalidInputDataError(f"Missing required columns: {missing_cols}")
        
        # 检查负值
        if (df['volume'] < 0).any():
            raise InvalidInputDataError("Invalid data: negative volume found")
        
        if (df[['open', 'high', 'low', 'close']] <= 0).any().any():
            raise InvalidInputDataError("Invalid data: non-positive prices found")
        
        # 检查高<低
        bad_hl = (df['high'] < df['low']).sum()
        if bad_hl > len(df) * 0.01:
            raise InvalidInputDataError(f"Too many high < low: {bad_hl} rows")
        
        logger.info(f"输入校验通过：{len(df)} rows")
    
    def _step_preprocess(self, df: pd.DataFrame) -> PreprocessingResult:
        """
        Step 2: 预处理 - SPEC Section 3
        
        输出:
        - 趋势方向
        - 量能标签
        - 波动分层
        - 局部高低点
        - 缺口候选
        - 长影线候选
        - 涨跌停异常
        """
        # 1. 趋势方向 (近 20 日线性回归斜率)
        recent_close = df['close'].tail(20).values
        x = np.arange(len(recent_close))
        slope = np.polyfit(x, recent_close, 1)[0]
        if slope > 0.02:
            trend_direction = "uptrend"
        elif slope < -0.02:
            trend_direction = "downtrend"
        else:
            trend_direction = "range"
        
        # 2. 量能标签 (最近 20 日 vs 60 日均值)
        recent_vol = df['volume'].tail(20).mean()
        avg_vol_60 = df['volume'].tail(60).mean()
        vol_ratio = recent_vol / avg_vol_60 if avg_vol_60 > 0 else 1.0
        
        if vol_ratio > self.rule_config.volume_extreme_high_threshold:
            volume_label = "extreme_high"
        elif vol_ratio > self.rule_config.volume_above_avg_threshold:
            volume_label = "above_average"
        elif vol_ratio < self.rule_config.volume_contracted_low:
            volume_label = "extreme_contracted"
        else:
            volume_label = "contracted"
        
        # 3. 波动分层 (ATR/收盘价)
        atr_14 = self._calc_atr(df, 14)
        vol_ratio = (atr_14 / df['close'].iloc[-1]).iloc[-1]
        if vol_ratio > 0.03:
            volatility_layer = "high"
        elif vol_ratio > 0.015:
            volatility_layer = "medium"
        else:
            volatility_layer = "low"
        
        # 4. 局部高低点 (rolling 20)
        rolling_high = df['high'].rolling(20).max()
        rolling_low = df['low'].rolling(20).min()
        
        local_highs = []
        local_lows = []
        for i in range(20, len(df)):
            if df['high'].iloc[i] == rolling_high.iloc[i]:
                local_highs.append({
                    'index': i,
                    'date': str(df['date'].iloc[i].date()),
                    'price': df['high'].iloc[i]
                })
            if df['low'].iloc[i] == rolling_low.iloc[i]:
                local_lows.append({
                    'index': i,
                    'date': str(df['date'].iloc[i].date()),
                    'price': df['low'].iloc[i]
                })
        
        # 5. 缺口候选
        gap_candidates = []
        for i in range(1, len(df)):
            if df['low'].iloc[i] > df['high'].iloc[i-1]:
                gap_candidates.append({
                    'index': i,
                    'date': str(df['date'].iloc[i].date()),
                    'type': 'gap_up',
                    'size': df['low'].iloc[i] - df['high'].iloc[i-1]
                })
            elif df['high'].iloc[i] < df['low'].iloc[i-1]:
                gap_candidates.append({
                    'index': i,
                    'date': str(df['date'].iloc[i].date()),
                    'type': 'gap_down',
                    'size': df['low'].iloc[i-1] - df['high'].iloc[i]
                })
        
        # 6. 长影线候选
        long_wick_candidates = []
        for i in range(len(df)):
            body = abs(df['close'].iloc[i] - df['open'].iloc[i])
            wick = (df['high'].iloc[i] - df['low'].iloc[i]) - body
            if body > 0 and wick > 3 * body:
                wick_type = "upper" if df['close'].iloc[i] > df['open'].iloc[i] else "lower"
                long_wick_candidates.append({
                    'index': i,
                    'date': str(df['date'].iloc[i].date()),
                    'type': wick_type,
                    'wick_ratio': wick / body
                })
        
        # 7. 涨跌停异常 (A 股±10%)
        limit_anomalies = []
        for i in range(1, len(df)):
            pct_change = (df['close'].iloc[i] - df['close'].iloc[i-1]) / df['close'].iloc[i-1]
            if pct_change >= 0.095:
                limit_anomalies.append({
                    'index': i,
                    'date': str(df['date'].iloc[i].date()),
                    'type': 'limit_up',
                    'pct': pct_change
                })
            elif pct_change <= -0.095:
                limit_anomalies.append({
                    'index': i,
                    'date': str(df['date'].iloc[i].date()),
                    'type': 'limit_down',
                    'pct': pct_change
                })
        
        return PreprocessingResult(
            trend_direction=trend_direction,
            volume_label=volume_label,
            volatility_layer=volatility_layer,
            local_highs=local_highs[-10:],  # 最近 10 个
            local_lows=local_lows[-10:],
            gap_candidates=gap_candidates[-10:],
            long_wick_candidates=long_wick_candidates[-10:],
            limit_anomalies=limit_anomalies[-10:],
        )
    
    def _step0_bc_scan(self, df: pd.DataFrame, prep: PreprocessingResult) -> BCResult:
        """
        Step 0: BC 定位扫描 - SPEC Section 4
        
        强制原则：任何方向性判断前必须先定位 BC
        
        BC 候选条件:
        1. 左侧存在明显上涨（前 60 日涨幅 > 15%）
        2. 是局部高点或近似局部高点
        3. 成交量标签为 extreme_high 或 above_average
        4. 伴随增强信号之一
        """
        # 1. 检查左侧上涨
        if len(df) < 60:
            return BCResult(
                found=False, candidate_index=-1, candidate_date="",
                candidate_price=0.0, volume_label="unknown",
                enhancement_signals=[]
            )
        
        # 检查最近 60 日前的上涨
        lookback_start = max(0, len(df) - 120)
        lookback_mid = max(0, len(df) - 60)
        
        if lookback_mid <= lookback_start:
            return BCResult(found=False, candidate_index=-1, candidate_date="",
                          candidate_price=0.0, volume_label="unknown", enhancement_signals=[])
        
        price_start = df['close'].iloc[lookback_start]
        price_mid = df['close'].iloc[lookback_mid]
        price_increase = (price_mid - price_start) / price_start
        
        if price_increase < self.rule_config.bc_min_price_increase_pct / 100:
            logger.info(f"左侧上涨不足 {self.rule_config.bc_min_price_increase_pct}%")
            return BCResult(found=False, candidate_index=-1, candidate_date="",
                          candidate_price=0.0, volume_label="unknown", enhancement_signals=[])
        
        # 2. 找局部高点 (rolling 20 max)
        rolling_high = df['high'].rolling(20).max()
        bc_candidates = []
        
        for i in range(lookback_start, lookback_mid):
            if df['high'].iloc[i] >= rolling_high.iloc[i] * 0.98:  # 近似高点
                bc_candidates.append(i)
        
        if not bc_candidates:
            return BCResult(found=False, candidate_index=-1, candidate_date="",
                          candidate_price=0.0, volume_label="unknown", enhancement_signals=[])
        
        # 3. 检查成交量和增强信号
        for idx in reversed(bc_candidates):
            # 检查成交量
            vol_20 = df['volume'].iloc[max(0, idx-20):idx+1].mean()
            avg_vol_60 = df['volume'].iloc[max(0, idx-60):idx+1].mean()
            vol_ratio = vol_20 / avg_vol_60 if avg_vol_60 > 0 else 1.0
            
            if vol_ratio < self.rule_config.bc_volume_multiplier_avg:
                continue
            
            # 检查增强信号
            enhancement_signals = []
            
            # 高位长上影
            for wick in prep.long_wick_candidates:
                if abs(wick['index'] - idx) <= 5 and wick['type'] == 'upper':
                    enhancement_signals.append("long_upper_wick")
            
            # 放量滞涨
            if vol_ratio > self.rule_config.bc_volume_multiplier_high:
                pct_change = (df['close'].iloc[idx] - df['open'].iloc[idx]) / df['open'].iloc[idx]
                if pct_change < 0.01:
                    enhancement_signals.append("volume_stagnation")
            
            # 跳空后衰竭
            for gap in prep.gap_candidates:
                if abs(gap['index'] - idx) <= 3 and gap['type'] == 'gap_up':
                    enhancement_signals.append("gap_exhaustion")
            
            # 假突破
            if len(enhancement_signals) >= 1:
                return BCResult(
                    found=True,
                    candidate_index=idx,
                    candidate_date=str(df['date'].iloc[idx].date()),
                    candidate_price=float(df['high'].iloc[idx]),
                    volume_label="extreme_high" if vol_ratio > self.rule_config.bc_volume_multiplier_high else "above_average",
                    enhancement_signals=enhancement_signals
                )
        
        return BCResult(found=False, candidate_index=-1, candidate_date="",
                       candidate_price=0.0, volume_label="unknown", enhancement_signals=[])
    
    def _step1_phase_identify(
        self,
        df: pd.DataFrame,
        bc_result: BCResult,
        prep: PreprocessingResult,
    ) -> PhaseResult:
        """
        Step 1: 大局观与阶段识别 - SPEC Section 5
        
        阶段: accumulation / markup / distribution / markdown / no_trade_zone
        """
        bc_idx = bc_result.candidate_index
        bc_price = bc_result.candidate_price
        
        # BC 后价格行为
        post_bc_df = df.iloc[bc_idx:].reset_index(drop=True)
        current_price = post_bc_df['close'].iloc[-1]
        price_change = (current_price - bc_price) / bc_price
        
        # 边界来源
        boundary_sources = ["BC"]
        
        # 找 AR (Automatic Rally) 高点
        ar_high = post_bc_df['high'].rolling(10).max().max()
        if ar_high > bc_price * 0.98:
            boundary_sources.append("AR")
        
        # 找 SC (Selling Climax) 低点
        sc_low = post_bc_df['low'].min()
        if sc_low < bc_price * 0.85:
            boundary_sources.append("SC")
        
        # 阶段判定
        if price_change < -0.15:
            # 大幅下跌 → distribution 或 markdown
            if prep.trend_direction == "downtrend":
                phase = "markdown"
            else:
                phase = "distribution"
            boundary_upper = str(bc_price)
            boundary_lower = str(sc_low)
        elif price_change > 0.05:
            # 上涨 → markup
            phase = "markup"
            boundary_upper = str(ar_high)
            boundary_lower = str(bc_price)
        elif -0.15 <= price_change <= 0.05:
            # 区间震荡 → accumulation
            phase = "accumulation"
            boundary_upper = str(ar_high)
            boundary_lower = str(sc_low)
        else:
            phase = "no_trade_zone"
            boundary_upper = str(bc_price)
            boundary_lower = str(sc_low)
        
        return PhaseResult(
            phase=phase,
            boundary_upper_zone=boundary_upper,
            boundary_lower_zone=boundary_lower,
            boundary_sources=boundary_sources,
        )
    
    def _step2_effort_result(
        self,
        df: pd.DataFrame,
        phase_result: PhaseResult,
        prep: PreprocessingResult,
    ) -> EffortResult:
        """
        Step 2: 努力与结果 - SPEC Section 6
        
        识别现象:
        - 放量滞涨
        - 缩量上推
        - 下边界供给枯竭
        - 高位炸板遗迹
        """
        phenomena = []
        accumulation_score = 0.0
        distribution_score = 0.0
        
        # 1. 放量滞涨
        if prep.volume_label in ["extreme_high", "above_average"]:
            recent_pct = (df['close'].iloc[-1] - df['close'].iloc[-5]) / df['close'].iloc[-5]
            if recent_pct < 0.01:
                phenomena.append("volume_stagnation")
                distribution_score += 0.3
        
        # 2. 缩量上推
        if prep.volume_label == "contracted":
            recent_pct = (df['close'].iloc[-1] - df['close'].iloc[-5]) / df['close'].iloc[-5]
            if recent_pct > 0.02:
                phenomena.append("low_volume_rally")
                accumulation_score += 0.2
        
        # 3. 下边界供给枯竭
        lower_boundary = float(phase_result.boundary_lower_zone)
        if df['low'].iloc[-1] <= lower_boundary * 1.02:
            if prep.volume_label == "extreme_contracted":
                phenomena.append("supply_drying_at_support")
                accumulation_score += 0.3
        
        # 4. 高位炸板遗迹
        for anomaly in prep.limit_anomalies:
            if anomaly['type'] == 'limit_up':
                idx = anomaly['index']
                if idx > len(df) - 20:
                    # 最近 20 日有涨停
                    post_limit_pct = (df['close'].iloc[-1] - df['close'].iloc[idx]) / df['close'].iloc[idx]
                    if post_limit_pct < -0.05:
                        phenomena.append("failed_limit_up")
                        distribution_score += 0.3
        
        # 5. 吸筹/派发倾向
        net_bias_score = accumulation_score - distribution_score
        if net_bias_score > 0.2:
            net_bias = "accumulation"
        elif net_bias_score < -0.2:
            net_bias = "distribution"
        else:
            net_bias = "neutral"
        
        return EffortResult(
            phenomena=phenomena,
            accumulation_evidence=accumulation_score,
            distribution_evidence=distribution_score,
            net_bias=net_bias,
        )
    
    def _step3_phase_c_test(
        self,
        df: pd.DataFrame,
        phase_result: PhaseResult,
        bc_result: BCResult,
        prep: PreprocessingResult,
    ) -> PhaseCTestResult:
        """
        Step 3: Phase C 终极测试 - SPEC Section 7
        
        检测:
        - Spring (刺穿下边界后快速收回)
        - UTAD (刺穿上边界后快速回落)
        - ST (Secondary Test)
        - False Breakout
        """
        spring_detected = False
        utad_detected = False
        st_detected = False
        false_breakout_detected = False
        spring_date = None
        utad_date = None
        
        lower_boundary = float(phase_result.boundary_lower_zone)
        upper_boundary = float(phase_result.boundary_upper_zone)
        
        # Spring 检测
        for i in range(len(df) - 5, len(df)):
            if df['low'].iloc[i] < lower_boundary:
                # 刺穿下边界
                if i < len(df) - 1:
                    # 检查是否快速收回
                    recovery_price = df['close'].iloc[i+1:]
                    if (recovery_price > lower_boundary).any():
                        spring_detected = True
                        spring_date = str(df['date'].iloc[i].date())
                        break
        
        # UTAD 检测
        for i in range(len(df) - 5, len(df)):
            if df['high'].iloc[i] > upper_boundary:
                # 刺穿上边界
                if i < len(df) - 1:
                    # 检查是否快速回落
                    decline_price = df['close'].iloc[i+1:]
                    if (decline_price < upper_boundary).any():
                        utad_detected = True
                        utad_date = str(df['date'].iloc[i].date())
                        break
        
        # ST 检测 (Spring 后的二次测试)
        if spring_detected and spring_date:
            spring_idx = df[df['date'].astype(str) == spring_date].index[0]
            post_spring = df.iloc[spring_idx:]
            if len(post_spring) > 3:
                # 检查是否有回测 Spring 低点但不破
                retest_low = post_spring['low'].iloc[1:].min()
                spring_low = df['low'].iloc[spring_idx]
                if retest_low >= spring_low * 0.99:
                    st_detected = True
        
        # False Breakout 检测
        for gap in prep.gap_candidates:
            if gap['index'] > len(df) - 10:
                # 最近 10 日的缺口
                if gap['type'] == 'gap_up':
                    post_gap_close = df['close'].iloc[gap['index']+1:].iloc[:3]
                    if (post_gap_close < df['close'].iloc[gap['index']]).any():
                        false_breakout_detected = True
        
        return PhaseCTestResult(
            spring_detected=spring_detected,
            utad_detected=utad_detected,
            st_detected=st_detected,
            false_breakout_detected=false_breakout_detected,
            spring_date=spring_date,
            utad_date=utad_date,
        )
    
    def _step35_counterfactual(
        self,
        df: pd.DataFrame,
        bc_result: BCResult,
        phase_result: PhaseResult,
        effort_result: EffortResult,
        phase_c_test: PhaseCTestResult,
    ) -> CounterfactualResult:
        """
        Step 3.5: 反事实压力测试 - SPEC Section 8
        
        四组反证:
        1. 这是 UTAD 不是突破
        2. 这是派发不是吸筹
        3. 这是无序震荡不是 Phase C
        4. 买入后次日可能进入流动性真空
        """
        pro_score = 0.0
        con_score = 0.0
        
        # 反证 1: UTAD 不是突破
        if phase_c_test.utad_detected:
            con_score += 0.3
        elif phase_result.phase == "markup":
            pro_score += 0.2
        
        # 反证 2: 派发不是吸筹
        if effort_result.net_bias == "distribution":
            con_score += 0.3
        elif effort_result.net_bias == "accumulation":
            pro_score += 0.2
        
        # 反证 3: 无序震荡不是 Phase C
        if phase_result.phase == "no_trade_zone":
            con_score += 0.4
        elif phase_c_test.spring_detected or phase_c_test.utad_detected:
            pro_score += 0.2
        
        # 反证 4: 流动性真空
        recent_vol = df['volume'].tail(5).mean()
        avg_vol_20 = df['volume'].tail(20).mean()
        if recent_vol < avg_vol_20 * 0.5:
            liquidity_risk = "high"
            con_score += 0.2
        elif recent_vol < avg_vol_20 * 0.7:
            liquidity_risk = "medium"
        else:
            liquidity_risk = "low"
        
        # 结论是否被推翻
        conclusion_overturned = con_score >= pro_score
        
        return CounterfactualResult(
            is_utad_not_breakout="likely" if phase_c_test.utad_detected else "unlikely",
            is_distribution_not_accumulation="likely" if effort_result.net_bias == "distribution" else "unlikely",
            is_chaos_not_phase_c="likely" if phase_result.phase == "no_trade_zone" else "unlikely",
            liquidity_vacuum_risk=liquidity_risk,
            total_pro_score=pro_score,
            total_con_score=con_score,
            conclusion_overturned=conclusion_overturned,
        )
    
    def _step4_risk_assessment(
        self,
        df: pd.DataFrame,
        phase_result: PhaseResult,
        phase_c_test: PhaseCTestResult,
        counterfactual: CounterfactualResult,
    ) -> RiskAssessment:
        """
        Step 4: T+1 与盈亏比评估 - SPEC Section 9
        
        输出:
        - T+1 风险等级
        - R:R 评估
        - Spring 冷冻期
        """
        # T+1 风险评估
        atr_14 = self._calc_atr(df, 14).iloc[-1]
        current_price = df['close'].iloc[-1]
        t1_risk_pct = atr_14 / current_price
        
        if t1_risk_pct > 0.04:
            t1_risk_level = "critical"
        elif t1_risk_pct > 0.03:
            t1_risk_level = "high"
        elif t1_risk_pct > 0.02:
            t1_risk_level = "medium"
        else:
            t1_risk_level = "low"
        
        t1_description = f"基于 ATR(14)={t1_risk_pct:.2%}，次日可能承受 {t1_risk_pct:.2%} 波动"
        
        # R:R 计算
        entry_price = current_price
        invalidation_price = float(phase_result.boundary_lower_zone) * 0.98
        target_price = float(phase_result.boundary_upper_zone) * 1.02
        
        risk = entry_price - invalidation_price
        reward = target_price - entry_price
        
        rr_ratio = reward / risk if risk > 0 else 0.0
        
        if rr_ratio >= self.rule_config.confidence_a_rr_min:
            rr_assessment = "excellent"
        elif rr_ratio >= self.rule_config.confidence_b_rr_min:
            rr_assessment = "pass"
        else:
            rr_assessment = "fail"
        
        # Spring 冷冻期
        freeze_until = None
        if phase_c_test.spring_detected and phase_c_test.spring_date:
            from datetime import datetime, timedelta
            spring_dt = datetime.strptime(phase_c_test.spring_date, "%Y-%m-%d")
            freeze_until = str((spring_dt + timedelta(days=self.rule_config.spring_freeze_days)).date())
        
        return RiskAssessment(
            t1_risk_level=t1_risk_level,
            t1_structural_description=t1_description,
            rr_ratio=rr_ratio,
            rr_assessment=rr_assessment,
            freeze_until=freeze_until,
        )
    
    def _step5_trading_plan(
        self,
        bc_result: BCResult,
        phase_result: PhaseResult,
        effort_result: EffortResult,
        phase_c_test: PhaseCTestResult,
        counterfactual: CounterfactualResult,
        risk: RiskAssessment,
    ) -> TradingPlan:
        """
        Step 5: 交易计划 - SPEC Section 10
        
        固定输出字段:
        - current_assessment
        - execution_preconditions
        - direction
        - entry_trigger
        - invalidation
        - target_1
        """
        # A 股强约束：Distribution/Markdown 只能 watch_only 或 abandon
        if phase_result.phase in ["distribution", "markdown"]:
            return TradingPlan(
                current_assessment=f"{phase_result.phase} 阶段，禁止做多",
                execution_preconditions=[],
                direction="watch_only",
                entry_trigger="",
                invalidation=phase_result.boundary_upper_zone,
                target_1="",
            )
        
        # R:R 不合格 → abandon
        if risk.rr_assessment == "fail":
            return TradingPlan(
                current_assessment=f"盈亏比不足 (R:R={risk.rr_ratio:.2f})",
                execution_preconditions=[],
                direction="abandon",
                entry_trigger="",
                invalidation=phase_result.boundary_lower_zone,
                target_1="",
            )
        
        # Spring 冷冻期 → watch_only
        if phase_c_test.spring_detected and risk.freeze_until:
            from datetime import datetime
            freeze_dt = datetime.strptime(risk.freeze_until, "%Y-%m-%d").date()
            if datetime.now().date() <= freeze_dt:
                return TradingPlan(
                    current_assessment=f"Spring 冷冻期至 {risk.freeze_until}",
                    execution_preconditions=["等待冷冻期结束"],
                    direction="watch_only",
                    entry_trigger="",
                    invalidation=phase_result.boundary_lower_zone,
                    target_1=phase_result.boundary_upper_zone,
                )
        
        # 反事实结论被推翻 → watch_only
        if counterfactual.conclusion_overturned:
            return TradingPlan(
                current_assessment="反证据强于正证据",
                execution_preconditions=["等待更明确信号"],
                direction="watch_only",
                entry_trigger="",
                invalidation=phase_result.boundary_lower_zone,
                target_1=phase_result.boundary_upper_zone,
            )
        
        # 多头候选
        preconditions = []
        if phase_c_test.st_detected:
            preconditions.append("ST 确认完成")
        
        trigger = "breakout_and_retest"
        if phase_c_test.spring_detected:
            trigger = "spring_confirmation"
        
        return TradingPlan(
            current_assessment=f"{phase_result.phase} 阶段，多头候选",
            execution_preconditions=preconditions,
            direction="long_setup",
            entry_trigger=trigger,
            invalidation=phase_result.boundary_lower_zone,
            target_1=phase_result.boundary_upper_zone,
        )
    
    def _calc_confidence(
        self,
        bc_result: BCResult,
        phase_result: PhaseResult,
        phase_c_test: PhaseCTestResult,
        counterfactual: CounterfactualResult,
        risk: RiskAssessment,
    ) -> str:
        """
        计算置信度 - SPEC Section 11
        
        A/B/C/D 四级
        """
        score = 0.0
        
        # BC 明确性
        if bc_result.found and len(bc_result.enhancement_signals) >= 2:
            score += 0.3
        elif bc_result.found:
            score += 0.2
        
        # 阶段清晰性
        if phase_result.phase in ["accumulation", "markup"]:
            score += 0.2
        elif phase_result.phase == "no_trade_zone":
            score -= 0.2
        
        # Phase C 明确性
        if phase_c_test.spring_detected or phase_c_test.utad_detected:
            score += 0.2
        
        # 反事实
        if not counterfactual.conclusion_overturned:
            score += 0.1
        else:
            score -= 0.2
        
        # R:R
        if risk.rr_assessment == "excellent":
            score += 0.2
        elif risk.rr_assessment == "pass":
            score += 0.1
        else:
            score -= 0.2
        
        # 分级
        if score >= 0.8:
            return "A"
        elif score >= 0.6:
            return "B"
        elif score >= 0.4:
            return "C"
        else:
            return "D"
    
    def _create_abandon_result(
        self,
        df: pd.DataFrame,
        symbol: str,
        asset_type: str,
        analysis_date: Optional[str],
        preprocessing: PreprocessingResult,
        bc_result: BCResult,
        reason: str,
    ) -> DailyRuleResult:
        """创建放弃结论的结果"""
        return DailyRuleResult(
            symbol=symbol,
            asset_type=asset_type,
            analysis_date=analysis_date or str(df['date'].max().date()),
            input_source="data",
            preprocessing=preprocessing,
            bc_result=bc_result,
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
                current_assessment=f"BC 未找到，{reason}",
                execution_preconditions=[],
                direction="abandon",
                entry_trigger="",
                invalidation="",
                target_1="",
            ),
            confidence="D",
            decision="abandon",
            abandon_reason=reason,
        )
    
    def _calc_atr(self, df: pd.DataFrame, period: int = 14) -> pd.Series:
        """计算 ATR"""
        high = df['high']
        low = df['low']
        close = df['close']
        
        tr1 = high - low
        tr2 = abs(high - close.shift(1))
        tr3 = abs(low - close.shift(1))
        
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(period).mean()
        
        return atr
