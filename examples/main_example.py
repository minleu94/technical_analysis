"""
舊版主程式示例（已棄用）
此文件保留作為參考，新的主程式請使用 ui_app/main.py
"""
import os
import pandas as pd
from datetime import datetime, timedelta
import matplotlib.pyplot as plt
import yfinance as yf
plt.style.use('seaborn')

from system_config import *
from data_module import TWStockConfig, MarketDateRange, TWMarketDataProcessor
from analysis_module import (
    TechnicalAnalyzer,
    MLAnalyzer,
    MathAnalyzer,
    PatternAnalyzer,
    SignalCombiner
)
from backtest_module import StrategyTester, PerformanceAnalyzer
# from recommendation_module import RecommendationEngine
from recommendation_module_legacy import RecommendationEngine

def setup_directories():
    """創建必要的目錄"""
    for directory in [RAW_DATA_DIR, PROCESSED_DATA_DIR, RESULTS_DIR, REPORTS_DIR]:
        os.makedirs(directory, exist_ok=True)

def main():
    print("開始運行股票測試模型系統...")
    
    # 創建目錄
    setup_directories()
    
    # 初始化各模組
    config = TWStockConfig()
    date_range = MarketDateRange.last_year()  # 使用最近一年的數據
    data_processor = TWMarketDataProcessor(config=config, date_range=date_range)
    
    tech_analyzer = TechnicalAnalyzer()
    ml_analyzer = MLAnalyzer()
    math_analyzer = MathAnalyzer()
    pattern_analyzer = PatternAnalyzer()
    signal_combiner = SignalCombiner()
    strategy_tester = StrategyTester(
        initial_capital=BACKTEST_PARAMS['initial_capital']
    )
    
    # 加載數據
    print(f"正在加載 {DEFAULT_TICKER} 的數據...")
    # 使用yfinance下載數據
    df = yf.download(
        DEFAULT_TICKER,
        start=date_range.start_date,
        end=date_range.end_date
    )
    
    # 重設索引，將日期作為常規列
    df = df.reset_index()
    
    # 重命名列名稱為中文
    df = df.rename(columns={
        'Date': '日期',
        'Open': '開盤價',
        'High': '最高價',
        'Low': '最低價',
        'Close': '收盤價',
        'Volume': '成交量'
    })
    
    # 數據預處理和特徵工程
    print("正在進行數據預處理...")
    # 使用數據處理器進行基本清洗
    df_cleaned = data_processor.preprocess_stock_data(df, DEFAULT_TICKER)
    
    # 添加技術指標
    print("正在計算技術指標...")
    df_tech = tech_analyzer.add_momentum_indicators(df_cleaned)
    df_tech = tech_analyzer.add_volatility_indicators(df_tech)
    df_tech = tech_analyzer.add_trend_indicators(df_tech)
    
    # 識別圖形模式
    print("正在識別圖形模式...")
    patterns = {}
    for pattern_type in PATTERN_PARAMS.keys():
        patterns[pattern_type] = pattern_analyzer.identify_pattern(
            df_tech,
            pattern_type,
            **PATTERN_PARAMS[pattern_type]
        )
    
    # 分析組合信號
    print("正在分析組合信號...")
    df_signals = signal_combiner.analyze_combined_signals(
        df_tech,
        pattern_types=list(PATTERN_PARAMS.keys()),
        technical_indicators=['momentum', 'volatility', 'trend'],
        volume_conditions=['increasing', 'decreasing', 'spike']
    )
    
    # 回測組合策略
    print("正在進行策略回測...")
    backtest_results = signal_combiner.backtest_strategy(
        df_signals,
        SIGNAL_PARAMS
    )
    
    # 生成交易建議
    print("正在生成交易建議...")
    recommendation_engine = RecommendationEngine(
        technical_analyzer=tech_analyzer,
        ml_analyzer=ml_analyzer,
        math_analyzer=math_analyzer
    )
    recommendation = recommendation_engine.generate_recommendation(df_tech)
    
    # 保存結果
    print("正在保存結果...")
    results_file = os.path.join(RESULTS_DIR, f"{DEFAULT_TICKER}_results.csv")
    df_signals.to_csv(results_file, encoding=DEFAULT_ENCODING)
    
    # 生成報告
    print("正在生成分析報告...")
    report = recommendation_engine.generate_report(DEFAULT_TICKER, df_tech)
    report_file = os.path.join(REPORTS_DIR, f"{DEFAULT_TICKER}_report.txt")
    with open(report_file, 'w', encoding=DEFAULT_ENCODING) as f:
        f.write(report)
    
    # 視覺化結果
    print("正在生成視覺化圖表...")
    signal_combiner.visualize_signals(
        df_signals,
        ticker=DEFAULT_TICKER,
        save_path=os.path.join(RESULTS_DIR, f"{DEFAULT_TICKER}_signals.png")
    )
    
    print("處理完成！")
    print(f"結果已保存到：{RESULTS_DIR}")
    print(f"報告已保存到：{REPORTS_DIR}")

if __name__ == "__main__":
    main()

