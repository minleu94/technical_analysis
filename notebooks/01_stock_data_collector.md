```python
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import os
from pathlib import Path
import requests
import time
from tqdm import tqdm
import traceback
import logging
from typing import List, Dict, Optional, Tuple
import yfinance as yf
from io import StringIO
import shutil
import glob
from dataclasses import dataclass
```


```python
@dataclass
class TWStockConfig:
    """台股數據分析核心配置"""
    
    # 基礎路徑配置
    base_dir: Path = Path("D:/Min/Python/Project/FA_Data")
    
    # 數據目錄
    data_dir: Path = None
    daily_price_dir: Path = None 
    meta_data_dir: Path = None
    technical_dir: Path = None
    
    # 關鍵檔案路徑
    market_index_file: Path = None
    industry_index_file: Path = None
    stock_data_file: Path = None
    all_stocks_data_file: Path = None  # 新增整合性數據文件
    
    # 數據參數
    default_start_date: str = "2014-01-01"
    backup_keep_days: int = 7
    min_data_days: int = 30
    
    # 新增API請求配置
    request_timeout: int = 30
    max_retries: int = 3
    retry_delay: int = 5
    
    def __post_init__(self):
        """初始化衍生屬性"""
        # 設定數據目錄
        self.data_dir = self.base_dir
        self.daily_price_dir = self.data_dir / 'daily_price'
        self.meta_data_dir = self.data_dir / 'meta_data'
        self.technical_dir = self.data_dir / 'technical_analysis'
        
        # 設定關鍵檔案路徑
        self.market_index_file = self.meta_data_dir / 'market_index.csv'
        self.industry_index_file = self.meta_data_dir / 'industry_index.csv'
        self.stock_data_file = self.meta_data_dir / 'stock_data_whole.csv'
        self.all_stocks_data_file = self.meta_data_dir / 'all_stocks_data.csv'
        
        # 確保所需目錄存在
        self._ensure_directories()
        
        # 創建備份目錄
        self.backup_dir.mkdir(parents=True, exist_ok=True)
    
    def _ensure_directories(self):
        """確保所需目錄結構存在"""
        directories = [
            self.daily_price_dir,
            self.meta_data_dir,
            self.technical_dir,
            self.backup_dir
        ]
        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)
    
    @property
    def backup_dir(self) -> Path:
        """備份目錄路徑"""
        return self.meta_data_dir / 'backup'
    
    def get_technical_file(self, stock_id: str) -> Path:
        """取得特定股票的技術分析檔案路徑"""
        return self.technical_dir / f'{stock_id}_indicators.csv'
    
    def get_daily_price_file(self, date: str) -> Path:
        """取得特定日期的價格檔案路徑"""
        return self.daily_price_dir / f'{date}.csv'
    
    def create_backup(self, file_path: Path):
        """創建數據文件的備份"""
        if file_path.exists():
            backup_time = datetime.now().strftime('%Y%m%d_%H%M%S')
            backup_file = self.backup_dir / f"{file_path.stem}_{backup_time}{file_path.suffix}"
            shutil.copy2(file_path, backup_file)
            
            # 清理舊備份
            self._cleanup_old_backups(file_path.stem)
    
    def _cleanup_old_backups(self, file_prefix: str):
        """清理超過保留天數的備份文件"""
        cutoff_time = datetime.now() - timedelta(days=self.backup_keep_days)
        for backup_file in self.backup_dir.glob(f"{file_prefix}_*"):
            try:
                file_time = datetime.fromtimestamp(backup_file.stat().st_mtime)
                if file_time < cutoff_time:
                    backup_file.unlink()
            except Exception:
                continue
```


```python
class MarketDateRange:
    """市場數據日期範圍控制"""
    def __init__(self, start_date: str = None, end_date: str = None):
        self.end_date = end_date if end_date else datetime.today().strftime('%Y-%m-%d')
        self.start_date = start_date if start_date else self._get_default_start_date()
    
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
        return [start + timedelta(days=x) for x in range((end-start).days + 1)]
```


