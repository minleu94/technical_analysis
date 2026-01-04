import pandas as pd
import numpy as np
import talib
from .technical_indicators import TechnicalIndicatorCalculator

class TechnicalAnalyzer:
    """技術指標分析類，提供高級接口對技術指標進行計算和分析"""
    
    def __init__(self):
        """初始化技術分析器"""
        # 使用TechnicalIndicatorCalculator作為底層計算引擎
        self.calculator = TechnicalIndicatorCalculator()
        # 複用映射關係
        self.column_mapping = self.calculator.column_mapping
        self.reverse_mapping = self.calculator.reverse_mapping
    
    def _get_column_name(self, df, eng_name):
        """獲取對應的列名，使用calculator的方法"""
        return self.calculator._get_column_name(df, eng_name)
    
    def add_momentum_indicators(self, df):
        """添加動量指標
        
        Args:
            df: 股票數據DataFrame
            
        Returns:
            DataFrame: 添加動量指標後的數據
        """
        df_result = df.copy()
        
        # 使用calculator計算RSI和MACD
        # 現在calculator.calculate_momentum_indicators返回字典而不是DataFrame
        momentum_indicators = self.calculator.calculate_momentum_indicators(df)
        if momentum_indicators:
            for key, value in momentum_indicators.items():
                df_result[key] = value
        
        # 使用calculator計算KD指標
        # 現在calculator.calculate_kd_indicator返回字典而不是DataFrame
        kd_indicators = self.calculator.calculate_kd_indicator(df)
        if kd_indicators:
            df_result['SlowK'] = kd_indicators.get('slowk')
            df_result['SlowD'] = kd_indicators.get('slowd')
            
        return df_result
    
    def add_volatility_indicators(self, df):
        """添加波動性指標
        
        Args:
            df: 股票數據DataFrame
            
        Returns:
            DataFrame: 添加波動性指標後的數據
        """
        df_result = df.copy()
        
        # 使用calculator計算波動性指標
        # 現在calculator.calculate_volatility_indicators返回字典而不是DataFrame
        volatility_indicators = self.calculator.calculate_volatility_indicators(df)
        if volatility_indicators:
            df_result['BB_Upper'] = volatility_indicators.get('upperband')
            df_result['BB_Middle'] = volatility_indicators.get('middleband')
            df_result['BB_Lower'] = volatility_indicators.get('lowerband')
            df_result['SAR'] = volatility_indicators.get('SAR')
            
        # 添加ATR（calculator中可能沒有）
        high_col = self._get_column_name(df, 'High')
        low_col = self._get_column_name(df, 'Low')
        close_col = self._get_column_name(df, 'Close')
        if high_col and low_col and close_col:
            high_prices = np.ascontiguousarray(df[high_col].values, dtype=np.float64)
            low_prices = np.ascontiguousarray(df[low_col].values, dtype=np.float64)
            close_prices = np.ascontiguousarray(df[close_col].values, dtype=np.float64)
            df_result['ATR'] = talib.ATR(
                high_prices,
                low_prices,
                close_prices,
                timeperiod=14
            )
            
        return df_result
    
    def add_trend_indicators(self, df):
        """添加趨勢指標
        
        Args:
            df: 股票數據DataFrame
            
        Returns:
            DataFrame: 添加趨勢指標後的數據
        """
        df_result = df.copy()
        
        # 使用calculator計算趨勢指標
        # 現在calculator.calculate_trend_indicators返回字典而不是DataFrame
        trend_indicators = self.calculator.calculate_trend_indicators(df)
        if trend_indicators:
            df_result['TSF'] = trend_indicators.get('TSF')
        
        # 添加ADX（calculator中可能沒有）
        high_col = self._get_column_name(df, 'High')
        low_col = self._get_column_name(df, 'Low')
        close_col = self._get_column_name(df, 'Close')
        if high_col and low_col and close_col:
            # 清理數據：將 '--' 和其他無效值轉換為 NaN
            def clean_price_series(series):
                """清理價格序列"""
                if series.dtype == 'object':
                    series = series.replace(['--', '', 'nan', 'NaN', 'None'], np.nan)
                    series = pd.to_numeric(series, errors='coerce')
                # 轉換為 numpy array
                prices = np.ascontiguousarray(series.values, dtype=np.float64)
                # 填充 NaN
                mask = np.isnan(prices)
                if mask.any():
                    prices = pd.Series(prices).ffill().bfill().fillna(0.0).values
                return prices
            
            high_prices = clean_price_series(df[high_col])
            low_prices = clean_price_series(df[low_col])
            close_prices = clean_price_series(df[close_col])
            
            df_result['ADX'] = talib.ADX(
                high_prices,
                low_prices,
                close_prices,
                timeperiod=14
            )
            
        return df_result 