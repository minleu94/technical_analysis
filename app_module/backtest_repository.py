"""
回測結果儲存庫 (Backtest Run Repository)
使用 SQLite 儲存回測結果，支援查詢、比較、追溯
"""

import sqlite3
import json
import pandas as pd
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime
from dataclasses import dataclass, asdict
from app_module.dtos import BacktestReportDTO


@dataclass
class BacktestRun:
    """回測執行記錄"""
    run_id: str
    run_name: str
    stock_code: str
    start_date: str
    end_date: str
    strategy_id: str
    strategy_params: Dict[str, Any]
    capital: float
    fee_bps: float
    slippage_bps: float
    stop_loss_pct: Optional[float]
    take_profit_pct: Optional[float]
    # 績效指標
    total_return: float
    annual_return: float
    sharpe_ratio: float
    max_drawdown: float
    win_rate: float
    total_trades: int
    expectancy: float
    profit_factor: float
    # 額外資訊
    notes: str = ""
    tags: List[str] = None
    created_at: str = None
    equity_curve_path: Optional[str] = None
    trade_list_path: Optional[str] = None
    promoted_version_id: Optional[str] = None  # 已升級的策略版本 ID
    
    def __post_init__(self):
        if self.tags is None:
            self.tags = []
        if self.created_at is None:
            self.created_at = datetime.now().isoformat()


