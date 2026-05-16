# -*- coding: utf-8 -*-
"""
威科夫规则引擎单元测试

测试覆盖:
- BC 未找到时直接 D 级+abandon
- Distribution/Markdown 不能输出多头
- Spring 后 T+3 冷冻期内只允许观察
- R:R < 1:2.5 时强制放弃
"""
from datetime import datetime

import numpy as np
import pandas as pd
import pytest

from src.exceptions import InvalidInputDataError
from src.wyckoff.data_engine import DataEngine


def create_test_dataframe(
    rows: int = 200,
    trend: str = "uptrend",
    has_bc: bool = True,
    has_spring: bool = False,
) -> pd.DataFrame:
    """创建测试用的 OHLCV DataFrame"""
    dates = pd.date_range(start="2023-01-01", periods=rows, freq="D")
    
    # 基础价格
    base_price = 100.0
    
    if trend == "uptrend":
        prices = np.linspace(base_price, base_price * 1.5, rows)
    elif trend == "downtrend":
        prices = np.linspace(base_price, base_price * 0.7, rows)
    else:
        prices = np.linspace(base_price, base_price, rows)
    
    # 添加波动
    np.random.seed(42)
    noise = np.random.randn(rows) * 2
    prices = prices + noise
    
    # 创建 BC 形态
    if has_bc and rows > 100:
        bc_idx = rows - 100
        prices[bc_idx] = prices[bc_idx] * 1.2  # BC 高点
        prices[bc_idx+1:bc_idx+10] = prices[bc_idx+1:bc_idx+10] * 0.9  # BC 后下跌
    
    # 创建 Spring 形态
    if has_spring and rows > 50:
        spring_idx = rows - 3
        prices[spring_idx] = prices[spring_idx] * 0.95  # 刺穿下边界
    
    df = pd.DataFrame({
        'date': dates,
        'open': prices,
        'high': prices * 1.02,
        'low': prices * 0.98,
        'close': prices,
        'volume': np.random.randn(rows) * 100000 + 500000,
    })
    
    df['volume'] = df['volume'].abs().astype(int)
    
    return df


class TestDataEngine:
    """规则引擎测试"""
    
    def test_bc_not_found_returns_abandon(self):
        """测试：找不到 BC 时直接 D 级+abandon"""
        # 创建无 BC 的数据
        df = create_test_dataframe(has_bc=False)
        
        engine = DataEngine()
        result = engine.run(df, "000300.SH", "index")
        
        assert not result.bc_result.found
        assert result.confidence == "D"
        assert result.decision == "abandon"
        assert result.abandon_reason == "bc_not_found"
    
    def test_distribution_phase_no_long_setup(self):
        """测试：Distribution 阶段不能输出多头"""
        # 创建下跌趋势数据 (可能判定为 distribution)
        df = create_test_dataframe(trend="downtrend", has_bc=True)
        
        engine = DataEngine()
        result = engine.run(df, "000300.SH", "index")
        
        # Distribution 或 Markdown 阶段不能给多头
        if result.phase_result.phase in ["distribution", "markdown"]:
            assert result.plan.direction in ["watch_only", "abandon"]
    
    def test_spring_freeze_period(self):
        """测试：Spring 后 T+3 冷冻期"""
        # 创建 Spring 形态数据
        df = create_test_dataframe(has_spring=True)
        
        engine = DataEngine()
        result = engine.run(df, "000300.SH", "index")
        
        if result.phase_c_test.spring_detected:
            assert result.risk.freeze_until is not None
            # 冷冻期内只能 watch_only
            if result.risk.freeze_until:
                freeze_date = datetime.strptime(result.risk.freeze_until, "%Y-%m-%d")
                if datetime.now() <= freeze_date:
                    assert result.plan.direction == "watch_only"
    
    def test_unfavorable_rr_abandon(self):
        """测试：R:R < 1:2.5 时强制放弃"""
        # 创建数据使 R:R 不足 (使用 uptrend 确保 BC 能找到)
        df = create_test_dataframe(trend="uptrend", has_bc=True)
        
        engine = DataEngine()
        result = engine.run(df, "000300.SH", "index")
        
        # R:R 不合格时必须 abandon
        # 注意：如果 BC 未找到，也会 abandon，原因会是 bc_not_found
        if result.risk.rr_assessment == "fail":
            assert result.plan.direction == "abandon"
            assert result.abandon_reason in ["unfavorable_rr_or_structure", "bc_not_found"]
    
    def test_insufficient_data_rows(self):
        """测试：数据行数不足时拒绝分析"""
        # 创建少于 100 行的数据
        df = create_test_dataframe(rows=50)
        
        engine = DataEngine()
        
        with pytest.raises(InvalidInputDataError):
            engine.run(df, "000300.SH", "index")
    
    def test_volume_labels_enum(self):
        """测试：量能标签只使用允许枚举"""
        df = create_test_dataframe()
        
        engine = DataEngine()
        result = engine.run(df, "000300.SH", "index")
        
        valid_labels = ["extreme_high", "above_average", "contracted", "extreme_contracted"]
        assert result.preprocessing.volume_label in valid_labels
    
    def test_phase_enum(self):
        """测试：阶段只输出 5 种合法值"""
        df = create_test_dataframe()
        
        engine = DataEngine()
        result = engine.run(df, "000300.SH", "index")
        
        valid_phases = ["accumulation", "markup", "distribution", "markdown", "no_trade_zone"]
        assert result.phase_result.phase in valid_phases
    
    def test_confidence_enum(self):
        """测试：置信度只输出 A/B/C/D"""
        df = create_test_dataframe()
        
        engine = DataEngine()
        result = engine.run(df, "000300.SH", "index")
        
        valid_confidence = ["A", "B", "C", "D"]
        assert result.confidence in valid_confidence


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
