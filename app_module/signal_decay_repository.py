from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import sqlite3
from typing import Any

from app_module.research_run_dtos import canonical_json
from app_module.signal_decay_dtos import SignalDecayObservation, SignalDecaySummary


class SignalDecayRepository:
    """Append-only/idempotent SQLite repository for signal decay observations."""

    def __init__(self, config: Any, *, db_path: str | Path | None = None) -> None:
        self.config = config
        self.db_path = Path(db_path) if db_path is not None else Path(config.db_file)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.ensure_schema()

    def ensure_schema(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS signal_decay_observations (
                    decay_id TEXT PRIMARY KEY,
                    decay_hash TEXT NOT NULL UNIQUE,
                    observation_date TEXT NOT NULL,
                    signal_scope_type TEXT NOT NULL,
                    signal_scope_id TEXT NOT NULL,
                    strategy_version_id TEXT NOT NULL DEFAULT '',
                    profile_id TEXT NOT NULL DEFAULT '',
                    event_type TEXT NOT NULL DEFAULT '',
                    event_family TEXT NOT NULL DEFAULT '',
                    factor_name TEXT NOT NULL DEFAULT '',
                    window_short INTEGER NOT NULL,
                    window_long INTEGER NOT NULL,
                    sample_size_short INTEGER NOT NULL DEFAULT 0,
                    sample_size_long INTEGER NOT NULL DEFAULT 0,
                    forward_excess_short_bp INTEGER,
                    forward_excess_long_bp INTEGER,
                    win_rate_short_bp INTEGER,
                    win_rate_long_bp INTEGER,
                    mae_short_bp INTEGER,
                    mae_long_bp INTEGER,
                    live_gap_short_bp INTEGER,
                    live_gap_long_bp INTEGER,
                    decay_score_bp INTEGER NOT NULL DEFAULT 0,
                    decay_status TEXT NOT NULL,
                    suggested_lifecycle_action TEXT NOT NULL,
                    confidence TEXT NOT NULL DEFAULT 'low',
                    evidence_event_count INTEGER NOT NULL DEFAULT 0,
                    gap_observation_count INTEGER NOT NULL DEFAULT 0,
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
                CREATE INDEX IF NOT EXISTS idx_signal_decay_scope
                ON signal_decay_observations(observation_date, signal_scope_type, signal_scope_id)
                """
            )

    def save_observation(self, observation: SignalDecayObservation) -> SignalDecayObservation:
        existing = self.get_by_hash(observation.decay_hash)
        if existing is not None:
            return existing
        row = self._observation_to_row(observation)
        columns = list(row.keys())
        placeholders = ", ".join("?" for _ in columns)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                f"INSERT INTO signal_decay_observations ({', '.join(columns)}) VALUES ({placeholders})",
                tuple(row[column] for column in columns),
            )
        saved = self.get_observation(observation.decay_id)
        if saved is None:
            raise RuntimeError(f"signal decay observation not found after insert: {observation.decay_id}")
        return saved

    def get_observation(self, decay_id: str) -> SignalDecayObservation | None:
        return self._fetch_one("decay_id = ?", (decay_id,))

    def get_by_hash(self, decay_hash: str) -> SignalDecayObservation | None:
        return self._fetch_one("decay_hash = ?", (decay_hash,))

    def list_observations(
        self,
        *,
        observation_date: str | None = None,
        signal_scope_type: str | None = None,
        signal_scope_id: str | None = None,
        limit: int | None = None,
    ) -> list[SignalDecayObservation]:
        where: list[str] = []
        params: list[Any] = []
        if observation_date:
            where.append("observation_date = ?")
            params.append(observation_date)
        if signal_scope_type:
            where.append("signal_scope_type = ?")
            params.append(signal_scope_type)
        if signal_scope_id:
            where.append("signal_scope_id = ?")
            params.append(signal_scope_id)
        sql = "SELECT * FROM signal_decay_observations"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY observation_date ASC, signal_scope_type ASC, signal_scope_id ASC, decay_id ASC"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))
        return self._fetch_many(sql, tuple(params))

    def summarize_decay(self, *, observation_date: str | None = None) -> SignalDecaySummary:
        observations = self.list_observations(observation_date=observation_date)
        status_counts = Counter(row.decay_status for row in observations)
        suggestion_counts = Counter(row.suggested_lifecycle_action for row in observations)
        confidence_counts = Counter(row.confidence for row in observations)
        quality_counts = Counter(row.quality for row in observations)
        warnings_count = sum(len(row.warnings_json) for row in observations)
        return SignalDecaySummary(
            observations_count=len(observations),
            status_counts=dict(sorted(status_counts.items())),
            suggestion_counts=dict(sorted(suggestion_counts.items())),
            confidence_counts=dict(sorted(confidence_counts.items())),
            quality_counts=dict(sorted(quality_counts.items())),
            warnings_count=warnings_count,
        )

    def _fetch_one(self, where: str, params: tuple[Any, ...]) -> SignalDecayObservation | None:
        rows = self._fetch_many(f"SELECT * FROM signal_decay_observations WHERE {where} LIMIT 1", params)
        return rows[0] if rows else None

    def _fetch_many(self, sql: str, params: tuple[Any, ...]) -> list[SignalDecayObservation]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(sql, params).fetchall()
        return [self._row_to_observation(dict(row)) for row in rows]

    def _observation_to_row(self, observation: SignalDecayObservation) -> dict[str, Any]:
        row = observation.to_dict()
        row["warnings_json"] = canonical_json(observation.warnings_json)
        row["diagnostics_json"] = canonical_json(observation.diagnostics_json)
        row["metadata_json"] = canonical_json(observation.metadata_json)
        if not row["created_at"]:
            row.pop("created_at")
        return row

    def _row_to_observation(self, row: dict[str, Any]) -> SignalDecayObservation:
        return SignalDecayObservation(
            decay_id=str(row["decay_id"]),
            decay_hash=str(row["decay_hash"]),
            observation_date=str(row["observation_date"]),
            signal_scope_type=str(row["signal_scope_type"]),
            signal_scope_id=str(row["signal_scope_id"]),
            strategy_version_id=str(row["strategy_version_id"]),
            profile_id=str(row["profile_id"]),
            event_type=str(row["event_type"]),
            event_family=str(row["event_family"]),
            factor_name=str(row["factor_name"]),
            window_short=int(row["window_short"]),
            window_long=int(row["window_long"]),
            sample_size_short=int(row["sample_size_short"]),
            sample_size_long=int(row["sample_size_long"]),
            forward_excess_short_bp=row["forward_excess_short_bp"],
            forward_excess_long_bp=row["forward_excess_long_bp"],
            win_rate_short_bp=row["win_rate_short_bp"],
            win_rate_long_bp=row["win_rate_long_bp"],
            mae_short_bp=row["mae_short_bp"],
            mae_long_bp=row["mae_long_bp"],
            live_gap_short_bp=row["live_gap_short_bp"],
            live_gap_long_bp=row["live_gap_long_bp"],
            decay_score_bp=int(row["decay_score_bp"]),
            decay_status=str(row["decay_status"]),
            suggested_lifecycle_action=str(row["suggested_lifecycle_action"]),
            confidence=str(row["confidence"]),
            evidence_event_count=int(row["evidence_event_count"]),
            gap_observation_count=int(row["gap_observation_count"]),
            quality=str(row["quality"]),
            warnings_json=json.loads(row["warnings_json"] or "[]"),
            diagnostics_json=json.loads(row["diagnostics_json"] or "[]"),
            metadata_json=json.loads(row["metadata_json"] or "{}"),
            created_at=str(row["created_at"]),
        )

