import pandas as pd
import numpy as np
import logging
from pathlib import Path
from typing import Optional, List, Dict, Union, Tuple
from datetime import datetime, timedelta
import requests
import time
import yfinance as yf
from .config import TWStockConfig
from .data_loader import MarketDateRange
import re

class TWMarketDataProcessor:
    """台股市場數據處理器"""
    
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

    def _make_request(self, url: str, params: Dict = None, retries: int = None) -> Optional[requests.Response]:
        """發送HTTP請求並處理重試邏輯"""
        retries = retries or self.config.max_retries
        for attempt in range(retries):
            try:
                response = requests.get(
                    url,
                    params=params,
                    timeout=self.config.request_timeout,
                    headers=self._get_headers()
                )
                response.raise_for_status()
                return response
            except Exception as e:
                if attempt == retries - 1:
                    self.logger.error(f"請求失敗: {str(e)}")
                    return None
                time.sleep(self.config.retry_delay)
    
    def _get_headers(self) -> Dict[str, str]:
        """獲取請求頭"""
        return {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
    
    def update_market_index(self) -> bool:
        """更新大盤指數數據"""
        try:
            # 下載台灣加權指數數據
            df = yf.download('^TWII', start=self.date_range.start_date, end=self.date_range.end_date)
            
            if df.empty:
                self.logger.error("未找到有效的大盤指數數據")
                return False
            
            # 重置索引，將日期列轉為普通列
            df = df.reset_index()
            
            # 重命名列
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
            df['日期'] = df['日期'].dt.strftime('%Y/%m/%d')
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
            self.config.create_backup(self.market_index_file)
            df.to_csv(self.market_index_file, index=False, encoding='utf-8-sig')
            
            self.logger.info(f"成功更新大盤指數數據，共 {len(df)} 筆記錄")
            return True
            
        except Exception as e:
            self.logger.error(f"更新大盤指數數據時發生錯誤: {str(e)}")
            return False
    
    def update_industry_index(self) -> bool:
        """更新產業指數數據"""
        try:
            # 從證交所獲取產業指數數據
            url = "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX"
            params = {
                "date": datetime.strptime(self.date_range.end_date, '%Y-%m-%d').strftime('%Y%m%d'),
                "type": "IND",
                "response": "json"
            }
            
            response = self._make_request(url, params=params)
            if not response:
                return False
            
            data = response.json()
            if data.get("stat") != "OK":
                self.logger.error(f"API返回錯誤狀態: {data.get('stat')}")
                return False
            
            # 解析數據
            if 'tables' not in data or not data['tables']:
                self.logger.error("API響應中缺少 tables 欄位")
                return False
                
            index_data = []
            # 尋找包含產業類指數的表格
            for table in data['tables']:
                if '類股指數' in table.get('title', ''):  # 修改判斷條件
                    for row in table.get('rows', []):
                        if len(row) < 7:  # 確保至少有7個欄位
                            continue
                            
                        name = row[0].strip()
                        try:
                            # 處理數值
                            open_price = float(str(row[1]).replace(',', '')) if row[1] != '--' else None
                            high_price = float(str(row[2]).replace(',', '')) if row[2] != '--' else None
                            low_price = float(str(row[3]).replace(',', '')) if row[3] != '--' else None
                            close_price = float(str(row[4]).replace(',', '')) if row[4] != '--' else None
                            change = float(str(row[5]).replace(',', '')) if row[5] != '--' else 0.0
                            change_percent = float(str(row[6]).replace(',', '').rstrip('%')) if row[6] != '--' else 0.0
                            
                            index_data.append({
                                '產業別': name,
                                '開盤指數': open_price,
                                '最高指數': high_price,
                                '最低指數': low_price,
                                '收盤指數': close_price,
                                '漲跌點數': change,
                                '漲跌百分比': change_percent,
                                '日期': self.date_range.end_date
                            })
                        except (ValueError, IndexError) as e:
                            self.logger.warning(f"處理產業指數行資料時發生錯誤: {str(e)}, Row: {row}")
                            continue
            
            if not index_data:
                self.logger.error("未找到有效的產業指數數據")
                return False
                
            # 轉換為DataFrame
            df = pd.DataFrame(index_data)
            
            # 讀取現有數據
            if self.industry_index_file.exists():
                existing_data = pd.read_csv(self.industry_index_file)
                # 合併新舊數據，保留最新數據
                df = pd.concat([existing_data, df]).drop_duplicates(subset=['日期', '產業別'], keep='last')
            
            # 保存數據
            self.config.create_backup(self.industry_index_file)
            df.to_csv(self.industry_index_file, index=False, encoding='utf-8-sig')
            
            self.logger.info(f"成功更新產業指數數據，共 {len(df)} 筆記錄")
            return True
            
        except Exception as e:
            self.logger.error(f"更新產業指數數據時發生錯誤: {str(e)}")
            return False
    
    def update_stock_data(self) -> bool:
        """更新個股數據"""
        try:
            # 從證交所獲取個股數據
            url = "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX"
            params = {
                "date": datetime.strptime(self.date_range.end_date, '%Y-%m-%d').strftime('%Y%m%d'),
                "type": "ALLBUT0999",  # 排除權證
                "response": "json"
            }
            
            response = self._make_request(url, params=params)
            if not response:
                return False
            
            data = response.json()
            if data.get("stat") != "OK":
                self.logger.error(f"API返回錯誤狀態: {data.get('stat')}")
                return False
            
            # 解析數據
            if 'tables' not in data or not data['tables']:
                self.logger.error("API響應中缺少 tables 欄位")
                return False
                
            stock_data = []
            # 尋找包含個股資訊的表格
            for table in data['tables']:
                if '個股行情' in table.get('title', ''):
                    for row in table.get('rows', []):
                        if len(row) < 16:  # 確保至少有16個欄位
                            continue
                            
                        try:
                            stock_id = row[0].strip()
                            # 只處理4位數的股票代碼
                            if not stock_id.isdigit() or len(stock_id) != 4:
                                continue
                                
                            stock_data.append({
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
                                '日期': self.date_range.end_date
                            })
                        except (ValueError, IndexError) as e:
                            self.logger.warning(f"處理個股行資料時發生錯誤: {str(e)}, Row: {row}")
                            continue
            
            if not stock_data:
                self.logger.error("未找到有效的個股數據")
                return False
                
            # 轉換為DataFrame
            df = pd.DataFrame(stock_data)
            
            # 讀取現有數據
            if self.stock_data_file.exists():
                existing_data = pd.read_csv(self.stock_data_file)
                # 合併新舊數據，保留最新數據
                df = pd.concat([existing_data, df]).drop_duplicates(
                    subset=['日期', '證券代號'], keep='last'
                )
            
            # 保存數據
            self.config.create_backup(self.stock_data_file)
            df.to_csv(self.stock_data_file, index=False, encoding='utf-8-sig')
            
            self.logger.info(f"成功更新個股數據，共 {len(df)} 筆記錄")
            return True
            
        except Exception as e:
            self.logger.error(f"更新個股數據時發生錯誤: {str(e)}")
            return False
    
    def check_data_consistency(self) -> bool:
        """檢查數據一致性"""
        try:
            # 讀取各個數據文件
            market_df = pd.read_csv(self.market_index_file)
            industry_df = pd.read_csv(self.industry_index_file) if self.industry_index_file.exists() else pd.DataFrame()
            stock_df = pd.read_csv(self.stock_data_file, low_memory=False) if self.stock_data_file.exists() else pd.DataFrame()

            # 統一日期格式為 YYYY/MM/DD
            def standardize_date(date_str):
                try:
                    if pd.isna(date_str):
                        return None
                    if isinstance(date_str, float):
                        return None
                    # 移除多餘的斜線
                    date_str = re.sub(r'/{2,}', '/', date_str)
                    # 如果是 YYYYMMDD 格式
                    if len(date_str) == 8 and date_str.isdigit():
                        return f"{date_str[:4]}/{date_str[4:6]}/{date_str[6:]}"
                    # 如果已經是 YYYY/MM/DD 格式
                    if re.match(r'\d{4}/\d{2}/\d{2}', date_str):
                        return date_str
                    # 嘗試轉換其他格式
                    date_obj = pd.to_datetime(date_str)
                    return date_obj.strftime('%Y/%m/%d')
                except Exception as e:
                    self.logger.warning(f"無法轉換日期格式: {date_str}")
                    return None

            # 處理日期格式
            if not market_df.empty:
                market_df['日期'] = market_df['日期'].apply(standardize_date)
                market_df = market_df[market_df['日期'].notna()]
                market_latest = market_df['日期'].max()
                self.logger.info(f"大盤指數最新日期: {market_latest}")

            if not industry_df.empty:
                industry_df['日期'] = industry_df['日期'].apply(standardize_date)
                industry_df = industry_df[industry_df['日期'].notna()]
                industry_latest = industry_df['日期'].max()
                self.logger.info(f"產業指數最新日期: {industry_latest}")

            if not stock_df.empty:
                stock_df['日期'] = stock_df['日期'].apply(standardize_date)
                stock_df = stock_df[stock_df['日期'].notna()]
                stock_latest = stock_df['日期'].max()
                self.logger.info(f"個股數據最新日期: {stock_latest}")

            # 檢查日期範圍一致性
            if not market_df.empty and not industry_df.empty:
                market_dates = set(market_df['日期'].dropna())
                industry_dates = set(industry_df['日期'].dropna())
                
                if market_dates != industry_dates:
                    self.logger.warning("大盤指數和產業指數的日期範圍不一致")
                    missing_in_market = industry_dates - market_dates
                    if missing_in_market:
                        self.logger.warning(f"大盤指數缺少以下日期: {missing_in_market}")
                    missing_in_industry = market_dates - industry_dates
                    if missing_in_industry:
                        self.logger.warning(f"產業指數缺少以下日期: {missing_in_industry}")

            return True

        except Exception as e:
            self.logger.error(f"檢查數據一致性時發生錯誤: {str(e)}")
            return False
    
    def generate_report(self) -> str:
        """生成數據更新報告"""
        try:
            # 讀取各個數據文件
            market_df = pd.read_csv(self.market_index_file)
            industry_df = pd.read_csv(self.industry_index_file) if self.industry_index_file.exists() else pd.DataFrame()
            stock_df = pd.read_csv(self.stock_data_file, low_memory=False) if self.stock_data_file.exists() else pd.DataFrame()

            # 統一日期格式
            def standardize_date(date_str):
                try:
                    if pd.isna(date_str):
                        return None
                    if isinstance(date_str, float):
                        return None
                    # 移除多餘的斜線
                    date_str = re.sub(r'/{2,}', '/', date_str)
                    # 如果是 YYYYMMDD 格式
                    if len(date_str) == 8 and date_str.isdigit():
                        return f"{date_str[:4]}/{date_str[4:6]}/{date_str[6:]}"
                    # 如果已經是 YYYY/MM/DD 格式
                    if re.match(r'\d{4}/\d{2}/\d{2}', date_str):
                        return date_str
                    # 嘗試轉換其他格式
                    date_obj = pd.to_datetime(date_str)
                    return date_obj.strftime('%Y/%m/%d')
                except Exception:
                    return None

            # 處理日期格式
            if not market_df.empty:
                market_df['日期'] = market_df['日期'].apply(standardize_date)
                market_df = market_df[market_df['日期'].notna()]
                market_df['日期'] = pd.to_datetime(market_df['日期'])

            if not industry_df.empty:
                industry_df['日期'] = industry_df['日期'].apply(standardize_date)
                industry_df = industry_df[industry_df['日期'].notna()]

            if not stock_df.empty:
                stock_df['日期'] = stock_df['日期'].apply(standardize_date)
                stock_df = stock_df[stock_df['日期'].notna()]

            # 生成報告
            report = f"數據更新報告 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            report += f"更新範圍: 從 {self.date_range.start_date} 到 {self.date_range.end_date}\n\n"

            # 大盤指數報告
            report += "大盤指數數據:\n"
            if not market_df.empty:
                report += f"- 記錄數: {len(market_df)}\n"
                report += f"- 日期範圍: {market_df['日期'].min().strftime('%Y/%m/%d')} 到 {market_df['日期'].max().strftime('%Y/%m/%d')}\n\n"
            else:
                report += "- 無數據\n\n"

            # 產業指數報告
            report += "產業指數數據:\n"
            if not industry_df.empty:
                industry_count = len(industry_df['產業別'].unique()) if '產業別' in industry_df.columns else 0
                report += f"- 記錄數: {len(industry_df)}\n"
                report += f"- 產業數: {industry_count}\n\n"
            else:
                report += "- 無數據\n\n"

            # 個股數據報告
            report += "個股數據:\n"
            if not stock_df.empty:
                stock_count = len(stock_df['股票代號'].unique()) if '股票代號' in stock_df.columns else 0
                report += f"- 記錄數: {len(stock_df)}\n"
                report += f"- 股票數: {stock_count}\n"
            else:
                report += "- 無數據\n"

            print(report)
            self.logger.info("成功生成數據更新報告")
            return True

        except Exception as e:
            self.logger.error(f"生成報告時發生錯誤: {str(e)}")
            return False 