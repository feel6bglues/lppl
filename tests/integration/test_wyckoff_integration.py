# -*- coding: utf-8 -*-
"""
威科夫系统集成测试

测试三种运行模式:
1. data-only
2. image-only
3. fusion
"""
import os
import shutil
import tempfile

import pytest

from src.wyckoff.data_engine import DataEngine
from src.wyckoff.fusion_engine import FusionEngine
from src.wyckoff.image_engine import ImageEngine
from src.wyckoff.models import AnalysisState


class TestIntegration:
    """集成测试"""
    
    @pytest.fixture
    def temp_output_dir(self):
        """创建临时输出目录"""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir, ignore_errors=True)
    
    def test_data_only_mode(self, temp_output_dir):
        """测试 data-only 模式"""
        # 使用真实指数数据测试
        from src.data.manager import DataManager
        
        data_manager = DataManager()
        df = data_manager.get_data("000300.SH")
        
        if df is None or df.empty:
            pytest.skip("000300.SH 数据不可用")
        
        engine = DataEngine()
        result = engine.run(df, "000300.SH", "index")
        
        # 验证输出
        assert result is not None
        assert result.symbol == "000300.SH"
        assert result.confidence in ["A", "B", "C", "D"]
        assert result.decision in ["long_setup", "watch_only", "no_trade_zone", "abandon"]
    
    def test_image_engine_scan(self, temp_output_dir):
        """测试图像引擎扫描"""
        # 创建测试图片目录
        test_plots_dir = os.path.join(temp_output_dir, "test_plots")
        os.makedirs(test_plots_dir, exist_ok=True)
        
        # 创建假图片文件
        test_image_path = os.path.join(test_plots_dir, "600519_daily.png")
        with open(test_image_path, "wb") as f:
            f.write(b"fake_image_data")
        
        engine = ImageEngine()
        bundle = engine.run(chart_dir=test_plots_dir)
        
        # 验证输出
        assert bundle is not None
        assert bundle.manifest.total_count == 1
        assert bundle.manifest.files[0].symbol == "600519.SH"
    
    def test_fusion_engine_conflict_matrix(self):
        """测试融合引擎冲突矩阵"""
        from src.wyckoff.models import (
            BCResult,
            ChartManifest,
            CounterfactualResult,
            DailyRuleResult,
            EffortResult,
            ImageEvidenceBundle,
            PhaseCTestResult,
            PhaseResult,
            PreprocessingResult,
            RiskAssessment,
            TradingPlan,
            VisualEvidence,
        )
        
        # 创建数据结果 (Distribution)
        data_result = DailyRuleResult(
            symbol="600519.SH",
            asset_type="stock",
            analysis_date="2026-04-08",
            input_source="data",
            preprocessing=PreprocessingResult(
                trend_direction="downtrend",
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
                candidate_price=50.0,
                volume_label="extreme_high",
                enhancement_signals=[],
            ),
            phase_result=PhaseResult(
                phase="distribution",
                boundary_upper_zone="50",
                boundary_lower_zone="40",
                boundary_sources=["BC"],
            ),
            effort_result=EffortResult(
                phenomena=[],
                accumulation_evidence=0.0,
                distribution_evidence=0.5,
                net_bias="distribution",
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
                is_utad_not_breakout="unlikely",
                is_distribution_not_accumulation="likely",
                is_chaos_not_phase_c="unlikely",
                liquidity_vacuum_risk="low",
                total_pro_score=0.2,
                total_con_score=0.5,
                conclusion_overturned=True,
            ),
            risk=RiskAssessment(
                t1_risk_level="medium",
                t1_structural_description="",
                rr_ratio=2.0,
                rr_assessment="fail",
                freeze_until=None,
            ),
            plan=TradingPlan(
                current_assessment="distribution",
                execution_preconditions=[],
                direction="watch_only",
                entry_trigger="",
                invalidation="50",
                target_1="",
            ),
            confidence="C",
            decision="watch_only",
            abandon_reason="",
        )
        
        # 创建图像证据 (Markup)
        image_bundle = ImageEvidenceBundle(
            manifest=ChartManifest(
                files=[],
                total_count=0,
                usable_count=0,
                scan_time="2026-04-08",
            ),
            detected_timeframes=["daily"],
            overall_image_quality="medium",
            visual_evidence_list=[
                VisualEvidence(
                    visual_trend="uptrend",
                    visual_phase_hint="possible_markup",
                    visual_boundaries={},
                    visual_anomalies=[],
                    visual_volume_label="above_average",
                )
            ],
            trust_level="medium",
        )
        
        # 融合
        engine = FusionEngine()
        result = engine.fuse(data_result, image_bundle)
        
        # 验证保守降级 (R:R fail 会导致 abandon)
        assert result.decision == "abandon"
        assert result.rr_assessment == "fail"
    
    def test_state_manager_persistence(self, temp_output_dir):
        """测试状态管理持久化"""
        from src.wyckoff.fusion_engine import StateManager
        
        state_manager = StateManager(temp_output_dir)
        
        # 创建测试状态
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
        
        # 保存状态
        state_path = state_manager.save_state(state)
        
        # 验证文件存在
        assert os.path.exists(state_path)
        
        # 加载状态
        loaded_state = state_manager.load_state("000300.SH")
        
        # 验证加载正确
        assert loaded_state is not None
        assert loaded_state.spring_detected == True
        assert loaded_state.freeze_until == "2026-04-11"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
