"""
推薦結果儲存庫 (Recommendation Result Repository)
管理推薦結果的儲存、載入、刪除
"""

import json
import sqlite3
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime
from dataclasses import dataclass, asdict
import numpy as np

from app_module.dtos import RecommendationResultDTO, RecommendationDTO


def _make_json_serializable(obj: Any) -> Any:
    """
    將對象轉換為 JSON 可序列化的格式
    
    處理：
    - numpy bool -> Python bool
    - numpy int -> Python int
    - numpy float -> Python float
    - numpy array -> list
    - 其他不可序列化的類型
    """
    # 處理 numpy 類型
    if isinstance(obj, np.bool_):
        return bool(obj)
    elif isinstance(obj, np.integer):
        return int(obj)
    elif isinstance(obj, np.floating):
        return float(obj)
    elif isinstance(obj, np.ndarray):
        return obj.tolist()
    # 處理基本類型（已經可序列化）
    elif isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    # 處理容器類型（遞歸處理）
    elif isinstance(obj, dict):
        return {key: _make_json_serializable(value) for key, value in obj.items()}
    elif isinstance(obj, (list, tuple)):
        return [_make_json_serializable(item) for item in obj]
    else:
        # 嘗試轉換為字符串
        try:
            return str(obj)
        except:
            return None


@dataclass
class RecommendationRun:
    """推薦結果記錄"""
    result_id: str
    result_name: str
    config: Dict[str, Any]
    regime: Optional[str]
    stock_count: int
    created_at: str
    notes: str = ""
    
    def __post_init__(self):
        """初始化後處理"""
        if not self.created_at:
            self.created_at = datetime.now().isoformat()


class RecommendationRepository:
    """推薦結果儲存庫"""
    
    def __init__(self, config):
        """
        初始化儲存庫
        
        Args:
            config: TWStockConfig 實例
        """
        self.config = config
        # 儲存在 output_root/recommendation/runs/
        self.runs_dir = config.resolve_output_path('recommendation/runs')
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        
        # SQLite 資料庫
        self.db_path = self.runs_dir / "recommendation_runs.db"
        self._init_database()
    
    def _init_database(self):
        """初始化資料庫結構"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # 建立 runs 表（儲存基本資訊）
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS runs (
                result_id TEXT PRIMARY KEY,
                result_name TEXT NOT NULL,
                regime TEXT,
                stock_count INTEGER,
                config TEXT,  -- JSON
                notes TEXT,
                created_at TEXT,
                data_path TEXT  -- 檔案路徑（JSON）
            )
        """)
        
        # 建立索引
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_created_at ON runs(created_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_regime ON runs(regime)")
        
        conn.commit()
        conn.close()
    
    def save_result(
        self,
        result: RecommendationResultDTO,
        result_name: Optional[str] = None
    ) -> str:
        """
        儲存推薦結果
        
        Args:
            result: RecommendationResultDTO 實例
            result_name: 結果名稱（如果為 None 則自動生成）
        
        Returns:
            結果ID
        """
        if not result.result_id:
            result.result_id = f"rec_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        if not result.created_at:
            result.created_at = datetime.now().isoformat()
        
        if not result_name:
            result_name = f"推薦結果_{datetime.now().strftime('%Y%m%d_%H%M')}"
        
        result.result_name = result_name
        
        # 儲存完整數據到 JSON 文件
        data_file = self.runs_dir / f"{result.result_id}.json"
        data = result.to_dict()
        # 清理數據，確保所有類型都是 JSON 可序列化的
        data = _make_json_serializable(data)
        data_file.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding='utf-8'
        )
        
        # 儲存元數據到 SQLite
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # 清理 config，確保 JSON 可序列化
        config_cleaned = _make_json_serializable(result.config)
        cursor.execute("""
            INSERT OR REPLACE INTO runs 
            (result_id, result_name, regime, stock_count, config, notes, created_at, data_path)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            result.result_id,
            result.result_name,
            result.regime,
            len(result.recommendations),
            json.dumps(config_cleaned, ensure_ascii=False),
            result.notes,
            result.created_at,
            str(data_file)
        ))
        
        conn.commit()
        conn.close()
        
        return result.result_id
    
    def load_result(self, result_id: str) -> Optional[RecommendationResultDTO]:
        """
        載入推薦結果
        
        Args:
            result_id: 結果ID
        
        Returns:
            RecommendationResultDTO 或 None
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("SELECT data_path FROM runs WHERE result_id = ?", (result_id,))
        row = cursor.fetchone()
        conn.close()
        
        if not row:
            return None
        
        data_file = Path(row[0])
        if not data_file.exists():
            return None
        
        try:
            data = json.loads(data_file.read_text(encoding='utf-8'))
            return RecommendationResultDTO.from_dict(data)
        except Exception as e:
            print(f"[RecommendationRepository] 載入失敗 {result_id}: {e}")
            return None
    
    def list_results(self) -> List[Dict[str, Any]]:
        """
        列出所有推薦結果
        
        Returns:
            結果列表
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT result_id, result_name, regime, stock_count, created_at, notes
            FROM runs
            ORDER BY created_at DESC
        """)
        
        results = []
        for row in cursor.fetchall():
            results.append({
                'result_id': row[0],
                'result_name': row[1],
                'regime': row[2],
                'stock_count': row[3],
                'created_at': row[4],
                'notes': row[5] or ''
            })
        
        conn.close()
        return results
    
    def delete_result(self, result_id: str) -> bool:
        """
        刪除推薦結果
        
        Args:
            result_id: 結果ID
        
        Returns:
            是否成功刪除
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # 獲取檔案路徑
        cursor.execute("SELECT data_path FROM runs WHERE result_id = ?", (result_id,))
        row = cursor.fetchone()
        
        if row:
            data_file = Path(row[0])
            if data_file.exists():
                try:
                    data_file.unlink()
                except:
                    pass
        
        # 從資料庫刪除
        cursor.execute("DELETE FROM runs WHERE result_id = ?", (result_id,))
        deleted = cursor.rowcount > 0
        
        conn.commit()
        conn.close()
        
        return deleted

