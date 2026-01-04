"""
市場狀態服務 (Regime Service)
提供市場狀態檢測的業務邏輯
"""

from typing import Dict, Any

# 方案 A：不搬檔案，service 層內部 import ui_app 模組
# from ui_app.market_regime_detector import MarketRegimeDetector
from decision_module.market_regime_detector import MarketRegimeDetector
from app_module.dtos import RegimeResultDTO


class RegimeService:
    """市場狀態服務類"""
    
    def __init__(self, config):
        """初始化市場狀態服務
        
        Args:
            config: TWStockConfig 實例
        """
        self.config = config
        self.regime_detector = MarketRegimeDetector(config)
    
    def detect_regime(self, date: str = None) -> RegimeResultDTO:
        """檢測市場狀態
        
        Args:
            date: 日期（YYYY-MM-DD格式），如果為None則使用最新日期
            
        Returns:
            RegimeResultDTO: 市場狀態檢測結果
        """
        regime_result = self.regime_detector.detect_regime(date=date)
        regime = regime_result.get('regime', 'Trend')
        confidence = regime_result.get('confidence', 0.5)
        details = regime_result.get('details', {})
        
        regime_name_map = {
            'Trend': '趨勢追蹤',
            'Reversion': '均值回歸',
            'Breakout': '突破準備'
        }
        regime_name_cn = regime_name_map.get(regime, regime)
        
        return RegimeResultDTO(
            regime=regime,
            confidence=confidence,
            details=details,
            regime_name_cn=regime_name_cn
        )
    
    def get_strategy_config(self, regime: str) -> Dict[str, Any]:
        """獲取指定市場狀態的策略配置
        
        Args:
            regime: 'Trend' | 'Reversion' | 'Breakout'
            
        Returns:
            dict: 策略配置字典
        """
        return self.regime_detector.get_strategy_config(regime)

