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
    ALLOWED_TABLES = {
        'daily_prices',
        'technical_indicators',
        'market_indices',
        'industry_indices',
        'broker_flows',
        'fundamental_monthly_revenues',
        'fundamental_statement_items',
        'fundamental_valuation_metrics',
    }
    DISPLAY_COLUMN_ALIASES = {'涨跌': '漲跌'}

    def __init__(self, config):
        """初始化檢視服務
        
        Args:
            config: TWStockConfig 實例
        """
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.db_manager = DBManager(config)

    def _validate_table_name(self, table_name: str):
        if table_name not in self.ALLOWED_TABLES:
            raise ValueError(f"拒絕訪問非白名單資料表: {table_name}")
        if not re.match(r'^[a-zA-Z0-9_]+$', table_name):
            raise ValueError(f"不合法的資料表名稱: {table_name}")

    def _get_raw_columns(self, table_name: str) -> List[str]:
        self._validate_table_name(table_name)
        with self.db_manager.connect() as conn:
            cursor = conn.execute(f"PRAGMA table_info({table_name});")
            return [row["name"] for row in cursor.fetchall()]

    def _display_column_name(self, raw_column: str) -> str:
        return self.DISPLAY_COLUMN_ALIASES.get(raw_column, raw_column)

    def _column_lookup(self, raw_columns: List[str]) -> Dict[str, str]:
        lookup = {col: col for col in raw_columns}
        for raw_col in raw_columns:
            lookup[self._display_column_name(raw_col)] = raw_col
        return lookup

    def _signed_change_expression(self, raw_columns: List[str]) -> Optional[str]:
        if '漲跌價差' not in raw_columns:
            return None

        sign_candidates = [col for col in ('漲跌(+/-)', '漲跌', '涨跌') if col in raw_columns]
        if not sign_candidates:
            return '"漲跌價差"'

        if len(sign_candidates) == 1:
            sign_expr = f'"{sign_candidates[0]}"'
        else:
            sign_expr = "COALESCE(" + ", ".join(f'"{col}"' for col in sign_candidates) + ")"
        return (
            f'CASE '
            f"WHEN TRIM({sign_expr}) IN ('-', '−', '跌', '▼') THEN -ABS(\"漲跌價差\") "
            f"WHEN TRIM({sign_expr}) IN ('+', '＋', '漲', '▲') THEN ABS(\"漲跌價差\") "
            f'ELSE "漲跌價差" END'
        )

    def _select_expression(self, table_name: str, raw_column: str, raw_columns: List[str]) -> str:
        display_col = self._display_column_name(raw_column)
        if table_name == "daily_prices" and raw_column == "漲跌價差":
            change_expr = self._signed_change_expression(raw_columns)
            if change_expr:
                return f'{change_expr} AS "{display_col}"'
        if display_col != raw_column:
            return f'"{raw_column}" AS "{display_col}"'
        return f'"{raw_column}"'

    def _default_order_sql(self, raw_columns: List[str]) -> str:
        order_clauses = []
        if '日期' in raw_columns:
            order_clauses.append('"日期" DESC')
        elif 'as_of_date' in raw_columns:
            order_clauses.append('"as_of_date" DESC')
        elif 'available_date' in raw_columns:
            order_clauses.append('"available_date" DESC')
        elif 'period' in raw_columns:
            order_clauses.append('"period" DESC')
        if '證券代號' in raw_columns:
            order_clauses.append('"證券代號" ASC')
        elif 'stock_code' in raw_columns:
            order_clauses.append('"stock_code" ASC')
        if '分點名稱' in raw_columns:
            order_clauses.append('"分點名稱" ASC')
        order_clauses.append('rowid ASC')
        return " ORDER BY " + ", ".join(order_clauses)

    def _sort_expression(
        self,
        table_name: str,
        sort_column: Optional[str],
        sort_order: str,
        raw_columns: List[str],
    ) -> str:
        if not sort_column:
            return self._default_order_sql(raw_columns)

        raw_column = self._column_lookup(raw_columns).get(sort_column)
        if not raw_column:
            return self._default_order_sql(raw_columns)

        direction = "ASC" if str(sort_order).lower() == "asc" else "DESC"
        if table_name == "daily_prices" and raw_column == "漲跌價差":
            order_expr = self._signed_change_expression(raw_columns) or '"漲跌價差"'
        else:
            order_expr = f'"{raw_column}"'

        stable_ties = []
        if raw_column != '日期' and '日期' in raw_columns:
            stable_ties.append('"日期" DESC')
        elif raw_column != 'as_of_date' and 'as_of_date' in raw_columns:
            stable_ties.append('"as_of_date" DESC')
        elif raw_column != 'available_date' and 'available_date' in raw_columns:
            stable_ties.append('"available_date" DESC')
        elif raw_column != 'period' and 'period' in raw_columns:
            stable_ties.append('"period" DESC')
        if raw_column != '證券代號' and '證券代號' in raw_columns:
            stable_ties.append('"證券代號" ASC')
        elif raw_column != 'stock_code' and 'stock_code' in raw_columns:
            stable_ties.append('"stock_code" ASC')
        stable_ties.append('rowid ASC')
        return " ORDER BY " + ", ".join([f"{order_expr} {direction}", *stable_ties])

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

        self._validate_table_name(table_name)

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
                if '欄位名稱' in df.columns:
                    df['欄位名稱'] = df['欄位名稱'].map(self._display_column_name)
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
            elif '欄位名稱' in schema_df.columns:
                schema_columns = set(schema_df['欄位名稱'].tolist())
                date_column = None
                for candidate in ('as_of_date', 'available_date', 'period'):
                    if candidate in schema_columns:
                        date_column = candidate
                        break
                if date_column:
                    date_df = self.db_manager.execute_query(
                        f'SELECT MIN("{date_column}") as min_date, MAX("{date_column}") as max_date FROM "{table_name}";'
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

    def _build_filtered_query(
        self,
        table_name: str,
        stock_code: Optional[str] = None,
        stock_name: Optional[str] = None,
        date_str: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        broker_branch: Optional[str] = None,
        sort_column: Optional[str] = None,
        sort_order: str = "desc",
    ) -> tuple[list[str], str, list[Any], str]:
        """建立篩選條件與排序 SQL，回傳 (raw_columns, WHERE_SQL, params, ORDER_BY_SQL)"""
        raw_columns = self._get_raw_columns(table_name)
        if not raw_columns:
            return [], "", [], ""

        where_clauses = []
        params = []

        def parse_date(d):
            if not d:
                return None
            s = str(d).replace('-', '').replace('/', '').strip()
            if len(s) == 8 and s.isdigit():
                return s
            return None

        # 篩選：證券代號
        if '證券代號' in raw_columns and stock_code:
            where_clauses.append('"證券代號" = ?')
            params.append(str(stock_code).strip())
        elif 'stock_code' in raw_columns and stock_code:
            where_clauses.append('"stock_code" = ?')
            params.append(str(stock_code).strip())

        # 篩選：證券名稱 (支援模糊查詢)
        if '證券名稱' in raw_columns and stock_name:
            where_clauses.append('"證券名稱" LIKE ?')
            params.append(f"%{str(stock_name).strip()}%")

        # 篩選：日期
        if '日期' in raw_columns:
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
        else:
            date_column = None
            for candidate in ('as_of_date', 'available_date'):
                if candidate in raw_columns:
                    date_column = candidate
                    break
            if date_column:
                date_value = str(date_str).strip() if date_str else ""
                if date_value:
                    where_clauses.append(f'"{date_column}" = ?')
                    params.append(date_value)
                else:
                    start_value = str(start_date).strip() if start_date else ""
                    end_value = str(end_date).strip() if end_date else ""
                    if start_value:
                        where_clauses.append(f'"{date_column}" >= ?')
                        params.append(start_value)
                    if end_value:
                        where_clauses.append(f'"{date_column}" <= ?')
                        params.append(end_value)

        # 篩選：分點名稱 (支援模糊查詢)
        if '分點名稱' in raw_columns and broker_branch:
            where_clauses.append('"分點名稱" LIKE ?')
            params.append(f"%{str(broker_branch).strip()}%")

        where_sql = ""
        if where_clauses:
            where_sql = " WHERE " + " AND ".join(where_clauses)

        order_by_sql = self._sort_expression(table_name, sort_column, sort_order, raw_columns)

        return raw_columns, where_sql, params, order_by_sql

    def query_table_data(
        self,
        table_name: str,
        stock_code: Optional[str] = None,
        stock_name: Optional[str] = None,
        date_str: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        broker_branch: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
        sort_column: Optional[str] = None,
        sort_order: str = "desc",
    ) -> pd.DataFrame:
        """受控的表格資料分頁查詢"""
        if not self.is_enabled():
            raise RuntimeError("SQLite 未啟用")

        if table_name not in self.ALLOWED_TABLES:
            raise ValueError(f"拒絕訪問非白名單資料表: {table_name}")

        limit = max(1, min(limit, 5000))
        offset = max(0, int(offset))

        raw_columns, where_sql, params, order_by_sql = self._build_filtered_query(
            table_name=table_name,
            stock_code=stock_code,
            stock_name=stock_name,
            date_str=date_str,
            start_date=start_date,
            end_date=end_date,
            broker_branch=broker_branch,
            sort_column=sort_column,
            sort_order=sort_order,
        )

        if not raw_columns:
            return pd.DataFrame()

        select_cols = ", ".join(
            self._select_expression(table_name, col, raw_columns)
            for col in raw_columns
        )
        sql = f'SELECT {select_cols} FROM "{table_name}"' + where_sql + order_by_sql + " LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        try:
            return self.db_manager.execute_query(sql, tuple(params))
        except Exception as e:
            self.logger.error(f"[SqliteInspectorService] 執行受控分頁查詢失敗: {e}")
            raise e

    def query_table_data_count(
        self,
        table_name: str,
        stock_code: Optional[str] = None,
        stock_name: Optional[str] = None,
        date_str: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        broker_branch: Optional[str] = None,
    ) -> int:
        """獲取受控查詢的總筆數 (計數)"""
        if not self.is_enabled():
            return 0

        if table_name not in self.ALLOWED_TABLES:
            raise ValueError(f"拒絕訪問非白名單資料表: {table_name}")

        _, where_sql, params, _ = self._build_filtered_query(
            table_name=table_name,
            stock_code=stock_code,
            stock_name=stock_name,
            date_str=date_str,
            start_date=start_date,
            end_date=end_date,
            broker_branch=broker_branch
        )

        sql = f'SELECT COUNT(*) as cnt FROM "{table_name}"' + where_sql

        try:
            df = self.db_manager.execute_query(sql, tuple(params))
            if not df.empty:
                return int(df.iloc[0]['cnt'])
            return 0
        except Exception as e:
            self.logger.error(f"[SqliteInspectorService] 執行計數查詢失敗: {e}")
            raise e

    def _format_date(self, val: Any) -> Optional[str]:
        """格式化日期格式為 YYYY-MM-DD"""
        if val is None:
            return None
        s = str(val).strip()
        if len(s) == 8 and s.isdigit():
            return f"{s[:4]}-{s[4:6]}-{s[6:]}"
        return s

