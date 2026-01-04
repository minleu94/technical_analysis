import sys
import os
from pathlib import Path
import logging
from datetime import datetime, timedelta
import pandas as pd

# 添加項目根目錄到系統路徑
project_root = Path(__file__).parent.parent
sys.path.append(str(project_root))

from data_module.data_loader import DataLoader
from data_module.config import TWStockConfig
# from technical_analysis.utils.io_utils import safe_write_with_dry_run
from utils.io_utils import safe_write_with_dry_run

def setup_logging():
    """設置日誌"""
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    
    # 創建格式化器
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    
    # 文件處理器（UTF-8 編碼）
    file_handler = logging.FileHandler(log_dir / "update_stock_data.log", encoding='utf-8')
    file_handler.setFormatter(formatter)
    
    # 控制台處理器（處理編碼錯誤）
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    # 設置錯誤處理，避免編碼錯誤導致崩潰
    console_handler.setLevel(logging.INFO)
    
    # 配置根日誌記錄器
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.handlers.clear()  # 清除現有處理器
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)
    
    return logging.getLogger(__name__)

def get_last_trading_date():
    """獲取最後一個交易日"""
    today = datetime.now()
    
    # 如果是週末，調整到週五
    if today.weekday() == 5:  # 星期六
        today = today - timedelta(days=1)
    elif today.weekday() == 6:  # 星期日
        today = today - timedelta(days=2)
    
    # 如果當前時間早於下午2點，使用前一個交易日
    if today.hour < 14:
        today = today - timedelta(days=1)
        # 如果前一天是週末，再往前調整
        if today.weekday() == 5:
            today = today - timedelta(days=1)
        elif today.weekday() == 6:
            today = today - timedelta(days=2)
    
    return today.strftime('%Y-%m-%d')

def get_last_local_date(daily_price_dir: Path) -> str:
    """獲取本地數據的最後日期"""
    try:
        # 獲取所有CSV文件
        csv_files = list(daily_price_dir.glob("*.csv"))
        if not csv_files:
            return None
            
        # 從文件名中獲取日期並找出最大值
        dates = [file.stem for file in csv_files]
        return max(dates)
        
    except Exception as e:
        logger = logging.getLogger(__name__)
        logger.error(f"獲取本地最後日期時發生錯誤: {str(e)}")
        return None

def generate_trading_dates(start_date: str, end_date: str) -> list:
    """生成交易日期列表"""
    dates = []
    current = datetime.strptime(start_date, '%Y-%m-%d')
    end = datetime.strptime(end_date, '%Y-%m-%d')
    
    while current <= end:
        # 跳過週末
        if current.weekday() < 5:  # 0-4 代表週一到週五
            dates.append(current.strftime('%Y-%m-%d'))
        current += timedelta(days=1)
    
    return dates

def batch_update_stock_data(start_date: str = None, end_date: str = None):
    """批量更新股票數據"""
    logger = setup_logging()
    
    try:
        # 初始化配置和數據加載器
        config = TWStockConfig()
        loader = DataLoader(config)
        
        # 如果沒有指定開始日期，使用本地最後更新日期的下一天
        if start_date is None:
            last_date = get_last_local_date(config.daily_price_dir)
            if last_date:
                start_date = (datetime.strptime(last_date, '%Y-%m-%d') + timedelta(days=1)).strftime('%Y-%m-%d')
            else:
                logger.error("無法確定開始日期")
                return False
        
        # 如果沒有指定結束日期，使用最後一個交易日
        if end_date is None:
            end_date = get_last_trading_date()
        
        logger.info(f"開始批量更新數據，日期範圍：{start_date} 到 {end_date}")
        
        # 生成需要更新的日期列表
        dates = generate_trading_dates(start_date, end_date)
        
        # 批量更新數據
        success_count = 0
        for date in dates:
            logger.info(f"正在處理日期：{date}")
            if loader.update_daily_data(date):
                success_count += 1
                logger.info(f"成功更新 {date} 的數據")
            else:
                logger.warning(f"更新 {date} 的數據失敗")
        
        # 如果有成功更新的數據，執行合併
        if success_count > 0:
            logger.info("開始合併數據...")
            merged_data = loader.merge_daily_data()
            if merged_data is not None:
                logger.info("數據合併完成")
                return True
        
        return False
        
    except Exception as e:
        logger.error(f"批量更新數據時發生錯誤: {str(e)}")
        return False

def update_stock_data(date: str = None):
    """更新股票數據"""
    logger = setup_logging()
    
    try:
        # 初始化配置和數據加載器
        config = TWStockConfig()
        loader = DataLoader(config)
        
        # 如果沒有指定日期，使用最後一個交易日
        if date is None:
            date = get_last_trading_date()
        
        logger.info(f"開始更新 {date} 的股票數據")
        
        # 更新數據
        if loader.update_daily_data(date):
            logger.info(f"成功更新 {date} 的股票數據")
            
            # 合併數據
            logger.info("開始合併每日數據")
            merged_data = loader.merge_daily_data()
            if merged_data is not None:
                logger.info("完成合併每日數據")
                return True
        else:
            logger.error(f"更新 {date} 的股票數據失敗")
            return False
        
        return True
        
    except Exception as e:
        logger.error(f"更新數據時發生錯誤: {str(e)}")
        return False

def start_scheduled_update():
    """啟動定時更新"""
    logger = setup_logging()
    
    try:
        # 初始化配置和數據加載器
        config = TWStockConfig()
        loader = DataLoader(config)
        
        logger.info("啟動定時更新服務")
        loader.schedule_daily_update()
        
    except Exception as e:
        logger.error(f"啟動定時更新服務時發生錯誤: {str(e)}")

if __name__ == "__main__":
    import argparse
    
    # 使用新的配置系統
    config, config_args = TWStockConfig.from_args()
    
    parser = argparse.ArgumentParser(description='更新股票數據')
    parser.add_argument('--date', type=str, help='指定更新日期 (YYYY-MM-DD格式)', default=None)
    parser.add_argument('--start-date', type=str, help='批量更新的開始日期 (YYYY-MM-DD格式)', default=None)
    parser.add_argument('--end-date', type=str, help='批量更新的結束日期 (YYYY-MM-DD格式)', default=None)
    parser.add_argument('--schedule', action='store_true', help='啟動定時更新服務')
    parser.add_argument('--batch', action='store_true', help='執行批量更新')
    
    args = parser.parse_args()
    
    # 更新DataLoader使用新配置
    loader = DataLoader(config)
    
    if args.schedule:
        start_scheduled_update()
    elif args.batch:
        batch_update_stock_data(args.start_date, args.end_date)
    else:
        update_stock_data(args.date) 