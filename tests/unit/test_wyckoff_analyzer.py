# -*- coding: utf-8 -*-
"""
Unit Tests for Wyckoff Analysis Module
"""

import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
import pandas as pd

from src.cli.wyckoff_analysis import _save_all_outputs, ensure_output_dirs, resolve_output_dirs
from src.wyckoff import (
    ConfidenceLevel,
    FusionEngine,
    StateManager,
    VolumeLevel,
    WyckoffAnalyzer,
    WyckoffPhase,
)
from src.wyckoff.models import (
    AnalysisResult,
    BCPoint,
    RiskRewardProjection,
    TradingPlan,
    WyckoffReport,
    WyckoffSignal,
    WyckoffStructure,
)


class TestWyckoffAnalyzer(unittest.TestCase):
    """威科夫分析器单元测试"""
    
    def _create_sample_data(
        self, 
        days: int = 120,
        trend: str = "up"
    ) -> pd.DataFrame:
        """创建测试用 K 线数据"""
        dates = pd.date_range(end=datetime.now(), periods=days, freq="D")
        
        if trend == "up":
            base_prices = np.linspace(100, 150, days)
            noise = np.random.normal(0, 2, days)
            closes = base_prices + noise
        elif trend == "down":
            base_prices = np.linspace(150, 100, days)
            noise = np.random.normal(0, 2, days)
            closes = base_prices + noise
        else:
            base_prices = np.ones(days) * 100
            noise = np.random.normal(0, 5, days)
            closes = base_prices + noise
        
        opens = closes + np.random.uniform(-1, 1, days)
        highs = np.maximum(opens, closes) + np.random.uniform(0, 2, days)
        lows = np.minimum(opens, closes) - np.random.uniform(0, 2, days)
        
        base_volume = 1000000
        volumes = base_volume + np.random.normal(0, 200000, days)
        volumes = np.abs(volumes)
        
        df = pd.DataFrame({
            "date": dates,
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": volumes,
        })
        
        return df
    
    def test_analyze_uptrend(self):
        """测试上涨趋势分析"""
        df = self._create_sample_data(days=120, trend="up")
        
        analyzer = WyckoffAnalyzer(lookback_days=120)
        report = analyzer.analyze(df, symbol="000001.SH", period="日线")
        
        self.assertIsInstance(report, WyckoffReport)
        self.assertEqual(report.symbol, "000001.SH")
        self.assertIn(report.structure.phase, [WyckoffPhase.MARKUP, WyckoffPhase.ACCUMULATION])
    
    def test_analyze_downtrend(self):
        """测试下跌趋势分析"""
        df = self._create_sample_data(days=120, trend="down")
        
        analyzer = WyckoffAnalyzer(lookback_days=120)
        report = analyzer.analyze(df, symbol="000001.SH", period="日线")
        
        self.assertIsInstance(report, WyckoffReport)
        self.assertEqual(report.symbol, "000001.SH")
        self.assertIn(
            report.trading_plan.direction, 
            ["空仓观望", "做多", "T+1零容错阻止，空仓观望"]
        )
    
    def test_analyze_insufficient_data(self):
        """测试数据不足情况"""
        df = self._create_sample_data(days=20, trend="up")
        
        analyzer = WyckoffAnalyzer(lookback_days=120)
        report = analyzer.analyze(df, symbol="000001.SH", period="日线")
        
        self.assertEqual(report.signal.signal_type, "no_signal")
        self.assertEqual(report.signal.confidence, ConfidenceLevel.D)
    
    def test_bc_sc_detection(self):
        """测试 BC/SC 点检测"""
        dates = pd.date_range(end=datetime.now(), periods=100, freq="D")
        
        prices = np.linspace(100, 200, 50).tolist() + np.linspace(200, 150, 50).tolist()
        
        df = pd.DataFrame({
            "date": dates,
            "open": prices,
            "high": [p + 5 for p in prices],
            "low": [p - 5 for p in prices],
            "close": prices,
            "volume": [1000000] * 100,
        })
        
        analyzer = WyckoffAnalyzer(lookback_days=100)
        bc_point, sc_point = analyzer._scan_bc_sc(df)
        
        self.assertIsNotNone(bc_point)
        self.assertIsNotNone(sc_point)
    
    def test_volume_classification(self):
        """测试量能分类"""
        df = self._create_sample_data(days=50, trend="up")
        
        analyzer = WyckoffAnalyzer()
        
        avg_vol = df["volume"].mean()
        
        extreme_high_vol = avg_vol * 3
        level = analyzer._classify_volume(extreme_high_vol, df["volume"])
        self.assertEqual(level, VolumeLevel.EXTREME_HIGH)
        
        low_vol = avg_vol * 0.3
        level = analyzer._classify_volume(low_vol, df["volume"])
        self.assertEqual(level, VolumeLevel.EXTREME_LOW)

    def test_spring_plan_stays_in_observation_during_cooldown(self):
        """Spring 候选在冷冻期内只能观察，不能直接做多"""
        analyzer = WyckoffAnalyzer()
        structure = WyckoffStructure(
            phase=WyckoffPhase.ACCUMULATION,
            bc_point=BCPoint(
                date="2026-04-01",
                price=12.8,
                volume_level=VolumeLevel.EXTREME_HIGH,
            ),
            trading_range_high=12.8,
            trading_range_low=11.4,
            current_price=12.2,
            current_date="2026-04-29",
        )
        signal = WyckoffSignal(
            signal_type="spring",
            confidence=ConfidenceLevel.B,
            phase=WyckoffPhase.ACCUMULATION,
            description="Spring 候选",
        )
        risk_reward = RiskRewardProjection(
            entry_price=12.2,
            stop_loss=11.2,
            first_target=12.8,
            reward_risk_ratio=2.5,
        )
        stress_tests = analyzer._run_stress_tests(
            self._create_sample_data(days=120, trend="range"),
            structure,
            signal,
        )

        plan = analyzer._build_trading_plan(structure, signal, risk_reward, stress_tests)
        analyzer._apply_t1_enforcement(signal, plan, stress_tests)

        self.assertIn("空仓观望", plan.direction)
        self.assertIn("T+3", plan.trigger_condition)
        self.assertEqual(plan.spring_cooldown_days, 3)

    def test_fusion_engine_blocks_long_setup_when_rr_below_threshold(self):
        """盈亏比不足 1:2.5 时必须禁止入场"""
        report = WyckoffReport(
            symbol="000001.SH",
            period="日线",
            structure=WyckoffStructure(
                phase=WyckoffPhase.ACCUMULATION,
                bc_point=BCPoint(
                    date="2026-04-01",
                    price=13.0,
                    volume_level=VolumeLevel.EXTREME_HIGH,
                ),
                trading_range_high=13.0,
                trading_range_low=11.5,
                current_price=12.7,
                current_date="2026-04-29",
            ),
            signal=WyckoffSignal(
                signal_type="sos_candidate",
                confidence=ConfidenceLevel.B,
                phase=WyckoffPhase.ACCUMULATION,
                description="上沿附近观察",
            ),
            risk_reward=RiskRewardProjection(
                entry_price=12.7,
                stop_loss=11.5,
                first_target=13.0,
                reward_risk_ratio=0.25,
            ),
            trading_plan=TradingPlan(
                direction="做多",
                trigger_condition="突破后回踩确认",
                invalidation_point="跌破 11.5",
                first_target="13.0",
                confidence=ConfidenceLevel.B,
            ),
        )

        result = FusionEngine().fuse(report)

        self.assertEqual(result.analysis_date, "2026-04-29")
        self.assertEqual(result.decision, "no_trade_zone")
        self.assertIn("盈亏比不足 1:2.5", result.abandon_reason)

    def test_state_manager_uses_trading_days_for_spring_freeze(self):
        """Spring 冷冻期按交易日推进，且在冷冻期内保持 cooling_down"""
        state_manager = StateManager()
        today = datetime.now().strftime("%Y-%m-%d")
        analysis_result = AnalysisResult(
            symbol="000001.SH",
            analysis_date=today,
            spring_detected=True,
            decision="watch_only",
            confidence="B",
        )

        with TemporaryDirectory() as tmpdir:
            state = state_manager.update_state(
                symbol="000001.SH",
                analysis_result=analysis_result,
                output_path=f"{tmpdir}/state.json",
            )

        expected = state_manager._add_trading_days(
            datetime.strptime(today, "%Y-%m-%d"),
            state_manager.spring_freeze_days,
        ).strftime("%Y-%m-%d")
        self.assertEqual(state.freeze_until, expected)
        self.assertEqual(state.watch_status, "cooling_down")

    def test_save_all_outputs_writes_non_fusion_summary(self):
        """CLI 在非融合模式下也应输出完整摘要字段"""
        report = WyckoffReport(
            symbol="000001.SH",
            period="日线",
            structure=WyckoffStructure(
                phase=WyckoffPhase.ACCUMULATION,
                bc_point=BCPoint(
                    date="2026-04-01",
                    price=13.0,
                    volume_level=VolumeLevel.EXTREME_HIGH,
                ),
                trading_range_high=13.0,
                trading_range_low=11.5,
                current_price=11.8,
                current_date="2026-04-29",
            ),
            signal=WyckoffSignal(
                signal_type="spring",
                confidence=ConfidenceLevel.B,
                phase=WyckoffPhase.ACCUMULATION,
                description="等待冷冻期结束",
                t1_risk评估="中等风险",
            ),
            risk_reward=RiskRewardProjection(
                entry_price=11.8,
                stop_loss=11.3,
                first_target=13.27,
                reward_risk_ratio=2.94,
            ),
            trading_plan=TradingPlan(
                direction="空仓观望",
                trigger_condition="T+3 后放量确认再观察",
                invalidation_point="跌破 11.3",
                first_target="13.27",
                confidence=ConfidenceLevel.B,
            ),
        )

        with TemporaryDirectory() as tmpdir:
            output_dirs = resolve_output_dirs(tmpdir)
            ensure_output_dirs(output_dirs)
            _save_all_outputs(report, None, None, output_dirs, "000001.SH", "data-only")
            summary_files = list(Path(output_dirs["summary"]).glob("*.csv"))

            self.assertEqual(len(summary_files), 1)
            content = summary_files[0].read_text(encoding="utf-8")

        self.assertIn("中等风险", content)
        self.assertIn("空仓观望", content)

    def test_resample_ohlcv_builds_weekly_bars(self):
        analyzer = WyckoffAnalyzer()
        df = pd.DataFrame(
            {
                "date": pd.to_datetime(
                    [
                        "2026-04-06",
                        "2026-04-07",
                        "2026-04-08",
                        "2026-04-09",
                        "2026-04-10",
                    ]
                ),
                "open": [10, 11, 12, 13, 14],
                "high": [11, 12, 13, 15, 16],
                "low": [9, 10, 11, 12, 13],
                "close": [10.5, 11.5, 12.5, 14.5, 15.5],
                "volume": [100, 200, 300, 400, 500],
            }
        )

        weekly = analyzer._resample_ohlcv(df, "W-FRI")

        self.assertEqual(len(weekly), 1)
        self.assertEqual(float(weekly.iloc[0]["open"]), 10.0)
        self.assertEqual(float(weekly.iloc[0]["high"]), 16.0)
        self.assertEqual(float(weekly.iloc[0]["low"]), 9.0)
        self.assertEqual(float(weekly.iloc[0]["close"]), 15.5)
        self.assertEqual(float(weekly.iloc[0]["volume"]), 1500.0)

    def test_multiframe_markdown_overrides_daily_markup(self):
        analyzer = WyckoffAnalyzer()
        daily_report = WyckoffReport(
            symbol="000001.SH",
            period="日线",
            structure=WyckoffStructure(
                phase=WyckoffPhase.MARKUP,
                current_price=12.5,
                current_date="2026-04-29",
            ),
            signal=WyckoffSignal(
                signal_type="sos_candidate",
                confidence=ConfidenceLevel.B,
                phase=WyckoffPhase.MARKUP,
                description="日线看起来偏强",
            ),
            risk_reward=RiskRewardProjection(reward_risk_ratio=2.8),
            trading_plan=TradingPlan(
                direction="持有观察",
                current_qualification="日线偏强",
                confidence=ConfidenceLevel.B,
            ),
        )
        weekly_report = WyckoffReport(
            symbol="000001.SH",
            period="周线",
            structure=WyckoffStructure(
                phase=WyckoffPhase.MARKDOWN,
                current_price=12.5,
                current_date="2026-04-25",
            ),
            signal=WyckoffSignal(
                signal_type="no_signal",
                confidence=ConfidenceLevel.D,
                phase=WyckoffPhase.MARKDOWN,
                description="周线空头压制",
            ),
            risk_reward=RiskRewardProjection(),
            trading_plan=TradingPlan(direction="空仓观望", confidence=ConfidenceLevel.D),
        )
        monthly_report = WyckoffReport(
            symbol="000001.SH",
            period="月线",
            structure=WyckoffStructure(
                phase=WyckoffPhase.UNKNOWN,
                current_price=12.5,
                current_date="2026-04-30",
            ),
            signal=WyckoffSignal(
                signal_type="no_signal",
                confidence=ConfidenceLevel.D,
                phase=WyckoffPhase.UNKNOWN,
                description="月线未确认",
            ),
            risk_reward=RiskRewardProjection(),
            trading_plan=TradingPlan(direction="空仓观望", confidence=ConfidenceLevel.D),
        )

        merged = analyzer._merge_multitimeframe_reports(
            symbol="000001.SH",
            daily_report=daily_report,
            weekly_report=weekly_report,
            monthly_report=monthly_report,
        )

        self.assertEqual(merged.structure.phase, WyckoffPhase.MARKDOWN)
        self.assertEqual(merged.trading_plan.direction, "空仓观望")
        self.assertIsNotNone(merged.multi_timeframe)
        self.assertTrue(merged.multi_timeframe.enabled)
        self.assertIn("Markdown", merged.signal.description)

    def test_multiframe_markup_does_not_hold_when_rr_is_negative(self):
        analyzer = WyckoffAnalyzer()
        daily_report = WyckoffReport(
            symbol="000001.SH",
            period="日线",
            structure=WyckoffStructure(
                phase=WyckoffPhase.MARKUP,
                current_price=12.5,
                current_date="2026-04-29",
            ),
            signal=WyckoffSignal(
                signal_type="sos_candidate",
                confidence=ConfidenceLevel.B,
                phase=WyckoffPhase.MARKUP,
                description="当前处于 Phase E Markup 延续段，价格已跃过 BC 11.00，出现 Phase E / SOS 动能扩张信号",
            ),
            risk_reward=RiskRewardProjection(
                entry_price=12.5,
                stop_loss=11.8,
                first_target=12.3,
                reward_risk_ratio=-0.2,
            ),
            trading_plan=TradingPlan(
                direction="空仓观望",
                trigger_condition="等待回踩确认",
                invalidation_point="跌破 11.8",
                first_target="12.3",
                confidence=ConfidenceLevel.B,
            ),
        )
        weekly_report = WyckoffReport(
            symbol="000001.SH",
            period="周线",
            structure=WyckoffStructure(
                phase=WyckoffPhase.MARKUP,
                current_price=12.5,
                current_date="2026-04-25",
            ),
            signal=WyckoffSignal(
                signal_type="no_signal",
                confidence=ConfidenceLevel.B,
                phase=WyckoffPhase.MARKUP,
                description="周线上涨延续",
            ),
            risk_reward=RiskRewardProjection(),
            trading_plan=TradingPlan(direction="空仓观望", confidence=ConfidenceLevel.B),
        )
        monthly_report = WyckoffReport(
            symbol="000001.SH",
            period="月线",
            structure=WyckoffStructure(
                phase=WyckoffPhase.MARKUP,
                current_price=12.5,
                current_date="2026-04-30",
            ),
            signal=WyckoffSignal(
                signal_type="no_signal",
                confidence=ConfidenceLevel.B,
                phase=WyckoffPhase.MARKUP,
                description="月线上涨延续",
            ),
            risk_reward=RiskRewardProjection(),
            trading_plan=TradingPlan(direction="空仓观望", confidence=ConfidenceLevel.B),
        )

        merged = analyzer._merge_multitimeframe_reports(
            symbol="000001.SH",
            daily_report=daily_report,
            weekly_report=weekly_report,
            monthly_report=monthly_report,
        )

        self.assertEqual(merged.trading_plan.direction, "空仓观望")
        self.assertIn("No Trade Zone", merged.trading_plan.current_qualification)

    def test_multiframe_accumulation_high_rr_gets_wait_trigger_note(self):
        analyzer = WyckoffAnalyzer()
        daily_report = WyckoffReport(
            symbol="000001.SH",
            period="日线",
            structure=WyckoffStructure(
                phase=WyckoffPhase.ACCUMULATION,
                current_price=8.5,
                current_date="2026-04-29",
            ),
            signal=WyckoffSignal(
                signal_type="no_signal",
                confidence=ConfidenceLevel.C,
                phase=WyckoffPhase.ACCUMULATION,
                description="积累结构待确认",
            ),
            risk_reward=RiskRewardProjection(
                entry_price=8.5,
                stop_loss=7.9,
                first_target=10.6,
                reward_risk_ratio=3.5,
            ),
            trading_plan=TradingPlan(
                direction="空仓观望",
                trigger_condition="等待确认",
                invalidation_point="跌破 7.9",
                first_target="10.6",
                confidence=ConfidenceLevel.C,
            ),
        )
        weekly_report = WyckoffReport(
            symbol="000001.SH",
            period="周线",
            structure=WyckoffStructure(
                phase=WyckoffPhase.UNKNOWN,
                current_price=8.5,
                current_date="2026-04-25",
            ),
            signal=WyckoffSignal(
                signal_type="no_signal",
                confidence=ConfidenceLevel.C,
                phase=WyckoffPhase.UNKNOWN,
                description="周线震荡待确认",
            ),
            risk_reward=RiskRewardProjection(),
            trading_plan=TradingPlan(direction="空仓观望", confidence=ConfidenceLevel.C),
        )
        monthly_report = WyckoffReport(
            symbol="000001.SH",
            period="月线",
            structure=WyckoffStructure(
                phase=WyckoffPhase.MARKUP,
                current_price=8.5,
                current_date="2026-04-30",
            ),
            signal=WyckoffSignal(
                signal_type="no_signal",
                confidence=ConfidenceLevel.B,
                phase=WyckoffPhase.MARKUP,
                description="月线趋势向上",
            ),
            risk_reward=RiskRewardProjection(),
            trading_plan=TradingPlan(direction="空仓观望", confidence=ConfidenceLevel.B),
        )

        merged = analyzer._merge_multitimeframe_reports(
            symbol="000001.SH",
            daily_report=daily_report,
            weekly_report=weekly_report,
            monthly_report=monthly_report,
        )

        self.assertIn("等待触发", merged.signal.description)
        self.assertIn("赔率充足", merged.trading_plan.current_qualification)

    def test_multiframe_weekly_unknown_preserves_actionable_markup_watch(self):
        analyzer = WyckoffAnalyzer()
        daily_report = WyckoffReport(
            symbol="000001.SH",
            period="日线",
            structure=WyckoffStructure(
                phase=WyckoffPhase.MARKUP,
                current_price=10.5,
                current_date="2026-04-29",
                trading_range_low=9.2,
                trading_range_high=12.8,
            ),
            signal=WyckoffSignal(
                signal_type="no_signal",
                confidence=ConfidenceLevel.B,
                phase=WyckoffPhase.MARKUP,
                description="当前处于 Markup 回踩中的 Lack of Supply / Test 观察区，等待缩量测试结束",
            ),
            risk_reward=RiskRewardProjection(
                entry_price=10.5,
                stop_loss=9.2,
                first_target=12.8,
                reward_risk_ratio=3.0,
            ),
            trading_plan=TradingPlan(
                direction="空仓观望",
                current_qualification="当前处于 Markup 回踩中的 Lack of Supply / Test 观察区，等待缩量测试结束",
                trigger_condition="等待回踩确认",
                invalidation_point="跌破 9.2",
                first_target="12.8",
                confidence=ConfidenceLevel.B,
            ),
        )
        weekly_report = WyckoffReport(
            symbol="000001.SH",
            period="周线",
            structure=WyckoffStructure(
                phase=WyckoffPhase.UNKNOWN,
                current_price=10.5,
                current_date="2026-04-25",
            ),
            signal=WyckoffSignal(
                signal_type="no_signal",
                confidence=ConfidenceLevel.C,
                phase=WyckoffPhase.UNKNOWN,
                description="周线震荡待确认",
            ),
            risk_reward=RiskRewardProjection(),
            trading_plan=TradingPlan(direction="空仓观望", confidence=ConfidenceLevel.C),
        )
        monthly_report = WyckoffReport(
            symbol="000001.SH",
            period="月线",
            structure=WyckoffStructure(
                phase=WyckoffPhase.MARKUP,
                current_price=10.5,
                current_date="2026-04-30",
            ),
            signal=WyckoffSignal(
                signal_type="no_signal",
                confidence=ConfidenceLevel.B,
                phase=WyckoffPhase.MARKUP,
                description="月线上涨延续",
            ),
            risk_reward=RiskRewardProjection(),
            trading_plan=TradingPlan(direction="空仓观望", confidence=ConfidenceLevel.B),
        )

        merged = analyzer._merge_multitimeframe_reports(
            symbol="000001.SH",
            daily_report=daily_report,
            weekly_report=weekly_report,
            monthly_report=monthly_report,
        )

        self.assertEqual(merged.trading_plan.direction, "持有观察 / 空仓者观望")
        self.assertIn("周线", merged.trading_plan.preconditions)

    def test_multiframe_unknown_under_markup_gets_structured_wait_plan(self):
        analyzer = WyckoffAnalyzer()
        daily_report = WyckoffReport(
            symbol="000001.SH",
            period="日线",
            structure=WyckoffStructure(
                phase=WyckoffPhase.UNKNOWN,
                current_price=8.2,
                current_date="2026-04-29",
                trading_range_low=7.7,
                trading_range_high=9.6,
            ),
            signal=WyckoffSignal(
                signal_type="no_signal",
                confidence=ConfidenceLevel.C,
                phase=WyckoffPhase.UNKNOWN,
                description="阶段不明确，但正在演化为 Phase A/AR 反弹观察区，建议继续空仓等待 ST 或 TR 边界明确",
            ),
            risk_reward=RiskRewardProjection(
                entry_price=8.2,
                stop_loss=7.7,
                first_target=9.6,
                reward_risk_ratio=2.8,
            ),
            trading_plan=TradingPlan(
                direction="空仓观望",
                current_qualification="阶段不明确，但正在演化为 Phase A/AR 反弹观察区，建议继续空仓等待 ST 或 TR 边界明确",
                trigger_condition="N/A",
                invalidation_point="N/A",
                first_target="N/A",
                confidence=ConfidenceLevel.C,
            ),
        )
        weekly_report = WyckoffReport(
            symbol="000001.SH",
            period="周线",
            structure=WyckoffStructure(
                phase=WyckoffPhase.MARKUP,
                current_price=8.2,
                current_date="2026-04-25",
            ),
            signal=WyckoffSignal(
                signal_type="no_signal",
                confidence=ConfidenceLevel.B,
                phase=WyckoffPhase.MARKUP,
                description="周线上涨延续",
            ),
            risk_reward=RiskRewardProjection(),
            trading_plan=TradingPlan(direction="空仓观望", confidence=ConfidenceLevel.B),
        )
        monthly_report = WyckoffReport(
            symbol="000001.SH",
            period="月线",
            structure=WyckoffStructure(
                phase=WyckoffPhase.MARKUP,
                current_price=8.2,
                current_date="2026-04-30",
            ),
            signal=WyckoffSignal(
                signal_type="no_signal",
                confidence=ConfidenceLevel.B,
                phase=WyckoffPhase.MARKUP,
                description="月线上涨延续",
            ),
            risk_reward=RiskRewardProjection(),
            trading_plan=TradingPlan(direction="空仓观望", confidence=ConfidenceLevel.B),
        )

        merged = analyzer._merge_multitimeframe_reports(
            symbol="000001.SH",
            daily_report=daily_report,
            weekly_report=weekly_report,
            monthly_report=monthly_report,
        )

        self.assertEqual(merged.structure.phase, WyckoffPhase.UNKNOWN)
        self.assertIn("上级周期仍偏多", merged.trading_plan.current_qualification)
        self.assertIn("ST", merged.trading_plan.trigger_condition)


if __name__ == "__main__":
    unittest.main()
