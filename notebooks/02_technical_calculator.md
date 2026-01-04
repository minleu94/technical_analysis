```python
# 首先設定路徑和基本導入
import os
import sys
from pathlib import Path
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
import glob
import shutil
import logging
import traceback
import numpy as np
import pandas as pd
import talib
from tqdm import tqdm

# 定義配置類別
@dataclass
class TWStockConfig:
    """台股數據分析核心配置"""
    
    # 基礎路徑配置
    base_dir: Path = Path("D:/Min/Python/Project/FA_Data")  # 修改為你的數據目錄
    
    # 數據目錄
    data_dir: Path = None
    daily_price_dir: Path = None 
    meta_data_dir: Path = None
    technical_dir: Path = None
    
    # 關鍵檔案路徑
    market_index_file: Path = None
    industry_index_file: Path = None
    stock_data_file: Path = None
    
    # 數據參數
    default_start_date: str = "2014-01-01"
    backup_keep_days: int = 7
    min_data_days: int = 30
    
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
        
        # 確保所需目錄存在
        self._ensure_directories()
    
    def _ensure_directories(self):
        """確保所需目錄結構存在"""
        directories = [
            self.daily_price_dir,
            self.meta_data_dir,
            self.technical_dir,
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

class MarketDateRange:
    """市場數據日期範圍控制"""
    def __init__(self, start_date: str = None, end_date: str = None):
        self.end_date = end_date if end_date else datetime.today().strftime('%Y-%m-%d')
        self.start_date = start_date
        
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

# 設置日誌
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# 清除現有的處理器
for handler in logger.handlers[:]:
    logger.removeHandler(handler)

# 設定日誌處理器
file_handler = logging.FileHandler('technical_calculation.log', encoding='utf-8')
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))

console_handler = logging.StreamHandler()
console_handler.setFormatter(logging.Formatter('%(levelname)s: %(message)s'))
console_handler.setLevel(logging.ERROR)

logger.addHandler(file_handler)
logger.addHandler(console_handler)
```


```python
def setup_logging():
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

logger = setup_logging()
```


```python
def process_price_data(df):
    """
    處理價格數據，包含資料清理和格式轉換
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
        logging.error(f"Error in process_price_data: {e}")
        logging.error(traceback.format_exc())
        return None
```


```python
def validate_config():
    """
    驗證必要的目錄和檔案是否存在
    """
    base_path = Path("D:/Min/Python/Project/FA_Data")
    required_dirs = [
        "meta_data",
        "technical_analysis",
        "meta_data\\backup"
    ]
    
    try:
        for dir_path in required_dirs:
            full_path = os.path.join(base_path, dir_path)
            if not os.path.exists(full_path):
                os.makedirs(full_path)
                logging.info(f"Created directory: {full_path}")
                
        return True
    except Exception as e:
        logging.error(f"Error validating config: {e}")
        return False
```


