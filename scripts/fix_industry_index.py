import pandas as pd
import numpy as np
from pathlib import Path
import logging
from datetime import datetime, timedelta
import time
import requests
from tqdm import tqdm
from typing import Optional, List, Dict
import random
import shutil

# 設置日誌
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def _make_request(url: str, max_retries: int = 3) -> Optional[requests.Response]:
    """發送HTTP請求並處理錯誤"""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7',
        'Referer': 'https://www.twse.com.tw/',
        'Connection': 'keep-alive',
        'Cache-Control': 'no-cache',
        'Pragma': 'no-cache'
    }
    
    for attempt in range(max_retries):
        try:
            # 添加隨機延遲
            time.sleep(random.uniform(2, 4))
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            
            # 檢查響應內容
            if response.text.strip() == '':
                logging.warning(f"收到空響應")
                continue
                
            try:
                data = response.json()
                if 'stat' in data and data['stat'] != 'OK':
                    logging.warning(f"API返回錯誤狀態: {data.get('msg', '未知錯誤')}")
                    continue
            except:
                logging.warning(f"響應不是有效的JSON格式")
                continue
                
            return response
        except requests.exceptions.Timeout:
            logging.warning(f"請求超時")
        except requests.exceptions.RequestException as e:
            logging.warning(f"第 {attempt+1} 次請求失敗: {str(e)}")
        except Exception as e:
            logging.warning(f"發生未預期的錯誤: {str(e)}")
            
        if attempt < max_retries - 1:
            wait_time = random.uniform(5, 10)  # 隨機等待5-10秒
            logging.info(f"等待 {wait_time:.1f} 秒後重試...")
            time.sleep(wait_time)
        else:
            logging.error(f"請求失敗，已達到最大重試次數")
            return None

def extract_index_data_for_date(date_str: str) -> Optional[List[Dict]]:
    """擷取特定日期的產業類股指數資料"""
    url = f'https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date={date_str}&type=IND&response=json'
    
    response = _make_request(url)
    if response is None:
        return None

    try:
        data = response.json()
        
        if 'tables' not in data or not data['tables']:
            logging.warning(f"日期 {date_str} 未擷取到任何產業指數")
            return None

        index_data = []
        # 尋找包含產業類指數的表格
        for table in data['tables']:
            if '價格指數' in table.get('title', '') or '報酬指數' in table.get('title', ''):
                for row in table.get('rows', []):
                    if len(row) < 5:
                        continue
                        
                    name = row[0].strip()
                    # 處理包含「類指數」和「類報酬指數」
                    if '類' in name and ('指數' in name or '報酬' in name):
                        try:
                            # 處理數值
                            close_price = float(str(row[1]).replace(',', ''))
                            change = row[2].replace('<p style =\'color:red\'>+</p>', '+').replace('<p style =\'color:green\'>-</p>', '-')
                            change_price = float(str(row[3]).replace(',', '')) if row[3] != '--' else 0.0
                            change_percent = float(str(row[4]).replace(',', '')) if row[4] != '--' else 0.0
                            
                            index_data.append({
                                '指數名稱': name,
                                '收盤指數': close_price,
                                '漲跌': change,
                                '漲跌點數': change_price,
                                '漲跌百分比': change_percent,
                                '日期': datetime.strptime(date_str, '%Y%m%d').strftime('%Y-%m-%d')
                            })
                        except (ValueError, IndexError) as e:
                            logging.warning(f"處理產業指數行資料時發生錯誤: {str(e)}, Row: {row}")
                            continue

        if index_data:
            logging.info(f"日期 {date_str} 成功抓取到 {len(index_data)} 個類股指數")
            logging.info(f"已取得 {len([x for x in index_data if '報酬' in x['指數名稱']])} 個類報酬指數")
            logging.info(f"已取得 {len([x for x in index_data if '報酬' not in x['指數名稱']])} 個類指數")
        return index_data

    except Exception as e:
        logging.error(f"處理 {date_str} 時發生錯誤: {str(e)}")
        return None

