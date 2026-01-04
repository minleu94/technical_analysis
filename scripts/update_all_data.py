import sys
import os
from pathlib import Path
import logging
import time
import random
import warnings
import shutil
import traceback
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
import requests
import argparse
import yfinance as yf
from tqdm import tqdm

# 忽略 HTTPS 請求的警告
warnings.filterwarnings('ignore', message='Unverified HTTPS request')

# 添加項目根目錄到系統路徑
project_root = Path(__file__).parent.parent
sys.path.append(str(project_root))

from data_module.data_loader import DataLoader, MarketDateRange
from data_module.config import TWStockConfig
# from technical_analysis.utils.io_utils import safe_write_with_dry_run
from utils.io_utils import safe_write_with_dry_run

def setup_logging():
    """設置日誌"""
    config = TWStockConfig()
    log_dir = config.log_dir
    log_dir.mkdir(exist_ok=True)
    
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.INFO)
    
    # 清除現有的處理器
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
    
    # 創建文件處理器
    file_handler = logging.FileHandler(
        log_dir / "update_all_data.log",
        encoding='utf-8'
    )
    file_handler.setLevel(logging.INFO)
    
    # 創建控制台處理器
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    
    # 設置格式
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)
    
    # 添加處理器
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    return logger

class TWMarketDataProcessor:
    def __init__(self, config=None, date_range=None, dry_run=False):
        """初始化數據處理器
        
        Args:
            config: TWStockConfig 實例，如果為 None 則創建新實例
            date_range: MarketDateRange 實例，如果為 None 則創建新實例
            dry_run: 是否為乾運行模式
        """
        self.config = config or TWStockConfig()
        self.date_range = date_range or MarketDateRange()
        self.dry_run = dry_run
        self.logger = setup_logging()
        
        # 記錄設定的日期範圍
        self.logger.info(f"設定數據處理範圍: {self.date_range.date_range_str}")
        if self.dry_run:
            self.logger.info("*** 乾運行模式 - 不會實際寫入檔案 ***")
        
        # 初始化數據加載器
        self.data_loader = DataLoader(self.config)
    
    def process_all(self):
        """處理所有類型的數據"""
        try:
            self.logger.info("=== 開始台股數據更新 ===")
            self.logger.info(f"日期範圍: {self.date_range.date_range_str}")
            
            # 獲取日期列表
            date_list = [d.strftime('%Y-%m-%d') for d in self.date_range.get_date_list() 
                         if d.weekday() < 5]  # 排除週末
            
            # 1. 更新大盤指數
            self.logger.info("\n1. 更新大盤指數...")
            market_success = 0
            for date in tqdm(date_list, desc="更新大盤指數"):
                if self.data_loader.update_market_index(date):
                    market_success += 1
                # 避免請求過於頻繁
                time.sleep(random.uniform(1, 2))
            
            self.logger.info(f"大盤指數更新完成: 成功 {market_success}/{len(date_list)} 天")
            
            time.sleep(3)  # 等待3秒避免請求過於頻繁
            
            # 2. 更新產業指數
            self.logger.info("\n2. 更新產業指數...")
            industry_success = 0
            for date in tqdm(date_list, desc="更新產業指數"):
                if self.data_loader.update_industry_index(date):
                    industry_success += 1
                # 避免請求過於頻繁
                time.sleep(random.uniform(1, 2))
            
            self.logger.info(f"產業指數更新完成: 成功 {industry_success}/{len(date_list)} 天")
            
            time.sleep(3)
            
            # 3. 更新個股數據
            self.logger.info("\n3. 更新個股數據...")
            stock_success = 0
            for date in tqdm(date_list, desc="更新個股數據"):
                if self.data_loader.update_daily_data(date):
                    stock_success += 1
                # 避免請求過於頻繁
                time.sleep(random.uniform(1, 2))
            
            self.logger.info(f"個股數據更新完成: 成功 {stock_success}/{len(date_list)} 天")
            
            self.logger.info("\n=== 台股數據更新完成 ===")
            return True
            
        except Exception as e:
            self.logger.error(f"\n更新過程發生錯誤: {str(e)}")
            self.logger.error("\n詳細錯誤信息:")
            self.logger.error(traceback.format_exc())
            return False

