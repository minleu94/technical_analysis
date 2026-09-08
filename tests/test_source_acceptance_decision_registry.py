from pathlib import Path
from hashlib import sha256
import json

import pytest

from data_module.source_acceptance_decision_registry import (
    OWNER_REVIEW_DECISION_SCHEMA_VERSION,
    SourceAcceptanceDecisionRegistry,
    SourceAcceptanceDecisionRevision,
    parse_source_acceptance_decisions,
    parse_source_acceptance_decision_revision,
)


def _decision(
    revision_id: str = "rev-1",
    parent_revision_id: str | None = None,
    source_id: str = "institutional_flows",
) -> SourceAcceptanceDecisionRevision:
    return SourceAcceptanceDecisionRevision(
        source_id=source_id,
        decision_revision_id=revision_id,
        parent_revision_id=parent_revision_id,
        status="deferred",
        allowed_use_cases=(),
        blockers=("missing_license",),
        license_evidence_ids=(),
        quality_evidence_ids=(),
        pit_evidence_ids=(),
        owner_role="Data Source Owner",
        reviewer_role="Data Governance Owner",
        decided_at="2026-07-13T09:00:00+08:00",
        rollback_reference="decision:future-disable-revision",
    )


def test_append_is_hash_idempotent_and_preserves_history(tmp_path: Path) -> None:
    registry = SourceAcceptanceDecisionRegistry(tmp_path / "governance.sqlite")
    first = registry.append(_decision())
    duplicate = registry.append(_decision())
    second = registry.append(_decision("rev-2", parent_revision_id="rev-1"))

    assert duplicate == first
    assert registry.list_revisions("institutional_flows") == (first, second)
    assert registry.current("institutional_flows") == second


def test_legacy_human_payload_hash_remains_immutable_after_machine_metadata_addition() -> None:
    payload = {
        "schema_version": "source-acceptance-decision-revision.v1",
        "source_id": "institutional_flows",
        "decision_revision_id": "rev-legacy",
        "parent_revision_id": None,
        "status": "deferred",
        "allowed_use_cases": [],
        "blockers": ["missing_license"],
        "license_evidence_ids": [],
        "quality_evidence_ids": [],
        "pit_evidence_ids": [],
        "owner_role": "Data Source Owner",
        "reviewer_role": "Data Governance Owner",
        "decided_at": "2026-07-13T09:00:00+08:00",
        "rollback_reference": "decision:future-disable-revision",
    }
    legacy_canonical = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    expected_hash = f"sha256:{sha256(legacy_canonical.encode('utf-8')).hexdigest()}"

    revision = parse_source_acceptance_decision_revision(payload)

    assert revision.content_hash == expected_hash
    assert revision.to_dict() == payload


def test_append_requires_an_initial_revision_then_same_source_parent_lineage(tmp_path: Path) -> None:
    registry = SourceAcceptanceDecisionRegistry(tmp_path / "governance.sqlite")
    registry.append(_decision())

    with pytest.raises(ValueError, match="parent"):
        registry.append(_decision("rev-2", parent_revision_id="missing"))
    with pytest.raises(ValueError, match="initial"):
        registry.append(_decision("rev-3"))

    other_source_parent = _decision(
        "rev-2", parent_revision_id="rev-1", source_id="credit_transactions"
    )
    with pytest.raises(ValueError, match="parent"):
        registry.append(other_source_parent)


def test_append_rejects_a_stale_parent_fork(tmp_path: Path) -> None:
    registry = SourceAcceptanceDecisionRegistry(tmp_path / "governance.sqlite")
    registry.append(_decision())
    registry.append(_decision("rev-2", parent_revision_id="rev-1"))

    with pytest.raises(ValueError, match="stale parent"):
        registry.append(_decision("rev-3", parent_revision_id="rev-1"))


def test_registry_accepts_evidence_complete_limited_source_decision(tmp_path: Path) -> None:
    registry = SourceAcceptanceDecisionRegistry(tmp_path / "governance.sqlite")
    limited = SourceAcceptanceDecisionRevision(
        source_id="institutional_flows",
        decision_revision_id="rev-limited",
        parent_revision_id=None,
        status="limited",
        allowed_use_cases=("research",),
        blockers=(),
        license_evidence_ids=("license:accepted",),
        quality_evidence_ids=("quality:accepted",),
        pit_evidence_ids=("pit:accepted",),
        owner_role="Data Source Owner",
        reviewer_role="Data Governance Owner",
        decided_at="2026-07-13T09:00:00+08:00",
        rollback_reference="decision:future-disable-revision",
    )

    assert registry.append(limited) == limited
    assert registry.current("institutional_flows") == limited


