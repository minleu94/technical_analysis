import os
import pandas as pd
import matplotlib.pyplot as plt
from data_module import DataLoader, DataProcessor

def test_data_loading():
    # 初始化數據加載器
    data_loader = DataLoader()
    data_processor = DataProcessor()
    
    # 設定股票代碼和數據路徑
    ticker = '2330'  # 台積電
    data_path = r"D:\Min\Python\Project\FA_Data\technical_analysis"
    file_path = os.path.join(data_path, f"{ticker}_indicators.csv")  # 修改為正確的文件名
    
    # 設定測試數據保存路徑
    test_data_path = r"D:\Min\Python\Project\FA_Data\test_data"
    stock_dir = os.path.join(test_data_path, ticker)
    os.makedirs(stock_dir, exist_ok=True)
    
    # 檢查文件是否存在
    if not os.path.exists(file_path):
        print(f"錯誤: 找不到文件 {file_path}")
        return
    
    # 嘗試加載數據
    try:
        print(f"正在加載 {ticker} 的歷史數據...")
        df = data_loader.load_from_csv(file_path)
        
        # 顯示數據基本信息
        print(f"\n成功加載數據，共 {len(df)} 筆記錄")
        print(f"數據範圍: {df.index[0]} 到 {df.index[-1]}")
        
        # 顯示欄位數量和名稱
        print(f"\n數據欄位數量: {len(df.columns)}")
        print("\n數據欄位:")
        for i, col in enumerate(df.columns, 1):
            print(f"{i}. {col}")
        
        # 顯示數據前5行的基本信息
        print("\n數據前5行的基本信息:")
        print(f"- 日期範圍: {df.index[0]} 到 {df.index[4]}")
        if '收盤價' in df.columns:
            print(f"- 收盤價範圍: {df['收盤價'].iloc[0]} 到 {df['收盤價'].iloc[4]}")
        
        # 檢查缺失值
        missing_values = df.isnull().sum()
        print("\n缺失值統計:")
        if any(missing_values > 0):
            for col, count in missing_values[missing_values > 0].items():
                print(f"- {col}: {count}")
        else:
            print("- 沒有缺失值")
        
        # 簡單數據處理
        print("\n正在進行基本數據處理...")
        df_cleaned = data_processor.clean_data(df)
        df_features = data_processor.add_basic_features(df_cleaned)
        
        # 顯示處理後的數據欄位
        print(f"\n處理後的數據欄位數量: {len(df_features.columns)}")
        print("\n處理後的數據欄位:")
        for i, col in enumerate(df_features.columns, 1):
            print(f"{i}. {col}")
        
        # 保存處理後的數據（可選）
        save_processed = input("\n是否保存處理後的數據? (y/n): ").lower() == 'y'
        if save_processed:
            output_path = os.path.join(stock_dir, f"{ticker}_processed.csv")
            # 確保日期索引被保存
            df_features.to_csv(output_path, encoding='utf-8-sig', index=True)
            print(f"處理後的數據已保存至 {output_path}")
        
    except Exception as e:
        print(f"處理數據時出錯: {str(e)}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_data_loading() 