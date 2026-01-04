import pandas as pd
from pathlib import Path
import logging
from datetime import datetime
import shutil
import argparse

# 設置日誌
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def merge_daily_data(force_all: bool = False, config=None):
    """合併每日股票數據
    
    Args:
        force_all: 是否強制重新合併所有數據
        config: TWStockConfig 實例（可選），如果提供則使用配置中的路徑
    """
    # ✅ 確保 datetime 在函數內部可用（避免 UnboundLocalError）
    from datetime import datetime as dt_module
    datetime = dt_module
    
    # 設置路徑
    if config is not None:
        # 使用配置中的路徑
        base_dir = Path(config.data_root)
        daily_price_dir = base_dir / "daily_price"
        meta_data_dir = base_dir / "meta_data"
        output_file = config.stock_data_file
        backup_dir = meta_data_dir / "backup"
        logger.info(f"使用配置路徑: base_dir={base_dir}")
    else:
        # 降級方案：使用硬編碼路徑（向後兼容）
        base_dir = Path("D:/Min/Python/Project/FA_Data")
        daily_price_dir = base_dir / "daily_price"
        meta_data_dir = base_dir / "meta_data"
        output_file = meta_data_dir / "stock_data_whole.csv"
        backup_dir = meta_data_dir / "backup"
        logger.warning(f"未提供 config，使用硬編碼路徑: base_dir={base_dir}")
    
    try:
        # 確保目錄存在
        if not daily_price_dir.exists():
            raise FileNotFoundError(f"找不到目錄：{daily_price_dir}")
        
        backup_dir.mkdir(parents=True, exist_ok=True)
        
        # 創建備份並讀取現有數據
        last_date = None
        if output_file.exists():
            # 創建備份
            backup_file = backup_dir / f'stock_data_whole_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
            shutil.copy2(output_file, backup_file)
            logger.info(f"已創建備份文件: {backup_file}")
            
            if not force_all:
                # 讀取現有數據（僅在非強制模式下）
                existing_df = pd.read_csv(output_file, encoding='utf-8-sig', low_memory=False)
                # ✅ 修復：確保日期格式正確（YYYYMMDD 字符串）
                max_date = existing_df['日期'].max()
                if isinstance(max_date, (int, float)):
                    # 如果是數字，轉換為 YYYYMMDD 字符串
                    last_date = str(int(max_date))
                    # 確保是8位數
                    if len(last_date) == 8:
                        pass  # 已經是正確格式
                    elif len(last_date) == 6:
                        # 可能是 YYMMDD，需要補年份
                        last_date = '20' + last_date
                    else:
                        # 嘗試轉換為日期再格式化
                        try:
                            date_str = str(int(max_date))
                            if len(date_str) == 8:
                                last_date = date_str
                            else:
                                # 嘗試解析為日期
                                if len(date_str) == 6:
                                    dt = datetime.strptime(date_str, '%y%m%d')
                                else:
                                    dt = datetime.fromtimestamp(max_date / 1000) if max_date > 1000000000 else datetime.fromtimestamp(max_date)
                                last_date = dt.strftime('%Y%m%d')
                        except:
                            last_date = str(int(max_date)).zfill(8)
                elif isinstance(max_date, str):
                    # 如果是字符串，確保是 YYYYMMDD 格式
                    last_date = max_date.replace('-', '').replace('/', '')
                    if len(last_date) != 8:
                        # 嘗試解析日期
                        try:
                            dt = pd.to_datetime(max_date)
                            last_date = dt.strftime('%Y%m%d')
                        except:
                            last_date = max_date
                else:
                    # 其他類型，嘗試轉換
                    try:
                        dt = pd.to_datetime(max_date)
                        last_date = dt.strftime('%Y%m%d')
                    except:
                        last_date = str(max_date).replace('-', '').replace('/', '')
                
                # 確保是8位數字符串
                if len(last_date) != 8 or not last_date.isdigit():
                    logger.warning(f"日期格式異常: {last_date}，嘗試修復...")
                    try:
                        dt = pd.to_datetime(str(max_date))
                        last_date = dt.strftime('%Y%m%d')
                    except:
                        logger.error(f"無法修復日期格式: {last_date}，將使用強制模式")
                        force_all = True
                        last_date = None
                
                logger.info(f"已讀取現有數據，最後更新日期為: {last_date} (原始值: {max_date}, 類型: {type(max_date)})")
            else:
                logger.info("強制模式：將重新合併所有數據")
        
        # 獲取所有CSV文件
        all_csv_files = list(daily_price_dir.glob("*.csv"))
        if not all_csv_files:
            raise FileNotFoundError(f"在 {daily_price_dir} 中找不到CSV文件")
        
        # 如果有最後更新日期且非強制模式，只處理新的文件
        if last_date and not force_all:
            # ✅ 修復：確保文件名也是正確格式，並正確比較
            csv_files = []
            for f in all_csv_files:
                file_stem = str(f.stem)
                # 確保文件名是8位數
                if len(file_stem) == 8 and file_stem.isdigit():
                    if file_stem > last_date:
                        csv_files.append(f)
                else:
                    logger.warning(f"文件名格式異常，跳過: {f.name} (stem: {file_stem})")
            
            if not csv_files:
                # 獲取最新文件名用於日誌
                valid_files = [str(f.stem) for f in all_csv_files if len(str(f.stem)) == 8 and str(f.stem).isdigit()]
                latest_file = max(valid_files) if valid_files else 'N/A'
                logger.info(f"沒有新的數據需要更新 (最後日期: {last_date}, 最新文件: {latest_file})")
                return
            logger.info(f"找到 {len(csv_files)} 個需要處理的新CSV文件 (最後日期: {last_date})")
        else:
            csv_files = all_csv_files
            if force_all:
                logger.info(f"強制模式：找到 {len(csv_files)} 個CSV文件，將全部重新合併")
            else:
                logger.info(f"找到 {len(csv_files)} 個CSV文件")
        
        # 讀取並合併所有文件
        all_data = []
        if last_date and not force_all:
            all_data.append(existing_df)  # 如果有現有數據且非強制模式，先加入
            
        for file in csv_files:
            try:
                # 從文件名獲取日期
                date = file.stem
                
                # 讀取CSV文件
                df = pd.read_csv(file, encoding='utf-8-sig')
                
                # 添加日期列
                df['日期'] = date
                
                # 確保證券代號是4位數的字符串
                df['證券代號'] = df['證券代號'].astype(str).str.zfill(4)
                
                all_data.append(df)
                logger.info(f"成功讀取 {file.name}")
                
            except Exception as e:
                logger.error(f"處理文件 {file.name} 時出錯: {str(e)}")
                continue
        
        if not all_data:
            raise ValueError("沒有成功讀取任何數據")
        
        # 合併所有數據
        merged_data = pd.concat(all_data, ignore_index=True)
        
        # 確保日期欄位是字符串格式（YYYYMMDD）
        merged_data['日期'] = merged_data['日期'].astype(str)
        
        # 重新排序列，把日期放在前面
        columns = ['日期', '證券代號', '證券名稱', '成交股數', '成交筆數', '成交金額', 
                  '開盤價', '最高價', '最低價', '收盤價', '漲跌(+/-)', '漲跌價差', 
                  '最後揭示買價', '最後揭示買量', '最後揭示賣價', '最後揭示賣量', '本益比']
        # 只保留存在的欄位
        available_columns = [col for col in columns if col in merged_data.columns]
        merged_data = merged_data[available_columns]
        
        # 按日期和證券代號排序（日期作為字符串排序）
        merged_data = merged_data.sort_values(['日期', '證券代號'])
        
        # 移除重複數據
        merged_data = merged_data.drop_duplicates(subset=['日期', '證券代號'], keep='last')
        
        # 保存合併後的數據
        merged_data.to_csv(output_file, index=False, encoding='utf-8-sig')
        logger.info(f"成功保存合併後的數據到 {output_file}")
        
        # 顯示數據統計
        logger.info(f"合併後的數據形狀: {merged_data.shape}")
        # 日期範圍（使用字符串排序）
        date_min = merged_data['日期'].min()
        date_max = merged_data['日期'].max()
        logger.info(f"日期範圍: {date_min} 到 {date_max}")
        logger.info(f"總共包含 {merged_data['證券代號'].nunique()} 個不同的證券代號")
        
    except Exception as e:
        import traceback
        error_msg = f"處理過程中出錯: {str(e)}"
        logger.error(error_msg)
        logger.error(traceback.format_exc())
        # 如果發生錯誤，嘗試恢復備份
        if 'backup_file' in locals() and 'output_file' in locals() and backup_file.exists() and output_file.exists():
            try:
                shutil.copy2(backup_file, output_file)
                logger.info("已恢復備份文件")
            except Exception as restore_error:
                logger.error(f"恢復備份文件時出錯: {str(restore_error)}")
        # 重新拋出異常，讓調用者知道出錯了
        raise

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='合併每日股票數據')
    parser.add_argument('--force-all', action='store_true', 
                       help='強制重新合併所有數據，忽略現有數據')
    args = parser.parse_args()
    
    merge_daily_data(force_all=args.force_all) 