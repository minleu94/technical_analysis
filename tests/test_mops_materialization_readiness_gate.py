from pathlib import Path
import pytest

from data_module.mops_numeric_pit_aggregator import build_mops_numeric_pit_aggregate
from data_module.mops_materialization_readiness_gate import (
    check_mops_materialization_readiness,
    materialize_development_feature_overlay,
)
from data_module.source_acceptance_governance import SourceAcceptanceDossier


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


def test_materialization_succeeds_only_when_preflight_passes(tmp_path: Path) -> None:
    agg = build_mops_numeric_pit_aggregate(
        candidate_dirs=REAL_CANDIDATE_DIRS,
        output_root=tmp_path,
        run_id="test-mat-agg-3",
    )

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
        coverage_numerator=174,
        coverage_denominator=179271,
        missing_policy="fail_closed",
        row_conservation_counts={"canonical_rows": 179271},
        quarantine_policy="verified",
        quality_thresholds={"minimum_coverage_bp": 5},
        downstream_use_cases=("development_feature_materialization",),
        downstream_eligibility="none",
        disable_conditions=("license_revoked",),
        rollback_reference="decision:pit.quarterly_financials:none",
        evidence_artifact_ids=("license:artifact:v1", "pit:eligible_rows:174"),
        reviewer_role="qa_lead",
        decision_timestamp="2026-08-04T00:00:00Z",
    )

    cand_rows = [
        {
            "stock_code": "2330",
            "period": "2025-Q1",
            "available_date": "2025-05-16",
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
        minimum_coverage_bp=5,
    )

    assert overlay["matched_pit_row_count"] == 1
    assert overlay["canonical_row_count"] == 2
    assert overlay["overlay_rows"][0]["pit_available_date"] == "2025-05-16"
    assert overlay["overlay_rows"][0]["revenue_twd_cents"] == 100000
    assert overlay["overlay_rows"][1]["pit_available_date"] is None
