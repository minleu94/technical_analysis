import pandas as pd
import numpy as np
from datetime import datetime
from data_module.config import DataConfig
from data_module.data_loader import DataLoader

def main():
    # 初始化配置和數據加載器
    config = DataConfig()
    loader = DataLoader(config)
    
    # 使用固定的日期
    date = "20250319"
    
    # 1. 讀取現有數據
    print(f"\n1. 讀取現有數據 ({date})")
    existing_data = loader.load_daily_price(date)
    if existing_data is not None:
        print(f"現有數據形狀: {existing_data.shape}")
        print("現有數據列名:", existing_data.columns.tolist())
        print("\n現有數據前5行:")
        print(existing_data.head())
    else:
        print(f"找不到日期 {date} 的現有數據")
    
    # 2. 從API下載新數據
    print(f"\n2. 從API下載新數據 ({date})")
    new_data = loader.download_from_api("ALL", date, date)
    if new_data is not None:
        print(f"API數據形狀: {new_data.shape}")
        print("API數據列名:", new_data.columns.tolist())
        print("\nAPI數據前5行:")
        print(new_data.head())
        
        # 額外的數據處理步驟
        print("\n處理股票代碼格式...")
        # 確保股票代碼是字符串類型
        new_data['證券代號'] = new_data['證券代號'].astype(str)
        # 移除任何前導零
        new_data['證券代號'] = new_data['證券代號'].str.lstrip('0')
        # 重新添加前導零以確保4位數格式
        new_data['證券代號'] = new_data['證券代號'].str.zfill(4)
        
        # 設置證券代號列為字符串類型
        new_data = new_data.astype({'證券代號': 'string'})
        
        # 3. 保存到正確位置
        print(f"\n3. 保存數據到正確位置")
        file_path = config.get_daily_price_file(date)
        print(f"保存路徑: {file_path}")
        # 使用utf-8-sig編碼保存，確保Excel能正確顯示中文
        new_data.to_csv(file_path, index=False, encoding='utf-8-sig')
        print(f"數據已保存到: {file_path}")
        
        # 4. 驗證保存的數據
        print(f"\n4. 驗證保存的數據")
        saved_data = pd.read_csv(file_path, encoding='utf-8-sig', dtype={'證券代號': 'string'})
        print(f"保存的數據形狀: {saved_data.shape}")
        print("\n保存的數據前5行:")
        print(saved_data.head())
        
        # 5. 驗證股票代碼格式
        print("\n驗證股票代碼格式:")
        print(saved_data['證券代號'].head())
        print("\n數據類型:", saved_data['證券代號'].dtype)
    else:
        print(f"無法從API獲取日期 {date} 的數據")

if __name__ == "__main__":
    main() 