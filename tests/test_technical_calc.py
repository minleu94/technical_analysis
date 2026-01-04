#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
技術指標計算測試腳本
採用02_technical_calculator.md中的路徑設定
"""

import os
import sys
from pathlib import Path
import pandas as pd
import logging
import traceback

# 將項目根目錄添加到系統路徑
root_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root_dir))

# 導入自定義模塊
from data_module.config import TWStockConfig
from analysis_module.technical_analysis.technical_indicators import TechnicalIndicatorCalculator


def setup_logging():
    """設置日誌記錄"""
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.INFO)
    
    # 清除現有的處理器
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
    
    # 檔案處理器
    file_handler = logging.FileHandler('tech_test.log', encoding='utf-8')
    file_handler.setFormatter(
        logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    )
    
    # 控制台處理器
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(
        logging.Formatter('%(levelname)s: %(message)s')
    )
    
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    return logger


def check_directories(logger):
    """檢查關鍵目錄是否存在"""
    # 使用02文件中的路徑
    base_dir = Path("D:/Min/Python/Project/FA_Data")
    
    # 關鍵目錄
    directories = {
        "基礎目錄": base_dir,
        "日交易數據": base_dir / "daily_price",
        "元數據": base_dir / "meta_data",
        "技術分析數據": base_dir / "technical_analysis",
        "備份目錄": base_dir / "meta_data/backup"
    }
    
    # 檢查目錄
    all_exist = True
    for name, dir_path in directories.items():
        exists = dir_path.exists()
        logger.info(f"{name}: {dir_path} - {'存在' if exists else '不存在'}")
        all_exist = all_exist and exists
        
        # 嘗試創建不存在的目錄
        if not exists:
            try:
                dir_path.mkdir(parents=True, exist_ok=True)
                logger.info(f"已創建目錄: {dir_path}")
            except Exception as e:
                logger.error(f"無法創建目錄 {dir_path}: {e}")
    
    # 檢查關鍵文件
    stock_data_file = base_dir / "meta_data/stock_data_whole.csv"
    if stock_data_file.exists():
        logger.info(f"股票數據文件存在: {stock_data_file}")
    else:
        logger.warning(f"股票數據文件不存在: {stock_data_file}")
        all_exist = False
    
    return all_exist


def process_stock(stock_id, logger):
    """處理特定股票的技術指標"""
    try:
        # 創建配置和計算器
        config = TWStockConfig()
        calculator = TechnicalIndicatorCalculator()
        
        # 檢查股票數據文件
        if not config.stock_data_file.exists():
            logger.error(f"找不到股票數據文件: {config.stock_data_file}")
            return False
        
        # 讀取股票數據
        logger.info(f"讀取股票數據: {config.stock_data_file}")
        df = pd.read_csv(config.stock_data_file, dtype={'證券代號': str})
        
        # 過濾特定股票
        if stock_id:
            df = df[df['證券代號'] == stock_id]
            if len(df) == 0:
                logger.error(f"找不到股票 {stock_id} 的數據")
                return False
        
        # 分組處理
        success_count = 0
        for current_stock_id, group_df in df.groupby('證券代號'):
            if len(group_df) < 30:
                logger.warning(f"股票 {current_stock_id} 數據量不足 ({len(group_df)} < 30)")
                continue
                
            logger.info(f"處理股票 {current_stock_id}，數據量：{len(group_df)}")
            
            # 計算指標
            result = calculator.calculate_and_store_indicators(
                group_df, 
                current_stock_id, 
                output_dir=config.technical_dir
            )
            
            if result is not None:
                success_count += 1
                logger.info(f"成功處理股票 {current_stock_id}")
            else:
                logger.error(f"處理股票 {current_stock_id} 失敗")
        
        logger.info(f"總共成功處理 {success_count} 支股票")
        return success_count > 0
        
    except Exception as e:
        logger.error(f"處理股票時發生錯誤: {e}")
        logger.error(traceback.format_exc())
        return False


def main():
    """主程序"""
    logger = setup_logging()
    logger.info("開始測試技術指標計算...")
    
    # 檢查目錄
    logger.info("檢查目錄結構...")
    if not check_directories(logger):
        logger.warning("一些關鍵目錄或文件不存在，但將繼續執行")
    
    # 處理特定股票 (例如 2330) 或留空處理所有股票
    stock_id = "2330"
    logger.info(f"開始處理股票: {stock_id}")
    
    if process_stock(stock_id, logger):
        logger.info("技術指標計算測試成功!")
    else:
        logger.error("技術指標計算測試失敗!")
    
    logger.info("測試完成")
    

if __name__ == "__main__":
    main() 