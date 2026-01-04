"""
策略預設服務 (Strategy Preset Service)
管理策略設定的儲存、載入、刪除
"""

import json
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime
from dataclasses import dataclass, asdict


@dataclass
class StrategyPreset:
    """策略預設資料結構"""
    name: str
    strategy_id: str
    params: Dict[str, Any]
    meta: Dict[str, Any] = None
    created_at: str = None
    updated_at: str = None
    tags: List[str] = None
    
    def __post_init__(self):
        """初始化後處理"""
        if self.meta is None:
            self.meta = {}
        if self.tags is None:
            self.tags = []
        if self.created_at is None:
            self.created_at = datetime.now().isoformat()
        if self.updated_at is None:
            self.updated_at = datetime.now().isoformat()


class PresetService:
    """策略預設服務"""
    
    def __init__(self, config):
        """
        初始化預設服務
        
        Args:
            config: TWStockConfig 實例
        """
        self.config = config
        # 預設儲存在 data_root/backtest/presets/
        self.presets_dir = config.resolve_output_path('backtest/presets')
        self.presets_dir.mkdir(parents=True, exist_ok=True)
    
    def save_preset(
        self,
        name: str,
        strategy_id: str,
        params: Dict[str, Any],
        meta: Optional[Dict[str, Any]] = None,
        tags: Optional[List[str]] = None,
        preset_id: Optional[str] = None
    ) -> str:
        """
        儲存策略預設
        
        Args:
            name: 預設名稱
            strategy_id: 策略ID
            params: 策略參數
            meta: 元資料（可選）
            tags: 標籤列表（可選）
            preset_id: 預設ID（如果提供則更新，否則新建）
        
        Returns:
            預設ID
        """
        if preset_id is None:
            # 生成新的ID（使用時間戳）
            preset_id = f"preset_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        preset = StrategyPreset(
            name=name,
            strategy_id=strategy_id,
            params=params,
            meta=meta or {},
            tags=tags or [],
            created_at=datetime.now().isoformat(),
            updated_at=datetime.now().isoformat()
        )
        
        # 如果更新現有預設，保留原始創建時間
        existing_file = self.presets_dir / f"{preset_id}.json"
        if existing_file.exists():
            try:
                existing_data = json.loads(existing_file.read_text(encoding='utf-8'))
                preset.created_at = existing_data.get('created_at', preset.created_at)
            except:
                pass
        
        # 儲存為JSON
        preset_file = self.presets_dir / f"{preset_id}.json"
        preset_data = {
            'version': 1,
            'preset_id': preset_id,
            **asdict(preset)
        }
        
        preset_file.write_text(
            json.dumps(preset_data, ensure_ascii=False, indent=2),
            encoding='utf-8'
        )
        
        return preset_id
    
    def list_presets(self) -> List[Dict[str, Any]]:
        """
        列出所有預設
        
        Returns:
            預設列表（包含ID、名稱、策略ID等）
        """
        presets = []
        
        for preset_file in self.presets_dir.glob("*.json"):
            try:
                data = json.loads(preset_file.read_text(encoding='utf-8'))
                presets.append({
                    'preset_id': data.get('preset_id', preset_file.stem),
                    'name': data.get('name', ''),
                    'strategy_id': data.get('strategy_id', ''),
                    'params': data.get('params', {}),
                    'tags': data.get('tags', []),
                    'created_at': data.get('created_at', ''),
                    'updated_at': data.get('updated_at', '')
                })
            except Exception as e:
                print(f"[PresetService] 讀取預設失敗 {preset_file}: {e}")
                continue
        
        # 按更新時間排序（最新的在前）
        presets.sort(key=lambda x: x.get('updated_at', ''), reverse=True)
        return presets
    
    def load_preset(self, preset_id: str) -> Optional[StrategyPreset]:
        """
        載入預設
        
        Args:
            preset_id: 預設ID
        
        Returns:
            StrategyPreset 對象或 None
        """
        preset_file = self.presets_dir / f"{preset_id}.json"
        
        if not preset_file.exists():
            return None
        
        try:
            data = json.loads(preset_file.read_text(encoding='utf-8'))
            return StrategyPreset(
                name=data.get('name', ''),
                strategy_id=data.get('strategy_id', ''),
                params=data.get('params', {}),
                meta=data.get('meta', {}),
                tags=data.get('tags', []),
                created_at=data.get('created_at'),
                updated_at=data.get('updated_at')
            )
        except Exception as e:
            print(f"[PresetService] 載入預設失敗 {preset_id}: {e}")
            return None
    
    def delete_preset(self, preset_id: str) -> bool:
        """
        刪除預設
        
        Args:
            preset_id: 預設ID
        
        Returns:
            是否成功刪除
        """
        preset_file = self.presets_dir / f"{preset_id}.json"
        
        if not preset_file.exists():
            return False
        
        try:
            preset_file.unlink()
            return True
        except Exception as e:
            print(f"[PresetService] 刪除預設失敗 {preset_id}: {e}")
            return False
    
    def export_preset(self, preset_id: str) -> Optional[Dict[str, Any]]:
        """
        匯出預設（用於分享/備份）
        
        Args:
            preset_id: 預設ID
        
        Returns:
            預設資料字典或 None
        """
        preset = self.load_preset(preset_id)
        if preset is None:
            return None
        
        return asdict(preset)
    
    def import_preset(self, preset_data: Dict[str, Any]) -> str:
        """
        匯入預設
        
        Args:
            preset_data: 預設資料字典
        
        Returns:
            新的預設ID
        """
        # 生成新ID（避免衝突）
        preset_id = f"preset_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        preset = StrategyPreset(
            name=preset_data.get('name', 'Imported Preset'),
            strategy_id=preset_data.get('strategy_id', ''),
            params=preset_data.get('params', {}),
            meta=preset_data.get('meta', {}),
            tags=preset_data.get('tags', []),
            created_at=datetime.now().isoformat(),
            updated_at=datetime.now().isoformat()
        )
        
        preset_file = self.presets_dir / f"{preset_id}.json"
        preset_file.write_text(
            json.dumps({
                'version': 1,
                'preset_id': preset_id,
                **asdict(preset)
            }, ensure_ascii=False, indent=2),
            encoding='utf-8'
        )
        
        return preset_id
    
    def save_from_backtest_run(
        self,
        run_id: str,
        name: Optional[str] = None,
        backtest_repository=None
    ) -> str:
        """
        從回測結果保存為 Preset（MVP 版本的 Promote 功能）
        
        Args:
            run_id: 回測執行 ID
            name: Preset 名稱（可選，如果不提供則自動生成）
            backtest_repository: BacktestRunRepository 實例（可選）
        
        Returns:
            Preset ID
        """
        if backtest_repository is None:
            raise ValueError("需要提供 backtest_repository 參數")
        
        # 載入回測結果
        run = backtest_repository.get_run(run_id)
        if run is None:
            raise ValueError(f"找不到回測結果: {run_id}")
        
        # 生成名稱
        if name is None:
            name = f"{run.strategy_id}_{run.run_name}_{datetime.now().strftime('%Y%m%d')}"
        
        # 構建 meta 資訊
        meta = {
            'source_run_id': run_id,
            'source_run_name': run.run_name,
            'stock_code': run.stock_code,
            'start_date': run.start_date,
            'end_date': run.end_date,
            'backtest_summary': {
                'total_return': run.total_return,
                'sharpe_ratio': run.sharpe_ratio,
                'max_drawdown': run.max_drawdown,
                'win_rate': run.win_rate
            }
        }
        
        # 保存為 Preset
        preset_id = self.save_preset(
            name=name,
            strategy_id=run.strategy_id,
            params=run.strategy_params,
            meta=meta,
            tags=['promoted', 'from_backtest']
        )
        
        return preset_id

