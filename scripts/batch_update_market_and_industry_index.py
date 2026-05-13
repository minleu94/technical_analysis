"""批量更新大盤指數和產業指數數據 - 使用主模組"""
import sys
import io
from pathlib import Path

# 設置 UTF-8 編碼以支持中文輸出
if sys.platform == 'win32':
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')
    except:
        pass  # 如果已經設置過，忽略錯誤

# 添加項目根目錄到系統路徑
project_root = Path(__file__).parent.parent
sys.path.append(str(project_root))

# 現在導入其他模組
import argparse
import logging
import time
import random
from datetime import datetime, timedelta

try:
    import pandas as pd
except ImportError as e:
    print(f"錯誤：無法導入 pandas 模組")
    print(f"請確認已安裝 pandas: pip install pandas")
    print(f"Python 路徑: {sys.executable}")
    sys.exit(1)

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
    current = start
    
    while current <= end:
        if is_trading_day(current):
            trading_days.append(current.strftime('%Y-%m-%d'))
        current += timedelta(days=1)
    
    return trading_days

def get_latest_date(file_path: Path) -> str:
    """獲取文件中的最新日期"""
    if not file_path.exists():
        return None
    
    try:
        df = pd.read_csv(file_path, encoding='utf-8-sig', on_bad_lines='skip', engine='python')
        if '日期' in df.columns and len(df) > 0:
            # 過濾掉無效日期（NaN）
            df = df[df['日期'].notna()]
            if len(df) == 0:
                return None
            
            # 統一日期格式為 YYYY-MM-DD
            def normalize_date(date_str):
                if pd.isna(date_str) or str(date_str) == 'nan':
                    return None
                try:
                    # 嘗試解析不同格式的日期
                    date_str = str(date_str).strip()
                    # 如果是 M/D/YYYY 格式
                    if '/' in date_str:
                        parts = date_str.split('/')
                        if len(parts) == 3:
                            month, day, year = parts
                            return f"{year}-{month.zfill(2)}-{day.zfill(2)}"
                    # 如果已經是 YYYY-MM-DD 格式
                    elif '-' in date_str and len(date_str) == 10:
                        return date_str
                    return None
                except:
                    return None
            
            df['日期_標準化'] = df['日期'].apply(normalize_date)
            valid_dates = df[df['日期_標準化'].notna()]['日期_標準化']
            if len(valid_dates) > 0:
                return valid_dates.max()
    except Exception as e:
        logging.warning(f"讀取 {file_path} 時發生錯誤: {str(e)}")
    
    return None

def get_existing_dates(file_path: Path) -> set:
    """獲取文件中已存在的標準化日期集合"""
    if not file_path.exists():
        return set()
    
    try:
        df = pd.read_csv(file_path, encoding='utf-8-sig', on_bad_lines='skip', engine='python')
        if '日期' in df.columns and len(df) > 0:
            # 過濾掉無效日期（NaN）
            df = df[df['日期'].notna()]
            if len(df) == 0:
                return set()
            
            # 統一日期格式為 YYYY-MM-DD
            def normalize_date(date_str):
                if pd.isna(date_str) or str(date_str) == 'nan':
                    return None
                try:
                    date_str = str(date_str).strip()
                    if '/' in date_str:
                        parts = date_str.split('/')
                        if len(parts) == 3:
                            month, day, year = parts
                            return f"{year}-{month.zfill(2)}-{day.zfill(2)}"
                    elif '-' in date_str and len(date_str) == 10:
                        return date_str
                    return None
                except:
                    return None
            
            df['日期_標準化'] = df['日期'].apply(normalize_date)
            valid_dates = set(df[df['日期_標準化'].notna()]['日期_標準化'].unique())
            return valid_dates
    except Exception as e:
        logging.warning(f"讀取 {file_path} 獲取已存在日期時發生錯誤: {str(e)}")
    
    return set()