def fix_industry_index(default_start_date: str = "2024-11-23"):
    """修復並更新industry_index.csv文件"""
    try:
        # 設定路徑
        base_path = Path("D:/Min/Python/Project/FA_Data")
        meta_data_path = base_path / 'meta_data'
        industry_index_file = meta_data_path / 'industry_index.csv'
        backup_path = meta_data_path / 'backup'

        # 確保目錄存在
        meta_data_path.mkdir(parents=True, exist_ok=True)
        backup_path.mkdir(parents=True, exist_ok=True)

        # 讀取現有數據並創建備份
        existing_df = None
        if industry_index_file.exists():
            # 創建備份
            backup_file = backup_path / f'industry_index_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
            shutil.copy2(industry_index_file, backup_file)
            logging.info(f"已創建備份文件: {backup_file}")
            
            # 讀取現有數據
            existing_df = pd.read_csv(industry_index_file)
            logging.info(f"已讀取現有數據，共 {len(existing_df)} 筆記錄")
            
            if not existing_df.empty:
                # 找到最後更新日期
                last_date = pd.to_datetime(existing_df['日期'].max())
                start_date = last_date + timedelta(days=1)
                logging.info(f"從最後更新日期 {last_date.strftime('%Y-%m-%d')} 的下一天開始更新")
            else:
                start_date = datetime.strptime(default_start_date, "%Y-%m-%d")
                logging.info(f"現有數據為空，從預設起始日期 {default_start_date} 開始更新")
        else:
            start_date = datetime.strptime(default_start_date, "%Y-%m-%d")
            logging.info(f"找不到現有數據文件，從預設起始日期 {default_start_date} 開始更新")

        # 設定結束日期為今天
        end_date = datetime.now()
        
        # 檢查是否需要更新
        if start_date > end_date:
            logging.info("數據已是最新，無需更新")
            return existing_df
        
        # 獲取需要處理的日期清單
        dates_to_process = []
        current_date = start_date
        while current_date <= end_date:
            if current_date.weekday() < 5:  # 只處理週一到週五
                dates_to_process.append(current_date)
            current_date += timedelta(days=1)

        logging.info(f"需要處理 {len(dates_to_process)} 天的數據")

        # 收集數據
        all_data = []
        retry_dates = []  # 用於存儲需要重試的日期
        
        for date in tqdm(dates_to_process, desc="處理產業指數數據進度"):
            date_str = date.strftime('%Y%m%d')
            index_data = extract_index_data_for_date(date_str)
            
            if index_data:
                all_data.extend(index_data)
            else:
                retry_dates.append(date)
            time.sleep(random.uniform(3, 5))  # 隨機等待3-5秒

        # 嘗試重試失敗的日期
        if retry_dates:
            logging.info(f"重試 {len(retry_dates)} 個失敗的日期")
            for date in retry_dates:
                date_str = date.strftime('%Y%m%d')
                index_data = extract_index_data_for_date(date_str)
                if index_data:
                    all_data.extend(index_data)
                time.sleep(random.uniform(5, 8))  # 重試時隨機等待5-8秒

        # 創建DataFrame並處理數據
        if all_data:
            new_df = pd.DataFrame(all_data)
            
            # 確保數值列為浮點數格式
            numeric_columns = ['收盤指數', '漲跌點數', '漲跌百分比']
            for col in numeric_columns:
                new_df[col] = pd.to_numeric(new_df[col], errors='coerce')
                logging.info(f"已將 {col} 轉換為數值型")

            # 移除任何包含NaN的行
            original_len = len(new_df)
            new_df = new_df.dropna()
            if len(new_df) < original_len:
                logging.info(f"已移除 {original_len - len(new_df)} 行含有NaN的數據")

            # 合併新舊數據
            if existing_df is not None:
                df = pd.concat([existing_df, new_df], ignore_index=True)
                df = df.drop_duplicates(subset=['日期', '指數名稱'], keep='last')
            else:
                df = new_df

            # 按日期和指數名稱排序
            df = df.sort_values(['日期', '指數名稱'])

            # 保存數據
            df.to_csv(industry_index_file, index=False, encoding='utf-8-sig')
            logging.info(f"已成功更新industry_index.csv，共 {len(df)} 筆記錄")
            logging.info(f"數據範圍: 從 {df['日期'].min()} 到 {df['日期'].max()}")
            
            # 顯示數據統計信息
            logging.info("\n=== 數據統計 ===")
            logging.info(f"指數數量: {len(df['指數名稱'].unique())}")
            for col in numeric_columns:
                if col in df.columns:
                    min_val = float(df[col].min())
                    max_val = float(df[col].max())
                    logging.info(f"{col}範圍: {min_val:.2f} - {max_val:.2f}")

            return df
        else:
            logging.info("沒有新的數據需要更新")
            return existing_df

    except Exception as e:
        logging.error(f"修復industry_index.csv時發生錯誤: {str(e)}")
        # 如果發生錯誤，嘗試恢復備份
        if 'backup_file' in locals() and backup_file.exists():
            shutil.copy2(backup_file, industry_index_file)
            logging.info("已恢復備份文件")
        raise

if __name__ == "__main__":
    try:
        fix_industry_index()
    except Exception as e:
        logging.error(f"程序執行失敗: {str(e)}") 