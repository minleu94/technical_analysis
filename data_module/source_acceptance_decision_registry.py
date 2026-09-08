"""Append-only source acceptance decision registry with evidence-gated applying states."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from collections.abc import Mapping, Sequence
from typing import Any


DECISION_REVISION_SCHEMA_VERSION = "source-acceptance-decision-revision.v1"
OWNER_REVIEW_DECISION_SCHEMA_VERSION = "source-acceptance-owner-review-decision.v1"
MACHINE_DECISION_ACTOR = "machine:evidence_policy"
MACHINE_DECISION_POLICY_VERSION = "source-acceptance-machine-review.v1"
MACHINE_ALLOWED_USE_CASES = frozenset({"research_shadow", "diagnostics"})
_DECISION_COLLECTION_FIELDS = (
    "allowed_use_cases",
    "blockers",
    "license_evidence_ids",
    "quality_evidence_ids",
    "pit_evidence_ids",
)
_NON_APPLYING_STATUSES = frozenset({"deferred", "rejected", "disabled"})


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
    # 這些欄位是 v1 payload 的附加資訊；human revision 保留歷史預設值，
    # machine revision 必須指出政策與產生它的證據封套，不得虛構 reviewer。
    decision_actor: str = "human"
    decision_policy_version: str = ""
    decision_evidence_hash: str = ""
    decision_reason: str = ""

    @property
    def content_hash(self) -> str:
        canonical = json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return f"sha256:{sha256(canonical.encode('utf-8')).hexdigest()}"

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": DECISION_REVISION_SCHEMA_VERSION,
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
        # 保持歷史 human payload 的內容與 hash 不變。machine metadata 只會
        # 出現在明確標記為 machine actor 的 revision，舊資料因此仍不可變。
        if self.decision_actor != "human":
            payload.update(
                {
                    "decision_actor": self.decision_actor,
                    "decision_policy_version": self.decision_policy_version,
                    "decision_evidence_hash": self.decision_evidence_hash,
                    "decision_reason": self.decision_reason,
                }
            )
        return payload


def parse_source_acceptance_decision_revision(
    payload: Mapping[str, Any],
    *,
    allow_owner_review_deferred: bool = True,
) -> SourceAcceptanceDecisionRevision:
    """Decode one decision artifact without opening or mutating a registry.

    The internal revision schema is the canonical registry format.  An external
    owner-review package may be read only when it explicitly remains
    ``deferred``/``rejected``/``disabled``; its richer evidence and attestation
    fields are intentionally not inferred into registry evidence IDs.  Applying
    ``accepted``/``limited`` decisions therefore still requires the canonical
    revision schema and the intake/evidence binding checks in the append CLI.
    """

    if not isinstance(payload, Mapping):
        raise TypeError("decision JSON must be an object")
    raw = dict(payload)
    schema_version = raw.pop("schema_version", DECISION_REVISION_SCHEMA_VERSION)
    if schema_version == OWNER_REVIEW_DECISION_SCHEMA_VERSION:
        if not allow_owner_review_deferred:
            raise ValueError(
                f"unsupported decision schema: {OWNER_REVIEW_DECISION_SCHEMA_VERSION}"
            )
        status = raw.get("status")
        if status not in _NON_APPLYING_STATUSES:
            raise ValueError(
                "owner-review decision schema may only be imported as deferred, rejected, or disabled"
            )
        active_blockers = _string_sequence(raw.get("active_blockers", ()), "active_blockers")
        explicit_blockers = _string_sequence(raw.get("blockers", ()), "blockers")
        blockers = tuple(dict.fromkeys((*explicit_blockers, *active_blockers)))
        decided_at = raw.get("decided_at") or raw.get("decision_timestamp")
        raw = {
            "source_id": raw.get("source_id"),
            "decision_revision_id": raw.get("decision_revision_id"),
            "parent_revision_id": raw.get("parent_revision_id"),
            "status": status,
            "allowed_use_cases": (),
            "blockers": blockers,
            "license_evidence_ids": (),
            "quality_evidence_ids": (),
            "pit_evidence_ids": (),
            "owner_role": raw.get("owner_role"),
            "reviewer_role": raw.get("reviewer_role"),
            "decided_at": decided_at,
            "rollback_reference": raw.get("rollback_reference"),
        }
    elif schema_version != DECISION_REVISION_SCHEMA_VERSION:
        raise ValueError(f"unsupported decision schema: {schema_version}")
    else:
        for key in _DECISION_COLLECTION_FIELDS:
            raw[key] = _string_sequence(raw.get(key, ()), key)

    try:
        revision = SourceAcceptanceDecisionRevision(**raw)
    except (TypeError, ValueError) as error:
        raise ValueError(f"invalid source acceptance decision: {error}") from error
    validate_source_acceptance_decision_revision(revision)
    return revision


def parse_source_acceptance_decisions(
    payload: Any,
    *,
    allow_owner_review_deferred: bool = True,
) -> tuple[SourceAcceptanceDecisionRevision, ...]:
    """Decode a list, wrapped list, or single decision artifact read-only."""

    if isinstance(payload, Mapping) and "decisions" in payload:
        raw_items = payload.get("decisions")
    elif isinstance(payload, Mapping) and "decision" in payload:
        raw_items = (payload.get("decision"),)
    elif isinstance(payload, Mapping) and "source_id" in payload:
        raw_items = (payload,)
    else:
        raw_items = payload
    if isinstance(raw_items, (str, bytes)) or not isinstance(raw_items, Sequence):
        raise ValueError("decision JSON must be a list or an object with decisions")
    return tuple(
        parse_source_acceptance_decision_revision(
            item,
            allow_owner_review_deferred=allow_owner_review_deferred,
        )
        for item in raw_items
    )


def _string_sequence(value: Any, field_name: str) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise TypeError(f"decision field {field_name} must be an array of strings")
    values = tuple(value)
    if any(not isinstance(item, str) for item in values):
        raise TypeError(f"decision field {field_name} must be an array of strings")
    return values


class SourceAcceptanceDecisionRegistry:
    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path
        self._initialize()

    def append(self, revision: SourceAcceptanceDecisionRevision) -> SourceAcceptanceDecisionRevision:
        validate_source_acceptance_decision_revision(revision)
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


def validate_source_acceptance_decision_revision(
    revision: SourceAcceptanceDecisionRevision,
) -> None:
    """Validate one decision revision without opening or mutating the registry.

    This validator is intentionally usable by read-only projections.  Keeping the
    evidence and prohibited-use-case rules in one place prevents a UI/CLI from
    presenting a malformed ``accepted`` or ``limited`` payload as a valid
    governance decision.
    """

    if not isinstance(revision, SourceAcceptanceDecisionRevision):
        raise TypeError("revision must be a SourceAcceptanceDecisionRevision")
    non_applying_statuses = {"deferred", "rejected", "disabled"}
    applying_statuses = {"limited", "accepted"}
    if revision.status not in non_applying_statuses | applying_statuses:
        raise ValueError("unsupported source acceptance decision status")
    if (
        not isinstance(revision.source_id, str)
        or not revision.source_id.strip()
        or not isinstance(revision.decision_revision_id, str)
        or not revision.decision_revision_id.strip()
    ):
        raise ValueError("source_id and decision_revision_id are required")
    if not isinstance(revision.decision_actor, str) or not revision.decision_actor.strip():
        raise ValueError("decision_actor is required")
    if not isinstance(revision.decision_policy_version, str):
        raise TypeError("decision_policy_version must be a string")
    if not isinstance(revision.decision_evidence_hash, str):
        raise TypeError("decision_evidence_hash must be a string")
    if not isinstance(revision.decision_reason, str):
        raise TypeError("decision_reason must be a string")
    if revision.decision_actor == "human":
        if (
            not isinstance(revision.owner_role, str)
            or not revision.owner_role.strip()
            or not isinstance(revision.reviewer_role, str)
            or not revision.reviewer_role.strip()
        ):
            raise ValueError("owner_role and reviewer_role are required")
        if any(
            value.strip()
            for value in (
                revision.decision_policy_version,
                revision.decision_evidence_hash,
                revision.decision_reason,
            )
        ):
            raise ValueError("human decisions must not carry machine evidence metadata")
    elif revision.decision_actor == MACHINE_DECISION_ACTOR:
        if revision.status != "limited":
            raise ValueError("machine evidence decisions must use limited status")
        if revision.owner_role != MACHINE_DECISION_ACTOR:
            raise ValueError("machine evidence owner_role must identify the machine actor")
        if not isinstance(revision.reviewer_role, str):
            raise TypeError("reviewer_role must be a string")
        if revision.reviewer_role.strip():
            raise ValueError("machine evidence decisions must not invent a human reviewer")
        if revision.decision_policy_version != MACHINE_DECISION_POLICY_VERSION:
            raise ValueError("unsupported machine evidence policy version")
        if not _is_sha256_hash(revision.decision_evidence_hash):
            raise ValueError("machine evidence decision hash must be a SHA-256 digest")
        if not revision.decision_reason.strip():
            raise ValueError("machine evidence decision reason is required")
    else:
        raise ValueError(f"unsupported decision actor: {revision.decision_actor}")
    if not isinstance(revision.rollback_reference, str) or not revision.rollback_reference.strip():
        raise ValueError("rollback_reference is required")
    if not isinstance(revision.decided_at, str) or not revision.decided_at.strip():
        raise ValueError("decided_at must be an ISO timestamp")
    try:
        decided_at = datetime.fromisoformat(revision.decided_at.replace("Z", "+00:00"))
    except (TypeError, ValueError) as error:
        raise ValueError("decided_at must be an ISO timestamp") from error
    if decided_at.tzinfo is None:
        raise ValueError("decided_at must include a timezone")

    for field_name in (
        "allowed_use_cases",
        "blockers",
        "license_evidence_ids",
        "quality_evidence_ids",
        "pit_evidence_ids",
    ):
        values = getattr(revision, field_name)
        if isinstance(values, (str, bytes)):
            raise TypeError(f"{field_name} must be a collection of strings")
        try:
            materialized = tuple(values)
        except TypeError as error:
            raise TypeError(f"{field_name} must be a collection of strings") from error
        if any(not isinstance(value, str) or not value.strip() for value in materialized):
            raise ValueError(f"{field_name} must contain non-empty strings")

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
    if revision.decision_actor == MACHINE_DECISION_ACTOR:
        if not set(revision.allowed_use_cases).issubset(MACHINE_ALLOWED_USE_CASES):
            raise ValueError(
                "machine evidence decisions are limited to research_shadow or diagnostics"
            )


def _is_sha256_hash(value: str) -> bool:
    if not isinstance(value, str):
        return False
    digest = value.removeprefix("sha256:")
    if len(digest) != 64:
        return False
    try:
        int(digest, 16)
    except ValueError:
        return False
    return True


# 保留為舊模組內 caller 使用的私有相容別名。
_validate_revision = validate_source_acceptance_decision_revision


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
        decision_actor=values.get("decision_actor", "human"),
        decision_policy_version=values.get("decision_policy_version", ""),
        decision_evidence_hash=values.get("decision_evidence_hash", ""),
        decision_reason=values.get("decision_reason", ""),
    )
