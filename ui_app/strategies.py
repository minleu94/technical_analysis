"""
交易策略定義模組
包含各種可用的交易策略函數
"""

import pandas as pd
import numpy as np

def _get_column_name(df, eng_name):
    """獲取對應的列名，支援中英文列名映射"""
    column_mapping = {
        '收盤價': 'Close',
        '開盤價': 'Open',
        '最高價': 'High',
        '最低價': 'Low',
        '成交量': 'Volume',
        '成交股數': 'Volume'
    }
    reverse_mapping = {v: k for k, v in column_mapping.items()}
    
    # 檢查中文列名
    if reverse_mapping.get(eng_name) in df.columns:
        return reverse_mapping.get(eng_name)
    # 檢查英文列名
    elif eng_name in df.columns:
        return eng_name
    return None

def ma_strategy(df, short_window=20, long_window=60):
    """移動平均線交叉策略
    
    Args:
        df: 股票數據DataFrame
        short_window: 短期均線週期，預設20
        long_window: 長期均線週期，預設60
        
    Returns:
        signals: 交易信號Series (1=買入, 0=賣出/空倉)
    """
    close_col = _get_column_name(df, 'Close')
    if close_col is None:
        return pd.Series(0, index=df.index)
    
    # 計算移動平均線
    ma_short = df[close_col].rolling(window=short_window).mean()
    ma_long = df[close_col].rolling(window=long_window).mean()
    
    # 生成信號
    signals = pd.Series(0, index=df.index)
    signals[ma_short > ma_long] = 1  # 短期均線在長期均線上方，做多
    signals[ma_short <= ma_long] = 0  # 短期均線在長期均線下方，空倉
    
    return signals

def rsi_strategy(df, rsi_period=14, oversold=30, overbought=70):
    """RSI 策略
    
    Args:
        df: 股票數據DataFrame
        rsi_period: RSI 週期，預設14
        oversold: 超賣閾值，預設30
        overbought: 超買閾值，預設70
        
    Returns:
        signals: 交易信號Series (1=買入, 0=賣出/空倉)
    """
    close_col = _get_column_name(df, 'Close')
    if close_col is None:
        return pd.Series(0, index=df.index)
    
    # 檢查是否有 RSI 列
    rsi_col = _get_column_name(df, 'RSI')
    if rsi_col and rsi_col in df.columns:
        rsi = df[rsi_col]
    else:
        # 計算 RSI
        delta = df[close_col].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=rsi_period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=rsi_period).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
    
    # 生成信號
    signals = pd.Series(0, index=df.index)
    signals[rsi < oversold] = 1  # RSI 低於超賣線，買入
    signals[rsi > overbought] = 0  # RSI 高於超買線，賣出
    
    return signals

def macd_strategy(df, fast=12, slow=26, signal=9):
    """MACD 策略
    
    Args:
        df: 股票數據DataFrame
        fast: 快速EMA週期，預設12
        slow: 慢速EMA週期，預設26
        signal: 信號線週期，預設9
        
    Returns:
        signals: 交易信號Series (1=買入, 0=賣出/空倉)
    """
    close_col = _get_column_name(df, 'Close')
    if close_col is None:
        return pd.Series(0, index=df.index)
    
    # 檢查是否有 MACD 相關列
    macd_col = _get_column_name(df, 'MACD')
    signal_col = _get_column_name(df, 'MACD_Signal')
    
    if macd_col and signal_col and macd_col in df.columns and signal_col in df.columns:
        macd = df[macd_col]
        macd_signal = df[signal_col]
    else:
        # 計算 MACD
        ema_fast = df[close_col].ewm(span=fast, adjust=False).mean()
        ema_slow = df[close_col].ewm(span=slow, adjust=False).mean()
        macd = ema_fast - ema_slow
        macd_signal = macd.ewm(span=signal, adjust=False).mean()
    
    # 生成信號
    signals = pd.Series(0, index=df.index)
    signals[macd > macd_signal] = 1  # MACD 在信號線上方，買入
    signals[macd <= macd_signal] = 0  # MACD 在信號線下方，賣出
    
    return signals

def bb_strategy(df, window=20, num_std=2):
    """布林通道策略
    
    Args:
        df: 股票數據DataFrame
        window: 移動平均週期，預設20
        num_std: 標準差倍數，預設2
        
    Returns:
        signals: 交易信號Series (1=買入, 0=賣出/空倉)
    """
    close_col = _get_column_name(df, 'Close')
    if close_col is None:
        return pd.Series(0, index=df.index)
    
    # 檢查是否有布林通道列
    bb_upper_col = _get_column_name(df, 'BB_Upper')
    bb_lower_col = _get_column_name(df, 'BB_Lower')
    
    if bb_upper_col and bb_lower_col and bb_upper_col in df.columns and bb_lower_col in df.columns:
        bb_upper = df[bb_upper_col]
        bb_lower = df[bb_lower_col]
    else:
        # 計算布林通道
        ma = df[close_col].rolling(window=window).mean()
        std = df[close_col].rolling(window=window).std()
        bb_upper = ma + (std * num_std)
        bb_lower = ma - (std * num_std)
    
    # 生成信號
    signals = pd.Series(0, index=df.index)
    signals[df[close_col] < bb_lower] = 1  # 價格觸及下軌，買入
    signals[df[close_col] > bb_upper] = 0  # 價格觸及上軌，賣出
    
    return signals

# 策略字典，用於 UI 選擇
STRATEGIES = {
    "移動平均線策略": {
        "func": ma_strategy,
        "params": {
            "short_window": {"label": "短期均線週期", "type": "int", "default": 20, "min": 5, "max": 100},
            "long_window": {"label": "長期均線週期", "type": "int", "default": 60, "min": 20, "max": 200}
        }
    },
    "RSI 策略": {
        "func": rsi_strategy,
        "params": {
            "rsi_period": {"label": "RSI 週期", "type": "int", "default": 14, "min": 5, "max": 50},
            "oversold": {"label": "超賣閾值", "type": "float", "default": 30, "min": 0, "max": 50},
            "overbought": {"label": "超買閾值", "type": "float", "default": 70, "min": 50, "max": 100}
        }
    },
    "MACD 策略": {
        "func": macd_strategy,
        "params": {
            "fast": {"label": "快速EMA週期", "type": "int", "default": 12, "min": 5, "max": 50},
            "slow": {"label": "慢速EMA週期", "type": "int", "default": 26, "min": 10, "max": 100},
            "signal": {"label": "信號線週期", "type": "int", "default": 9, "min": 5, "max": 30}
        }
    },
    "布林通道策略": {
        "func": bb_strategy,
        "params": {
            "window": {"label": "移動平均週期", "type": "int", "default": 20, "min": 5, "max": 100},
            "num_std": {"label": "標準差倍數", "type": "float", "default": 2, "min": 1, "max": 5}
        }
    }
}

