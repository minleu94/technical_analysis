import pandas as pd

# 讀取原始數據
file_path = r"D:\Min\Python\Project\FA_Data\technical_analysis\2330_indicators.csv"
try:
    df = pd.read_csv(file_path, encoding='utf-8-sig')
    print(f"成功讀取數據，共 {len(df)} 筆記錄")
    print(f"欄位數量: {len(df.columns)}")
    print("欄位名稱及類型:")
    for i, col in enumerate(df.columns, 1):
        # 顯示欄位名稱、類型和長度，以及前幾個字符的ASCII碼
        col_str = str(col)
        col_repr = repr(col)
        col_type = type(col).__name__
        print(f"{i}. '{col}' (類型: {col_type}, 表示: {col_repr})")
    
    # 檢查是否有重複的欄位名稱
    duplicates = df.columns.duplicated()
    if any(duplicates):
        print("\n發現重複的欄位名稱:")
        for i, (col, is_dup) in enumerate(zip(df.columns, duplicates), 1):
            if is_dup:
                print(f"{i}. '{col}' (重複)")
    
    # 顯示前5行數據的前幾個欄位
    print("\n前5行數據的前幾個欄位:")
    print(df.iloc[:5, :5])
    
except Exception as e:
    print(f"讀取數據時出錯: {str(e)}") 