from pathlib import Path
import pytest

from data_module.mops_numeric_pit_aggregator import build_mops_numeric_pit_aggregate
from data_module.mops_materialization_readiness_gate import (
    check_mops_materialization_readiness,
    materialize_development_feature_overlay,
)
from data_module.source_acceptance_governance import SourceAcceptanceDossier
from data_module.source_acceptance_decision_registry import SourceAcceptanceDecisionRevision


REAL_CANDIDATE_DIRS = [
    Path(r"C:\Temp\technical_analysis_development_output\dev71-mops-numeric-pit-2330-2025q1-20260729-r1"),
    Path(r"C:\Temp\technical_analysis_development_output\dev73-mops-numeric-pit-2317-2025q1-20260731-r1"),
    Path(r"C:\Temp\technical_analysis_development_output\dev74-mops-numeric-pit-2454-2025q1-20260801-r1"),
    Path(r"C:\Temp\technical_analysis_development_output\dev75-mops-numeric-pit-2308-2025q1-20260802-r1"),
]


def test_materialization_preflight_rejects_under_current_real_conditions(tmp_path: Path) -> None:
    agg = build_mops_numeric_pit_aggregate(
        candidate_dirs=REAL_CANDIDATE_DIRS,
        output_root=tmp_path,
        run_id="test-mat-agg-1",
    )

    res = check_mops_materialization_readiness(agg)

    assert not res.materialization_ready
    assert "coverage_below_minimum" in res.active_blockers
    assert "missing_license_evidence" in res.active_blockers
    assert "missing_owner_reviewer_decision" in res.active_blockers
    assert "unauthorized_use_case" in res.active_blockers


def test_materialization_raises_error_when_preflight_fails(tmp_path: Path) -> None:
    agg = build_mops_numeric_pit_aggregate(
        candidate_dirs=REAL_CANDIDATE_DIRS,
        output_root=tmp_path,
        run_id="test-mat-agg-2",
    )

    with pytest.raises(PermissionError, match="materialization preflight failed"):
        materialize_development_feature_overlay(
            aggregate_payload=agg,
            canonical_dataset_payload={"fit_rows": []},
            candidate_rows=[],
        )


def test_materialization_requires_registered_applying_revision(tmp_path: Path) -> None:
    agg = build_mops_numeric_pit_aggregate(
        candidate_dirs=REAL_CANDIDATE_DIRS,
        output_root=tmp_path,
        run_id="test-mat-agg-unregistered",
    )
    dossier = SourceAcceptanceDossier(
        source_id="pit.quarterly_financials",
        source_owner_role="owner",
        license_owner_role="legal",
        license_status="approved",
        license_scope="research",
        redistribution_policy="internal",
        source_status="research_candidate",
        publication_time_policy="verified",
        timezone="Asia/Taipei",
        available_date_policy="verified",
        revision_policy="verified",
        pit_coverage_window="bounded",
        coverage_numerator=174,
        coverage_denominator=179271,
        missing_policy="fail_closed",
        row_conservation_counts={"canonical_rows": 179271},
        quarantine_policy="verified",
        quality_thresholds={"minimum_coverage_bp": 8000},
        downstream_use_cases=("development_feature_materialization",),
        downstream_eligibility="none",
        disable_conditions=("license_revoked",),
        rollback_reference="decision:pit.quarterly_financials:none",
        evidence_artifact_ids=("license:arbitrary",),
        reviewer_role="reviewer",
        decision_timestamp="2026-08-04T00:00:00Z",
    )
    result = check_mops_materialization_readiness(agg, dossier)
    assert not result.materialization_ready
    assert "missing_registered_decision_revision" in result.active_blockers
    assert "coverage_below_minimum" in result.active_blockers


def test_materialization_rejects_forged_aggregate_claims() -> None:
    forged = {
        "schema_version": "mops-numeric-pit-aggregate.v1",
        "research_only": True,
        "candidate_count": 1,
        "unique_identity_count": 1,
        "matching_decision_row_count": 1,
        "pit_eligible_row_count": 1,
        "canonical_denominator": 1,
        "cumulative_coverage_bp": 10000,
        "minimum_coverage_bp": 8000,
        "coverage_gap_bp": 0,
        "formal_oos_allowed": False,
        "formal_evidence_credit_authorized": False,
        "production_blend_alpha_bp": 0,
        "downstream_eligibility": "none",
    }

    result = check_mops_materialization_readiness(forged)

    assert not result.materialization_ready
    assert result.coverage_bp == 0
    assert "invalid_aggregate_contract" in result.active_blockers
    assert "invalid_source_identity_mapping" in result.active_blockers
    assert "missing_license_evidence" in result.active_blockers


