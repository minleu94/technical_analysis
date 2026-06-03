"""
SQLite 資料庫檢視服務 (SQLite Inspector Service)
提供 SQLite 資料表的 metadata 查詢、結構描述、以及受控的篩選查詢功能。
"""

import re
import logging
from typing import Dict, List, Any, Optional
import pandas as pd
from data_module.db_manager import DBManager


class SqliteInspectorService:
    """SQLite 資料表檢視與查詢服務"""

    # 白名單限制的五大核心表
    ALLOWED_TABLES = {'daily_prices', 'technical_indicators', 'market_indices', 'industry_indices', 'broker_flows'}

    def __init__(self, config):
        """初始化檢視服務
        
        Args:
            config: TWStockConfig 實例
        """
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.db_manager = DBManager(config)

    def is_enabled(self) -> bool:
        """檢查 SQLite 是否啟用"""
        return getattr(self.config, 'use_sqlite', False)

    def get_tables(self) -> List[str]:
        """獲取資料庫中所有的使用者資料表列表 (過濾並僅限白名單中且實際存在的表)
        
        Returns:
            List[str]: 資料表名稱列表
        """
        if not self.is_enabled():
            return []

        try:
            sql = "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';"
            df = self.db_manager.execute_query(sql)
            if not df.empty:
                existing = df['name'].tolist()
                return [t for t in existing if t in self.ALLOWED_TABLES]
            return []
        except Exception as e:
            self.logger.error(f"[SqliteInspectorService] 獲取資料表列表失敗: {e}")
            return []

    def get_table_schema(self, table_name: str) -> pd.DataFrame:
        """獲取指定資料表的欄位定義 (Schema)
        
        Args:
            table_name: 資料表名稱
            
        Returns:
            pd.DataFrame: 欄位詳細資訊，包含 cid, name, type, notnull, dflt_value, pk
        """
        if not self.is_enabled():
            return pd.DataFrame()

        if table_name not in self.ALLOWED_TABLES:
            raise ValueError(f"拒絕訪問非白名單資料表: {table_name}")

        # 防禦：防止 SQL Injection 在 PRAGMA 中，限制 table_name 必須為合法的標識符
        if not re.match(r'^[a-zA-Z0-9_]+$', table_name):
            raise ValueError(f"不合法的資料表名稱: {table_name}")

        try:
            # PRAGMA 查詢需要獨立連線
            with self.db_manager.connect() as conn:
                cursor = conn.execute(f"PRAGMA table_info({table_name});")
                rows = cursor.fetchall()
                if not rows:
                    return pd.DataFrame()
                
                # 轉成 DataFrame
                cols = ['cid', 'name', 'type', 'notnull', 'dflt_value', 'pk']
                data = []
                for row in rows:
                    data.append({c: row[c] for c in cols if c in row.keys()})
                
                df = pd.DataFrame(data)
                # 將 pk 欄位轉為易讀的布林或文字
                if 'pk' in df.columns:
                    df['pk'] = df['pk'].map(lambda x: '✓ 主鍵' if x else '')
                if 'notnull' in df.columns:
                    df['notnull'] = df['notnull'].map(lambda x: '✓' if x else '')
                
                # 重命名欄位以便於 UI 呈現
                rename_map = {
                    'cid': '序號',
                    'name': '欄位名稱',
                    'type': '資料型態',
                    'notnull': '必填 (Not Null)',
                    'dflt_value': '預設值',
                    'pk': '主鍵'
                }
                df = df.rename(columns=rename_map)
                return df
        except Exception as e:
            self.logger.error(f"[SqliteInspectorService] 獲取資料表 {table_name} Schema 失敗: {e}")
            return pd.DataFrame()

    def get_table_info(self, table_name: str) -> Dict[str, Any]:
        """獲取指定資料表的基本狀態與資訊 (總筆數、時間跨度等)
        
        Args:
            table_name: 資料表名稱
            
        Returns:
            Dict: 包含總記錄數與日期範圍等 metadata
        """
        result = {
            'table_name': table_name,
            'total_records': 0,
            'latest_date': None,
            'earliest_date': None,
            'columns_count': 0,
            'success': False,
            'message': ''
        }

        if not self.is_enabled():
            result['message'] = 'SQLite 未啟用'
            return result

        if table_name not in self.ALLOWED_TABLES:
            result['message'] = f'拒絕訪問非白名單資料表: {table_name}'
            raise ValueError(f"拒絕訪問非白名單資料表: {table_name}")

        if not re.match(r'^[a-zA-Z0-9_]+$', table_name):
            result['message'] = f'不合法的資料表名稱: {table_name}'
            return result

        try:
            # 1. 取得欄位數量
            schema_df = self.get_table_schema(table_name)
            result['columns_count'] = len(schema_df)

            # 2. 取得總筆數
            cnt_df = self.db_manager.execute_query(f"SELECT COUNT(*) as cnt FROM {table_name};")
            if not cnt_df.empty:
                result['total_records'] = int(cnt_df.iloc[0]['cnt'])

            # 3. 若有日期欄位，取得日期範圍
            if '欄位名稱' in schema_df.columns and '日期' in schema_df['欄位名稱'].values:
                date_df = self.db_manager.execute_query(
                    f"SELECT MIN(日期) as min_date, MAX(日期) as max_date FROM {table_name};"
                )
                if not date_df.empty:
                    min_d = date_df.iloc[0]['min_date']
                    max_d = date_df.iloc[0]['max_date']
                    result['earliest_date'] = self._format_date(min_d)
                    result['latest_date'] = self._format_date(max_d)

            result['success'] = True
            result['message'] = '獲取資訊成功'
            return result
        except Exception as e:
            error_msg = f"獲取表 {table_name} 資訊失敗: {e}"
            self.logger.error(f"[SqliteInspectorService] {error_msg}")
            result['message'] = error_msg
            return result

    def query_table_data(
        self,
        table_name: str,
        stock_code: Optional[str] = None,
        stock_name: Optional[str] = None,
        date_str: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        broker_branch: Optional[str] = None,
        limit: int = 100
    ) -> pd.DataFrame:
        """受控的表格資料查詢
        
        Args:
            table_name: 資料表名稱 (必須在 ALLOWED_TABLES 白名單中)
            stock_code: 證券代號 (選填)
            stock_name: 證券名稱 (選填)
            date_str: 日期字串，格式為 YYYY-MM-DD 或 YYYYMMDD (選填)
            start_date: 開始日期字串 (選填)
            end_date: 結束日期字串 (選填)
            broker_branch: 分點名稱 (選填)
            limit: 限制筆數
            
        Returns:
            pd.DataFrame: 查詢結果
        """
        if not self.is_enabled():
            raise RuntimeError("SQLite 未啟用")

        if table_name not in self.ALLOWED_TABLES:
            raise ValueError(f"拒絕訪問非白名單資料表: {table_name}")

        # limit clamp 限制，確保在 10 ~ 5000 之間，防範大資料量 OOM
        limit = max(10, min(limit, 5000))

        # 1. 取得 Table schema 以驗證欄位白名單，並安全拼裝 SELECT 欄位
        schema_df = self.get_table_schema(table_name)
        if schema_df.empty:
            return pd.DataFrame()

        # get_table_schema 傳回的 DF 中，欄位名稱欄重命名成了 '欄位名稱'
        valid_columns = schema_df['欄位名稱'].tolist()
        if not valid_columns:
            return pd.DataFrame()

        # 安全地將欄位名稱用引號括起來，以防止 SQL Injection
        escaped_cols = ", ".join([f'"{col}"' for col in valid_columns])

        # 2. 建構 SQL 語句
        sql = f'SELECT {escaped_cols} FROM "{table_name}"'
        where_clauses = []
        params: List[Any] = []

        def parse_date(d):
            if not d:
                return None
            s = str(d).replace('-', '').replace('/', '').strip()
            if len(s) == 8 and s.isdigit():
                return s
            return None

        # 篩選：證券代號
        if '證券代號' in valid_columns and stock_code:
            where_clauses.append('"證券代號" = ?')
            params.append(str(stock_code).strip())

        # 篩選：證券名稱 (支援模糊查詢)
        if '證券名稱' in valid_columns and stock_name:
            where_clauses.append('"證券名稱" LIKE ?')
            params.append(f"%{str(stock_name).strip()}%")

        # 篩選：日期
        if '日期' in valid_columns:
            # 單一日期優先
            d_val = parse_date(date_str)
            if d_val:
                where_clauses.append('"日期" = ?')
                params.append(d_val)
            else:
                s_val = parse_date(start_date)
                e_val = parse_date(end_date)
                if s_val:
                    where_clauses.append('"日期" >= ?')
                    params.append(s_val)
                if e_val:
                    where_clauses.append('"日期" <= ?')
                    params.append(e_val)

        # 篩選：分點名稱 (支援模糊查詢)
        if '分點名稱' in valid_columns and broker_branch:
            where_clauses.append('"分點名稱" LIKE ?')
            params.append(f"%{str(broker_branch).strip()}%")

        if where_clauses:
            sql += " WHERE " + " AND ".join(where_clauses)

        # 自動排序：如果表有日期欄位，優先按日期降序排列
        if '日期' in valid_columns:
            sql += ' ORDER BY "日期" DESC'

        # 限制筆數
        sql += " LIMIT ?"
        params.append(limit)

        try:
            return self.db_manager.execute_query(sql, tuple(params))
        except Exception as e:
            self.logger.error(f"[SqliteInspectorService] 執行受控查詢失敗: {e}")
            raise e

    def _format_date(self, val: Any) -> Optional[str]:
        """格式化日期格式為 YYYY-MM-DD"""
        if val is None:
            return None
        s = str(val).strip()
        if len(s) == 8 and s.isdigit():
            return f"{s[:4]}-{s[4:6]}-{s[6:]}"
        return s