```python
class TWMarketDataProcessor:
    def __init__(self, config: Optional[TWStockConfig] = None, 
                 date_range: Optional[MarketDateRange] = None):
        """初始化數據處理器
        
        Args:
            config: TWStockConfig 實例，如果為 None 則創建新實例
            date_range: MarketDateRange 實例，如果為 None 則創建新實例
        """
        self.config = config or TWStockConfig()
        self.date_range = date_range or MarketDateRange()
        
        # 文件路徑屬性從 config 獲取
        self.stock_data_file = self.config.stock_data_file
        self.market_index_file = self.config.market_index_file
        self.industry_index_file = self.config.industry_index_file
        self.daily_price_path = self.config.daily_price_dir
        self.meta_data_path = self.config.meta_data_dir
        
        self.setup_logging()
        
        # 記錄設定的日期範圍
        self.logger.info(f"設定數據處理範圍: {self.date_range.date_range_str}")
    
    def setup_logging(self):
        """設定更簡潔的日誌系統"""
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.INFO)
        
        # 清除現有的處理器
        for handler in self.logger.handlers[:]:
            self.logger.removeHandler(handler)
        
        # 檔案處理器
        log_file = self.config.meta_data_dir / 'market_data_process.log'
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setFormatter(
            logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        )
        
        # 控制台處理器 - 只顯示錯誤和關鍵信息
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(
            logging.Formatter('%(levelname)s: %(message)s')
        )
        console_handler.setLevel(logging.ERROR)  # 提高顯示門檻
        
        self.logger.addHandler(file_handler)
        self.logger.addHandler(console_handler)

    def _make_request(self, url: str, retries: int = None) -> Optional[requests.Response]:
        """發送HTTP請求並處理重試邏輯"""
        retries = retries or self.config.max_retries
        for attempt in range(retries):
            try:
                response = requests.get(url, timeout=self.config.request_timeout)
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

    def get_latest_date(self, file_path: Path, date_column: str = '日期') -> Optional[str]:
        """獲取指定文件的最新日期
        
        Args:
            file_path: 數據文件路徑
            date_column: 日期欄位名稱，預設為 '日期'
        
        Returns:
            Optional[str]: 最新的日期字符串，如果檔案不存在或讀取失敗則返回 None
        """
        if not file_path.exists():
            return None
            
        try:
            # 指定 dtype 並設置 low_memory=False
            df = pd.read_csv(
                file_path,
                dtype={'證券代號': str, '證券名稱': str},
                low_memory=False
            )
            
            if df.empty:
                return None
                
            return df[date_column].max()
            
        except Exception as e:
            self.logger.error(f"讀取{file_path}的最新日期時發生錯誤: {str(e)}")
            return None

    def get_daily_stock_data(self, date_str: str) -> Optional[pd.DataFrame]:
        """從TWSE獲取每日股票資料"""
        url = f'https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date={date_str}&type=ALL&response=json'
        
        try:
            # 發送請求並檢查狀態碼
            response = requests.get(url)
            if response.status_code != 200:
                self.logger.warning(f"無法獲取 {date_str} 的數據: HTTP {response.status_code}")
                return None
        
            data = response.json()
            if data.get('stat') != 'OK':  # 檢查API回應狀態
                return None
            
            # 檢查是否有資料表
            if 'tables' not in data or len(data['tables']) < 9:
                return None
                
            # 取得股票交易資料（第9個table）
            stock_data = data['tables'][8]
            
            if not stock_data.get('data'):
                return None
                
            # 轉換為DataFrame
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
            
            # 處理漲跌符號
            if '漲跌(+/-)' in df.columns:
                df['漲跌(+/-)'] = df['漲跌(+/-)'].apply(
                    lambda x: '+' if 'color:red' in str(x) else 
                             '-' if 'color:green' in str(x) else ''
                )
            
            return df
    
        except Exception as e:
            self.logger.error(f"處理 {date_str} 的股票數據時發生錯誤: {str(e)}")
            return None

    def save_daily_price(self, date_str: str, df: pd.DataFrame) -> None:
        """儲存每日價格數據到daily_price資料夾"""
        try:
            if df is not None and not df.empty:
                file_path = self.config.daily_price_dir / f"{date_str}.csv"
                df.to_csv(file_path, index=False, encoding='utf-8-sig')
                self.logger.debug(f"已儲存 {date_str} 的每日價格數據")
        except Exception as e:
            self.logger.error(f"儲存 {date_str} 的每日價格數據時發生錯誤: {str(e)}")

    def process_price_data(self, df):
        """處理價格資料，包含清理千分位逗號、特殊字符和 HTML 標籤"""
        df = df.copy()
        
        # 處理漲跌符號欄位中的 HTML 標籤
        if '漲跌(+/-)' in df.columns:
            df['漲跌(+/-)'] = df['漲跌(+/-)'].replace({
                '<p style= color:red>+</p>': '+',
                '<p style= color:green>-</p>': '-',
                '<p style =color:red>+</p>': '+',  # 處理可能的空格變異
                '<p style =color:green>-</p>': '-'
            })
    
        # 需要處理的價格欄位
        price_columns = ['開盤價', '最高價', '最低價', '收盤價', '最後揭示買價', '最後揭示賣價']
        volume_columns = ['成交股數', '成交筆數', '成交金額']
        
        # 處理價格欄位
        for col in price_columns:
            if col in df.columns:
                df[col] = df[col].astype(str).replace('--', '')
                df[col] = df[col].str.replace(',', '')
                df[col] = pd.to_numeric(df[col], errors='coerce')
        
        # 處理成交量相關欄位
        for col in volume_columns:
            if col in df.columns:
                df[col] = df[col].astype(str).replace('--', '')
                df[col] = df[col].str.replace(',', '')
                df[col] = pd.to_numeric(df[col], errors='coerce')
        
        return df

    # 使用函數
    def process_daily_stock_data(self, start_date: str = None, end_date: str = None) -> Optional[pd.DataFrame]:
        """處理每日股票數據 - 增加主動獲取最新數據"""
        try:
            # 確定日期範圍
            if start_date is None:
                latest_date = self.get_latest_date(self.stock_data_file)
                if latest_date:
                    # 確保 latest_date 為字串型別
                    if not isinstance(latest_date, str):
                        latest_date = str(latest_date)
                    
                    # 統一轉換為 datetime 物件，不改變原始格式
                    try:
                        # 嘗試直接解析 YYYYMMDD 格式
                        if len(latest_date) == 8 and latest_date.isdigit():
                            parsed_date = datetime.strptime(latest_date, '%Y%m%d')
                        else:
                            # 嘗試 YYYY-MM-DD 格式
                            parsed_date = datetime.strptime(latest_date, '%Y-%m-%d')
                    except ValueError:
                        self.logger.warning(f"無法解析日期格式: {latest_date}，嘗試其他格式")
                        try:
                            # 使用 pandas 嘗試自動解析
                            parsed_date = pd.to_datetime(latest_date).to_pydatetime()
                        except:
                            self.logger.warning(f"所有日期解析嘗試失敗，使用預設值")
                            parsed_date = datetime.strptime('20140101', '%Y%m%d')
                    
                    # 下一天的日期，但保持 YYYYMMDD 格式
                    next_date = (parsed_date + timedelta(days=1)).strftime('%Y%m%d')
                    start_date = next_date
                    self.logger.info(f"從最新日期之後開始更新: {start_date}")
                else:
                    start_date = '20140101'
                    self.logger.info(f"未找到現有資料，從 {start_date} 開始更新")
            
            # 如果 start_date 是 YYYY-MM-DD 格式，轉換為 YYYYMMDD
            if start_date and '-' in start_date:
                start_date = start_date.replace('-', '')
            
            if end_date is None:
                # 使用當前日期
                end_date = datetime.today().strftime('%Y%m%d')  # 使用 YYYYMMDD 格式
            elif '-' in end_date:
                end_date = end_date.replace('-', '')
                    
            self.logger.info(f"處理日期範圍: {start_date} 到 {end_date}")
    
            # 讀取現有數據
            existing_df = pd.DataFrame()
            if self.stock_data_file.exists():
                try:
                    existing_df = pd.read_csv(
                        self.stock_data_file,
                        dtype={'證券代號': str, '證券名稱': str, '日期': str},
                        low_memory=False
                    )
                    self.logger.info(f"已讀取現有數據，共 {len(existing_df)} 筆")
                    
                    # 確保日期欄位格式一致 (YYYYMMDD)
                    if '日期' in existing_df.columns:
                        existing_df['日期'] = existing_df['日期'].apply(self._ensure_yyyymmdd_format)
                        
                except Exception as e:
                    self.logger.error(f"讀取現有數據時發生錯誤: {str(e)}")
                    existing_df = pd.DataFrame()
            
            # 將字串日期轉換為 datetime 物件
            start_dt = datetime.strptime(start_date, '%Y%m%d')
            end_dt = datetime.strptime(end_date, '%Y%m%d')
            
            # 生成日期範圍
            dates_range = [start_dt + timedelta(days=x) for x in range((end_dt - start_dt).days + 1)]
            
            # 主動獲取日期資料
            for date in tqdm(dates_range, desc="獲取每日股票數據"):
                if date.weekday() >= 5:  # 跳過週末
                    continue
                    
                # 轉換日期為 YYYYMMDD 格式
                date_str = date.strftime('%Y%m%d')
                daily_file = self.config.daily_price_dir / f"{date_str}.csv"
                
                # 檢查日期文件是否已存在且不為空
                if not daily_file.exists() or daily_file.stat().st_size == 0:
                    # 從 TWSE 下載該日期的數據
                    self.logger.info(f"從 TWSE 獲取 {date_str} 的股票數據")
                    daily_data = self.get_daily_stock_data(date_str)
                    
                    if daily_data is not None and not daily_data.empty:
                        # 儲存原始每日數據
                        self.save_daily_price(date_str, daily_data)
                        self.logger.info(f"成功獲取並儲存 {date_str} 的數據，共 {len(daily_data)} 筆")
                    else:
                        self.logger.warning(f"無法獲取 {date_str} 的數據")
                
                # 避免請求過於頻繁
                time.sleep(3)
            
            # 找出需要更新的日期
            update_dates = []
            for date in dates_range:
                if date.weekday() < 5:  # 跳過週末
                    date_str = date.strftime('%Y%m%d')
                    daily_file = self.config.daily_price_dir / f"{date_str}.csv"
                    
                    if daily_file.exists() and daily_file.stat().st_size > 0:
                        update_dates.append(date_str)
                        self.logger.debug(f"找到日期 {date_str} 的每日數據檔案")
            
            if not update_dates:
                self.logger.info("未找到需要更新的日期數據")
                return existing_df if not existing_df.empty else None
            
            self.logger.info(f"找到 {len(update_dates)} 個需要更新的日期")
            
            # 移除這些日期的舊記錄（如果存在）
            for date_str in update_dates:
                records_before = len(existing_df)
                existing_df = existing_df[existing_df['日期'] != date_str]
                records_after = len(existing_df)
                if records_before > records_after:
                    self.logger.info(f"移除了 {records_before - records_after} 筆日期為 {date_str} 的舊記錄")
            
            # 讀取並合併每日數據
            new_records = []
            for date_str in tqdm(update_dates, desc="處理每日股票數據進度"):
                daily_file = self.config.daily_price_dir / f"{date_str}.csv"
                try:
                    daily_data = pd.read_csv(daily_file, dtype={'證券代號': str})
                    
                    # 確保有日期欄位
                    if '日期' not in daily_data.columns:
                        daily_data['日期'] = date_str
                    else:
                        # 確保日期格式一致
                        daily_data['日期'] = date_str
                    
                    new_records.append(daily_data)
                    self.logger.debug(f"已讀取 {date_str} 的數據，共 {len(daily_data)} 筆")
                    
                except Exception as e:
                    self.logger.warning(f"讀取 {date_str} 數據時發生錯誤: {str(e)}")
                    continue
            
            if not new_records:
                self.logger.info("未能成功讀取任何新數據")
                return existing_df if not existing_df.empty else None
            
            # 合併新數據
            new_df = pd.concat(new_records, ignore_index=True)
            self.logger.info(f"合併後的新數據共 {len(new_df)} 筆")
            
            # 確保日期格式一致為 YYYYMMDD
            if '日期' in new_df.columns:
                new_df['日期'] = new_df['日期'].apply(self._ensure_yyyymmdd_format)
            
            # 最終合併
            final_df = pd.concat([existing_df, new_df], ignore_index=True)
            
            # 排序和保存前先備份
            self.config.create_backup(self.stock_data_file)
            
            # 根據證券代號和日期排序 (日期使用數值形式比較以確保正確排序)
            final_df['日期_排序'] = pd.to_numeric(final_df['日期'], errors='coerce')
            final_df = final_df.sort_values(['證券代號', '日期_排序'])
            final_df = final_df.drop(columns=['日期_排序']) # 去除排序用的臨時欄位
            
            # 保存更新後的數據
            final_df.to_csv(self.stock_data_file, index=False, encoding='utf-8-sig')
            self.logger.info(f"已保存更新後的數據，共 {len(final_df)} 筆記錄")
            
            # 檢查最新日期
            max_date = final_df['日期'].max()
            self.logger.info(f"更新後的最新日期: {max_date}")
            
            return final_df
            
        except Exception as e:
            self.logger.error(f"處理每日股票數據時發生錯誤: {str(e)}")
            self.logger.error(traceback.format_exc())
            return None
    
    def _ensure_yyyymmdd_format(self, date_str):
        """確保日期格式為 YYYYMMDD"""
        if not isinstance(date_str, str):
            date_str = str(date_str)
        
        date_str = date_str.strip()
        
        # 已經是 YYYYMMDD 格式
        if len(date_str) == 8 and date_str.isdigit():
            return date_str
        
        # 處理 YYYY-MM-DD 格式
        if len(date_str) == 10 and date_str[4] == '-' and date_str[7] == '-':
            return date_str.replace('-', '')
        
        # 處理 YYYY/MM/DD 格式
        if len(date_str) == 10 and date_str[4] == '/' and date_str[7] == '/':
            return date_str.replace('/', '')
        
        # 處理 MM/DD/YYYY 格式
        if '/' in date_str and len(date_str.split('/')) == 3:
            parts = date_str.split('/')
            if len(parts[2]) == 4:  # 年份部分有4位數
                month, day, year = parts
                return f"{year}{month.zfill(2)}{day.zfill(2)}"
        
        # 嘗試使用 pandas 解析其他格式
        try:
            return pd.to_datetime(date_str).strftime('%Y%m%d')
        except:
            self.logger.warning(f"無法將日期 '{date_str}' 轉換為 YYYYMMDD 格式")
            return date_str  # 返回原始值，避免數據丟失

    def preprocess_stock_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """預處理股票數據"""
        df = df.copy()
        
        # 確保證券代號為字符串
        df['證券代號'] = df['證券代號'].astype(str)
        
        # 數值型欄位清單
        numeric_columns = [
            '成交股數', '成交筆數', '成交金額', '開盤價', 
            '最高價', '最低價', '收盤價', '漲跌價差',
            '最後揭示買價', '最後揭示買量', 
            '最後揭示賣價', '最後揭示賣量', '本益比'
        ]
        
        # 處理每個數值型欄位
        for col in numeric_columns:
            if col in df.columns:
                # 將 '--' 替換為 NaN
                df[col] = df[col].replace('--', np.nan)
                
                # 如果是字符串類型，移除逗號
                if df[col].dtype == 'object':
                    df[col] = df[col].astype(str).str.replace(',', '')
                
                # 轉換為浮點數，錯誤時設為 NaN
                df[col] = pd.to_numeric(df[col], errors='coerce')
        
        return df

    def update_market_index(self) -> Optional[pd.DataFrame]:
        """更新台灣加權指數數據 - 修正排序和日期格式問題"""
        try:
            self.logger.info("開始更新市場指數數據")
            
            # 創建備份
            self.config.create_backup(self.config.market_index_file)
            
            # 使用yfinance獲取TAIEX數據
            self.logger.info(f"獲取TAIEX數據: {self.date_range.date_range_str}")
            
            # 1. 獲取新數據
            max_retries = 3
            taiex_data = None
            
            for attempt in range(max_retries):
                try:
                    taiex_data = yf.download("^TWII", 
                                        start=self.date_range.start_date, 
                                        end=self.date_range.end_date,
                                        progress=False)
                    
                    if not taiex_data.empty:
                        break
                        
                    self.logger.warning(f"第 {attempt+1} 次嘗試獲取TAIEX數據失敗，數據為空")
                    time.sleep(5)
                    
                except Exception as e:
                    self.logger.warning(f"第 {attempt+1} 次嘗試獲取TAIEX數據出錯: {str(e)}")
                    if attempt < max_retries - 1:
                        time.sleep(5)
                    else:
                        self.logger.error(f"無法獲取TAIEX數據: {str(e)}")
                        return None
            
            if taiex_data is None or taiex_data.empty:
                self.logger.warning("未獲取到TAIEX數據")
                return None
                    
            # 2. 轉換新數據格式
            new_data = taiex_data.reset_index()
            new_data_standardized = pd.DataFrame()
            
            # 確保日期欄位格式統一為 YYYY-MM-DD
            new_data_standardized['日期'] = new_data['Date'].dt.strftime('%Y-%m-%d')  # 統一使用 YYYY-MM-DD 格式
            new_data_standardized['開盤價'] = new_data['Open'].values
            new_data_standardized['最高價'] = new_data['High'].values
            new_data_standardized['最低價'] = new_data['Low'].values
            new_data_standardized['收盤價'] = new_data['Close'].values
            new_data_standardized['成交量'] = new_data['Volume'].values
            
            # 3. 讀取並合併舊數據
            standardized_data = new_data_standardized.copy()
            
            if self.config.market_index_file.exists():
                try:
                    # 讀取舊數據
                    old_data = pd.read_csv(self.config.market_index_file)
                    
                    # 檢查日期欄位
                    if '日期' in old_data.columns:
                        # 統一日期格式
                        old_data['日期'] = old_data['日期'].apply(self._standardize_date_format)
                        
                        # 合併新舊數據
                        combined_data = pd.concat([old_data, new_data_standardized])
                        
                        # 去除重複數據，保留最新的
                        combined_data = combined_data.drop_duplicates(subset=['日期'], keep='last')
                        
                        # 確保按日期排序 - 注意這裡重要！
                        combined_data['日期_sort'] = pd.to_datetime(combined_data['日期'])  # 創建排序用的日期列
                        combined_data = combined_data.sort_values('日期_sort')
                        combined_data = combined_data.drop(columns=['日期_sort'])  # 去除排序列
                        
                        standardized_data = combined_data
                    else:
                        self.logger.warning("舊數據中找不到日期欄位，使用新數據取代")
                except Exception as e:
                    self.logger.error(f"處理舊數據時發生錯誤: {str(e)}")
                    self.logger.error(traceback.format_exc())
            
            # 4. 保存數據
            standardized_data.to_csv(self.config.market_index_file, index=False, encoding='utf-8-sig')
            
            self.logger.info(f"已更新TAIEX數據，共 {len(standardized_data)} 筆記錄")
            return standardized_data
            
        except Exception as e:
            self.logger.error(f"更新市場指數時發生錯誤: {str(e)}")
            self.logger.error(traceback.format_exc())
            return None
        
    def _standardize_date_format(self, date_str):
        """將各種日期格式統一轉換為 YYYY-MM-DD 格式"""
        if not isinstance(date_str, str):
            date_str = str(date_str)
        
        date_str = date_str.strip()
        
        # 處理 YYYYMMDD 格式
        if len(date_str) == 8 and date_str.isdigit():
            return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
        
        # 處理 YYYY/MM/DD 格式
        if len(date_str) == 10 and date_str[4] == '/' and date_str[7] == '/':
            year, month, day = date_str.split('/')
            return f"{year}-{month}-{day}"
        
        # 處理 MM/DD/YYYY 格式
        if '/' in date_str and len(date_str.split('/')) == 3:
            parts = date_str.split('/')
            if len(parts[2]) == 4:  # 年份部分有4位數
                month, day, year = parts
                return f"{year}-{month.zfill(2)}-{day.zfill(2)}"
        
        # 已經是 YYYY-MM-DD 格式
        if len(date_str) == 10 and date_str[4] == '-' and date_str[7] == '-':
            return date_str
        
        # 嘗試使用 pandas 解析其他格式
        try:
            return pd.to_datetime(date_str).strftime('%Y-%m-%d')
        except:
            self.logger.warning(f"無法將日期 '{date_str}' 轉換為 YYYY-MM-DD 格式")
            return date_str  # 返回原始值，避免數據丟失

    def extract_index_data_for_date(self, date_str: str) -> Optional[List[Dict]]:
        """擷取特定日期的產業類股指數資料（包含價格指數和報酬指數）"""
        try:
            url = f'https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date={date_str}&type=IND&response=json'
            
            response = self._make_request(url)
            if response is None:
                return None
        
            data = response.json()
            
            if 'tables' not in data or not data['tables']:
                self.logger.warning(f"日期 {date_str} 未擷取到任何產業指數")
                return None
        
            index_data = []
            # 尋找包含產業類指數的表格
            for table in data['tables']:
                if '價格指數' in table.get('title', '') or '報酬指數' in table.get('title', ''):
                    for row in table['data']:
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
                                self.logger.warning(f"處理產業指數行資料時發生錯誤: {str(e)}, Row: {row}")
                                continue
        
            if index_data:
                self.logger.debug(f"日期 {date_str} 抓取到 {len(index_data)} 個類股指數")
                self.logger.info(f"已取得 {len([x for x in index_data if '報酬' in x['指數名稱']])} 個類報酬指數")
                self.logger.info(f"已取得 {len([x for x in index_data if '報酬' not in x['指數名稱']])} 個類指數")
            return index_data
            
        except Exception as e:
            self.logger.error(f"處理 {date_str} 時發生錯誤: {str(e)}")
            return None

    def process_industry_index_data(self) -> Optional[pd.DataFrame]:
        """處理產業指數數據"""
        try:
            self.logger.info(f"開始處理產業指數數據: {self.date_range.date_range_str}")
            
            # 創建備份
            self.config.create_backup(self.config.industry_index_file)
            
            # 讀取現有數據
            existing_df = pd.DataFrame()
            existing_dates = set()
            if self.config.industry_index_file.exists():
                existing_df = pd.read_csv(self.config.industry_index_file)
                existing_dates = set(existing_df['日期'].unique())
                self.logger.info(f"已讀取現有數據，共 {len(existing_df)} 筆記錄")
    
            # 獲取需要處理的日期清單
            dates_to_process = []
            for date in self.date_range.get_date_list():
                # 跳過週末
                if date.weekday() >= 5:  # 5是星期六，6是星期日
                    continue
                date_str = date.strftime('%Y-%m-%d')
                if date_str not in existing_dates:
                    dates_to_process.append(date)
    
            if not dates_to_process:
                self.logger.info("所有日期的數據都已存在，無需更新")
                return existing_df
    
            self.logger.info(f"需要處理 {len(dates_to_process)} 天的數據")
    
            # 收集新數據
            new_data = []
            retry_dates = []  # 用於存儲需要重試的日期
            
            for date in tqdm(dates_to_process, desc="處理產業指數數據進度"):
                date_str = date.strftime('%Y%m%d')
                index_data = self.extract_index_data_for_date(date_str)
                
                if index_data:
                    new_data.extend(index_data)
                else:
                    retry_dates.append(date)
                time.sleep(3)  # 避免請求過於頻繁
    
            # 嘗試重試失敗的日期
            if retry_dates:
                self.logger.info(f"重試 {len(retry_dates)} 個失敗的日期")
                for date in retry_dates:
                    date_str = date.strftime('%Y%m%d')
                    index_data = self.extract_index_data_for_date(date_str)
                    if index_data:
                        new_data.extend(index_data)
                    time.sleep(5)  # 重試時增加等待時間
    
            if not new_data:
                self.logger.info("沒有新的產業指數數據需要處理")
                return existing_df if not existing_df.empty else None
    
            # 合併新舊數據
            new_df = pd.DataFrame(new_data)
            if not existing_df.empty:
                df = pd.concat([existing_df, new_df], ignore_index=True)
                df = df.drop_duplicates(subset=['日期', '指數名稱'], keep='last')
            else:
                df = new_df
    
            # 排序和保存
            df = df.sort_values(['指數名稱', '日期'])
            df.to_csv(self.config.industry_index_file, index=False, encoding='utf-8-sig')
            
            self._generate_index_report(df)
            return df
                
        except Exception as e:
            self.logger.error(f"處理產業指數數據時發生錯誤: {str(e)}")
            raise

    def _generate_index_report(self, df: pd.DataFrame):
        """生成指數數據報告"""
        self.logger.info("\n=== 指數數據報告 ===")
        self.logger.info(f"總記錄數: {len(df):,d}")
        self.logger.info(f"指數數量: {len(df['指數名稱'].unique()):,d}")
        self.logger.info(f"日期範圍: {df['日期'].min()} 到 {df['日期'].max()}")
        self.logger.info(f"總交易日數: {len(df['日期'].unique()):,d}")
        
        # 最近更新的日期
        recent_dates = sorted(df['日期'].unique())[-5:]
        self.logger.info(f"最近的5個交易日: {', '.join(recent_dates)}")
        
        try:
            # 最新日期的指數漲跌情況
            latest_date = df['日期'].max()
            latest_data = df[df['日期'] == latest_date]
            
            self.logger.info(f"\n最新交易日 ({latest_date}) 指數表現:")
            for _, row in latest_data.iterrows():
                self.logger.info(
                    f"  - {row['指數名稱']}: {row['收盤指數']:,.2f} "
                    f"({row['漲跌']} {row['漲跌點數']:,.2f} / {row['漲跌百分比']:,.2f}%)"
                )
            
            # 計算期間漲幅最大的指數
            df_period = df.sort_values('日期')
            index_performance = []
            
            for name in df['指數名稱'].unique():
                index_data = df[df['指數名稱'] == name]
                if len(index_data) >= 2:
                    first_value = index_data.iloc[0]['收盤指數']
                    last_value = index_data.iloc[-1]['收盤指數']
                    change_pct = ((last_value - first_value) / first_value) * 100
                    index_performance.append({
                        '指數名稱': name,
                        '漲跌幅': change_pct
                    })
            
            if index_performance:
                performance_df = pd.DataFrame(index_performance)
                top_performers = performance_df.nlargest(5, '漲跌幅')
                
                self.logger.info("\n期間漲幅最大的指數:")
                for _, row in top_performers.iterrows():
                    self.logger.info(
                        f"  - {row['指數名稱']}: {row['漲跌幅']:,.2f}%"
                    )
                    
        except Exception as e:
            self.logger.error(f"生成指數報告時發生錯誤: {str(e)}")

    def _generate_stock_report(self, df: pd.DataFrame):
        """生成股票數據報告"""
        try:
            self.logger.info("\n=== 股票數據報告 ===")
            self.logger.info(f"總記錄數: {len(df):,d}")
            self.logger.info(f"股票數量: {len(df['證券代號'].unique()):,d}")
            self.logger.info(f"日期範圍: {df['日期'].min()} 到 {df['日期'].max()}")
            self.logger.info(f"總交易日數: {len(df['日期'].unique()):,d}")
                       
        except Exception as e:
            self.logger.error(f"生成股票報告時發生錯誤: {str(e)}")

    def process_all(self) -> Dict[str, pd.DataFrame]:
        """執行完整的數據處理流程"""
        self.logger.info(f"開始執行完整數據更新流程: {self.date_range.date_range_str}")
        
        results = {}
        try:
            
            # 1. 更新大盤指數
            self.logger.info("\n=== 更新大盤指數 ===")
            results['taiex_data'] = self.update_market_index()
            
            # 2. 更新產業指數
            self.logger.info("\n=== 更新產業指數 ===")
            results['industry_data'] = self.process_industry_index_data()
            
            # 3. 更新個股數據
            self.logger.info("\n=== 更新個股數據 ===")
            results['stock_data'] = self.process_daily_stock_data()
            
            # 4. 生成更新報告
            self._generate_update_summary()
            
            return results
            
        except Exception as e:
            self.logger.error(f"更新過程中發生錯誤: {str(e)}")
            raise

    def _generate_update_summary(self):
        """生成數據更新摘要報告"""
        self.logger.info("\n=== 數據更新摘要 ===")
        
        files_status = {
            '大盤指數': (self.config.market_index_file, 'Date'),
            '產業指數': (self.config.industry_index_file, '日期'),
            '個股數據': (self.config.stock_data_file, '日期')
        }
        
        for name, (file_path, date_col) in files_status.items():
            if file_path.exists():
                try:
                    dtype_dict = {'證券代號': str, '證券名稱': str, '日期': str} if name == '個股數據' else None
                    df = pd.read_csv(file_path, dtype=dtype_dict, na_values=['--'], keep_default_na=True, low_memory=False)
                    
                    self.logger.info(f"{name}:")
                    self.logger.info(f"  - 資料筆數: {len(df):,d}")
                    self.logger.info(f"  - 日期範圍: {df[date_col].min()} 到 {df[date_col].max()}")
                    
                    if name == '產業指數':
                        self.logger.info(f"  - 指數數量: {len(df['指數名稱'].unique())}")
                    elif name == '個股數據':
                        self.logger.info(f"  - 股票數量: {len(df['證券代號'].unique())}")
                        
                except Exception as e:
                    self.logger.error(f"讀取 {name} 數據時發生錯誤: {str(e)}")
            else:
                self.logger.warning(f"{name} 數據文件不存在")

    def show_data_structure(self):
        """顯示所有數據文件的基本結構"""
        self.logger.info("\n=== 數據文件結構總覽 ===")
        
        files_info = {
            '大盤指數': {
                'path': self.config.market_index_file,
                'description': '台灣加權指數每日交易數據',
                'date_column': 'Date'
            },
            '產業指數': {
                'path': self.config.industry_index_file,
                'description': '各產業指數每日數據',
                'date_column': '日期'
            },
            '個股數據': {
                'path': self.config.stock_data_file,
                'description': '個股每日交易詳細數據',
                'date_column': '日期'
            }
        }
        
        for name, info in files_info.items():
            self.logger.info(f"\n{'-'*50}")
            self.logger.info(f"【{name}】")
            self.logger.info(f"說明: {info['description']}")
            
            if not info['path'].exists():
                self.logger.warning(f"檔案不存在: {info['path']}")
                continue
                
            try:
                # 讀取檔案（只讀取前100行來分析結構）
                if name == '個股數據':
                    df = pd.read_csv(info['path'], 
                                   dtype={'證券代號': str, '證券名稱': str, '日期': str},
                                   na_values=['--'],
                                   nrows=100,
                                   low_memory=False)
                else:
                    df = pd.read_csv(info['path'], nrows=100, low_memory=False)
                
                # 基本信息
                self.logger.info(f"欄位數量: {len(df.columns)}")
                
                # 欄位資訊表格
                self.logger.info("\n欄位明細:")
                self.logger.info(f"{'欄位名稱':<20} {'數據類型':<15} {'非空值比例':<10} {'值示例':<30}")
                self.logger.info("-" * 75)
                
                for col in df.columns:
                    # 計算非空值比例
                    non_null_ratio = (df[col].notna().sum() / len(df)) * 100
                    # 獲取值示例
                    sample_value = df[col].dropna().iloc[0] if not df[col].empty else 'N/A'
                    # 格式化輸出
                    self.logger.info(
                        f"{str(col):<20} {str(df[col].dtype):<15} "
                        f"{non_null_ratio:>8.1f}% {str(sample_value):<30}"
                    )
                    
                # 日期範圍信息
                date_col = info['date_column']
                if date_col in df.columns:
                    self.logger.info(f"\n數據時間範圍: {df[date_col].min()} 到 {df[date_col].max()}")
                    
            except Exception as e:
                self.logger.error(f"分析 {name} 時發生錯誤: {str(e)}")

    def check_data_consistency(self):
        """檢查數據一致性"""
        try:
            self.logger.info("\n=== 資料一致性檢查 ===")
            
            # 讀取 stock_data_whole
            stock_df = pd.read_csv(self.config.stock_data_file, 
                                 dtype={'證券代號': str})
            
            # 檢查資料筆數少的股票
            stock_counts = stock_df.groupby('證券代號').agg({
                '日期': ['count', 'min', 'max'],
                '證券名稱': 'first'
            })
            stock_counts.columns = ['筆數', '開始日期', '結束日期', '名稱']
            
            low_count_stocks = stock_counts[stock_counts['筆數'] < 50]
            
            self.logger.info("\n=== 資料筆數少於50的股票 ===")
            self.logger.info(f"共有 {len(low_count_stocks)} 支股票")
            for idx, row in low_count_stocks.iterrows():
                self.logger.info(
                    f"代號: {idx}, 名稱: {row['名稱']}, "
                    f"資料筆數: {row['筆數']}, "
                    f"資料區間: {row['開始日期']} 到 {row['結束日期']}"
                )
            
            # 檢查daily_price檔案
            daily_files = list(self.config.daily_price_dir.glob('*.csv'))
            self.logger.info(f"\n=== daily_price檔案檢查 ===")
            self.logger.info(f"檔案總數: {len(daily_files)}")
            
            # 檢查部分檔案內容
            sample_files = sorted(daily_files)[-5:]  # 最新的5個檔案
            for file in sample_files:
                df = pd.read_csv(file)
                self.logger.info(
                    f"檔案 {file.name}: "
                    f"資料筆數 {len(df)}, "
                    f"股票數量 {df['證券代號'].nunique()}"
                )
                
        except Exception as e:
            self.logger.error(f"檢查資料一致性時發生錯誤: {str(e)}")
```


