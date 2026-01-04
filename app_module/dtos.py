"""
數據傳輸對象 (Data Transfer Objects)
定義服務層的輸入輸出結構
"""

from dataclasses import dataclass
from typing import List, Optional, Dict, Any
import pandas as pd


@dataclass
class RecommendationDTO:
    """股票推薦數據傳輸對象"""
    stock_code: str
    stock_name: str
    close_price: float
    price_change: float  # 漲幅百分比
    total_score: float
    indicator_score: float
    pattern_score: float
    volume_score: float
    recommendation_reasons: str
    industry: str
    regime_match: bool
    
    def to_dict(self) -> dict:
        """轉換為字典"""
        return {
            '證券代號': self.stock_code,
            '證券名稱': self.stock_name,
            '收盤價': self.close_price,
            '漲幅%': self.price_change,
            '總分': self.total_score,
            '指標分': self.indicator_score,
            '圖形分': self.pattern_score,
            '成交量分': self.volume_score,
            '推薦理由': self.recommendation_reasons,
            '產業': self.industry,
            'Regime匹配': '是' if self.regime_match else '否'
        }


@dataclass
class RegimeResultDTO:
    """市場狀態檢測結果"""
    regime: str  # 'Trend', 'Reversion', 'Breakout'
    confidence: float  # 0-1
    details: Dict[str, Any]
    regime_name_cn: str  # 中文名稱
    
    def to_dict(self) -> dict:
        """轉換為字典"""
        return {
            'regime': self.regime,
            'regime_name_cn': self.regime_name_cn,
            'confidence': self.confidence,
            'details': self.details
        }


@dataclass
class RecommendationResultDTO:
    """推薦結果數據傳輸對象（固定欄位，可保存、可追溯）"""
    result_id: str  # 結果ID（唯一標識）
    result_name: str  # 結果名稱
    config: Dict[str, Any]  # 策略配置（完整配置）
    recommendations: List[RecommendationDTO]  # 推薦股票列表
    regime: Optional[str] = None  # 市場狀態
    created_at: str = None  # 創建時間
    notes: str = ""  # 備註
    
    def to_dict(self) -> dict:
        """轉換為字典"""
        return {
            'result_id': self.result_id,
            'result_name': self.result_name,
            'config': self.config,
            'recommendations': [rec.to_dict() for rec in self.recommendations],
            'regime': self.regime,
            'created_at': self.created_at,
            'notes': self.notes
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'RecommendationResultDTO':
        """從字典創建對象"""
        recommendations = [
            RecommendationDTO(**rec) if isinstance(rec, dict) else rec
            for rec in data.get('recommendations', [])
        ]
        return cls(
            result_id=data.get('result_id', ''),
            result_name=data.get('result_name', ''),
            config=data.get('config', {}),
            recommendations=recommendations,
            regime=data.get('regime'),
            created_at=data.get('created_at'),
            notes=data.get('notes', '')
        )


@dataclass
class BacktestReportDTO:
    """回測報告數據傳輸對象"""
    total_return: float
    annual_return: float
    sharpe_ratio: float
    max_drawdown: float
    win_rate: float
    total_trades: int
    expectancy: float  # 期望值（平均報酬）
    details: Dict[str, Any]
    baseline_comparison: Optional[Dict[str, Any]] = None  # Baseline 對比結果
    overfitting_risk: Optional[Dict[str, Any]] = None  # 過擬合風險評估結果
    
    def to_dict(self) -> dict:
        """轉換為字典"""
        result = {
            '總報酬率': self.total_return,
            '年化報酬率': self.annual_return,
            '夏普比率': self.sharpe_ratio,
            '最大回撤': self.max_drawdown,
            '勝率': self.win_rate,
            '總交易次數': self.total_trades,
            '期望值': self.expectancy,
            '詳細信息': self.details
        }
        if self.baseline_comparison:
            result['Baseline對比'] = self.baseline_comparison
        if self.overfitting_risk:
            result['過擬合風險'] = self.overfitting_risk
        return result

