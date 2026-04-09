# -*- coding: utf-8 -*-
"""
Wyckoff 核心分析引擎
基于 Richard Wyckoff 理论的 A 股实战分析
"""

import logging
from typing import Dict, List, Optional, Tuple

import pandas as pd
import numpy as np

from src.wyckoff.models import (
    BCPoint,
    SCPoint,
    ConfidenceLevel,
    SupportResistance,
    TradingPlan,
    VolumeLevel,
    WyckoffPhase,
    WyckoffReport,
    WyckoffSignal,
    WyckoffStructure,
    RiskRewardProjection,
    LimitMove,
    LimitMoveType,
    StressTest,
    ChipAnalysis,
    ImageEvidenceBundle,
    AnalysisResult,
    AnalysisState,
)

logger = logging.getLogger(__name__)


class WyckoffAnalyzer:
    """威科夫分析器"""
    
    def __init__(self, lookback_days: int = 120):
        self.lookback_days = lookback_days
    
    def analyze(self, df: pd.DataFrame, symbol: str = "UNKNOWN", period: str = "日线", 
                image_evidence: Optional[ImageEvidenceBundle] = None) -> WyckoffReport:
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
        if df is None or len(df) < 100:
            reason = f"数据不足，需要至少 100 根 K 线，当前只有 {len(df) if df is not None else 0} 根"
            return self._create_no_signal_report(symbol, period, reason)
        
        df = df.tail(self.lookback_days).reset_index(drop=True)
        
        bc_point, sc_point = self._scan_bc_sc(df)
        
        if bc_point is None and sc_point is None:
            return self._create_no_signal_report(symbol, period, "未找到BC/SC点")
        
        structure = self._determine_wyckoff_structure(df, bc_point, sc_point)
        
        signal = self._detect_wyckoff_signals(df, structure)
        
        limit_moves = self._detect_limit_moves(df)
        
        chip_analysis = self._analyze_chips(df, structure)
        
        stress_tests = self._run_stress_tests(df, structure, signal)

        risk_reward = self._calculate_risk_reward(df, structure, signal)

        trading_plan = self._build_trading_plan(structure, signal, risk_reward, stress_tests)

        # T+1 零容错强制执行（必须在 trading_plan 构建后执行）
        self._apply_t1_enforcement(signal, trading_plan, stress_tests)
        
        # 创建基础报告
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
        
        # 如果有图像证据，进行融合
        if image_evidence is not None:
            from src.wyckoff.fusion_engine import FusionEngine
            fusion_engine = FusionEngine()
            analysis_result = fusion_engine.fuse(report, image_evidence)
            report.analysis_result = analysis_result
            
            # 更新置信度等级（如果融合引擎提供了更好的置信度）
            if hasattr(analysis_result, 'confidence') and analysis_result.confidence:
                try:
                    # 将字符串置信度转换为枚举
                    conf_map = {'A': ConfidenceLevel.A, 'B': ConfidenceLevel.B, 
                               'C': ConfidenceLevel.C, 'D': ConfidenceLevel.D}
                    if analysis_result.confidence in conf_map:
                        report.trading_plan.confidence = conf_map[analysis_result.confidence]
                        report.signal.confidence = conf_map[analysis_result.confidence]
                except Exception as e:
                    logger.warning(f"无法更新置信度: {e}")
            
            # 创建分析状态
            from datetime import datetime
            analysis_state = AnalysisState(
                symbol=symbol,
                asset_type="stock" if symbol.endswith('.SH') or symbol.endswith('.SZ') else "index",
                analysis_date=datetime.now().strftime('%Y-%m-%d'),
                last_phase=structure.phase.value if structure.phase else "unknown",
                last_micro_action=getattr(signal, 'micro_action', ""),
                last_confidence=report.trading_plan.confidence.value,
                bc_found=structure.bc_point is not None,
                spring_detected=getattr(signal, 'signal_type', "") == "spring",
                watch_status="cooling_down" if getattr(signal, 'signal_type', "") == "spring" else "none",
                trigger_armed=False,
                trigger_text=getattr(signal, 'trigger_condition', ""),
                invalid_level=getattr(trading_plan, 'invalidation_point', ""),
                target_1=getattr(trading_plan, 'first_target', ""),
                weekly_context="",  # 将由图像引擎填充
                intraday_context="",  # 将由图像引擎填充
                conflict_summary="; ".join(getattr(analysis_result, 'conflicts', [])) if hasattr(analysis_result, 'conflicts') else "",
                last_decision=getattr(analysis_result, 'decision', "no_trade_zone") if hasattr(analysis_result, 'decision') else "no_trade_zone",
                abandon_reason=getattr(analysis_result, 'abandon_reason', "") if hasattr(analysis_result, 'abandon_reason') else ""
            )
            report.analysis_state = analysis_state
        
        return report
    
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
        peak_idx = df["close"].idxmax()
        trough_idx = df["close"].idxmin()
        
        # BC 点增强识别
        bc_candidates = []
        for idx in df.nlargest(3, "close").index:
            row = df.loc[idx]
            vol_rank = row["vol_rank"]
            shadow_ratio = row["shadow_ratio"]
            
            # 评分系统
            score = 0
            if vol_rank > 0.8:
                score += 2
            elif vol_rank > 0.6:
                score += 1
            
            if shadow_ratio > 0.6:  # 长上影
                score += 2
            elif shadow_ratio > 0.4:
                score += 1
            
            # 检查后续回调
            peak_pos = df.index.get_loc(idx)
            if peak_pos < len(df) - 5:
                subsequent_low = df.iloc[peak_pos+1:peak_pos+10]["close"].min()
                peak_price = row["close"]
                if (peak_price - subsequent_low) / peak_price > 0.05:
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
                price=float(row["close"]),
                volume_level=volume_level,
                is_extremum=(idx == peak_idx),
                confidence_score=score,  # 自定义字段，用于置信度计算
            )
        
        # SC 点增强识别
        sc_candidates = []
        for idx in df.nsmallest(3, "close").index:
            row = df.loc[idx]
            vol_rank = row["vol_rank"]
            lower_shadow_ratio = row["lower_shadow_ratio"]
            
            # 评分系统
            score = 0
            if vol_rank > 0.8:  # 放量
                score += 2
            elif vol_rank < 0.2:  # 极度缩量（恐慌后无人卖出）
                score += 1
            
            if lower_shadow_ratio > 0.6:  # 长下影
                score += 2
            elif lower_shadow_ratio > 0.4:
                score += 1
            
            # 检查后续反弹
            trough_pos = df.index.get_loc(idx)
            if trough_pos < len(df) - 5:
                subsequent_high = df.iloc[trough_pos+1:trough_pos+10]["close"].max()
                trough_price = row["close"]
                if (subsequent_high - trough_price) / trough_price > 0.05:
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
                price=float(row["close"]),
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
        avg_price = recent["close"].mean()
        
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
            
            limit_moves.append(LimitMove(
                date=str(row["date"]),
                move_type=move_type,
                price=float(row["close"]),
                volume_level=volume_level,
                is_broken=is_broken,
            ))
        
        return limit_moves
    
    def _analyze_chips(self, df: pd.DataFrame, structure: WyckoffStructure) -> ChipAnalysis:
        """筹码微观分析"""
        analysis = ChipAnalysis()
        
        recent = df.tail(20)
        
        price_change = (recent["close"].iloc[-1] - recent["close"].iloc[0]) / recent["close"].iloc[0]
        volume_change = (recent["volume"].iloc[-1] - recent["volume"].iloc[0]) / recent["volume"].iloc[0]
        
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
        self, 
        df: pd.DataFrame, 
        structure: WyckoffStructure,
        signal: WyckoffSignal
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
            test1.outcome = f"支撑失守，可能加速下跌"
            test1.risk_level = "高"
            test1.passes = False
        else:
            test1.outcome = f"仍在支撑上方运行"
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
            test3.outcome = f"需等待二次确认"
            test3.risk_level = "中"
            test3.passes = True
        else:
            test3.outcome = f"未到Spring，等待信号"
            test3.risk_level = "低"
            test3.passes = True
        stress_tests.append(test3)
        
        return stress_tests
    
    def _apply_t1_enforcement(
        self, 
        signal: WyckoffSignal,
        trading_plan: Optional[TradingPlan],
        stress_tests: List[StressTest]
    ) -> None:
        """T+1 零容错强制执行"""
        if trading_plan is None:
            return
        
        if signal.signal_type == "spring":
            signal.description += " [Spring冷静期3天]"
            trading_plan.spring_cooldown_days = 3
        
        has_high_risk = any(st.risk_level == "高" for st in stress_tests)
        
        if has_high_risk and signal.signal_type == "spring":
            trading_plan.t1_blocked = True
            trading_plan.direction = "T+1零容错阻止，空仓观望"
            trading_plan.trigger_condition = "风险过高，禁止入场"
        
    def _determine_wyckoff_structure(
        self,
        df: pd.DataFrame,
        bc_point: Optional[BCPoint],
        sc_point: Optional[SCPoint]
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
        total_range_pct = (price_high - price_low) / price_low if price_low > 0 else 1.0

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
                prior_trend_pct = (prior_last - prior_first) / prior_first if prior_first > 0 else 0.0
            else:
                prior_trend_pct = 0.0

            if prior_trend_pct < -0.10:
                # TR 前有明显下跌：主力可能正在低位吸筹 → Accumulation
                structure.phase = WyckoffPhase.ACCUMULATION
            elif prior_trend_pct > 0.10:
                # TR 前有明显上涨：主力可能正在高位派发 → Distribution
                structure.phase = WyckoffPhase.DISTRIBUTION
            else:
                # 前期趋势不明显，无法判断意图 → 保守处理为 UNKNOWN
                structure.phase = WyckoffPhase.UNKNOWN
                logger.debug(
                    "TR 前趋势幅度不足 10%%（prior_trend=%.2f%%），无法区分 "
                    "Accumulation/Distribution，降级为 UNKNOWN",
                    prior_trend_pct * 100,
                )
        else:
            # --- Step 3：非 TR，按短期趋势方向判定 Markup / Markdown ---
            if short_trend_pct >= 0.03:
                structure.phase = WyckoffPhase.MARKUP
            elif short_trend_pct <= -0.03:
                structure.phase = WyckoffPhase.MARKDOWN
            else:
                structure.phase = WyckoffPhase.UNKNOWN

        # --- 区间边界计算（取近 30 日极值） ---
        recent_df = df.tail(30)
        structure.trading_range_high = float(recent_df["high"].max())
        structure.trading_range_low = float(recent_df["low"].min())
        structure.current_price = float(df.iloc[-1]["close"])
        structure.current_date = str(df.iloc[-1]["date"])

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
    
    def _detect_wyckoff_signals(
        self, 
        df: pd.DataFrame, 
        structure: WyckoffStructure
    ) -> WyckoffSignal:
        """
        检测威科夫事件信号

        产出的 signal_type 为结构事件枚举，只允许：
        spring / utad / sos_candidate / no_signal
        严禁将宏观阶段名（如 'accumulation'）写入 signal_type。
        """
        signal = WyckoffSignal()
        signal.phase = structure.phase

        # A 股铁律：Distribution / Markdown 阶段禁止给任何做多方向信号
        if structure.phase in [WyckoffPhase.MARKDOWN, WyckoffPhase.DISTRIBUTION]:
            signal.signal_type = "no_signal"
            signal.confidence = ConfidenceLevel.D
            signal.description = "当前处于派发/下跌阶段，A 股禁止做空，建议空仓观望"
            return signal

        # 阶段不明确：保守处理
        if structure.phase == WyckoffPhase.UNKNOWN:
            signal.signal_type = "no_signal"
            signal.confidence = ConfidenceLevel.D
            signal.description = "阶段不明确，当前处于不可交易区，建议空仓观望"
            return signal

        # BC 未定位：无法做任何方向推演（SPEC RC §4.3 强制规则）
        if structure.bc_point is None:
            signal.signal_type = "no_signal"
            signal.confidence = ConfidenceLevel.D
            signal.description = "未找到 BC 点，无法确认趋势方向，放弃"
            return signal

        last_price = structure.current_price
        last_vol = df.iloc[-1]["volume"]
        volume_level = self._classify_volume(last_vol, df["volume"])
        signal.volume_confirmation = volume_level

        # --- Spring 检测：仅在 ACCUMULATION 阶段有效 ---
        # Spring = 价格刺穿或接近区间下边界，且随即快速收回
        if (structure.phase == WyckoffPhase.ACCUMULATION
                and structure.trading_range_low is not None):
            low_bound = structure.trading_range_low
            if last_price <= low_bound * 1.02:
                signal.signal_type = "spring"
                signal.trigger_price = last_price
                signal.confidence = ConfidenceLevel.B
                signal.description = (
                    f"价格接近震荡区间下边界 {low_bound:.2f}，"
                    "检测到 Spring 候选信号，需等待 T+3 冷冻期后二次确认"
                )
                signal.t1_risk评估 = self._assess_t1_risk(df, structure, last_price)
                return signal

        # --- SOS 候选：价格接近区间上边界，可能进入 Markup ---
        if (signal.signal_type == "no_signal"
                and structure.trading_range_high is not None):
            high_bound = structure.trading_range_high
            if last_price >= high_bound * 0.98:
                signal.signal_type = "sos_candidate"
                signal.trigger_price = last_price
                signal.confidence = ConfidenceLevel.C
                signal.description = (
                    f"价格接近震荡区间上边界 {high_bound:.2f}，"
                    "可能进入上涨阶段，仅允许观察，不可立即入场"
                )
                return signal

        # --- 无明确事件信号：保守降级为空仓观望（不得编造方向结论）---
        # SPEC §12 强制保守降级清单：信号不明确时输出 no_signal，置信度 D
        signal.signal_type = "no_signal"
        signal.confidence = ConfidenceLevel.D
        signal.description = (
            f"当前处于 {structure.phase.value} 阶段，"
            "价格在区间内部运行，无明确事件信号，建议空仓观望，等待 Spring 或 SOS 确认"
        )
        return signal
    
    def _assess_t1_risk(
        self, 
        df: pd.DataFrame, 
        structure: WyckoffStructure, 
        entry_price: float
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
        
        return f"基于10日平均振幅{range_pct*100:.1f}%，风险等级{risk_level}，支撑强度{support_strength}"
    
    def _calculate_risk_reward(
        self, 
        df: pd.DataFrame, 
        structure: WyckoffStructure,
        signal: WyckoffSignal
    ) -> RiskRewardProjection:
        """计算盈亏比"""
        proj = RiskRewardProjection()
        
        if signal.signal_type == "no_signal":
            return proj
        
        current_price = structure.current_price
        proj.entry_price = current_price
        
        if structure.trading_range_low is not None:
            proj.stop_loss = structure.trading_range_low * 0.98
            proj.risk_amount = current_price - proj.stop_loss
        
        if structure.trading_range_high is not None:
            proj.first_target = structure.trading_range_high
            proj.reward_amount = proj.first_target - current_price
        
        if proj.risk_amount and proj.risk_amount > 0:
            proj.reward_risk_ratio = proj.reward_amount / proj.risk_amount
            proj.structure_based = f"基于震荡区间 {structure.trading_range_low} - {structure.trading_range_high}"
        
        return proj
    
    def _build_trading_plan(
        self, 
        structure: WyckoffStructure,
        signal: WyckoffSignal,
        risk_reward: RiskRewardProjection,
        stress_tests: Optional[List[StressTest]] = None
    ) -> TradingPlan:
        """构建交易计划"""
        plan = TradingPlan()
        
        if signal.signal_type == "no_signal":
            plan.direction = "空仓观望"
            plan.trigger_condition = "N/A"
            plan.invalidation_point = "N/A"
            plan.first_target = "N/A"
            plan.confidence = signal.confidence
            plan.current_qualification = signal.description
            plan.preconditions = "需等待明确信号"
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
        
        plan.direction = "做多"
        plan.confidence = signal.confidence
        plan.current_qualification = signal.description
        plan.preconditions = "需大盘指数/所属板块不出现系统性单边暴跌"
        
        if signal.signal_type == "spring":
            plan.trigger_condition = f"价格放量突破 {structure.current_price} 后缩量回踩不破 {structure.trading_range_low} 时入场"
            plan.invalidation_point = f"跌破 {structure.trading_range_low} 无条件止损"
        else:
            plan.trigger_condition = "等待价格突破震荡区间上边界并回踩确认"
            plan.invalidation_point = f"跌破 {structure.current_price * 0.95} 止损"
        
        if risk_reward.first_target is not None:
            plan.first_target = f"第一目标位 {risk_reward.first_target}"
        else:
            plan.first_target = "待确认"
        
        return plan
    
    def _create_no_signal_report(
        self, 
        symbol: str, 
        period: str, 
        reason: str
    ) -> WyckoffReport:
        """创建无信号报告"""
        structure = WyckoffStructure()
        structure.phase = WyckoffPhase.UNKNOWN
        
        signal = WyckoffSignal()
        signal.signal_type = "no_signal"
        signal.confidence = ConfidenceLevel.D
        signal.description = f"当前图表信号杂乱，处于不可交易区（No Trade Zone），建议放弃。原因: {reason}"
        
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
