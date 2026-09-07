"""候選池 SQLite 副本儲存；明確初始化及 revision 衝突檢查。"""

from contextlib import closing
import json
from pathlib import Path
import sqlite3
from typing import Any


class WatchlistRepository:
    SCHEMA_VERSION = 1

    def __init__(self, db_path: Path, *, initialize: bool = False):
        self.db_path = Path(db_path).resolve()
        if initialize:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            with closing(sqlite3.connect(self.db_path)) as conn, conn:
                conn.execute("CREATE TABLE IF NOT EXISTS watchlists (watchlist_id TEXT PRIMARY KEY, payload_json TEXT NOT NULL, revision INTEGER NOT NULL, source_hash TEXT NOT NULL DEFAULT '')")

    def load(self, watchlist_id: str) -> tuple[dict[str, Any], int] | None:
        with closing(sqlite3.connect(f"{self.db_path.as_uri()}?mode=ro", uri=True)) as conn:
            conn.execute("PRAGMA query_only=ON")
            row = conn.execute("SELECT payload_json, revision FROM watchlists WHERE watchlist_id=?", (watchlist_id,)).fetchone()
        if row is None:
            return None
        payload = json.loads(row[0])
        if not isinstance(payload, dict):
            raise ValueError("候選池 payload 必須是 object")
        return payload, int(row[1])

    def save(self, watchlist_id: str, payload: dict[str, Any], *, expected_revision: int | None, source_hash: str = "") -> int:
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, allow_nan=False)
        with closing(sqlite3.connect(f"{self.db_path.as_uri()}?mode=rw", uri=True)) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT revision FROM watchlists WHERE watchlist_id=?", (watchlist_id,)).fetchone()
            actual = int(row[0]) if row else None
            if actual != expected_revision:
                raise RuntimeError("watchlist_revision_conflict")
            revision = (actual or 0) + 1
            conn.execute("INSERT INTO watchlists(watchlist_id,payload_json,revision,source_hash) VALUES(?,?,?,?) ON CONFLICT(watchlist_id) DO UPDATE SET payload_json=excluded.payload_json,revision=excluded.revision", (watchlist_id, raw, revision, source_hash))
        return revision

    def list_ids(self) -> list[str]:
        with closing(sqlite3.connect(f"{self.db_path.as_uri()}?mode=ro", uri=True)) as conn:
            return [row[0] for row in conn.execute("SELECT watchlist_id FROM watchlists ORDER BY watchlist_id")]

    def delete(self, watchlist_id: str, *, expected_revision: int) -> bool:
        with closing(sqlite3.connect(f"{self.db_path.as_uri()}?mode=rw", uri=True)) as conn, conn:
            cursor = conn.execute("DELETE FROM watchlists WHERE watchlist_id=? AND revision=?", (watchlist_id, expected_revision))
            if cursor.rowcount != 1:
                raise RuntimeError("watchlist_revision_conflict")
        return True
