"""StockScreener 的 SQLite 唯讀資料載入支援函式。"""

import logging
from pathlib import Path
import sqlite3

import pandas as pd


logger = logging.getLogger(__name__)


def _readonly_connection(config):
    db_file = Path(getattr(config, "db_file", ""))
    if not db_file.exists():
        return None

    conn = sqlite3.connect(f"{db_file.resolve().as_uri()}?mode=ro", uri=True)
    conn.execute("PRAGMA query_only=ON")
    return conn


def _recent_date_values(conn, table_name, date_column, limit):
    sql = f"""
        SELECT DISTINCT {date_column} AS date_value
        FROM {table_name}
        WHERE {date_column} IS NOT NULL
        ORDER BY {date_column} DESC
        LIMIT ?
    """
    rows = conn.execute(sql, (limit,)).fetchall()
    return [row[0] for row in rows if row and row[0]]


def load_recent_stock_prices(config, period, volume_lookback):
    """載入強弱勢個股篩選所需的最近 SQLite 資料。"""
    if not getattr(config, "use_sqlite", False):
        return None

    lookback_limit = max(volume_lookback + 8, 32 if period == "day" else 48)
    try:
        conn = _readonly_connection(config)
        if conn is None:
            return None

        with conn:
            date_values = _recent_date_values(conn, "daily_prices", "日期", lookback_limit)
            if not date_values:
                return None

            placeholders = ",".join("?" for _ in date_values)
            sql = f"""
                SELECT
                    日期,
                    證券代號,
                    證券名稱,
                    收盤價,
                    開盤價,
                    最高價,
                    最低價,
                    成交股數,
                    成交金額
                FROM daily_prices
                WHERE 日期 IN ({placeholders})
                ORDER BY 日期 ASC, 證券代號 ASC
            """
            return pd.read_sql_query(sql, conn, params=date_values)
    except Exception as sql_err:
        logger.warning("SQLite 快速載入強弱勢個股資料失敗: %s，將降級為既有路徑", sql_err)
        return None


def load_recent_industry_indices(config, period):
    """載入強弱勢產業篩選所需的最近 SQLite 資料。"""
    if not getattr(config, "use_sqlite", False):
        return None

    lookback_limit = 45 if period == "day" else 90
    try:
        conn = _readonly_connection(config)
        if conn is None:
            return None

        with conn:
            date_values = _recent_date_values(conn, "industry_indices", "日期", lookback_limit)
            if not date_values:
                return None

            placeholders = ",".join("?" for _ in date_values)
            sql = f"""
                SELECT 日期, 指數名稱, 收盤指數
                FROM industry_indices
                WHERE 日期 IN ({placeholders})
                ORDER BY 日期 ASC, 指數名稱 ASC
            """
            return pd.read_sql_query(sql, conn, params=date_values)
    except Exception as sql_err:
        logger.warning("SQLite 快速載入強弱勢產業資料失敗: %s，將降級為 CSV", sql_err)
        return None
