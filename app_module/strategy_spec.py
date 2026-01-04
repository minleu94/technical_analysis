"""
策略規格定義
定義 StrategySpec、StrategyExecutor、StrategyMeta
"""

from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Protocol, runtime_checkable
from datetime import datetime
import pandas as pd


@dataclass
class StrategySpec:
    """策略規格（純資料，可序列化為 JSON/YAML）"""
    strategy_id: str  # 固定 ID，例如 "breakout_momentum_v1"
    strategy_version: str  # 例如 "1.0.0"
    data_version: Optional[str] = None  # 對應技術指標版本/資料修復版本
    name: str = ""  # 顯示名稱
    description: str = ""  # 策略說明
    regime: List[str] = field(default_factory=list)  # 適用 Regime: ['Trend', 'Reversion', 'Breakout']
    risk_level: str = "medium"  # 'low', 'medium', 'high'
    target_type: str = "stock"  # 'stock', 'industry', 'both'
    default_params: Dict[str, Any] = field(default_factory=dict)  # 預設參數
    config: Dict[str, Any] = field(default_factory=dict)  # 完整策略配置（technical, patterns, signals, filters）
    
    def to_dict(self) -> Dict[str, Any]:
        """轉換為字典（可序列化）"""
        return {
            'strategy_id': self.strategy_id,
            'strategy_version': self.strategy_version,
            'data_version': self.data_version,
            'name': self.name,
            'description': self.description,
            'regime': self.regime,
            'risk_level': self.risk_level,
            'target_type': self.target_type,
            'default_params': self.default_params,
            'config': self.config
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'StrategySpec':
        """從字典創建（反序列化）"""
        return cls(**data)


@dataclass
class StrategyMeta:
    """策略元數據（適用/不適用 Regime、風險屬性）"""
    strategy_id: str
    strategy_version: str
    name: str
    description: str  # 策略說明（Why，不是 How）
    regime: List[str]  # 適用 Regime: ['Trend', 'Reversion', 'Breakout']
    risk_level: str  # 'low', 'medium', 'high'
    not_suitable_regime: List[str] = field(default_factory=list)  # 不適用 Regime
    risk_description: str = ""  # 風險敘述
    target_type: str = "stock"  # 'stock', 'industry', 'both'
    default_params: Dict[str, Any] = field(default_factory=dict)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    
    def __post_init__(self):
        """初始化後處理"""
        if self.created_at is None:
            self.created_at = datetime.now()
        if self.updated_at is None:
            self.updated_at = datetime.now()
    
    def to_dict(self) -> Dict[str, Any]:
        """轉換為字典"""
        return {
            'strategy_id': self.strategy_id,
            'strategy_version': self.strategy_version,
            'name': self.name,
            'description': self.description,
            'regime': self.regime,
            'risk_level': self.risk_level,
            'target_type': self.target_type,
            'default_params': self.default_params,
            'risk_description': self.risk_description,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }


@runtime_checkable
class StrategyExecutor(Protocol):
    """策略執行器介面（Protocol）"""
    
    def generate_signals(
        self, 
        df: pd.DataFrame, 
        spec: StrategySpec
    ) -> pd.DataFrame:
        """
        生成每日信號
        
        Args:
            df: 股票數據 DataFrame（必須包含日期索引和技術指標）
            spec: 策略規格
        
        Returns:
            DailySignalFrame: index=date，欄位含 signal, score breakdown, reason tags
                - signal: int (1=買入, 0=持有, -1=賣出)
                - score: float (總分 0-100)
                - indicator_score: float
                - pattern_score: float
                - volume_score: float
                - reason_tags: List[str] (可序列化為字符串)
                - regime_match: bool
                - ... (其他技術指標欄位)
        """
        ...


def create_daily_signal_frame(
    df: pd.DataFrame,
    signals: pd.Series,
    scores: Dict[str, pd.Series],
    reason_tags: pd.Series,
    regime_match: pd.Series
) -> pd.DataFrame:
    """
    創建 DailySignalFrame（統一輸出格式）
    
    Args:
        df: 原始數據 DataFrame（必須有日期索引）
        signals: 信號序列（1=買入, 0=持有, -1=賣出）
        scores: 分數字典 {'score': Series, 'indicator_score': Series, ...}
        reason_tags: 理由標籤序列（每個元素是 List[str]）
        regime_match: Regime 匹配序列（bool）
    
    Returns:
        DailySignalFrame: 統一的信號輸出格式
    """
    result = df.copy()
    
    # 確保日期索引
    if '日期' in result.columns:
        result = result.set_index('日期')
    
    # 添加信號和分數
    result['signal'] = signals
    for key, value in scores.items():
        result[key] = value
    
    # 添加理由標籤（轉換為字符串以便序列化）
    result['reason_tags'] = reason_tags.apply(lambda x: ','.join(x) if isinstance(x, list) else str(x))
    result['regime_match'] = regime_match
    
    return result