def check_data_status():
    """檢查各資料檔案的狀態和最新日期，修正日期排序問題"""
    logger = setup_logging()
    
    # 設定路徑
    config = TWStockConfig()
    
    logger.info("\n=== 台股數據檔案狀態 ===")
    
    # 檢查大盤指數檔案
    if config.market_index_file.exists():
        df_market = pd.read_csv(config.market_index_file, encoding='utf-8-sig')
        
        # 檢查並修正日期格式
        if '日期' in df_market.columns:
            try:
                df_market['日期'] = pd.to_datetime(df_market['日期'], format='mixed').dt.strftime('%Y-%m-%d')
                df_market = df_market.sort_values('日期')
                df_market.to_csv(config.market_index_file, index=False, encoding='utf-8-sig')
                logger.info("大盤指數檔案日期已排序")
            except Exception as e:
                logger.error(f"處理大盤指數日期時發生錯誤: {str(e)}")
        
        logger.info(f"大盤指數檔案: 存在 ({len(df_market)} 筆資料)")
        logger.info(f"  - 最新日期: {df_market['日期'].max() if '日期' in df_market.columns else '無日期欄位'}")
    else:
        logger.info("大盤指數檔案: 不存在")
    
    # 檢查產業指數檔案
    if config.industry_index_file.exists():
        df_industry = pd.read_csv(config.industry_index_file, encoding='utf-8-sig')
        
        # 檢查並修正日期格式
        if '日期' in df_industry.columns:
            try:
                df_industry['日期'] = pd.to_datetime(df_industry['日期'], format='mixed').dt.strftime('%Y-%m-%d')
                df_industry = df_industry.sort_values(['日期', '指數名稱'])
                df_industry.to_csv(config.industry_index_file, index=False, encoding='utf-8-sig')
                logger.info("產業指數檔案日期已排序")
            except Exception as e:
                logger.error(f"處理產業指數日期時發生錯誤: {str(e)}")
        
        logger.info(f"產業指數檔案: 存在 ({len(df_industry)} 筆資料)")
        logger.info(f"  - 最新日期: {df_industry['日期'].max() if '日期' in df_industry.columns else '無日期欄位'}")
        logger.info(f"  - 指數數量: {df_industry['指數名稱'].nunique() if '指數名稱' in df_industry.columns else '無指數名稱欄位'}")
    else:
        logger.info("產業指數檔案: 不存在")
    
    # 檢查每日價格檔案數量
    daily_price_files = list(config.daily_price_dir.glob('*.csv'))
    logger.info(f"每日價格檔案: {len(daily_price_files)} 個檔案")
    
    if daily_price_files:
        # 檢查最新和最舊的價格檔案
        date_pattern = r'(\d{4}-\d{2}-\d{2})\.csv'
        file_dates = []
        for file in daily_price_files:
            import re
            match = re.search(date_pattern, file.name)
            if match:
                file_dates.append(match.group(1))
        
        if file_dates:
            file_dates.sort()
            logger.info(f"  - 最早日期: {file_dates[0]}")
            logger.info(f"  - 最新日期: {file_dates[-1]}")
            logger.info(f"  - 涵蓋天數: {len(file_dates)} 天")

def main():
    """主函數"""
    # 使用新的配置系統
    config, config_args = TWStockConfig.from_args()
    
    parser = argparse.ArgumentParser(description='台股數據更新工具')
    parser.add_argument('--days', type=int, default=30, help='更新最近幾天的數據')
    parser.add_argument('--start', type=str, help='開始日期，格式: YYYY-MM-DD')
    parser.add_argument('--end', type=str, help='結束日期，格式: YYYY-MM-DD')
    parser.add_argument('--check', action='store_true', help='只檢查數據狀態，不更新')
    parser.add_argument('--all', action='store_true', help='更新所有數據（從2014年起）')
    
    args = parser.parse_args()
    
    if args.check:
        check_data_status()
        return
    
    # 設定日期範圍
    if args.all:
        # 從2014年開始
        date_range = MarketDateRange("2014-01-01", datetime.today().strftime('%Y-%m-%d'))
    elif args.start and args.end:
        date_range = MarketDateRange(args.start, args.end)
    elif args.days:
        date_range = MarketDateRange.last_n_days(args.days)
    else:
        date_range = MarketDateRange.last_month()
    
    # 初始化處理器並執行更新
    processor = TWMarketDataProcessor(
        config=config, 
        date_range=date_range, 
        dry_run=config_args.dry_run
    )
    processor.process_all()

if __name__ == "__main__":
    main() 