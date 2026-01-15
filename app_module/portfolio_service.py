"""
投資組合服務類（Portfolio Service）
管理 Portfolio 總覽和統計資訊
"""

import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime
from collections import defaultdict

from app_module.position_dtos import PortfolioDTO, PositionDTO
from app_module.position_service import PositionService
from data_module.config import TWStockConfig

logger = logging.getLogger(__name__)


class PortfolioService:
    """投資組合服務類"""
    
    def __init__(self, config: TWStockConfig, position_service: PositionService):
        """
        初始化投資組合服務
        
        Args:
            config: TWStockConfig 實例
            position_service: PositionService 實例
        """
        self.config = config
        self.position_service = position_service
        self.portfolio_file = Path(config.output_root) / 'portfolio' / 'portfolio.json'
        self.portfolio_file.parent.mkdir(parents=True, exist_ok=True)
    
    def get_portfolio(self) -> PortfolioDTO:
        """
        取得投資組合總覽
        
        Returns:
            PortfolioDTO: 投資組合總覽
        """
        # 取得所有持倉
        positions = self.position_service.list_positions()
        active_positions = [p for p in positions if p.is_holding]
        
        # 計算持倉分布
        holding_days_distribution = self._calculate_holding_days_distribution(active_positions)
        profile_distribution = self._calculate_profile_distribution(active_positions)
        strategy_version_distribution = self._calculate_strategy_version_distribution(active_positions)
        
        # 計算未實現損益
        total_unrealized_pnl = sum(p.unrealized_pnl or 0.0 for p in active_positions)
        total_unrealized_pnl_pct = self._calculate_weighted_pnl_pct(active_positions)
        
        # 計算各持倉損益明細
        positions_pnl_breakdown = [
            {
                'stock_code': p.stock_code,
                'stock_name': p.stock_name,
                'unrealized_pnl': p.unrealized_pnl or 0.0,
                'unrealized_pnl_pct': p.unrealized_pnl_pct or 0.0
            }
            for p in active_positions
        ]
        
        # 計算條件監控總覽
        condition_summary = defaultdict(int)
        for p in active_positions:
            condition_summary[p.condition_status] += 1
        
        # 建立 PortfolioDTO
        portfolio = PortfolioDTO(
            portfolio_id='default',
            portfolio_name='預設投資組合',
            total_positions=len(positions),
            active_positions=len(active_positions),
            holding_days_distribution=holding_days_distribution,
            profile_distribution=profile_distribution,
            strategy_version_distribution=strategy_version_distribution,
            total_unrealized_pnl=total_unrealized_pnl,
            total_unrealized_pnl_pct=total_unrealized_pnl_pct,
            positions_pnl_breakdown=positions_pnl_breakdown,
            condition_summary=dict(condition_summary),
            positions=active_positions,
            created_at=datetime.now().isoformat(),
            updated_at=datetime.now().isoformat()
        )
        
        return portfolio
    
    def update_portfolio(self) -> PortfolioDTO:
        """
        更新投資組合資訊
        
        Returns:
            PortfolioDTO: 更新後的投資組合總覽
        """
        # 更新所有持倉的狀態
        positions = self.position_service.list_positions(is_holding=True)
        for position in positions:
            # 這裡應該調用其他服務來獲取當前價格、Regime、TotalScore
            # 目前先返回現有狀態
            pass
        
        # 重新計算總覽
        return self.get_portfolio()
    
    def get_benchmark_comparison(
        self,
        benchmark_type: str = 'buy_hold'
    ) -> Dict[str, Any]:
        """
        取得與 Benchmark 的對比（資訊性）
        
        Args:
            benchmark_type: 基準類型（'buy_hold' / 'market_index'）
        
        Returns:
            Benchmark 對比結果
        """
        # TODO: 實作 Benchmark 對比邏輯
        # 目前返回空字典，後續可以整合 BacktestService 的 Baseline 對比邏輯
        
        return {
            'benchmark_type': benchmark_type,
            'portfolio_return': 0.0,
            'benchmark_return': 0.0,
            'excess_return': 0.0,
            'note': 'Benchmark 對比功能待實作'
        }
    
    def _calculate_holding_days_distribution(self, positions: list[PositionDTO]) -> Dict[str, int]:
        """計算持有天數分布"""
        distribution = defaultdict(int)
        
        for position in positions:
            days = position.holding_days
            if days <= 7:
                distribution['0-7'] += 1
            elif days <= 30:
                distribution['8-30'] += 1
            elif days <= 90:
                distribution['31-90'] += 1
            else:
                distribution['90+'] += 1
        
        return dict(distribution)
    
    def _calculate_profile_distribution(self, positions: list[PositionDTO]) -> Dict[str, int]:
        """計算 Profile 分布"""
        distribution = defaultdict(int)
        
        for position in positions:
            # 從 entry_snapshot 中提取 profile_id
            snapshot = position.entry_snapshot
            if 'recommendation_snapshot' in snapshot:
                config = snapshot['recommendation_snapshot'].get('config', {})
                profile_id = config.get('profile_id', 'unknown')
                distribution[profile_id] += 1
            else:
                distribution['unknown'] += 1
        
        return dict(distribution)
    
    def _calculate_strategy_version_distribution(self, positions: list[PositionDTO]) -> Dict[str, int]:
        """計算策略版本分布"""
        distribution = defaultdict(int)
        
        for position in positions:
            # 從 entry_snapshot 中提取 strategy_version_id
            snapshot = position.entry_snapshot
            if 'strategy_version_snapshot' in snapshot:
                version_id = snapshot['strategy_version_snapshot'].get('version_id', 'unknown')
                distribution[version_id] += 1
            elif 'backtest_snapshot' in snapshot:
                # 從 backtest 中提取 promoted_version_id
                backtest = snapshot['backtest_snapshot']
                version_id = backtest.get('promoted_version_id', 'unknown')
                distribution[version_id] += 1
            else:
                distribution['unknown'] += 1
        
        return dict(distribution)
    
    def _calculate_weighted_pnl_pct(self, positions: list[PositionDTO]) -> float:
        """計算加權平均未實現損益百分比"""
        if not positions:
            return 0.0
        
        total_pnl = sum(p.unrealized_pnl_pct or 0.0 for p in positions)
        return total_pnl / len(positions) if positions else 0.0

