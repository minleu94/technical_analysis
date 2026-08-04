from pathlib import Path
import json
import shutil
from hashlib import sha256
import pytest

from data_module.mops_numeric_pit_aggregator import (
    build_mops_numeric_pit_aggregate,
    validate_single_candidate_bundle,
)
from data_module.p0_source_contract_registry import (
    resolve_mops_numeric_pit_source_mapping,
)


REAL_CANDIDATE_DIRS = [
    Path(r"C:\Temp\technical_analysis_development_output\dev71-mops-numeric-pit-2330-2025q1-20260729-r1"),
    Path(r"C:\Temp\technical_analysis_development_output\dev73-mops-numeric-pit-2317-2025q1-20260731-r1"),
    Path(r"C:\Temp\technical_analysis_development_output\dev74-mops-numeric-pit-2454-2025q1-20260801-r1"),
    Path(r"C:\Temp\technical_analysis_development_output\dev75-mops-numeric-pit-2308-2025q1-20260802-r1"),
]


def test_v1_candidate_source_mapping_backwards_compatible() -> None:
    mapping = resolve_mops_numeric_pit_source_mapping(
        artifact_source_id="mops.statement.publication",
        numeric_source_id="mops.t163sb06.financial_ratio",
        availability_source_id="mops.document_listing.statement_publication",
    )
    assert not mapping.blockers
    assert mapping.governance_source_id == "pit.quarterly_financials"
    assert mapping.artifact_source_id == "mops.statement.publication"


def test_unknown_artifact_source_id_fails_closed() -> None:
    mapping = resolve_mops_numeric_pit_source_mapping(
        artifact_source_id="unknown.source.id",
        numeric_source_id="mops.t163sb06.financial_ratio",
        availability_source_id="mops.document_listing.statement_publication",
    )
    assert "unmapped_candidate_artifact_source_id" in mapping.blockers
    assert mapping.governance_source_id is None


def test_availability_lane_cannot_be_numeric_source_fails_closed() -> None:
    mapping = resolve_mops_numeric_pit_source_mapping(
        artifact_source_id="mops.ezsearch.statement_publication",
        numeric_source_id="mops.t163sb06.financial_ratio",
        availability_source_id="mops.document_listing.statement_publication",
    )
    assert "availability_lane_cannot_be_numeric_source" in mapping.blockers
    assert mapping.governance_source_id is None


def test_four_real_candidates_aggregate_exact_counts(tmp_path: Path) -> None:
    for d in REAL_CANDIDATE_DIRS:
        assert d.is_dir(), f"missing required candidate directory: {d}"

    out = build_mops_numeric_pit_aggregate(
        candidate_dirs=REAL_CANDIDATE_DIRS,
        output_root=tmp_path,
        run_id="test-run-4-candidates",
    )

    assert out["candidate_count"] == 4
    assert out["unique_identity_count"] == 4
    assert out["matching_decision_row_count"] == 470
    assert out["pit_eligible_row_count"] == 174
    assert out["canonical_denominator"] == 179271
    assert out["cumulative_coverage_bp"] == 9
    assert out["coverage_gap_bp"] == 7991
    assert out["governance_source_id"] == "pit.quarterly_financials"
    assert out["downstream_eligibility"] == "none"


def test_duplicate_candidate_fails_closed(tmp_path: Path) -> None:
    dups = [REAL_CANDIDATE_DIRS[0], REAL_CANDIDATE_DIRS[0]]
    with pytest.raises(ValueError, match="duplicate candidate identity"):
        build_mops_numeric_pit_aggregate(
            candidate_dirs=dups,
            output_root=tmp_path,
            run_id="test-dup-candidate",
        )


def test_coverage_uses_integer_division(tmp_path: Path) -> None:
    out = build_mops_numeric_pit_aggregate(
        candidate_dirs=REAL_CANDIDATE_DIRS,
        output_root=tmp_path,
        run_id="test-integer-division",
    )
    expected_bp = (174 * 10000) // 179271
    assert out["cumulative_coverage_bp"] == expected_bp == 9
    assert isinstance(out["cumulative_coverage_bp"], int)


def test_tampered_coverage_counts_fail_closed(tmp_path: Path) -> None:
    copied = tmp_path / "tampered-candidate"
    shutil.copytree(REAL_CANDIDATE_DIRS[0], copied)
    candidate_path = copied / "numeric-pit-candidate.json"
    payload = json.loads(candidate_path.read_text(encoding="utf-8"))
    coverage = payload["pit_coverage_summary"]
    coverage["canonical_dataset_row_count"] = 1
    coverage["canonical_matching_decision_row_count"] = 2
    coverage["canonical_pit_eligible_row_count"] = 2
    coverage["canonical_pit_eligible_coverage_bp"] = 20000
    candidate_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest_path = copied / "run-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"]["candidate"] = f"sha256:{sha256(candidate_path.read_bytes()).hexdigest()}"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="coverage counts"):
        validate_single_candidate_bundle(copied)


def test_run_id_cannot_escape_output_root(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="run_id"):
        build_mops_numeric_pit_aggregate(
            candidate_dirs=[REAL_CANDIDATE_DIRS[0]],
            output_root=tmp_path,
            run_id="../escaped",
        )
