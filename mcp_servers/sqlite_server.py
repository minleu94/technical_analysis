from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from data_module.config import TWStockConfig

MAX_QUERY_ROWS = 1000


def get_db_path() -> Path:
    config = TWStockConfig()
    return config.db_file


def _readonly_connection(db_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"{db_path.resolve().as_uri()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    return connection


def _validate_read_query(sql: str) -> str:
    statement = sql.strip().rstrip(";").strip()
    keyword = statement.partition(" ")[0].upper()
    if keyword not in {"SELECT", "WITH"}:
        raise ValueError("僅允許執行唯讀 SELECT / WITH 查詢！")
    return statement


def query_sqlite_readonly(
    db_path: Path,
    sql: str,
    *,
    max_rows: int = MAX_QUERY_ROWS,
) -> list[dict[str, Any]]:
    statement = _validate_read_query(sql)
    with _readonly_connection(db_path) as connection:
        cursor = connection.execute(statement)
        rows = cursor.fetchmany(max_rows + 1)
    if len(rows) > max_rows:
        raise ValueError(f"查詢回傳列數超過安全上限 {max_rows}，請縮小條件或加 LIMIT。")
    return [dict(row) for row in rows]


def explain_sqlite(db_path: Path, sql: str) -> list[dict[str, Any]]:
    statement = sql.strip().rstrip(";").strip()
    prefix = "EXPLAIN QUERY PLAN "
    if statement.upper().startswith(prefix):
        statement = statement[len(prefix):].lstrip()
    statement = _validate_read_query(statement)
    with _readonly_connection(db_path) as connection:
        rows = connection.execute(f"{prefix}{statement}").fetchall()
    return [dict(row) for row in rows]


def get_sqlite_schema(db_path: Path) -> dict[str, list[dict[str, Any]]]:
    with _readonly_connection(db_path) as connection:
        tables = [
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ).fetchall()
        ]
        schema_info: dict[str, list[dict[str, Any]]] = {}
        for table in tables:
            quoted_table = table.replace('"', '""')
            cols = connection.execute(
                f'PRAGMA table_info("{quoted_table}")'
            ).fetchall()
            schema_info[table] = [dict(col) for col in cols]
    return schema_info


def create_sqlite_mcp_server():
    from fastmcp import FastMCP

    mcp = FastMCP("twstock-sqlite-inspector")
    db_path = get_db_path()

    @mcp.tool()
    def query_sqlite(sql: str) -> list[dict[str, Any]]:
        """執行唯讀 SELECT / WITH 查詢，最多回傳 1000 列。"""
        return query_sqlite_readonly(db_path, sql)

    @mcp.tool()
    def explain_query(sql: str) -> list[dict[str, Any]]:
        """對指定的 SQL 查詢執行 EXPLAIN QUERY PLAN。"""
        return explain_sqlite(db_path, sql)

    @mcp.tool()
    def get_db_schema() -> dict[str, list[dict[str, Any]]]:
        """獲取 twstock.db 所有資料表的 Schema 結構資訊。"""
        return get_sqlite_schema(db_path)

    return mcp

if __name__ == "__main__":
    create_sqlite_mcp_server().run(show_banner=False)