def batch_update_market_index(start_date: str, end_date: str = None, 
                              delay_min: float = 4.0, delay_max: float = 4.0,
                              config=None):
    """批量更新大盤指數數據
    
    Args:
        start_date: 開始日期 (YYYY-MM-DD)
        end_date: 結束日期 (YYYY-MM-DD)，如果為 None 則使用今天
        delay_min: 最小延遲時間（秒）
        delay_max: 最大延遲時間（秒）
        config: TWStockConfig 實例（可選），如果提供則使用，否則創建新的
    """
    logger = setup_logging()
    if config is None:
        config = TWStockConfig()
    loader = DataLoader(config)
    
    # 獲取交易日列表
    trading_days = get_trading_days(start_date, end_date)
    
    if not trading_days:
        logger.warning("沒有找到需要更新的交易日")
        return
    
    # 獲取已存在的日期集合，避免重複下載，並支持歷史數據回補
    existing_dates = get_existing_dates(config.market_index_file)
    if existing_dates:
        logger.info(f"現有 market_index.csv 中已存在 {len(existing_dates)} 天的數據")
        trading_days = [d for d in trading_days if d not in existing_dates]
    
    if not trading_days:
        logger.info("所有數據已是最新，無需更新")
        return
    
    logger.info(f"準備更新從 {trading_days[0]} 到 {trading_days[-1]} 的大盤指數數據")
    logger.info(f"共 {len(trading_days)} 個交易日需要更新")
    logger.info(f"延遲時間: {delay_min}-{delay_max} 秒/次")
    logger.info("=" * 60)
    
    # 開始前備份一次
    if config.market_index_file.exists():
        logger.info(f"開始批量更新前，創建 {config.market_index_file.name} 備份...")
        config.create_backup(config.market_index_file)
    
    success_count = 0
    fail_count = 0
    failed_dates = []
    
    for i, date in enumerate(trading_days, 1):
        logger.info(f"\n[{i}/{len(trading_days)}] 正在更新 {date} 的大盤指數數據...")
        
        try:
            # 使用主模組的 update_market_index 方法，並跳過逐日備份
            success = loader.update_market_index(date, skip_backup=True)
            
            if success:
                logger.info(f"  ✓ {date} 更新成功")
                success_count += 1
            else:
                logger.error(f"  ✗ {date} 更新失敗")
                fail_count += 1
                failed_dates.append(date)
            
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
    logger.info("大盤指數批量更新完成！")
    logger.info(f"成功: {success_count} 天")
    logger.info(f"失敗: {fail_count} 天")
    
    if failed_dates:
        logger.warning(f"失敗的日期: {', '.join(failed_dates)}")
        logger.warning("可以稍後重新嘗試更新這些日期")
        
    # 結束後備份一次
    if success_count > 0 and config.market_index_file.exists():
        logger.info(f"更新結束後，創建 {config.market_index_file.name} 備份...")
        config.create_backup(config.market_index_file)
    
    logger.info("=" * 60)

def batch_update_industry_index(start_date: str, end_date: str = None, 
                                delay_min: float = 4.0, delay_max: float = 4.0,
                                config=None):
    """批量更新產業指數數據
    
    Args:
        start_date: 開始日期 (YYYY-MM-DD)
        end_date: 結束日期 (YYYY-MM-DD)，如果為 None 則使用今天
        delay_min: 最小延遲時間（秒）
        delay_max: 最大延遲時間（秒）
        config: TWStockConfig 實例（可選），如果提供則使用，否則創建新的
    """
    logger = setup_logging()
    if config is None:
        config = TWStockConfig()
    loader = DataLoader(config)
    
    # 獲取交易日列表
    trading_days = get_trading_days(start_date, end_date)
    
    if not trading_days:
        logger.warning("沒有找到需要更新的交易日")
        return
    
    # 獲取已存在的日期集合，避免重複下載，並支持歷史數據回補
    existing_dates = get_existing_dates(config.industry_index_file)
    if existing_dates:
        logger.info(f"現有 industry_index.csv 中已存在 {len(existing_dates)} 天的數據")
        trading_days = [d for d in trading_days if d not in existing_dates]
    
    if not trading_days:
        logger.info("所有數據已是最新，無需更新")
        return
    
    logger.info(f"準備更新從 {trading_days[0]} 到 {trading_days[-1]} 的產業指數數據")
    logger.info(f"共 {len(trading_days)} 個交易日需要更新")
    logger.info(f"延遲時間: {delay_min}-{delay_max} 秒/次")
    logger.info("=" * 60)
    
    # 開始前備份一次
    if config.industry_index_file.exists():
        logger.info(f"開始批量更新前，創建 {config.industry_index_file.name} 備份...")
        config.create_backup(config.industry_index_file)
    
    success_count = 0
    fail_count = 0
    failed_dates = []
    
    for i, date in enumerate(trading_days, 1):
        logger.info(f"\n[{i}/{len(trading_days)}] 正在更新 {date} 的產業指數數據...")
        
        try:
            # 使用主模組的 update_industry_index 方法，並跳過逐日備份
            success = loader.update_industry_index(date, skip_backup=True)
            
            if success:
                logger.info(f"  ✓ {date} 更新成功")
                success_count += 1
            else:
                logger.error(f"  ✗ {date} 更新失敗")
                fail_count += 1
                failed_dates.append(date)
            
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
    logger.info("產業指數批量更新完成！")
    logger.info(f"成功: {success_count} 天")
    logger.info(f"失敗: {fail_count} 天")
    
    if failed_dates:
        logger.warning(f"失敗的日期: {', '.join(failed_dates)}")
        logger.warning("可以稍後重新嘗試更新這些日期")
        
    # 結束後備份一次
    if success_count > 0 and config.industry_index_file.exists():
        logger.info(f"更新結束後，創建 {config.industry_index_file.name} 備份...")
        config.create_backup(config.industry_index_file)
    
    logger.info("=" * 60)

