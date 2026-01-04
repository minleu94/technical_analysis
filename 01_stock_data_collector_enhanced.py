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

# 載入環境變數（從 .env 檔案）
try:
    from dotenv import load_dotenv
    load_dotenv()  # 載入 .env 檔案中的環境變數
except ImportError:
    # 如果沒有安裝 python-dotenv，只從系統環境變數讀取
    pass

# 設定 FinMind API token（從環境變數讀取）
FINMIND_TOKEN = os.environ.get('FINMIND_TOKEN', '')  # 請在 .env 檔案中設定 FINMIND_TOKEN
if not FINMIND_TOKEN:
    raise ValueError("請設定環境變數 FINMIND_TOKEN 或在 .env 檔案中設定")

# 嘗試導入 finmind
try:
    import finmind
    from finmind.data import Data
    FINMIND_AVAILABLE = True
except ImportError:
    print("警告: finmind 模組未安裝，將只使用 yfinance 作為數據源")
    FINMIND_AVAILABLE = False

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
    all_stocks_data_file: Path = None
    
    # 數據參數
    default_start_date: str = "2014-01-01"
    backup_keep_days: int = 7
    min_data_days: int = 30
    
    # API請求配置
    request_timeout: int = 30
    max_retries: int = 3
    retry_delay: int = 5
    
    def __post_init__(self):
        """初始化路徑"""
        # 設定數據目錄
        self.data_dir = self.base_dir / "data"
        self.daily_price_dir = self.data_dir / "daily_price"
        self.meta_data_dir = self.data_dir / "meta_data"
        self.technical_dir = self.data_dir / "technical_analysis"
        
        # 設定檔案路徑
        self.market_index_file = self.data_dir / "market_index.csv"
        self.industry_index_file = self.data_dir / "industry_index.csv"
        self.stock_data_file = self.data_dir / "stock_data.csv"
        self.all_stocks_data_file = self.data_dir / "all_stocks_data.csv"
        
        # 創建必要的目錄
        for path in [self.data_dir, self.daily_price_dir, self.meta_data_dir, self.technical_dir]:
            path.mkdir(parents=True, exist_ok=True)
    
    def create_backup(self, file_path: Path) -> None:
        """創建檔案備份"""
        if not file_path.exists():
            return
            
        backup_dir = file_path.parent / "backup"
        backup_dir.mkdir(exist_ok=True)
        
        # 創建帶時間戳的備份檔案
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file = backup_dir / f"{file_path.stem}_{timestamp}{file_path.suffix}"
        
        # 複製檔案
        shutil.copy2(file_path, backup_file)
        
        # 清理舊備份
        self._cleanup_old_backups(backup_dir)
    
    def _cleanup_old_backups(self, backup_dir: Path) -> None:
        """清理舊的備份檔案"""
        backup_files = list(backup_dir.glob(f"*{self.market_index_file.suffix}"))
        backup_files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
        
        # 保留最近 N 天的備份
        cutoff_date = datetime.now() - timedelta(days=self.backup_keep_days)
        for file in backup_files[self.backup_keep_days:]:
            if datetime.fromtimestamp(file.stat().st_mtime) < cutoff_date:
                file.unlink()

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
    
    @property
    def date_range_str(self) -> str:
        """獲取日期範圍字符串"""
        return f"{self.start_date} 至 {self.end_date}"
    
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

