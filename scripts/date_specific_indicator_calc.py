#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
日期範圍技術指標計算腳本
為特定日期範圍計算技術指標
"""

import os
import sys
from pathlib import Path
import pandas as pd
import numpy as np
import logging
import traceback
import argparse
from datetime import datetime, timedelta
from tqdm import tqdm

# 將項目根目錄添加到系統路徑
root_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root_dir))

# 導入自定義模塊
from data_module.config import TWStockConfig
from analysis_module.technical_analysis.technical_indicators import TechnicalIndicatorCalculator


def parse_args():
    """解析命令行參數"""
    parser = argparse.ArgumentParser(description='特定日期範圍技術指標計算')
    parser.add_argument('--stock', type=str, help='要處理的股票代號，如不指定則處理所有股票')
    parser.add_argument('--start-date', type=str, default=None, help='開始日期 (YYYY-MM-DD)')
    parser.add_argument('--end-date', type=str, default=None, help='結束日期 (YYYY-MM-DD)')
    parser.add_argument('--days', type=int, default=30, help='如果未指定開始日期，處理最近N天的數據')
    parser.add_argument('--force', action='store_true', help='強制重新計算，即使指標文件已存在')
    return parser.parse_args()


def process_stock_with_date_range(stock_id, start_date=None, end_date=None, days=30, force=False):
    """處理特定日期範圍的股票技術指標"""
    print(f"===== 開始處理股票 {stock_id} 的技術指標 =====")
    start_time = datetime.now()
    
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
        df = pd.read_csv(stock_data_file, dtype={'證券代號': str}, low_memory=False)
        
        # 過濾特定股票
        df = df[df['證券代號'] == stock_id]
        
        if len(df) == 0:
            print(f"錯誤: 找不到股票 {stock_id} 的數據")
            return False
            
        # 4. 日期處理
        # 確保日期列為日期格式
        if '日期' in df.columns:
            if not pd.api.types.is_datetime64_any_dtype(df['日期']):
                # 嘗試不同的日期格式
                try:
                    df['日期'] = pd.to_datetime(df['日期'], format='%Y%m%d')
                except:
                    try:
                        df['日期'] = pd.to_datetime(df['日期'])
                    except:
                        print("警告: 無法將日期列轉換為日期格式，將使用所有數據")
        
        # 日期過濾
        if '日期' in df.columns and pd.api.types.is_datetime64_any_dtype(df['日期']):
            # 處理開始日期
            if start_date:
                try:
                    start_date = pd.to_datetime(start_date)
                    df = df[df['日期'] >= start_date]
                    print(f"過濾開始日期: {start_date.strftime('%Y-%m-%d')}")
                except:
                    print(f"警告: 無法解析開始日期 {start_date}，將忽略")
            elif days:
                # 如果沒有指定開始日期，使用最近N天
                latest_date = df['日期'].max()
                start_date = latest_date - timedelta(days=days)
                df = df[df['日期'] >= start_date]
                print(f"處理最近 {days} 天的數據: {start_date.strftime('%Y-%m-%d')} 至 {latest_date.strftime('%Y-%m-%d')}")
            
            # 處理結束日期
            if end_date:
                try:
                    end_date = pd.to_datetime(end_date)
                    df = df[df['日期'] <= end_date]
                    print(f"過濾結束日期: {end_date.strftime('%Y-%m-%d')}")
                except:
                    print(f"警告: 無法解析結束日期 {end_date}，將忽略")
        
        print(f"成功載入 {len(df)} 筆 {stock_id} 在選定日期範圍的數據")
        
        if len(df) == 0:
            print(f"錯誤: 在指定日期範圍內沒有股票 {stock_id} 的數據")
            return False
            
        # 5. 檢查是否需要重新計算
        output_file = technical_dir / f"{stock_id}_indicators.csv"
        if not force and output_file.exists():
            # 讀取現有指標文件
            try:
                ind_df = pd.read_csv(output_file)
                
                # 檢查是否已包含所有需要的日期
                if '日期' in ind_df.columns and '日期' in df.columns:
                    # 確保日期格式一致
                    if not pd.api.types.is_datetime64_any_dtype(ind_df['日期']):
                        try:
                            ind_df['日期'] = pd.to_datetime(ind_df['日期'])
                        except:
                            pass
                    
                    # 檢查缺失的日期
                    df_dates = set(df['日期'].dt.strftime('%Y-%m-%d'))
                    ind_dates = set(ind_df['日期'].dt.strftime('%Y-%m-%d'))
                    missing_dates = df_dates - ind_dates
                    
                    if not missing_dates:
                        print(f"股票 {stock_id} 的指標文件已包含所需日期範圍的數據")
                        print(f"現有指標文件: {output_file}")
                        print(f"總記錄數: {len(ind_df)}")
                        print(f"日期範圍: {ind_df['日期'].min().strftime('%Y-%m-%d')} 至 {ind_df['日期'].max().strftime('%Y-%m-%d')}")
                        
                        # 顯示最近的記錄
                        print("\n最近5筆技術指標數據:")
                        recent_data = ind_df.sort_values('日期', ascending=False).head(5)
                        for _, row in recent_data.iterrows():
                            date_str = row['日期'].strftime('%Y-%m-%d')
                            print(f"日期: {date_str}, 收盤價: {row.get('收盤價', 'N/A')}, RSI: {row.get('RSI', 'N/A'):.2f}, MACD: {row.get('MACD', 'N/A'):.2f}")
                        
                        return True
                    else:
                        print(f"股票 {stock_id} 的指標文件缺少 {len(missing_dates)} 天的數據，將重新計算")
                        # 只處理缺失的日期數據
                        missing_dates_list = list(missing_dates)
                        df = df[df['日期'].dt.strftime('%Y-%m-%d').isin(missing_dates_list)]
                        print(f"處理 {len(df)} 筆缺失日期的數據")
            except Exception as e:
                print(f"讀取現有指標文件時出錯: {e}")
                print("將重新計算所有指標")
        
        # 6. 計算技術指標
        if len(df) > 0:
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
            
            # 7. 合併與保存結果
            if output_file.exists() and not force:
                print(f"步驟3: 合併現有指標和新計算結果")
                try:
                    # 讀取現有指標
                    existing_df = pd.read_csv(output_file)
                    
                    # 確保日期格式一致
                    for df_temp in [existing_df, result_df]:
                        if '日期' in df_temp.columns and not pd.api.types.is_datetime64_any_dtype(df_temp['日期']):
                            try:
                                df_temp['日期'] = pd.to_datetime(df_temp['日期'])
                            except:
                                pass
                    
                    # 將日期轉換為字符串，便於合併
                    if '日期' in existing_df.columns and pd.api.types.is_datetime64_any_dtype(existing_df['日期']):
                        existing_df['日期'] = existing_df['日期'].dt.strftime('%Y-%m-%d')
                    
                    if '日期' in result_df.columns and pd.api.types.is_datetime64_any_dtype(result_df['日期']):
                        result_df['日期'] = result_df['日期'].dt.strftime('%Y-%m-%d')
                    
                    # 合併，如果有重複日期，使用新計算的結果
                    combined_df = pd.concat([existing_df, result_df])
                    combined_df = combined_df.drop_duplicates(subset=['日期'], keep='last')
                    combined_df = combined_df.sort_values('日期')
                    
                    # 保存合併結果
                    print(f"保存合併結果，共 {len(combined_df)} 筆記錄")
                    combined_df.to_csv(output_file, index=False, encoding='utf-8-sig')
                    result_df = combined_df  # 更新結果DataFrame以顯示
                    
                except Exception as e:
                    print(f"合併指標時出錯: {e}")
                    print("將只保存新計算的指標")
                    # 確保目錄存在
                    os.makedirs(os.path.dirname(output_file), exist_ok=True)
                    result_df.to_csv(output_file, index=False, encoding='utf-8-sig')
            else:
                # 直接保存新計算的結果
                print(f"步驟3: 保存結果到 {output_file}")
                os.makedirs(os.path.dirname(output_file), exist_ok=True)
                result_df.to_csv(output_file, index=False, encoding='utf-8-sig')
            
            # 8. 顯示結果範例
            print("\n計算結果範例 (最後5筆):")
            if '日期' in result_df.columns:
                result_df = result_df.sort_values('日期', ascending=False)
            print(result_df.head(5).to_string())
            
            print(f"\n成功處理並保存 {stock_id} 的技術指標!")
            return True
        else:
            print("沒有需要處理的數據")
            return True
        
    except Exception as e:
        print(f"處理時發生錯誤: {e}")
        traceback.print_exc()
        return False
    finally:
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        print(f"===== 處理完成 =====")
        print(f"處理時間: {duration:.2f} 秒")


def process_all_stocks(start_date=None, end_date=None, days=30, force=False):
    """處理所有股票的技術指標"""
    # 1. 創建配置
    config = TWStockConfig(base_dir=Path("D:/Min/Python/Project/FA_Data"))
    
    # 2. 讀取股票數據
    print("讀取所有股票數據...")
    try:
        df = pd.read_csv(config.stock_data_file, dtype={'證券代號': str}, low_memory=False)
        # 只處理標準股票代碼
        df = df[df['證券代號'].str.match(r'^\d{4}$')]
        stock_ids = df['證券代號'].unique()
        print(f"共發現 {len(stock_ids)} 支股票")
        
        # 3. 批量處理
        success_count = 0
        fail_count = 0
        
        with tqdm(total=len(stock_ids), desc="處理進度") as progress_bar:
            for stock_id in stock_ids:
                print(f"\n處理股票 {stock_id}")
                if process_stock_with_date_range(stock_id, start_date, end_date, days, force):
                    success_count += 1
                else:
                    fail_count += 1
                progress_bar.update(1)
        
        # 4. 顯示總結
        print("\n===== 處理總結 =====")
        print(f"總處理股票數: {len(stock_ids)}")
        print(f"成功處理數: {success_count}")
        print(f"失敗數: {fail_count}")
        print("===================")
        
        return success_count > 0
        
    except Exception as e:
        print(f"處理所有股票時發生錯誤: {e}")
        traceback.print_exc()
        return False


def main():
    """主程序"""
    args = parse_args()
    
    print("===== 特定日期範圍技術指標計算 =====")
    start_time = datetime.now()
    
    success = False
    if args.stock:
        # 處理單一股票
        success = process_stock_with_date_range(
            args.stock, 
            args.start_date, 
            args.end_date, 
            args.days,
            args.force
        )
    else:
        # 處理所有股票
        success = process_all_stocks(
            args.start_date,
            args.end_date,
            args.days,
            args.force
        )
    
    end_time = datetime.now()
    total_duration = (end_time - start_time).total_seconds()
    
    print("\n===== 全部處理完成 =====")
    print(f"總處理時間: {total_duration:.2f} 秒")
    print(f"結果: {'成功' if success else '失敗'}")
    
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main()) 