```python
def check_data_status():
    """檢查各資料檔案的狀態和最新日期，修正日期排序問題"""
    # 設定路徑
    base_path = Path("D:/Min/Python/Project/FA_Data")
    meta_data_path = base_path / 'meta_data'
    
    # 檢查文件
    market_file = meta_data_path / 'market_index.csv'
    industry_file = meta_data_path / 'industry_index.csv'
    stock_file = meta_data_path / 'stock_data_whole.csv'
    
    print("\n=== 台股數據檔案狀態 ===")
    
    # 檢查大盤指數檔案
    if market_file.exists():
        try:
            # 讀取檔案
            df_market = pd.read_csv(market_file)
            print(f"大盤指數檔案: 存在 ({len(df_market)} 筆資料)")
            print(f"  - 欄位名稱: {list(df_market.columns)}")
            
            # 查找日期欄位
            date_col = None
            for col in df_market.columns:
                if col.lower() in ['日期', 'date']:
                    date_col = col
                    break
            
            if date_col:
                print(f"  - 使用日期欄位: {date_col}")
                
                # 直接轉換所有日期為 datetime 物件進行排序
                # 使用 pd.to_datetime 並指定 errors='coerce' 避免錯誤
                df_market['date_for_sort'] = pd.to_datetime(df_market[date_col], errors='coerce')
                
                # 過濾掉轉換失敗的日期 (NaT)
                df_market_valid = df_market.dropna(subset=['date_for_sort'])
                
                if not df_market_valid.empty:
                    # 按日期排序
                    df_market_sorted = df_market_valid.sort_values('date_for_sort')
                    
                    # 取得最早和最新日期
                    earliest_date = df_market_sorted[date_col].iloc[0]
                    latest_date = df_market_sorted[date_col].iloc[-1]
                    
                    print(f"  - 最新日期: {latest_date}")
                    print(f"  - 最早日期: {earliest_date}")
                    print(f"  - 有效日期筆數: {len(df_market_valid)}")
                    
                    # 顯示最新的幾筆資料，便於確認
                    print(f"  - 最新5筆日期資料:")
                    for i in range(min(5, len(df_market_sorted))):
                        idx = len(df_market_sorted) - i - 1
                        print(f"      {df_market_sorted[date_col].iloc[idx]}")
                else:
                    print("  - 無有效日期資料")
            else:
                print("  - 無法辨識日期欄位")
        except Exception as e:
            print(f"大盤指數檔案: 讀取錯誤 ({str(e)})")
            import traceback
            print(traceback.format_exc())
    else:
        print("大盤指數檔案: 不存在")
    
    # 檢查產業指數檔案
    if industry_file.exists():
        try:
            df_industry = pd.read_csv(industry_file)
            # 確保日期欄位為字串
            if '日期' in df_industry.columns:
                # 使用同樣的日期排序邏輯
                df_industry['date_for_sort'] = pd.to_datetime(df_industry['日期'], errors='coerce')
                df_industry_valid = df_industry.dropna(subset=['date_for_sort'])
                
                if not df_industry_valid.empty:
                    df_industry_sorted = df_industry_valid.sort_values('date_for_sort')
                    latest_date = df_industry_sorted['日期'].iloc[-1]
                    
                    print(f"產業指數檔案: 存在 ({len(df_industry)} 筆資料)")
                    print(f"  - 最新日期: {latest_date}")
                    print(f"  - 指數數量: {df_industry['指數名稱'].nunique()}")
                else:
                    print(f"產業指數檔案: 存在但日期資料無效")
            else:
                print(f"產業指數檔案: 存在但缺少日期欄位")
        except Exception as e:
            print(f"產業指數檔案: 讀取錯誤 ({str(e)})")
    else:
        print("產業指數檔案: 不存在")
    
    # 檢查股票資料檔案
    if stock_file.exists():
        try:
            df_stock = pd.read_csv(
                stock_file, 
                dtype={'證券代號': str, '證券名稱': str, '日期': str},
                low_memory=False
            )
            if '日期' in df_stock.columns:
                # 嘗試統一日期格式並排序
                # 先將 YYYYMMDD 格式轉換為 YYYY-MM-DD 格式
                df_stock['formatted_date'] = df_stock['日期'].apply(
                    lambda x: f"{x[:4]}-{x[4:6]}-{x[6:]}" if len(str(x)) == 8 and str(x).isdigit() else x
                )
                
                # 轉換為日期型別進行排序
                df_stock['date_for_sort'] = pd.to_datetime(df_stock['formatted_date'], errors='coerce')
                df_stock_valid = df_stock.dropna(subset=['date_for_sort'])
                
                if not df_stock_valid.empty:
                    df_stock_sorted = df_stock_valid.sort_values('date_for_sort')
                    
                    print(f"股票資料檔案: 存在 ({len(df_stock)} 筆資料)")
                    print(f"  - 最新日期: {df_stock_sorted['日期'].iloc[-1]} (格式化後: {df_stock_sorted['formatted_date'].iloc[-1]})")
                    print(f"  - 日期格式範例: {df_stock['日期'].iloc[0]}")
                    print(f"  - 股票數量: {df_stock['證券代號'].nunique()}")
                else:
                    print(f"股票資料檔案: 存在但日期資料無效")
            else:
                print(f"股票資料檔案: 存在但缺少日期欄位")
        except Exception as e:
            print(f"股票資料檔案: 讀取錯誤 ({str(e)})")
    else:
        print("股票資料檔案: 不存在")
```


