from pathlib import Path
from typing import Optional, Dict, List, Union
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
import requests
import json
import logging
import re
import time
import random
import yfinance as yf

from .config import TWStockConfig

class MarketDateRange:
    """市場數據日期範圍控制"""
    def __init__(self, start_date: str = None, end_date: str = None):
        self.end_date = end_date if end_date else datetime.today().strftime('%Y-%m-%d')
        self.start_date = start_date if start_date else self._get_default_start_date()
        
        # 確保日期範圍有效
        end_dt = datetime.strptime(self.end_date, '%Y-%m-%d')
        start_dt = datetime.strptime(self.start_date, '%Y-%m-%d')
        if start_dt > end_dt:
            self.start_date, self.end_date = self.end_date, self.start_date
            
        # 確保日期不超過今天
        today = datetime.now().strftime('%Y-%m-%d')
        if self.end_date > today:
            self.end_date = today
        if self.start_date > today:
            self.start_date = today
    
    @staticmethod
    def _get_default_start_date() -> str:
        """獲取預設起始日期（前一個月）"""
        return (datetime.today() - timedelta(days=30)).strftime('%Y-%m-%d')
    
    @classmethod
    def last_n_days(cls, n: int) -> 'MarketDateRange':
        """創建最近 n 天的日期範圍"""
        end_date = datetime.today()
        start_date = end_date - timedelta(days=n)
        return cls(
            start_date=start_date.strftime('%Y-%m-%d'),
            end_date=end_date.strftime('%Y-%m-%d')
        )
    
    @classmethod
    def last_month(cls) -> 'MarketDateRange':
        """創建最近一個月的日期範圍"""
        return cls.last_n_days(30)
    
    @classmethod
    def last_quarter(cls) -> 'MarketDateRange':
        """創建最近一季的日期範圍"""
        return cls.last_n_days(90)
    
    @classmethod
    def last_year(cls) -> 'MarketDateRange':
        """創建最近一年的日期範圍"""
        return cls.last_n_days(365)
    
    @classmethod
    def year_to_date(cls) -> 'MarketDateRange':
        """創建今年至今的日期範圍"""
        return cls(
            start_date=datetime.today().replace(month=1, day=1).strftime('%Y-%m-%d')
        )
    
    @property
    def date_range_str(self) -> str:
        """返回日期範圍的字符串表示"""
        return f"從 {self.start_date or '最早'} 到 {self.end_date}"
    
    def get_date_list(self) -> List[datetime]:
        """獲取日期範圍內的所有日期"""
        start = datetime.strptime(self.start_date, '%Y-%m-%d')
        end = datetime.strptime(self.end_date, '%Y-%m-%d')
        
        # 確保開始日期不晚於結束日期
        if start > end:
            start, end = end, start
            
        return [start + timedelta(days=x) for x in range((end-start).days + 1)]

