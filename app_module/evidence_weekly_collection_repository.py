from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from typing import Any, Mapping

from app_module.evidence_weekly_collection_dtos import EvidenceWeeklyCollectionRecord


_SCHEMA_VERSION = 1
_PENDING_STATUS = "pending_human_review"
_FAILED_STATUS = "collection_failed"


def _canonical_json(payload: Mapping[str, Any]) -> str:
    return json.dumps(dict(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


class EvidenceWeeklyCollectionRepository:
    """Stores weekly collection evidence in a SQLite sidecar beside its source."""

    def __init__(self, source_db_path: str | Path, *, sidecar_path: str | Path | None = None) -> None:
        self.source_db_path = Path(source_db_path)
        self.sidecar_path = (
            Path(sidecar_path)
            if sidecar_path is not None
            else self.source_db_path.with_suffix(f"{self.source_db_path.suffix}.weekly_collection_sidecar.sqlite")
        )
        self.sidecar_path.parent.mkdir(parents=True, exist_ok=True)
        self.ensure_schema()

    def ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sidecar_schema_version (
                    version INTEGER NOT NULL
                )
                """
            )
            conn.execute(
                """
                INSERT INTO sidecar_schema_version (version)
                SELECT ?
                WHERE NOT EXISTS (SELECT 1 FROM sidecar_schema_version)
                """,
                (_SCHEMA_VERSION,),
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS evidence_weekly_collections (
                    collection_id TEXT PRIMARY KEY,
                    period_start TEXT NOT NULL,
                    period_end TEXT NOT NULL,
                    source_path TEXT NOT NULL,
                    source_hash TEXT NOT NULL,
                    status TEXT NOT NULL CHECK (
                        status IN ('pending_human_review', 'collection_failed')
                    ),
                    payload_json TEXT NOT NULL,
                    error_type TEXT NOT NULL DEFAULT '',
                    error_message TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

    def save_pending(
        self,
        *,
        period_start: str,
        period_end: str,
        payload_json: Mapping[str, Any],
    ) -> EvidenceWeeklyCollectionRecord:
        record = self._new_record(
            period_start=period_start,
            period_end=period_end,
            payload_json=payload_json,
            status=_PENDING_STATUS,
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO evidence_weekly_collections (
                    collection_id, period_start, period_end, source_path, source_hash,
                    status, payload_json, error_type, error_message
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(collection_id) DO NOTHING
                """,
                self._record_values(record),
            )
        return self._get_required(record.collection_id)

    def save_failed(
        self,
        *,
        period_start: str,
        period_end: str,
        payload_json: Mapping[str, Any],
        error: Exception,
    ) -> EvidenceWeeklyCollectionRecord:
        record = self._new_record(
            period_start=period_start,
            period_end=period_end,
            payload_json=payload_json,
            status=_FAILED_STATUS,
            error=error,
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO evidence_weekly_collections (
                    collection_id, period_start, period_end, source_path, source_hash,
                    status, payload_json, error_type, error_message
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(collection_id) DO UPDATE SET
                    status = excluded.status,
                    error_type = excluded.error_type,
                    error_message = excluded.error_message
                """,
                self._record_values(record),
            )
        return self._get_required(record.collection_id)

    def get_by_identity(self, collection_id: str) -> EvidenceWeeklyCollectionRecord | None:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM evidence_weekly_collections WHERE collection_id = ?",
                (collection_id,),
            ).fetchone()
        return self._row_to_record(dict(row)) if row is not None else None

    def _new_record(
        self,
        *,
        period_start: str,
        period_end: str,
        payload_json: Mapping[str, Any],
        status: str,
        error: Exception | None = None,
    ) -> EvidenceWeeklyCollectionRecord:
        payload = dict(payload_json)
        source_hash = self._source_hash()
        identity = _canonical_json(
            {
                "period_start": period_start,
                "period_end": period_end,
                "source_hash": source_hash,
                "payload_json": payload,
            }
        )
        collection_id = f"ewc_{sha256(identity.encode('utf-8')).hexdigest()[:16]}"
        return EvidenceWeeklyCollectionRecord(
            collection_id=collection_id,
            period_start=period_start,
            period_end=period_end,
            source_path=str(self.source_db_path),
            source_hash=source_hash,
            status=status,
            payload_json=payload,
            error_type=type(error).__name__ if error is not None else "",
            error_message=str(error) if error is not None else "",
        )

    def _source_hash(self) -> str:
        digest = sha256()
        with self.source_db_path.open("rb") as source_file:
            while chunk := source_file.read(1024 * 1024):
                digest.update(chunk)
        return f"sha256:{digest.hexdigest()}"

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.sidecar_path)

    def _get_required(self, collection_id: str) -> EvidenceWeeklyCollectionRecord:
        record = self.get_by_identity(collection_id)
        if record is None:
            raise RuntimeError(f"collection record not found after save: {collection_id}")
        return record

    @staticmethod
    def _record_values(record: EvidenceWeeklyCollectionRecord) -> tuple[str, ...]:
        return (
            record.collection_id,
            record.period_start,
            record.period_end,
            record.source_path,
            record.source_hash,
            record.status,
            _canonical_json(record.payload_json),
            record.error_type,
            record.error_message,
        )

    @staticmethod
    def _row_to_record(row: dict[str, Any]) -> EvidenceWeeklyCollectionRecord:
        return EvidenceWeeklyCollectionRecord(
            collection_id=str(row["collection_id"]),
            period_start=str(row["period_start"]),
            period_end=str(row["period_end"]),
            source_path=str(row["source_path"]),
            source_hash=str(row["source_hash"]),
            status=str(row["status"]),
            payload_json=json.loads(row["payload_json"]),
            error_type=str(row["error_type"]),
            error_message=str(row["error_message"]),
            created_at=str(row["created_at"]),
        )
