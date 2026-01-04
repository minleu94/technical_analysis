import os
import pandas as pd
import matplotlib.pyplot as plt
from data_module.data_loader import DataLoader
from data_module.data_processor import DataProcessor
from analysis_module.math_analyzer import MathAnalyzer

def test_math_analyzer():
    """測試數學分析器的功能"""
    # 初始化數據加載器和處理器
    data_loader = DataLoader()
    data_processor = DataProcessor()
    math_analyzer = MathAnalyzer()
    
    # 設定股票代碼和數據路徑
    ticker = '2330'  # 台積電
    data_path = r"D:\Min\Python\Project\FA_Data\technical_analysis"
    file_path = os.path.join(data_path, f"{ticker}_indicators.csv")
    
    # 設定測試數據保存路徑
    test_data_path = r"D:\Min\Python\Project\FA_Data\test_data"
    if not os.path.exists(test_data_path):
        os.makedirs(test_data_path)
    
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
    
    # 數據預處理
    print("\n正在進行數據預處理...")
    df_cleaned = data_processor.clean_data(df)
    
    # 測試平穩性檢驗
    print("\n正在測試平穩性檢驗...")
    try:
        if '收盤價' in df_cleaned.columns:
            stationarity = math_analyzer.check_stationarity(df_cleaned['收盤價'])
            print(f"價格序列平穩性檢驗結果:")
            for key, value in stationarity.items():
                print(f"- {key}: {value}")
            
            # 繪製原始序列和差分序列
            plt.figure(figsize=(12, 8))
            
            # 原始序列
            plt.subplot(2, 1, 1)
            plt.plot(df_cleaned.index, df_cleaned['收盤價'])
            plt.title('原始價格序列')
            plt.grid(True)
            
            # 差分序列
            plt.subplot(2, 1, 2)
            diff = df_cleaned['收盤價'].diff().dropna()
            plt.plot(df_cleaned.index[1:], diff)
            plt.title('價格序列一階差分')
            plt.grid(True)
            
            plt.tight_layout()
            plt.show()
        else:
            print("錯誤: 找不到 '收盤價' 列")
    except Exception as e:
        print(f"平穩性檢驗時出錯: {str(e)}")
        import traceback
        traceback.print_exc()
    
    # 測試自相關和偏自相關
    print("\n正在測試自相關和偏自相關...")
    try:
        if '收盤價' in df_cleaned.columns:
            # 計算自相關
            acf_values = math_analyzer.calculate_acf(df_cleaned['收盤價'], nlags=20)
            print(f"自相關係數 (前5個):")
            for i, value in enumerate(acf_values[:5], 0):
                print(f"- Lag {i}: {value:.4f}")
            
            # 計算偏自相關
            pacf_values = math_analyzer.calculate_pacf(df_cleaned['收盤價'], nlags=20)
            print(f"偏自相關係數 (前5個):")
            for i, value in enumerate(pacf_values[:5], 0):
                print(f"- Lag {i}: {value:.4f}")
            
            # 繪製自相關和偏自相關圖
            plt.figure(figsize=(12, 8))
            
            # 自相關圖
            plt.subplot(2, 1, 1)
            plt.bar(range(len(acf_values)), acf_values)
            plt.axhline(y=0, linestyle='-', color='black')
            plt.axhline(y=1.96/np.sqrt(len(df_cleaned)), linestyle='--', color='gray')
            plt.axhline(y=-1.96/np.sqrt(len(df_cleaned)), linestyle='--', color='gray')
            plt.title('自相關函數 (ACF)')
            plt.xlabel('Lag')
            plt.ylabel('相關係數')
            plt.grid(True)
            
            # 偏自相關圖
            plt.subplot(2, 1, 2)
            plt.bar(range(len(pacf_values)), pacf_values)
            plt.axhline(y=0, linestyle='-', color='black')
            plt.axhline(y=1.96/np.sqrt(len(df_cleaned)), linestyle='--', color='gray')
            plt.axhline(y=-1.96/np.sqrt(len(df_cleaned)), linestyle='--', color='gray')
            plt.title('偏自相關函數 (PACF)')
            plt.xlabel('Lag')
            plt.ylabel('相關係數')
            plt.grid(True)
            
            plt.tight_layout()
            plt.show()
        else:
            print("錯誤: 找不到 '收盤價' 列")
    except Exception as e:
        print(f"自相關和偏自相關計算時出錯: {str(e)}")
        import traceback
        traceback.print_exc()
    
    # 測試ARIMA模型
    print("\n正在測試ARIMA模型...")
    try:
        if '收盤價' in df_cleaned.columns:
            # 擬合ARIMA模型
            arima_model = math_analyzer.fit_arima(df_cleaned['收盤價'], order=(5,1,0))
            print(f"ARIMA模型摘要:")
            print(arima_model.summary())
            
            # 預測未來5天
            forecast = math_analyzer.forecast_arima(steps=5)
            print(f"未來5天預測值:")
            for i, value in enumerate(forecast, 1):
                print(f"- 第{i}天: {value:.4f}")
            
            # 繪製原始數據和預測結果
            plt.figure(figsize=(12, 6))
            plt.plot(df_cleaned.index, df_cleaned['收盤價'], label='歷史數據')
            
            # 計算預測的日期範圍
            last_date = df_cleaned.index[-1]
            if isinstance(last_date, str):
                # 如果索引是字符串，嘗試轉換為日期
                try:
                    last_date = pd.to_datetime(last_date)
                except:
                    # 如果無法轉換，使用數字索引
                    last_date = len(df_cleaned)
                    forecast_index = range(last_date + 1, last_date + 6)
            elif isinstance(last_date, (int, float)):
                # 如果索引是數字，直接使用
                forecast_index = range(last_date + 1, last_date + 6)
            else:
                # 其他情況，使用數字索引
                forecast_index = range(len(df_cleaned), len(df_cleaned) + 5)
            
            plt.plot(forecast_index, forecast, 'r--', label='預測值')
            plt.title(f'{ticker} ARIMA模型預測')
            plt.xlabel('時間')
            plt.ylabel('價格')
            plt.legend()
            plt.grid(True)
            plt.show()
        else:
            print("錯誤: 找不到 '收盤價' 列")
    except Exception as e:
        print(f"ARIMA模型擬合時出錯: {str(e)}")
        import traceback
        traceback.print_exc()
    
    # 保存處理後的數據
    save_processed = input("\n是否保存處理後的數據? (y/n): ").lower() == 'y'
    if save_processed:
        output_path = os.path.join(test_data_path, f"{ticker}_math.csv")
        df_cleaned.to_csv(output_path, encoding='utf-8-sig', index=False)
        print(f"處理後的數據已保存至 {output_path}")

if __name__ == "__main__":
    import numpy as np  # 添加這一行，因為我們在腳本中使用了np
    test_math_analyzer() 