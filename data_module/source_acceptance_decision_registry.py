"""Append-only source acceptance decision registry with evidence-gated applying states."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from typing import Any


@dataclass(frozen=True)
class SourceAcceptanceDecisionRevision:
    source_id: str
    decision_revision_id: str
    parent_revision_id: str | None
    status: str
    allowed_use_cases: tuple[str, ...]
    blockers: tuple[str, ...]
    license_evidence_ids: tuple[str, ...]
    quality_evidence_ids: tuple[str, ...]
    pit_evidence_ids: tuple[str, ...]
    owner_role: str
    reviewer_role: str
    decided_at: str
    rollback_reference: str

    @property
    def content_hash(self) -> str:
        canonical = json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return f"sha256:{sha256(canonical.encode('utf-8')).hexdigest()}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "source-acceptance-decision-revision.v1",
            "source_id": self.source_id,
            "decision_revision_id": self.decision_revision_id,
            "parent_revision_id": self.parent_revision_id,
            "status": self.status,
            "allowed_use_cases": list(self.allowed_use_cases),
            "blockers": list(self.blockers),
            "license_evidence_ids": list(self.license_evidence_ids),
            "quality_evidence_ids": list(self.quality_evidence_ids),
            "pit_evidence_ids": list(self.pit_evidence_ids),
            "owner_role": self.owner_role,
            "reviewer_role": self.reviewer_role,
            "decided_at": self.decided_at,
            "rollback_reference": self.rollback_reference,
        }


class SourceAcceptanceDecisionRegistry:
    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path
        self._initialize()

    def append(self, revision: SourceAcceptanceDecisionRevision) -> SourceAcceptanceDecisionRevision:
        _validate_revision(revision)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM source_acceptance_decisions WHERE content_hash = ?",
                (revision.content_hash,),
            ).fetchone()
            if row is not None:
                return _from_payload(row["payload"])
            self._validate_parent_lineage(connection, revision)
            try:
                connection.execute(
                    "INSERT INTO source_acceptance_decisions "
                    "(source_id, revision_id, content_hash, payload) VALUES (?, ?, ?, ?)",
                    (
                        revision.source_id,
                        revision.decision_revision_id,
                        revision.content_hash,
                        json.dumps(revision.to_dict(), ensure_ascii=False, sort_keys=True),
                    ),
                )
            except sqlite3.IntegrityError as error:
                raise ValueError("decision_revision_id already exists with different content") from error
        return revision

    def append_rollback(
        self,
        *,
        source_id: str,
        decision_revision_id: str,
        status: str,
        reason: str,
        reviewer_role: str,
        decided_at: str,
        rollback_reference: str,
    ) -> SourceAcceptanceDecisionRevision:
        if status not in {"deferred", "rejected", "disabled"}:
            raise ValueError("rollback status must be deferred, rejected, or disabled")
        return self.append(
            SourceAcceptanceDecisionRevision(
                source_id=source_id,
                decision_revision_id=decision_revision_id,
                parent_revision_id=self._require_current_revision_id(source_id),
                status=status,
                allowed_use_cases=(),
                blockers=("rollback_applied", reason),
                license_evidence_ids=(),
                quality_evidence_ids=(),
                pit_evidence_ids=(),
                owner_role="Data Governance Owner",
                reviewer_role=reviewer_role,
                decided_at=decided_at,
                rollback_reference=rollback_reference,
            )
        )

    def list_revisions(self, source_id: str) -> tuple[SourceAcceptanceDecisionRevision, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload FROM source_acceptance_decisions WHERE source_id = ? ORDER BY sequence",
                (source_id,),
            ).fetchall()
        return tuple(_from_payload(row["payload"]) for row in rows)

    def current(self, source_id: str) -> SourceAcceptanceDecisionRevision | None:
        revisions = self.list_revisions(source_id)
        return revisions[-1] if revisions else None

    def _initialize(self) -> None:
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS source_acceptance_decisions ("
                "sequence INTEGER PRIMARY KEY AUTOINCREMENT, "
                "source_id TEXT NOT NULL, "
                "revision_id TEXT NOT NULL, "
                "content_hash TEXT NOT NULL UNIQUE, "
                "payload TEXT NOT NULL, "
                "UNIQUE(source_id, revision_id))"
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _validate_parent_lineage(
        self, connection: sqlite3.Connection, revision: SourceAcceptanceDecisionRevision
    ) -> None:
        if revision.parent_revision_id is None:
            existing = connection.execute(
                "SELECT 1 FROM source_acceptance_decisions WHERE source_id = ? LIMIT 1",
                (revision.source_id,),
            ).fetchone()
            if existing is not None:
                raise ValueError("initial revision cannot follow an existing revision")
            return
        parent = connection.execute(
            "SELECT 1 FROM source_acceptance_decisions WHERE source_id = ? AND revision_id = ?",
            (revision.source_id, revision.parent_revision_id),
        ).fetchone()
        if parent is None:
            raise ValueError("parent revision must exist for the same source")
        latest = connection.execute(
            "SELECT revision_id FROM source_acceptance_decisions "
            "WHERE source_id = ? ORDER BY sequence DESC LIMIT 1",
            (revision.source_id,),
        ).fetchone()
        if latest is None or latest["revision_id"] != revision.parent_revision_id:
            raise ValueError("stale parent revision cannot create a fork")

    def _require_current_revision_id(self, source_id: str) -> str:
        current = self.current(source_id)
        if current is None:
            raise ValueError("rollback requires an existing parent revision")
        return current.decision_revision_id


def _validate_revision(revision: SourceAcceptanceDecisionRevision) -> None:
    non_applying_statuses = {"deferred", "rejected", "disabled"}
    applying_statuses = {"limited", "accepted"}
    if revision.status not in non_applying_statuses | applying_statuses:
        raise ValueError("unsupported source acceptance decision status")
    if not revision.source_id or not revision.decision_revision_id:
        raise ValueError("source_id and decision_revision_id are required")
    if not revision.owner_role or not revision.reviewer_role:
        raise ValueError("owner_role and reviewer_role are required")
    if not revision.rollback_reference:
        raise ValueError("rollback_reference is required")
    decided_at = datetime.fromisoformat(revision.decided_at.replace("Z", "+00:00"))
    if decided_at.tzinfo is None:
        raise ValueError("decided_at must include a timezone")

    if revision.status in non_applying_statuses:
        if revision.allowed_use_cases:
            raise ValueError("non-applying decisions must not allow downstream use cases")
        return

    if not revision.allowed_use_cases:
        raise ValueError("accepted or limited decisions require explicit allowed_use_cases")
    if revision.blockers:
        raise ValueError("accepted or limited decisions cannot retain blockers")
    if not revision.license_evidence_ids:
        raise ValueError("accepted or limited decisions require license evidence")
    if not revision.quality_evidence_ids:
        raise ValueError("accepted or limited decisions require quality evidence")
    if not revision.pit_evidence_ids:
        raise ValueError("accepted or limited decisions require PIT evidence")
    prohibited_tokens = {
        "formal",
        "production",
        "scoring",
        "advice",
        "portfolio",
        "scheduler",
        "trading",
    }
    if any(
        token in use_case.lower()
        for use_case in revision.allowed_use_cases
        for token in prohibited_tokens
    ):
        raise ValueError(
            "source acceptance registry cannot authorize formal or production use cases"
        )


def _from_payload(payload: str) -> SourceAcceptanceDecisionRevision:
    values: dict[str, Any] = json.loads(payload)
    return SourceAcceptanceDecisionRevision(
        source_id=values["source_id"],
        decision_revision_id=values["decision_revision_id"],
        parent_revision_id=values["parent_revision_id"],
        status=values["status"],
        allowed_use_cases=tuple(values["allowed_use_cases"]),
        blockers=tuple(values["blockers"]),
        license_evidence_ids=tuple(values["license_evidence_ids"]),
        quality_evidence_ids=tuple(values["quality_evidence_ids"]),
        pit_evidence_ids=tuple(values["pit_evidence_ids"]),
        owner_role=values["owner_role"],
        reviewer_role=values["reviewer_role"],
        decided_at=values["decided_at"],
        rollback_reference=values["rollback_reference"],
    )
