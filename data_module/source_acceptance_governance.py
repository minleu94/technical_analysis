"""Fail-closed, non-applying governance for EV2 source dossiers."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Any, Iterable, Mapping

from data_module.source_acceptance_decision_registry import SourceAcceptanceDecisionRevision


BROKER_REVALIDATION_SOURCE_ID = "broker_branch.revalidation"


@dataclass(frozen=True)
class SourceAcceptanceDossier:
    """A review artifact only; it never authorizes downstream source use."""

    source_id: str
    source_owner_role: str
    license_owner_role: str
    license_status: str
    license_scope: str
    redistribution_policy: str
    source_status: str
    publication_time_policy: str
    timezone: str
    available_date_policy: str
    revision_policy: str
    pit_coverage_window: str
    coverage_numerator: int
    coverage_denominator: int
    missing_policy: str
    row_conservation_counts: Mapping[str, int]
    quarantine_policy: str
    quality_thresholds: Mapping[str, Any]
    downstream_use_cases: tuple[str, ...]
    disable_conditions: tuple[str, ...]
    rollback_reference: str
    evidence_artifact_ids: tuple[str, ...]
    downstream_eligibility: str = "none"
    reviewer_role: str = ""
    decision_timestamp: str = ""
    decision_revision_id: str = ""

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "SourceAcceptanceDossier":
        values = dict(payload)
        schema_version = values.pop("schema_version", "source-acceptance-dossier.v1")
        if schema_version != "source-acceptance-dossier.v1":
            raise ValueError(f"unsupported source acceptance dossier schema: {schema_version}")
        values["downstream_use_cases"] = tuple(values.get("downstream_use_cases", ()))
        values["disable_conditions"] = tuple(values.get("disable_conditions", ()))
        values["evidence_artifact_ids"] = tuple(values.get("evidence_artifact_ids", ()))
        values["row_conservation_counts"] = dict(values.get("row_conservation_counts", {}))
        values["quality_thresholds"] = dict(values.get("quality_thresholds", {}))
        return cls(**values)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "source-acceptance-dossier.v1",
            "source_id": self.source_id,
            "source_owner_role": self.source_owner_role,
            "license_owner_role": self.license_owner_role,
            "license_status": self.license_status,
            "license_scope": self.license_scope,
            "redistribution_policy": self.redistribution_policy,
            "source_status": self.source_status,
            "publication_time_policy": self.publication_time_policy,
            "timezone": self.timezone,
            "available_date_policy": self.available_date_policy,
            "revision_policy": self.revision_policy,
            "pit_coverage_window": self.pit_coverage_window,
            "coverage_numerator": self.coverage_numerator,
            "coverage_denominator": self.coverage_denominator,
            "missing_policy": self.missing_policy,
            "row_conservation_counts": dict(self.row_conservation_counts),
            "quarantine_policy": self.quarantine_policy,
            "quality_thresholds": dict(self.quality_thresholds),
            "downstream_use_cases": list(self.downstream_use_cases),
            "downstream_eligibility": self.downstream_eligibility,
            "disable_conditions": list(self.disable_conditions),
            "rollback_reference": self.rollback_reference,
            "evidence_artifact_ids": list(self.evidence_artifact_ids),
            "reviewer_role": self.reviewer_role,
            "decision_timestamp": self.decision_timestamp,
            "decision_revision_id": self.decision_revision_id,
        }

    @property
    def content_hash(self) -> str:
        canonical = json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return f"sha256:{sha256(canonical.encode('utf-8')).hexdigest()}"


@dataclass(frozen=True)
class SourceAcceptanceProjection:
    p0_source_count: int
    p0_source_ids: tuple[str, ...]
    broker_lane_source_id: str
    decisions: tuple[SourceAcceptanceDecisionRevision, ...]


class SourceAcceptanceGovernance:
    """Projects only deferred eligibility until a separately authorized review."""

    def evaluate(self, dossier: SourceAcceptanceDossier) -> SourceAcceptanceDecisionRevision:
        blockers = _required_blockers(dossier)
        blockers.append("source_acceptance_not_authorized")
        revision_id = dossier.decision_revision_id or (
            f"candidate:{dossier.source_id}:{dossier.content_hash.removeprefix('sha256:')[:16]}"
        )
        return SourceAcceptanceDecisionRevision(
            source_id=dossier.source_id,
            decision_revision_id=revision_id,
            parent_revision_id=None,
            status="deferred",
            allowed_use_cases=(),
            blockers=tuple(sorted(set(blockers))),
            license_evidence_ids=_evidence_ids(dossier, "license:"),
            quality_evidence_ids=_evidence_ids(dossier, "quality:"),
            pit_evidence_ids=_evidence_ids(dossier, "pit:"),
            owner_role=dossier.source_owner_role,
            reviewer_role=dossier.reviewer_role,
            decided_at=dossier.decision_timestamp,
            rollback_reference=dossier.rollback_reference,
        )

    def project(
        self, contracts: Iterable[Any], decisions: Iterable[SourceAcceptanceDecisionRevision]
    ) -> SourceAcceptanceProjection:
        p0_source_ids = tuple(contract.source_id for contract in contracts)
        if len(p0_source_ids) != 13 or len(set(p0_source_ids)) != 13:
            raise ValueError("P0 source denominator must remain exactly thirteen")
        if BROKER_REVALIDATION_SOURCE_ID in p0_source_ids:
            raise ValueError("broker revalidation must remain outside the P0 denominator")
        return SourceAcceptanceProjection(
            p0_source_count=len(p0_source_ids),
            p0_source_ids=p0_source_ids,
            broker_lane_source_id=BROKER_REVALIDATION_SOURCE_ID,
            decisions=tuple(decisions),
        )


def _required_blockers(dossier: SourceAcceptanceDossier) -> list[str]:
    blockers: list[str] = []
    if not dossier.source_owner_role.strip():
        blockers.append("missing_source_owner")
    if not dossier.license_owner_role.strip():
        blockers.append("missing_license_owner")
    if dossier.license_status.strip().lower() != "approved":
        blockers.append("license_not_accepted")
    if not _evidenced(dossier.publication_time_policy):
        blockers.append("missing_publication_time_policy")
    if not _evidenced(dossier.available_date_policy):
        blockers.append("missing_available_date_policy")
    if not _evidenced(dossier.revision_policy):
        blockers.append("missing_revision_policy")
    if not _evidenced(dossier.pit_coverage_window):
        blockers.append("missing_pit_coverage")
    if not dossier.row_conservation_counts:
        blockers.append("missing_row_conservation")
    if not _evidenced(dossier.quarantine_policy):
        blockers.append("missing_quarantine_policy")
    if not dossier.quality_thresholds:
        blockers.append("missing_quality_thresholds")
    if not dossier.downstream_eligibility.strip():
        blockers.append("missing_downstream_eligibility")
    if not dossier.rollback_reference.strip():
        blockers.append("missing_rollback_reference")
    return blockers


def _evidenced(value: str) -> bool:
    return value.strip().lower() not in {"", "unverified", "not_evidenced", "not_decided", "requires_review"}


def _evidence_ids(dossier: SourceAcceptanceDossier, prefix: str) -> tuple[str, ...]:
    return tuple(item for item in dossier.evidence_artifact_ids if item.startswith(prefix))
