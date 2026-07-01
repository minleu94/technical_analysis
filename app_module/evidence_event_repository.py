from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import sqlite3
from typing import Any
from uuid import uuid4

from app_module.evidence_event_dtos import EvidenceEvent, EvidenceEventType, EvidenceOutcome, normalize_event_type
from app_module.research_run_dtos import canonical_json
from data_module.evidence_event_migration import apply_evidence_event_schema


class EvidenceEventRepository:
    """SQLite repository for append-only evidence events and forward outcomes."""

    def __init__(self, config: Any, *, db_path: str | Path | None = None) -> None:
        self.config = config
        self.db_path = Path(db_path) if db_path is not None else Path(config.db_file)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.ensure_schema()

    def ensure_schema(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            apply_evidence_event_schema(conn)

    def insert_event(self, event: EvidenceEvent) -> EvidenceEvent:
        existing = self.get_event_by_hash(event.event_hash)
        if existing is not None:
            return existing
        same_id = self.get_event(event.event_id)
        if same_id is not None and same_id.event_hash != event.event_hash:
            event = replace(event, event_id=f"evt_{uuid4().hex}")

        row = self._event_to_row(event)
        columns = list(row.keys())
        placeholders = ", ".join("?" for _ in columns)
        column_sql = ", ".join(columns)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                f"INSERT INTO evidence_events ({column_sql}) VALUES ({placeholders})",
                tuple(row[column] for column in columns),
            )
        saved = self.get_event(event.event_id)
        if saved is None:
            raise RuntimeError(f"evidence event not found after insert: {event.event_id}")
        return saved

    def get_event(self, event_id: str) -> EvidenceEvent | None:
        return self._fetch_event("event_id = ?", (event_id,))

    def get_event_by_hash(self, event_hash: str) -> EvidenceEvent | None:
        return self._fetch_event("event_hash = ?", (event_hash,))

    def list_events(
        self,
        *,
        symbol: str | None = None,
        event_type: EvidenceEventType | str | None = None,
        decision_date: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        limit: int | None = None,
    ) -> list[EvidenceEvent]:
        where: list[str] = []
        params: list[Any] = []
        if symbol is not None:
            where.append("symbol = ?")
            params.append(symbol)
        if event_type is not None:
            where.append("event_type = ?")
            params.append(normalize_event_type(event_type).value)
        if decision_date is not None:
            where.append("decision_date = ?")
            params.append(decision_date)
        if start_date is not None:
            where.append("decision_date >= ?")
            params.append(start_date)
        if end_date is not None:
            where.append("decision_date <= ?")
            params.append(end_date)
        sql = "SELECT * FROM evidence_events"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY decision_date ASC, event_id ASC"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(sql, tuple(params)).fetchall()
        return [self._row_to_event(dict(row)) for row in rows]

    def upsert_outcome(self, outcome: EvidenceOutcome) -> EvidenceOutcome:
        row = self._outcome_to_row(outcome)
        columns = list(row.keys())
        placeholders = ", ".join("?" for _ in columns)
        column_sql = ", ".join(columns)
        updates = ", ".join(f"{column} = excluded.{column}" for column in columns if column != "calculated_at")
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                f"""
                INSERT INTO evidence_outcomes ({column_sql})
                VALUES ({placeholders})
                ON CONFLICT(event_id, window_days, return_basis) DO UPDATE SET
                    {updates},
                    calculated_at = CURRENT_TIMESTAMP
                """,
                tuple(row[column] for column in columns),
            )
        saved = self.get_outcome(outcome.event_id, outcome.window_days, outcome.return_basis)
        if saved is None:
            raise RuntimeError(f"evidence outcome not found after upsert: {outcome.event_id}")
        return saved

    def get_outcome(
        self,
        event_id: str,
        window_days: int,
        return_basis: str = "close_to_close_event_date",
    ) -> EvidenceOutcome | None:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT * FROM evidence_outcomes
                WHERE event_id = ? AND window_days = ? AND return_basis = ?
                """,
                (event_id, int(window_days), return_basis),
            ).fetchone()
        return self._row_to_outcome(dict(row)) if row is not None else None

    def list_outcomes(
        self,
        *,
        event_id: str | None = None,
        window_days: int | None = None,
    ) -> list[EvidenceOutcome]:
        where: list[str] = []
        params: list[Any] = []
        if event_id is not None:
            where.append("event_id = ?")
            params.append(event_id)
        if window_days is not None:
            where.append("window_days = ?")
            params.append(int(window_days))
        sql = "SELECT * FROM evidence_outcomes"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY event_id ASC, window_days ASC"
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(sql, tuple(params)).fetchall()
        return [self._row_to_outcome(dict(row)) for row in rows]

    def _fetch_event(self, where: str, params: tuple[Any, ...]) -> EvidenceEvent | None:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(f"SELECT * FROM evidence_events WHERE {where}", params).fetchone()
        return self._row_to_event(dict(row)) if row is not None else None

    def _event_to_row(self, event: EvidenceEvent) -> dict[str, Any]:
        return {
            "event_id": event.event_id,
            "event_hash": event.event_hash,
            "event_date": event.event_date,
            "decision_date": event.decision_date,
            "symbol": event.symbol,
            "event_type": event.event_type.value,
            "event_family": event.event_family,
            "source_type": event.source_type,
            "source_id": event.source_id,
            "source_snapshot_id": event.source_snapshot_id,
            "strategy_version_id": event.strategy_version_id,
            "profile_id": event.profile_id,
            "run_id": event.run_id,
            "reason_codes_json": canonical_json(list(event.reason_codes)),
            "why_not_codes_json": canonical_json(list(event.why_not_codes)),
            "risk_codes_json": canonical_json(list(event.risk_codes)),
            "score_bp": event.score_bp,
            "score_percentile_bp": event.score_percentile_bp,
            "regime": event.regime,
            "sector": event.sector,
            "concept_basket": event.concept_basket,
            "liquidity_state": event.liquidity_state,
            "data_quality": event.data_quality.value,
            "warnings_json": canonical_json(list(event.warnings)),
            "as_of_date": event.as_of_date,
            "available_date": event.available_date,
            "source_version": event.source_version,
            "cost_model_id": event.cost_model_id,
            "benchmark_id": event.benchmark_id,
            "industry_benchmark_id": event.industry_benchmark_id,
            "metadata_json": canonical_json(event.metadata),
        }

    def _row_to_event(self, row: dict[str, Any]) -> EvidenceEvent:
        return EvidenceEvent(
            event_id=str(row["event_id"]),
            event_hash=str(row["event_hash"]),
            event_date=str(row["event_date"]),
            decision_date=str(row["decision_date"]),
            symbol=row["symbol"],
            event_type=str(row["event_type"]),
            event_family=str(row["event_family"]),
            source_type=str(row["source_type"]),
            source_id=str(row["source_id"]),
            source_snapshot_id=str(row["source_snapshot_id"]),
            strategy_version_id=str(row["strategy_version_id"]),
            profile_id=str(row["profile_id"]),
            run_id=str(row["run_id"]),
            reason_codes=tuple(json.loads(row["reason_codes_json"] or "[]")),
            why_not_codes=tuple(json.loads(row["why_not_codes_json"] or "[]")),
            risk_codes=tuple(json.loads(row["risk_codes_json"] or "[]")),
            score_bp=row["score_bp"],
            score_percentile_bp=row["score_percentile_bp"],
            regime=row["regime"],
            sector=row["sector"],
            concept_basket=row["concept_basket"],
            liquidity_state=row["liquidity_state"],
            data_quality=str(row["data_quality"]),
            warnings=tuple(json.loads(row["warnings_json"] or "[]")),
            as_of_date=str(row["as_of_date"]),
            available_date=str(row["available_date"]),
            source_version=str(row["source_version"]),
            cost_model_id=str(row["cost_model_id"]),
            benchmark_id=row["benchmark_id"],
            industry_benchmark_id=row["industry_benchmark_id"],
            metadata=json.loads(row["metadata_json"] or "{}"),
            created_at=str(row["created_at"]),
        )

    def _outcome_to_row(self, outcome: EvidenceOutcome) -> dict[str, Any]:
        return {
            "outcome_id": outcome.outcome_id,
            "event_id": outcome.event_id,
            "window_days": outcome.window_days,
            "window_type": outcome.window_type,
            "return_basis": outcome.return_basis,
            "event_price_date": outcome.event_price_date,
            "event_close": outcome.event_close,
            "outcome_price_date": outcome.outcome_price_date,
            "outcome_close": outcome.outcome_close,
            "forward_return_bp": outcome.forward_return_bp,
            "benchmark_return_bp": outcome.benchmark_return_bp,
            "benchmark_excess_bp": outcome.benchmark_excess_bp,
            "industry_return_bp": outcome.industry_return_bp,
            "industry_excess_bp": outcome.industry_excess_bp,
            "max_adverse_excursion_bp": outcome.max_adverse_excursion_bp,
            "max_favorable_excursion_bp": outcome.max_favorable_excursion_bp,
            "tradable_flag": None if outcome.tradable_flag is None else int(outcome.tradable_flag),
            "limit_up_down_flag": None if outcome.limit_up_down_flag is None else int(outcome.limit_up_down_flag),
            "suspended_flag": None if outcome.suspended_flag is None else int(outcome.suspended_flag),
            "liquidity_cost_bp": outcome.liquidity_cost_bp,
            "outcome_status": outcome.outcome_status.value,
            "data_quality": outcome.data_quality.value,
            "warnings_json": canonical_json(list(outcome.warnings)),
            "data_as_of_date": outcome.data_as_of_date,
            "metadata_json": canonical_json(outcome.metadata),
        }

    def _row_to_outcome(self, row: dict[str, Any]) -> EvidenceOutcome:
        return EvidenceOutcome(
            outcome_id=str(row["outcome_id"]),
            event_id=str(row["event_id"]),
            window_days=int(row["window_days"]),
            window_type=str(row["window_type"]),
            return_basis=str(row["return_basis"]),
            event_price_date=row["event_price_date"],
            event_close=row["event_close"],
            outcome_price_date=row["outcome_price_date"],
            outcome_close=row["outcome_close"],
            forward_return_bp=row["forward_return_bp"],
            benchmark_return_bp=row["benchmark_return_bp"],
            benchmark_excess_bp=row["benchmark_excess_bp"],
            industry_return_bp=row["industry_return_bp"],
            industry_excess_bp=row["industry_excess_bp"],
            max_adverse_excursion_bp=row["max_adverse_excursion_bp"],
            max_favorable_excursion_bp=row["max_favorable_excursion_bp"],
            tradable_flag=None if row["tradable_flag"] is None else bool(row["tradable_flag"]),
            limit_up_down_flag=None if row["limit_up_down_flag"] is None else bool(row["limit_up_down_flag"]),
            suspended_flag=None if row["suspended_flag"] is None else bool(row["suspended_flag"]),
            liquidity_cost_bp=row["liquidity_cost_bp"],
            outcome_status=str(row["outcome_status"]),
            data_quality=str(row["data_quality"]),
            warnings=tuple(json.loads(row["warnings_json"] or "[]")),
            calculated_at=str(row["calculated_at"]),
            data_as_of_date=row["data_as_of_date"],
            metadata=json.loads(row["metadata_json"] or "{}"),
        )
