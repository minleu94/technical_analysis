import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from ..technical_analysis import TechnicalAnalyzer
from ..pattern_analysis import PatternAnalyzer

class SignalCombiner:
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
        # 檢查中文列名是否存在
        if self.reverse_mapping.get(eng_name) in df.columns:
            return self.reverse_mapping.get(eng_name)
        # 檢查英文列名是否存在
        elif eng_name in df.columns:
            return eng_name
        # 都不存在，返回None
        return None
    
    def analyze_combined_signals(self, df, pattern_types=None, technical_indicators=None, volume_conditions=None):
        """分析組合信號
        
        Args:
            df: 數據DataFrame
            pattern_types: 要識別的形態類型列表，例如 ['W底', '頭肩頂', '頭肩底']
            technical_indicators: 要計算的技術指標列表，例如 ['momentum', 'volatility', 'trend']
            volume_conditions: 要檢查的交易量條件列表，例如 ['increasing', 'decreasing', 'spike']
            
        Returns:
            DataFrame: 包含組合信號的DataFrame
        """
        df_result = df.copy()
        
        # 識別形態
        patterns_found = {}
        if pattern_types:
            for pattern_type in pattern_types:
                patterns_found[pattern_type] = self.pattern_analyzer.identify_pattern(df, pattern_type)
        
        # 計算技術指標
        if technical_indicators:
            if 'momentum' in technical_indicators:
                df_result = self.technical_analyzer.add_momentum_indicators(df_result)
            if 'volatility' in technical_indicators:
                df_result = self.technical_analyzer.add_volatility_indicators(df_result)
            if 'trend' in technical_indicators:
                df_result = self.technical_analyzer.add_trend_indicators(df_result)
        
        # 分析交易量
        if volume_conditions:
            df_result = self._analyze_volume(df_result, volume_conditions)
        
        # 組合信號
        signals = self._combine_signals(df_result, patterns_found)
        
        # 評估信號可靠性
        signals = self._evaluate_signal_reliability(signals)
        
        return signals
    
    def _analyze_volume(self, df, volume_conditions):
        """分析交易量
        
        Args:
            df: 數據DataFrame
            volume_conditions: 要檢查的交易量條件列表
            
        Returns:
            DataFrame: 添加交易量分析結果的DataFrame
        """
        df_result = df.copy()
        volume_col = self._get_column_name(df, 'Volume')
        
        if not volume_col:
            print("警告: 找不到交易量列")
            return df_result
        
        # 計算交易量的移動平均
        df_result['Volume_MA5'] = df[volume_col].rolling(window=5).mean()
        df_result['Volume_MA20'] = df[volume_col].rolling(window=20).mean()
        
        # 檢查交易量是否增加
        df_result['Volume_Increasing'] = (df[volume_col] > df_result['Volume_MA5']).astype(int)
        
        # 檢查交易量是否減少
        df_result['Volume_Decreasing'] = (df[volume_col] < df_result['Volume_MA5']).astype(int)
        
        # 檢查交易量是否出現尖峰
        df_result['Volume_Spike'] = ((df[volume_col] / df_result['Volume_MA5']) > 2).astype(int)
        
        return df_result
    
    def _combine_signals(self, df, patterns):
        """組合不同來源的信號
        
        Args:
            df: 數據DataFrame
            patterns: 識別出的形態字典，格式為 {形態類型: [(開始索引, 結束索引), ...]}
            
        Returns:
            DataFrame: 包含組合信號的DataFrame
        """
        df_result = df.copy()
        
        # 創建信號列
        df_result['Pattern_Signal'] = 0  # 0表示無信號，1表示看漲信號，-1表示看跌信號
        
        # 添加形態信號
        for pattern_type, pattern_positions in patterns.items():
            for start_idx, end_idx in pattern_positions:
                # 根據形態類型設置信號
                if pattern_type in ['W底', '頭肩底']:
                    # 看漲形態
                    df_result.loc[end_idx, 'Pattern_Signal'] = 1
                elif pattern_type in ['頭肩頂']:
                    # 看跌形態
                    df_result.loc[end_idx, 'Pattern_Signal'] = -1
        
        # 添加技術指標信號
        df_result['Technical_Signal'] = 0
        
        # RSI信號
        if 'RSI' in df_result.columns:
            # RSI < 30 表示超賣，看漲信號
            df_result.loc[df_result['RSI'] < 30, 'Technical_Signal'] = 1
            # RSI > 70 表示超買，看跌信號
            df_result.loc[df_result['RSI'] > 70, 'Technical_Signal'] = -1
        
        # MACD信號
        if all(col in df_result.columns for col in ['MACD', 'MACD_Signal']):
            # MACD上穿信號線，看漲信號
            df_result['MACD_Crossover'] = ((df_result['MACD'] > df_result['MACD_Signal']) & 
                                          (df_result['MACD'].shift(1) <= df_result['MACD_Signal'].shift(1))).astype(int)
            # MACD下穿信號線，看跌信號
            df_result['MACD_Crossunder'] = ((df_result['MACD'] < df_result['MACD_Signal']) & 
                                           (df_result['MACD'].shift(1) >= df_result['MACD_Signal'].shift(1))).astype(int)
            
            df_result.loc[df_result['MACD_Crossover'] == 1, 'Technical_Signal'] = 1
            df_result.loc[df_result['MACD_Crossunder'] == 1, 'Technical_Signal'] = -1
        
        # 布林帶信號
        if all(col in df_result.columns for col in ['BB_Upper', 'BB_Middle', 'BB_Lower']):
            close_col = self._get_column_name(df, 'Close')
            if close_col:
                # 價格觸及下軌，看漲信號
                df_result.loc[df_result[close_col] <= df_result['BB_Lower'], 'Technical_Signal'] = 1
                # 價格觸及上軌，看跌信號
                df_result.loc[df_result[close_col] >= df_result['BB_Upper'], 'Technical_Signal'] = -1
        
        # 添加交易量信號
        df_result['Volume_Signal'] = 0
        
        if 'Volume_Spike' in df_result.columns and 'Pattern_Signal' in df_result.columns:
            # 形態確認點的交易量出現尖峰，增強信號
            df_result.loc[(df_result['Pattern_Signal'] != 0) & (df_result['Volume_Spike'] == 1), 'Volume_Signal'] = df_result['Pattern_Signal']
        
        # 組合所有信號
        df_result['Combined_Signal'] = 0
        
        # 當形態信號和技術指標信號一致時，產生強信號
        df_result.loc[(df_result['Pattern_Signal'] == 1) & (df_result['Technical_Signal'] == 1), 'Combined_Signal'] = 2  # 強看漲信號
        df_result.loc[(df_result['Pattern_Signal'] == -1) & (df_result['Technical_Signal'] == -1), 'Combined_Signal'] = -2  # 強看跌信號
        
        # 當只有一種信號時，產生弱信號
        df_result.loc[(df_result['Pattern_Signal'] == 1) & (df_result['Combined_Signal'] == 0), 'Combined_Signal'] = 1  # 弱看漲信號
        df_result.loc[(df_result['Pattern_Signal'] == -1) & (df_result['Combined_Signal'] == 0), 'Combined_Signal'] = -1  # 弱看跌信號
        df_result.loc[(df_result['Technical_Signal'] == 1) & (df_result['Combined_Signal'] == 0), 'Combined_Signal'] = 1  # 弱看漲信號
        df_result.loc[(df_result['Technical_Signal'] == -1) & (df_result['Combined_Signal'] == 0), 'Combined_Signal'] = -1  # 弱看跌信號
        
        # 當交易量信號確認時，進一步增強信號
        df_result.loc[(df_result['Combined_Signal'] > 0) & (df_result['Volume_Signal'] > 0), 'Combined_Signal'] += 1
        df_result.loc[(df_result['Combined_Signal'] < 0) & (df_result['Volume_Signal'] < 0), 'Combined_Signal'] -= 1
        
        return df_result
    
    def _evaluate_signal_reliability(self, df):
        """評估信號可靠性
        
        Args:
            df: 數據DataFrame
            
        Returns:
            DataFrame: 添加信號可靠性評分的DataFrame
        """
        df_result = df.copy()
        
        # 初始化可靠性得分
        df_result['Signal_Reliability'] = 0.0
        
        # 根據信號強度設置基礎可靠性得分
        df_result.loc[df_result['Combined_Signal'] == 3, 'Signal_Reliability'] = 0.9  # 最強看漲信號
        df_result.loc[df_result['Combined_Signal'] == 2, 'Signal_Reliability'] = 0.7  # 強看漲信號
        df_result.loc[df_result['Combined_Signal'] == 1, 'Signal_Reliability'] = 0.5  # 弱看漲信號
        df_result.loc[df_result['Combined_Signal'] == -3, 'Signal_Reliability'] = 0.9  # 最強看跌信號
        df_result.loc[df_result['Combined_Signal'] == -2, 'Signal_Reliability'] = 0.7  # 強看跌信號
        df_result.loc[df_result['Combined_Signal'] == -1, 'Signal_Reliability'] = 0.5  # 弱看跌信號
        
        # 添加方向
        df_result['Signal_Direction'] = np.sign(df_result['Combined_Signal'])
        
        return df_result
    
    def backtest_strategy(self, df, strategy_params, initial_capital=100000, commission=0.001):
        """回測組合信號策略
        
        Args:
            df: 數據DataFrame，必須包含Combined_Signal和Signal_Reliability列
            strategy_params: 策略參數字典，包含：
                - buy_threshold: 買入閾值，默認為1
                - sell_threshold: 賣出閾值，默認為-1
                - reliability_threshold: 可靠性閾值，默認為0.5
                - use_stop_loss: 是否使用止損，默認為True
                - stop_loss_pct: 止損百分比，默認為0.05 (5%)
            initial_capital: 初始資金，默認為100000
            commission: 交易手續費率，默認為0.001 (0.1%)
            
        Returns:
            dict: 回測結果
        """
        # 參數設置
        buy_threshold = strategy_params.get('buy_threshold', 1)
        sell_threshold = strategy_params.get('sell_threshold', -1)
        reliability_threshold = strategy_params.get('reliability_threshold', 0.5)
        use_stop_loss = strategy_params.get('use_stop_loss', True)
        stop_loss_pct = strategy_params.get('stop_loss_pct', 0.05)
        
        # 回測結果
        result = {
            'initial_capital': initial_capital,
            'final_capital': initial_capital,
            'total_returns': 0.0,
            'annualized_returns': 0.0,
            'total_trades': 0,
            'winning_trades': 0,
            'losing_trades': 0,
            'win_rate': 0.0,
            'avg_win': 0.0,
            'avg_loss': 0.0,
            'max_drawdown': 0.0,
            'sharpe_ratio': 0.0,
            'trades': []
        }
        
        # 確保數據按日期排序
        df_sorted = df.sort_index()
        
        # 獲取價格列
        close_col = self._get_column_name(df_sorted, 'Close')
        if not close_col:
            print("錯誤: 找不到收盤價列")
            return result
        
        # 回測變量
        position = 0  # 0: 無倉位, 1: 多頭, -1: 空頭
        entry_price = 0
        capital = initial_capital
        trades = []
        
        # 遍歷每個時間點
        for i, (idx, row) in enumerate(df_sorted.iterrows()):
            # 跳過沒有足夠數據的時間點
            if i < 20:
                continue
                
            price = row[close_col]
            signal = row.get('Combined_Signal', 0)
            reliability = row.get('Signal_Reliability', 0)
            
            # 檢查止損
            if position != 0 and use_stop_loss:
                if position == 1 and price < entry_price * (1 - stop_loss_pct):
                    # 止損平多
                    profit = (price - entry_price) * (capital / entry_price) - commission * capital
                    capital += profit
                    
                    trades.append({
                        'entry_time': idx - 1,  # 近似值
                        'entry_price': entry_price,
                        'exit_time': idx,
                        'exit_price': price,
                        'position': position,
                        'profit': profit,
                        'reason': '止損'
                    })
                    
                    position = 0
                    entry_price = 0
                elif position == -1 and price > entry_price * (1 + stop_loss_pct):
                    # 止損平空
                    profit = (entry_price - price) * (capital / entry_price) - commission * capital
                    capital += profit
                    
                    trades.append({
                        'entry_time': idx - 1,  # 近似值
                        'entry_price': entry_price,
                        'exit_time': idx,
                        'exit_price': price,
                        'position': position,
                        'profit': profit,
                        'reason': '止損'
                    })
                    
                    position = 0
                    entry_price = 0
            
            # 交易信號
            if position == 0:
                # 無倉位，檢查買入信號
                if signal >= buy_threshold and reliability >= reliability_threshold:
                    # 開多倉
                    position = 1
                    entry_price = price
                elif signal <= sell_threshold and reliability >= reliability_threshold:
                    # 開空倉
                    position = -1
                    entry_price = price
            elif position == 1:
                # 多頭倉位，檢查賣出信號
                if signal <= sell_threshold and reliability >= reliability_threshold:
                    # 平多倉
                    profit = (price - entry_price) * (capital / entry_price) - commission * capital
                    capital += profit
                    
                    trades.append({
                        'entry_time': idx - 1,  # 近似值
                        'entry_price': entry_price,
                        'exit_time': idx,
                        'exit_price': price,
                        'position': position,
                        'profit': profit,
                        'reason': '信號'
                    })
                    
                    position = 0
                    entry_price = 0
            elif position == -1:
                # 空頭倉位，檢查買入信號
                if signal >= buy_threshold and reliability >= reliability_threshold:
                    # 平空倉
                    profit = (entry_price - price) * (capital / entry_price) - commission * capital
                    capital += profit
                    
                    trades.append({
                        'entry_time': idx - 1,  # 近似值
                        'entry_price': entry_price,
                        'exit_time': idx,
                        'exit_price': price,
                        'position': position,
                        'profit': profit,
                        'reason': '信號'
                    })
                    
                    position = 0
                    entry_price = 0
        
        # 回測統計
        result['final_capital'] = capital
        result['total_returns'] = (capital - initial_capital) / initial_capital
        
        result['total_trades'] = len(trades)
        if result['total_trades'] > 0:
            winning_trades = [t for t in trades if t['profit'] > 0]
            losing_trades = [t for t in trades if t['profit'] <= 0]
            
            result['winning_trades'] = len(winning_trades)
            result['losing_trades'] = len(losing_trades)
            
            result['win_rate'] = result['winning_trades'] / result['total_trades'] if result['total_trades'] > 0 else 0
            
            result['avg_win'] = sum(t['profit'] for t in winning_trades) / len(winning_trades) if winning_trades else 0
            result['avg_loss'] = sum(t['profit'] for t in losing_trades) / len(losing_trades) if losing_trades else 0
            
            result['trades'] = trades
        
        return result
    
    def visualize_signals(self, df, ticker=None, save_path=None):
        """視覺化組合信號
        
        Args:
            df: 數據DataFrame，必須包含Combined_Signal和Signal_Reliability列
            ticker: 股票代碼，用於標題，默認為None
            save_path: 保存路徑，如果為None則顯示圖形而不保存
            
        Returns:
            None
        """
        # 確保數據按日期排序
        df_sorted = df.sort_index()
        
        # 獲取價格列
        close_col = self._get_column_name(df_sorted, 'Close')
        if not close_col:
            print("錯誤: 找不到收盤價列")
            return
        
        # 創建圖形
        fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(15, 12), sharex=True, gridspec_kw={'height_ratios': [3, 1, 1]})
        
        # 繪製價格圖
        ax1.plot(df_sorted.index, df_sorted[close_col], label='價格')
        ax1.set_title(f"{'股票: ' + ticker if ticker else '價格'} 與交易信號")
        ax1.legend(loc='upper left')
        
        # 添加買入和賣出標記
        buy_signals = df_sorted[df_sorted['Combined_Signal'] >= 2].index
        sell_signals = df_sorted[df_sorted['Combined_Signal'] <= -2].index
        
        for idx in buy_signals:
            ax1.axvline(x=idx, color='g', linestyle='--', alpha=0.7)
        
        for idx in sell_signals:
            ax1.axvline(x=idx, color='r', linestyle='--', alpha=0.7)
        
        # 繪製信號強度圖
        ax2.bar(df_sorted.index, df_sorted['Combined_Signal'], label='信號強度')
        ax2.axhline(y=0, color='k', linestyle='-', alpha=0.3)
        ax2.set_ylabel('信號強度')
        ax2.legend(loc='upper left')
        
        # 繪製信號可靠性圖
        ax3.plot(df_sorted.index, df_sorted['Signal_Reliability'], label='信號可靠性', color='purple')
        ax3.axhline(y=0.5, color='k', linestyle='--', alpha=0.3)
        ax3.set_ylim(0, 1)
        ax3.set_ylabel('可靠性得分')
        ax3.legend(loc='upper left')
        
        plt.tight_layout()
        
        # 保存或顯示圖形
        if save_path:
            plt.savefig(save_path)
        
        return fig 