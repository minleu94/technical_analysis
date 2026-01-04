"""
篩選服務 (Screening Service)
提供強勢股/產業篩選的業務邏輯
"""

import pandas as pd
from typing import Optional

# 方案 A：不搬檔案，service 層內部 import ui_app 模組
# from ui_app.stock_screener import StockScreener
# from ui_app.industry_mapper import IndustryMapper
from decision_module.stock_screener import StockScreener
from decision_module.industry_mapper import IndustryMapper


class ScreeningService:
    """篩選服務類"""
    
    def __init__(self, config, industry_mapper: Optional[IndustryMapper] = None):
        """初始化篩選服務
        
        Args:
            config: TWStockConfig 實例
            industry_mapper: IndustryMapper 實例（可選，如果為 None 則自動創建）
        """
        self.config = config
        if industry_mapper is None:
            self.industry_mapper = IndustryMapper(config)
        else:
            self.industry_mapper = industry_mapper
        self.stock_screener = StockScreener(config, self.industry_mapper)
    
    def get_strong_stocks(
        self, 
        period: str = 'day', 
        top_n: int = 20,
        min_volume: Optional[int] = None
    ) -> tuple[pd.DataFrame, int]:
        """獲取強勢股
        
        Args:
            period: 'day' 或 'week'，表示本日或本周
            top_n: 返回前N名
            min_volume: 最小成交量（可選）
            
        Returns:
            tuple: (DataFrame, universe_count)
                - DataFrame: 強勢股列表，包含排名、證券代號、證券名稱、收盤價、漲幅%、評分、推薦理由
                - universe_count: Universe 股票數量（有效數據的股票數）
        """
        return self.stock_screener.get_strong_stocks(
            period=period,
            top_n=top_n,
            min_volume=min_volume
        )
    
    def get_strong_industries(
        self, 
        period: str = 'day', 
        top_n: int = 20
    ) -> pd.DataFrame:
        """獲取強勢產業
        
        Args:
            period: 'day' 或 'week'，表示本日或本周
            top_n: 返回前N名
            
        Returns:
            DataFrame: 強勢產業列表，包含排名、指數名稱、收盤指數、漲幅%
        """
        return self.stock_screener.get_strong_industries(
            period=period,
            top_n=top_n
        )
    
    def get_weak_stocks(
        self, 
        period: str = 'day', 
        top_n: int = 20,
        min_volume: Optional[int] = None
    ) -> tuple[pd.DataFrame, int]:
        """獲取弱勢股（與強勢股同架構，反向排名）
        
        Args:
            period: 'day' 或 'week'，表示本日或本周
            top_n: 返回前N名（最弱的）
            min_volume: 最小成交量（可選）
            
        Returns:
            tuple: (DataFrame, universe_count)
                - DataFrame: 弱勢股列表，包含排名、證券代號、證券名稱、收盤價、漲幅%、評分、推薦理由
                - universe_count: Universe 股票數量（有效數據的股票數）
        """
        return self.stock_screener.get_weak_stocks(
            period=period,
            top_n=top_n,
            min_volume=min_volume
        )
    
    def get_weak_industries(
        self, 
        period: str = 'day', 
        top_n: int = 20
    ) -> pd.DataFrame:
        """獲取弱勢產業（與強勢產業同架構，反向排名）
        
        Args:
            period: 'day' 或 'week'，表示本日或本周
            top_n: 返回前N名（最弱的）
            
        Returns:
            DataFrame: 弱勢產業列表，包含排名、指數名稱、收盤指數、漲幅%
        """
        return self.stock_screener.get_weak_industries(
            period=period,
            top_n=top_n
        )

