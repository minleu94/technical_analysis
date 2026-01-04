"""使用主模組更新每日股票數據 - 推薦方式"""
import sys
from pathlib import Path
import argparse
import logging

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

def update_daily_stock_data(date: str, merge: bool = False):
    """更新指定日期的股票數據
    
    Args:
        date: 日期字串，格式為 YYYY-MM-DD
        merge: 是否合併到 meta_data
    """
    logger = setup_logging()
    config = TWStockConfig()
    loader = DataLoader(config)
    
    logger.info(f"開始更新 {date} 的股票數據...")
    
    # 使用主模組的 download_from_api 方法
    df = loader.download_from_api(date)
    
    if df is None or df.empty:
        logger.error(f"無法獲取 {date} 的股票數據")
        return False
    
    logger.info(f"✓ 成功更新 {date} 的股票數據，共 {len(df)} 筆記錄")
    
    # 如果需要合併到 meta_data
    if merge:
        logger.info("開始合併數據到 meta_data...")
        merged_data = loader.merge_daily_data()
        
        if merged_data is not None:
            logger.info(f"✓ 成功合併數據到 {config.all_stocks_data_file}")
            logger.info(f"  合併後的數據形狀: {merged_data.shape}")
            logger.info(f"  日期範圍: {merged_data['日期'].min()} 到 {merged_data['日期'].max()}")
            return True
        else:
            logger.error("✗ 合併數據失敗")
            return False
    
    return True

def main():
    """主函數"""
    parser = argparse.ArgumentParser(
        description='使用主模組更新每日股票數據（推薦方式）',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用範例:
  # 更新單日數據（只更新 daily_price）
  python scripts/update_daily_stock_data.py --date 2025-08-29
  
  # 更新並自動合併到 meta_data
  python scripts/update_daily_stock_data.py --date 2025-08-29 --merge
        """
    )
    
    parser.add_argument(
        '--date', 
        type=str, 
        required=True,
        help='更新日期 (YYYY-MM-DD格式)'
    )
    parser.add_argument(
        '--merge', 
        action='store_true',
        help='更新後自動合併到 meta_data'
    )
    
    args = parser.parse_args()
    
    success = update_daily_stock_data(args.date, args.merge)
    
    if success:
        print(f"\n✓ 更新完成！")
        sys.exit(0)
    else:
        print(f"\n✗ 更新失敗！")
        sys.exit(1)

if __name__ == "__main__":
    main()

