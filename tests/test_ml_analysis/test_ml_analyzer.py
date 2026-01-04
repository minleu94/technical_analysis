import os
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from data_module import DataLoader, DataProcessor
from analysis_module.ml_analysis import MLAnalyzer

def set_chinese_font():
    """設定中文字體"""
    try:
        plt.rcParams['font.sans-serif'] = ['Microsoft JhengHei', 'SimHei', 'Arial Unicode MS']
        plt.rcParams['axes.unicode_minus'] = False
        print("已設定中文字體")
    except:
        print("設定中文字體失敗，將使用默認字體")

def test_ml_analyzer():
    """測試機器學習分析器的功能"""
    # 設定中文字體
    set_chinese_font()
    
    # 初始化數據加載器和處理器
    data_loader = DataLoader()
    data_processor = DataProcessor()
    ml_analyzer = MLAnalyzer()
    
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
    
    # 分割訓練集和測試集
    print("正在分割訓練集和測試集...")
    train_data, test_data = data_processor.split_train_test(df_features, test_size=0.2)
    print(f"訓練集大小: {len(train_data)}, 測試集大小: {len(test_data)}")
    
    # 準備特徵和目標
    print("正在準備特徵和目標...")
    target_col = data_processor._get_column_name(train_data, 'Close')
    if target_col is None:
        print("錯誤: 找不到收盤價列")
        return
    
    try:
        X, y_reg, y_cls = ml_analyzer.prepare_features_targets(
            train_data,
            target_col=target_col,
            prediction_horizon=5
        )
        print(f"特徵矩陣形狀: {X.shape}")
        print(f"回歸目標形狀: {y_reg.shape}")
        print(f"分類目標形狀: {y_cls.shape}")
    except Exception as e:
        print(f"準備特徵和目標時出錯: {str(e)}")
        return
    
    # 訓練模型
    print("\n正在訓練模型...")
    try:
        # 訓練分類器
        print("訓練隨機森林分類器...")
        ml_analyzer.train_classifier(
            X, y_cls,
            model_type='random_forest',
            n_estimators=100,
            random_state=42
        )
        
        # 訓練回歸器
        print("訓練梯度提升回歸器...")
        ml_analyzer.train_regressor(
            X, y_reg,
            model_type='gradient_boosting',
            n_estimators=100,
            random_state=42
        )
    except Exception as e:
        print(f"訓練模型時出錯: {str(e)}")
        return
    
    # 評估模型
    print("\n正在評估模型...")
    try:
        # 準備測試數據
        X_test, y_reg_test, y_cls_test = ml_analyzer.prepare_features_targets(
            test_data,
            target_col=target_col,
            prediction_horizon=5
        )
        
        # 評估分類器
        cls_accuracy = ml_analyzer.evaluate_classifier(
            X_test, y_cls_test,
            'random_forest_classifier'
        )
        print(f"分類器準確率: {cls_accuracy:.4f}")
        
        # 評估回歸器
        reg_mse = ml_analyzer.evaluate_regressor(
            X_test, y_reg_test,
            'gradient_boosting_regressor'
        )
        print(f"回歸器均方誤差: {reg_mse:.4f}")
    except Exception as e:
        print(f"評估模型時出錯: {str(e)}")
        return
    
    # 進行預測
    print("\n正在進行預測...")
    try:
        # 獲取最新的特徵
        latest_features = ml_analyzer.prepare_features_targets(
            df_features.iloc[-100:],
            target_col=target_col,
            prediction_horizon=5
        )[0]
        
        # 進行分類預測
        cls_predictions = ml_analyzer.predict_class(
            latest_features,
            'random_forest_classifier'
        )
        print(f"分類預測結果: {cls_predictions}")
        
        # 進行回歸預測
        reg_predictions = ml_analyzer.predict_regression(
            latest_features,
            'gradient_boosting_regressor'
        )
        print(f"回歸預測結果: {reg_predictions}")
        
        # 繪製預測結果
        plt.figure(figsize=(12, 6))
        plt.plot(df_features.index[-100:], df_features[target_col].iloc[-100:], label='實際價格')
        plt.plot(df_features.index[-95:], reg_predictions, label='預測價格', linestyle='--')
        plt.title(f'{ticker} - 價格預測')
        plt.legend()
        plt.grid(True)
        
        # 保存圖表
        chart_path = os.path.join(stock_dir, f"{ticker}_ml_predictions.png")
        plt.savefig(chart_path)
        print(f"預測圖表已保存至 {chart_path}")
        
    except Exception as e:
        print(f"進行預測時出錯: {str(e)}")
        return
    
    print("\n機器學習分析器測試完成！")

if __name__ == "__main__":
    test_ml_analyzer() 