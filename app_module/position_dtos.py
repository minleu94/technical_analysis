"""
持倉資料傳輸對象 (Position Data Transfer Objects)
定義 Position 和 Portfolio 的資料結構
"""

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from datetime import datetime


@dataclass
class PositionDTO:
    """持倉資料傳輸對象"""
    
    # 基本資訊
    position_id: str  # 持倉 ID（唯一標識）
    stock_code: str  # 股票代號
    stock_name: str  # 股票名稱
    
    # 持有狀態
    is_holding: bool  # 當前是否持有（Yes / No）
    entry_date: str  # 進場日期（YYYY-MM-DD）
    holding_days: int  # 已持有天數
    
    # 進場來源（與 Phase 3 關聯）
    entry_source_type: str  # 'recommendation' / 'backtest' / 'strategy_version'
    entry_source_id: str  # 來源 ID（recommendation_result_id / backtest_run_id / strategy_version_id）
    entry_source_name: str  # 來源名稱（用於顯示）
    
    # 進場時的快照（Snapshot）
    entry_snapshot: Dict[str, Any]  # 包含：
        # - recommendation_snapshot: RecommendationResultDTO（如果是從推薦進場）
        # - backtest_snapshot: BacktestRun（如果是從回測進場）
        # - strategy_version_snapshot: StrategyVersion（如果是從策略版本進場）
        # - entry_regime: str  # 進場時的 Regime
        # - entry_total_score: float  # 進場時的 TotalScore
        # - entry_price: float  # 進場價格
        # - entry_reasons: str  # 進場理由
    
    # 當前狀態（對照用）
    current_regime: Optional[str] = None  # 當前 Regime
    current_total_score: Optional[float] = None  # 當前 TotalScore
    current_price: Optional[float] = None  # 當前價格
    
    # 未實現損益（僅顯示，不驅動行為）
    unrealized_pnl: Optional[float] = None  # 未實現損益（金額）
    unrealized_pnl_pct: Optional[float] = None  # 未實現損益（百分比）
    
    # 條件監控狀態
    condition_status: str = 'valid'  # 'valid' / 'warning' / 'invalid'
    condition_details: Dict[str, Any] = field(default_factory=dict)  # 條件監控詳細資訊
        # - regime_changed: bool  # Regime 是否改變
        # - score_degraded: bool  # TotalScore 是否下降
        # - price_change: float  # 價格變化百分比
    
    # 備註
    notes: str = ""  # 使用者備註
    created_at: str = ""  # 建立時間
    updated_at: str = ""  # 最後更新時間
    
    def to_dict(self) -> dict:
        """轉換為字典"""
        return {
            'position_id': self.position_id,
            'stock_code': self.stock_code,
            'stock_name': self.stock_name,
            'is_holding': self.is_holding,
            'entry_date': self.entry_date,
            'holding_days': self.holding_days,
            'entry_source_type': self.entry_source_type,
            'entry_source_id': self.entry_source_id,
            'entry_source_name': self.entry_source_name,
            'entry_snapshot': self.entry_snapshot,
            'current_regime': self.current_regime,
            'current_total_score': self.current_total_score,
            'current_price': self.current_price,
            'unrealized_pnl': self.unrealized_pnl,
            'unrealized_pnl_pct': self.unrealized_pnl_pct,
            'condition_status': self.condition_status,
            'condition_details': self.condition_details,
            'notes': self.notes,
            'created_at': self.created_at,
            'updated_at': self.updated_at
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'PositionDTO':
        """從字典創建對象"""
        return cls(
            position_id=data.get('position_id', ''),
            stock_code=data.get('stock_code', ''),
            stock_name=data.get('stock_name', ''),
            is_holding=data.get('is_holding', False),
            entry_date=data.get('entry_date', ''),
            holding_days=data.get('holding_days', 0),
            entry_source_type=data.get('entry_source_type', ''),
            entry_source_id=data.get('entry_source_id', ''),
            entry_source_name=data.get('entry_source_name', ''),
            entry_snapshot=data.get('entry_snapshot', {}),
            current_regime=data.get('current_regime'),
            current_total_score=data.get('current_total_score'),
            current_price=data.get('current_price'),
            unrealized_pnl=data.get('unrealized_pnl'),
            unrealized_pnl_pct=data.get('unrealized_pnl_pct'),
            condition_status=data.get('condition_status', 'valid'),
            condition_details=data.get('condition_details', {}),
            notes=data.get('notes', ''),
            created_at=data.get('created_at', ''),
            updated_at=data.get('updated_at', '')
        )


@dataclass
class PortfolioDTO:
    """投資組合資料傳輸對象"""
    
    # 基本資訊
    portfolio_id: str  # 投資組合 ID
    portfolio_name: str  # 投資組合名稱
    
    # 持倉總覽
    total_positions: int  # 目前持倉數量
    active_positions: int  # 活躍持倉數量（is_holding=True）
    
    # 持倉分布
    holding_days_distribution: Dict[str, int] = field(default_factory=dict)  # 持有天數分布
        # {'0-7': 3, '8-30': 5, '31-90': 2, '90+': 1}
    profile_distribution: Dict[str, int] = field(default_factory=dict)  # Profile 分布
        # {'profile_1': 5, 'profile_2': 3, ...}
    strategy_version_distribution: Dict[str, int] = field(default_factory=dict)  # 策略版本分布
        # {'version_1': 4, 'version_2': 2, ...}
    
    # 未實現損益總覽（僅資訊呈現）
    total_unrealized_pnl: float = 0.0  # 總未實現損益（金額）
    total_unrealized_pnl_pct: float = 0.0  # 總未實現損益（百分比）
    positions_pnl_breakdown: List[Dict[str, Any]] = field(default_factory=list)  # 各持倉損益明細
    
    # 與 Benchmark 的整體對比（資訊性）
    benchmark_comparison: Optional[Dict[str, Any]] = None
        # - benchmark_type: str  # 'buy_hold' / 'market_index'
        # - portfolio_return: float  # 投資組合報酬率
        # - benchmark_return: float  # 基準報酬率
        # - excess_return: float  # 超額報酬率
    
    # 條件監控總覽
    condition_summary: Dict[str, int] = field(default_factory=dict)  # 條件狀態分布
        # {'valid': 8, 'warning': 2, 'invalid': 1}
    
    # 持倉列表
    positions: List[PositionDTO] = field(default_factory=list)  # 所有持倉列表
    
    # 時間戳
    created_at: str = ""  # 建立時間
    updated_at: str = ""  # 最後更新時間
    
    def to_dict(self) -> dict:
        """轉換為字典"""
        return {
            'portfolio_id': self.portfolio_id,
            'portfolio_name': self.portfolio_name,
            'total_positions': self.total_positions,
            'active_positions': self.active_positions,
            'holding_days_distribution': self.holding_days_distribution,
            'profile_distribution': self.profile_distribution,
            'strategy_version_distribution': self.strategy_version_distribution,
            'total_unrealized_pnl': self.total_unrealized_pnl,
            'total_unrealized_pnl_pct': self.total_unrealized_pnl_pct,
            'positions_pnl_breakdown': self.positions_pnl_breakdown,
            'benchmark_comparison': self.benchmark_comparison,
            'condition_summary': self.condition_summary,
            'positions': [pos.to_dict() for pos in self.positions],
            'created_at': self.created_at,
            'updated_at': self.updated_at
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'PortfolioDTO':
        """從字典創建對象"""
        positions = [
            PositionDTO.from_dict(pos) if isinstance(pos, dict) else pos
            for pos in data.get('positions', [])
        ]
        return cls(
            portfolio_id=data.get('portfolio_id', ''),
            portfolio_name=data.get('portfolio_name', ''),
            total_positions=data.get('total_positions', 0),
            active_positions=data.get('active_positions', 0),
            holding_days_distribution=data.get('holding_days_distribution', {}),
            profile_distribution=data.get('profile_distribution', {}),
            strategy_version_distribution=data.get('strategy_version_distribution', {}),
            total_unrealized_pnl=data.get('total_unrealized_pnl', 0.0),
            total_unrealized_pnl_pct=data.get('total_unrealized_pnl_pct', 0.0),
            positions_pnl_breakdown=data.get('positions_pnl_breakdown', []),
            benchmark_comparison=data.get('benchmark_comparison'),
            condition_summary=data.get('condition_summary', {}),
            positions=positions,
            created_at=data.get('created_at', ''),
            updated_at=data.get('updated_at', '')
        )

