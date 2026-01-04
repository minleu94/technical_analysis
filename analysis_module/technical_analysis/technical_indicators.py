import pandas as pd
import numpy as np
import talib
import logging
import traceback
from pathlib import Path
import os

class TechnicalIndicatorCalculator:
    """技術指標計算類別，基於02_technical_calculator.md中的功能"""
    
    def __init__(self, logger=None):
        """初始化技術指標計算器
        
        Args:
            logger: 日誌記錄器，如果為None則創建新的記錄器
        """
        self.logger = logger or self._setup_logging()
        
        # 定義列名映射，將中文列名映射到英文列名
        self.column_mapping = {
            # 中文列名 -> 英文列名
            '收盤價': 'Close',
            '開盤價': 'Open',
            '最高價': 'High',
            '最低價': 'Low',
            '成交量': 'Volume',
            '成交股數': 'Volume'
        }
        # 反向映射，將英文列名映射到中文列名
        self.reverse_mapping = {v: k for k, v in self.column_mapping.items()}
    
    def _setup_logging(self):
        """設置日誌記錄"""
        logger = logging.getLogger(__name__)
        logger.setLevel(logging.INFO)
        
        # 清除現有的處理器
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)
        
        # 檔案處理器
        file_handler = logging.FileHandler('technical_calculation.log', encoding='utf-8')
        file_handler.setFormatter(
            logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        )
        
        # 控制台處理器
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(
            logging.Formatter('%(levelname)s: %(message)s')
        )
        console_handler.setLevel(logging.ERROR)
        
        logger.addHandler(file_handler)
        logger.addHandler(console_handler)
        return logger
    
    def _get_column_name(self, df, eng_name):
        """獲取對應的列名，優先使用中文列名，如果不存在則使用英文列名
        
        Args:
            df: 數據DataFrame
            eng_name: 英文列名
            
        Returns:
            str: 對應的列名
        """
        # 檢查中文列名是否存在
        if self.reverse_mapping.get(eng_name) in df.columns:
            return self.reverse_mapping.get(eng_name)
        # 檢查英文列名是否存在
        elif eng_name in df.columns:
            return eng_name
        # 都不存在，返回None
        return None
    
    def process_price_data(self, df):
        """處理價格數據，包含資料清理和格式轉換
        
        Args:
            df: 原始價格數據DataFrame
            
        Returns:
            DataFrame: 處理後的價格數據
        """
        try:
            # 複製DataFrame避免修改原始資料
            df = df.copy()
            # 處理漲跌符號欄位中的 HTML 標籤
            if '漲跌(+/-)' in df.columns:
                replace_dict = {
                    '<p style= color:red>+</p>': '+',
                    '<p style= color:green>-</p>': '-',
                    '<p style =color:red>+</p>': '+',
                    '<p style =color:green>-</p>': '-'
                }
                df['漲跌(+/-)'] = df['漲跌(+/-)'].map(lambda x: replace_dict.get(x, x))
            
            # 處理價格欄位
            price_columns = ['開盤價', '最高價', '最低價', '收盤價', '最後揭示買價', '最後揭示賣價']
            for col in price_columns:
                if col in df.columns:
                    df[col] = df[col].apply(lambda x: str(x).replace(',', '') if isinstance(x, str) else x)
                    df[col] = pd.to_numeric(df[col], errors='coerce')
            
            # 處理成交量欄位
            volume_columns = ['成交股數', '成交筆數', '成交金額']
            for col in volume_columns:
                if col in df.columns:
                    df[col] = df[col].apply(lambda x: str(x).replace(',', '') if isinstance(x, str) else x)
                    df[col] = pd.to_numeric(df[col], errors='coerce')
            
            # 處理日期欄位
            if '日期' in df.columns:
                df['日期'] = pd.to_datetime(df['日期']).dt.strftime('%Y-%m-%d')
                
            # 處理特殊字符
            df = df.replace('--', np.nan)
            df = df.replace('', np.nan)
            
            return df
            
        except Exception as e:
            self.logger.error(f"處理價格數據時發生錯誤: {e}")
            self.logger.error(traceback.format_exc())
            return None
    
    def preprocess_stock_data(self, df, stock_id):
        """資料預處理與驗證
        
        Args:
            df: 原始股票數據DataFrame
            stock_id: 股票代號
            
        Returns:
            DataFrame: 預處理後的股票數據
        """
        try:
            df = df.copy()
            
            # 1. 基本資料處理
            if '證券代號' in df.columns:
                df['證券代號'] = df['證券代號'].astype(str)
            if '日期' in df.columns:
                df = df.sort_values('日期').reset_index(drop=True)
            
            # 2. 處理價格欄位
            price_columns = ['開盤價', '最高價', '最低價', '收盤價']
            for col in price_columns:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col].replace('--', np.nan), errors='coerce')
            
            # 3. 處理成交量
            volume_columns = ['成交股數', '成交筆數', '成交金額']
            for col in volume_columns:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col].replace('--', 0), errors='coerce')
                    df[col] = df[col].fillna(0)
            
            # 4. 處理暫停交易日(volume = 0)
            if '成交股數' in df.columns:
                mask = df['成交股數'] == 0
                for col in price_columns:
                    if col in df.columns and mask.any():
                        df.loc[mask, col] = df[col].ffill()
            
            # 5. 驗證數據完整性
            if any(col in df.columns for col in price_columns):
                if df[list(col for col in price_columns if col in df.columns)].isnull().any().any():
                    self.logger.debug(f"股票 {stock_id} 存在缺失值")
                    for col in price_columns:
                        if col in df.columns:
                            df[col] = df[col].ffill()
                    
            return df
            
        except Exception as e:
            self.logger.error(f"預處理股票 {stock_id} 資料時發生錯誤: {str(e)}")
            return None
    
    def calculate_ma_series(self, df):
        """計算移動平均線系列
        
        Args:
            df: 股票數據DataFrame
            
        Returns:
            DataFrame: 添加移動平均線後的DataFrame
        """
        try:
            df_result = df.copy()
            close_col = self._get_column_name(df, 'Close')
            
            if close_col:
                close_prices = np.ascontiguousarray(df[close_col].values, dtype=np.float64)
                df_result['SMA30'] = talib.SMA(close_prices, timeperiod=30)
                df_result['DEMA30'] = talib.DEMA(close_prices, timeperiod=30)
                df_result['EMA30'] = talib.EMA(close_prices, timeperiod=30)
                
            return df_result
            
        except Exception as e:
            self.logger.error(f"計算移動平均線時發生錯誤: {str(e)}")
            return df.copy()
    
    def calculate_momentum_indicators(self, df):
        """計算動量指標
        
        Args:
            df: 股票數據DataFrame
            
        Returns:
            Dict: 包含動量指標的字典
        """
        try:
            result = {}
            close_col = self._get_column_name(df, 'Close')
            
            if close_col:
                # 清理價格序列（處理 '--' 和其他無效值）
                def clean_price_series(series):
                    """清理價格序列"""
                    if series.dtype == 'object':
                        series = series.replace(['--', '', 'nan', 'NaN', 'None'], np.nan)
                        series = pd.to_numeric(series, errors='coerce')
                    # 轉換為 numpy array
                    prices = np.ascontiguousarray(series.values, dtype=np.float64)
                    # 填充 NaN
                    mask = np.isnan(prices)
                    if mask.any():
                        prices = pd.Series(prices).ffill().bfill().fillna(0.0).values
                    return prices
                
                close_prices = clean_price_series(df[close_col])
                
                # RSI計算
                rsi = talib.RSI(close_prices, timeperiod=14)
                result['RSI'] = np.clip(np.nan_to_num(rsi, nan=50.0), 0, 100)
                
                # MACD計算
                macd, signal, hist = talib.MACD(close_prices, 
                                           fastperiod=12, 
                                           slowperiod=26, 
                                           signalperiod=9)
                result['MACD'] = macd
                result['MACD_signal'] = signal
                result['MACD_hist'] = hist
                
            return result
            
        except Exception as e:
            self.logger.error(f"計算動量指標時發生錯誤: {str(e)}")
            return {}
    
    def calculate_kd_indicator(self, df):
        """計算KD指標
        
        Args:
            df: 股票數據DataFrame
            
        Returns:
            Dict: 包含KD指標的字典
        """
        try:
            result = {}
            high_col = self._get_column_name(df, 'High')
            low_col = self._get_column_name(df, 'Low')
            close_col = self._get_column_name(df, 'Close')
            
            if high_col and low_col and close_col:
                # 清理價格序列（處理 '--' 和其他無效值）
                def clean_price_series(series):
                    """清理價格序列"""
                    if series.dtype == 'object':
                        series = series.replace(['--', '', 'nan', 'NaN', 'None'], np.nan)
                        series = pd.to_numeric(series, errors='coerce')
                    # 轉換為 numpy array
                    prices = np.ascontiguousarray(series.values, dtype=np.float64)
                    # 填充 NaN
                    mask = np.isnan(prices)
                    if mask.any():
                        prices = pd.Series(prices).ffill().bfill().fillna(0.0).values
                    return prices
                
                high_prices = clean_price_series(df[high_col])
                low_prices = clean_price_series(df[low_col])
                close_prices = clean_price_series(df[close_col])
                
                slowk, slowd = talib.STOCH(high_prices, 
                                      low_prices, 
                                      close_prices,
                                      fastk_period=5, 
                                      slowk_period=3, 
                                      slowk_matype=0,
                                      slowd_period=3, 
                                      slowd_matype=0)
                                     
                result['slowk'] = np.clip(np.nan_to_num(slowk, nan=50.0), 0, 100)
                result['slowd'] = np.clip(np.nan_to_num(slowd, nan=50.0), 0, 100)
                
            return result
            
        except Exception as e:
            self.logger.error(f"計算KD指標時發生錯誤: {str(e)}")
            return {}
    
    def calculate_volatility_indicators(self, df):
        """計算波動指標
        
        Args:
            df: 股票數據DataFrame
            
        Returns:
            Dict: 包含波動指標的字典
        """
        try:
            result = {}
            high_col = self._get_column_name(df, 'High')
            low_col = self._get_column_name(df, 'Low')
            close_col = self._get_column_name(df, 'Close')
            
            if close_col:
                close_prices = np.ascontiguousarray(df[close_col].values, dtype=np.float64)
                
                # 布林通道
                upper, middle, lower = talib.BBANDS(close_prices, 
                                              timeperiod=30,
                                              nbdevup=2,
                                              nbdevdn=2,
                                              matype=0)
                result['middleband'] = middle
                result['upperband'] = upper
                result['lowerband'] = lower
                
            if high_col and low_col:
                high_prices = np.ascontiguousarray(df[high_col].values, dtype=np.float64)
                low_prices = np.ascontiguousarray(df[low_col].values, dtype=np.float64)
                
                # SAR指標
                sar = talib.SAR(high_prices,
                           low_prices,
                           acceleration=0.02,
                           maximum=0.2)
                
                if close_col:
                    # 處理SAR的極端值
                    max_price = df[high_col].max() * 1.5
                    min_price = df[low_col].min() * 0.5
                    sar = np.nan_to_num(sar, nan=df[close_col].mean())
                    sar = np.clip(sar, min_price, max_price)
                    
                result['SAR'] = sar
                
            return result
            
        except Exception as e:
            self.logger.error(f"計算波動指標時發生錯誤: {str(e)}")
            return {}
    
    def calculate_trend_indicators(self, df):
        """計算趨勢指標
        
        Args:
            df: 股票數據DataFrame
            
        Returns:
            Dict: 包含趨勢指標的字典
        """
        try:
            result = {}
            close_col = self._get_column_name(df, 'Close')
            
            if close_col:
                # 清理數據：將 '--' 和其他無效值轉換為 NaN
                close_series = df[close_col].copy()
                if close_series.dtype == 'object':
                    # 替換 '--' 和其他無效字符串
                    close_series = close_series.replace(['--', '', 'nan', 'NaN', 'None'], np.nan)
                    # 嘗試轉換為數值
                    close_series = pd.to_numeric(close_series, errors='coerce')
                
                # 轉換為 numpy array，處理 NaN
                close_prices = np.ascontiguousarray(close_series.values, dtype=np.float64)
                
                # 填充 NaN 值（使用前向填充和後向填充）
                mask = np.isnan(close_prices)
                if mask.any():
                    close_prices = pd.Series(close_prices).ffill().bfill().fillna(0.0).values
                
                result['TSF'] = talib.TSF(close_prices, timeperiod=14)
                
            return result
            
        except Exception as e:
            self.logger.error(f"計算趨勢指標時發生錯誤: {str(e)}")
            return {}
    
    def validate_indicator_results(self, df):
        """驗證指標計算結果
        
        Args:
            df: 含技術指標的DataFrame
            
        Returns:
            DataFrame: 驗證並修正後的DataFrame
        """
        try:
            df_result = df.copy()
            
            # 確保百分比指標在0-100範圍內
            percentage_columns = ['RSI', 'slowk', 'slowd']
            for col in percentage_columns:
                if col in df_result.columns:
                    df_result[col] = np.clip(df_result[col], 0, 100)
            
            # 處理無限值
            df_result = df_result.replace([np.inf, -np.inf], np.nan)
            
            # 填充NaN值
            df_result = df_result.ffill().bfill()
            
            return df_result
            
        except Exception as e:
            self.logger.error(f"驗證指標結果時發生錯誤: {str(e)}")
            return df.copy()
    
    def calculate_all_indicators(self, df, stock_id=None):
        """計算所有技術指標
        
        Args:
            df: 股票數據DataFrame
            stock_id: 股票代號，用於日誌記錄
            
        Returns:
            DataFrame: 添加所有技術指標後的DataFrame
        """
        try:
            # 1. 資料預處理
            df_result = self.preprocess_stock_data(df, stock_id)
            if df_result is None:
                return None
                
            # 2. 計算各類指標
            # 計算移動平均線
            ma_result = self.calculate_ma_series(df_result)
            if not isinstance(ma_result, pd.DataFrame):
                return None
            df_result = ma_result
            
            # 計算動量指標
            momentum_indicators = self.calculate_momentum_indicators(df_result)
            if momentum_indicators:
                for key, value in momentum_indicators.items():
                    df_result[key] = value
            
            # 計算KD指標
            kd_indicators = self.calculate_kd_indicator(df_result)
            if kd_indicators:
                for key, value in kd_indicators.items():
                    df_result[key] = value
            
            # 計算波動指標
            volatility_indicators = self.calculate_volatility_indicators(df_result)
            if volatility_indicators:
                for key, value in volatility_indicators.items():
                    df_result[key] = value
            
            # 計算趨勢指標
            trend_indicators = self.calculate_trend_indicators(df_result)
            if trend_indicators:
                for key, value in trend_indicators.items():
                    df_result[key] = value
            
            # 3. 驗證結果
            df_result = self.validate_indicator_results(df_result)
            
            return df_result
            
        except Exception as e:
            self.logger.error(f"計算股票 {stock_id} 的技術指標時發生錯誤: {str(e)}")
            self.logger.error(traceback.format_exc())
            return None
    
    def calculate_and_store_indicators(self, df, stock_id=None, output_dir=None, ignore_existing=False):
        """計算技術指標並保存結果（會合併現有數據，避免覆蓋）
        
        Args:
            df: 股票數據DataFrame
            stock_id: 股票代號
            output_dir: 輸出目錄，如果為None則使用默認目錄
            ignore_existing: 如果為 True，忽略現有文件，直接覆蓋（用於修復有問題的文件）
            
        Returns:
            DataFrame: 計算好的技術指標DataFrame（包含合併後的完整數據）
        """
        try:
            # 計算所有指標
            result_df = self.calculate_all_indicators(df, stock_id)
            if result_df is None:
                return None
                
            # 保存結果 - 使用傳入的 output_dir，避免硬編碼路徑
            if stock_id:
                if output_dir is None:
                    # 如果沒有指定 output_dir，使用當前工作目錄下的 technical_analysis
                    # 這應該由調用者確保傳入正確的 output_dir
                    raise ValueError(f"必須指定 output_dir 參數，不允許使用硬編碼路徑。股票: {stock_id}")
                else:
                    output_path = Path(output_dir) / f"{stock_id}_indicators.csv"
                
                os.makedirs(os.path.dirname(output_path), exist_ok=True)
                
                # ✅ 修復：合併現有數據，避免覆蓋（添加數據驗證）
                if output_path.exists() and not ignore_existing:
                    try:
                        # 讀取現有數據
                        existing_df = pd.read_csv(output_path, encoding='utf-8-sig')
                        self.logger.info(f"讀取現有指標文件: {output_path}，包含 {len(existing_df)} 筆數據")
                        
                        # ✅ 數據驗證：檢查現有數據是否有效
                        if len(existing_df) == 0:
                            self.logger.warning(f"現有指標文件為空，將使用新數據覆蓋")
                        elif '日期' not in existing_df.columns:
                            self.logger.warning(f"現有指標文件缺少日期欄位，將使用新數據覆蓋")
                            existing_df = None  # 標記為無效，使用新數據
                        else:
                            # 檢查日期欄位是否有有效數據
                            date_col = pd.to_datetime(existing_df['日期'], errors='coerce')
                            valid_dates = date_col.notna().sum()
                            if valid_dates == 0:
                                self.logger.warning(f"現有指標文件的日期欄位無效，將使用新數據覆蓋")
                                existing_df = None  # 標記為無效，使用新數據
                        
                        # 如果現有數據有效，進行合併
                        if existing_df is not None and len(existing_df) > 0:
                            # 確保日期欄位存在且格式一致
                            if '日期' in existing_df.columns and '日期' in result_df.columns:
                                # 轉換日期為字符串格式以便比較
                                existing_df['日期'] = pd.to_datetime(existing_df['日期'], errors='coerce').dt.strftime('%Y-%m-%d')
                                result_df['日期'] = pd.to_datetime(result_df['日期'], errors='coerce').dt.strftime('%Y-%m-%d')
                                
                                # ✅ 數據驗證：檢查合併前的數據完整性
                                # 檢查是否有必要的欄位
                                required_cols = ['日期', '證券代號']
                                missing_cols = [col for col in required_cols if col not in existing_df.columns]
                                if missing_cols:
                                    self.logger.warning(f"現有指標文件缺少必要欄位 {missing_cols}，將使用新數據覆蓋")
                                    existing_df = None
                                else:
                                    # 合併數據（保留所有列）
                                    merged_df = pd.concat([existing_df, result_df], ignore_index=True)
                                    
                                    # 去重（基於日期，保留最後一條）
                                    merged_df = merged_df.drop_duplicates(subset=['日期'], keep='last')
                                    
                                    # 按日期排序
                                    merged_df['日期'] = pd.to_datetime(merged_df['日期'], errors='coerce')
                                    merged_df = merged_df.sort_values('日期')
                                    merged_df['日期'] = merged_df['日期'].dt.strftime('%Y-%m-%d')
                                    
                                    self.logger.info(f"合併後數據: {len(merged_df)} 筆（原有 {len(existing_df)} 筆，新增 {len(result_df)} 筆）")
                                    result_df = merged_df
                            else:
                                # 如果沒有日期欄位，直接合併
                                self.logger.warning(f"警告：指標文件缺少日期欄位，將直接合併數據")
                                result_df = pd.concat([existing_df, result_df], ignore_index=True)
                                result_df = result_df.drop_duplicates(keep='last')
                            
                    except Exception as e:
                        self.logger.warning(f"讀取現有指標文件時發生錯誤，將覆蓋文件: {e}")
                        import traceback
                        self.logger.debug(f"詳細錯誤信息: {traceback.format_exc()}")
                        # 如果讀取失敗，繼續使用新數據
                
                # 保存合併後的數據
                result_df.to_csv(output_path, index=False, encoding='utf-8-sig')
                self.logger.info(f"已保存 {stock_id} 的技術指標到 {output_path}（共 {len(result_df)} 筆數據）")
                
            return result_df
            
        except Exception as e:
            self.logger.error(f"處理並保存股票 {stock_id} 的技術指標時發生錯誤: {str(e)}")
            self.logger.error(traceback.format_exc())
            return None
    
    def process_stock_data_batch(self, stock_data_path="D:/Min/Python/Project/FA_Data/meta_data/stock_data_whole.csv"):
        """批次處理股票資料
        
        Args:
            stock_data_path: 股票數據檔案路徑
            
        Returns:
            bool: 處理成功返回True，否則返回False
        """
        try:
            import shutil
            from datetime import datetime
            from tqdm import tqdm
            
            # 1. 讀取資料
            self.logger.info(f"開始批次處理股票技術指標，讀取數據從: {stock_data_path}")
            stock_data = pd.read_csv(
                stock_data_path,
                dtype={'證券代號': str}
            )
            
            # 2. 只保留4位數股票
            stock_data = stock_data[stock_data['證券代號'].str.match(r'^\d{4}$')]
            
            # 3. 批次處理
            all_data = []
            grouped = stock_data.groupby('證券代號')
            
            with tqdm(grouped, desc="處理進度") as pbar:
                for stock_id, group_df in pbar:
                    pbar.set_description(f"處理 {stock_id}")
                    
                    if len(group_df) < 30:
                        continue
                        
                    result = self.calculate_and_store_indicators(group_df, stock_id)
                    if isinstance(result, pd.DataFrame):
                        all_data.append(result)
            
            # 4. 合併並儲存結果
            if all_data:
                final_df = pd.concat(all_data, ignore_index=True)
                # 使用與02完全一致的路徑
                save_path = Path("D:/Min/Python/Project/FA_Data/meta_data/all_stocks_data.csv")
                os.makedirs(os.path.dirname(save_path), exist_ok=True)
                final_df.to_csv(save_path, index=False, encoding='utf-8-sig')
                
                # 建立備份
                today = datetime.now().strftime('%Y%m%d')
                backup_path = Path("D:/Min/Python/Project/FA_Data/meta_data/backup") / f"all_stocks_data_{today}.csv"
                os.makedirs(os.path.dirname(backup_path), exist_ok=True)
                shutil.copy2(save_path, backup_path)
                self.logger.info(f"已保存合併數據到 {save_path} 並備份到 {backup_path}")
                
                return True
                
            return False
            
        except Exception as e:
            self.logger.error(f"批次處理發生錯誤: {str(e)}")
            self.logger.error(traceback.format_exc())
            return False
    
    def main(self):
        """主程序
        
        Returns:
            bool: 執行成功返回True，否則返回False
        """
        try:
            self.logger.info("開始批次處理股票技術指標...")
            
            # 1. 驗證目錄結構
            base_path = Path("D:/Min/Python/Project/FA_Data")
            required_dirs = [
                "meta_data",
                "technical_analysis",
                "meta_data/backup"
            ]
            
            for dir_path in required_dirs:
                full_path = os.path.join(base_path, dir_path)
                if not os.path.exists(full_path):
                    os.makedirs(full_path)
                    self.logger.info(f"Created directory: {full_path}")
            
            # 2. 開始批次處理
            if self.process_stock_data_batch():
                self.logger.info("批次處理完成")
                
                # 3. 檢查結果
                results_path = base_path / "meta_data" / "all_stocks_data.csv"
                if results_path.exists():
                    df = pd.read_csv(results_path)
                    self.logger.info(f"總處理筆數: {len(df):,}")
                    self.logger.info(f"股票數量: {df['證券代號'].nunique():,}")
                return True
            else:
                self.logger.error("批次處理失敗")
                return False
                
        except Exception as e:
            self.logger.error(f"主程序執行時發生錯誤: {e}")
            self.logger.error(traceback.format_exc())
            return False


# 如果直接運行該模塊，則執行主程序
if __name__ == "__main__":
    calculator = TechnicalIndicatorCalculator()
    if calculator.main():
        calculator.logger.info("程序執行完成")
        
        # 顯示範例結果
        try:
            example_stock = "2330"
            df = pd.read_csv(f"D:/Min/Python/Project/FA_Data/technical_analysis/{example_stock}_indicators.csv")
            print(f"\n{example_stock} 技術指標計算結果範例:")
            print(df.tail())
        except Exception as e:
            calculator.logger.error(f"顯示範例結果時發生錯誤: {e}")
    else:
        calculator.logger.error("程序執行失敗") 