"""
推薦組合回測執行紀錄儲存庫 (Recommendation Portfolio Run Repository)
管理推薦組合回測結果的儲存、載入、刪除與比較
"""

import json
import sqlite3
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime
import numpy as np

from app_module.recommendation_portfolio_dtos import RecommendationPortfolioBacktestResultDTO


def _make_json_serializable(obj: Any) -> Any:
    """
    將對象轉換為 JSON 可序列化的格式。
    
    處理 numpy 類型、容器類型與基本類型。
    """
    if isinstance(obj, np.bool_):
        return bool(obj)
    elif isinstance(obj, np.integer):
        return int(obj)
    elif isinstance(obj, np.floating):
        return float(obj)
    elif isinstance(obj, np.ndarray):
        return obj.tolist()
    elif isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    elif isinstance(obj, dict):
        return {key: _make_json_serializable(value) for key, value in obj.items()}
    elif isinstance(obj, (list, tuple)):
        return [_make_json_serializable(item) for item in obj]
    else:
        try:
            return str(obj)
        except:
            return None


class RecommendationPortfolioRunRepository:
    """推薦組合回測結果儲存庫"""
    
    def __init__(self, config):
        """
        初始化儲存庫。
        
        Args:
            config: TWStockConfig 實例
        """
        self.config = config
        # 儲存在 output_root/recommendation_portfolio/runs/
        self.runs_dir = config.resolve_output_path('recommendation_portfolio/runs')
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        
        # SQLite 資料庫
        self.db_path = self.runs_dir / "recommendation_portfolio_runs.db"
        self._init_database()
        
    def _init_database(self):
        """初始化資料庫結構"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                run_name TEXT NOT NULL,
                profile_id TEXT,
                start_date TEXT,
                end_date TEXT,
                initial_capital REAL,
                rebalance_frequency TEXT,
                top_n INTEGER,
                allocation_method TEXT,
                holding_days INTEGER,
                stop_loss_pct REAL,
                take_profit_pct REAL,
                total_return REAL,
                max_drawdown REAL,
                sharpe_ratio REAL,
                sortino_ratio REAL,
                total_trades INTEGER,
                notes TEXT,
                created_at TEXT,
                data_path TEXT  -- JSON 檔案路徑
            )
        """)
        
        # 建立索引
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_created_at ON runs(created_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_profile_id ON runs(profile_id)")
        
        conn.commit()
        conn.close()
        
    def save_run(
        self,
        run_name: str,
        profile_id: str,
        start_date: str,
        end_date: str,
        initial_capital: float,
        rebalance_frequency: str,
        top_n: int,
        allocation_method: str,
        holding_days: int,
        stop_loss_pct: Optional[float],
        take_profit_pct: Optional[float],
        result: RecommendationPortfolioBacktestResultDTO,
        notes: str = "",
        run_id: Optional[str] = None
    ) -> str:
        """
        儲存推薦組合回測結果。
        
        Args:
            run_name: 回測名稱
            profile_id: 推薦配置 Profile ID
            start_date: 開始日期
            end_date: 結束日期
            initial_capital: 初始資金
            rebalance_frequency: 重播頻率
            top_n: 每期檔數
            allocation_method: 權重配置方式
            holding_days: 持有天數
            stop_loss_pct: 停損百分比
            take_profit_pct: 停利百分比
            result: RecommendationPortfolioBacktestResultDTO 實例
            notes: 備註
            run_id: 指定 ID（如為 None 則自動生成）
            
        Returns:
            儲存的 run_id
        """
        if not run_id:
            run_id = f"port_run_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
            
        created_at = datetime.now().isoformat()
        
        # 儲存完整結果到 JSON
        data_file = self.runs_dir / f"{run_id}.json"
        
        # 把 ResultDTO 與回測配置參數包裝在一起
        config_data = {
            "profile_id": profile_id,
            "start_date": start_date,
            "end_date": end_date,
            "initial_capital": initial_capital,
            "rebalance_frequency": rebalance_frequency,
            "top_n": top_n,
            "allocation_method": allocation_method,
            "holding_days": holding_days,
            "stop_loss_pct": stop_loss_pct,
            "take_profit_pct": take_profit_pct,
        }
        
        full_data = {
            "run_id": run_id,
            "run_name": run_name,
            "notes": notes,
            "created_at": created_at,
            "config": config_data,
            "result": result.to_dict()
        }
        
        # 轉成 JSON 可序列化結構
        full_data_cleaned = _make_json_serializable(full_data)
        data_file.write_text(
            json.dumps(full_data_cleaned, ensure_ascii=False, indent=2),
            encoding='utf-8'
        )
        
        # 儲存 metadata 到 SQLite
        summary = result.summary
        total_return = summary.get("total_return", 0.0)
        max_drawdown = summary.get("max_drawdown", 0.0)
        sharpe_ratio = summary.get("sharpe_ratio", 0.0)
        sortino_ratio = summary.get("sortino_ratio", 0.0)
        total_trades = summary.get("total_trades", 0)
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT OR REPLACE INTO runs (
                run_id, run_name, profile_id, start_date, end_date,
                initial_capital, rebalance_frequency, top_n, allocation_method,
                holding_days, stop_loss_pct, take_profit_pct,
                total_return, max_drawdown, sharpe_ratio, sortino_ratio, total_trades,
                notes, created_at, data_path
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            run_id, run_name, profile_id, start_date, end_date,
            initial_capital, rebalance_frequency, top_n, allocation_method,
            holding_days, stop_loss_pct, take_profit_pct,
            total_return, max_drawdown, sharpe_ratio, sortino_ratio, total_trades,
            notes, created_at, str(data_file)
        ))
        
        conn.commit()
        conn.close()
        
        return run_id
        
    def list_runs(self) -> List[Dict[str, Any]]:
        """
        列出所有推薦組合回測紀錄摘要。
        
        Returns:
            回測紀錄的 dictionary 列表。
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT run_id, run_name, profile_id, start_date, end_date,
                   total_return, max_drawdown, sharpe_ratio, sortino_ratio, total_trades,
                   created_at, notes
            FROM runs
            ORDER BY created_at DESC
        """)
        
        results = []
        for row in cursor.fetchall():
            results.append({
                'run_id': row[0],
                'run_name': row[1],
                'profile_id': row[2],
                'start_date': row[3],
                'end_date': row[4],
                'total_return': row[5],
                'max_drawdown': row[6],
                'sharpe_ratio': row[7],
                'sortino_ratio': row[8],
                'total_trades': row[9],
                'created_at': row[10],
                'notes': row[11] or ''
            })
            
        conn.close()
        return results
        
    def load_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        """
        載入推薦組合回測的完整資料與 DTO。
        
        Args:
            run_id: 回測 ID
            
        Returns:
            包含 config, metadata, 與還原的 RecommendationPortfolioBacktestResultDTO 實例的 dict
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("SELECT data_path FROM runs WHERE run_id = ?", (run_id,))
        row = cursor.fetchone()
        conn.close()
        
        if not row:
            return None
            
        data_file = Path(row[0])
        if not data_file.exists():
            return None
            
        try:
            full_data = json.loads(data_file.read_text(encoding='utf-8'))
            
            # 從 JSON dictionary 還原 RecommendationPortfolioBacktestResultDTO
            result_dict = full_data.get("result", {})
            dto = RecommendationPortfolioBacktestResultDTO.from_dict(result_dict)
            
            full_data["result_dto"] = dto
            full_data["data_path"] = str(data_file)
            return full_data
        except Exception as e:
            print(f"[RecommendationPortfolioRunRepository] 載入失敗 {run_id}: {e}")
            return None
            
    def delete_run(self, run_id: str) -> bool:
        """
        刪除推薦組合回測紀錄與對應 JSON。
        
        Args:
            run_id: 回測 ID
            
        Returns:
            是否刪除成功
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # 獲取檔案路徑
        cursor.execute("SELECT data_path FROM runs WHERE run_id = ?", (run_id,))
        row = cursor.fetchone()
        
        if row:
            data_file = Path(row[0])
            if data_file.exists():
                try:
                    data_file.unlink()
                except:
                    pass
                    
        # 從資料庫刪除
        cursor.execute("DELETE FROM runs WHERE run_id = ?", (run_id,))
        deleted = cursor.rowcount > 0
        
        conn.commit()
        conn.close()
        
        return deleted