```python
# 調用檢查函數來顯示數據狀態
check_data_status()
```

    
    === 台股數據檔案狀態 ===
    大盤指數檔案: 存在 (2734 筆資料)
      - 欄位名稱: ['日期', '開盤價', '最高價', '最低價', '收盤價', '成交量']
      - 使用日期欄位: 日期
      - 最新日期: 2025-04-01
      - 最早日期: 2014-01-02
      - 有效日期筆數: 2734
      - 最新5筆日期資料:
          2025-04-01
          2025-03-31
          2025-03-28
          2025-03-27
          2025-03-26
    產業指數檔案: 存在 (157173 筆資料)
      - 最新日期: 2025-04-02
      - 指數數量: 79
    股票資料檔案: 存在 (2564335 筆資料)
      - 最新日期: 20250401 (格式化後: 2025-04-01)
      - 日期格式範例: 20241212
      - 股票數量: 1171
    


```python
# processor.update_market_index()  # 更新大盤指數
# processor.process_industry_index_data()  # 更新產業指數
# processor.process_daily_stock_data()  # 更新個股數據

# 處理日期範圍(有end_date就會給範圍,沒有則預設為今天
# date_range = MarketDateRange(start_date='2023-01-01',end_date='2023-12-31')
# date_range = MarketDateRange(start_date='2024-01-01')
# processor = TWMarketDataProcessor(date_range=date_range)

#function
# 最近一個月的數據
# processor = TWMarketDataProcessor(date_range=MarketDateRange.last_month())
# # 最近90天（一季）的數據
# processor = TWMarketDataProcessor(date_range=MarketDateRange.last_quarter())
# # 最近一年的數據
# processor = TWMarketDataProcessor(date_range=MarketDateRange.last_year())
# # 今年至今的數據
# processor = TWMarketDataProcessor(date_range=MarketDateRange.year_to_date())
# 自定義天數
# processor = TWMarketDataProcessor(date_range=MarketDateRange.last_n_days(45))
#顯示數據結構
# processor.show_data_structure()  # 在更新數據之前或之後都可以調用
```


