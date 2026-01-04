import os
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
from data_module.data_loader import DataLoader
from data_module.data_processor import DataProcessor
from analysis_module.technical_analyzer import TechnicalAnalyzer
from analysis_module.pattern_analyzer import PatternAnalyzer
from analysis_module.signal_combiner import SignalCombiner

def set_chinese_font():
    """設定中文字體"""
    # 嘗試設定微軟正黑體（適用於Windows）
    try:
        plt.rcParams['font.sans-serif'] = ['Microsoft JhengHei', 'SimHei', 'Arial Unicode MS']
        plt.rcParams['axes.unicode_minus'] = False  # 解決負號顯示問題
        print("已設定中文字體")
    except:
        print("設定中文字體失敗，將使用默認字體")

def test_signal_combiner():
    """測試信號組合分析器的功能"""
    # 設定中文字體
    set_chinese_font()
    
    # 初始化數據加載器和處理器
    data_loader = DataLoader()
    data_processor = DataProcessor()
    signal_combiner = SignalCombiner()
    
    # 設定股票代碼和數據路徑
    ticker = '2330'  # 台積電
    data_path = r"D:\Min\Python\Project\FA_Data\technical_analysis"
    file_path = os.path.join(data_path, f"{ticker}_indicators.csv")
    
    # 設定測試數據保存路徑
    test_data_path = r"D:\Min\Python\Project\FA_Data\test_data"
    stock_dir = os.path.join(test_data_path, ticker)
    os.makedirs(stock_dir, exist_ok=True)
    
    # 檢查文件是否存在
    if not os.path.exists(file_path):
        print(f"錯誤: 找不到文件 {file_path}")
        return
    
    # 加載數據
    print(f"正在加載 {ticker} 的歷史數據...")
    try:
        df = data_loader.load_from_csv(file_path)
        print(f"成功加載數據，共 {len(df)} 筆記錄")
        print(f"數據範圍: {df.index[0]} 到 {df.index[-1]}")
        
        # 顯示欄位數量和名稱
        print(f"數據欄位數量: {len(df.columns)}")
        print("數據欄位:")
        for i, col in enumerate(df.columns, 1):
            print(f"{i}. {col}")
    except Exception as e:
        print(f"加載數據時出錯: {str(e)}")
        return
    
    # 處理日期列
    print("\n正在處理日期列...")
    try:
        # 檢查是否有日期列
        if '日期' in df.columns:
            # 將日期列轉換為日期類型
            df['日期'] = pd.to_datetime(df['日期'], format='%Y%m%d', errors='coerce')
            # 將日期列設為索引
            df = df.set_index('日期')
            print("已將日期列設為索引")
        else:
            print("警告: 找不到日期列，將使用默認索引")
    except Exception as e:
        print(f"處理日期列時出錯: {str(e)}")
    
    # 數據預處理
    print("\n正在進行數據預處理...")
    df_cleaned = data_processor.clean_data(df)
    df_features = data_processor.add_basic_features(df_cleaned)
    
    # 分析組合信號
    print("\n正在分析組合信號...")
    pattern_types = ['W底', '頭肩頂', '頭肩底']
    technical_indicators = ['momentum', 'volatility', 'trend']
    volume_conditions = ['increasing', 'decreasing', 'spike']
    
    df_signals = signal_combiner.analyze_combined_signals(
        df_features, 
        pattern_types=pattern_types,
        technical_indicators=technical_indicators,
        volume_conditions=volume_conditions
    )
    
    # 顯示信號統計
    print("\n信號統計:")
    print(f"總記錄數: {len(df_signals)}")
    print(f"看漲信號數: {len(df_signals[df_signals['Combined_Signal'] > 0])}")
    print(f"看跌信號數: {len(df_signals[df_signals['Combined_Signal'] < 0])}")
    print(f"強看漲信號數 (>=2): {len(df_signals[df_signals['Combined_Signal'] >= 2])}")
    print(f"強看跌信號數 (<=-2): {len(df_signals[df_signals['Combined_Signal'] <= -2])}")
    
    # 回測策略
    print("\n正在回測策略...")
    strategy_params = {
        'buy_threshold': 1,  # 買入信號閾值，降低為1（弱看漲信號）
        'sell_threshold': -1,  # 賣出信號閾值，提高為-1（弱看跌信號）
        'reliability_threshold': 0.5,  # 可靠性閾值，降低為0.5
        'use_stop_loss': True,  # 是否使用止損
        'stop_loss_pct': 0.05  # 止損百分比
    }
    
    backtest_results = signal_combiner.backtest_strategy(df_signals, strategy_params)
    
    if backtest_results:
        print("\n回測結果:")
        print(f"初始資金: {backtest_results['initial_capital']}")
        print(f"最終價值: {backtest_results['final_value']:.2f}")
        print(f"總回報率: {backtest_results['total_return']:.2%}")
        print(f"勝率: {backtest_results['win_rate']:.2%}")
        print(f"交易次數: {len(backtest_results['trades'])}")
    
    # 視覺化信號
    print("\n正在視覺化信號...")
    save_path = os.path.join(stock_dir, f"{ticker}_signals.png")
    signal_combiner.visualize_signals(df_signals, ticker=ticker, save_path=save_path)
    print(f"信號圖表已保存至: {save_path}")
    
    # 保存結果
    print("\n正在保存結果...")
    result_path = os.path.join(stock_dir, f"{ticker}_signals.csv")
    df_signals.to_csv(result_path, encoding='utf-8-sig')
    print(f"信號數據已保存至: {result_path}")
    
    print("\n測試完成!")

if __name__ == "__main__":
    test_signal_combiner() 