class DataLoader:
    """數據加載器，負責從各種來源加載股票數據"""
    
    def __init__(self, config: TWStockConfig):
        self.config = config
        self._setup_logging()
        
    def _setup_logging(self):
        """設置日誌"""
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.INFO)
        
        # 清除現有的處理器
        for handler in self.logger.handlers[:]:
            self.logger.removeHandler(handler)
        
        # 創建文件處理器
        file_handler = logging.FileHandler(
            self.config.log_dir / "data_loader.log",
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
        self.logger.addHandler(file_handler)
        self.logger.addHandler(console_handler)
    
    def load_daily_price(self, date: str) -> Optional[pd.DataFrame]:
        """加載指定日期的價格數據"""
        try:
            file_path = self.config.get_daily_price_file(date)
            if not file_path.exists():
                self.logger.warning(f"找不到日期 {date} 的價格數據文件")
                return None
                
            df = pd.read_csv(file_path)
            self.logger.info(f"成功加載日期 {date} 的價格數據")
            return df
            
        except Exception as e:
            self.logger.error(f"加載日期 {date} 的價格數據時發生錯誤: {str(e)}")
            return None
    
    def load_stock_data(self) -> Optional[pd.DataFrame]:
        """加載股票基本資料"""
        try:
            if not self.config.stock_data_file.exists():
                self.logger.warning("找不到股票基本資料文件")
                return None
                
            df = pd.read_csv(self.config.stock_data_file)
            self.logger.info("成功加載股票基本資料")
            return df
            
        except Exception as e:
            self.logger.error(f"加載股票基本資料時發生錯誤: {str(e)}")
            return None
    
    def load_market_index(self) -> Optional[pd.DataFrame]:
        """加載市場指數數據"""
        try:
            if not self.config.market_index_file.exists():
                self.logger.warning("找不到市場指數數據文件")
                return None
                
            df = pd.read_csv(self.config.market_index_file, encoding='utf-8-sig')
            if not df.empty:
                last_date = pd.to_datetime(df['日期'].max())
                self.logger.info(f"成功加載市場指數數據，最後更新日期: {last_date.strftime('%Y-%m-%d')}")
            else:
                self.logger.warning("市場指數數據文件為空")
            return df
            
        except Exception as e:
            self.logger.error(f"加載市場指數數據時發生錯誤: {str(e)}")
            return None
    
    def load_industry_index(self) -> Optional[pd.DataFrame]:
        """加載產業指數數據"""
        try:
            if not self.config.industry_index_file.exists():
                self.logger.warning("找不到產業指數數據文件")
                return None
                
            df = pd.read_csv(self.config.industry_index_file, encoding='utf-8-sig')
            if not df.empty:
                last_date = pd.to_datetime(df['日期'].max())
                self.logger.info(f"成功加載產業指數數據，最後更新日期: {last_date.strftime('%Y-%m-%d')}")
            else:
                self.logger.warning("產業指數數據文件為空")
            return df
            
        except Exception as e:
            self.logger.error(f"加載產業指數數據時發生錯誤: {str(e)}")
            return None
    
    def load_all_stocks_data(self) -> Optional[pd.DataFrame]:
        """加載整合性股票數據"""
        try:
            if not self.config.all_stocks_data_file.exists():
                self.logger.warning("找不到整合性股票數據文件")
                return None
                
            df = pd.read_csv(self.config.all_stocks_data_file)
            self.logger.info("成功加載整合性股票數據")
            return df
            
        except Exception as e:
            self.logger.error(f"加載整合性股票數據時發生錯誤: {str(e)}")
            return None
    
    def save_market_index(self, df: pd.DataFrame):
        """保存市場指數數據"""
        try:
            # 創建備份
            if self.config.market_index_file.exists():
                backup_file = self.config.backup_dir / f'market_index_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
                self.config.create_backup(self.config.market_index_file, backup_file)
                self.logger.info(f"已創建備份文件: {backup_file}")
            
            # 保存新數據
            df.to_csv(self.config.market_index_file, index=False, encoding='utf-8-sig')
            self.logger.info(f"成功保存市場指數數據，共 {len(df)} 筆記錄")
            
        except Exception as e:
            self.logger.error(f"保存市場指數數據時發生錯誤: {str(e)}")
            # 如果有備份，嘗試恢復
            if 'backup_file' in locals() and backup_file.exists():
                self.config.restore_backup(backup_file, self.config.market_index_file)
                self.logger.info("已恢復備份文件")
    
    def save_industry_index(self, data: pd.DataFrame, date: str = None):
        """保存產業指數數據"""
        try:
            if data is None or data.empty:
                self.logger.warning("沒有數據需要保存")
                return
                
            # 如果指定了日期，添加日期列
            if date:
                data['日期'] = date
                
            # 如果文件已存在，創建備份
            if self.config.industry_index_file.exists():
                self.config.create_backup(self.config.industry_index_file)
                
            # 保存數據
            data.to_csv(self.config.industry_index_file, index=False, encoding='utf-8')
            self.logger.info(f"已保存產業指數數據到: {self.config.industry_index_file}")
            
        except Exception as e:
            self.logger.error(f"保存產業指數數據時發生錯誤: {str(e)}")
    
    def save_all_stocks_data(self, df: pd.DataFrame):
        """保存整合性股票數據"""
        try:
            # 創建備份
            self.config.create_backup(self.config.all_stocks_data_file)
            
            # 保存新數據
            df.to_csv(self.config.all_stocks_data_file, index=False)
            self.logger.info("成功保存整合性股票數據")
            
        except Exception as e:
            self.logger.error(f"保存整合性股票數據時發生錯誤: {str(e)}")
    
    def download_from_yahoo(self, stock_id: str, start_date: str, end_date: str) -> Optional[pd.DataFrame]:
        """從Yahoo Finance下載股票數據"""
        try:
            # 添加.TW後綴
            yahoo_id = f"{stock_id}.TW"
            stock = yf.Ticker(yahoo_id)
            
            # 下載數據
            df = stock.history(start=start_date, end=end_date)
            
            if df.empty:
                self.logger.warning(f"無法從Yahoo Finance下載股票 {stock_id} 的數據")
                return None
                
            self.logger.info(f"成功從Yahoo Finance下載股票 {stock_id} 的數據")
            return df
            
        except Exception as e:
            self.logger.error(f"從Yahoo Finance下載股票 {stock_id} 的數據時發生錯誤: {str(e)}")
            return None
    
    def validate_stock_data(self, df: pd.DataFrame) -> bool:
        """驗證股票數據的完整性和正確性"""
        try:
            # 檢查必要的列是否存在
            required_columns = ['證券代號', '證券名稱']
            if not all(col in df.columns for col in required_columns):
                self.logger.error("數據缺少必要的列")
                return False
                
            # 檢查證券代號格式（只保留4位數的代號）
            if not df['證券代號'].str.len().eq(4).all():
                self.logger.error("存在不正確的證券代號格式")
                return False
                
            return True
            
        except Exception as e:
            self.logger.error(f"驗證數據時發生錯誤: {str(e)}")
            return False

    def download_from_api(self, date: str) -> Optional[pd.DataFrame]:
        """從證交所API下載個股交易資料 - 使用與 notebook 相同的邏輯
        
        API: MI_INDEX (type=ALL)
        - 端點: https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX
        - 參數: date (YYYYMMDD), type=ALL, response=json
        - 數據位置: data['tables'][8] (第9個表格)
        
        Args:
            date: 日期字串，格式為 YYYY-MM-DD
            
        Returns:
            DataFrame 包含個股交易資料，如果下載失敗則返回 None
        """
        try:
            # 轉換日期格式為 YYYYMMDD
            date_obj = datetime.strptime(date, '%Y-%m-%d')
            formatted_date = date_obj.strftime('%Y%m%d')
            
            # 使用 Session 維持 cookie（避免 307 重定向問題）
            session = requests.Session()
            
            # 先訪問主頁獲取 cookie（模擬真實瀏覽器行為）
            try:
                session.get("https://www.twse.com.tw/", timeout=self.config.request_timeout)
                self.logger.debug("已訪問主頁獲取 cookie")
            except Exception as e:
                self.logger.warning(f"訪問主頁時發生錯誤（繼續嘗試）: {str(e)}")
            
            # 添加延遲時間（避免請求過快被限制）
            delay_time = random.uniform(1.5, 2.5)  # 隨機延遲 1.5-2.5 秒
            self.logger.debug(f"等待 {delay_time:.1f} 秒後發送請求...")
            time.sleep(delay_time)
            
            # 構建 API URL - 使用 type=ALL（與 notebook 相同）
            url = "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX"
            params = {
                "date": formatted_date,
                "type": "ALL",  # 使用 ALL（與 notebook 和 update_20250828.py 相同）
                "response": "json"
            }
            
            # 添加請求頭（模擬真實瀏覽器）
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'application/json, text/plain, */*',
                'Accept-Language': 'zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7',
                'Referer': 'https://www.twse.com.tw/',
                'Connection': 'keep-alive'
            }
            
            # 發送請求（使用 session 和 headers）
            self.logger.info(f"正在從 MI_INDEX API 獲取 {formatted_date} 的數據...")
            response = session.get(url, params=params, headers=headers, timeout=self.config.request_timeout)
            
            if response.status_code != 200:
                self.logger.warning(f"無法獲取 {formatted_date} 的數據: HTTP {response.status_code}")
                if response.status_code == 307:
                    self.logger.warning("遇到 307 重定向，可能需要使用增強版腳本（支援 Selenium）")
                return None
            
            # 解析 JSON 響應
            data = response.json()
            
            # 檢查響應狀態
            if data.get('stat') != 'OK':
                self.logger.warning(f"API返回錯誤狀態: {data.get('stat')}")
                return None
            
            # 檢查是否有資料表（按照 notebook 的方式，需要至少9個表格）
            if 'tables' not in data or len(data['tables']) < 9:
                self.logger.warning("API響應中沒有足夠的資料表")
                return None
            
            # 取得股票交易資料（第9個table，索引為8，與 notebook 相同）
            stock_data = data['tables'][8]
            
            if not stock_data.get('data'):
                self.logger.warning("股票交易資料為空")
                return None
            
            # 轉換為DataFrame（按照 notebook 的方式）
            df = pd.DataFrame(stock_data['data'], columns=stock_data['fields'])
            
            # 只保留4位數股票代號的資料
            df = df[df['證券代號'].str.len() == 4]
            
            # 處理數值欄位
            numeric_columns = ['成交股數', '成交筆數', '成交金額', '開盤價', '最高價', 
                             '最低價', '收盤價', '漲跌價差', '最後揭示買價', 
                             '最後揭示買量', '最後揭示賣價', '最後揭示賣量', '本益比']
            
            for col in numeric_columns:
                if col in df.columns:
                    # 移除逗號並轉換為數值
                    df[col] = df[col].replace({'--': np.nan, '': np.nan})
                    df[col] = df[col].apply(lambda x: str(x).replace(',', '') if pd.notnull(x) else x)
                    df[col] = pd.to_numeric(df[col], errors='coerce')
            
            # 處理漲跌符號（從 HTML 標籤中提取）
            if '漲跌(+/-)' in df.columns:
                df['漲跌(+/-)'] = df['漲跌(+/-)'].apply(
                    lambda x: '+' if 'color:red' in str(x) else 
                             '-' if 'color:green' in str(x) else ''
                )
            
            # 創建備份
            daily_price_file = self.config.get_daily_price_file(date)
            if daily_price_file.exists():
                backup_file = self.config.backup_dir / f'daily_price_{date}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
                self.config.create_backup(daily_price_file, backup_file)
                self.logger.info(f"已創建備份文件: {backup_file}")
            
            # 保存每日價格數據
            df.to_csv(daily_price_file, index=False, encoding='utf-8-sig')
            self.logger.info(f"成功保存 {date} 的個股交易資料，共 {len(df)} 筆記錄")
            
            return df
            
        except Exception as e:
            self.logger.error(f"下載個股交易資料時發生錯誤: {str(e)}")
            import traceback
            traceback.print_exc()
            # 如果有備份，嘗試恢復
            if 'backup_file' in locals() and backup_file.exists():
                self.config.restore_backup(backup_file, daily_price_file)
                self.logger.info("已恢復備份文件")
            return None

    def _convert_date_format(self, date_str: str, to_api: bool = False) -> str:
        """轉換日期格式
        
        支持的格式：
        - 113/03/29 -> 20250329 或 113/03/29
        - 2024-03-29 -> 20250329 或 113/03/29
        - 20250329 -> 20250329 或 113/03/29
        
        Args:
            date_str: 輸入的日期字符串
            to_api: 是否轉換為API格式（民國年）
        """
        try:
            # 如果已經是 YYYYMMDD 格式
            if re.match(r'^\d{8}$', date_str):
                if to_api:
                    year = int(date_str[:4]) - 1911
                    return f"{year:03d}/{date_str[4:6]}/{date_str[6:]}"
                return date_str
                
            # 如果是 YYYY-MM-DD 格式
            if re.match(r'^\d{4}-\d{2}-\d{2}$', date_str):
                date_obj = datetime.strptime(date_str, '%Y-%m-%d')
                if to_api:
                    year = date_obj.year - 1911
                    return f"{year:03d}/{date_obj.month:02d}/{date_obj.day:02d}"
                return date_obj.strftime('%Y%m%d')
                
            # 如果是 YYY/MM/DD 格式（民國年）
            match = re.match(r'^(\d{3})/(\d{2})/(\d{2})$', date_str)
            if match:
                if to_api:
                    return date_str
                year = int(match.group(1)) + 1911
                return f"{year}{match.group(2)}{match.group(3)}"
                
            raise ValueError(f"不支持的日期格式: {date_str}")
            
        except Exception as e:
            self.logger.error(f"日期格式轉換錯誤: {str(e)}")
            return None

    def _convert_to_datetime(self, date_str: str) -> datetime:
        """將日期字符串轉換為datetime對象"""
        try:
            # 如果是 YYYYMMDD 格式
            if re.match(r'^\d{8}$', date_str):
                return datetime.strptime(date_str, '%Y%m%d')
                
            # 如果是 YYYY-MM-DD 格式
            if re.match(r'^\d{4}-\d{2}-\d{2}$', date_str):
                return datetime.strptime(date_str, '%Y-%m-%d')
                
            # 如果是 YYY/MM/DD 格式（民國年）
            match = re.match(r'^(\d{3})/(\d{2})/(\d{2})$', date_str)
            if match:
                year = int(match.group(1)) + 1911
                return datetime(year, int(match.group(2)), int(match.group(3)))
                
            raise ValueError(f"不支持的日期格式: {date_str}")
            
        except Exception as e:
            self.logger.error(f"日期轉換錯誤: {str(e)}")
            return None

    def get_daily_price_file(self, date: str) -> Path:
        """取得特定日期的價格檔案路徑"""
        date_str = self._convert_date_format(date)
        if not date_str:
            raise ValueError(f"無效的日期格式: {date}")
        return self.config.daily_price_dir / f'{date_str}.csv'

    def get_latest_date(self, file_path: Path, date_column: str = '日期') -> Optional[str]:
        """獲取指定文件的最新日期"""
        if not file_path.exists():
            return None
            
        try:
            df = pd.read_csv(file_path, encoding='utf-8-sig')
            if df.empty or date_column not in df.columns:
                return None
                
            # 轉換日期格式並獲取最大值
            df[date_column] = pd.to_datetime(df[date_column], format='mixed')
            latest_date = df[date_column].max()
            
            return latest_date.strftime('%Y-%m-%d')
        except Exception as e:
            self.logger.error(f"獲取最新日期時發生錯誤: {str(e)}")
            return None

    def update_daily_data(self, date: str) -> bool:
        """更新個股日成交資料 - 使用 download_from_api 方法（推薦）
        
        此方法會調用 download_from_api 來獲取數據，然後保存到 daily_price 目錄。
        這是主模組推薦的更新方式，使用成功驗證的 MI_INDEX API (type=ALL) 邏輯。
        
        Args:
            date: 日期字串，格式為 YYYY-MM-DD
            
        Returns:
            bool: 更新是否成功
        """
        try:
            self.logger.info(f"正在更新 {date} 的個股日成交資料（使用主模組方法）")
            
            # 使用 download_from_api 方法（已包含 delay time 和 Session 處理）
            df = self.download_from_api(date)
            
            if df is None or df.empty:
                self.logger.error(f"無法獲取 {date} 的個股日成交資料")
                return False
            
            self.logger.info(f"成功更新 {date} 的個股日成交資料，共 {len(df)} 筆記錄")
            return True
            
        except Exception as e:
            self.logger.error(f"更新個股日成交資料時發生錯誤: {str(e)}")
            import traceback
            traceback.print_exc()
            return False

    def schedule_daily_update(self):
        """設置定時更新任務"""
        import schedule
        import time
        
        def job():
            self.update_daily_data()
        
        # 設置在每個工作日下午 2 點執行更新（台股收盤後）
        schedule.every().monday.at("14:00").do(job)
        schedule.every().tuesday.at("14:00").do(job)
        schedule.every().wednesday.at("14:00").do(job)
        schedule.every().thursday.at("14:00").do(job)
        schedule.every().friday.at("14:00").do(job)
        
        while True:
            schedule.run_pending()
            time.sleep(60)
    
    def merge_daily_data(self) -> Optional[pd.DataFrame]:
        """合併每日交易數據"""
        try:
            daily_price_dir = self.config.daily_price_dir
            if not daily_price_dir.exists():
                self.logger.error(f"找不到目錄：{daily_price_dir}")
                return None
            
            # 檢查現有的合併文件
            last_date = None
            if self.config.all_stocks_data_file.exists():
                # 創建備份
                backup_file = self.config.backup_dir / f'stock_data_whole_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
                self.config.create_backup(self.config.all_stocks_data_file, backup_file)
                self.logger.info(f"已創建備份文件: {backup_file}")
                
                # 讀取現有數據
                existing_df = pd.read_csv(self.config.all_stocks_data_file, encoding='utf-8-sig', low_memory=False)
                last_date = str(existing_df['日期'].max())
                self.logger.info(f"已讀取現有數據，最後更新日期為: {last_date}")
            
            # 獲取所有CSV文件
            all_csv_files = list(daily_price_dir.glob("*.csv"))
            if not all_csv_files:
                self.logger.error(f"在 {daily_price_dir} 中找不到CSV文件")
                return None
            
            # 如果有最後更新日期，只處理新的文件
            if last_date:
                csv_files = [f for f in all_csv_files if str(f.stem) > last_date]
                if not csv_files:
                    self.logger.info("沒有新的數據需要更新")
                    return existing_df
                self.logger.info(f"找到 {len(csv_files)} 個需要處理的新CSV文件")
            else:
                csv_files = all_csv_files
                self.logger.info(f"找到 {len(csv_files)} 個CSV文件")
            
            # 讀取並合併所有文件
            all_data = []
            if last_date:
                all_data.append(existing_df)
                
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
                    self.logger.info(f"成功讀取 {file.name}")
                    
                except Exception as e:
                    self.logger.error(f"處理文件 {file.name} 時出錯: {str(e)}")
                    continue
            
            if not all_data:
                raise ValueError("沒有成功讀取任何數據")
            
            # 合併所有數據
            merged_data = pd.concat(all_data, ignore_index=True)
            
            # 重新排序列，把日期放在前面
            columns = ['日期', '證券代號', '證券名稱', '成交股數', '成交筆數', '成交金額', 
                      '開盤價', '最高價', '最低價', '收盤價', '漲跌(+/-)', '漲跌價差', 
                      '最後揭示買價', '最後揭示買量', '最後揭示賣價', '最後揭示賣量', '本益比']
            merged_data = merged_data[columns]
            
            # 按日期和證券代號排序
            merged_data = merged_data.sort_values(['日期', '證券代號'])
            
            # 移除重複數據
            merged_data = merged_data.drop_duplicates(subset=['日期', '證券代號'], keep='last')
            
            # 保存合併後的數據
            merged_data.to_csv(self.config.all_stocks_data_file, index=False, encoding='utf-8-sig')
            self.logger.info(f"成功保存合併後的數據到 {self.config.all_stocks_data_file}")
            
            # 顯示數據統計
            self.logger.info(f"合併後的數據形狀: {merged_data.shape}")
            self.logger.info(f"日期範圍: {merged_data['日期'].min()} 到 {merged_data['日期'].max()}")
            self.logger.info(f"總共包含 {merged_data['證券代號'].nunique()} 個不同的證券代號")
            
            return merged_data
            
        except Exception as e:
            self.logger.error(f"合併每日交易數據時發生錯誤: {str(e)}")
            # 如果有備份，嘗試恢復
            if 'backup_file' in locals() and backup_file.exists():
                self.config.restore_backup(backup_file, self.config.all_stocks_data_file)
                self.logger.info("已恢復備份文件")
            return None

    def update_industry_index(self, date: str) -> bool:
        """更新產業指數資料
        
        Args:
            date: 日期字串，格式為 YYYY-MM-DD
            
        Returns:
            bool: 更新是否成功
        """
        try:
            self.logger.info(f"正在更新 {date} 的產業指數資料")
            
            # 轉換日期格式
            date_obj = datetime.strptime(date, '%Y-%m-%d')
            formatted_date = date_obj.strftime('%Y%m%d')
            
            # 從證交所API獲取數據
            url = "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX"
            params = {
                "date": formatted_date,
                "type": "IND",
                "response": "json"
            }
            
            response = self._make_request(url, params)
            if response is None:
                self.logger.error(f"無法獲取 {date} 的產業指數數據")
                return False
                
            # 解析JSON響應
            try:
                data = response.json()
            except Exception as e:
                self.logger.error(f"解析JSON響應時發生錯誤: {str(e)}")
                return False
                
            # 檢查響應狀態
            if data.get("stat") != "OK" or "tables" not in data or not data["tables"]:
                self.logger.warning(f"API返回無效數據: {data.get('stat', '未知狀態')}")
                return False
                
            # 處理數據
            try:
                index_data = []
                
                # 尋找包含產業類指數的表格（參考 fix_industry_index.py 的邏輯）
                for table in data["tables"]:
                    table_title = table.get('title', '')
                    # 使用 rows 而不是 data（參考 fix_industry_index.py）
                    rows = table.get('rows', table.get('data', []))
                    
                    if '價格指數' in table_title or '報酬指數' in table_title or '類股指數' in table_title:
                        for row in rows:
                            if len(row) < 5:  # 確保至少有5個欄位
                                continue
                                
                            try:
                                # 處理指數名稱
                                name = str(row[0]).strip()
                                # 只處理包含「類」的指數
                                if '類' not in name:
                                    continue
                                
                                # 處理數值（參考 fix_industry_index.py 的邏輯）
                                try:
                                    close_price = float(str(row[1]).replace(',', '')) if row[1] != '--' else None
                                except:
                                    close_price = None
                                
                                # 處理漲跌符號（可能包含 HTML）
                                change = str(row[2]) if len(row) > 2 else '+'
                                change = change.replace('<p style =\'color:red\'>+</p>', '+')
                                change = change.replace('<p style =\'color:green\'>-</p>', '-')
                                change = change.replace('+', '+').replace('-', '-')
                                # 提取符號
                                if '+' in change or (isinstance(change, str) and change.strip() == '+'):
                                    change_direction = '+'
                                elif '-' in change or (isinstance(change, str) and change.strip() == '-'):
                                    change_direction = '-'
                                else:
                                    change_direction = '+'  # 預設
                                
                                # 處理漲跌點數
                                try:
                                    change_price = float(str(row[3]).replace(',', '')) if len(row) > 3 and row[3] != '--' else 0.0
                                except:
                                    change_price = 0.0
                                
                                # 處理漲跌百分比
                                try:
                                    change_percent = float(str(row[4]).replace(',', '')) if len(row) > 4 and row[4] != '--' else None
                                except:
                                    change_percent = None
                                
                                # 創建字典（匹配現有文件格式）
                                # 現有文件欄位：['指數名稱', '收盤指數', '漲跌', '漲跌點數', '漲跌百分比', '日期']
                                data_dict = {
                                    '指數名稱': name,
                                    '收盤指數': close_price,
                                    '漲跌': change_direction,
                                    '漲跌點數': abs(change_price) if change_price else 0.0,
                                    '漲跌百分比': change_percent,
                                    '日期': date
                                }
                                
                                index_data.append(data_dict)
                            except Exception as e:
                                self.logger.warning(f"處理產業指數行時發生錯誤: {str(e)}, Row: {row}")
                                continue
                
                if not index_data:
                    self.logger.warning(f"未找到 {date} 的有效產業指數數據")
                    return False
                
                # 創建DataFrame
                result_df = pd.DataFrame(index_data)
                
                # 檢查現有數據
                if self.config.industry_index_file.exists():
                    existing_df = pd.read_csv(self.config.industry_index_file, encoding='utf-8-sig')
                    
                    # 檢查新數據是否包含所有指數（避免部分指數數據丟失）
                    new_indices = set(result_df['指數名稱'].unique())
                    existing_indices = set(existing_df['指數名稱'].unique())
                    
                    # 如果新數據缺少某些指數，記錄警告但不刪除（保留舊數據）
                    missing_indices = existing_indices - new_indices
                    if missing_indices:
                        self.logger.warning(f"新數據缺少 {len(missing_indices)} 個指數的數據，將保留這些指數的舊數據")
                        # 保留缺失指數的當天數據
                        missing_data = existing_df[
                            (existing_df['日期'] == date) & 
                            (existing_df['指數名稱'].isin(missing_indices))
                        ]
                        if len(missing_data) > 0:
                            result_df = pd.concat([result_df, missing_data], ignore_index=True)
                    
                    # 創建備份
                    self.config.create_backup(self.config.industry_index_file)
                    
                    # 從現有數據中刪除當天的數據（只刪除新數據中存在的指數）
                    indices_to_update = set(result_df['指數名稱'].unique())
                    existing_df = existing_df[
                        ~((existing_df['日期'] == date) & (existing_df['指數名稱'].isin(indices_to_update)))
                    ]
                    
                    # 合併數據
                    result_df = pd.concat([existing_df, result_df], ignore_index=True)
                else:
                    # 如果文件不存在，直接保存新數據
                    result_df.to_csv(self.config.industry_index_file, index=False, encoding='utf-8-sig')
                    self.logger.info(f"成功創建產業指數數據文件，日期: {date}，共 {len(result_df)} 筆記錄")
                    return True
                
                # 保存數據
                result_df.to_csv(self.config.industry_index_file, index=False, encoding='utf-8-sig')
                self.logger.info(f"成功更新產業指數數據，日期: {date}，共 {len(result_df)} 筆記錄")
                return True
                
            except Exception as e:
                self.logger.error(f"處理產業指數數據時發生錯誤: {str(e)}")
                return False
                
        except Exception as e:
            self.logger.error(f"更新產業指數數據時發生未處理的錯誤: {str(e)}")
            return False

    def update_market_index(self, date: str) -> bool:
        """更新特定日期的市場指數數據
        
        Args:
            date: 日期字符串（YYYY-MM-DD格式）
            
        Returns:
            是否成功更新
        """
        try:
            self.logger.info(f"開始更新 {date} 的市場指數數據")
            
            # 檢查是否已有最新數據
            latest_date = self.get_latest_date(self.config.market_index_file)
            if latest_date and latest_date >= date:
                self.logger.info(f"已有 {date} 的市場指數數據，最新日期為 {latest_date}")
                return True
                
            # 將日期轉換為證交所API需要的格式
            date_obj = datetime.strptime(date, '%Y-%m-%d')
            formatted_date = date_obj.strftime('%Y%m%d')
            
            # 從證交所API獲取數據
            url = "https://www.twse.com.tw/rwd/zh/afterTrading/FMTQIK"
            params = {
                "date": formatted_date,
                "response": "json"
            }
            
            response = self._make_request(url, params)
            if response is None:
                self.logger.error(f"無法獲取 {date} 的市場指數數據")
                return False
                
            # 解析JSON響應
            try:
                data = response.json()
            except Exception as e:
                self.logger.error(f"解析JSON響應時發生錯誤: {str(e)}")
                return False
                
            # 檢查響應狀態
            if data.get("stat") != "OK" or "data" not in data or not data["data"]:
                self.logger.warning(f"API返回無效數據: {data.get('stat', '未知狀態')}")
                return False
                
            # 處理數據
            try:
                # 創建DataFrame
                df = pd.DataFrame(data["data"], columns=data["fields"])
                
                # 轉換數值欄位
                numeric_columns = ['成交股數', '成交金額', '成交筆數', '發行量加權股價指數', '漲跌點數']
                for col in numeric_columns:
                    df[col] = pd.to_numeric(df[col].str.replace(',', ''), errors='coerce')
                
                # 轉換日期格式（從民國年到西元年）
                df['日期'] = df['日期'].apply(self._convert_roc_date)
                
                # 重新組織數據格式
                result_df = pd.DataFrame({
                    '日期': pd.to_datetime(df['日期']).dt.strftime('%Y-%m-%d'),
                    '收盤價': df['發行量加權股價指數'],
                    '開盤價': df['發行量加權股價指數'],  # API只提供收盤價
                    '最高價': df['發行量加權股價指數'],  # API只提供收盤價
                    '最低價': df['發行量加權股價指數'],  # API只提供收盤價
                    '成交量': df['成交股數']
                })
                
                # 檢查現有數據
                if self.config.market_index_file.exists():
                    existing_df = pd.read_csv(self.config.market_index_file, encoding='utf-8-sig')
                    
                    # 創建備份
                    self.config.create_backup(self.config.market_index_file)
                    
                    # 合併數據
                    existing_df['日期'] = pd.to_datetime(existing_df['日期'], format='mixed').dt.strftime('%Y-%m-%d')
                    result_df = pd.concat([existing_df, result_df], ignore_index=True)
                    
                    # 刪除重複的日期，保留最新的數據
                    result_df = result_df.drop_duplicates(subset=['日期'], keep='last')
                    
                    # 按日期排序
                    result_df = result_df.sort_values('日期')
                
                # 保存數據
                result_df.to_csv(self.config.market_index_file, index=False, encoding='utf-8-sig')
                self.logger.info(f"成功更新市場指數數據，共 {len(result_df)} 筆記錄")
                return True
                
            except Exception as e:
                self.logger.error(f"處理市場指數數據時發生錯誤: {str(e)}")
                return False
                
        except Exception as e:
            self.logger.error(f"更新市場指數數據時發生未處理的錯誤: {str(e)}")
            return False

    def _make_request(self, url: str, params: Dict = None, retries: int = None) -> Optional[requests.Response]:
        """發送HTTP請求並處理重試邏輯"""
        retries = retries or self.config.max_retries
        for attempt in range(retries):
            try:
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
                }
                response = requests.get(
                    url, 
                    params=params, 
                    headers=headers,
                    timeout=self.config.request_timeout
                )
                if response.status_code == 200:
                    return response
                elif response.status_code == 429:  # Too Many Requests
                    time.sleep(self.config.retry_delay * (attempt + 1))
                    continue
                else:
                    self.logger.warning(f"請求失敗 (HTTP {response.status_code}): {url}")
                    return None
            except requests.RequestException as e:
                if attempt < retries - 1:
                    time.sleep(self.config.retry_delay)
                    continue
                self.logger.error(f"請求異常: {str(e)}")
                return None
        return None

    def _convert_roc_date(self, date_str: str) -> str:
        """將民國年日期轉換為西元年日期
        
        Args:
            date_str: 民國年日期字符串，例如 '111/01/04'
            
        Returns:
            西元年日期字符串，例如 '2022/01/04'
        """
        try:
            parts = date_str.split('/')
            if len(parts) != 3:
                return date_str
                
            year = int(parts[0]) + 1911
            return f"{year}/{parts[1]}/{parts[2]}"
        except Exception:
            return date_str 