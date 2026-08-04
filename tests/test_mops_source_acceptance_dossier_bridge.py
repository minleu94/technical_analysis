from pathlib import Path
import pytest

from data_module.mops_numeric_pit_aggregator import build_mops_numeric_pit_aggregate
from data_module.mops_source_acceptance_dossier_bridge import build_mops_readiness_package


REAL_CANDIDATE_DIRS = [
    Path(r"C:\Temp\technical_analysis_development_output\dev71-mops-numeric-pit-2330-2025q1-20260729-r1"),
    Path(r"C:\Temp\technical_analysis_development_output\dev73-mops-numeric-pit-2317-2025q1-20260731-r1"),
    Path(r"C:\Temp\technical_analysis_development_output\dev74-mops-numeric-pit-2454-2025q1-20260801-r1"),
    Path(r"C:\Temp\technical_analysis_development_output\dev75-mops-numeric-pit-2308-2025q1-20260802-r1"),
]


def test_dossier_bridge_missing_license_evidence_blocked(tmp_path: Path) -> None:
    agg = build_mops_numeric_pit_aggregate(
        candidate_dirs=REAL_CANDIDATE_DIRS,
        output_root=tmp_path,
        run_id="test-dossier-agg-1",
    )
    pkg = build_mops_readiness_package(agg, license_evidence_id="")

    assert pkg.status == "blocked"
    assert "missing_license_evidence" in pkg.diagnostics
    assert "coverage_below_minimum" in pkg.diagnostics
    assert pkg.dossier.downstream_eligibility == "none"


def test_dossier_bridge_programmatic_complete_never_auto_accepted(tmp_path: Path) -> None:
    agg = build_mops_numeric_pit_aggregate(
        candidate_dirs=REAL_CANDIDATE_DIRS,
        output_root=tmp_path,
        run_id="test-dossier-agg-2",
    )
    pkg = build_mops_readiness_package(
        agg,
        license_evidence_id="artifact:license:mops:v1",
        owner_role="data_engineering_lead",
        reviewer_role="qa_lead",
        decision_timestamp="2026-08-04T00:00:00Z",
    )

    # Even when programmatic & license & reviewer present, max status is eligible_for_human_review, NEVER accepted!
    assert pkg.status == "blocked"
    assert pkg.dossier.downstream_eligibility == "none"
    assert not pkg.to_dict()["formal_acceptance_applied"]


def test_dossier_bridge_rejects_threshold_override(tmp_path: Path) -> None:
    agg = build_mops_numeric_pit_aggregate(
        candidate_dirs=REAL_CANDIDATE_DIRS,
        output_root=tmp_path,
        run_id="test-dossier-agg-threshold",
    )
    with pytest.raises(ValueError, match="fixed policy threshold"):
        build_mops_readiness_package(agg, minimum_coverage_bp=5)


def test_dossier_bridge_prohibits_formal_production_use_cases(tmp_path: Path) -> None:
    agg = build_mops_numeric_pit_aggregate(
        candidate_dirs=REAL_CANDIDATE_DIRS,
        output_root=tmp_path,
        run_id="test-dossier-agg-3",
    )
    pkg = build_mops_readiness_package(agg)
    payload = pkg.to_dict()

    assert not payload.get("formal_oos_allowed", False)
    assert payload.get("production_blend_alpha_bp", 0) == 0
    assert payload.get("downstream_eligibility") == "none"
