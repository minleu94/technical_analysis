"""
舊版系統配置（已棄用）
此文件保留作為參考，新的配置系統請使用 data_module/config.py
"""
import os

# 基本路徑配置
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')
RAW_DATA_DIR = os.path.join(DATA_DIR, 'raw')
PROCESSED_DATA_DIR = os.path.join(DATA_DIR, 'processed')
OUTPUT_DIR = os.path.join(BASE_DIR, 'output')
RESULTS_DIR = os.path.join(OUTPUT_DIR, 'results')
REPORTS_DIR = os.path.join(OUTPUT_DIR, 'reports')
TEST_DATA_DIR = os.path.join(BASE_DIR, 'test_data')

# 數據配置
DEFAULT_ENCODING = 'utf-8-sig'
DATE_FORMAT = '%Y-%m-%d'
DEFAULT_TICKER = '2330.TW'  # 台積電

# 技術分析參數
TECHNICAL_PARAMS = {
    'short_window': 5,
    'middle_window': 10,
    'long_window': 20,
    'rsi_period': 14,
    'macd_fast': 12,
    'macd_slow': 26,
    'macd_signal': 9,
    'bollinger_window': 20,
    'bollinger_std': 2
}

# 圖形模式參數
PATTERN_PARAMS = {
    'W底': {
        'window': 10,
        'threshold': 0.03,
        'prominence': 0.5
    },
    '頭肩頂': {
        'window': 20,
        'threshold': 0.08
    },
    '三角形': {
        'window': 20,
        'threshold': 0.08,
        'min_r_squared': 0.4,
        'min_height_ratio': 0.02
    }
}

# 回測參數
BACKTEST_PARAMS = {
    'initial_capital': 1000000,
    'commission': 0.001425,  # 手續費率
    'tax_rate': 0.003,      # 證券交易稅率
    'min_holding_days': 1,
    'max_holding_days': 60
}

# 機器學習參數
ML_PARAMS = {
    'test_size': 0.2,
    'random_state': 42,
    'cv_folds': 5
}

# 數學模型參數
MATH_PARAMS = {
    'arima_order': (1, 1, 1),
    'volatility_window': 20,
    'risk_free_rate': 0.02
}

# 推薦系統參數
RECOMMENDATION_PARAMS = {
    'technical_weight': 0.4,
    'ml_weight': 0.3,
    'math_weight': 0.3,
    'signal_threshold': 0.7
}

# 信號組合參數
SIGNAL_PARAMS = {
    'buy_threshold': 1,
    'sell_threshold': -1,
    'reliability_threshold': 0.5,
    'use_stop_loss': True,
    'stop_loss_pct': 0.05
}

# 圖表樣式配置
PLOT_STYLE = {
    'figsize': (15, 8),
    'style': 'seaborn',
    'grid': True,
    'title_fontsize': 14,
    'label_fontsize': 12,
    'tick_fontsize': 10
}

# 中英文列名映射
COLUMN_MAPPING = {
    'date': '日期',
    'open': '開盤價',
    'high': '最高價',
    'low': '最低價',
    'close': '收盤價',
    'volume': '成交量',
    'change': '漲跌幅',
    'ma5': '5日均線',
    'ma10': '10日均線',
    'ma20': '20日均線',
    'rsi': 'RSI指標',
    'macd': 'MACD',
    'signal': '信號線',
    'histogram': '柱狀圖'
}

