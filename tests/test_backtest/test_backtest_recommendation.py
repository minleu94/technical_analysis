import os
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
from datetime import datetime, timedelta

from data_module import DataLoader, DataProcessor
from analysis_module.technical_analysis import TechnicalAnalyzer
from analysis_module.ml_analysis import MLAnalyzer
from analysis_module.technical_analysis import MathAnalyzer
from backtest_module import StrategyTester, PerformanceAnalyzer
# from recommendation_module import RecommendationEngine
from recommendation_module_legacy import RecommendationEngine

def set_chinese_font():
    """設定中文字體"""
    # 嘗試設定微軟正黑體（適用於Windows）
    try:
        plt.rcParams['font.sans-serif'] = ['Microsoft JhengHei', 'SimHei', 'Arial Unicode MS']
        plt.rcParams['axes.unicode_minus'] = False  # 解決負號顯示問題
        print("已設定中文字體")
    except:
        print("設定中文字體失敗，將使用默認字體")

def test_backtest_module():
    """測試回測模組的功能"""
    print("\n===== 測試回測模組 =====")
    
    # 初始化數據加載器和處理器
    data_loader = DataLoader()
    data_processor = DataProcessor()
    tech_analyzer = TechnicalAnalyzer()
    strategy_tester = StrategyTester(initial_capital=100000.0)
    
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
    except Exception as e:
        print(f"加載數據時出錯: {str(e)}")
        return
    
    # 數據預處理
    print("正在進行數據預處理...")
    df_cleaned = data_processor.clean_data(df)
    df_features = data_processor.add_basic_features(df_cleaned)
    
    # 添加技術指標
    print("正在計算技術指標...")
    df_tech = tech_analyzer.add_momentum_indicators(df_features)
    df_tech = tech_analyzer.add_volatility_indicators(df_tech)
    df_tech = tech_analyzer.add_trend_indicators(df_tech)
    
    # 定義一個簡單的交易策略函數
    def simple_ma_strategy(df, short_window=20, long_window=60):
        """簡單移動平均線交叉策略"""
        signals = pd.Series(0, index=df.index)
        
        # 獲取列名
        close_col = data_processor._get_column_name(df, 'Close')
        ma20_col = data_processor._get_column_name(df, 'MA20')
        ma60_col = data_processor._get_column_name(df, 'MA60')
        sma30_col = data_processor._get_column_name(df, 'SMA30')
        
        # 檢查是否有 MA20 和 MA60 列
        if ma20_col and ma60_col and ma20_col in df.columns and ma60_col in df.columns:
            signals[df[ma20_col] > df[ma60_col]] = 1  # 短期均線在長期均線上方，做多
            signals[df[ma20_col] < df[ma60_col]] = 0  # 短期均線在長期均線下方，空倉
        # 如果沒有 MA20 和 MA60，但有 SMA30，使用 SMA30 與收盤價比較
        elif sma30_col and close_col and sma30_col in df.columns and close_col in df.columns:
            signals[df[sma30_col] > df[close_col]] = 1  # SMA30 在收盤價上方，做多
            signals[df[sma30_col] < df[close_col]] = 0  # SMA30 在收盤價下方，空倉
        
        return signals
    
    # 回測策略
    print("正在進行策略回測...")
    try:
        backtest_results = strategy_tester.run_backtest(df_tech, simple_ma_strategy)
        
        # 計算績效指標
        portfolio_returns = strategy_tester.portfolio_value['Total_Value'].pct_change().dropna()
        
        # 獲取收盤價列名
        close_col = data_processor._get_column_name(df_tech, 'Close')
        if close_col is None:
            print("錯誤: 找不到收盤價列，請確保數據中包含'Close'或'收盤價'列")
            return
            
        benchmark_returns = df_tech[close_col].pct_change().dropna()
        
        performance_analyzer = PerformanceAnalyzer(portfolio_returns, benchmark_returns)
        performance_report = performance_analyzer.generate_performance_report()
        
        print("\n===== 策略績效報告 =====")
        for key, value in performance_report.items():
            print(f"{key}: {value:.4f}")
        
        # 繪製回測結果並保存
        plt.figure(figsize=(12, 8))
        strategy_tester.plot_results()
        plt.tight_layout()
        plt.savefig(os.path.join(stock_dir, f"{ticker}_backtest_result_complete.png"))
        
        # 繪製績效分析圖表並保存
        plt.figure(figsize=(12, 10))
        performance_analyzer.plot_performance()
        plt.tight_layout()
        plt.savefig(os.path.join(stock_dir, f"{ticker}_performance_analysis.png"))
        
        print(f"完整回測結果圖表已保存至 {os.path.join(stock_dir, f'{ticker}_backtest_result_complete.png')}")
        print(f"績效分析圖表已保存至 {os.path.join(stock_dir, f'{ticker}_performance_analysis.png')}")
        print("回測模組測試成功！")
        
    except Exception as e:
        print(f"策略回測時出錯: {str(e)}")

