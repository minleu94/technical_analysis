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
    
    def add_momentum_indicators(self, df, config=None, full_config=None):
        """添加動量指標
        
        Args:
            df: 股票數據DataFrame
            config: 動量指標配置字典
            full_config: 完整配置字典
            
        Returns:
            DataFrame: 添加動量指標後的數據
        """
        df_result = df.copy()
        
        # 取得 schema_version
        schema_version = 0
        if full_config and isinstance(full_config, dict):
            try:
                schema_version = int(full_config.get('config_schema_version', 0))
            except (ValueError, TypeError):
                pass
        default_enabled = (schema_version < 1)
        
        rsi_params = None
        macd_params = None
        kd_params = None
        
        if config is None:
            # config 為 None 代表全部啟用預設
            rsi_params = {}
            macd_params = {}
            kd_params = {}
        elif isinstance(config, dict):
            def get_sub_params(key):
                if key in config:
                    sub_cfg = config[key]
                    if isinstance(sub_cfg, dict):
                        if sub_cfg.get('enabled', True):
                            return sub_cfg
                    elif sub_cfg is True:
                        return {}
                else:
                    if default_enabled:
                        return {}
                return None
                
            rsi_params = get_sub_params('rsi')
            macd_params = get_sub_params('macd')
            kd_params = get_sub_params('kd')
        
        # 只有在至少啟用一個指標時，才呼叫 calculate_momentum_indicators
        if rsi_params is not None or macd_params is not None:
            momentum_indicators = self.calculator.calculate_momentum_indicators(
                df_result, 
                rsi_params=rsi_params, 
                macd_params=macd_params, 
                full_config=full_config
            )
            if momentum_indicators:
                for key, value in momentum_indicators.items():
                    df_result[key] = value
        
        # 只有在啟用 KD 時，才呼叫 calculate_kd_indicator
        if kd_params is not None:
            kd_indicators = self.calculator.calculate_kd_indicator(
                df_result, 
                params=kd_params, 
                full_config=full_config
            )
            if kd_indicators:
                df_result['SlowK'] = kd_indicators.get('slowk')
                df_result['SlowD'] = kd_indicators.get('slowd')
            
        return df_result
    
    def add_volatility_indicators(self, df, config=None, full_config=None):
        """添加波動性指標
        
        Args:
            df: 股票數據DataFrame
            config: 波動率配置字典
            full_config: 完整配置字典
            
        Returns:
            DataFrame: 添加波動性指標後的數據
        """
        df_result = df.copy()
        
        # 取得 schema_version
        schema_version = 0
        if full_config and isinstance(full_config, dict):
            try:
                schema_version = int(full_config.get('config_schema_version', 0))
            except (ValueError, TypeError):
                pass
        default_enabled = (schema_version < 1)
        
        bollinger_params = None
        sar_params = None
        atr_params = None
        
        if config is None:
            bollinger_params = {}
            sar_params = {}
            atr_params = {}
        elif isinstance(config, dict):
            def get_sub_params(key):
                if key in config:
                    sub_cfg = config[key]
                    if isinstance(sub_cfg, dict):
                        if sub_cfg.get('enabled', True):
                            return sub_cfg
                    elif sub_cfg is True:
                        return {}
                else:
                    if default_enabled:
                        return {}
                return None
                
            bollinger_params = get_sub_params('bollinger')
            sar_params = get_sub_params('sar')
            atr_params = get_sub_params('atr')
        
        # 只有在至少啟用一個指標時，才呼叫 calculate_volatility_indicators
        if bollinger_params is not None or sar_params is not None:
            volatility_indicators = self.calculator.calculate_volatility_indicators(
                df_result, 
                bollinger_params=bollinger_params, 
                sar_params=sar_params, 
                full_config=full_config
            )
            if volatility_indicators:
                if 'upperband' in volatility_indicators:
                    df_result['BB_Upper'] = volatility_indicators['upperband']
                if 'middleband' in volatility_indicators:
                    df_result['BB_Middle'] = volatility_indicators['middleband']
                if 'lowerband' in volatility_indicators:
                    df_result['BB_Lower'] = volatility_indicators['lowerband']
                if 'SAR' in volatility_indicators:
                    df_result['SAR'] = volatility_indicators['SAR']
            
        # 只有在啟用 ATR 時，才呼叫 calculate_atr_indicator
        if atr_params is not None:
            atr_indicators = self.calculator.calculate_atr_indicator(
                df_result, 
                params=atr_params, 
                full_config=full_config
            )
            if atr_indicators:
                df_result['ATR'] = atr_indicators.get('ATR')
            
        return df_result
    
    def add_trend_indicators(self, df, config=None, full_config=None):
        """添加趨勢指標
        
        Args:
            df: 股票數據DataFrame
            config: 趨勢配置字典
            full_config: 完整配置字典
            
        Returns:
            DataFrame: 添加趨勢指標後的數據
        """
        df_result = df.copy()
        
        # 取得 schema_version
        schema_version = 0
        if full_config and isinstance(full_config, dict):
            try:
                schema_version = int(full_config.get('config_schema_version', 0))
            except (ValueError, TypeError):
                pass
        default_enabled = (schema_version < 1)
        
        tsf_params = None
        adx_params = None
        ma_params = None
        
        if config is None:
            tsf_params = {}
            adx_params = {}
            ma_params = {}
        elif isinstance(config, dict):
            def get_sub_params(key):
                if key in config:
                    sub_cfg = config[key]
                    if isinstance(sub_cfg, dict):
                        if sub_cfg.get('enabled', True):
                            return sub_cfg
                    elif sub_cfg is True:
                        return {}
                else:
                    if default_enabled:
                        return {}
                return None
                
            tsf_params = get_sub_params('tsf')
            adx_params = get_sub_params('adx')
            ma_params = get_sub_params('ma')
        
        # 只有在啟用 TSF 時，才呼叫 calculate_trend_indicators
        if tsf_params is not None:
            trend_indicators = self.calculator.calculate_trend_indicators(
                df_result, 
                tsf_params=tsf_params, 
                full_config=full_config
            )
            if trend_indicators:
                df_result['TSF'] = trend_indicators.get('TSF')
        
        # 只有在啟用 ADX 時，才呼叫 calculate_adx_indicator
        if adx_params is not None:
            adx_indicators = self.calculator.calculate_adx_indicator(
                df_result, 
                params=adx_params, 
                full_config=full_config
            )
            if adx_indicators:
                df_result['ADX'] = adx_indicators.get('ADX')
            
        # 只有在啟用 MA 時，才呼叫 calculate_ma_series
        if ma_params is not None:
            df_result = self.calculator.calculate_ma_series(
                df_result, 
                params=ma_params, 
                full_config=full_config
            )
            
        return df_result 
