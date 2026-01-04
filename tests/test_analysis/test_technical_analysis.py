import pytest
import pandas as pd
import numpy as np
from analysis_module.technical_analysis.technical_indicators import TechnicalIndicatorCalculator
from analysis_module.technical_analysis.technical_analyzer import TechnicalAnalyzer

class TestTechnicalIndicators:
    """測試技術指標計算"""
    
    def test_moving_averages(self, sample_stock_data):
        """測試移動平均線計算"""
        calculator = TechnicalIndicatorCalculator()
        df = calculator.calculate_moving_averages(sample_stock_data)
        
        assert 'MA5' in df.columns
        assert 'MA10' in df.columns
        assert 'MA20' in df.columns
        assert not df['MA5'].isna().all()
        assert not df['MA10'].isna().all()
        assert not df['MA20'].isna().all()
    
    def test_momentum_indicators(self, sample_stock_data):
        """測試動量指標計算"""
        calculator = TechnicalIndicatorCalculator()
        df = calculator.calculate_momentum_indicators(sample_stock_data)
        
        assert 'RSI' in df.columns
        assert 'MACD' in df.columns
        assert 'MACD_Signal' in df.columns
        assert 'MACD_Hist' in df.columns
        assert not df['RSI'].isna().all()
        assert not df['MACD'].isna().all()
    
    def test_volatility_indicators(self, sample_stock_data):
        """測試波動率指標計算"""
        calculator = TechnicalIndicatorCalculator()
        df = calculator.calculate_volatility_indicators(sample_stock_data)
        
        assert 'ATR' in df.columns
        assert 'BB_Upper' in df.columns
        assert 'BB_Lower' in df.columns
        assert not df['ATR'].isna().all()
        assert not df['BB_Upper'].isna().all()
        assert not df['BB_Lower'].isna().all()

class TestTechnicalAnalyzer:
    """測試技術分析器"""
    
    def test_trend_analysis(self, sample_stock_data):
        """測試趨勢分析"""
        analyzer = TechnicalAnalyzer()
        df = analyzer.analyze_trend(sample_stock_data)
        
        assert 'Trend' in df.columns
        assert 'Trend_Strength' in df.columns
        assert not df['Trend'].isna().all()
        assert not df['Trend_Strength'].isna().all()
    
    def test_support_resistance(self, sample_stock_data):
        """測試支撐阻力位分析"""
        analyzer = TechnicalAnalyzer()
        levels = analyzer.find_support_resistance(sample_stock_data)
        
        assert isinstance(levels, dict)
        assert 'support' in levels
        assert 'resistance' in levels
        assert len(levels['support']) > 0
        assert len(levels['resistance']) > 0
    
    def test_pattern_recognition(self, sample_stock_data):
        """測試形態識別"""
        analyzer = TechnicalAnalyzer()
        patterns = analyzer.identify_patterns(sample_stock_data)
        
        assert isinstance(patterns, list)
        assert len(patterns) > 0
        for pattern in patterns:
            assert 'type' in pattern
            assert 'start_date' in pattern
            assert 'end_date' in pattern 