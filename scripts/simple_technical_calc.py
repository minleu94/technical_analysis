#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
簡化版技術指標計算腳本
直接使用02_technical_calculator.md中的路徑設定
"""

import os
import sys
from pathlib import Path
import pandas as pd
import numpy as np
import logging
import traceback
from datetime import datetime

# 將項目根目錄添加到系統路徑
root_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root_dir))

# 導入自定義模塊
from data_module.config import TWStockConfig
from analysis_module.technical_analysis.technical_indicators import TechnicalIndicatorCalculator


def process_stock(stock_id="2330"):
    """處理指定股票的技術指標"""
    # 設置直接輸出到控制台
    print(f"開始處理股票 {stock_id} 的技術指標...")
    
    try:
        # 1. 創建配置
        base_dir = Path("D:/Min/Python/Project/FA_Data")
        config = TWStockConfig(base_dir=base_dir)
        
        # 2. 檢查關鍵目錄和檔案
        stock_data_file = config.stock_data_file
        technical_dir = config.technical_dir
        
        print(f"使用的數據目錄: {config.data_dir}")
        print(f"股票數據文件: {stock_data_file}")
        print(f"技術指標輸出目錄: {technical_dir}")
        
        if not stock_data_file.exists():
            print(f"錯誤: 股票數據文件不存在: {stock_data_file}")
            return False
            
        # 確保目錄存在
        technical_dir.mkdir(parents=True, exist_ok=True)
        
        # 3. 讀取數據
        print(f"讀取股票數據...")
        df = pd.read_csv(stock_data_file, dtype={'證券代號': str})
        
        # 過濾特定股票
        df = df[df['證券代號'] == stock_id]
        
        if len(df) == 0:
            print(f"錯誤: 找不到股票 {stock_id} 的數據")
            return False
            
        print(f"成功載入 {len(df)} 筆 {stock_id} 的數據")
        
        # 4. 計算技術指標
        print(f"開始計算技術指標...")
        calculator = TechnicalIndicatorCalculator()
        
        # 預處理數據
        print("步驟1: 數據預處理")
        processed_df = calculator.process_price_data(df)
        
        # 計算指標
        print("步驟2: 計算技術指標")
        result_df = calculator.calculate_all_indicators(processed_df, stock_id)
        
        if result_df is None:
            print("錯誤: 技術指標計算失敗")
            return False
        
        # 5. 保存結果
        output_file = technical_dir / f"{stock_id}_indicators.csv"
        print(f"步驟3: 保存結果到 {output_file}")
        
        # 確保目錄存在
        os.makedirs(os.path.dirname(output_file), exist_ok=True)
        
        # 保存檔案
        result_df.to_csv(output_file, index=False, encoding='utf-8-sig')
        
        # 顯示結果範例
        print("\n計算結果範例 (最後5筆):")
        print(result_df.tail().to_string())
        
        print(f"\n成功處理並保存 {stock_id} 的技術指標!")
        return True
        
    except Exception as e:
        print(f"處理時發生錯誤: {e}")
        traceback.print_exc()
        return False


if __name__ == "__main__":
    # 可以直接提供股票代碼作為命令行參數
    if len(sys.argv) > 1:
        stock_id = sys.argv[1]
    else:
        stock_id = "2330"
    
    print(f"===== 開始處理股票 {stock_id} 的技術指標 =====")
    start_time = datetime.now()
    
    success = process_stock(stock_id)
    
    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()
    
    print(f"===== 處理完成 =====")
    print(f"處理時間: {duration:.2f} 秒")
    print(f"結果: {'成功' if success else '失敗'}")
    
    sys.exit(0 if success else 1) 