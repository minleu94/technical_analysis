"""
TA-Lib 兼容性模組
使用 ta 套件來替代 talib 的功能
"""

import pandas as pd
import numpy as np
import ta

# 創建一個兼容性類來模擬 talib 的 API
class TalibCompatibility:
    """TA-Lib 兼容性類，使用 ta 套件實現相同的功能"""
    
    @staticmethod
    def SMA(close, timeperiod=30):
        """簡單移動平均線"""
        return ta.trend.sma_indicator(close, window=timeperiod)
    
    @staticmethod
    def EMA(close, timeperiod=30):
        """指數移動平均線"""
        return ta.trend.ema_indicator(close, window=timeperiod)
    
    @staticmethod
    def RSI(close, timeperiod=14):
        """相對強弱指數"""
        return ta.momentum.rsi(close, window=timeperiod)
    
    @staticmethod
    def MACD(close, fastperiod=12, slowperiod=26, signalperiod=9):
        """MACD 指標"""
        macd = ta.trend.MACD(close, window_slow=slowperiod, window_fast=fastperiod, window_sign=signalperiod)
        return macd.macd(), macd.macd_signal(), macd.macd_diff()
    
    @staticmethod
    def BBANDS(close, timeperiod=20, nbdevup=2, nbdevdn=2, matype=0):
        """布林帶"""
        bb = ta.volatility.BollingerBands(close, window=timeperiod, window_dev=nbdevup)
        return bb.bollinger_hband(), bb.bollinger_lband(), bb.bollinger_mavg()
    
    @staticmethod
    def STOCH(high, low, close, fastk_period=5, slowk_period=3, slowd_period=3):
        """隨機指標"""
        stoch = ta.momentum.StochasticOscillator(high, low, close, window=fastk_period, smooth_window=slowk_period)
        return stoch.stoch(), stoch.stoch_signal()
    
    @staticmethod
    def ADX(high, low, close, timeperiod=14):
        """平均方向指數"""
        return ta.trend.adx(high, low, close, window=timeperiod)
    
    @staticmethod
    def ATR(high, low, close, timeperiod=14):
        """平均真實範圍"""
        return ta.volatility.average_true_range(high, low, close, window=timeperiod)
    
    @staticmethod
    def CCI(high, low, close, timeperiod=14):
        """商品通道指數"""
        return ta.trend.cci(high, low, close, window=timeperiod)
    
    @staticmethod
    def WILLR(high, low, close, timeperiod=14):
        """威廉指標"""
        return ta.momentum.williams_r(high, low, close, lbp=timeperiod)

# 創建一個模擬 talib 模組
class MockTalib:
    """模擬 talib 模組"""
    
    @staticmethod
    def SMA(close, timeperiod=30):
        return TalibCompatibility.SMA(close, timeperiod)
    
    @staticmethod
    def EMA(close, timeperiod=30):
        return TalibCompatibility.EMA(close, timeperiod)
    
    @staticmethod
    def RSI(close, timeperiod=14):
        return TalibCompatibility.RSI(close, timeperiod)
    
    @staticmethod
    def MACD(close, fastperiod=12, slowperiod=26, signalperiod=9):
        return TalibCompatibility.MACD(close, fastperiod, slowperiod, signalperiod)
    
    @staticmethod
    def BBANDS(close, timeperiod=20, nbdevup=2, nbdevdn=2, matype=0):
        return TalibCompatibility.BBANDS(close, timeperiod, nbdevup, nbdevdn, matype)
    
    @staticmethod
    def STOCH(high, low, close, fastk_period=5, slowk_period=3, slowd_period=3):
        return TalibCompatibility.STOCH(high, low, close, fastk_period, slowk_period, slowd_period)
    
    @staticmethod
    def ADX(high, low, close, timeperiod=14):
        return TalibCompatibility.ADX(high, low, close, timeperiod)
    
    @staticmethod
    def ATR(high, low, close, timeperiod=14):
        return TalibCompatibility.ATR(high, low, close, timeperiod)
    
    @staticmethod
    def CCI(high, low, close, timeperiod=14):
        return TalibCompatibility.CCI(high, low, close, timeperiod)
    
    @staticmethod
    def WILLR(high, low, close, timeperiod=14):
        return TalibCompatibility.WILLR(high, low, close, timeperiod)

# 嘗試導入真正的 talib，如果失敗則使用模擬版本
try:
    import talib
    print("成功導入真正的 talib")
except ImportError:
    print("無法導入 talib，使用兼容性模組")
    talib = MockTalib()