def test_registry_rejects_incomplete_applying_source_decision(tmp_path: Path) -> None:
    registry = SourceAcceptanceDecisionRegistry(tmp_path / "governance.sqlite")
    incomplete = SourceAcceptanceDecisionRevision(
        source_id="institutional_flows",
        decision_revision_id="rev-accepted",
        parent_revision_id=None,
        status="accepted",
        allowed_use_cases=("research",),
        blockers=(),
        license_evidence_ids=(),
        quality_evidence_ids=("quality:accepted",),
        pit_evidence_ids=("pit:accepted",),
        owner_role="Data Source Owner",
        reviewer_role="Data Governance Owner",
        decided_at="2026-07-13T09:00:00+08:00",
        rollback_reference="decision:future-disable-revision",
    )

    with pytest.raises(ValueError, match="license evidence"):
        registry.append(incomplete)


def test_registry_rejects_formal_or_production_use_case(tmp_path: Path) -> None:
    registry = SourceAcceptanceDecisionRegistry(tmp_path / "governance.sqlite")
    prohibited = SourceAcceptanceDecisionRevision(
        source_id="institutional_flows",
        decision_revision_id="rev-formal",
        parent_revision_id=None,
        status="limited",
        allowed_use_cases=("formal_scoring",),
        blockers=(),
        license_evidence_ids=("license:accepted",),
        quality_evidence_ids=("quality:accepted",),
        pit_evidence_ids=("pit:accepted",),
        owner_role="Data Source Owner",
        reviewer_role="Data Governance Owner",
        decided_at="2026-07-13T09:00:00+08:00",
        rollback_reference="decision:future-disable-revision",
    )

    with pytest.raises(ValueError, match="formal or production"):
        registry.append(prohibited)


def test_rollback_appends_a_non_applying_revision_only(tmp_path: Path) -> None:
    registry = SourceAcceptanceDecisionRegistry(tmp_path / "governance.sqlite")
    registry.append(_decision())

    rollback = registry.append_rollback(
        source_id="institutional_flows",
        decision_revision_id="rev-2",
        status="rejected",
        reason="license withdrawn",
        reviewer_role="Data Governance Owner",
        decided_at="2026-07-14T09:00:00+08:00",
        rollback_reference="decision:rev-1",
    )

    assert rollback.status == "rejected"
    assert rollback.allowed_use_cases == ()
    assert registry.current("institutional_flows") == rollback


def test_owner_review_decision_is_normalized_only_as_non_applying() -> None:
    revision = parse_source_acceptance_decision_revision(
        {
            "schema_version": OWNER_REVIEW_DECISION_SCHEMA_VERSION,
            "source_id": "institutional_flows",
            "decision_revision_id": "decision:institutional_flows:20260827-r1",
            "parent_revision_id": None,
            "status": "deferred",
            "owner_role": "archi / Project Owner",
            "reviewer_role": "Data Governance Owner",
            "decided_at": "2026-08-27T12:00:00+08:00",
            "active_blockers": ["source_acceptance_not_authorized"],
            "rollback_reference": "owner-policy:disable",
            "evidence": [{"kind": "license", "url": "https://example.invalid"}],
        }
    )

    assert revision.status == "deferred"
    assert revision.allowed_use_cases == ()
    assert revision.license_evidence_ids == ()
    assert revision.blockers == ("source_acceptance_not_authorized",)


def test_owner_review_applying_decision_is_rejected() -> None:
    with pytest.raises(ValueError, match="only be imported as deferred"):
        parse_source_acceptance_decision_revision(
            {
                "schema_version": OWNER_REVIEW_DECISION_SCHEMA_VERSION,
                "source_id": "institutional_flows",
                "decision_revision_id": "decision:institutional_flows:accepted",
                "parent_revision_id": None,
                "status": "accepted",
                "owner_role": "owner",
                "reviewer_role": "reviewer",
                "decided_at": "2026-08-27T12:00:00+08:00",
                "rollback_reference": "owner-policy:disable",
            }
        )


def test_decision_collection_accepts_single_artifact() -> None:
    payload = {
        "schema_version": OWNER_REVIEW_DECISION_SCHEMA_VERSION,
        "source_id": "institutional_flows",
        "decision_revision_id": "decision:institutional_flows:single",
        "parent_revision_id": None,
        "status": "deferred",
        "owner_role": "owner",
        "reviewer_role": "reviewer",
        "decision_timestamp": "2026-08-27T12:00:00+08:00",
        "active_blockers": ["pending"],
        "rollback_reference": "owner-policy:disable",
    }

    revisions = parse_source_acceptance_decisions(payload)

    assert len(revisions) == 1
    assert revisions[0].decision_revision_id.endswith(":single")
