"""共用的 SQLite 唯讀查詢 adapter。

狀態卡、Inspector 等讀取路徑不能因為查詢而初始化 schema、切換 WAL 或
commit。這個 adapter 只接受已存在的資料庫，並以 ``mode=ro`` 與
``PRAGMA query_only=ON`` 建立短生命週期查詢連線。
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, List
from urllib.parse import quote

import pandas as pd


class ReadOnlySQLiteManager:
    """以 query-only 連線讀取既有 SQLite 檔案。"""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.last_read_mode = "normal"

    def _uri(self, *, immutable: bool = False) -> str:
        path = str(self.db_path).replace("\\", "/")
        suffix = "mode=ro&immutable=1" if immutable else "mode=ro"
        return f"file:{quote(path, safe='/:')}?{suffix}"

    @contextmanager
    def connect(self, *, immutable: bool = False) -> Iterator[sqlite3.Connection]:
        if not self.db_path.is_file():
            raise FileNotFoundError(f"找不到 SQLite 資料庫：{self.db_path}")
        conn = sqlite3.connect(self._uri(immutable=immutable), uri=True)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA query_only=ON")
            yield conn
        finally:
            conn.close()

    @staticmethod
    def _can_retry_immutable(exc: BaseException) -> bool:
        return "unable to open database file" in str(exc).lower()

    def execute_query(self, query: str, params: tuple[Any, ...] = ()) -> pd.DataFrame:
        try:
            with self.connect() as conn:
                result = pd.read_sql_query(query, conn, params=params)
            self.last_read_mode = "normal"
            return result
        except Exception as exc:
            # Windows 上若其他程序持有資料庫鎖，SQLite 可能無法取得一般
            # read lock。immutable 只讀快照會繞過鎖定檢查，可能只看到最後
            # 已提交內容；結果會留下 read mode 供上層診斷，若仍不可讀則原樣拋出。
            if not self._can_retry_immutable(exc):
                raise
            with self.connect(immutable=True) as conn:
                result = pd.read_sql_query(query, conn, params=params)
            self.last_read_mode = "immutable_fallback"
            return result

    def iter_query(
        self,
        query: str,
        params: tuple[Any, ...] = (),
        *,
        chunksize: int = 10_000,
    ) -> Iterator[pd.DataFrame]:
        """以 query-only 連線逐批讀取既有 SQLite 資料。

        匯出等長任務不應一次把整張表載入記憶體，也不應在單一大型
        ``to_csv`` 呼叫期間失去取消觀測。此 iterator 保留連線直到資料
        讀完；若一般唯讀連線在尚未產生任何 chunk 前無法開啟，才安全地
        重試 immutable snapshot。已產生部分資料後不重試，避免呼叫端把
        重試結果與前一輪資料重複寫出。
        """
        if isinstance(chunksize, bool) or chunksize <= 0:
            raise ValueError("chunksize must be a positive integer")

        yielded = False
        try:
            with self.connect() as conn:
                chunks = pd.read_sql_query(
                    query,
                    conn,
                    params=params,
                    chunksize=chunksize,
                )
                for chunk in chunks:
                    yielded = True
                    yield chunk
            self.last_read_mode = "normal"
            return
        except Exception as exc:
            if yielded or not self._can_retry_immutable(exc):
                raise

        with self.connect(immutable=True) as conn:
            chunks = pd.read_sql_query(
                query,
                conn,
                params=params,
                chunksize=chunksize,
            )
            for chunk in chunks:
                yielded = True
                yield chunk
        self.last_read_mode = "immutable_fallback"

    def get_table_columns(self, table_name: str) -> List[str]:
        query = f'PRAGMA table_info("{table_name}")'
        try:
            with self.connect() as conn:
                rows = conn.execute(query).fetchall()
            self.last_read_mode = "normal"
        except Exception as exc:
            if not self._can_retry_immutable(exc):
                raise
            with self.connect(immutable=True) as conn:
                rows = conn.execute(query).fetchall()
            self.last_read_mode = "immutable_fallback"
        return [str(row[1]) for row in rows]
