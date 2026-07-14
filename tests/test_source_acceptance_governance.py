from data_module.p0_source_contract_registry import build_p0_source_contract_registry
from data_module.source_acceptance_governance import (
    SourceAcceptanceDossier,
    SourceAcceptanceGovernance,
)


def _candidate_dossier(**changes: object) -> SourceAcceptanceDossier:
    values: dict[str, object] = {
        "source_id": "institutional_flows",
        "source_owner_role": "Data Source Owner",
        "license_owner_role": "License/Legal Owner",
        "license_status": "requires_review",
        "license_scope": "not_decided",
        "redistribution_policy": "not_decided",
        "source_status": "candidate",
        "publication_time_policy": "daily publication window unverified",
        "timezone": "Asia/Taipei",
        "available_date_policy": "explicit and not later than decision time",
        "revision_policy": "not_evidenced",
        "pit_coverage_window": "not_evidenced",
        "coverage_numerator": 10,
        "coverage_denominator": 10,
        "missing_policy": "fail_closed",
        "row_conservation_counts": {"raw": 10, "accepted_candidate": 10},
        "quarantine_policy": "malformed rows isolated",
        "quality_thresholds": {"minimum_coverage_bp": 8000},
        "downstream_use_cases": (),
        "disable_conditions": ("license_not_accepted",),
        "rollback_reference": "decision:future-disable-revision",
        "evidence_artifact_ids": ("http:200", "parser:passed"),
    }
    values.update(changes)
    return SourceAcceptanceDossier(**values)


def test_p0_denominator_remains_thirteen_and_excludes_broker_lane() -> None:
    contracts = build_p0_source_contract_registry().list()

    report = SourceAcceptanceGovernance().project(contracts, decisions=())

    assert report.p0_source_count == 13
    assert "broker_branch.revalidation" not in report.p0_source_ids
    assert report.broker_lane_source_id == "broker_branch.revalidation"


def test_http_and_parser_success_do_not_accept_source() -> None:
    decision = SourceAcceptanceGovernance().evaluate(_candidate_dossier())

    assert decision.status == "deferred"
    assert decision.allowed_use_cases == ()
    assert decision.parent_revision_id is None
    assert decision.license_evidence_ids == ()
    assert decision.quality_evidence_ids == ()
    assert decision.pit_evidence_ids == ()
    assert "license_not_accepted" in decision.blockers
    assert "source_acceptance_not_authorized" in decision.blockers


def test_governance_evaluation_returns_registry_compatible_revision() -> None:
    decision = SourceAcceptanceGovernance().evaluate(
        _candidate_dossier(
            decision_revision_id="candidate-revision-1",
            reviewer_role="Data Governance Reviewer",
            decision_timestamp="2026-07-13T09:00:00+08:00",
            evidence_artifact_ids=("license:reviewed", "quality:verified", "pit:verified"),
        )
    )

    assert decision.decision_revision_id == "candidate-revision-1"
    assert decision.owner_role == "Data Source Owner"
    assert decision.reviewer_role == "Data Governance Reviewer"
    assert decision.decided_at == "2026-07-13T09:00:00+08:00"
    assert decision.license_evidence_ids == ("license:reviewed",)
    assert decision.quality_evidence_ids == ("quality:verified",)
    assert decision.pit_evidence_ids == ("pit:verified",)


def test_complete_candidate_still_cannot_be_accepted_in_wave_2a() -> None:
    dossier = _candidate_dossier(
        license_status="approved",
        license_scope="internal_research",
        redistribution_policy="prohibited",
        source_status="verified_candidate",
        publication_time_policy="official publication timestamp retained",
        revision_policy="immutable revision chain retained",
        pit_coverage_window="2020-01-01 through 2026-07-12",
        quality_thresholds={"minimum_coverage_bp": 8000, "passed": True},
        downstream_use_cases=("research",),
        downstream_eligibility="research_only",
        reviewer_role="Data Governance Owner",
        decision_timestamp="2026-07-13T09:00:00+08:00",
        decision_revision_id="candidate-revision-1",
        evidence_artifact_ids=(
            "license:reviewed",
            "pit:verified",
            "quality:verified",
            "coverage:10000bp",
            "row-conservation:verified",
            "quarantine:verified",
        ),
    )

    decision = SourceAcceptanceGovernance().evaluate(dossier)

    assert decision.status == "deferred"
    assert decision.allowed_use_cases == ()
    assert "source_acceptance_not_authorized" in decision.blockers


def test_missing_required_evidence_fails_closed_with_no_allowed_use_cases() -> None:
    dossier = _candidate_dossier(
        source_owner_role="",
        license_owner_role="",
        publication_time_policy="",
        available_date_policy="",
        revision_policy="",
        pit_coverage_window="",
        row_conservation_counts={},
        quarantine_policy="",
        quality_thresholds={},
        downstream_eligibility="",
        rollback_reference="",
    )

    decision = SourceAcceptanceGovernance().evaluate(dossier)

    assert decision.status == "deferred"
    assert decision.allowed_use_cases == ()
    assert set(decision.blockers) >= {
        "missing_source_owner",
        "missing_license_owner",
        "missing_publication_time_policy",
        "missing_available_date_policy",
        "missing_revision_policy",
        "missing_pit_coverage",
        "missing_row_conservation",
        "missing_quarantine_policy",
        "missing_quality_thresholds",
        "missing_downstream_eligibility",
        "missing_rollback_reference",
    }
