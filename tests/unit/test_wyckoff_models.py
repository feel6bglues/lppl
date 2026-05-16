# -*- coding: utf-8 -*-
"""
威科夫模型单元测试
"""
from datetime import datetime

import pytest

from src.wyckoff.models import (
    AnalysisResult,
    AnalysisState,
    BCResult,
    ChartManifest,
    ChartManifestItem,
    DailyRuleResult,
    PhaseResult,
    PreprocessingResult,
    VisualEvidence,
)


class TestModels:
    """模型测试"""
    
    def test_daily_rule_result_creation(self):
        """测试 DailyRuleResult 实例化"""
        result = DailyRuleResult(
            symbol="000300.SH",
            asset_type="index",
            analysis_date="2026-04-08",
            input_source="data",
            preprocessing=PreprocessingResult(
                trend_direction="uptrend",
                volume_label="above_average",
                volatility_layer="medium",
                local_highs=[],
                local_lows=[],
                gap_candidates=[],
                long_wick_candidates=[],
                limit_anomalies=[],
            ),
            bc_result=BCResult(
                found=True,
                candidate_index=100,
                candidate_date="2026-01-15",
                candidate_price=120.5,
                volume_label="extreme_high",
                enhancement_signals=["long_upper_wick"],
            ),
            phase_result=PhaseResult(
                phase="accumulation",
                boundary_upper_zone="125.0",
                boundary_lower_zone="95.0",
                boundary_sources=["BC", "AR"],
            ),
            effort_result=None,  # 简化测试
            phase_c_test=None,
            counterfactual=None,
            risk=None,
            plan=None,
            confidence="B",
            decision="long_setup",
            abandon_reason="",
        )
        
        assert result.symbol == "000300.SH"
        assert result.confidence == "B"
        assert result.decision == "long_setup"
    
    def test_analysis_result_creation(self):
        """测试 AnalysisResult 实例化"""
        result = AnalysisResult(
            symbol="600519.SH",
            asset_type="stock",
            analysis_date="2026-04-08",
            input_sources=["data", "images"],
            timeframes_seen=["daily", "weekly"],
            bc_found=True,
            phase="accumulation",
            micro_action="spring_candidate",
            boundary_upper_zone="1800",
            boundary_lower_zone="1600",
            volume_profile_label="contracted",
            spring_detected=True,
            utad_detected=False,
            counterfactual_summary="weekly overhead supply",
            t1_risk_assessment="medium",
            rr_assessment="pass",
            decision="watch_only",
            trigger="spring_confirmation",
            invalidation="1580",
            target_1="1800",
            confidence="B",
            abandon_reason="",
            conflicts=[],
            image_bundle=None,
            consistency_score="high_alignment",
            weekly_context="supportive",
            intraday_context="positive",
        )
        
        assert result.symbol == "600519.SH"
        assert result.spring_detected
        assert result.decision == "watch_only"
    
    def test_chart_manifest_creation(self):
        """测试 ChartManifest 实例化"""
        item = ChartManifestItem(
            file_path="/test/600519_daily.png",
            file_name="600519_daily.png",
            relative_dir="plots",
            modified_time=datetime.now().isoformat(),
            symbol="600519.SH",
            inferred_timeframe="daily",
            image_quality="high",
        )
        
        manifest = ChartManifest(
            files=[item],
            total_count=1,
            usable_count=1,
            scan_time=datetime.now().isoformat(),
        )
        
        assert manifest.total_count == 1
        assert manifest.files[0].symbol == "600519.SH"
    
    def test_visual_evidence_creation(self):
        """测试 VisualEvidence 实例化"""
        evidence = VisualEvidence(
            visual_trend="uptrend",
            visual_phase_hint="possible_markup",
            visual_boundaries={"upper": "resistance_zone"},
            visual_anomalies=["gap"],
            visual_volume_label="above_average",
        )
        
        assert evidence.visual_trend == "uptrend"
        assert evidence.visual_boundaries["upper"] == "resistance_zone"
    
    def test_analysis_state_creation(self):
        """测试 AnalysisState 实例化"""
        state = AnalysisState(
            symbol="000300.SH",
            asset_type="index",
            analysis_date="2026-04-08",
            last_phase="accumulation",
            last_micro_action="spring_candidate",
            last_confidence="B",
            bc_found=True,
            spring_detected=True,
            freeze_until="2026-04-11",
            watch_status="cooling_down",
            trigger_armed=True,
            trigger_text="spring_confirmation",
            invalid_level="3500",
            target_1="4000",
            weekly_context="supportive",
            intraday_context="positive",
            conflict_summary=[],
            last_decision="watch_only",
            abandon_reason="",
        )
        
        assert state.spring_detected
        assert state.watch_status == "cooling_down"
        assert state.freeze_until == "2026-04-11"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