```python
def preprocess_stock_data(df, stock_id):
    """資料預處理與驗證"""
    try:
        df = df.copy()
        
        # 1. 基本資料處理
        df['證券代號'] = df['證券代號'].astype(str)
        df = df.sort_values('日期').reset_index(drop=True)
        
        # 2. 處理價格欄位
        price_columns = ['開盤價', '最高價', '最低價', '收盤價']
        for col in price_columns:
            df[col] = pd.to_numeric(df[col].replace('--', np.nan), errors='coerce')
        
        # 3. 處理成交量
        volume_columns = ['成交股數', '成交筆數', '成交金額']
        for col in volume_columns:
            df[col] = pd.to_numeric(df[col].replace('--', 0), errors='coerce')
            df[col] = df[col].fillna(0)
        
        # 4. 處理暫停交易日(volume = 0)
        mask = df['成交股數'] == 0
        for col in price_columns:
            df.loc[mask, col] = df[col].ffill()
        
        # 5. 驗證數據完整性
        if df[price_columns].isnull().any().any():
            logging.warning(f"股票 {stock_id} 存在缺失值")
            df[price_columns] = df[price_columns].ffill()
            
        return df
        
    except Exception as e:
        logging.error(f"預處理股票 {stock_id} 資料時發生錯誤: {str(e)}")
        return None

def calculate_ma_series(close_prices):
    """計算移動平均線系列"""
    try:
        ma_dict = {
            'SMA30': talib.SMA(close_prices, timeperiod=30),
            'DEMA30': talib.DEMA(close_prices, timeperiod=30),
            'EMA30': talib.EMA(close_prices, timeperiod=30)
        }
        return ma_dict
    except Exception as e:
        logging.error(f"計算移動平均線時發生錯誤: {str(e)}")
        return None

def calculate_momentum_indicators(close_prices):
    """計算動量指標"""
    try:
        # RSI計算
        rsi = talib.RSI(close_prices, timeperiod=14)
        rsi = np.nan_to_num(rsi, nan=50.0)
        rsi = np.clip(rsi, 0, 100)
        
        # MACD計算
        macd, signal, hist = talib.MACD(close_prices, 
                                      fastperiod=12, 
                                      slowperiod=26, 
                                      signalperiod=9)
        
        return {
            'RSI': rsi,
            'MACD': macd,
            'MACD_signal': signal,
            'MACD_hist': hist
        }
    except Exception as e:
        logging.error(f"計算動量指標時發生錯誤: {str(e)}")
        return None

def calculate_kd_indicator(high_prices, low_prices, close_prices):
    """計算KD指標"""
    try:
        slowk, slowd = talib.STOCH(high_prices, 
                                 low_prices, 
                                 close_prices,
                                 fastk_period=5, 
                                 slowk_period=3, 
                                 slowk_matype=0,
                                 slowd_period=3, 
                                 slowd_matype=0)
                                 
        slowk = np.nan_to_num(slowk, nan=50.0)
        slowd = np.nan_to_num(slowd, nan=50.0)
        
        return {
            'slowk': np.clip(slowk, 0, 100),
            'slowd': np.clip(slowd, 0, 100)
        }
    except Exception as e:
        logging.error(f"計算KD指標時發生錯誤: {str(e)}")
        return None

def calculate_volatility_indicators(df, close_prices):
    """計算波動指標"""
    try:
        # 布林通道
        upper, middle, lower = talib.BBANDS(close_prices, 
                                          timeperiod=30,
                                          nbdevup=2,
                                          nbdevdn=2,
                                          matype=0)
                                          
        # SAR指標
        sar = talib.SAR(df['最高價'].values,
                       df['最低價'].values,
                       acceleration=0.02,
                       maximum=0.2)
                       
        # 處理SAR的極端值
        max_price = df['最高價'].max() * 1.5
        min_price = df['最低價'].min() * 0.5
        sar = np.nan_to_num(sar, nan=df['收盤價'].mean())
        sar = np.clip(sar, min_price, max_price)
        
        return {
            'middleband': middle,
            'SAR': sar
        }
    except Exception as e:
        logging.error(f"計算波動指標時發生錯誤: {str(e)}")
        return None

def calculate_trend_indicators(close_prices):
    """計算趨勢指標"""
    try:
        tsf = talib.TSF(close_prices, timeperiod=14)
        return {'TSF': tsf}
    except Exception as e:
        logging.error(f"計算趨勢指標時發生錯誤: {str(e)}")
        return None

def validate_indicator_results(df):
    """驗證指標計算結果"""
    try:
        # 確保百分比指標在0-100範圍內
        percentage_columns = ['RSI', 'slowk', 'slowd']
        for col in percentage_columns:
            if col in df.columns:
                df[col] = np.clip(df[col], 0, 100)
        
        # 處理無限值
        df = df.replace([np.inf, -np.inf], np.nan)
        
        # 填充NaN值
        df = df.ffill().bfill()
        
        return df
    except Exception as e:
        logging.error(f"驗證指標結果時發生錯誤: {str(e)}")
        return df

def calculate_and_store_indicators(df, stock_id=None):
    """計算技術指標主函數"""
    try:
        # 1. 資料準備
        df = df.copy()
        df = df.sort_values('日期').reset_index(drop=True)

        # 2. 處理價格欄位
        price_cols = ['開盤價', '最高價', '最低價', '收盤價']
        for col in price_cols:
            df[col] = pd.to_numeric(df[col].replace(['--', ''], np.nan), errors='coerce')
            df[col] = df[col].ffill()

        # 3. 處理成交量
        df['成交股數'] = pd.to_numeric(df['成交股數'].replace('--', 0), errors='coerce').fillna(0)
        
        # 4. 處理暫停交易日(volume = 0)
        mask = df['成交股數'] == 0
        if mask.any():
            for col in price_cols:
                df.loc[mask, col] = df[col].ffill()

        # 5. 獲取價格序列
        close = df['收盤價'].values
        high = df['最高價'].values
        low = df['最低價'].values
        
        # 6. 計算技術指標
        # 移動平均線
        df['SMA30'] = talib.SMA(close, timeperiod=30)
        df['DEMA30'] = talib.DEMA(close, timeperiod=30)
        df['EMA30'] = talib.EMA(close, timeperiod=30)
        
        # RSI
        rsi = talib.RSI(close, timeperiod=14)
        df['RSI'] = np.clip(np.nan_to_num(rsi, nan=50.0), 0, 100)
        
        # MACD
        macd, signal, hist = talib.MACD(close, fastperiod=12, slowperiod=26, signalperiod=9)
        df['MACD'] = macd
        df['MACD_signal'] = signal
        df['MACD_hist'] = hist
        
        # KD
        slowk, slowd = talib.STOCH(high, low, close, 
                                 fastk_period=5, 
                                 slowk_period=3,
                                 slowd_period=3)
        df['slowk'] = np.clip(np.nan_to_num(slowk, nan=50.0), 0, 100)
        df['slowd'] = np.clip(np.nan_to_num(slowd, nan=50.0), 0, 100)
        
        # 其他指標
        df['TSF'] = talib.TSF(close, timeperiod=14)
        _, df['middleband'], _ = talib.BBANDS(close, timeperiod=30, nbdevup=2, nbdevdn=2)
        df['SAR'] = talib.SAR(high, low, acceleration=0.02, maximum=0.2)
        
        # 7. 處理極端值
        df = df.replace([np.inf, -np.inf], np.nan)
        df = df.ffill().bfill()
        
        # 8. 儲存結果
        save_path = Path(f"D:/Min/Python/Project/FA_Data/technical_analysis/{stock_id}_indicators.csv")
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        df.to_csv(save_path, index=False, encoding='utf-8-sig')
        
        return df
        
    except Exception as e:
        logging.error(f"處理股票 {stock_id} 時發生錯誤: {str(e)}")
        return None
```


