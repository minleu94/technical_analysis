"""
SQLite 資料庫檢視服務 (SQLite Inspector Service)
提供 SQLite 資料表的 metadata 查詢、結構描述、以及唯讀的自訂 SQL 查詢功能。
"""

import re
import logging
from typing import Dict, List, Any, Optional
import pandas as pd
from data_module.db_manager import DBManager


class SqliteInspectorService:
    """SQLite 資料表檢視與查詢服務"""

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
        """獲取資料庫中所有的使用者資料表列表 (排除系統內建表)
        
        Returns:
            List[str]: 資料表名稱列表
        """
        if not self.is_enabled():
            return []

        try:
            sql = "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';"
            df = self.db_manager.execute_query(sql)
            if not df.empty:
                return df['name'].tolist()
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

    def execute_query(self, sql_query: str, params: tuple = (), limit: int = 100) -> pd.DataFrame:
        """執行唯讀的 SQL SELECT 查詢並返回結果
        
        Args:
            sql_query: SQL 查詢字串
            params: 參數 tuple
            limit: 限制筆數，避免記憶體溢出
            
        Returns:
            pd.DataFrame: 查詢結果
        """
        if not self.is_enabled():
            raise RuntimeError("SQLite 未啟用，無法執行查詢")

        clean_sql = sql_query.strip().strip(';').strip()
        if not clean_sql:
            return pd.DataFrame()

        # 1. 安全防禦：僅能執行 SELECT 查詢，防止任何 INSERT/UPDATE/DELETE/DROP/CREATE
        # 使用正則比對，必須以 SELECT 關鍵字開頭 (不分大小寫)
        if not re.match(r'^\s*SELECT\b', clean_sql, re.IGNORECASE):
            raise ValueError("安全性限制：僅允許執行唯讀的 SELECT 查詢！")

        # 進一步防禦：防止 SQL 中夾帶分號執行多重 command，或是含有破壞性字眼（如修改 schema 的 DDL/DML）
        restricted_keywords = [
            r'\bINSERT\b', r'\bUPDATE\b', r'\bDELETE\b', r'\bDROP\b', 
            r'\bCREATE\b', r'\bALTER\b', r'\bREPLACE\b', r'\bTRUNCATE\b'
        ]
        for pattern in restricted_keywords:
            if re.search(pattern, clean_sql, re.IGNORECASE):
                raise ValueError("安全性限制：查詢語法中包含不被允許的寫入或修改關鍵字！")

        # 2. 限額防禦：若 SQL 沒有 LIMIT 語句，自動在尾端加上 LIMIT 限制以保護記憶體
        if not re.search(r'\bLIMIT\b\s+\d+', clean_sql, re.IGNORECASE):
            # 去除尾端的分號與空白
            clean_sql = f"{clean_sql} LIMIT {limit}"

        # 3. 執行查詢
        try:
            return self.db_manager.execute_query(clean_sql, params)
        except Exception as e:
            self.logger.error(f"[SqliteInspectorService] SQL 執行出錯: {sql_query}, 錯誤: {e}")
            raise e

    def _format_date(self, val: Any) -> Optional[str]:
        """格式化日期格式為 YYYY-MM-DD"""
        if val is None:
            return None
        s = str(val).strip()
        if len(s) == 8 and s.isdigit():
            return f"{s[:4]}-{s[4:6]}-{s[6:]}"
        return s
