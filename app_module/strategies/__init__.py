"""
策略執行器模組
自動註冊所有策略到 StrategyRegistry
"""

from app_module.strategy_registry import StrategyRegistry
from app_module.strategies.baseline_score_executor import BaselineScoreExecutor
from app_module.strategies.momentum_aggressive_executor import MomentumAggressiveExecutor
from app_module.strategies.stable_conservative_executor import StableConservativeExecutor

# 註冊策略
StrategyRegistry.register('baseline_score_threshold', BaselineScoreExecutor)
StrategyRegistry.register('momentum_aggressive_v1', MomentumAggressiveExecutor)
StrategyRegistry.register('stable_conservative_v1', StableConservativeExecutor)

__all__ = [
    'BaselineScoreExecutor',
    'MomentumAggressiveExecutor',
    'StableConservativeExecutor'
]
