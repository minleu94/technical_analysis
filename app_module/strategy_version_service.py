"""
策略版本服務 (Strategy Version Service)
管理策略版本的生命週期
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime
from dataclasses import dataclass, asdict

logger = logging.getLogger(__name__)


@dataclass
class StrategyVersion:
    """策略版本資料結構"""
    version_id: str
    strategy_id: str
    strategy_version: str  # 版本號（如 "1.0.0"）
    source_run_id: str  # 來源回測 run_id
    promoted_at: str  # 升級時間
    # 策略參數
    params: Dict[str, Any]  # buy_score, sell_score, confirm_days 等
    config: Dict[str, Any]  # 完整策略配置（technical, patterns, signals）
    # 回測摘要
    backtest_summary: Dict[str, Any]  # total_return, sharpe_ratio, max_drawdown 等
    # 適用 Regime
    regime: List[str]  # ['Trend', 'Reversion', 'Breakout']
    # Profile 關聯
    profile_id: Optional[str] = None  # 掛載到哪個 Profile（可選）
    profile_version: Optional[str] = None  # Profile 版本（可選）
    # 驗證狀態
    validation_status: str = "pending"  # 'pending', 'validated', 'rejected'
    validation_metrics: Optional[Dict[str, Any]] = None  # Walk-Forward 結果、Baseline 對比結果
    notes: Optional[str] = None  # 備註
    
    def to_dict(self) -> Dict[str, Any]:
        """轉換為字典"""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'StrategyVersion':
        """從字典創建"""
        return cls(**data)


class StrategyVersionService:
    """策略版本服務"""
    
    def __init__(self, config):
        """
        初始化策略版本服務
        
        Args:
            config: TWStockConfig 實例
        """
        self.config = config
        # 儲存在 data_root/backtest/versions/
        self.versions_dir = config.resolve_output_path('backtest/versions')
        self.versions_dir.mkdir(parents=True, exist_ok=True)
    
    def _generate_version_number(
        self,
        strategy_id: str,
        base_version: Optional[str] = None
    ) -> str:
        """
        生成版本號
        
        Args:
            strategy_id: 策略 ID
            base_version: 基礎版本號（可選，如果不提供則從現有版本推斷）
        
        Returns:
            版本號（如 "1.0.0"）
        """
        if base_version:
            # 如果提供了基礎版本號，遞增補丁版本
            parts = base_version.split('.')
            if len(parts) == 3:
                try:
                    major, minor, patch = map(int, parts)
                    patch += 1
                    return f"{major}.{minor}.{patch}"
                except ValueError:
                    pass
        
        # 查找現有版本
        existing_versions = self.list_versions(strategy_id)
        if existing_versions:
            # 找到最高版本號
            max_version = "0.0.0"
            for version_data in existing_versions:
                version_str = version_data.get('strategy_version', '0.0.0')
                if self._compare_version(version_str, max_version) > 0:
                    max_version = version_str
            
            # 遞增補丁版本
            parts = max_version.split('.')
            if len(parts) == 3:
                try:
                    major, minor, patch = map(int, parts)
                    patch += 1
                    return f"{major}.{minor}.{patch}"
                except ValueError:
                    pass
        
        # 預設從 1.0.0 開始
        return "1.0.0"
    
    def _compare_version(self, v1: str, v2: str) -> int:
        """
        比較版本號
        
        Returns:
            -1 if v1 < v2, 0 if v1 == v2, 1 if v1 > v2
        """
        def version_tuple(v):
            parts = v.split('.')
            return tuple(int(p) for p in parts[:3])
        
        try:
            t1 = version_tuple(v1)
            t2 = version_tuple(v2)
            if t1 < t2:
                return -1
            elif t1 > t2:
                return 1
            else:
                return 0
        except (ValueError, IndexError):
            return 0
    
    def create_version(
        self,
        strategy_id: str,
        strategy_version: Optional[str] = None,
        params: Optional[Dict[str, Any]] = None,
        config: Optional[Dict[str, Any]] = None,
        backtest_summary: Optional[Dict[str, Any]] = None,
        regime: Optional[List[str]] = None,
        source_run_id: Optional[str] = None,
        profile_id: Optional[str] = None,
        profile_version: Optional[str] = None,
        validation_status: str = "pending",
        validation_metrics: Optional[Dict[str, Any]] = None,
        notes: Optional[str] = None,
        version_id: Optional[str] = None
    ) -> str:
        """
        創建策略版本
        
        Args:
            strategy_id: 策略 ID
            strategy_version: 版本號（可選，如果不提供則自動生成）
            params: 策略參數
            config: 完整策略配置
            backtest_summary: 回測摘要
            regime: 適用 Regime
            source_run_id: 來源回測 run_id
            profile_id: Profile ID（可選）
            profile_version: Profile 版本（可選）
            validation_status: 驗證狀態
            validation_metrics: 驗證指標
            notes: 備註
            version_id: 版本 ID（可選，如果不提供則自動生成）
        
        Returns:
            版本 ID
        """
        if version_id is None:
            version_id = f"version_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        if strategy_version is None:
            strategy_version = self._generate_version_number(strategy_id)
        
        version = StrategyVersion(
            version_id=version_id,
            strategy_id=strategy_id,
            strategy_version=strategy_version,
            source_run_id=source_run_id or "",
            promoted_at=datetime.now().isoformat(),
            params=params or {},
            config=config or {},
            backtest_summary=backtest_summary or {},
            regime=regime or [],
            profile_id=profile_id,
            profile_version=profile_version,
            validation_status=validation_status,
            validation_metrics=validation_metrics,
            notes=notes
        )
        
        # 儲存為 JSON
        version_file = self.versions_dir / f"{version_id}.json"
        version_data = {
            'version': 1,
            **version.to_dict()
        }
        
        version_file.write_text(
            json.dumps(version_data, ensure_ascii=False, indent=2),
            encoding='utf-8'
        )
        
        logger.info(
            f"[StrategyVersionService] 創建策略版本: "
            f"version_id={version_id}, strategy_id={strategy_id}, "
            f"strategy_version={strategy_version}"
        )
        
        return version_id
    
    def get_version(self, version_id: str) -> Optional[StrategyVersion]:
        """
        獲取策略版本
        
        Args:
            version_id: 版本 ID
        
        Returns:
            StrategyVersion 對象或 None
        """
        version_file = self.versions_dir / f"{version_id}.json"
        
        if not version_file.exists():
            return None
        
        try:
            data = json.loads(version_file.read_text(encoding='utf-8'))
            return StrategyVersion.from_dict(data)
        except Exception as e:
            logger.error(f"[StrategyVersionService] 載入版本失敗 {version_id}: {e}")
            return None
    
    def list_versions(
        self,
        strategy_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        列出策略版本
        
        Args:
            strategy_id: 策略 ID 篩選（可選）
        
        Returns:
            版本列表
        """
        versions = []
        
        for version_file in self.versions_dir.glob("*.json"):
            try:
                data = json.loads(version_file.read_text(encoding='utf-8'))
                version_data = StrategyVersion.from_dict(data)
                
                # 篩選
                if strategy_id and version_data.strategy_id != strategy_id:
                    continue
                
                versions.append(version_data.to_dict())
            except Exception as e:
                logger.warning(f"[StrategyVersionService] 讀取版本失敗 {version_file}: {e}")
                continue
        
        # 按升級時間排序（最新的在前）
        versions.sort(key=lambda x: x.get('promoted_at', ''), reverse=True)
        return versions
    
    def delete_version(self, version_id: str) -> bool:
        """
        刪除策略版本
        
        Args:
            version_id: 版本 ID
        
        Returns:
            是否成功刪除
        """
        version_file = self.versions_dir / f"{version_id}.json"
        
        if not version_file.exists():
            return False
        
        try:
            version_file.unlink()
            logger.info(f"[StrategyVersionService] 刪除版本: {version_id}")
            return True
        except Exception as e:
            logger.error(f"[StrategyVersionService] 刪除版本失敗 {version_id}: {e}")
            return False
    
    def update_version(
        self,
        version_id: str,
        **kwargs
    ) -> bool:
        """
        更新策略版本
        
        Args:
            version_id: 版本 ID
            **kwargs: 要更新的欄位
        
        Returns:
            是否成功更新
        """
        version = self.get_version(version_id)
        if version is None:
            return False
        
        # 更新欄位
        for key, value in kwargs.items():
            if hasattr(version, key):
                setattr(version, key, value)
        
        # 更新時間戳
        version.promoted_at = datetime.now().isoformat()
        
        # 保存
        version_file = self.versions_dir / f"{version_id}.json"
        version_data = {
            'version': 1,
            **version.to_dict()
        }
        
        try:
            version_file.write_text(
                json.dumps(version_data, ensure_ascii=False, indent=2),
                encoding='utf-8'
            )
            logger.info(f"[StrategyVersionService] 更新版本: {version_id}")
            return True
        except Exception as e:
            logger.error(f"[StrategyVersionService] 更新版本失敗 {version_id}: {e}")
            return False

