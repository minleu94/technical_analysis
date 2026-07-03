from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from typing import Any

from app_module.evidence_operations_dtos import EvidenceOperationsWeeklyReview
from app_module.evidence_operations_history_dtos import EvidenceOperationsHistoryRecord
from app_module.research_run_dtos import canonical_json


class EvidenceOperationsHistoryRepository:
    def __init__(self, config: Any, *, db_path: str | Path | None = None) -> None:
        self.config = config
        self.db_path = Path(db_path) if db_path is not None else Path(config.db_file)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.ensure_schema()

    def ensure_schema(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS evidence_operations_weekly_reviews (
                    review_id TEXT PRIMARY KEY,
                    review_hash TEXT NOT NULL UNIQUE,
                    period_start TEXT NOT NULL,
                    period_end TEXT NOT NULL,
                    review_status TEXT NOT NULL,
                    scheduler_readiness TEXT NOT NULL,
                    production_scheduler_allowed INTEGER NOT NULL DEFAULT 0,
                    decision_quality_reviews_count INTEGER NOT NULL DEFAULT 0,
                    signal_decay_observations_count INTEGER NOT NULL DEFAULT 0,
                    manual_lifecycle_candidate_count INTEGER NOT NULL DEFAULT 0,
                    warnings_count INTEGER NOT NULL DEFAULT 0,
                    generated_by TEXT NOT NULL DEFAULT '',
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_evidence_operations_weekly_reviews_period
                ON evidence_operations_weekly_reviews(period_end, period_start)
                """
            )

    def save_weekly_review(
        self,
        report: EvidenceOperationsWeeklyReview,
        *,
        generated_by: str = "",
    ) -> EvidenceOperationsHistoryRecord:
        payload = report.to_dict()
        review_hash = "sha256:" + sha256(canonical_json(payload).encode("utf-8")).hexdigest()
        existing = self.get_by_hash(review_hash)
        if existing is not None:
            return existing
        record = EvidenceOperationsHistoryRecord(
            review_id=f"eor_{review_hash.removeprefix('sha256:')[:16]}",
            review_hash=review_hash,
            period_start=report.start_date,
            period_end=report.end_date,
            review_status=report.status,
            scheduler_readiness=report.manual_approval.readiness,
            production_scheduler_allowed=False,
            decision_quality_reviews_count=report.decision_quality.reviews_count,
            signal_decay_observations_count=report.signal_decay.observations_count,
            manual_lifecycle_candidate_count=len(report.manual_lifecycle_candidates),
            warnings_count=len(report.warnings),
            generated_by=generated_by,
            payload_json=payload,
        )
        row = self._record_to_row(record)
        columns = list(row.keys())
        placeholders = ", ".join("?" for _ in columns)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                f"INSERT INTO evidence_operations_weekly_reviews ({', '.join(columns)}) VALUES ({placeholders})",
                tuple(row[column] for column in columns),
            )
        saved = self.get_weekly_review(record.review_id)
        if saved is None:
            raise RuntimeError(f"evidence operations history record not found after insert: {record.review_id}")
        return saved

    def get_weekly_review(self, review_id: str) -> EvidenceOperationsHistoryRecord | None:
        return self._fetch_one("review_id = ?", (review_id,))

    def get_by_hash(self, review_hash: str) -> EvidenceOperationsHistoryRecord | None:
        return self._fetch_one("review_hash = ?", (review_hash,))

    def list_weekly_reviews(
        self,
        *,
        start_date: str | None = None,
        end_date: str | None = None,
        limit: int | None = None,
    ) -> list[EvidenceOperationsHistoryRecord]:
        where: list[str] = []
        params: list[Any] = []
        if start_date:
            where.append("period_end >= ?")
            params.append(start_date)
        if end_date:
            where.append("period_start <= ?")
            params.append(end_date)
        sql = "SELECT * FROM evidence_operations_weekly_reviews"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY period_end DESC, period_start DESC, review_id ASC"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(sql, tuple(params)).fetchall()
        return [self._row_to_record(dict(row)) for row in rows]

    def _fetch_one(self, where: str, params: tuple[Any, ...]) -> EvidenceOperationsHistoryRecord | None:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                f"SELECT * FROM evidence_operations_weekly_reviews WHERE {where} LIMIT 1",
                params,
            ).fetchone()
        return self._row_to_record(dict(row)) if row is not None else None

    def _record_to_row(self, record: EvidenceOperationsHistoryRecord) -> dict[str, Any]:
        row = record.to_dict()
        row["production_scheduler_allowed"] = int(record.production_scheduler_allowed)
        row["payload_json"] = canonical_json(record.payload_json)
        if not row["created_at"]:
            row.pop("created_at")
        return row

    def _row_to_record(self, row: dict[str, Any]) -> EvidenceOperationsHistoryRecord:
        return EvidenceOperationsHistoryRecord(
            review_id=str(row["review_id"]),
            review_hash=str(row["review_hash"]),
            period_start=str(row["period_start"]),
            period_end=str(row["period_end"]),
            review_status=str(row["review_status"]),
            scheduler_readiness=str(row["scheduler_readiness"]),
            production_scheduler_allowed=bool(row["production_scheduler_allowed"]),
            decision_quality_reviews_count=int(row["decision_quality_reviews_count"]),
            signal_decay_observations_count=int(row["signal_decay_observations_count"]),
            manual_lifecycle_candidate_count=int(row["manual_lifecycle_candidate_count"]),
            warnings_count=int(row["warnings_count"]),
            generated_by=str(row["generated_by"]),
            payload_json=json.loads(row["payload_json"] or "{}"),
            created_at=str(row["created_at"]),
        )
