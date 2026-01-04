import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from datetime import datetime

class StrategyTester:
    """策略回測實現類"""
    
    def __init__(self, initial_capital=100000.0):
        """初始化策略測試器
        
        Args:
            initial_capital: 初始資金
        """
        self.initial_capital = initial_capital
        self.positions = {}
        self.trades = []
        self.portfolio_value = []
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
        
    def run_backtest(self, df, strategy_func, **strategy_params):
        """運行回測
        
        Args:
            df: 股票數據DataFrame
            strategy_func: 策略函數，接收價格數據和參數，返回交易信號
            **strategy_params: 策略參數
            
        Returns:
            回測結果DataFrame
        """
        # 確保數據按日期排序
        df = df.sort_index()
        
        # 生成交易信號
        signals = strategy_func(df, **strategy_params)
        
        # 初始化回測結果
        results = df.copy()
        results['Signal'] = signals
        results['Position'] = signals.diff()
        
        # 初始化資金和持倉
        cash = self.initial_capital
        position = 0
        
        # 獲取收盤價列名
        close_col = self._get_column_name(df, 'Close')
        if close_col is None:
            raise ValueError("找不到收盤價列，請確保數據中包含'Close'或'收盤價'列")
        
        # 記錄每日資產價值和交易
        portfolio_values = []
        trades_list = []
        
        for date, row in results.iterrows():
            # 處理交易
            if row['Position'] > 0:  # 買入信號
                shares_to_buy = int(cash / row[close_col])
                cost = shares_to_buy * row[close_col]
                cash -= cost
                position += shares_to_buy
                trades_list.append({
                    'Date': date,
                    'Type': '買入',
                    'Price': row[close_col],
                    'Shares': shares_to_buy,
                    'Value': cost
                })
            elif row['Position'] < 0:  # 賣出信號
                value = position * row[close_col]
                cash += value
                trades_list.append({
                    'Date': date,
                    'Type': '賣出',
                    'Price': row[close_col],
                    'Shares': position,
                    'Value': value
                })
                position = 0
                
            # 計算當前組合價值
            portfolio_value = cash + (position * row[close_col])
            portfolio_values.append({
                'Date': date,
                'Cash': cash,
                'Position': position,
                'Stock_Value': position * row[close_col],
                'Total_Value': portfolio_value
            })
            
        # 創建回測結果DataFrame
        self.portfolio_value = pd.DataFrame(portfolio_values).set_index('Date')
        self.trades = pd.DataFrame(trades_list)
        
        # 合併結果
        results = pd.concat([results, self.portfolio_value], axis=1)
        
        return results
    
    def plot_results(self):
        """繪製回測結果圖表"""
        if len(self.portfolio_value) == 0:
            print("沒有回測結果可繪製")
            return
            
        plt.figure(figsize=(12, 8))
        
        # 繪製資產價值曲線
        plt.subplot(2, 1, 1)
        plt.plot(self.portfolio_value.index, self.portfolio_value['Total_Value'], label='組合總價值')
        plt.plot(self.portfolio_value.index, self.portfolio_value['Cash'], label='現金', linestyle='--')
        plt.plot(self.portfolio_value.index, self.portfolio_value['Stock_Value'], label='股票價值', linestyle=':')
        
        # 標記交易點
        if not self.trades.empty:
            buy_trades = self.trades[self.trades['Type'] == '買入']
            sell_trades = self.trades[self.trades['Type'] == '賣出']
            
            plt.scatter(buy_trades['Date'], buy_trades['Value'], 
                       marker='^', color='g', s=100, label='買入')
            plt.scatter(sell_trades['Date'], sell_trades['Value'], 
                       marker='v', color='r', s=100, label='賣出')
        
        plt.title('回測結果')
        plt.xlabel('日期')
        plt.ylabel('價值')
        plt.legend()
        plt.grid(True)
        
        # 繪製收益率曲線
        plt.subplot(2, 1, 2)
        returns = self.portfolio_value['Total_Value'].pct_change()
        cumulative_returns = (1 + returns).cumprod() - 1
        plt.plot(cumulative_returns.index, cumulative_returns * 100, label='累積收益率 (%)')
        plt.title('累積收益率')
        plt.xlabel('日期')
        plt.ylabel('收益率 (%)')
        plt.legend()
        plt.grid(True)
        
        plt.tight_layout() 