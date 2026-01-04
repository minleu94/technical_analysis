import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import os
from pathlib import Path
import requests
import time
from tqdm import tqdm
import logging
import shutil
from typing import Optional, List, Dict
import sys

# 設置日誌
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/market_index_fix.log', encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

class MarketIndexFixer:
    def __init__(self):
        # 使用固定的基礎目錄
        self.base_dir = Path('D:/Min/Python/Project/FA_Data')
        self.meta_data_dir = self.base_dir / 'meta_data'
        self.market_index_file = self.meta_data_dir / 'market_index.csv'
        self.backup_dir = self.meta_data_dir / 'backup'
        
        # 確保所需目錄存在
        self.meta_data_dir.mkdir(parents=True, exist_ok=True)
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"初始化 MarketIndexFixer:")
        logger.info(f"基礎目錄: {self.base_dir}")
        logger.info(f"數據目錄: {self.meta_data_dir}")
        logger.info(f"市場指數文件: {self.market_index_file}")
        logger.info(f"備份目錄: {self.backup_dir}")
    
    def create_backup(self):
        """創建數據文件的備份"""
        if self.market_index_file.exists():
            backup_time = datetime.now().strftime('%Y%m%d_%H%M%S')
            backup_file = self.backup_dir / f"market_index_{backup_time}.csv"
            shutil.copy2(self.market_index_file, backup_file)
            logger.info(f"已創建備份文件: {backup_file}")
    
    def get_index_data(self, start_date: datetime, end_date: datetime) -> Optional[pd.DataFrame]:
        """從證交所下載大盤指數數據"""
        try:
            all_data = []
            current_date = start_date
            
            while current_date <= end_date:
                # 轉換日期格式
                formatted_date = current_date.strftime('%Y%m%d')
                
                # API URL
                url = "https://www.twse.com.tw/rwd/zh/afterTrading/FMTQIK"
                
                # 設置請求參數
                params = {
                    "date": formatted_date,
                    "response": "json"
                }
                
                # 添加請求頭
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
                }
                
                try:
                    # 發送請求
                    response = requests.get(url, params=params, headers=headers)
                    response.raise_for_status()
                    
                    # 解析JSON響應
                    data = response.json()
                    
                    # 檢查響應狀態
                    if data.get("stat") == "OK" and "data" in data and data["data"]:
                        # 解析數據
                        df = pd.DataFrame(data["data"], columns=data["fields"])
                        
                        # 轉換數值欄位
                        numeric_columns = ['成交股數', '成交金額', '成交筆數', '發行量加權股價指數', '漲跌點數']
                        for col in numeric_columns:
                            df[col] = pd.to_numeric(df[col].str.replace(',', ''), errors='coerce')
                        
                        # 轉換日期格式（從民國年到西元年）
                        df['日期'] = df['日期'].apply(lambda x: str(int(x.split('/')[0]) + 1911) + '/' + '/'.join(x.split('/')[1:]))
                        
                        # 重新組織數據格式
                        result_df = pd.DataFrame({
                            '日期': pd.to_datetime(df['日期'], format='%Y/%m/%d').dt.strftime('%Y-%m-%d'),
                            '收盤價': df['發行量加權股價指數'],
                            '開盤價': df['發行量加權股價指數'],  # FMTQIK API 只提供收盤價
                            '最高價': df['發行量加權股價指數'],  # FMTQIK API 只提供收盤價
                            '最低價': df['發行量加權股價指數'],  # FMTQIK API 只提供收盤價
                            '成交量': df['成交股數']
                        })
                        
                        all_data.append(result_df)
                        logger.info(f"成功獲取 {current_date.strftime('%Y-%m-%d')} 的數據")
                    else:
                        logger.warning(f"日期 {formatted_date} 未找到任何有效的市場指數數據")
                        
                except Exception as e:
                    logger.warning(f"獲取 {formatted_date} 的數據時發生錯誤: {str(e)}")
                
                # 移動到下一個月
                current_date = (current_date.replace(day=1) + timedelta(days=32)).replace(day=1)
                time.sleep(3)  # 避免請求過於頻繁
            
            if all_data:
                # 合併所有數據
                final_df = pd.concat(all_data, ignore_index=True)
                
                # 移除重複的數據
                final_df = final_df.drop_duplicates(subset=['日期'], keep='last')
                
                # 檢查成交量異常值
                volume_mean = final_df['成交量'].mean()
                volume_std = final_df['成交量'].std()
                volume_threshold = volume_mean + 3 * volume_std
                
                # 標記異常的成交量
                abnormal_volumes = final_df[final_df['成交量'] > volume_threshold]
                if not abnormal_volumes.empty:
                    logger.warning("檢測到異常成交量:")
                    for _, row in abnormal_volumes.iterrows():
                        logger.warning(f"日期: {row['日期']}, 成交量: {row['成交量']:,.0f}")
                
                return final_df
            
            return None
            
        except Exception as e:
            logger.error(f"獲取指數數據時發生錯誤: {str(e)}", exc_info=True)
            return None
    
    def fix_market_index(self):
        """修復市場指數數據文件"""
        try:
            logger.info("開始修復市場指數數據")
            
            # 讀取現有數據
            existing_df = None
            if self.market_index_file.exists():
                try:
                    # 先創建備份
                    self.create_backup()
                    
                    # 讀取現有數據
                    existing_df = pd.read_csv(self.market_index_file, encoding='utf-8-sig')
                    logger.info(f"已讀取現有數據，共 {len(existing_df)} 筆記錄")
                    logger.info(f"數據欄位: {existing_df.columns.tolist()}")
                    
                    if not existing_df.empty:
                        # 統一日期格式（使用更靈活的解析）
                        existing_df['日期'] = pd.to_datetime(existing_df['日期'], format='mixed').dt.strftime('%Y-%m-%d')
                        # 找到最後更新日期
                        last_date = pd.to_datetime(existing_df['日期'].max())
                        logger.info(f"現有數據最後更新日期: {last_date.strftime('%Y-%m-%d')}")
                        
                        # 設定更新範圍為最近一個月
                        today = datetime.today()
                        start_date = (today - timedelta(days=30)).replace(day=1)
                        logger.info(f"將更新從 {start_date.strftime('%Y-%m-%d')} 到 {today.strftime('%Y-%m-%d')} 的數據")
                        
                        # 獲取新數據
                        new_df = self.get_index_data(start_date, today)
                        
                        if new_df is not None and not new_df.empty:
                            # 移除現有數據中這段時間的記錄
                            existing_df = existing_df[pd.to_datetime(existing_df['日期']) < start_date]
                            
                            # 合併數據
                            df = pd.concat([existing_df, new_df], ignore_index=True)
                            df = df.drop_duplicates(subset=['日期'], keep='last')
                            
                            # 排序
                            df = df.sort_values('日期')
                            
                            # 檢查並移除未來日期
                            today_str = today.strftime('%Y-%m-%d')
                            df = df[df['日期'] <= today_str]
                            
                            # 保存前再次備份
                            backup_time = datetime.now().strftime('%Y%m%d_%H%M%S')
                            backup_file = self.backup_dir / f"market_index_before_save_{backup_time}.csv"
                            existing_df.to_csv(backup_file, index=False, encoding='utf-8-sig')
                            logger.info(f"已創建更新前的備份文件: {backup_file}")
                            
                            # 保存
                            df.to_csv(self.market_index_file, index=False, encoding='utf-8-sig')
                            
                            # 輸出統計信息
                            logger.info(f"已成功更新market_index.csv，共 {len(df)} 筆記錄")
                            logger.info(f"數據範圍: 從 {df['日期'].min()} 到 {df['日期'].max()}")
                        else:
                            logger.info("沒有新的市場指數數據需要處理")
                    
                except Exception as e:
                    logger.error(f"處理數據時發生錯誤: {str(e)}", exc_info=True)
                    return
            else:
                logger.error("找不到市場指數文件，請確保文件存在")
                return
            
        except Exception as e:
            logger.error(f"修復market_index.csv時發生錯誤: {str(e)}", exc_info=True)

def main():
    fixer = MarketIndexFixer()
    fixer.fix_market_index()

if __name__ == "__main__":
    main() 