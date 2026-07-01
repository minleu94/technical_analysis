from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import sqlite3
from typing import Any

from app_module.decision_desk_snapshot_storage_dtos import StoredDecisionDeskSnapshot
from app_module.research_run_dtos import canonical_json
from app_module.evidence_event_service import utc_timestamp


class DecisionDeskSnapshotRepository:
    """SQLite repository for durable Daily Decision Desk snapshots."""

    def __init__(self, config: Any, *, db_path: str | Path | None = None) -> None:
        self.config = config
        self.db_path = Path(db_path) if db_path is not None else Path(config.db_file)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.ensure_schema()

    def ensure_schema(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_version (
                    component TEXT PRIMARY KEY,
                    version INTEGER NOT NULL,
                    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS decision_desk_snapshots (
                    snapshot_id TEXT PRIMARY KEY,
                    snapshot_hash TEXT NOT NULL UNIQUE,
                    decision_date TEXT NOT NULL,
                    as_of_date TEXT NOT NULL,
                    source_version TEXT NOT NULL,
                    builder_version TEXT NOT NULL,
                    data_quality TEXT NOT NULL,
                    warnings_json TEXT NOT NULL,
                    market_regime_json TEXT NOT NULL,
                    market_breadth_json TEXT NOT NULL,
                    sector_rotation_json TEXT NOT NULL,
                    relative_strength_liquidity_json TEXT NOT NULL,
                    watchlist_trigger_json TEXT NOT NULL,
                    portfolio_alert_json TEXT NOT NULL,
                    risk_prompt_json TEXT NOT NULL,
                    fundamental_diagnostics_json TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    snapshot_status TEXT NOT NULL DEFAULT 'active',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                INSERT OR REPLACE INTO schema_version (component, version, applied_at)
                VALUES ('decision_desk_snapshot_repository', 1, CURRENT_TIMESTAMP)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_decision_desk_snapshots_decision_date
                ON decision_desk_snapshots(decision_date)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_decision_desk_snapshots_status
                ON decision_desk_snapshots(snapshot_status)
                """
            )

    def save_snapshot(self, snapshot: StoredDecisionDeskSnapshot) -> StoredDecisionDeskSnapshot:
        existing = self.get_snapshot_by_hash(snapshot.snapshot_hash)
        if existing is not None:
            return existing

        created_at = snapshot.created_at or utc_timestamp()
        row_snapshot = replace(snapshot, created_at=created_at, snapshot_status="active")
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE decision_desk_snapshots
                SET snapshot_status = 'superseded'
                WHERE decision_date = ? AND snapshot_status = 'active'
                """,
                (row_snapshot.decision_date,),
            )
            row = self._snapshot_to_row(row_snapshot)
            columns = list(row.keys())
            placeholders = ", ".join("?" for _ in columns)
            conn.execute(
                f"INSERT INTO decision_desk_snapshots ({', '.join(columns)}) VALUES ({placeholders})",
                tuple(row[column] for column in columns),
            )
        saved = self.get_snapshot(row_snapshot.snapshot_id)
        if saved is None:
            raise RuntimeError(f"decision desk snapshot not found after insert: {row_snapshot.snapshot_id}")
        return saved

    def get_snapshot(self, snapshot_id: str) -> StoredDecisionDeskSnapshot | None:
        return self._fetch_one("snapshot_id = ?", (snapshot_id,))

    def get_snapshot_by_hash(self, snapshot_hash: str) -> StoredDecisionDeskSnapshot | None:
        return self._fetch_one("snapshot_hash = ?", (snapshot_hash,))

    def list_snapshots(self, *, limit: int | None = None, include_archived: bool = True) -> list[StoredDecisionDeskSnapshot]:
        where = "" if include_archived else "WHERE snapshot_status <> 'archived'"
        sql = f"SELECT * FROM decision_desk_snapshots {where} ORDER BY decision_date DESC, created_at DESC"
        params: tuple[Any, ...] = ()
        if limit is not None:
            sql += " LIMIT ?"
            params = (int(limit),)
        return self._fetch_many(sql, params)

    def find_by_decision_date(self, decision_date: str) -> list[StoredDecisionDeskSnapshot]:
        return self._fetch_many(
            """
            SELECT * FROM decision_desk_snapshots
            WHERE decision_date = ?
            ORDER BY created_at DESC
            """,
            (str(decision_date),),
        )

    def latest_before_or_on(self, decision_date: str) -> StoredDecisionDeskSnapshot | None:
        rows = self._fetch_many(
            """
            SELECT * FROM decision_desk_snapshots
            WHERE decision_date <= ? AND snapshot_status = 'active'
            ORDER BY decision_date DESC, created_at DESC
            LIMIT 1
            """,
            (str(decision_date),),
        )
        return rows[0] if rows else None

    def archive(self, snapshot_id: str) -> bool:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "UPDATE decision_desk_snapshots SET snapshot_status = 'archived' WHERE snapshot_id = ?",
                (snapshot_id,),
            )
        return cursor.rowcount > 0

    def _fetch_one(self, where: str, params: tuple[Any, ...]) -> StoredDecisionDeskSnapshot | None:
        rows = self._fetch_many(f"SELECT * FROM decision_desk_snapshots WHERE {where} LIMIT 1", params)
        return rows[0] if rows else None

    def _fetch_many(self, sql: str, params: tuple[Any, ...]) -> list[StoredDecisionDeskSnapshot]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(sql, params).fetchall()
        return [self._row_to_snapshot(dict(row)) for row in rows]

    def _snapshot_to_row(self, snapshot: StoredDecisionDeskSnapshot) -> dict[str, Any]:
        return {
            "snapshot_id": snapshot.snapshot_id,
            "snapshot_hash": snapshot.snapshot_hash,
            "decision_date": snapshot.decision_date,
            "as_of_date": snapshot.as_of_date,
            "source_version": snapshot.source_version,
            "builder_version": snapshot.builder_version,
            "data_quality": snapshot.data_quality,
            "warnings_json": canonical_json(snapshot.warnings_json),
            "market_regime_json": canonical_json(snapshot.market_regime_json),
            "market_breadth_json": canonical_json(snapshot.market_breadth_json),
            "sector_rotation_json": canonical_json(snapshot.sector_rotation_json),
            "relative_strength_liquidity_json": canonical_json(snapshot.relative_strength_liquidity_json),
            "watchlist_trigger_json": canonical_json(snapshot.watchlist_trigger_json),
            "portfolio_alert_json": canonical_json(snapshot.portfolio_alert_json),
            "risk_prompt_json": canonical_json(snapshot.risk_prompt_json),
            "fundamental_diagnostics_json": canonical_json(snapshot.fundamental_diagnostics_json),
            "metadata_json": canonical_json(snapshot.metadata_json),
            "snapshot_status": snapshot.snapshot_status,
            "created_at": snapshot.created_at,
        }

    def _row_to_snapshot(self, row: dict[str, Any]) -> StoredDecisionDeskSnapshot:
        return StoredDecisionDeskSnapshot(
            snapshot_id=str(row["snapshot_id"]),
            snapshot_hash=str(row["snapshot_hash"]),
            decision_date=str(row["decision_date"]),
            as_of_date=str(row["as_of_date"]),
            source_version=str(row["source_version"]),
            builder_version=str(row["builder_version"]),
            data_quality=str(row["data_quality"]),
            warnings_json=json.loads(row["warnings_json"] or "[]"),
            market_regime_json=json.loads(row["market_regime_json"] or "{}"),
            market_breadth_json=json.loads(row["market_breadth_json"] or "{}"),
            sector_rotation_json=json.loads(row["sector_rotation_json"] or "{}"),
            relative_strength_liquidity_json=json.loads(row["relative_strength_liquidity_json"] or "{}"),
            watchlist_trigger_json=json.loads(row["watchlist_trigger_json"] or "{}"),
            portfolio_alert_json=json.loads(row["portfolio_alert_json"] or "{}"),
            risk_prompt_json=json.loads(row["risk_prompt_json"] or "{}"),
            fundamental_diagnostics_json=json.loads(row["fundamental_diagnostics_json"] or "{}"),
            metadata_json=json.loads(row["metadata_json"] or "{}"),
            snapshot_status=str(row["snapshot_status"]),
            created_at=str(row["created_at"]),
        )
