import pandas as pd
import numpy as np
from statsmodels.tsa.arima.model import ARIMA
from statsmodels.tsa.stattools import adfuller
from statsmodels.graphics.tsaplots import plot_acf, plot_pacf

class MathAnalyzer:
    """數學模型分析類"""
    
    def __init__(self):
        """初始化數學分析器"""
        self.models = {}
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
        
    def check_stationarity(self, time_series):
        """檢查時間序列的平穩性
        
        Args:
            time_series: 時間序列數據
            
        Returns:
            tuple: (ADF統計量, p值, 臨界值字典)
        """
        result = adfuller(time_series.dropna())
        return {
            'ADF統計量': result[0],
            'p值': result[1],
            '臨界值': result[4],
            '是否平穩': result[1] < 0.05
        }
    
    def fit_arima(self, time_series, order=(1,1,1)):
        """擬合ARIMA模型
        
        Args:
            time_series: 時間序列數據
            order: ARIMA模型的階數 (p,d,q)
            
        Returns:
            擬合的ARIMA模型
        """
        try:
            # 確保時間序列有頻率信息
            ts_clean = time_series.dropna()
            
            # 檢查是否有日期索引
            if isinstance(ts_clean.index, pd.DatetimeIndex):
                # 添加頻率信息
                ts_clean = ts_clean.asfreq('D')  # 假設是日頻率數據
            
            # 擬合ARIMA模型
            model = ARIMA(ts_clean, order=order)
            model_fit = model.fit()
            self.models['arima'] = model_fit
            return model_fit
        except Exception as e:
            print(f"擬合ARIMA模型時出錯: {str(e)}")
            return None
    
    def forecast_arima(self, steps=5):
        """使用ARIMA模型進行預測
        
        Args:
            steps: 預測步數
            
        Returns:
            預測結果
        """
        if 'arima' not in self.models:
            raise ValueError("ARIMA模型尚未擬合")
        
        try:
            forecast = self.models['arima'].forecast(steps=steps)
            return forecast
        except Exception as e:
            print(f"ARIMA預測時出錯: {str(e)}")
            # 返回一個默認的預測結果，避免程序崩潰
            return np.zeros(steps)
    
    def calculate_volatility(self, returns, window=20):
        """計算波動率
        
        Args:
            returns: 收益率時間序列
            window: 窗口大小
            
        Returns:
            波動率時間序列
        """
        return returns.rolling(window=window).std() * np.sqrt(252)  # 年化波動率
    
    def calculate_sharpe_ratio(self, returns, risk_free_rate=0.0):
        """計算夏普比率
        
        Args:
            returns: 收益率時間序列
            risk_free_rate: 無風險利率
            
        Returns:
            夏普比率
        """
        excess_returns = returns - risk_free_rate
        return np.sqrt(252) * excess_returns.mean() / excess_returns.std()
    
    def calculate_correlation_matrix(self, df):
        """計算相關性矩陣
        
        Args:
            df: 包含多個資產收益率的DataFrame
            
        Returns:
            相關性矩陣
        """
        return df.corr() 