class BacktestRunRepository:
    """回測結果儲存庫"""
    
    def __init__(self, config):
        """
        初始化儲存庫
        
        Args:
            config: TWStockConfig 實例
        """
        self.config = config
        # 儲存在 data_root/backtest/runs/
        self.runs_dir = config.resolve_output_path('backtest/runs')
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        
        # SQLite 資料庫
        self.db_path = self.runs_dir / "backtest_runs.db"
        self._init_database()
    
    def _init_database(self):
        """初始化資料庫結構"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # 建立 runs 表（儲存基本資訊和績效摘要）
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                run_name TEXT NOT NULL,
                stock_code TEXT,
                start_date TEXT,
                end_date TEXT,
                strategy_id TEXT,
                strategy_params TEXT,  -- JSON
                capital REAL,
                fee_bps REAL,
                slippage_bps REAL,
                stop_loss_pct REAL,
                take_profit_pct REAL,
                total_return REAL,
                annual_return REAL,
                sharpe_ratio REAL,
                max_drawdown REAL,
                win_rate REAL,
                total_trades INTEGER,
                expectancy REAL,
                profit_factor REAL,
                notes TEXT,
                tags TEXT,  -- JSON array
                created_at TEXT,
                equity_curve_path TEXT,  -- 檔案路徑
                trade_list_path TEXT,    -- 檔案路徑
                promoted_version_id TEXT  -- 已升級的策略版本 ID（可選）
            )
        """)
        
        # 如果 promoted_version_id 欄位不存在，則添加（向後兼容）
        try:
            cursor.execute("ALTER TABLE runs ADD COLUMN promoted_version_id TEXT")
        except sqlite3.OperationalError:
            # 欄位已存在，忽略錯誤
            pass
        
        # 建立索引
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_created_at ON runs(created_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_strategy_id ON runs(strategy_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_stock_code ON runs(stock_code)")
        
        conn.commit()
        conn.close()
    
    def save_run(
        self,
        run_name: str,
        stock_code: str,
        start_date: str,
        end_date: str,
        strategy_id: str,
        strategy_params: Dict[str, Any],
        capital: float,
        fee_bps: float,
        slippage_bps: float,
        stop_loss_pct: Optional[float],
        take_profit_pct: Optional[float],
        report: BacktestReportDTO,
        notes: str = "",
        tags: Optional[List[str]] = None,
        run_id: Optional[str] = None
    ) -> str:
        """
        儲存回測結果
        
        Args:
            run_name: 執行名稱
            stock_code: 股票代號
            start_date: 開始日期
            end_date: 結束日期
            strategy_id: 策略ID
            strategy_params: 策略參數
            capital: 初始資金
            fee_bps: 手續費
            slippage_bps: 滑價
            stop_loss_pct: 停損百分比
            take_profit_pct: 停利百分比
            report: 回測報告
            notes: 備註
            tags: 標籤
            run_id: 執行ID（如果提供則更新，否則新建）
        
        Returns:
            執行ID
        """
        if run_id is None:
            run_id = f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        # 儲存 equity curve 和 trade list 為檔案
        equity_curve_path = self.runs_dir / f"{run_id}_equity_curve.parquet"
        trade_list_path = self.runs_dir / f"{run_id}_trades.parquet"
        
        # 嘗試使用 parquet，如果失敗則使用 CSV
        if 'equity_curve' in report.details and isinstance(report.details['equity_curve'], pd.DataFrame):
            try:
                # 嘗試導入 pyarrow 或 fastparquet
                try:
                    import pyarrow
                    engine = 'pyarrow'
                except ImportError:
                    try:
                        import fastparquet
                        engine = 'fastparquet'
                    except ImportError:
                        raise ImportError("需要安裝 pyarrow 或 fastparquet: pip install pyarrow")
                
                report.details['equity_curve'].to_parquet(equity_curve_path, engine=engine)
            except Exception as e:
                # 如果 parquet 失敗，使用 CSV
                print(f"[BacktestRepository] 警告: 無法使用 parquet 保存 equity_curve，改用 CSV: {e}")
                equity_curve_path = self.runs_dir / f"{run_id}_equity_curve.csv"
                report.details['equity_curve'].to_csv(equity_curve_path, index=True)
        
        if 'trade_list' in report.details and isinstance(report.details['trade_list'], pd.DataFrame):
            try:
                # 嘗試導入 pyarrow 或 fastparquet
                try:
                    import pyarrow
                    engine = 'pyarrow'
                except ImportError:
                    try:
                        import fastparquet
                        engine = 'fastparquet'
                    except ImportError:
                        raise ImportError("需要安裝 pyarrow 或 fastparquet: pip install pyarrow")
                
                report.details['trade_list'].to_parquet(trade_list_path, engine=engine)
            except Exception as e:
                # 如果 parquet 失敗，使用 CSV
                print(f"[BacktestRepository] 警告: 無法使用 parquet 保存 trade_list，改用 CSV: {e}")
                trade_list_path = self.runs_dir / f"{run_id}_trades.csv"
                report.details['trade_list'].to_csv(trade_list_path, index=False)
        
        # 儲存到資料庫
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT OR REPLACE INTO runs (
                run_id, run_name, stock_code, start_date, end_date,
                strategy_id, strategy_params, capital, fee_bps, slippage_bps,
                stop_loss_pct, take_profit_pct,
                total_return, annual_return, sharpe_ratio, max_drawdown,
                win_rate, total_trades, expectancy, profit_factor,
                notes, tags, created_at, equity_curve_path, trade_list_path, promoted_version_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            run_id, run_name, stock_code, start_date, end_date,
            strategy_id, json.dumps(strategy_params, ensure_ascii=False),
            capital, fee_bps, slippage_bps, stop_loss_pct, take_profit_pct,
            report.total_return, report.annual_return, report.sharpe_ratio,
            report.max_drawdown, report.win_rate, report.total_trades,
            report.expectancy, report.details.get('profit_factor', 0.0),
            notes, json.dumps(tags or [], ensure_ascii=False),
            datetime.now().isoformat(),
            str(equity_curve_path), str(trade_list_path), None
        ))
        
        conn.commit()
        conn.close()
        
        return run_id
    
    def list_runs(
        self,
        strategy_id: Optional[str] = None,
        stock_code: Optional[str] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        列出回測結果
        
        Args:
            strategy_id: 策略ID篩選（可選）
            stock_code: 股票代號篩選（可選）
            limit: 限制數量
        
        Returns:
            結果列表
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        query = "SELECT * FROM runs WHERE 1=1"
        params = []
        
        if strategy_id:
            query += " AND strategy_id = ?"
            params.append(strategy_id)
        
        if stock_code:
            query += " AND stock_code = ?"
            params.append(stock_code)
        
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        
        # 取得欄位名稱
        columns = [desc[0] for desc in cursor.description]
        
        conn.close()
        
        # 轉換為字典列表
        runs = []
        for row in rows:
            run_dict = dict(zip(columns, row))
            # 解析JSON欄位
            if run_dict.get('strategy_params'):
                run_dict['strategy_params'] = json.loads(run_dict['strategy_params'])
            if run_dict.get('tags'):
                run_dict['tags'] = json.loads(run_dict['tags'])
            runs.append(run_dict)
        
        return runs
    
    def load_run(self, run_id: str) -> Optional[BacktestRun]:
        """
        載入回測結果
        
        Args:
            run_id: 執行ID
        
        Returns:
            BacktestRun 對象或 None
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,))
        row = cursor.fetchone()
        
        if row is None:
            conn.close()
            return None
        
        # 取得欄位名稱
        columns = [desc[0] for desc in cursor.description]
        run_dict = dict(zip(columns, row))
        
        conn.close()
        
        # 解析JSON欄位
        if run_dict.get('strategy_params'):
            if isinstance(run_dict['strategy_params'], str):
                run_dict['strategy_params'] = json.loads(run_dict['strategy_params'])
        if run_dict.get('tags'):
            if isinstance(run_dict['tags'], str):
                run_dict['tags'] = json.loads(run_dict['tags'])
        
        # 確保所有必需欄位都有值
        if 'equity_curve_path' not in run_dict:
            run_dict['equity_curve_path'] = None
        if 'trade_list_path' not in run_dict:
            run_dict['trade_list_path'] = None
        if 'promoted_version_id' not in run_dict:
            run_dict['promoted_version_id'] = None
        
        return BacktestRun(**run_dict)
    
    def load_run_data(self, run_id: str) -> Optional[Dict[str, Any]]:
        """
        載入回測的完整資料（包含 equity curve 和 trade list）
        
        Args:
            run_id: 執行ID
        
        Returns:
            包含完整資料的字典或 None
        """
        run = self.load_run(run_id)
        if run is None:
            return None
        
        result = asdict(run)
        
        # 載入 equity curve
        if run.equity_curve_path and Path(run.equity_curve_path).exists():
            try:
                if str(run.equity_curve_path).endswith('.parquet'):
                    result['equity_curve'] = pd.read_parquet(run.equity_curve_path)
                else:
                    result['equity_curve'] = pd.read_csv(run.equity_curve_path, index_col=0, parse_dates=True)
            except Exception as e:
                print(f"[BacktestRepository] 警告: 載入 equity_curve 失敗: {e}")
                result['equity_curve'] = pd.DataFrame()
        
        # 載入 trade list
        if run.trade_list_path and Path(run.trade_list_path).exists():
            try:
                if str(run.trade_list_path).endswith('.parquet'):
                    result['trade_list'] = pd.read_parquet(run.trade_list_path)
                else:
                    # CSV 格式：不使用 index_col，因為 trade_list 沒有索引列
                    result['trade_list'] = pd.read_csv(run.trade_list_path)
            except Exception as e:
                print(f"[BacktestRepository] 警告: 載入 trade_list 失敗: {e}")
                result['trade_list'] = pd.DataFrame()
        
        return result
    
    def delete_run(self, run_id: str) -> bool:
        """
        刪除回測結果
        
        Args:
            run_id: 執行ID
        
        Returns:
            是否成功刪除
        """
        # 先載入以取得檔案路徑
        run = self.load_run(run_id)
        if run is None:
            return False
        
        # 刪除檔案
        if run.equity_curve_path and Path(run.equity_curve_path).exists():
            Path(run.equity_curve_path).unlink()
        if run.trade_list_path and Path(run.trade_list_path).exists():
            Path(run.trade_list_path).unlink()
        
        # 刪除資料庫記錄
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM runs WHERE run_id = ?", (run_id,))
        conn.commit()
        conn.close()
        
        return True
    
    def get_run(self, run_id: str) -> Optional[BacktestRun]:
        """
        獲取回測結果（load_run 的別名，用於與 PromotionService 兼容）
        
        Args:
            run_id: 執行ID
        
        Returns:
            BacktestRun 對象或 None
        """
        return self.load_run(run_id)
    
    def mark_as_promoted(self, run_id: str, version_id: str) -> bool:
        """
        標記回測結果為已升級
        
        Args:
            run_id: 回測執行 ID
            version_id: 策略版本 ID
        
        Returns:
            是否成功標記
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute(
            "UPDATE runs SET promoted_version_id = ? WHERE run_id = ?",
            (version_id, run_id)
        )
        
        conn.commit()
        affected_rows = cursor.rowcount
        conn.close()
        
        if affected_rows > 0:
            print(f"[BacktestRepository] 標記回測結果為已升級: run_id={run_id}, version_id={version_id}")
            return True
        else:
            print(f"[BacktestRepository] 警告: 找不到回測結果: run_id={run_id}")
            return False

