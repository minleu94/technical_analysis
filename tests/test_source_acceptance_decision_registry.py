from pathlib import Path

import pytest

from data_module.source_acceptance_decision_registry import (
    SourceAcceptanceDecisionRegistry,
    SourceAcceptanceDecisionRevision,
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
