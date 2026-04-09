# -*- coding: utf-8 -*-
"""
Unit Tests for Wyckoff Analysis Module
"""

import unittest
from datetime import datetime, timedelta

import pandas as pd
import numpy as np

from src.wyckoff import (
    WyckoffAnalyzer,
    WyckoffPhase,
    ConfidenceLevel,
    VolumeLevel,
)
from src.wyckoff.models import (
    BCPoint,
    SCPoint,
    WyckoffReport,
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


if __name__ == "__main__":
    unittest.main()