def main():
    """主函數"""
    parser = argparse.ArgumentParser(
        description='批量更新大盤指數和產業指數數據（使用主模組）',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用範例:
  # 更新大盤指數（從最後更新日期到今天）
  python scripts/batch_update_market_and_industry_index.py --type market
  
  # 更新產業指數（從最後更新日期到今天）
  python scripts/batch_update_market_and_industry_index.py --type industry
  
  # 更新兩者（從指定日期開始）
  python scripts/batch_update_market_and_industry_index.py --type both --start-date 2025-08-28
  
  # 自訂延遲時間（秒）
  python scripts/batch_update_market_and_industry_index.py --type market --delay-min 3 --delay-max 5
        """
    )
    
    parser.add_argument(
        '--type',
        type=str,
        choices=['market', 'industry', 'both'],
        default='both',
        help='更新類型：market（大盤指數）、industry（產業指數）、both（兩者都更新）'
    )
    parser.add_argument(
        '--start-date', 
        type=str, 
        default=None,
        help='開始日期 (YYYY-MM-DD格式)，如果未指定則從現有數據的最新日期開始'
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
    if args.start_date:
        try:
            datetime.strptime(args.start_date, '%Y-%m-%d')
        except ValueError:
            print("錯誤：開始日期格式必須為 YYYY-MM-DD")
            sys.exit(1)
    
    if args.end_date:
        try:
            datetime.strptime(args.end_date, '%Y-%m-%d')
        except ValueError:
            print("錯誤：結束日期格式必須為 YYYY-MM-DD")
            sys.exit(1)
    
    # 驗證延遲時間
    if args.delay_min < 0 or args.delay_max < 0:
        print("錯誤：延遲時間必須大於等於 0")
        sys.exit(1)
    
    if args.delay_min > args.delay_max:
        print("錯誤：最小延遲時間不能大於最大延遲時間")
        sys.exit(1)
    
    # 確定開始日期
    if args.start_date is None:
        # 從現有數據的最新日期開始
        config = TWStockConfig()
        if args.type in ['market', 'both']:
            latest_market = get_latest_date(config.market_index_file)
            if latest_market:
                args.start_date = latest_market
            else:
                args.start_date = "2024-01-01"  # 預設起始日期
        
        if args.type in ['industry', 'both']:
            latest_industry = get_latest_date(config.industry_index_file)
            if latest_industry:
                if args.start_date is None or latest_industry < args.start_date:
                    args.start_date = latest_industry
            else:
                if args.start_date is None:
                    args.start_date = "2024-01-01"  # 預設起始日期
    
    # 執行更新
    if args.type in ['market', 'both']:
        batch_update_market_index(
            args.start_date,
            args.end_date,
            args.delay_min,
            args.delay_max
        )
    
    if args.type in ['industry', 'both']:
        batch_update_industry_index(
            args.start_date,
            args.end_date,
            args.delay_min,
            args.delay_max
        )

if __name__ == "__main__":
    main()

