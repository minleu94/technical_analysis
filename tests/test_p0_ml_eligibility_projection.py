import importlib
import json
from pathlib import Path


def _module():
    try:
        return importlib.import_module("data_module.p0_ml_eligibility_projection")
    except ModuleNotFoundError:
        return None


def _candidate(**overrides: str) -> dict[str, str]:
    row = {
        "natural_key": "2330|monthly_revenue|2024-04",
        "available_at": "2024-05-10",
        "feature_cutoff": "2024-05-11",
        "quality_tier": "official",
        "label_start": "2024-05-13",
        "label_end": "2024-06-13",
        "corporate_source_id": "corporate_action.ex_dividend_timeline",
    }
    row.update(overrides)
    return row


def _coverage(quality: str = "official") -> dict[str, str]:
    return {
        "source_id": "corporate_action.ex_dividend_timeline",
        "coverage_start": "2024-01-01" if quality != "unknown" else "",
        "coverage_end": "2024-12-31" if quality != "unknown" else "",
        "quality": quality,
    }


def test_strict_projection_blocks_backfill_future_and_unknown_coverage() -> None:
    module = _module()
    assert module is not None, "p0 ML eligibility projection contract is missing"
    artifact = module.project_p0_ml_eligibility(
        candidates=(
            _candidate(),
            _candidate(
                natural_key="2330|statement|2024-Q1",
                available_at="2026-06-17",
                feature_cutoff="2024-05-11",
                quality_tier="retroactive_baseline",
            ),
            _candidate(
                natural_key="2317|monthly_revenue|2024-04",
                corporate_source_id="corporate_action.reduction_split_par_value",
            ),
        ),
        mapping_hashes={"monthly": "a" * 64, "quarterly": "b" * 64},
        corporate_coverage=(
            _coverage(),
            {
                "source_id": "corporate_action.reduction_split_par_value",
                "coverage_start": "",
                "coverage_end": "",
                "quality": "unknown",
            },
        ),
        mode="strict",
    )

    assert artifact.schema_version == "p0-ml-eligibility.v1"
    assert artifact.eligible_keys == ("2330|monthly_revenue|2024-04",)
    assert artifact.blocked_keys == (
        "2317|monthly_revenue|2024-04",
        "2330|statement|2024-Q1",
    )
    assert artifact.reason_counts["coverage_unknown"] == 1
    assert artifact.reason_counts["retroactive_backfill_not_historical_availability"] == 1
    assert artifact.reason_counts["available_after_feature_cutoff"] == 1
    assert len(artifact.canonical_hash) == 64
    assert artifact.formal_oos_allowed is False


def test_research_projection_marks_unknown_coverage_degraded() -> None:
    module = _module()
    assert module is not None, "p0 ML eligibility projection contract is missing"
    artifact = module.project_p0_ml_eligibility(
        candidates=(_candidate(),),
        mapping_hashes={"monthly": "a" * 64},
        corporate_coverage=(_coverage("unknown"),),
        mode="research",
    )

    assert artifact.eligible_keys == ()
    assert artifact.blocked_keys == ()
    assert artifact.degraded_keys == ("2330|monthly_revenue|2024-04",)
    assert artifact.formal_oos_allowed is False


def test_projection_writer_does_not_hash_machine_specific_output_path(tmp_path: Path) -> None:
    module = _module()
    assert module is not None, "p0 ML eligibility projection contract is missing"
    artifact = module.project_p0_ml_eligibility(
        candidates=(_candidate(),),
        mapping_hashes={"monthly": "a" * 64},
        corporate_coverage=(_coverage(),),
        mode="strict",
    )

    first = module.write_p0_ml_eligibility(artifact, output_root=tmp_path / "one")
    second = module.write_p0_ml_eligibility(artifact, output_root=tmp_path / "two")

    assert first.parent == (tmp_path / "one").resolve()
    assert second.parent == (tmp_path / "two").resolve()
    assert first.read_bytes() == second.read_bytes()


def test_projection_cli_writes_only_explicit_output_root(tmp_path: Path) -> None:
    candidates = tmp_path / "candidates.json"
    coverage = tmp_path / "coverage.json"
    hashes = tmp_path / "hashes.json"
    output_root = tmp_path / "staging"
    candidates.write_text(json.dumps([_candidate()]), encoding="utf-8")
    coverage.write_text(json.dumps([_coverage()]), encoding="utf-8")
    hashes.write_text(json.dumps({"monthly": "a" * 64}), encoding="utf-8")
    try:
        cli = importlib.import_module("scripts.project_p0_ml_eligibility")
    except ModuleNotFoundError:
        cli = None
    assert cli is not None, "p0 ML eligibility CLI is missing"

    result = cli.main(
        [
            "--candidates-json",
            str(candidates),
            "--mapping-hashes-json",
            str(hashes),
            "--corporate-coverage-json",
            str(coverage),
            "--mode",
            "strict",
            "--output-root",
            str(output_root),
        ]
    )

    assert result == 0
    assert (output_root / "p0-ml-eligibility.v1.json").exists()
