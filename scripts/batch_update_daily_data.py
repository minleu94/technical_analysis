"""批量更新每日股票數據 - 使用主模組"""
import sys
from pathlib import Path
import argparse
import logging
import time
import random
from datetime import datetime, timedelta

# 添加項目根目錄到系統路徑
project_root = Path(__file__).parent.parent
sys.path.append(str(project_root))

from data_module.config import TWStockConfig
from data_module.data_loader import DataLoader

def setup_logging():
    """設置日誌"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    return logging.getLogger(__name__)

def is_trading_day(date: datetime) -> bool:
    """檢查是否為交易日（排除週末）"""
    # 週一=0, 週日=6
    return date.weekday() < 5  # 週一到週五

def get_trading_days(start_date: str, end_date: str = None) -> list:
    """獲取交易日列表
    
    Args:
        start_date: 開始日期 (YYYY-MM-DD)
        end_date: 結束日期 (YYYY-MM-DD)，如果為 None 則使用今天
    """
    if end_date is None:
        end_date = datetime.today().strftime('%Y-%m-%d')
    
    start = datetime.strptime(start_date, '%Y-%m-%d')
    end = datetime.strptime(end_date, '%Y-%m-%d')
    
    trading_days = []
    current = start + timedelta(days=1)  # 從 start_date 的第二天開始
    
    while current <= end:
        if is_trading_day(current):
            trading_days.append(current.strftime('%Y-%m-%d'))
        current += timedelta(days=1)
    
    return trading_days

def batch_update_daily_data(start_date: str, end_date: str = None, 
                            delay_min: float = 4.0, delay_max: float = 4.0):
    """批量更新每日股票數據
    
    Args:
        start_date: 開始日期 (YYYY-MM-DD)
        end_date: 結束日期 (YYYY-MM-DD)，如果為 None 則使用今天
        delay_min: 最小延遲時間（秒）
        delay_max: 最大延遲時間（秒）
    """
    logger = setup_logging()
    config = TWStockConfig()
    loader = DataLoader(config)
    
    # 獲取交易日列表
    trading_days = get_trading_days(start_date, end_date)
    
    if not trading_days:
        logger.warning("沒有找到需要更新的交易日")
        logger.info("=" * 60)
        logger.info("批量更新完成！")
        logger.info("成功: 0 天（範圍內沒有交易日）")
        logger.info("失敗: 0 天")
        logger.info("=" * 60)
        return
    
    logger.info(f"準備更新從 {start_date} 之後到 {end_date or '今天'} 的股票數據")
    logger.info(f"共 {len(trading_days)} 個交易日需要更新")
    logger.info(f"延遲時間: {delay_min} 秒/次（固定）")
    logger.info("=" * 60)
    
    success_count = 0
    fail_count = 0
    failed_dates = []
    
    for i, date in enumerate(trading_days, 1):
        logger.info(f"\n[{i}/{len(trading_days)}] 正在更新 {date} 的數據...")
        
        try:
            # 檢查文件是否已存在（使用主模組的方法確保格式正確）
            daily_price_file = loader.get_daily_price_file(date)
            if daily_price_file.exists():
                logger.info(f"  ⚠ {date} 的數據已存在（{daily_price_file.name}），跳過")
                success_count += 1
                continue
            
            # 使用主模組的 download_from_api 方法
            df = loader.download_from_api(date)
            
            if df is None or df.empty:
                logger.error(f"  ✗ {date} 更新失敗：無法獲取數據或數據為空")
                fail_count += 1
                failed_dates.append(date)
            else:
                logger.info(f"  ✓ {date} 更新成功：{len(df)} 筆記錄")
                success_count += 1
            
            # 添加延遲（最後一個不需要延遲）
            if i < len(trading_days):
                delay_time = random.uniform(delay_min, delay_max)
                logger.info(f"  等待 {delay_time:.1f} 秒後繼續...")
                time.sleep(delay_time)
                
        except Exception as e:
            logger.error(f"  ✗ {date} 更新時發生錯誤: {str(e)}")
            fail_count += 1
            failed_dates.append(date)
            
            # 即使出錯也要延遲，避免連續錯誤
            if i < len(trading_days):
                delay_time = random.uniform(delay_min, delay_max)
                time.sleep(delay_time)
    
    # 顯示總結
    logger.info("\n" + "=" * 60)
    logger.info("批量更新完成！")
    logger.info(f"成功: {success_count} 天")
    logger.info(f"失敗: {fail_count} 天")
    
    if failed_dates:
        logger.warning(f"失敗的日期: {', '.join(failed_dates)}")
        logger.warning("可以稍後重新嘗試更新這些日期")
    
    logger.info("=" * 60)
    logger.info("注意：數據已更新到 daily_price 目錄，尚未合併到 meta_data")
    logger.info("請檢查數據無誤後，再執行合併：python scripts/merge_daily_data.py")
    
    # ✅ 輸出易於解析的總結行（用於 UpdateService 解析）
    # 使用 print 輸出到 stdout，確保能被 subprocess 捕獲
    # 使用英文標記避免編碼問題
    print(f"\n[UPDATE_SUMMARY] SUCCESS: {success_count} days, FAILED: {fail_count} days", flush=True)

def main():
    """主函數"""
    parser = argparse.ArgumentParser(
        description='批量更新每日股票數據（使用主模組）',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用範例:
  # 更新從 2025-08-28 之後到今天的所有交易日
  python scripts/batch_update_daily_data.py --start-date 2025-08-28
  
  # 更新指定日期範圍
  python scripts/batch_update_daily_data.py --start-date 2025-08-28 --end-date 2025-09-05
  
  # 自訂延遲時間（秒）
  python scripts/batch_update_daily_data.py --start-date 2025-08-28 --delay-min 3 --delay-max 5
        """
    )
    
    parser.add_argument(
        '--start-date', 
        type=str, 
        required=True,
        help='開始日期 (YYYY-MM-DD格式)，會從這個日期的第二天開始更新'
    )
    parser.add_argument(
        '--end-date', 
        type=str,
        default=None,
        help='結束日期 (YYYY-MM-DD格式)，如果未指定則使用今天'
    )
    parser.add_argument(
        '--delay-min', 
        type=float,
        default=4.0,
        help='最小延遲時間（秒），預設 4.0'
    )
    parser.add_argument(
        '--delay-max', 
        type=float,
        default=4.0,
        help='最大延遲時間（秒），預設 4.0'
    )
    
    args = parser.parse_args()
    
    # 驗證日期格式
    try:
        datetime.strptime(args.start_date, '%Y-%m-%d')
        if args.end_date:
            datetime.strptime(args.end_date, '%Y-%m-%d')
    except ValueError:
        print("錯誤：日期格式必須為 YYYY-MM-DD")
        sys.exit(1)
    
    # 驗證延遲時間
    if args.delay_min < 0 or args.delay_max < 0:
        print("錯誤：延遲時間必須大於等於 0")
        sys.exit(1)
    
    if args.delay_min > args.delay_max:
        print("錯誤：最小延遲時間不能大於最大延遲時間")
        sys.exit(1)
    
    batch_update_daily_data(
        args.start_date, 
        args.end_date,
        args.delay_min,
        args.delay_max
    )

if __name__ == "__main__":
    main()

