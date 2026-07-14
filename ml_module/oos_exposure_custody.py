"""2025 OOS exposure/custody 的純 metadata 稽核契約。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from hashlib import sha256
import json
from typing import Literal


AuditStatus = Literal[
    "seen_oos",
    "exposed_no_design_influence_declared",
    "custody_verified_unopened",
    "indeterminate",
]
AccessState = Literal["unopened", "exposed", "unknown"]

_INFLUENCE_DIMENSIONS = frozenset(
    {
        "feature",
        "label",
        "universe",
        "rule",
        "threshold",
        "model_family",
        "hyperparameter",
        "calibration",
        "blend",
        "sample_filter",
        "success_criteria",
    }
)


@dataclass(frozen=True)
class AuditEvidenceMetadata:
    evidence_id: str
    sha256: str
    recorded_at: str
    access_state: AccessState


@dataclass(frozen=True)
class SignedCustodyDeclaration:
    declaration_id: str
    reviewer_identity: str
    signed_at: str
    declares_no_design_influence: bool


@dataclass(frozen=True)
class OOSExposureCustodyRequest:
    generation_manifest: AuditEvidenceMetadata | None
    access_inventory: AuditEvidenceMetadata | None
    signed_declaration: SignedCustodyDeclaration | None
    influence_dimensions: tuple[str, ...]


@dataclass(frozen=True)
class OOSExposureCustodyReport:
    status: AuditStatus
    blockers: tuple[str, ...]
    influence_dimensions: tuple[str, ...]
    generation_manifest: AuditEvidenceMetadata | None
    access_inventory: AuditEvidenceMetadata | None
    signed_declaration: SignedCustodyDeclaration | None
    formal_oos_allowed: bool = field(default=False, init=False)
    production_blend_alpha_bp: int = field(default=0, init=False)
    retrospective_only: bool = False
    candidate_for_later_formal_verification: bool = False

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    def canonical_json(self) -> str:
        return json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    def canonical_sha256(self) -> str:
        return sha256(self.canonical_json().encode("utf-8")).hexdigest()


class OOSExposureCustodyAuditor:
    """只依 metadata 與具名聲明，採 fail-closed 產生 custody 判定。"""

    def audit(self, request: OOSExposureCustodyRequest) -> OOSExposureCustodyReport:
        blockers = _request_blockers(request)
        dimensions = tuple(sorted(set(request.influence_dimensions)))
        valid_dimensions = tuple(
            dimension
            for dimension in dimensions
            if dimension in _INFLUENCE_DIMENSIONS
        )
        if blockers:
            return _report("indeterminate", blockers, valid_dimensions, request)
        if valid_dimensions:
            return _report(
                "seen_oos",
                (),
                valid_dimensions,
                request,
            )

        generation_manifest = request.generation_manifest
        access_inventory = request.access_inventory
        if generation_manifest is None or access_inventory is None:
            return _report("indeterminate", ("machine_evidence_missing",), (), request)
        access_states = (
            generation_manifest.access_state,
            access_inventory.access_state,
        )
        if "exposed" in access_states:
            return _report(
                "exposed_no_design_influence_declared",
                (),
                (),
                request,
                retrospective_only=True,
            )
        if access_states == ("unopened", "unopened"):
            return _report(
                "custody_verified_unopened",
                (),
                (),
                request,
                candidate_for_later_formal_verification=True,
            )
        return _report("indeterminate", ("machine_access_state_unknown",), (), request)


def _request_blockers(request: OOSExposureCustodyRequest) -> tuple[str, ...]:
    blockers: list[str] = []
    blockers.extend(_metadata_blockers("generation_manifest", request.generation_manifest))
    blockers.extend(_metadata_blockers("access_inventory", request.access_inventory))
    blockers.extend(_declaration_blockers(request.signed_declaration))
    invalid_dimensions = sorted(
        set(request.influence_dimensions) - _INFLUENCE_DIMENSIONS
    )
    if invalid_dimensions:
        blockers.append("influence_dimension_invalid")
    return tuple(blockers)


def _metadata_blockers(
    field_name: str,
    evidence: AuditEvidenceMetadata | None,
) -> list[str]:
    if evidence is None:
        return [f"{field_name}_missing"]
    blockers: list[str] = []
    if not evidence.evidence_id:
        blockers.append(f"{field_name}_identity_missing")
    if not _is_sha256(evidence.sha256):
        blockers.append(f"{field_name}_hash_invalid")
    if not _is_timestamp(evidence.recorded_at):
        blockers.append(f"{field_name}_timestamp_invalid")
    if evidence.access_state not in {"unopened", "exposed", "unknown"}:
        blockers.append(f"{field_name}_access_state_invalid")
    return blockers


def _declaration_blockers(
    declaration: SignedCustodyDeclaration | None,
) -> list[str]:
    if declaration is None:
        return ["signed_declaration_missing"]
    blockers: list[str] = []
    if not declaration.declaration_id:
        blockers.append("signed_declaration_identity_missing")
    if not declaration.reviewer_identity:
        blockers.append("reviewer_identity_missing")
    if not _is_timestamp(declaration.signed_at):
        blockers.append("signed_declaration_timestamp_invalid")
    if not declaration.declares_no_design_influence:
        blockers.append("signed_declaration_no_influence_not_attested")
    return blockers


def _report(
    status: AuditStatus,
    blockers: tuple[str, ...],
    influence_dimensions: tuple[str, ...],
    request: OOSExposureCustodyRequest,
    *,
    retrospective_only: bool = False,
    candidate_for_later_formal_verification: bool = False,
) -> OOSExposureCustodyReport:
    return OOSExposureCustodyReport(
        status=status,
        blockers=blockers,
        influence_dimensions=influence_dimensions,
        generation_manifest=request.generation_manifest,
        access_inventory=request.access_inventory,
        signed_declaration=request.signed_declaration,
        retrospective_only=retrospective_only,
        candidate_for_later_formal_verification=candidate_for_later_formal_verification,
    )


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def _is_timestamp(value: str) -> bool:
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True