```python
def main():
    # 創建數據處理器
    processor = TWMarketDataProcessor(date_range=MarketDateRange.last_n_days(45))
    
    try:
        print("=== 開始台股數據更新 ===")
        print(f"日期範圍: {processor.date_range.date_range_str}")
        
        # 1. 更新大盤指數
        print("\n1. 更新大盤指數...")
        market_result = processor.update_market_index()
        if market_result is not None:
            if '日期' in market_result.columns and not market_result.empty:
                # 獲取排序後的最後一筆資料的日期作為最新日期
                latest_date = market_result['日期'].iloc[-1]
                print(f"  ✓ 大盤指數更新完成，最新日期: {latest_date}")
            else:
                print(f"  ✓ 大盤指數更新完成，共 {len(market_result)} 筆資料")
        else:
            print("  ✗ 大盤指數更新失敗")
            
        time.sleep(3)  # 等待3秒避免請求過於頻繁
        
        # 2. 更新產業指數
        print("\n2. 更新產業指數...")
        industry_result = processor.process_industry_index_data()
        if industry_result is not None:
            latest_date = industry_result['日期'].max() if '日期' in industry_result.columns else "未知"
            print(f"  ✓ 產業指數更新完成，最新日期: {latest_date}")
        else:
            print("  ✗ 產業指數更新失敗")
        
        time.sleep(3)
        
        # 3. 更新個股數據
        print("\n3. 更新個股數據...")
        stock_result = processor.process_daily_stock_data()
        if stock_result is not None:
            latest_date = stock_result['日期'].max() if '日期' in stock_result.columns else "未知"
            print(f"  ✓ 個股數據更新完成，最新日期: {latest_date}")
        else:
            print("  ✗ 個股數據更新失敗")
        
        print("\n=== 台股數據更新完成 ===")
        
    except Exception as e:
        print(f"\n更新過程發生錯誤: {str(e)}")
        # 錯誤發生時，提供更詳細的診斷信息
        import traceback
        print("\n詳細錯誤信息:")
        traceback.print_exc()

if __name__ == "__main__":
    main()
```

    === 開始台股數據更新 ===
    日期範圍: 從 2025-02-16 到 2025-04-02
    
    1. 更新大盤指數...
      ✓ 大盤指數更新完成，最新日期: 2025-04-01
    
    2. 更新產業指數...
    

    處理產業指數數據進度: 100%|██████████████████████████████████████████████████████████████| 1/1 [00:04<00:00,  4.39s/it]
    

      ✓ 產業指數更新完成，最新日期: 2025-04-02
    
    3. 更新個股數據...
    

    獲取每日股票數據: 100%|██████████████████████████████████████████████████████████████████| 1/1 [00:08<00:00,  8.01s/it]
    處理每日股票數據進度: 100%|██████████████████████████████████████████████████████████████| 1/1 [00:00<00:00, 21.51it/s]
    

      ✓ 個股數據更新完成，最新日期: 20250402
    
    === 台股數據更新完成 ===
    


```python
# 設定路徑
base_path = Path("D:/Min/Python/Project/FA_Data")
meta_data_path = base_path / 'meta_data'

# 檢查文件
market_file = meta_data_path / 'market_index.csv'
industry_file = meta_data_path / 'industry_index.csv'
stock_file = meta_data_path / 'stock_data_whole.csv'

# 讀取並顯示資料狀態
if market_file.exists():
    df_market = pd.read_csv(market_file)
    print(f"大盤指數最新日期: {df_market['日期'].max()}")

if industry_file.exists():
    df_industry = pd.read_csv(industry_file)
    print(f"產業指數最新日期: {df_industry['日期'].max()}")
    
if stock_file.exists():
    df_stock = pd.read_csv(stock_file, low_memory=False)
    print(f"股票資料最新日期: {df_stock['日期'].max()}")
```

    大盤指數最新日期: 2025-04-01
    產業指數最新日期: 2025-04-02
    股票資料最新日期: 20250402
    