def test_materialization_succeeds_only_when_preflight_passes(tmp_path: Path) -> None:
    candidate_hash = "sha256:" + "1" * 64
    manifest_hash = "sha256:" + "2" * 64
    agg = {
        "schema_version": "mops-numeric-pit-aggregate.v1",
        "generated_at": "2026-08-04T00:00:00+00:00",
        "research_only": True,
        "governance_source_id": "pit.quarterly_financials",
        "artifact_source_id": "mops.statement.publication",
        "numeric_source_id": "mops.t163sb06.financial_ratio",
        "availability_source_id": "mops.document_listing.statement_publication",
        "source_identity_mapping": {
            "artifact_source_id": "mops.statement.publication",
            "numeric_source_id": "mops.t163sb06.financial_ratio",
            "availability_source_id": "mops.document_listing.statement_publication",
            "governance_source_id": "pit.quarterly_financials",
            "mapping_version": "p0-candidate-source-alignment.v1",
            "blockers": [],
        },
        "canonical_manifest_sha256": manifest_hash,
        "canonical_dataset_sha256": "sha256:" + "3" * 64,
        "candidate_count": 1,
        "unique_identity_count": 1,
        "matching_decision_row_count": 1,
        "pit_eligible_row_count": 1,
        "canonical_denominator": 1,
        "cumulative_coverage_bp": 10000,
        "minimum_coverage_bp": 8000,
        "coverage_gap_bp": 0,
        "candidates": [{
            "run_id": "test-run",
            "stock_code": "2330",
            "period": "2025-Q1",
            "available_date": "2025-05-16",
            "candidate_sha256": candidate_hash,
            "manifest_sha256": manifest_hash,
        }],
        "rejected_diagnostics": [],
        "source_acceptance_readiness_diagnostics": [],
        "formal_oos_allowed": False,
        "formal_evidence_credit_authorized": False,
        "production_blend_alpha_bp": 0,
        "downstream_eligibility": "none",
    }

    dossier = SourceAcceptanceDossier(
        source_id="pit.quarterly_financials",
        source_owner_role="data_engineering_lead",
        license_owner_role="legal_compliance_officer",
        license_status="approved",
        license_scope="research_development_only",
        redistribution_policy="internal_research_only",
        source_status="research_candidate",
        publication_time_policy="verified",
        timezone="Asia/Taipei",
        available_date_policy="conservative_next_day",
        revision_policy="verified",
        pit_coverage_window="2025_q1",
        coverage_numerator=1,
        coverage_denominator=1,
        missing_policy="fail_closed",
        row_conservation_counts={"canonical_rows": 179271},
        quarantine_policy="verified",
        quality_thresholds={"minimum_coverage_bp": 8000},
        downstream_use_cases=("development_feature_materialization",),
        downstream_eligibility="limited",
        disable_conditions=("license_revoked",),
        rollback_reference="decision:pit.quarterly_financials:20260804-r1",
        evidence_artifact_ids=("license:artifact:v1", "quality:artifact:v1", "pit:artifact:v1"),
        reviewer_role="qa_lead",
        decision_timestamp="2026-08-04T00:00:00Z",
        decision_revision_id="decision:pit.quarterly_financials:20260804-r1",
    )

    decision = SourceAcceptanceDecisionRevision(
        source_id="pit.quarterly_financials",
        decision_revision_id="decision:pit.quarterly_financials:20260804-r1",
        parent_revision_id=None,
        status="limited",
        allowed_use_cases=("development_feature_materialization",),
        blockers=(),
        license_evidence_ids=("license:artifact:v1",),
        quality_evidence_ids=("quality:artifact:v1",),
        pit_evidence_ids=("pit:artifact:v1",),
        owner_role="data_engineering_lead",
        reviewer_role="qa_lead",
        decided_at="2026-08-04T00:00:00Z",
        rollback_reference="decision:pit.quarterly_financials:20260804-r1",
    )

    cand_rows = [
        {
            "stock_code": "2330",
            "period": "2025-Q1",
            "available_date": "2025-05-15",
            "revision": 1,
            "candidate_sha256": candidate_hash,
            "statement_items": {
                "revenue_twd_cents": 1,
                "gross_margin_bp": 1,
                "operating_margin_bp": 1,
                "pretax_margin_bp": 1,
                "net_margin_bp": 1,
            },
        },
        {
            "stock_code": "2330",
            "period": "2025-Q1",
            "available_date": "2025-05-16",
            "revision": 1,
            "candidate_sha256": candidate_hash,
            "statement_items": {
                "revenue_twd_cents": 100000,
                "gross_margin_bp": 5200,
                "operating_margin_bp": 4200,
                "pretax_margin_bp": 4400,
                "net_margin_bp": 3800,
            },
        }
    ]

    dataset = {
        "fit_rows": [
            {"symbol": "2330", "decision_date": "2025-05-20"},
            {"symbol": "2330", "decision_date": "2025-05-10"},  # before available_date -> unmatched
        ]
    }

    overlay = materialize_development_feature_overlay(
        aggregate_payload=agg,
        canonical_dataset_payload=dataset,
        candidate_rows=cand_rows,
        dossier=dossier,
        decision_revision=decision,
    )

    assert overlay["matched_pit_row_count"] == 1
    assert overlay["canonical_row_count"] == 2
    assert overlay["overlay_rows"][0]["pit_available_date"] == "2025-05-16"
    assert overlay["overlay_rows"][0]["revenue_twd_cents"] == 100000
    assert overlay["overlay_rows"][1]["pit_available_date"] is None