class TWMarketDataProcessor:
    """台股市場數據處理器"""
    
    def __init__(self, config: Optional[TWStockConfig] = None, 
                 date_range: Optional[MarketDateRange] = None):
        """初始化數據處理器"""
        self.config = config or TWStockConfig()
        self.date_range = date_range or MarketDateRange()
        
        # 文件路徑屬性從 config 獲取
        self.stock_data_file = self.config.stock_data_file
        self.market_index_file = self.config.market_index_file
        self.industry_index_file = self.config.industry_index_file
        self.daily_price_path = self.config.daily_price_dir
        self.meta_data_path = self.config.meta_data_dir
        
        # 只有在 finmind 可用時才初始化
        if FINMIND_AVAILABLE:
            finmind.login(FINMIND_TOKEN)
            self.finmind_data = Data()
        else:
            self.finmind_data = None
        
        self.setup_logging()
        
        # 記錄設定的日期範圍
        self.logger.info(f"設定數據處理範圍: {self.date_range.date_range_str}")
    
    def setup_logging(self):
        """設置日誌"""
        self.logger = logging.getLogger(__name__)
        if not self.logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)
            self.logger.setLevel(logging.INFO)
    
    def _get_headers(self) -> Dict[str, str]:
        """獲取請求頭"""
        return {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
    
    def update_market_index(self) -> bool:
        """更新大盤指數數據"""
        try:
            self.logger.info("開始更新市場指數數據")
            
            # 創建備份
            self.config.create_backup(self.market_index_file)
            
            # 1. 首先嘗試使用 yfinance
            df_yf = None
            try:
                df_yf = yf.download('^TWII', 
                                  start=self.date_range.start_date, 
                                  end=self.date_range.end_date,
                                  progress=False)
                if not df_yf.empty:
                    self.logger.info("成功從 yfinance 獲取數據")
            except Exception as e:
                self.logger.warning(f"從 yfinance 獲取數據失敗: {str(e)}")
            
            # 2. 如果 yfinance 失敗且 finmind 可用，嘗試使用 FinMind
            if (df_yf is None or df_yf.empty) and FINMIND_AVAILABLE:
                try:
                    finmind.login(FINMIND_TOKEN)
                    finmind_data = Data()
                    df_fm = finmind_data.taiwan_stock_index_daily(
                        stock_id="TAIEX",
                        start_date=self.date_range.start_date,
                        end_date=self.date_range.end_date
                    )
                    if not df_fm.empty:
                        self.logger.info("成功從 FinMind 獲取數據")
                        df_yf = df_fm.rename(columns={
                            'date': 'Date',
                            'open': 'Open',
                            'high': 'High',
                            'low': 'Low',
                            'close': 'Close',
                            'volume': 'Volume'
                        })
                        df_yf.set_index('Date', inplace=True)
                except Exception as e:
                    self.logger.warning(f"從 FinMind 獲取數據失敗: {str(e)}")
            
            if df_yf is None or df_yf.empty:
                self.logger.error("無法從任何數據源獲取大盤指數數據")
                return False
            
            # 3. 處理數據格式
            df = df_yf.reset_index()
            df = df.rename(columns={
                'Date': '日期',
                'Open': '開盤價',
                'High': '最高價',
                'Low': '最低價',
                'Close': '收盤價',
                'Volume': '成交量'
            })
            
            # 只保留需要的列
            df = df[['日期', '開盤價', '最高價', '最低價', '收盤價', '成交量']]
            
            # 處理數據格式
            df['日期'] = df['日期'].dt.strftime('%Y-%m-%d')
            df['開盤價'] = df['開盤價'].round(2)
            df['最高價'] = df['最高價'].round(2)
            df['最低價'] = df['最低價'].round(2)
            df['收盤價'] = df['收盤價'].round(2)
            df['成交量'] = df['成交量'].astype(int)
            
            # 讀取現有數據（如果存在）
            if self.market_index_file.exists():
                existing_df = pd.read_csv(self.market_index_file)
                # 合併新舊數據
                df = pd.concat([existing_df, df], ignore_index=True)
                # 刪除重複的日期，保留最新的數據
                df = df.drop_duplicates(subset=['日期'], keep='last')
                # 按日期排序
                df = df.sort_values('日期')
            
            # 保存數據
            df.to_csv(self.market_index_file, index=False, encoding='utf-8-sig')
            
            self.logger.info(f"成功更新大盤指數數據，共 {len(df)} 筆記錄")
            return True
            
        except Exception as e:
            self.logger.error(f"更新大盤指數數據時發生錯誤: {str(e)}")
            return False

    def update_industry_index(self) -> bool:
        """批次更新產業指數數據（多日）"""
        try:
            all_data = []
            date_list = pd.date_range(self.date_range.start_date, self.date_range.end_date).strftime('%Y-%m-%d')
            for date in tqdm(date_list, desc='處理產業指數數據進度'):
                url = "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX"
                params = {
                    "date": datetime.strptime(date, '%Y-%m-%d').strftime('%Y%m%d'),
                    "type": "IND",
                    "response": "json"
                }
                try:
                    response = requests.get(url, params=params, headers=self._get_headers())
                    if response.status_code != 200:
                        continue
                    data = response.json()
                    if data.get("stat") != "OK":
                        continue
                    if 'tables' not in data or not data['tables']:
                        continue
                    for table in data['tables']:
                        if '類股指數' in table.get('title', ''):
                            for row in table.get('rows', []):
                                if len(row) < 7:
                                    continue
                                name = row[0].strip()
                                try:
                                    open_price = float(str(row[1]).replace(',', '')) if row[1] != '--' else None
                                    high_price = float(str(row[2]).replace(',', '')) if row[2] != '--' else None
                                    low_price = float(str(row[3]).replace(',', '')) if row[3] != '--' else None
                                    close_price = float(str(row[4]).replace(',', '')) if row[4] != '--' else None
                                    change = float(str(row[5]).replace(',', '')) if row[5] != '--' else 0.0
                                    change_percent = float(str(row[6]).replace(',', '').rstrip('%')) if row[6] != '--' else 0.0
                                    all_data.append({
                                        '產業別': name,
                                        '開盤指數': open_price,
                                        '最高指數': high_price,
                                        '最低指數': low_price,
                                        '收盤指數': close_price,
                                        '漲跌點數': change,
                                        '漲跌百分比': change_percent,
                                        '日期': date
                                    })
                                except Exception:
                                    continue
                except Exception:
                    continue
            if not all_data:
                self.logger.warning("未找到任何產業指數數據")
                return False
            df = pd.DataFrame(all_data)
            if self.industry_index_file.exists():
                existing_df = pd.read_csv(self.industry_index_file)
                df = pd.concat([existing_df, df], ignore_index=True)
                df = df.drop_duplicates(subset=['日期', '產業別'], keep='last')
                df = df.sort_values(['日期', '產業別'])
            self.config.create_backup(self.industry_index_file)
            df.to_csv(self.industry_index_file, index=False, encoding='utf-8-sig')
            self.logger.info(f"成功更新產業指數數據，共 {len(df)} 筆記錄，最新日期: {df['日期'].max()}")
            return True
        except Exception as e:
            self.logger.error(f"更新產業指數數據時發生錯誤: {str(e)}")
            return False

    def update_stock_data(self) -> bool:
        """批次更新個股數據（多日）"""
        try:
            all_data = []
            date_list = pd.date_range(self.date_range.start_date, self.date_range.end_date).strftime('%Y-%m-%d')
            for date in tqdm(date_list, desc='獲取每日股票數據'):
                url = "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX"
                params = {
                    "date": datetime.strptime(date, '%Y-%m-%d').strftime('%Y%m%d'),
                    "type": "ALLBUT0999",
                    "response": "json"
                }
                try:
                    response = requests.get(url, params=params, headers=self._get_headers())
                    if response.status_code != 200:
                        continue
                    data = response.json()
                    if data.get("stat") != "OK":
                        continue
                    if 'tables' not in data or not data['tables']:
                        continue
                    for table in data['tables']:
                        if '個股行情' in table.get('title', ''):
                            for row in table.get('rows', []):
                                if len(row) < 16:
                                    continue
                                try:
                                    stock_id = row[0].strip()
                                    if not stock_id.isdigit() or len(stock_id) != 4:
                                        continue
                                    all_data.append({
                                        '證券代號': stock_id,
                                        '證券名稱': row[1],
                                        '成交股數': float(str(row[2]).replace(',', '')) if row[2] != '--' else 0,
                                        '成交筆數': float(str(row[3]).replace(',', '')) if row[3] != '--' else 0,
                                        '成交金額': float(str(row[4]).replace(',', '')) if row[4] != '--' else 0,
                                        '開盤價': float(str(row[5]).replace(',', '')) if row[5] != '--' else None,
                                        '最高價': float(str(row[6]).replace(',', '')) if row[6] != '--' else None,
                                        '最低價': float(str(row[7]).replace(',', '')) if row[7] != '--' else None,
                                        '收盤價': float(str(row[8]).replace(',', '')) if row[8] != '--' else None,
                                        '漲跌(+/-)': row[9] if row[9] != '--' else '',
                                        '漲跌價差': float(str(row[10]).replace(',', '')) if row[10] != '--' else 0,
                                        '最後揭示買價': float(str(row[11]).replace(',', '')) if row[11] != '--' else None,
                                        '最後揭示買量': float(str(row[12]).replace(',', '')) if row[12] != '--' else 0,
                                        '最後揭示賣價': float(str(row[13]).replace(',', '')) if row[13] != '--' else None,
                                        '最後揭示賣量': float(str(row[14]).replace(',', '')) if row[14] != '--' else 0,
                                        '本益比': float(str(row[15]).replace(',', '')) if row[15] != '--' else None,
                                        '日期': date
                                    })
                                except Exception:
                                    continue
                except Exception:
                    continue
            if not all_data:
                self.logger.warning("未找到任何個股數據")
                return False
            df = pd.DataFrame(all_data)
            if self.stock_data_file.exists():
                existing_df = pd.read_csv(self.stock_data_file)
                df = pd.concat([existing_df, df], ignore_index=True)
                df = df.drop_duplicates(subset=['日期', '證券代號'], keep='last')
                df = df.sort_values(['日期', '證券代號'])
            self.config.create_backup(self.stock_data_file)
            df.to_csv(self.stock_data_file, index=False, encoding='utf-8-sig')
            self.logger.info(f"成功更新個股數據，共 {len(df)} 筆記錄，最新日期: {df['日期'].max()}")
            return True
        except Exception as e:
            self.logger.error(f"更新個股數據時發生錯誤: {str(e)}")
            return False

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
            results['industry_data'] = self.update_industry_index()
            
            # 3. 更新個股數據
            self.logger.info("\n=== 更新個股數據 ===")
            results['stock_data'] = self.update_stock_data()
            
            return results
            
        except Exception as e:
            self.logger.error(f"更新過程中發生錯誤: {str(e)}")
            raise

def main():
    # 創建數據處理器
    processor = TWMarketDataProcessor(date_range=MarketDateRange.last_n_days(45))
    
    try:
        print("=== 開始台股數據更新 ===")
        print(f"日期範圍: {processor.date_range.date_range_str}")
        
        # 1. 更新大盤指數
        print("\n1. 更新大盤指數...")
        market_result = processor.update_market_index()
        if market_result:
            print("  ✓ 大盤指數更新完成")
        else:
            print("  ✗ 大盤指數更新失敗")
            
        time.sleep(3)  # 等待3秒避免請求過於頻繁
        
        # 2. 更新產業指數
        print("\n2. 更新產業指數...")
        industry_result = processor.update_industry_index()
        if industry_result:
            print("  ✓ 產業指數更新完成")
        else:
            print("  ✗ 產業指數更新失敗")
        
        time.sleep(3)
        
        # 3. 更新個股數據
        print("\n3. 更新個股數據...")
        stock_result = processor.update_stock_data()
        if stock_result:
            print("  ✓ 個股數據更新完成")
        else:
            print("  ✗ 個股數據更新失敗")
        
        print("\n=== 台股數據更新完成 ===")
        
    except Exception as e:
        print(f"\n更新過程中發生錯誤: {str(e)}")
        traceback.print_exc()

if __name__ == "__main__":
    main() 