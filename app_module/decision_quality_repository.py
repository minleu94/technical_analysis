from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import sqlite3
from typing import Any
from uuid import uuid4

from app_module.decision_quality_dtos import (
    DecisionQualityActionItem,
    DecisionQualityItem,
    DecisionQualityReview,
    DecisionQualitySummary,
)
from app_module.research_run_dtos import canonical_json


class DecisionQualityRepository:
    """Append-only/idempotent storage for process review evidence."""

    def __init__(self, config: Any, *, db_path: str | Path | None = None) -> None:
        self.config = config
        self.db_path = Path(db_path) if db_path is not None else Path(config.db_file)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.ensure_schema()

    def ensure_schema(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS decision_quality_reviews (
                    review_id TEXT PRIMARY KEY,
                    review_hash TEXT NOT NULL UNIQUE,
                    review_period_start TEXT NOT NULL,
                    review_period_end TEXT NOT NULL,
                    review_type TEXT NOT NULL,
                    portfolio_mode_counts_json TEXT NOT NULL DEFAULT '{}',
                    evidence_event_count INTEGER NOT NULL DEFAULT 0,
                    trade_count INTEGER NOT NULL DEFAULT 0,
                    journal_entry_count INTEGER NOT NULL DEFAULT 0,
                    portfolio_alert_count INTEGER NOT NULL DEFAULT 0,
                    ignored_alert_count INTEGER NOT NULL DEFAULT 0,
                    manual_override_count INTEGER NOT NULL DEFAULT 0,
                    missed_high_quality_signal_count INTEGER NOT NULL DEFAULT 0,
                    unreviewed_decay_candidate_count INTEGER NOT NULL DEFAULT 0,
                    unlinked_trade_count INTEGER NOT NULL DEFAULT 0,
                    decision_quality_score_bp INTEGER NOT NULL DEFAULT 0,
                    process_adherence_score_bp INTEGER NOT NULL DEFAULT 0,
                    evidence_usage_score_bp INTEGER NOT NULL DEFAULT 0,
                    risk_discipline_score_bp INTEGER NOT NULL DEFAULT 0,
                    review_completeness_score_bp INTEGER NOT NULL DEFAULT 0,
                    review_status TEXT NOT NULL,
                    quality TEXT NOT NULL DEFAULT 'missing',
                    warnings_json TEXT NOT NULL DEFAULT '[]',
                    diagnostics_json TEXT NOT NULL DEFAULT '[]',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS decision_quality_items (
                    item_id TEXT PRIMARY KEY,
                    review_id TEXT NOT NULL,
                    item_type TEXT NOT NULL,
                    symbol TEXT NOT NULL DEFAULT '',
                    event_date TEXT NOT NULL DEFAULT '',
                    decision_date TEXT NOT NULL DEFAULT '',
                    source_type TEXT NOT NULL DEFAULT '',
                    source_id TEXT NOT NULL DEFAULT '',
                    related_trade_id TEXT NOT NULL DEFAULT '',
                    related_position_id TEXT NOT NULL DEFAULT '',
                    related_evidence_event_id TEXT NOT NULL DEFAULT '',
                    related_gap_id TEXT NOT NULL DEFAULT '',
                    related_decay_id TEXT NOT NULL DEFAULT '',
                    severity TEXT NOT NULL DEFAULT 'medium',
                    status TEXT NOT NULL DEFAULT 'open',
                    reason_codes_json TEXT NOT NULL DEFAULT '[]',
                    evidence_json TEXT NOT NULL DEFAULT '{}',
                    suggested_review_question TEXT NOT NULL DEFAULT '',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(review_id) REFERENCES decision_quality_reviews(review_id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS decision_quality_item_status_history (
                    history_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    item_id TEXT NOT NULL,
                    previous_status TEXT NOT NULL DEFAULT '',
                    new_status TEXT NOT NULL,
                    reviewer TEXT NOT NULL DEFAULT '',
                    reason_code TEXT NOT NULL DEFAULT '',
                    note TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS decision_quality_action_items (
                    action_item_id TEXT PRIMARY KEY,
                    review_id TEXT NOT NULL,
                    item_id TEXT NOT NULL DEFAULT '',
                    description TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'open',
                    owner TEXT NOT NULL DEFAULT '',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(review_id) REFERENCES decision_quality_reviews(review_id)
                )
                """
            )

    def save_review(
        self,
        review: DecisionQualityReview,
        *,
        items: list[DecisionQualityItem] | tuple[DecisionQualityItem, ...] = (),
    ) -> DecisionQualityReview:
        existing = self.get_review_by_hash(review.review_hash)
        if existing is not None:
            return existing
        row = self._review_to_row(review)
        columns = list(row.keys())
        placeholders = ", ".join("?" for _ in columns)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                f"INSERT INTO decision_quality_reviews ({', '.join(columns)}) VALUES ({placeholders})",
                tuple(row[column] for column in columns),
            )
            for item in items:
                item_row = self._item_to_row(item)
                item_columns = list(item_row.keys())
                item_placeholders = ", ".join("?" for _ in item_columns)
                conn.execute(
                    f"INSERT OR IGNORE INTO decision_quality_items ({', '.join(item_columns)}) "
                    f"VALUES ({item_placeholders})",
                    tuple(item_row[column] for column in item_columns),
                )
        saved = self.get_review(review.review_id)
        if saved is None:
            raise RuntimeError(f"decision quality review not found after insert: {review.review_id}")
        return saved

    def get_review(self, review_id: str) -> DecisionQualityReview | None:
        return self._fetch_review("review_id = ?", (review_id,))

    def get_review_by_hash(self, review_hash: str) -> DecisionQualityReview | None:
        return self._fetch_review("review_hash = ?", (review_hash,))

    def list_reviews(
        self,
        *,
        start_date: str | None = None,
        end_date: str | None = None,
        review_type: str | None = None,
    ) -> list[DecisionQualityReview]:
        where: list[str] = []
        params: list[Any] = []
        if start_date:
            where.append("review_period_end >= ?")
            params.append(start_date)
        if end_date:
            where.append("review_period_start <= ?")
            params.append(end_date)
        if review_type:
            where.append("review_type = ?")
            params.append(review_type)
        sql = "SELECT * FROM decision_quality_reviews"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY review_period_start ASC, review_id ASC"
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(sql, tuple(params)).fetchall()
        return [self._row_to_review(dict(row)) for row in rows]

    def list_items(self, *, review_id: str | None = None, status: str | None = None) -> list[DecisionQualityItem]:
        where: list[str] = []
        params: list[Any] = []
        if review_id:
            where.append("review_id = ?")
            params.append(review_id)
        if status:
            where.append("status = ?")
            params.append(status)
        sql = "SELECT * FROM decision_quality_items"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY created_at ASC, item_id ASC"
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(sql, tuple(params)).fetchall()
        return [self._row_to_item(dict(row)) for row in rows]

    def mark_item_reviewed(self, item_id: str, *, reviewer: str = "", note: str = "") -> DecisionQualityItem:
        return self._mark_item_status(item_id, new_status="reviewed", reviewer=reviewer, reason_code="", note=note)

    def mark_item_dismissed(
        self,
        item_id: str,
        *,
        reviewer: str = "",
        reason_code: str = "",
        note: str = "",
    ) -> DecisionQualityItem:
        return self._mark_item_status(
            item_id,
            new_status="dismissed",
            reviewer=reviewer,
            reason_code=reason_code,
            note=note,
        )

    def create_action_item(
        self,
        *,
        review_id: str,
        item_id: str,
        description: str,
        owner: str = "",
        metadata_json: dict[str, Any] | None = None,
    ) -> DecisionQualityActionItem:
        action = DecisionQualityActionItem(
            action_item_id=f"dqa_{uuid4().hex}",
            review_id=review_id,
            item_id=item_id,
            description=description,
            owner=owner,
            metadata_json=metadata_json or {},
        )
        row = self._action_to_row(action)
        columns = list(row.keys())
        placeholders = ", ".join("?" for _ in columns)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                f"INSERT INTO decision_quality_action_items ({', '.join(columns)}) VALUES ({placeholders})",
                tuple(row[column] for column in columns),
            )
        saved = self.get_action_item(action.action_item_id)
        if saved is None:
            raise RuntimeError(f"decision quality action item not found after insert: {action.action_item_id}")
        return saved

    def get_action_item(self, action_item_id: str) -> DecisionQualityActionItem | None:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM decision_quality_action_items WHERE action_item_id = ?",
                (action_item_id,),
            ).fetchone()
        return self._row_to_action(dict(row)) if row is not None else None

    def list_action_items(self, *, review_id: str | None = None) -> list[DecisionQualityActionItem]:
        sql = "SELECT * FROM decision_quality_action_items"
        params: tuple[Any, ...] = ()
        if review_id:
            sql += " WHERE review_id = ?"
            params = (review_id,)
        sql += " ORDER BY created_at ASC, action_item_id ASC"
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(sql, params).fetchall()
        return [self._row_to_action(dict(row)) for row in rows]

    def list_item_status_history(self, item_id: str) -> list[dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT * FROM decision_quality_item_status_history
                WHERE item_id = ?
                ORDER BY history_id ASC
                """,
                (item_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def summarize_reviews(self) -> DecisionQualitySummary:
        reviews = self.list_reviews()
        items = self.list_items()
        scores = [review.decision_quality_score_bp for review in reviews]
        return DecisionQualitySummary(
            reviews_count=len(reviews),
            item_counts=dict(sorted(Counter(item.item_type for item in items).items())),
            status_counts=dict(sorted(Counter(item.status for item in items).items())),
            review_status_counts=dict(sorted(Counter(review.review_status for review in reviews).items())),
            average_decision_quality_score_bp=(sum(scores) // len(scores)) if scores else None,
            warnings_count=sum(len(review.warnings_json) for review in reviews),
        )

    def _fetch_review(self, where: str, params: tuple[Any, ...]) -> DecisionQualityReview | None:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(f"SELECT * FROM decision_quality_reviews WHERE {where}", params).fetchone()
        return self._row_to_review(dict(row)) if row is not None else None

    def _mark_item_status(
        self,
        item_id: str,
        *,
        new_status: str,
        reviewer: str,
        reason_code: str,
        note: str,
    ) -> DecisionQualityItem:
        current = {item.item_id: item for item in self.list_items()}.get(item_id)
        if current is None:
            raise KeyError(f"decision quality item not found: {item_id}")
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("UPDATE decision_quality_items SET status = ? WHERE item_id = ?", (new_status, item_id))
            conn.execute(
                """
                INSERT INTO decision_quality_item_status_history (
                    item_id, previous_status, new_status, reviewer, reason_code, note
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (item_id, current.status, new_status, reviewer, reason_code, note),
            )
        updated = {item.item_id: item for item in self.list_items()}.get(item_id)
        if updated is None:
            raise RuntimeError(f"decision quality item not found after status update: {item_id}")
        return updated

    def _review_to_row(self, review: DecisionQualityReview) -> dict[str, Any]:
        row = review.to_dict()
        row["portfolio_mode_counts_json"] = canonical_json(review.portfolio_mode_counts_json)
        row["warnings_json"] = canonical_json(review.warnings_json)
        row["diagnostics_json"] = canonical_json(review.diagnostics_json)
        row["metadata_json"] = canonical_json(review.metadata_json)
        if not row["created_at"]:
            row.pop("created_at")
        return row

    def _item_to_row(self, item: DecisionQualityItem) -> dict[str, Any]:
        row = item.to_dict()
        row["reason_codes_json"] = canonical_json(item.reason_codes_json)
        row["evidence_json"] = canonical_json(item.evidence_json)
        row["metadata_json"] = canonical_json(item.metadata_json)
        if not row["created_at"]:
            row.pop("created_at")
        return row

    def _action_to_row(self, action: DecisionQualityActionItem) -> dict[str, Any]:
        row = action.to_dict()
        row["metadata_json"] = canonical_json(action.metadata_json)
        if not row["created_at"]:
            row.pop("created_at")
        return row

    def _row_to_review(self, row: dict[str, Any]) -> DecisionQualityReview:
        return DecisionQualityReview(
            review_id=str(row["review_id"]),
            review_hash=str(row["review_hash"]),
            review_period_start=str(row["review_period_start"]),
            review_period_end=str(row["review_period_end"]),
            review_type=str(row["review_type"]),
            portfolio_mode_counts_json=json.loads(row["portfolio_mode_counts_json"] or "{}"),
            evidence_event_count=int(row["evidence_event_count"]),
            trade_count=int(row["trade_count"]),
            journal_entry_count=int(row["journal_entry_count"]),
            portfolio_alert_count=int(row["portfolio_alert_count"]),
            ignored_alert_count=int(row["ignored_alert_count"]),
            manual_override_count=int(row["manual_override_count"]),
            missed_high_quality_signal_count=int(row["missed_high_quality_signal_count"]),
            unreviewed_decay_candidate_count=int(row["unreviewed_decay_candidate_count"]),
            unlinked_trade_count=int(row["unlinked_trade_count"]),
            decision_quality_score_bp=int(row["decision_quality_score_bp"]),
            process_adherence_score_bp=int(row["process_adherence_score_bp"]),
            evidence_usage_score_bp=int(row["evidence_usage_score_bp"]),
            risk_discipline_score_bp=int(row["risk_discipline_score_bp"]),
            review_completeness_score_bp=int(row["review_completeness_score_bp"]),
            review_status=str(row["review_status"]),
            quality=str(row["quality"]),
            warnings_json=json.loads(row["warnings_json"] or "[]"),
            diagnostics_json=json.loads(row["diagnostics_json"] or "[]"),
            metadata_json=json.loads(row["metadata_json"] or "{}"),
            created_at=str(row["created_at"]),
        )

    def _row_to_item(self, row: dict[str, Any]) -> DecisionQualityItem:
        return DecisionQualityItem(
            item_id=str(row["item_id"]),
            review_id=str(row["review_id"]),
            item_type=str(row["item_type"]),
            symbol=str(row["symbol"]),
            event_date=str(row["event_date"]),
            decision_date=str(row["decision_date"]),
            source_type=str(row["source_type"]),
            source_id=str(row["source_id"]),
            related_trade_id=str(row["related_trade_id"]),
            related_position_id=str(row["related_position_id"]),
            related_evidence_event_id=str(row["related_evidence_event_id"]),
            related_gap_id=str(row["related_gap_id"]),
            related_decay_id=str(row["related_decay_id"]),
            severity=str(row["severity"]),
            status=str(row["status"]),
            reason_codes_json=json.loads(row["reason_codes_json"] or "[]"),
            evidence_json=json.loads(row["evidence_json"] or "{}"),
            suggested_review_question=str(row["suggested_review_question"]),
            metadata_json=json.loads(row["metadata_json"] or "{}"),
            created_at=str(row["created_at"]),
        )

    def _row_to_action(self, row: dict[str, Any]) -> DecisionQualityActionItem:
        return DecisionQualityActionItem(
            action_item_id=str(row["action_item_id"]),
            review_id=str(row["review_id"]),
            item_id=str(row["item_id"]),
            description=str(row["description"]),
            status=str(row["status"]),
            owner=str(row["owner"]),
            metadata_json=json.loads(row["metadata_json"] or "{}"),
            created_at=str(row["created_at"]),
        )
