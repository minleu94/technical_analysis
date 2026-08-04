from pathlib import Path
import shutil
from unittest.mock import patch

from scripts.acquire_mops_numeric_pit_batch import execute_mops_batch


REAL_CANDIDATE = Path(r"C:\Temp\technical_analysis_development_output\dev71-mops-numeric-pit-2330-2025q1-20260729-r1")


def test_batch_max_items_enforced(tmp_path: Path) -> None:
    manifest = [
        {"stock_code": "2330", "market": "sii", "roc_year": 114, "season": 1},
        {"stock_code": "2317", "market": "sii", "roc_year": 114, "season": 1},
        {"stock_code": "2454", "market": "sii", "roc_year": 114, "season": 1},
    ]

    res = execute_mops_batch(
        manifest,
        output_root=tmp_path,
        canonical_manifest=tmp_path / "dummy_manifest.json",
        canonical_dataset=tmp_path / "dummy_dataset.json",
        max_items=2,
        dry_run=True,
    )

    assert res["max_items_requested"] == 2
    assert res["attempted"] == 2
    assert res["succeeded"] == 2


def test_batch_dry_run_mode(tmp_path: Path) -> None:
    manifest = [{"stock_code": "2330", "market": "sii", "roc_year": 114, "season": 1}]

    res = execute_mops_batch(
        manifest,
        output_root=tmp_path,
        canonical_manifest=tmp_path / "dummy_manifest.json",
        canonical_dataset=tmp_path / "dummy_dataset.json",
        max_items=1,
        dry_run=True,
    )

    assert res["dry_run"] is True
    assert res["attempted"] == 1
    assert res["failed"] == 0


def test_existing_identity_requires_expected_hash_before_fetch(tmp_path: Path) -> None:
    shutil.copytree(REAL_CANDIDATE, tmp_path / REAL_CANDIDATE.name)
    manifest = [{"stock_code": "2330", "market": "sii", "roc_year": 114, "season": 1}]
    with patch(
        "scripts.acquire_mops_numeric_pit_batch.build_candidate",
        side_effect=AssertionError("builder must not run for an unverifiable resume"),
    ) as builder:
        result = execute_mops_batch(
            manifest,
            output_root=tmp_path,
            canonical_manifest=tmp_path / "manifest.json",
            canonical_dataset=tmp_path / "dataset.json",
            max_items=1,
            rate_limit_seconds=0,
        )
    assert builder.call_count == 0
    assert result["failed"] == 1
    assert result["skipped_identical"] == 0
    assert result["failure_diagnostics"][0]["error"] == "resume_requires_expected_candidate_sha256"


def test_existing_identity_skips_with_matching_hash(tmp_path: Path) -> None:
    shutil.copytree(REAL_CANDIDATE, tmp_path / REAL_CANDIDATE.name)
    candidate_hash = "79a48a24feaf17cdf23c2782d423c2f80b1da2204dc60c3761c463c9e2e7cd94"
    manifest = [{
        "stock_code": "2330",
        "market": "sii",
        "roc_year": 114,
        "season": 1,
        "candidate_sha256": candidate_hash,
    }]
    with patch(
        "scripts.acquire_mops_numeric_pit_batch.build_candidate",
        side_effect=AssertionError("builder must not run for an identical resume"),
    ) as builder:
        result = execute_mops_batch(
            manifest,
            output_root=tmp_path,
            canonical_manifest=tmp_path / "manifest.json",
            canonical_dataset=tmp_path / "dataset.json",
            max_items=1,
            rate_limit_seconds=0,
        )
    assert builder.call_count == 0
    assert result["failed"] == 0
    assert result["skipped_identical"] == 1
