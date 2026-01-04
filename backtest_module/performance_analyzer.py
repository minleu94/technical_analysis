import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from scipy.stats import norm

class PerformanceAnalyzer:
    """績效指標計算類"""
    
    def __init__(self, portfolio_returns, benchmark_returns=None, risk_free_rate=0.0):
        """初始化績效分析器
        
        Args:
            portfolio_returns: 投資組合收益率序列
            benchmark_returns: 基準收益率序列（可選）
            risk_free_rate: 無風險利率
        """
        self.portfolio_returns = portfolio_returns
        self.benchmark_returns = benchmark_returns
        self.risk_free_rate = risk_free_rate
        
    def calculate_returns(self, portfolio_values):
        """計算收益率
        
        Args:
            portfolio_values: 投資組合價值序列
            
        Returns:
            收益率序列
        """
        return portfolio_values.pct_change().dropna()
    
    def calculate_cumulative_returns(self, returns=None):
        """計算累積收益率
        
        Args:
            returns: 收益率序列，如果為None則使用投資組合收益率
            
        Returns:
            累積收益率序列
        """
        if returns is None:
            returns = self.portfolio_returns
            
        return (1 + returns).cumprod() - 1
    
    def calculate_annualized_return(self, returns=None):
        """計算年化收益率
        
        Args:
            returns: 收益率序列，如果為None則使用投資組合收益率
            
        Returns:
            年化收益率
        """
        if returns is None:
            returns = self.portfolio_returns
            
        total_return = self.calculate_cumulative_returns(returns).iloc[-1]
        n_years = len(returns) / 252  # 假設一年有252個交易日
        return (1 + total_return) ** (1 / n_years) - 1
    
    def calculate_volatility(self, returns=None, annualized=True):
        """計算波動率
        
        Args:
            returns: 收益率序列，如果為None則使用投資組合收益率
            annualized: 是否年化
            
        Returns:
            波動率
        """
        if returns is None:
            returns = self.portfolio_returns
            
        vol = returns.std()
        if annualized:
            vol = vol * np.sqrt(252)
            
        return vol
    
    def calculate_sharpe_ratio(self, returns=None):
        """計算夏普比率
        
        Args:
            returns: 收益率序列，如果為None則使用投資組合收益率
            
        Returns:
            夏普比率
        """
        if returns is None:
            returns = self.portfolio_returns
            
        excess_returns = returns - self.risk_free_rate
        return np.sqrt(252) * excess_returns.mean() / excess_returns.std()
    
    def calculate_sortino_ratio(self, returns=None):
        """計算索提諾比率
        
        Args:
            returns: 收益率序列，如果為None則使用投資組合收益率
            
        Returns:
            索提諾比率
        """
        if returns is None:
            returns = self.portfolio_returns
            
        excess_returns = returns - self.risk_free_rate
        downside_returns = excess_returns[excess_returns < 0]
        downside_deviation = downside_returns.std() * np.sqrt(252)
        
        if downside_deviation == 0:
            return np.nan
            
        return np.sqrt(252) * excess_returns.mean() / downside_deviation
    
    def calculate_max_drawdown(self, returns=None):
        """計算最大回撤
        
        Args:
            returns: 收益率序列，如果為None則使用投資組合收益率
            
        Returns:
            最大回撤
        """
        if returns is None:
            returns = self.portfolio_returns
            
        cum_returns = self.calculate_cumulative_returns(returns)
        running_max = cum_returns.cummax()
        drawdown = (cum_returns - running_max) / (1 + running_max)
        return drawdown.min()
    
    def calculate_alpha_beta(self):
        """計算阿爾法和貝塔係數
        
        Returns:
            tuple: (阿爾法, 貝塔)
        """
        if self.benchmark_returns is None:
            raise ValueError("需要基準收益率來計算阿爾法和貝塔")
            
        # 計算貝塔
        covariance = np.cov(self.portfolio_returns, self.benchmark_returns)[0, 1]
        benchmark_variance = self.benchmark_returns.var()
        beta = covariance / benchmark_variance
        
        # 計算阿爾法
        portfolio_return = self.calculate_annualized_return()
        benchmark_return = self.calculate_annualized_return(self.benchmark_returns)
        alpha = portfolio_return - (self.risk_free_rate + beta * (benchmark_return - self.risk_free_rate))
        
        return alpha, beta
    
    def generate_performance_report(self):
        """生成績效報告
        
        Returns:
            績效指標字典
        """
        report = {
            '累積收益率': self.calculate_cumulative_returns().iloc[-1],
            '年化收益率': self.calculate_annualized_return(),
            '年化波動率': self.calculate_volatility(),
            '夏普比率': self.calculate_sharpe_ratio(),
            '索提諾比率': self.calculate_sortino_ratio(),
            '最大回撤': self.calculate_max_drawdown()
        }
        
        if self.benchmark_returns is not None:
            alpha, beta = self.calculate_alpha_beta()
            report['阿爾法'] = alpha
            report['貝塔'] = beta
            
        return report
    
    def plot_performance(self):
        """繪製績效圖表"""
        plt.figure(figsize=(15, 10))
        
        # 繪製累積收益率
        plt.subplot(2, 2, 1)
        cum_returns = self.calculate_cumulative_returns() * 100
        plt.plot(cum_returns.index, cum_returns, label='投資組合')
        
        if self.benchmark_returns is not None:
            bench_cum_returns = self.calculate_cumulative_returns(self.benchmark_returns) * 100
            plt.plot(bench_cum_returns.index, bench_cum_returns, label='基準', linestyle='--')
            
        plt.title('累積收益率 (%)')
        plt.xlabel('日期')
        plt.ylabel('收益率 (%)')
        plt.legend()
        plt.grid(True)
        
        # 繪製回撤
        plt.subplot(2, 2, 2)
        cum_returns = self.calculate_cumulative_returns()
        running_max = cum_returns.cummax()
        drawdown = (cum_returns - running_max) / (1 + running_max) * 100
        plt.fill_between(drawdown.index, drawdown, 0, color='red', alpha=0.3)
        plt.plot(drawdown.index, drawdown, color='red', label='回撤')
        plt.title('回撤 (%)')
        plt.xlabel('日期')
        plt.ylabel('回撤 (%)')
        plt.legend()
        plt.grid(True)
        
        # 繪製月度收益熱圖
        plt.subplot(2, 2, 3)
        monthly_returns = self.portfolio_returns.resample('M').apply(
            lambda x: (1 + x).prod() - 1
        )
        monthly_returns = monthly_returns.to_frame('收益率')
        monthly_returns['年'] = monthly_returns.index.year
        monthly_returns['月'] = monthly_returns.index.month
        pivot_table = monthly_returns.pivot_table(
            index='年', columns='月', values='收益率'
        )
        
        plt.imshow(pivot_table.values, cmap='RdYlGn', aspect='auto')
        plt.colorbar(label='月度收益率')
        plt.title('月度收益熱圖')
        plt.xlabel('月份')
        plt.ylabel('年份')
        plt.xticks(range(12), range(1, 13))
        plt.yticks(range(len(pivot_table.index)), pivot_table.index)
        
        # 繪製收益分佈
        plt.subplot(2, 2, 4)
        plt.hist(self.portfolio_returns * 100, bins=50, alpha=0.5, label='實際分佈')
        
        # 擬合正態分佈
        mu, sigma = norm.fit(self.portfolio_returns * 100)
        x = np.linspace(mu - 3*sigma, mu + 3*sigma, 100)
        plt.plot(x, norm.pdf(x, mu, sigma) * len(self.portfolio_returns) * (6*sigma/50), 
                 label=f'正態分佈 (μ={mu:.2f}, σ={sigma:.2f})')
        
        plt.title('收益率分佈')
        plt.xlabel('日收益率 (%)')
        plt.ylabel('頻率')
        plt.legend()
        plt.grid(True)
        
        plt.tight_layout() 