def test_recommendation_module():
    """測試推薦模組的功能"""
    print("\n===== 測試推薦模組 =====")
    
    # 初始化數據加載器和處理器
    data_loader = DataLoader()
    data_processor = DataProcessor()
    tech_analyzer = TechnicalAnalyzer()
    ml_analyzer = MLAnalyzer()
    math_analyzer = MathAnalyzer()
    
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
    except Exception as e:
        print(f"加載數據時出錯: {str(e)}")
        return
    
    # 數據預處理
    print("正在進行數據預處理...")
    df_cleaned = data_processor.clean_data(df)
    df_features = data_processor.add_basic_features(df_cleaned)
    
    # 添加技術指標
    print("正在計算技術指標...")
    df_tech = tech_analyzer.add_momentum_indicators(df_features)
    df_tech = tech_analyzer.add_volatility_indicators(df_tech)
    df_tech = tech_analyzer.add_trend_indicators(df_tech)
    
    # 分割訓練集和測試集
    train_data, test_data = data_processor.split_train_test(df_tech, test_size=0.2)
    print(f"訓練集大小: {len(train_data)}, 測試集大小: {len(test_data)}")
    
    # 準備機器學習特徵和目標
    print("正在訓練機器學習模型...")
    try:
        # 獲取目標列名
        target_col = data_processor._get_column_name(train_data, 'Close')
        if target_col is None:
            print("錯誤: 找不到收盤價列，請確保數據中包含'Close'或'收盤價'列")
            return
        
        X, y_reg, y_cls = ml_analyzer.prepare_features_targets(
            train_data, 
            target_col=target_col,
            prediction_horizon=5
        )
        
        # 訓練機器學習模型
        ml_analyzer.train_classifier(X, y_cls, model_type='random_forest', n_estimators=100, random_state=42)
        ml_analyzer.train_regressor(X, y_reg, model_type='gradient_boosting', n_estimators=100, random_state=42)
        
        # 評估模型
        X_test, y_reg_test, y_cls_test = ml_analyzer.prepare_features_targets(
            test_data, 
            target_col=target_col,
            prediction_horizon=5
        )
        
        cls_accuracy = ml_analyzer.evaluate_classifier(X_test, y_cls_test, 'random_forest_classifier')
        reg_mse = ml_analyzer.evaluate_regressor(X_test, y_reg_test, 'gradient_boosting_regressor')
        
        print(f"分類模型準確率: {cls_accuracy:.4f}")
        print(f"回歸模型均方誤差: {reg_mse:.4f}")
    except Exception as e:
        print(f"機器學習模型訓練時出錯: {str(e)}")
        return
    
    # 數學模型分析
    print("正在進行時間序列分析...")
    try:
        # 獲取目標列名
        price_col = data_processor._get_column_name(df_tech, 'Close')
        if price_col is None:
            print("錯誤: 找不到收盤價列，請確保數據中包含'Close'或'收盤價'列")
            return
        
        stationarity = math_analyzer.check_stationarity(df_tech[price_col])
        print(f"價格序列平穩性檢驗: {'平穩' if stationarity['是否平穩'] else '非平穩'}")
        
        # 擬合ARIMA模型
        arima_model = math_analyzer.fit_arima(df_tech[price_col], order=(5,1,0))
        forecast = math_analyzer.forecast_arima(steps=5)
        print(f"ARIMA模型5日預測: {forecast.tolist()}")
    except Exception as e:
        print(f"時間序列分析時出錯: {str(e)}")
        return
    
    # 生成交易建議
    print("\n正在生成交易建議...")
    try:
        recommendation_engine = RecommendationEngine(
            technical_analyzer=tech_analyzer,
            ml_analyzer=ml_analyzer,
            math_analyzer=math_analyzer
        )
        
        recommendation = recommendation_engine.generate_recommendation(df_tech)
        latest_recommendation = recommendation_engine.get_latest_recommendation(df_tech, days=5)
        
        print("\n===== 最近5日交易建議 =====")
        for date, row in latest_recommendation.iterrows():
            print(f"{date.strftime('%Y-%m-%d')}: {row['Recommendation_Text']} (技術: {row['Technical_Signal']:.2f}, ML: {row['ML_Signal']:.2f}, 數學: {row['Math_Signal']:.2f})")
        
        # 生成詳細分析報告
        report = recommendation_engine.generate_report(ticker, df_tech)
        print(report)
        
        # 保存推薦報告
        report_path = os.path.join(stock_dir, f"{ticker}_recommendation_report.txt")
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(report)
        print(f"推薦報告已保存至: {report_path}")
        
        # 繪製推薦信號圖表
        plt.figure(figsize=(12, 6))
        plt.plot(df_tech.index[-100:], df_tech[price_col].iloc[-100:], label='收盤價')
        plt.plot(df_tech.index[-100:], df_tech['SMA30'].iloc[-100:], label='30日均線')
        plt.title(f'{ticker} - 推薦信號')
        plt.legend()
        plt.grid(True)
        plt.savefig(os.path.join(stock_dir, f"{ticker}_recommendation_signals.png"))
        print(f"推薦信號圖表已保存至: {os.path.join(stock_dir, f'{ticker}_recommendation_signals.png')}")
        
        print("推薦模組測試成功！")
        
    except Exception as e:
        print(f"生成交易建議時出錯: {str(e)}")

def main():
    # 設定中文字體
    set_chinese_font()
    
    # 測試回測模組
    test_backtest_module()
    
    # 測試推薦模組
    test_recommendation_module()
    
    print("\n所有測試完成！")

if __name__ == "__main__":
    main() 