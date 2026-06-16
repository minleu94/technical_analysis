import sqlite3
import logging
from pathlib import Path
from contextlib import contextmanager
from typing import Generator, List, Dict, Any, Union
import pandas as pd
from .config import TWStockConfig

class DBManager:
    """台股 SQLite 資料庫管理模組，負責連線、建表、動態 schema 升級與 Transaction 管理"""
    
    def __init__(self, config: TWStockConfig):
        self.config = config
        self._setup_logging()
        self.db_path = self.config.db_file
        
        # 確保資料庫目錄存在（config 應該已建立，但這裡做防禦性確保）
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        # 初始化資料庫 Table Schema
        self.init_database()
        
    def _setup_logging(self):
        """設置日誌"""
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.INFO)
        self.logger.propagate = False
        
        if not self.logger.handlers:
            file_handler = logging.FileHandler(
                self.config.log_dir / "db_manager.log",
                encoding='utf-8'
            )
            file_handler.setLevel(logging.INFO)
            
            console_handler = logging.StreamHandler()
            console_handler.setLevel(logging.WARNING)
            
            formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            file_handler.setFormatter(formatter)
            console_handler.setFormatter(formatter)
            
            self.logger.addHandler(file_handler)
            self.logger.addHandler(console_handler)

    @contextmanager
    def connect(self) -> Generator[sqlite3.Connection, None, None]:
        """資料庫連線上下文管理器，支援自動 Commit/Rollback 與 Transaction 安全"""
        conn = sqlite3.connect(self.db_path)
        # 啟用 WAL 模式 (Write-Ahead Logging) 以極大提升讀寫併發效能與穩定性
        try:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")
        except sqlite3.Error as e:
            self.logger.warning(f"設定 PRAGMA 失敗: {str(e)}")
            
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            self.logger.error(f"資料庫事務執行失敗，已回滾: {str(e)}")
            raise e
        finally:
            conn.close()

    def init_database(self):
        """初始化資料表結構與索引"""
        self.logger.info("開始初始化 SQLite 資料庫...")
        with self.connect() as conn:
            # 1. 每日個股價量表 (daily_prices)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS daily_prices (
                    日期 TEXT,
                    證券代號 TEXT,
                    證券名稱 TEXT,
                    成交股數 INTEGER,
                    成交筆數 INTEGER,
                    成交金額 INTEGER,
                    開盤價 REAL,
                    最高價 REAL,
                    最低價 REAL,
                    收盤價 REAL,
                    涨跌 TEXT,
                    漲跌價差 REAL,
                    最後揭示買價 REAL,
                    最後揭示買量 INTEGER,
                    最後揭示賣價 REAL,
                    最後揭示賣量 INTEGER,
                    本益比 REAL,
                    PRIMARY KEY (證券代號, 日期)
                );
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_daily_prices_date ON daily_prices (日期);")
            
            # 2. 技術指標表 (technical_indicators) - 預設欄位寬表，並會動態升級
            conn.execute("""
                CREATE TABLE IF NOT EXISTS technical_indicators (
                    日期 TEXT,
                    證券代號 TEXT,
                    PRIMARY KEY (證券代號, 日期)
                );
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tech_indicators_date ON technical_indicators (日期);")
            
            # 3. 大盤指數表 (market_indices)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS market_indices (
                    日期 TEXT,
                    指數名稱 TEXT,
                    收盤指數 REAL,
                    漲跌 TEXT,
                    漲跌點數 REAL,
                    漲跌百分比 REAL,
                    PRIMARY KEY (指數名稱, 日期)
                );
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_market_indices_date ON market_indices (日期);")
            
            # 4. 產業指數表 (industry_indices)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS industry_indices (
                    日期 TEXT,
                    指數名稱 TEXT,
                    收盤指數 REAL,
                    漲跌 TEXT,
                    漲跌點數 REAL,
                    漲跌百分比 REAL,
                    PRIMARY KEY (指數名稱, 日期)
                );
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_industry_indices_date ON industry_indices (日期);")

            # 5. 券商分點資料表 (broker_flows)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS broker_flows (
                    日期 TEXT,
                    分點名稱 TEXT,
                    證券代號 TEXT,
                    證券名稱 TEXT,
                    買進股數 INTEGER,
                    賣出股數 INTEGER,
                    買賣超股數 INTEGER,
                    買進金額千元 INTEGER,
                    賣出金額千元 INTEGER,
                    買賣超金額千元 INTEGER,
                    trade_type TEXT,
                    lots_observed INTEGER,
                    amount_observed INTEGER,
                    lots_rank INTEGER,
                    amount_rank INTEGER,
                    PRIMARY KEY (分點名稱, 證券代號, 日期)
                );
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_broker_flows_date ON broker_flows (日期);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_broker_flows_stock ON broker_flows (證券代號);")
            
        self.logger.info("SQLite 資料庫初始化成功！")

    def get_table_columns(self, table_name: str) -> List[str]:
        """獲取指定 Table 目前擁有的所有欄位名稱"""
        with self.connect() as conn:
            cursor = conn.execute(f"PRAGMA table_info({table_name});")
            columns = [row['name'] for row in cursor.fetchall()]
            return columns

    def ensure_columns(self, table_name: str, df_columns: List[str]):
        """動態確保資料表結構 (寬表) 與 DataFrame 欄位對齊。若有缺失欄位，自動執行 ALTER TABLE 新增"""
        existing_cols = set(self.get_table_columns(table_name))
        cols_to_add = [col for col in df_columns if col not in existing_cols]
        
        if not cols_to_add:
            return
            
        self.logger.info(f"發現資料表 {table_name} 缺少欄位 {cols_to_add}，開始動態升級 Schema...")
        
        # 進行動態欄位升級
        # SQLite 僅支援一次 ALTER TABLE 增加一欄，需循環處理
        with self.connect() as conn:
            for col in cols_to_add:
                # 處理欄位名稱有括號或特殊字元，使用雙引號包裹以保安全
                # 預設新增的技術指標皆為 REAL 類型，非技術指標做類型判斷
                col_type = "REAL"
                if col in ['日期', '證券代號', '證券名稱', '漲跌', 'trade_type']:
                    col_type = "TEXT"
                elif col in [
                    '成交股數', '成交筆數', '成交金額',
                    '最後揭示買量', '最後揭示賣量',
                    '買進股數', '賣出股數', '買賣超股數',
                    '買進金額千元', '賣出金額千元', '買賣超金額千元',
                    'lots_observed', 'amount_observed', 'lots_rank', 'amount_rank',
                ]:
                    col_type = "INTEGER"
                
                query = f'ALTER TABLE {table_name} ADD COLUMN "{col}" {col_type};'
                try:
                    conn.execute(query)
                    self.logger.info(f"成功新增欄位: {table_name}.{col} ({col_type})")
                except sqlite3.Error as e:
                    self.logger.error(f"新增欄位 {table_name}.{col} 失敗: {str(e)}")
                    raise e

    def write_dataframe(self, table_name: str, df: pd.DataFrame, if_exists: str = 'append') -> bool:
        """高效寫入 DataFrame 資料到指定的資料庫表中，並自動處理 Schema 對齊與 Transaction 安全"""
        if df is None or df.empty:
            self.logger.warning(f"欲寫入 {table_name} 的 DataFrame 為空，略過寫入")
            return False
            
        try:
            # 確保並升級欄位
            self.ensure_columns(table_name, list(df.columns))
            
            # 使用 pd.DataFrame.to_sql 寫入
            # 注意：為確保 Transaction 完整性與 WAL 模式順暢，我們透過 connect 上下文獲取 conn
            with self.connect() as conn:
                df.to_sql(
                    name=table_name,
                    con=conn,
                    if_exists=if_exists,
                    index=False
                )
            self.logger.info(f"成功寫入 {len(df)} 筆資料至 Table {table_name}")
            return True
        except Exception as e:
            self.logger.error(f"寫入 DataFrame 至 Table {table_name} 失敗: {str(e)}")
            return False

    def execute_query(self, sql: str, params: tuple = ()) -> pd.DataFrame:
        """執行 SELECT 查詢並直接返回 Pandas DataFrame"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                # SELECT 唯讀查詢不需 WAL 上下文事務，直接讀取
                df = pd.read_sql_query(sql, conn, params=params)
                return df
        except Exception as e:
            self.logger.error(f"執行查詢失敗: {sql}, 錯誤: {str(e)}")
            raise e
