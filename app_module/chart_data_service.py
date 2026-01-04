"""
圖表資料服務 (Chart Data Service)
提供圖表所需的資料轉換，不涉及 UI
"""

import pandas as pd
import numpy as np
from typing import Optional, Dict, Any
from pathlib import Path
from app_module.backtest_repository import BacktestRunRepository


class ChartDataService:
    """圖表資料服務"""
    
    def __init__(self, run_repository: BacktestRunRepository):
        """
        初始化圖表資料服務
        
        Args:
            run_repository: BacktestRunRepository 實例
        """
        self.run_repository = run_repository
    
    def get_equity_series(self, run_id: str) -> Optional[pd.Series]:
        """
        獲取權益曲線序列
        
        Args:
            run_id: 回測執行ID
        
        Returns:
            權益序列（日期索引）或 None
        """
        run_data = self.run_repository.load_run_data(run_id)
        if not run_data:
            return None
        
        equity_curve = run_data.get('equity_curve')
        if equity_curve is None or not isinstance(equity_curve, pd.DataFrame):
            return None
        
        if 'equity' in equity_curve.columns:
            return equity_curve['equity']
        elif len(equity_curve.columns) > 0:
            # 如果沒有 equity 欄位，使用第一欄
            return equity_curve.iloc[:, 0]
        
        return None
    
    def get_drawdown_series(self, run_id: str) -> Optional[pd.Series]:
        """
        獲取回撤曲線序列
        
        Args:
            run_id: 回測執行ID
        
        Returns:
            回撤序列（日期索引，負數）或 None
        """
        equity_series = self.get_equity_series(run_id)
        if equity_series is None or len(equity_series) == 0:
            return None
        
        # 計算累積最高點
        cummax = equity_series.cummax()
        
        # 計算回撤（負數）
        drawdown = (equity_series - cummax) / cummax
        
        return drawdown
    
    def get_max_drawdown_info(self, run_id: str) -> Optional[Dict[str, Any]]:
        """
        獲取最大回撤資訊
        
        Args:
            run_id: 回測執行ID
        
        Returns:
            最大回撤資訊字典或 None
        """
        drawdown_series = self.get_drawdown_series(run_id)
        if drawdown_series is None or len(drawdown_series) == 0:
            return None
        
        # 找到最大回撤
        max_dd_value = drawdown_series.min()
        max_dd_date = drawdown_series.idxmin()
        
        # 找到回撤開始日期（最大回撤日期之前的最高點）
        equity_series = self.get_equity_series(run_id)
        if equity_series is None:
            return None
        
        # 在最大回撤日期之前找到最高點
        before_dd = equity_series.loc[:max_dd_date]
        if len(before_dd) > 0:
            peak_date = before_dd.idxmax()
            peak_value = before_dd.max()
        else:
            peak_date = max_dd_date
            peak_value = equity_series.loc[max_dd_date]
        
        # 找到恢復日期（最大回撤之後回到峰值）
        after_dd = equity_series.loc[max_dd_date:]
        if len(after_dd) > 0:
            recovery_dates = after_dd[after_dd >= peak_value]
            if len(recovery_dates) > 0:
                recovery_date = recovery_dates.index[0]
            else:
                recovery_date = None
        else:
            recovery_date = None
        
        # 計算恢復天數
        if recovery_date is not None:
            recovery_days = (recovery_date - max_dd_date).days
        else:
            recovery_days = None
        
        return {
            'max_drawdown': max_dd_value,
            'max_drawdown_date': max_dd_date,
            'peak_date': peak_date,
            'peak_value': peak_value,
            'recovery_date': recovery_date,
            'recovery_days': recovery_days
        }
    
    def get_trade_list(self, run_id: str) -> Optional[pd.DataFrame]:
        """
        獲取交易明細 DataFrame
        
        Args:
            run_id: 回測執行ID
        
        Returns:
            交易明細 DataFrame 或 None
        """
        run_data = self.run_repository.load_run_data(run_id)
        if not run_data:
            return None
        
        trade_list = run_data.get('trade_list')
        if trade_list is None or not isinstance(trade_list, pd.DataFrame):
            return None
        
        return trade_list
    
    def get_trade_returns(self, run_id: str) -> Optional[np.ndarray]:
        """
        獲取交易報酬率陣列
        
        Args:
            run_id: 回測執行ID
        
        Returns:
            報酬率陣列（百分比）或 None
        """
        run_data = self.run_repository.load_run_data(run_id)
        if not run_data:
            return None
        
        trade_list = run_data.get('trade_list')
        if trade_list is None or not isinstance(trade_list, pd.DataFrame):
            return None
        
        if '報酬率%' in trade_list.columns:
            returns = trade_list['報酬率%'].values
        elif 'return_pct' in trade_list.columns:
            returns = trade_list['return_pct'].values * 100
        else:
            return None
        
        # 移除 NaN
        returns = returns[~np.isnan(returns)]
        
        return returns if len(returns) > 0 else None
    
    def get_holding_days(self, run_id: str) -> Optional[np.ndarray]:
        """
        獲取持有天數陣列
        
        Args:
            run_id: 回測執行ID
        
        Returns:
            持有天數陣列或 None
        """
        run_data = self.run_repository.load_run_data(run_id)
        if not run_data:
            return None
        
        trade_list = run_data.get('trade_list')
        if trade_list is None or not isinstance(trade_list, pd.DataFrame):
            return None
        
        if '持有天數' in trade_list.columns:
            days = trade_list['持有天數'].values
        elif 'holding_days' in trade_list.columns:
            days = trade_list['holding_days'].values
        else:
            return None
        
        # 移除 NaN
        days = days[~np.isnan(days)]
        days = days[days > 0]  # 只保留正數
        
        return days if len(days) > 0 else None
    
    def get_trade_statistics(self, run_id: str) -> Optional[Dict[str, float]]:
        """
        獲取交易統計資訊
        
        Args:
            run_id: 回測執行ID
        
        Returns:
            統計資訊字典或 None
        """
        returns = self.get_trade_returns(run_id)
        if returns is None or len(returns) == 0:
            return None
        
        stats = {
            'mean': float(np.mean(returns)),
            'median': float(np.median(returns)),
            'std': float(np.std(returns)),
            'min': float(np.min(returns)),
            'max': float(np.max(returns)),
        }
        
        # 計算 95% VaR（簡單分位數）
        if len(returns) > 0:
            stats['var_95'] = float(np.percentile(returns, 5))  # 5% 分位數（負數表示風險）
        
        return stats
    
    def get_benchmark_series(
        self,
        start_date: str,
        end_date: str,
        benchmark_code: str = "TAIEX"
    ) -> Optional[pd.Series]:
        """
        獲取基準指數序列（用於疊加比較）
        
        Args:
            start_date: 開始日期（YYYY-MM-DD）
            end_date: 結束日期（YYYY-MM-DD）
            benchmark_code: 基準代號（預設 TAIEX，目前只支援 TAIEX）
        
        Returns:
            基準序列（日期索引，標準化為起始值對齊）或 None
        """
        try:
            # 從 run_repository 獲取 config
            if not hasattr(self.run_repository, 'config'):
                return None
            
            config = self.run_repository.config
            market_index_file = config.market_index_file
            
            # 檢查文件是否存在
            if not market_index_file or not market_index_file.exists():
                return None
            
            # 載入市場指數數據
            df = pd.read_csv(
                market_index_file,
                encoding='utf-8-sig',
                on_bad_lines='skip',
                engine='python'
            )
            
            if df.empty:
                return None
            
            # 解析日期欄位
            if '日期' not in df.columns:
                return None
            
            # 轉換日期格式
            df['日期'] = pd.to_datetime(df['日期'], format='mixed', errors='coerce')
            df = df.dropna(subset=['日期'])
            
            if len(df) == 0:
                return None
            
            # 找到收盤價欄位
            close_col = None
            for col in ['Close', '收盤價', 'close', '收盤']:
                if col in df.columns:
                    close_col = col
                    break
            
            if close_col is None:
                return None
            
            # 轉換為數值
            df[close_col] = pd.to_numeric(df[close_col], errors='coerce')
            df = df.dropna(subset=[close_col])
            
            if len(df) == 0:
                return None
            
            # 設置日期為索引
            df = df.set_index('日期')
            df = df.sort_index()
            
            # 轉換日期範圍為 datetime
            start_dt = pd.to_datetime(start_date, errors='coerce')
            end_dt = pd.to_datetime(end_date, errors='coerce')
            
            if pd.isna(start_dt) or pd.isna(end_dt):
                return None
            
            # 篩選日期範圍
            mask = (df.index >= start_dt) & (df.index <= end_dt)
            df_filtered = df[mask]
            
            if len(df_filtered) == 0:
                return None
            
            # 提取收盤價序列
            benchmark_series = df_filtered[close_col]
            
            # 移除重複日期（保留最後一個）
            benchmark_series = benchmark_series[~benchmark_series.index.duplicated(keep='last')]
            
            # 返回原始收盤價序列（標準化會在 EquityCurveWidget.plot() 中處理）
            if len(benchmark_series) > 0:
                return benchmark_series
            
            return None
            
        except Exception as e:
            # 靜默失敗，不影響主功能
            import logging
            logger = logging.getLogger(__name__)
            logger.debug(f"[ChartDataService] 載入基準線失敗: {e}")
            return None

