from ..signal_combiner_support import SignalCombinationMixin
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from ..technical_analysis import TechnicalAnalyzer
from .pattern_analyzer import PatternAnalyzer
from .pattern_column_support import resolve_pattern_column

class SignalCombiner(SignalCombinationMixin):
    """信號組合分析器，用於組合不同分析模組的信號並評估綜合信號的可靠性"""
    
    def __init__(self):
        """初始化信號組合分析器"""
        self.pattern_analyzer = PatternAnalyzer()
        self.technical_analyzer = TechnicalAnalyzer()
        
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
        return resolve_pattern_column(df.columns, self.reverse_mapping, eng_name)
    
    def _evaluate_signal_reliability(self, df):
        """評估信號的可靠性
        
        Args:
            df: 包含信號的DataFrame
            
        Returns:
            DataFrame: 添加信號可靠性評分的DataFrame
        """
        df_result = df.copy()
        
        # 創建信號可靠性評分列
        df_result['Signal_Reliability'] = 0.0
        
        # 根據信號強度設置基礎可靠性
        df_result.loc[df_result['Combined_Signal'] == 3, 'Signal_Reliability'] = 0.9  # 非常強的看漲信號
        df_result.loc[df_result['Combined_Signal'] == 2, 'Signal_Reliability'] = 0.7  # 強看漲信號
        df_result.loc[df_result['Combined_Signal'] == 1, 'Signal_Reliability'] = 0.5  # 弱看漲信號
        df_result.loc[df_result['Combined_Signal'] == -1, 'Signal_Reliability'] = 0.5  # 弱看跌信號
        df_result.loc[df_result['Combined_Signal'] == -2, 'Signal_Reliability'] = 0.7  # 強看跌信號
        df_result.loc[df_result['Combined_Signal'] == -3, 'Signal_Reliability'] = 0.9  # 非常強的看跌信號
        
        # 根據ADX調整可靠性（如果有）
        if 'ADX' in df_result.columns:
            # ADX > 25 表示趨勢強，增加可靠性
            df_result.loc[df_result['ADX'] > 25, 'Signal_Reliability'] *= 1.2
            # ADX < 20 表示趨勢弱，降低可靠性
            df_result.loc[df_result['ADX'] < 20, 'Signal_Reliability'] *= 0.8
        
        # 確保可靠性在 0-1 範圍內
        df_result['Signal_Reliability'] = df_result['Signal_Reliability'].clip(0, 1)
        
        return df_result
    
    def backtest_strategy(self, df, strategy_params, initial_capital=100000, commission=0.001):
        """回測組合策略
        
        Args:
            df: 包含信號的DataFrame
            strategy_params: 策略參數字典
            initial_capital: 初始資金
            commission: 交易手續費率
            
        Returns:
            dict: 回測結果
        """
        df_result = df.copy()
        close_col = self._get_column_name(df, 'Close')
        
        if not close_col:
            print("警告: 找不到收盤價列")
            return None
        
        # 設置初始資金和持倉
        capital = initial_capital
        position = 0
        trades = []
        
        # 設置信號閾值
        buy_threshold = strategy_params.get('buy_threshold', 2)  # 默認買入信號閾值為2（強看漲信號）
        sell_threshold = strategy_params.get('sell_threshold', -2)  # 默認賣出信號閾值為-2（強看跌信號）
        reliability_threshold = strategy_params.get('reliability_threshold', 0.7)  # 默認可靠性閾值為0.7
        
        # 遍歷數據
        for i in range(1, len(df_result)):
            # 獲取當前價格
            current_price = df_result[close_col].iloc[i]
            
            # 跳過NaN價格
            if pd.isna(current_price):
                continue
            
            # 獲取當前信號和可靠性
            current_signal = df_result['Combined_Signal'].iloc[i]
            current_reliability = df_result['Signal_Reliability'].iloc[i]
            
            # 跳過NaN信號或可靠性
            if pd.isna(current_signal) or pd.isna(current_reliability):
                continue
            
            # 買入信號
            if current_signal >= buy_threshold and current_reliability >= reliability_threshold and position == 0:
                # 計算可買入的股數
                shares = int(capital / current_price)
                if shares > 0:
                    # 執行買入
                    cost = shares * current_price * (1 + commission)
                    capital -= cost
                    position = shares
                    trades.append({
                        'date': df_result.index[i],
                        'action': 'buy',
                        'price': current_price,
                        'shares': shares,
                        'cost': cost,
                        'capital': capital
                    })
            
            # 賣出信號
            elif (current_signal <= sell_threshold and current_reliability >= reliability_threshold and position > 0) or \
                 (strategy_params.get('use_stop_loss', True) and position > 0 and len(trades) > 0 and 
                  current_price < trades[-1]['price'] * (1 - strategy_params.get('stop_loss_pct', 0.05))):
                # 執行賣出
                revenue = position * current_price * (1 - commission)
                capital += revenue
                trades.append({
                    'date': df_result.index[i],
                    'action': 'sell',
                    'price': current_price,
                    'shares': position,
                    'revenue': revenue,
                    'capital': capital
                })
                position = 0
        
        # 計算最終資產價值
        final_value = capital
        if position > 0:
            final_value += position * df_result[close_col].iloc[-1] * (1 - commission)
        
        # 計算回測指標
        total_return = (final_value - initial_capital) / initial_capital
        
        # 計算勝率
        if len(trades) > 1:
            profitable_trades = 0
            for i in range(0, len(trades) - 1, 2):
                if i + 1 < len(trades):  # 確保有配對的買入和賣出
                    if trades[i]['action'] == 'buy' and trades[i+1]['action'] == 'sell':
                        buy_price = trades[i]['price']
                        sell_price = trades[i+1]['price']
                        if sell_price > buy_price:
                            profitable_trades += 1
            
            win_rate = profitable_trades / (len(trades) // 2) if len(trades) >= 2 else 0
        else:
            win_rate = 0
        
        # 返回回測結果
        return {
            'initial_capital': initial_capital,
            'final_value': final_value,
            'total_return': total_return,
            'win_rate': win_rate,
            'trades': trades
        }
    
    def visualize_signals(self, df, ticker=None, save_path=None):
        """視覺化信號
        
        Args:
            df: 包含信號的DataFrame
            ticker: 股票代碼
            save_path: 圖表保存路徑
            
        Returns:
            None
        """
        close_col = self._get_column_name(df, 'Close')
        
        if not close_col:
            print("警告: 找不到收盤價列")
            return
        
        plt.figure(figsize=(15, 10))
        
        # 繪製價格
        plt.subplot(3, 1, 1)
        plt.plot(df.index, df[close_col], label='價格')
        
        # 標記信號
        buy_signals = df[df['Combined_Signal'] >= 2]
        sell_signals = df[df['Combined_Signal'] <= -2]
        
        plt.scatter(buy_signals.index, buy_signals[close_col], marker='^', color='g', s=100, label='買入信號')
        plt.scatter(sell_signals.index, sell_signals[close_col], marker='v', color='r', s=100, label='賣出信號')
        
        plt.title(f'{ticker if ticker else ""} 價格和信號')
        plt.legend()
        
        # 繪製技術指標
        plt.subplot(3, 1, 2)
        if 'RSI' in df.columns:
            plt.plot(df.index, df['RSI'], label='RSI')
            plt.axhline(y=70, color='r', linestyle='--')
            plt.axhline(y=30, color='g', linestyle='--')
        
        if all(col in df.columns for col in ['MACD', 'MACD_Signal']):
            plt.plot(df.index, df['MACD'], label='MACD')
            plt.plot(df.index, df['MACD_Signal'], label='MACD信號線')
        
        plt.title('技術指標')
        plt.legend()
        
        # 繪製信號可靠性
        plt.subplot(3, 1, 3)
        plt.bar(df.index, df['Signal_Reliability'], label='信號可靠性')
        plt.axhline(y=0.7, color='r', linestyle='--', label='可靠性閾值')
        
        plt.title('信號可靠性')
        plt.legend()
        
        plt.tight_layout()
        
        if save_path:
            plt.savefig(save_path)
