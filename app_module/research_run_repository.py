"""Research Run Registry SQLite metadata repository."""

from __future__ import annotations

from dataclasses import fields
import sqlite3
from pathlib import Path
from typing import Any

from app_module.research_run_dtos import (
    ResearchRunMetadataDTO,
    canonical_json,
    parse_json_list,
    parse_json_object,
)


class ResearchRunRepositoryError(Exception):
    """Research Run Repository 基底例外。"""


class ResearchRunConflictError(ResearchRunRepositoryError):
    """同一 run_id 對應到不同 payload hash。"""


class ResearchRunRepository:
    """統一研究 run metadata 的 SQLite repository。

    B1 只負責 schema 與 metadata round-trip。Parquet 寫入、crash recovery 與
    integrity verification 由 M2-B 後續 task 接續。
    """

    SCHEMA_NAME = "research_runs"
    SCHEMA_VERSION = 2

    JSON_FIELD_MAP = {
        "original_input": "original_input_json",
        "normalized_params": "normalized_params_json",
        "fallback_reason": "fallback_reason_json",
        "universe": "universe_json",
        "data_manifest": "data_manifest_json",
        "metrics": "metrics_json",
        "regime_breakdown": "regime_breakdown_json",
        "benchmark_results": "benchmark_results_json",
    }

    def __init__(self, config: Any):
        self.config = config
        self.db_path = Path(config.research_run_db_file)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.ensure_schema()

    def ensure_schema(self) -> None:
        """執行可重入 schema migration。"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_version (
                    name TEXT PRIMARY KEY,
                    version INTEGER NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            current = conn.execute(
                "SELECT version FROM schema_version WHERE name = ?",
                (self.SCHEMA_NAME,),
            ).fetchone()
            current_version = int(current[0]) if current else 0

            if current_version < 1:
                self._migrate_v1(conn)
                current_version = 1
            if current_version < 2:
                self._migrate_v2(conn)

            conn.execute(
                """
                INSERT INTO schema_version(name, version, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(name) DO UPDATE SET
                    version = excluded.version,
                    updated_at = excluded.updated_at
                """,
                (self.SCHEMA_NAME, self.SCHEMA_VERSION),
            )

    def _migrate_v1(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS research_runs (
                run_id TEXT PRIMARY KEY,
                run_name TEXT NOT NULL,
                run_type TEXT NOT NULL,
                strategy_id TEXT NOT NULL DEFAULT '',
                strategy_version TEXT NOT NULL DEFAULT '',
                parameter_contract_version TEXT NOT NULL DEFAULT '',
                original_input_json TEXT NOT NULL DEFAULT '{}',
                normalized_params_json TEXT NOT NULL DEFAULT '{}',
                fallback_reason_json TEXT NOT NULL DEFAULT '{}',
                universe_json TEXT NOT NULL DEFAULT '[]',
                start_date TEXT NOT NULL DEFAULT '',
                end_date TEXT NOT NULL DEFAULT '',
                data_cutoff_date TEXT NOT NULL DEFAULT '',
                data_fingerprint TEXT NOT NULL DEFAULT '',
                fingerprint_algorithm TEXT NOT NULL DEFAULT '',
                data_manifest_json TEXT NOT NULL DEFAULT '{}',
                capital_cents INTEGER NOT NULL DEFAULT 0,
                fee_bp_x100 INTEGER NOT NULL DEFAULT 0,
                slippage_bp_x100 INTEGER NOT NULL DEFAULT 0,
                stop_loss_bp INTEGER,
                take_profit_bp INTEGER,
                execution_price TEXT NOT NULL DEFAULT '',
                sizing_mode TEXT NOT NULL DEFAULT '',
                metrics_json TEXT NOT NULL DEFAULT '{}',
                regime_breakdown_json TEXT NOT NULL DEFAULT '{}',
                benchmark_results_json TEXT NOT NULL DEFAULT '{}',
                payload_hash TEXT NOT NULL,
                equity_path TEXT NOT NULL DEFAULT '',
                equity_parquet_hash TEXT NOT NULL DEFAULT '',
                trades_path TEXT NOT NULL DEFAULT '',
                trades_parquet_hash TEXT NOT NULL DEFAULT '',
                is_archived INTEGER NOT NULL DEFAULT 0,
                promoted_version_id TEXT,
                promotion_reconciliation_status TEXT NOT NULL DEFAULT 'none',
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_research_runs_created_at "
            "ON research_runs(created_at)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_research_runs_type_strategy "
            "ON research_runs(run_type, strategy_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_research_runs_archived "
            "ON research_runs(is_archived)"
        )

    def _migrate_v2(self, conn: sqlite3.Connection) -> None:
        self._add_column_if_missing(
            conn,
            "research_runs",
            "storage_state",
            "TEXT NOT NULL DEFAULT 'committed'",
        )
        self._add_column_if_missing(
            conn,
            "research_runs",
            "integrity_status",
            "TEXT NOT NULL DEFAULT 'valid'",
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_research_runs_storage_state "
            "ON research_runs(storage_state)"
        )

    def _add_column_if_missing(
        self,
        conn: sqlite3.Connection,
        table_name: str,
        column_name: str,
        definition: str,
    ) -> None:
        columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table_name})")}
        if column_name not in columns:
            conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")

    def insert_metadata(self, metadata: ResearchRunMetadataDTO) -> ResearchRunMetadataDTO:
        existing = self.get_metadata(metadata.run_id)
        if existing:
            if existing.payload_hash != metadata.payload_hash:
                raise ResearchRunConflictError(
                    f"run_id 已存在但 payload_hash 不一致: {metadata.run_id}"
                )
            return existing

        row = self._dto_to_row(metadata)
        columns = list(row.keys())
        placeholders = ", ".join("?" for _ in columns)
        column_sql = ", ".join(columns)

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                f"INSERT INTO research_runs ({column_sql}) VALUES ({placeholders})",
                tuple(row[column] for column in columns),
            )
        return metadata

    def get_metadata(self, run_id: str) -> ResearchRunMetadataDTO | None:
        row = self.get_raw_metadata_row(run_id)
        if row is None:
            return None
        return self._row_to_dto(row)

    def get_raw_metadata_row(self, run_id: str) -> dict[str, Any] | None:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM research_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        if row is None:
            return None
        return dict(row)

    def update_storage_fields(
        self,
        run_id: str,
        *,
        equity_path: str | None = None,
        equity_parquet_hash: str | None = None,
        trades_path: str | None = None,
        trades_parquet_hash: str | None = None,
        storage_state: str | None = None,
        integrity_status: str | None = None,
    ) -> None:
        updates: dict[str, Any] = {}
        if equity_path is not None:
            updates["equity_path"] = equity_path
        if equity_parquet_hash is not None:
            updates["equity_parquet_hash"] = equity_parquet_hash
        if trades_path is not None:
            updates["trades_path"] = trades_path
        if trades_parquet_hash is not None:
            updates["trades_parquet_hash"] = trades_parquet_hash
        if storage_state is not None:
            updates["storage_state"] = storage_state
        if integrity_status is not None:
            updates["integrity_status"] = integrity_status
        if not updates:
            return

        set_sql = ", ".join(f"{column} = ?" for column in updates)
        params = [*updates.values(), run_id]
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                f"UPDATE research_runs SET {set_sql} WHERE run_id = ?",
                params,
            )

    def list_uncommitted_rows(self) -> list[dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT * FROM research_runs
                WHERE storage_state IN ('staging', 'files_ready')
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def list_metadata(self, *, include_archived: bool = False) -> list[ResearchRunMetadataDTO]:
        where = "" if include_archived else "WHERE is_archived = 0"
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                f"""
                SELECT * FROM research_runs
                {where}
                ORDER BY created_at DESC, run_id ASC
                """
            ).fetchall()
        return [self._row_to_dto(dict(row)) for row in rows]

    def archive_run(self, run_id: str) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE research_runs SET is_archived = 1 WHERE run_id = ?",
                (run_id,),
            )

    def mark_promoted(self, run_id: str, version_id: str) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE research_runs
                SET promoted_version_id = ?,
                    promotion_reconciliation_status = 'synced'
                WHERE run_id = ?
                """,
                (version_id, run_id),
            )

    def _dto_to_row(self, metadata: ResearchRunMetadataDTO) -> dict[str, Any]:
        row: dict[str, Any] = {}
        for field_info in fields(metadata):
            name = field_info.name
            value = getattr(metadata, name)
            if name in self.JSON_FIELD_MAP:
                row[self.JSON_FIELD_MAP[name]] = canonical_json(value)
            elif name == "is_archived":
                row[name] = 1 if value else 0
            else:
                row[name] = value
        return row

    def _row_to_dto(self, row: dict[str, Any]) -> ResearchRunMetadataDTO:
        kwargs: dict[str, Any] = {}
        reverse_json_map = {value: key for key, value in self.JSON_FIELD_MAP.items()}
        dto_field_names = {field_info.name for field_info in fields(ResearchRunMetadataDTO)}

        for column, value in row.items():
            if column in reverse_json_map:
                dto_name = reverse_json_map[column]
                if dto_name == "universe":
                    kwargs[dto_name] = parse_json_list(value)
                else:
                    kwargs[dto_name] = parse_json_object(value)
            elif column in dto_field_names:
                kwargs[column] = bool(value) if column == "is_archived" else value

        return ResearchRunMetadataDTO(**kwargs)
