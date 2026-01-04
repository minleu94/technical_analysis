#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
批量處理股票技術指標腳本
基於02_technical_calculator.md中的功能
"""

import os
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

# 將項目根目錄添加到系統路徑
root_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root_dir))

# 現在導入其他模組
import argparse
import shutil
from datetime import datetime, timedelta
from typing import Optional
import logging
import traceback
import time

try:
    import pandas as pd
except ImportError as e:
    print(f"錯誤：無法導入 pandas 模組")
    print(f"請確認已安裝 pandas: pip install pandas")
    print(f"Python 路徑: {sys.executable}")
    sys.exit(1)

try:
    from tqdm import tqdm
except ImportError:
    # 如果沒有 tqdm，使用簡單的進度顯示
    def tqdm(iterable, desc=None, total=None):
        if desc:
            print(desc)
        return iterable

# 導入自定義模塊
from data_module.config import TWStockConfig
from analysis_module.technical_analysis.technical_indicators import TechnicalIndicatorCalculator


def setup_logging(verbose=False):
    """設置日誌記錄"""
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.INFO)
    
    # 清除現有的處理器
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
    
    # 確保日誌目錄存在
    log_dir = Path("D:/Min/Python/Project/FA_Data/logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    
    # 檔案處理器 - 記錄所有日誌
    log_file = log_dir / f"tech_indicators_{datetime.now().strftime('%Y%m%d')}.log"
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setFormatter(
        logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    )
    
    # 控制台處理器 - 根據verbose參數設置級別
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(
        logging.Formatter('%(levelname)s: %(message)s')
    )
    if verbose:
        console_handler.setLevel(logging.INFO)  # 詳細模式顯示所有INFO及以上日誌
    else:
        console_handler.setLevel(logging.WARNING)  # 普通模式只顯示警告及以上
    
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    return logger


def parse_args():
    """解析命令行參數"""
    parser = argparse.ArgumentParser(description='計算股票技術指標')
    parser.add_argument('--stock', type=str, help='要處理的股票代號，如不指定則處理所有股票')
    parser.add_argument('--output', type=str, help='輸出目錄路徑，如不指定則使用默認路徑')
    parser.add_argument('--check', action='store_true', help='僅檢查，不更新數據')
    parser.add_argument('--start-date', type=str, help='指定開始更新的日期 (YYYY-MM-DD)，默認自動檢測')
    parser.add_argument('--force-all', action='store_true', help='強制更新所有數據，忽略日期檢查')
    parser.add_argument('--ignore-existing', action='store_true', help='忽略現有指標文件，直接覆蓋（用於修復有問題的文件）')
    parser.add_argument('--verbose', action='store_true', help='詳細模式，顯示更多信息')
    return parser.parse_args()


def validate_config(config: TWStockConfig, logger: logging.Logger) -> bool:
    """驗證配置是否正確
    
    Args:
        config: 配置對象
        logger: 日誌記錄器
        
    Returns:
        bool: 配置是否有效
    """
    try:
        # 檢查必要的目錄
        required_dirs = [
            config.data_dir,
            config.technical_dir,
            config.meta_data_dir,
            config.backup_dir
        ]
        
        for dir_path in required_dirs:
            if not dir_path.exists():
                dir_path.mkdir(parents=True, exist_ok=True)
                logger.info(f"創建目錄: {dir_path}")
                # 直接顯示到控制台
                print(f"創建目錄: {dir_path}")
        
        # 檢查必要的文件
        stock_data_file = config.stock_data_file
        if not stock_data_file.exists():
            error_msg = f"股票數據文件不存在: {stock_data_file}"
            logger.error(error_msg)
            print(f"錯誤: {error_msg}")
            return False
        
        print(f"配置驗證成功: 數據目錄 {config.data_dir}")
        print(f"股票數據文件: {stock_data_file}")
        print(f"技術指標輸出目錄: {config.technical_dir}")
            
        return True
    except Exception as e:
        error_msg = f"驗證配置時發生錯誤: {e}"
        logger.error(error_msg)
        logger.error(traceback.format_exc())
        print(f"錯誤: {error_msg}")
        return False


def determine_start_date(config: TWStockConfig, logger: logging.Logger) -> Optional[str]:
    """檢測最新的技術指標日期，用於增量更新
    
    Args:
        config: 配置對象
        logger: 日誌記錄器
        
    Returns:
        Optional[str]: 最新的指標日期，如果找不到現有指標文件則返回 None（表示需要全量更新）
    """
    try:
        # ✅ 優先檢查技術指標目錄下的文件（更可靠）
        tech_files = list(config.technical_dir.glob('*_indicators.csv'))
        
        if tech_files:
            # 從前5個文件中抽樣查找最新日期
            sample_files = tech_files[:5]
            dates = []
            
            for file in sample_files:
                try:
                    df = pd.read_csv(file)
                    if '日期' in df.columns and not df['日期'].empty:
                        date_col = df['日期']
                        # 如果日期列不是字符串類型，轉換為字符串
                        if not pd.api.types.is_string_dtype(date_col):
                            date_col = date_col.astype(str)
                        dates.append(date_col.max())
                except Exception:
                    continue
            
            if dates:
                latest_date = max(dates)
                logger.info(f"從技術指標文件中檢測到最新指標日期: {latest_date}")
                print(f"從技術指標文件中檢測到最新指標日期: {latest_date}")
                return latest_date
        
        # 如果技術指標目錄是空的，檢查整合數據文件（但僅作為參考）
        all_data_file = config.all_stocks_data_file
        if all_data_file.exists() and len(tech_files) == 0:
            logger.warning(f"技術指標目錄為空，但整合指標文件存在: {all_data_file}")
            logger.warning(f"建議使用 --force-all 參數重新生成所有指標文件")
            print(f"警告: 技術指標目錄為空，但整合指標文件存在")
            print(f"建議使用 --force-all 參數重新生成所有指標文件")
            # 如果技術指標目錄是空的，返回 None 表示需要全量更新
            return None
        
        # 如果找不到任何現有指標文件，返回 None（表示需要全量更新）
        if not tech_files:
            logger.info(f"未檢測到現有指標文件，將進行全量更新")
            print(f"未檢測到現有指標文件，將進行全量更新")
            return None
            
        return None
    except Exception as e:
        error_msg = f"檢測起始日期時發生錯誤: {e}"
        logger.error(error_msg)
        logger.error(traceback.format_exc())
        print(f"錯誤: {error_msg}")
        # 發生錯誤時，返回 None 表示需要全量更新
        return None


def process_stock_data_batch(config: TWStockConfig, calculator: TechnicalIndicatorCalculator, 
                             logger: logging.Logger, target_stock: str = None, 
                             check_only: bool = False, start_date: str = None,
                             force_all: bool = False, verbose: bool = False,
                             ignore_existing: bool = False) -> dict:
    """批次處理股票技術指標
    
    Args:
        config: 配置對象
        calculator: 技術指標計算器
        logger: 日誌記錄器
        target_stock: 要處理的特定股票代號，如為None則處理所有股票
        check_only: 是否僅檢查不更新
        start_date: 指定開始更新的日期，如為None則自動檢測
        force_all: 是否強制更新所有數據
        verbose: 是否顯示詳細信息
        ignore_existing: 是否忽略現有指標文件，直接覆蓋（用於修復有問題的文件）
        
    Returns:
        dict: 處理結果統計
    """
    start_time = datetime.now()
    
    # 初始化結果統計
    results = {
        "total_stocks": 0,
        "success_count": 0,
        "fail_count": 0,
        "insufficient_data_count": 0,
        "start_date": "",
        "end_date": "",
        "failed_stocks": [],
        "insufficient_stocks": [],
        "updated_stocks": [],
        "no_new_data_stocks": []
    }
    
    try:
        # 1. 讀取股票數據
        logger.info("讀取股票數據...")
        print("讀取股票數據...")
        stock_data = pd.read_csv(
            config.stock_data_file,
            dtype={'證券代號': str},
            low_memory=False  # 防止混合類型警告
        )
        
        # 2. 只保留正常股票（一般為4位數）
        stock_data = stock_data[stock_data['證券代號'].str.match(r'^\d{4}$')]
        
        # 3. 檢查更新日期範圍
        if not force_all and start_date is None:
            detected_start_date = determine_start_date(config, logger)
            if detected_start_date:
                start_date = detected_start_date
                logger.info(f"檢測到最新指標日期為 {start_date}，將從此日期後開始更新")
                print(f"檢測到最新指標日期為 {start_date}，將從此日期後開始更新")
            else:
                # 如果沒有檢測到現有指標文件，進行全量更新
                start_date = None
                logger.info("未檢測到現有指標文件，將進行全量更新")
                print("未檢測到現有指標文件，將進行全量更新")
        elif force_all:
            start_date = None
            logger.info("強制更新所有數據")
            print("強制更新所有數據")
        elif start_date:
            logger.info(f"指定開始更新日期: {start_date}")
            print(f"指定開始更新日期: {start_date}")
            
        # 如果指定了特定股票，只處理該股票
        if target_stock:
            if target_stock in stock_data['證券代號'].unique():
                stock_data = stock_data[stock_data['證券代號'] == target_stock]
                logger.info(f"僅處理股票: {target_stock}")
                print(f"僅處理股票: {target_stock}")
            else:
                error_msg = f"指定的股票 {target_stock} 不存在於股票數據中"
                logger.error(error_msg)
                print(f"錯誤: {error_msg}")
                results["fail_count"] += 1
                results["failed_stocks"].append(target_stock)
                return results
        
        # 4. 批次處理
        all_data = []
        grouped = stock_data.groupby('證券代號')
        total_stocks = len(grouped)
        results["total_stocks"] = total_stocks
        
        logger.info(f"開始處理 {total_stocks} 支股票的技術指標...")
        print(f"開始處理 {total_stocks} 支股票的技術指標...")
        if check_only:
            logger.info("僅檢查模式，不會更新數據")
            print("僅檢查模式，不會更新數據")
            
        # 記錄全局的日期範圍
        min_date = "9999-12-31"
        max_date = "1900-01-01"
        
        # 使用tqdm的fixed參數確保進度條顯示在固定位置，強制使用正確的文件對象
        with tqdm(total=total_stocks, desc="處理進度", position=0, leave=True, dynamic_ncols=True) as progress_bar:
            for stock_id, group_df in grouped:
                progress_desc = f"處理 {stock_id}".ljust(10)
                progress_bar.set_description(progress_desc)
                
                # 跳過數據量不足的股票
                if len(group_df) < config.min_data_days:
                    if verbose:
                        print(f"股票 {stock_id} 數據量不足 ({len(group_df)} < {config.min_data_days})，跳過")
                    # 將警告信息改為debug級別，避免輸出到控制台
                    logger.debug(f"股票 {stock_id} 數據量不足 ({len(group_df)} < {config.min_data_days})，跳過")
                    results["insufficient_data_count"] += 1
                    results["insufficient_stocks"].append(stock_id)
                    progress_bar.update(1)
                    continue
                
                # 記錄日期範圍
                if '日期' in group_df.columns:
                    group_min_date = group_df['日期'].min()
                    group_max_date = group_df['日期'].max()
                    
                    # 確保日期格式為字符串，方便比較
                    if not isinstance(group_min_date, str):
                        group_min_date = str(group_min_date)
                    if not isinstance(group_max_date, str):
                        group_max_date = str(group_max_date)
                    
                    # 確保min_date和max_date也是字符串
                    if not isinstance(min_date, str):
                        min_date = str(min_date)
                    if not isinstance(max_date, str):
                        max_date = str(max_date)
                    
                    min_date = min(min_date, group_min_date)
                    max_date = max(max_date, group_max_date)
                
                # 檢查是否需要更新（基於日期）
                if start_date and '日期' in group_df.columns and not force_all:
                    # 確保日期格式一致
                    date_col = group_df['日期']
                    # 如果日期列不是字符串類型，轉換為字符串
                    if not pd.api.types.is_string_dtype(date_col):
                        date_col = date_col.astype(str)
                    
                    filtered_df = group_df[date_col > start_date]
                    if len(filtered_df) == 0:
                        if verbose:
                            print(f"股票 {stock_id} 沒有新數據需要更新")
                        logger.debug(f"股票 {stock_id} 沒有新數據需要更新")
                        results["no_new_data_stocks"].append(stock_id)
                        progress_bar.update(1)
                        continue
                    group_df = filtered_df
                
                # 檢查或處理
                if check_only:
                    indicators_file = config.get_technical_file(stock_id)
                    if indicators_file.exists():
                        try:
                            ind_df = pd.read_csv(indicators_file)
                            if verbose:
                                print(f"股票 {stock_id} 指標文件存在，包含 {len(ind_df)} 條記錄")
                            logger.debug(f"股票 {stock_id} 指標文件存在，包含 {len(ind_df)} 條記錄")
                            results["success_count"] += 1
                        except Exception as e:
                            if verbose:
                                print(f"讀取股票 {stock_id} 指標文件時發生錯誤: {e}")
                            logger.debug(f"讀取股票 {stock_id} 指標文件時發生錯誤: {e}")
                            results["fail_count"] += 1
                            results["failed_stocks"].append(stock_id)
                    else:
                        if verbose:
                            print(f"股票 {stock_id} 指標文件不存在")
                        logger.debug(f"股票 {stock_id} 指標文件不存在")
                        results["fail_count"] += 1
                        results["failed_stocks"].append(stock_id)
                else:
                    # 計算並保存指標
                    result = calculator.calculate_and_store_indicators(
                        group_df, 
                        stock_id, 
                        output_dir=config.technical_dir,
                        ignore_existing=ignore_existing or force_all
                    )
                    
                    if isinstance(result, pd.DataFrame):
                        all_data.append(result)
                        results["success_count"] += 1
                        results["updated_stocks"].append(stock_id)
                        # 將成功信息改為debug級別
                        if verbose:
                            print(f"成功處理股票 {stock_id}，獲得 {len(result)} 筆數據")
                        logger.debug(f"成功處理股票 {stock_id}，獲得 {len(result)} 筆數據")
                    else:
                        if verbose:
                            print(f"處理股票 {stock_id} 失敗")
                        logger.debug(f"處理股票 {stock_id} 失敗")
                        results["fail_count"] += 1
                        results["failed_stocks"].append(stock_id)
                
                progress_bar.update(1)
        
        # 更新結果日期範圍
        results["start_date"] = min_date if min_date != "9999-12-31" else "未知"
        results["end_date"] = max_date if max_date != "1900-01-01" else "未知"
        
        # 5. 合併並儲存所有結果（非檢查模式）
        if not check_only and all_data:
            logger.info("合併所有指標數據...")
            print("合併所有指標數據...")
            final_df = pd.concat(all_data, ignore_index=True)
            save_path = config.all_stocks_data_file
            
            # 創建備份
            if save_path.exists():
                logger.info(f"備份現有的整合指標文件: {save_path}")
                print(f"備份現有的整合指標文件: {save_path}")
                config.create_backup(save_path)
            
            # 保存
            final_df.to_csv(save_path, index=False, encoding='utf-8-sig')
            logger.info(f"已保存整合指標到: {save_path}")
            print(f"已保存整合指標到: {save_path}")
            
            # 記錄統計信息
            logger.info(f"總處理筆數: {len(final_df):,}")
            logger.info(f"處理的股票數量: {final_df['證券代號'].nunique():,}")
            print(f"總處理筆數: {len(final_df):,}")
            print(f"處理的股票數量: {final_df['證券代號'].nunique():,}")
        
        return results
        
    except Exception as e:
        error_msg = f"批次處理時發生錯誤: {e}"
        logger.error(error_msg)
        logger.error(traceback.format_exc())
        print(f"錯誤: {error_msg}")
        results["fail_count"] += 1
        return results


def format_summary_report(results: dict, start_time: datetime, logger: logging.Logger):
    """格式化生成處理報告摘要
    
    Args:
        results: 處理結果統計
        start_time: 處理開始時間
        logger: 日誌記錄器
    """
    end_time = datetime.now()
    duration_seconds = (end_time - start_time).total_seconds()
    
    # 格式化時間
    hours, remainder = divmod(duration_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    duration_str = f"{int(hours)}小時{int(minutes)}分{int(seconds)}秒" if hours > 0 else \
                   f"{int(minutes)}分{int(seconds)}秒" if minutes > 0 else \
                   f"{seconds:.2f}秒"
    
    # 生成報告
    report = [
        "===== 技術指標計算報告 =====",
        f"處理時間: {start_time.strftime('%Y-%m-%d %H:%M:%S')} 至 {end_time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"總耗時: {duration_str}",
        f"總處理股票數: {results['total_stocks']}",
        f"成功處理數: {results['success_count']}",
        f"失敗數: {results['fail_count']}",
        f"數據不足股票數: {results['insufficient_data_count']}",
        f"無需更新股票數: {len(results['no_new_data_stocks'])}",
        f"處理數據日期範圍: {results['start_date']} 至 {results['end_date']}",
    ]
    
    # 如果有失敗的股票，列出前10個
    if results['failed_stocks']:
        failed_stocks_str = ", ".join(results['failed_stocks'][:10])
        if len(results['failed_stocks']) > 10:
            failed_stocks_str += f"... (共{len(results['failed_stocks'])}支)"
        report.append(f"失敗股票: {failed_stocks_str}")
    
    # 如果有數據不足的股票，列出前10個
    if results['insufficient_stocks']:
        insufficient_stocks_str = ", ".join(results['insufficient_stocks'][:10])
        if len(results['insufficient_stocks']) > 10:
            insufficient_stocks_str += f"... (共{len(results['insufficient_stocks'])}支)"
        report.append(f"數據不足股票: {insufficient_stocks_str}")
    
    # 如果有成功更新的股票，僅顯示數量
    if results['updated_stocks']:
        report.append(f"成功更新: {len(results['updated_stocks'])}支股票")
    
    report.append("===========================")
    
    # 輸出報告到日誌
    for line in report:
        logger.info(line)
    
    # 同時輸出報告到控制台，確保即使控制台日誌級別較高也能看到摘要
    print("\n".join(report))


def main():
    """主程序"""
    start_time = datetime.now()
    
    # 1. 初始化
    args = parse_args()
    logger = setup_logging(verbose=args.verbose)
    
    try:
        # 顯示開始訊息，確保在控制台可見
        start_msg = "==== 股票技術指標計算開始 ===="
        logger.info(start_msg)
        print(start_msg)
        
        # 2. 加載配置
        config = TWStockConfig()
        
        # 3. 驗證配置
        if not validate_config(config, logger):
            error_msg = "配置驗證失敗，程序終止"
            logger.error(error_msg)
            print(f"錯誤: {error_msg}")
            return False
            
        # 4. 創建技術指標計算器
        calculator = TechnicalIndicatorCalculator(logger)
        
        # 5. 批次處理股票指標
        results = process_stock_data_batch(
            config, 
            calculator, 
            logger,
            target_stock=args.stock,
            check_only=args.check,
            start_date=args.start_date,
            force_all=args.force_all,
            verbose=args.verbose,
            ignore_existing=getattr(args, 'ignore_existing', False)
        )
        
        # 6. 輸出處理報告
        format_summary_report(results, start_time, logger)
        
        # 7. 顯示範例結果 (如果不是檢查模式)
        if not args.check and results["success_count"] > 0:
            try:
                # 嘗試從成功更新的股票中選一個做示例
                example_stock = results["updated_stocks"][0] if results["updated_stocks"] else (args.stock if args.stock else "2330")
                indicators_file = config.get_technical_file(example_stock)
                
                if indicators_file.exists():
                    df = pd.read_csv(indicators_file)
                    example_info = [
                        f"\n{example_stock} 技術指標計算結果範例:",
                        f"總筆數: {len(df)}",
                        f"範例數據 (最後5筆):\n{df.tail().to_string()}"
                    ]
                    for line in example_info:
                        logger.info(line)
                        # 無論是否在詳細模式下都輸出示例數據到控制台
                        print(line)
            except Exception as e:
                logger.error(f"顯示範例結果時發生錯誤: {e}")
                print(f"錯誤: 顯示範例結果時發生錯誤: {e}")
                
        return True
            
    except Exception as e:
        logger.error(f"主程序執行時發生錯誤: {e}")
        logger.error(traceback.format_exc())
        print(f"錯誤: 執行時發生錯誤: {e}")
        return False
    finally:
        # 顯示結束訊息，確保在控制台可見
        end_msg = "==== 股票技術指標計算結束 ===="
        logger.info(end_msg)
        print(end_msg)


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1) 