```python
def process_stock_data_batch():
    """批次處理股票資料"""
    try:
        # 1. 讀取資料
        base_path = Path("D:/Min/Python/Project/FA_Data")
        stock_data = pd.read_csv(
            base_path / "meta_data" / "stock_data_whole.csv",
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
                    
                result = calculate_and_store_indicators(group_df, stock_id)
                if isinstance(result, pd.DataFrame):
                    all_data.append(result)
        
        # 4. 合併並儲存結果
        if all_data:
            final_df = pd.concat(all_data, ignore_index=True)
            save_path = base_path / "meta_data" / "all_stocks_data.csv"
            final_df.to_csv(save_path, index=False, encoding='utf-8-sig')
            
            # 建立備份
            today = datetime.now().strftime('%Y%m%d')
            backup_path = base_path / "meta_data" / "backup" / f"all_stocks_data_{today}.csv"
            shutil.copy2(save_path, backup_path)
            return True
            
        return False
        
    except Exception as e:
        logging.error(f"批次處理發生錯誤: {str(e)}")
        return False
```


```python
def main():
    """主程序"""
    try:
        # 1. 初始化配置
        config = TWStockConfig()
        logging.info("開始批次處理股票技術指標...")
        
        # 2. 驗證配置
        if not validate_config():
            logging.error("配置驗證失敗")
            return False
            
        # 3. 開始批次處理
        if process_stock_data_batch():
            logging.info("批次處理完成")
            
            # 4. 檢查結果
            results_path = config.meta_data_dir / "all_stocks_data.csv"
            if results_path.exists():
                df = pd.read_csv(results_path)
                logging.info(f"總處理筆數: {len(df):,}")
                logging.info(f"股票數量: {df['證券代號'].nunique():,}")
            return True
        else:
            logging.error("批次處理失敗")
            return False
            
    except Exception as e:
        logging.error(f"主程序執行時發生錯誤: {e}")
        logging.error(traceback.format_exc())
        return False
```


```python
if __name__ == "__main__":
    setup_logging()
    if main():
        logging.info("程序執行完成")
        
        # 顯示範例結果
        try:
            example_stock = "2330"
            df = pd.read_csv(f"D:/Min/Python/Project/FA_Data/technical_analysis/{example_stock}_indicators.csv")
            print(f"\n{example_stock} 技術指標計算結果範例:")
            print(df.tail())
        except Exception as e:
            logging.error(f"顯示範例結果時發生錯誤: {e}")
    else:
        logging.error("程序執行失敗")
```

    處理 9958: 100%|██████████| 1120/1120 [01:03<00:00, 17.54it/s]
    

    
    2330 技術指標計算結果範例:
          證券代號 證券名稱      成交股數    成交筆數         成交金額     開盤價     最高價    最低價    收盤價  \
    2669  2330  台積電  38527201  132537  37951553847   980.0   995.0  976.0  988.0   
    2670  2330  台積電  42915696  192169  42199819801  1000.0  1005.0  965.0  965.0   
    2671  2330  台積電  42394920  163735  40803705615   965.0   969.0  955.0  959.0   
    2672  2330  台積電  35012870   77808  34177107575   977.0   985.0  968.0  970.0   
    2673  2330  台積電  25716157   64687  24986151171   976.0   978.0  968.0  971.0   
    
         漲跌(+/-)  ...        EMA30        RSI       MACD  MACD_signal  MACD_hist  \
    2669       +  ...  1048.829020  35.911654 -27.677385   -19.963488  -7.713898   
    2670       -  ...  1043.420696  32.290063 -29.770314   -21.924853  -7.845461   
    2671       -  ...  1037.974200  31.400437 -31.549442   -23.849771  -7.699672   
    2672       +  ...  1033.588768  34.939454 -31.706316   -25.421080  -6.285236   
    2673       +  ...  1029.550783  35.266405 -31.388125   -26.614489  -4.773636   
    
              slowk      slowd         TSF   middleband          SAR  
    2669  22.684118  19.728473  964.186813  1068.066667  1035.811304  
    2670  18.839399  19.863435  954.670330  1062.900000  1024.161495  
    2671  17.525967  19.683161  949.868132  1057.533333  1014.375656  
    2672  14.085106  16.816824  949.175824  1052.033333  1005.000000  
    2673  23.333333  18.314802  948.714286  1048.733333   996.000000  
    
    [5 rows x 29 columns]
    
