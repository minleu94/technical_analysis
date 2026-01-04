"""
策略註冊表
管理所有策略執行器的註冊和獲取
"""

from typing import Dict, Type, Optional
from app_module.strategy_spec import StrategySpec, StrategyExecutor


class StrategyRegistry:
    """策略註冊表（工廠模式）"""
    
    _registry: Dict[str, Type[StrategyExecutor]] = {}
    
    @classmethod
    def register(cls, strategy_id: str, executor_cls: Type[StrategyExecutor]):
        """
        註冊策略執行器
        
        Args:
            strategy_id: 策略 ID（必須唯一）
            executor_cls: 策略執行器類別（必須實現 StrategyExecutor 介面）
        """
        if strategy_id in cls._registry:
            raise ValueError(f"策略 {strategy_id} 已經註冊過了")
        cls._registry[strategy_id] = executor_cls
    
    @classmethod
    def get_executor(cls, spec: StrategySpec) -> StrategyExecutor:
        """
        根據 StrategySpec 獲取對應的策略執行器實例
        
        Args:
            spec: 策略規格
        
        Returns:
            策略執行器實例
        
        Raises:
            ValueError: 如果策略 ID 未註冊
        """
        if spec.strategy_id not in cls._registry:
            raise ValueError(f"未知的策略: {spec.strategy_id}。已註冊的策略: {list(cls._registry.keys())}")
        
        executor_cls = cls._registry[spec.strategy_id]
        return executor_cls(spec)
    
    @classmethod
    def list_strategies(cls) -> Dict[str, Dict]:
        """
        列出所有已註冊的策略
        
        Returns:
            策略資訊字典 {strategy_id: {name, version, description, ...}}
        """
        from app_module.strategy_spec import StrategyMeta
        
        result = {}
        for strategy_id, executor_cls in cls._registry.items():
            # 嘗試從類別獲取元數據
            if hasattr(executor_cls, 'get_meta'):
                meta = executor_cls.get_meta()
                # 如果返回的是 StrategyMeta 對象，轉換為字典
                if isinstance(meta, StrategyMeta):
                    result[strategy_id] = meta.to_dict()
                elif isinstance(meta, dict):
                    result[strategy_id] = meta
                else:
                    # 其他類型，嘗試轉換
                    result[strategy_id] = {
                        'strategy_id': getattr(meta, 'strategy_id', strategy_id),
                        'name': getattr(meta, 'name', executor_cls.__name__),
                        'description': getattr(meta, 'description', executor_cls.__doc__ or ''),
                        'version': getattr(meta, 'strategy_version', '1.0')
                    }
            else:
                result[strategy_id] = {
                    'strategy_id': strategy_id,
                    'name': executor_cls.__name__,
                    'description': executor_cls.__doc__ or '',
                    'version': '1.0'
                }
        return result
    
    @classmethod
    def is_registered(cls, strategy_id: str) -> bool:
        """檢查策略是否已註冊"""
        return strategy_id in cls._registry

