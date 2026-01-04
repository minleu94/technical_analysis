import pandas as pd

# 讀取信號數據
file_path = r"D:\Min\Python\Project\FA_Data\test_data\2330_signals.csv"
try:
    df = pd.read_csv(file_path, encoding='utf-8-sig')
    print(f"成功讀取數據，共 {len(df)} 筆記錄")
    print(f"欄位數量: {len(df.columns)}")
    print("欄位名稱:")
    for i, col in enumerate(df.columns, 1):
        print(f"{i}. {col}")
    
    # 顯示前5行數據的前幾個欄位
    print("\n前5行數據的前幾個欄位:")
    print(df.iloc[:5, :5])
    
except Exception as e:
    print(f"讀取數據時出錯: {str(e)}") 