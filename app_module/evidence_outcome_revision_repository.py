"""Append-only SQLite sidecar for external-evidence outcome revisions."""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3

from app_module.external_evidence_contracts import EvidenceOutcomeRevision, ExternalEvidenceDecisionSnapshot


class EvidenceOutcomeRevisionRepository:
    """Stores formal revisions without modifying any legacy evidence read model."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def append(self, revision: EvidenceOutcomeRevision) -> EvidenceOutcomeRevision:
        existing = self.get(revision.revision_id)
        if existing is not None:
            if existing.content_hash == revision.content_hash and existing.to_dict() == revision.to_dict():
                return existing
            raise ValueError("revision_id already exists with different payload")
        snapshot = self.get_snapshot(revision.snapshot_id)
        if snapshot is None or snapshot.capture_kind != "manual_observed":
            raise ValueError("revision requires a persisted manual_observed snapshot")
        if revision.parent_revision_id is not None:
            parent = self.get(revision.parent_revision_id)
            if parent is None:
                raise ValueError("parent_revision_id does not exist")
            if parent.snapshot_id != revision.snapshot_id:
                raise ValueError("parent_revision_id belongs to another snapshot")
        payload = revision.to_dict()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO external_evidence_outcome_revisions (
                    revision_id, parent_revision_id, snapshot_id, window_trading_days,
                    status, content_hash, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    revision.revision_id,
                    revision.parent_revision_id,
                    revision.snapshot_id,
                    revision.window_trading_days,
                    revision.status,
                    revision.content_hash,
                    json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                ),
            )
        return revision

    def append_snapshot(
        self, snapshot: ExternalEvidenceDecisionSnapshot
    ) -> ExternalEvidenceDecisionSnapshot:
        """Insert one observed decision artifact, never an inferred or replayed day."""
        snapshot_id = snapshot.snapshot_id
        verified_snapshot = ExternalEvidenceDecisionSnapshot.create(
            decision_timestamp=snapshot.decision_timestamp,
            data_as_of_date=snapshot.data_as_of_date,
            max_available_timestamp=snapshot.max_available_timestamp,
            source_versions=snapshot.source_versions,
            strategy_version=snapshot.strategy_version,
            policy_version=snapshot.policy_version,
            rule_champion_snapshot_id=snapshot.rule_champion_snapshot_id,
            universe_id=snapshot.universe_id,
            universe_hash=snapshot.universe_hash,
            symbol=snapshot.symbol,
            score_bp=snapshot.score_bp,
            score_status=snapshot.score_status,
            rank=snapshot.rank,
            action_or_prompt=snapshot.action_or_prompt,
            why=snapshot.why,
            why_not=snapshot.why_not,
            risk_reasons=snapshot.risk_reasons,
            market_regime=snapshot.market_regime,
            liquidity_state=snapshot.liquidity_state,
            restriction_state=snapshot.restriction_state,
            evidence_tier=snapshot.evidence_tier,
            missing_sources=snapshot.missing_sources,
            degraded_reasons=snapshot.degraded_reasons,
            parent_artifact_ids=snapshot.parent_artifact_ids,
            capture_kind=snapshot.capture_kind,
        )
        if verified_snapshot.snapshot_id != snapshot_id:
            raise ValueError("snapshot_id does not match a verifiable manual_observed payload")
        existing = self.get_snapshot(verified_snapshot.snapshot_id)
        if existing is not None:
            if existing.to_dict() == verified_snapshot.to_dict():
                return existing
            raise ValueError("snapshot_id already exists with different payload")
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO external_evidence_decision_snapshots (snapshot_id, decision_timestamp, payload_json) VALUES (?, ?, ?)",
                (
                    verified_snapshot.snapshot_id,
                    verified_snapshot.decision_timestamp,
                    json.dumps(verified_snapshot.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                ),
            )
        return verified_snapshot

    def get_snapshot(self, snapshot_id: str) -> ExternalEvidenceDecisionSnapshot | None:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT payload_json FROM external_evidence_decision_snapshots WHERE snapshot_id = ?", (snapshot_id,)
            ).fetchone()
        if row is None:
            return None
        payload = json.loads(row[0])
        snapshot_id = payload.pop("snapshot_id")
        snapshot = ExternalEvidenceDecisionSnapshot.create(**payload)
        if snapshot.snapshot_id != snapshot_id:
            raise ValueError("stored snapshot identity does not match its immutable payload")
        return snapshot

    def get(self, revision_id: str) -> EvidenceOutcomeRevision | None:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT payload_json FROM external_evidence_outcome_revisions WHERE revision_id = ?", (revision_id,)
            ).fetchone()
        return self._from_payload(row[0]) if row is not None else None

    def list_revisions(self, snapshot_id: str) -> tuple[EvidenceOutcomeRevision, ...]:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT payload_json FROM external_evidence_outcome_revisions WHERE snapshot_id = ? ORDER BY sequence_no ASC",
                (snapshot_id,),
            ).fetchall()
        return tuple(self._from_payload(row[0]) for row in rows)

    def current(self, snapshot_id: str) -> EvidenceOutcomeRevision:
        revisions = self.list_revisions(snapshot_id)
        if not revisions:
            raise LookupError(f"no outcome revisions for snapshot: {snapshot_id}")
        parent_ids = {item.parent_revision_id for item in revisions if item.parent_revision_id is not None}
        leaves = tuple(item for item in revisions if item.revision_id not in parent_ids)
        if len(leaves) != 1:
            raise ValueError("outcome revision history does not have one current revision")
        return leaves[0]

    def _ensure_schema(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS external_evidence_decision_snapshots (
                    sequence_no INTEGER PRIMARY KEY AUTOINCREMENT,
                    snapshot_id TEXT NOT NULL UNIQUE,
                    decision_timestamp TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS external_evidence_outcome_revisions (
                    sequence_no INTEGER PRIMARY KEY AUTOINCREMENT,
                    revision_id TEXT NOT NULL UNIQUE,
                    parent_revision_id TEXT NULL,
                    snapshot_id TEXT NOT NULL,
                    window_trading_days INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_external_evidence_revisions_snapshot ON external_evidence_outcome_revisions(snapshot_id, sequence_no)"
            )

    @staticmethod
    def _from_payload(payload_json: str) -> EvidenceOutcomeRevision:
        payload = json.loads(payload_json)
        return EvidenceOutcomeRevision(**payload)
