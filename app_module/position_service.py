"""
持倉服務類（Position Service）
管理 Position 的 CRUD 操作和狀態更新
"""

import json
import logging
from pathlib import Path
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
from dataclasses import asdict

from app_module.position_dtos import PositionDTO
from data_module.config import TWStockConfig

logger = logging.getLogger(__name__)


class PositionService:
    """持倉服務類"""
    
    def __init__(self, config: TWStockConfig):
        """
        初始化持倉服務
        
        Args:
            config: TWStockConfig 實例
        """
        self.config = config
        self.positions_dir = Path(config.output_root) / 'portfolio' / 'positions'
        self.positions_dir.mkdir(parents=True, exist_ok=True)
    
    def create_position(
        self,
        stock_code: str,
        stock_name: str,
        entry_source_type: str,
        entry_source_id: str,
        entry_source_name: str,
        entry_price: float,
        entry_snapshot: Dict[str, Any],
        notes: str = ""
    ) -> PositionDTO:
        """
        建立新持倉
        
        Args:
            stock_code: 股票代號
            stock_name: 股票名稱
            entry_source_type: 進場來源類型（'recommendation' / 'backtest' / 'strategy_version'）
            entry_source_id: 來源 ID
            entry_source_name: 來源名稱
            entry_price: 進場價格
            entry_snapshot: 進場快照（包含 Regime、TotalScore、理由等）
            notes: 備註
        
        Returns:
            PositionDTO: 新建立的持倉
        """
        # 生成 Position ID
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        position_id = f"pos_{timestamp}_{stock_code}"
        
        # 建立 PositionDTO
        position = PositionDTO(
            position_id=position_id,
            stock_code=stock_code,
            stock_name=stock_name,
            is_holding=True,
            entry_date=datetime.now().strftime('%Y-%m-%d'),
            holding_days=0,
            entry_source_type=entry_source_type,
            entry_source_id=entry_source_id,
            entry_source_name=entry_source_name,
            entry_snapshot=entry_snapshot,
            current_price=entry_price,
            unrealized_pnl=0.0,
            unrealized_pnl_pct=0.0,
            condition_status='valid',
            condition_details={},
            notes=notes,
            created_at=datetime.now().isoformat(),
            updated_at=datetime.now().isoformat()
        )
        
        # 保存到檔案
        self._save_position(position)
        
        logger.info(f"[PositionService] 建立新持倉: {position_id} ({stock_code})")
        return position
    
    def get_position(self, position_id: str) -> Optional[PositionDTO]:
        """
        取得持倉資訊
        
        Args:
            position_id: 持倉 ID
        
        Returns:
            PositionDTO 或 None
        """
        position_file = self.positions_dir / f"{position_id}.json"
        if not position_file.exists():
            logger.warning(f"[PositionService] 找不到持倉: {position_id}")
            return None
        
        try:
            with open(position_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return PositionDTO.from_dict(data)
        except Exception as e:
            logger.error(f"[PositionService] 讀取持倉失敗: {position_id}, {e}")
            return None
    
    def list_positions(self, is_holding: Optional[bool] = None) -> List[PositionDTO]:
        """
        列出所有持倉
        
        Args:
            is_holding: 是否只列出持有中的持倉（None 表示全部）
        
        Returns:
            List[PositionDTO]: 持倉列表
        """
        positions = []
        
        for position_file in self.positions_dir.glob('*.json'):
            try:
                with open(position_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                position = PositionDTO.from_dict(data)
                
                # 過濾條件
                if is_holding is None or position.is_holding == is_holding:
                    positions.append(position)
            except Exception as e:
                logger.warning(f"[PositionService] 讀取持倉檔案失敗: {position_file}, {e}")
        
        # 按建立時間排序（最新的在前）
        positions.sort(key=lambda p: p.created_at, reverse=True)
        
        return positions
    
    def update_position_status(
        self,
        position_id: str,
        current_price: Optional[float] = None,
        current_regime: Optional[str] = None,
        current_total_score: Optional[float] = None
    ) -> Optional[PositionDTO]:
        """
        更新持倉當前狀態（價格、TotalScore、Regime）
        
        Args:
            position_id: 持倉 ID
            current_price: 當前價格
            current_regime: 當前 Regime
            current_total_score: 當前 TotalScore
        
        Returns:
            更新後的 PositionDTO 或 None
        """
        position = self.get_position(position_id)
        if position is None:
            return None
        
        # 更新當前狀態
        if current_price is not None:
            position.current_price = current_price
        if current_regime is not None:
            position.current_regime = current_regime
        if current_total_score is not None:
            position.current_total_score = current_total_score
        
        # 計算未實現損益
        if position.current_price is not None and position.entry_snapshot.get('entry_price'):
            entry_price = position.entry_snapshot.get('entry_price')
            if entry_price:
                position.unrealized_pnl = position.current_price - entry_price
                position.unrealized_pnl_pct = (position.current_price / entry_price - 1) * 100
        
        # 更新持有天數
        entry_date = datetime.strptime(position.entry_date, '%Y-%m-%d')
        position.holding_days = (datetime.now() - entry_date).days
        
        # 檢查條件狀態
        self._check_condition(position)
        
        # 更新時間戳
        position.updated_at = datetime.now().isoformat()
        
        # 保存
        self._save_position(position)
        
        logger.info(f"[PositionService] 更新持倉狀態: {position_id}")
        return position
    
    def check_condition(self, position_id: str) -> Dict[str, Any]:
        """
        檢查持倉條件狀態
        
        Args:
            position_id: 持倉 ID
        
        Returns:
            條件監控結果
        """
        position = self.get_position(position_id)
        if position is None:
            return {}
        
        self._check_condition(position)
        self._save_position(position)
        
        return {
            'condition_status': position.condition_status,
            'condition_details': position.condition_details
        }
    
    def close_position(
        self,
        position_id: str,
        exit_date: str,
        exit_price: float,
        exit_reasons: str
    ) -> Optional[PositionDTO]:
        """
        平倉（標記為不再持有）
        
        Args:
            position_id: 持倉 ID
            exit_date: 出場日期（YYYY-MM-DD）
            exit_price: 出場價格
            exit_reasons: 出場理由
        
        Returns:
            更新後的 PositionDTO 或 None
        """
        position = self.get_position(position_id)
        if position is None:
            return None
        
        # 標記為不再持有
        position.is_holding = False
        
        # 更新出場資訊到 entry_snapshot
        position.entry_snapshot['exit_date'] = exit_date
        position.entry_snapshot['exit_price'] = exit_price
        position.entry_snapshot['exit_reasons'] = exit_reasons
        
        # 計算實現損益
        entry_price = position.entry_snapshot.get('entry_price', 0)
        if entry_price:
            realized_pnl = exit_price - entry_price
            realized_pnl_pct = (exit_price / entry_price - 1) * 100
            position.entry_snapshot['realized_pnl'] = realized_pnl
            position.entry_snapshot['realized_pnl_pct'] = realized_pnl_pct
        
        # 更新時間戳
        position.updated_at = datetime.now().isoformat()
        
        # 保存
        self._save_position(position)
        
        logger.info(f"[PositionService] 平倉: {position_id}")
        return position
    
    def _check_condition(self, position: PositionDTO):
        """
        檢查持倉條件狀態（內部方法）
        
        Args:
            position: PositionDTO 實例
        """
        entry_regime = position.entry_snapshot.get('entry_regime')
        entry_total_score = position.entry_snapshot.get('entry_total_score')
        
        condition_details = {
            'regime_changed': False,
            'score_degraded': False,
            'price_change': 0.0
        }
        
        # 檢查 Regime 是否改變
        if entry_regime and position.current_regime:
            condition_details['regime_changed'] = (entry_regime != position.current_regime)
        
        # 檢查 TotalScore 是否下降
        if entry_total_score is not None and position.current_total_score is not None:
            score_change = position.current_total_score - entry_total_score
            condition_details['score_degraded'] = (score_change < -10)  # 下降超過 10 分
            condition_details['score_change'] = score_change
        
        # 計算價格變化
        entry_price = position.entry_snapshot.get('entry_price')
        if entry_price and position.current_price:
            condition_details['price_change'] = (position.current_price / entry_price - 1) * 100
        
        # 判斷條件狀態
        if condition_details['regime_changed'] or condition_details['score_degraded']:
            if condition_details['score_degraded'] and condition_details['regime_changed']:
                position.condition_status = 'invalid'
            else:
                position.condition_status = 'warning'
        else:
            position.condition_status = 'valid'
        
        position.condition_details = condition_details
    
    def _save_position(self, position: PositionDTO):
        """
        保存持倉到檔案（內部方法）
        
        Args:
            position: PositionDTO 實例
        """
        position_file = self.positions_dir / f"{position.position_id}.json"
        try:
            with open(position_file, 'w', encoding='utf-8') as f:
                json.dump(position.to_dict(), f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"[PositionService] 保存持倉失敗: {position.position_id}, {e}")
            raise

