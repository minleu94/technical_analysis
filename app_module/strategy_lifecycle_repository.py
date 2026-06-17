"""Append-only lifecycle evidence repository."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import json
from pathlib import Path
import sqlite3
from typing import Any

from app_module.research_run_dtos import ResearchRunMetadataDTO
from app_module.strategy_lifecycle_service import (
    LifecycleAction,
    LifecycleDecision,
    StrategyLifecycleService,
)


class LifecycleEvidenceStatus(str, Enum):
    """Lifecycle evidence persistence status."""

    PROPOSED = "proposed"
    APPLIED = "applied"
    SUPERSEDED = "superseded"


@dataclass(frozen=True)
class LifecycleEvidenceRecord:
    evidence_id: int
    run_id: str
    strategy_id: str
    version_id: str
    action: str
    status: LifecycleEvidenceStatus
    reason: str
    decision_snapshot: dict[str, Any]
    created_at: str


@dataclass(frozen=True)
class LifecycleCurrentState:
    run_id: str
    strategy_id: str
    version_id: str
    action: str
    status: LifecycleEvidenceStatus
    latest_evidence_id: int
    updated_at: str


class LifecycleEvidenceRepository:
    """Persist lifecycle decisions without mutating historical strategy evidence."""

    SCHEMA_NAME = "strategy_lifecycle_evidence"
    SCHEMA_VERSION = 1

    def __init__(
        self,
        config: Any,
        *,
        lifecycle_service: StrategyLifecycleService | None = None,
    ) -> None:
        self.config = config
        self.db_path = Path(config.research_run_db_file)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.lifecycle_service = lifecycle_service or StrategyLifecycleService()
        self.ensure_schema()

    def ensure_schema(self) -> None:
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
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS strategy_lifecycle_evidence (
                    evidence_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    strategy_id TEXT NOT NULL DEFAULT '',
                    version_id TEXT NOT NULL DEFAULT '',
                    action TEXT NOT NULL,
                    status TEXT NOT NULL,
                    reason TEXT NOT NULL DEFAULT '',
                    decision_snapshot_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_lifecycle_evidence_run "
                "ON strategy_lifecycle_evidence(run_id, evidence_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_lifecycle_evidence_strategy "
                "ON strategy_lifecycle_evidence(strategy_id, evidence_id)"
            )
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

    def record_decision(
        self,
        *,
        run: ResearchRunMetadataDTO,
        version_id: str = "",
        status: LifecycleEvidenceStatus = LifecycleEvidenceStatus.PROPOSED,
        reason: str = "",
        decision: LifecycleDecision | None = None,
    ) -> LifecycleEvidenceRecord:
        lifecycle_decision = decision or self.lifecycle_service.evaluate_run(run)
        snapshot = self._decision_to_snapshot(lifecycle_decision)
        payload = json.dumps(snapshot, ensure_ascii=False, sort_keys=True)
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """
                INSERT INTO strategy_lifecycle_evidence (
                    run_id,
                    strategy_id,
                    version_id,
                    action,
                    status,
                    reason,
                    decision_snapshot_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run.run_id,
                    run.strategy_id,
                    version_id,
                    lifecycle_decision.action.value,
                    status.value,
                    reason,
                    payload,
                ),
            )
            if cursor.lastrowid is None:
                raise RuntimeError("lifecycle evidence insert did not return row id")
            evidence_id = int(cursor.lastrowid)
        record = self.get_evidence(evidence_id)
        if record is None:
            raise RuntimeError(f"lifecycle evidence not found after insert: {evidence_id}")
        return record

    def get_evidence(self, evidence_id: int) -> LifecycleEvidenceRecord | None:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT * FROM strategy_lifecycle_evidence
                WHERE evidence_id = ?
                """,
                (evidence_id,),
            ).fetchone()
        return self._row_to_record(dict(row)) if row is not None else None

    def list_evidence_for_run(self, run_id: str) -> list[LifecycleEvidenceRecord]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT * FROM strategy_lifecycle_evidence
                WHERE run_id = ?
                ORDER BY evidence_id ASC
                """,
                (run_id,),
            ).fetchall()
        return [self._row_to_record(dict(row)) for row in rows]

    def get_current_state(self, run_id: str) -> LifecycleCurrentState | None:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT * FROM strategy_lifecycle_evidence
                WHERE run_id = ?
                ORDER BY evidence_id DESC
                LIMIT 1
                """,
                (run_id,),
            ).fetchone()
        if row is None:
            return None
        record = self._row_to_record(dict(row))
        return LifecycleCurrentState(
            run_id=record.run_id,
            strategy_id=record.strategy_id,
            version_id=record.version_id,
            action=record.action,
            status=record.status,
            latest_evidence_id=record.evidence_id,
            updated_at=record.created_at,
        )

    def _decision_to_snapshot(self, decision: LifecycleDecision) -> dict[str, Any]:
        return {
            "run_id": decision.run_id,
            "action": decision.action.value,
            "status": decision.status.value,
            "reasons": list(decision.reasons),
            "gates": [
                {
                    "gate_name": gate.gate_name,
                    "status": gate.status.value,
                    "reason": gate.reason,
                    "observed": gate.observed,
                    "threshold": gate.threshold,
                }
                for gate in decision.gates
            ],
            "regime_compatibility": {
                "status": decision.regime_compatibility.status.value,
                "compatible_regimes": list(decision.regime_compatibility.compatible_regimes),
                "incompatible_regimes": list(decision.regime_compatibility.incompatible_regimes),
                "coverage_bp": decision.regime_compatibility.coverage_bp,
                "warnings": list(decision.regime_compatibility.warnings),
            },
        }

    def _row_to_record(self, row: dict[str, Any]) -> LifecycleEvidenceRecord:
        return LifecycleEvidenceRecord(
            evidence_id=int(row["evidence_id"]),
            run_id=str(row["run_id"]),
            strategy_id=str(row["strategy_id"]),
            version_id=str(row["version_id"]),
            action=str(row["action"]),
            status=LifecycleEvidenceStatus(str(row["status"])),
            reason=str(row["reason"]),
            decision_snapshot=json.loads(str(row["decision_snapshot_json"] or "{}")),
            created_at=str(row["created_at"]),
        )


class LifecycleEvidenceGovernanceService:
    """Record demote / retire lifecycle proposals from committed registry runs."""

    def __init__(
        self,
        *,
        research_repository: Any,
        evidence_repository: LifecycleEvidenceRepository,
        lifecycle_service: StrategyLifecycleService | None = None,
    ) -> None:
        self.research_repository = research_repository
        self.evidence_repository = evidence_repository
        self.lifecycle_service = lifecycle_service or StrategyLifecycleService()

    def record_review_evidence(self) -> list[LifecycleEvidenceRecord]:
        candidates: list[tuple[int, ResearchRunMetadataDTO, LifecycleDecision]] = []
        priority = {
            LifecycleAction.RETIRE: 0,
            LifecycleAction.DEMOTE: 1,
            LifecycleAction.HOLD: 2,
            LifecycleAction.PROMOTE: 3,
        }
        for run in self.research_repository.list_metadata(include_archived=False):
            decision = self.lifecycle_service.evaluate_run(run)
            if decision.action not in {LifecycleAction.DEMOTE, LifecycleAction.RETIRE}:
                continue
            candidates.append((priority[decision.action], run, decision))

        records: list[LifecycleEvidenceRecord] = []
        for _priority, run, decision in sorted(
            candidates,
            key=lambda item: (item[0], item[1].run_id),
        ):
            records.append(
                self.evidence_repository.record_decision(
                    run=run,
                    status=LifecycleEvidenceStatus.PROPOSED,
                    reason="lifecycle review proposal",
                    decision=decision,
                )
            )
        return records
