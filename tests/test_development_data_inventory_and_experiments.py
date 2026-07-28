"""DEV-70 comprehensive test suite for Data Inventory, Experiment Runner & Hostile Safety Checks."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
import re

import pytest

from app_module.research_console_source_service import ResearchConsoleSourceService
from development_module.contracts import DevelopmentDatasetManifest
from development_module.data_inventory import (
    DataInventoryField,
    build_development_data_inventory,
)
from development_module.experiment_contract import (
    PREDEFINED_FEATURE_PACKS,
    DevelopmentExperimentContract,
    DevelopmentExperimentRunner,
)


def _serialized_dataset_content_hash(dataset: dict[str, object]) -> str:
    def normalize_row(value: object) -> dict[str, object]:
        assert isinstance(value, dict)
        labels = value["labels"]
        assert isinstance(labels, list)
        return {
            "symbol": value["symbol"],
            "decision_date": value["decision_date"],
            "feature_as_of_date": value["feature_as_of_date"],
            "available_date": value["available_date"],
            "values": value["features"],
            "labels": [
                {
                    "id": label["label_id"],
                    "value": label["value"],
                    "horizon_end_date": label["horizon_end_date"],
                    "available_date": label["available_date"],
                    "quality": label["quality"],
                }
                for label in labels
                if isinstance(label, dict)
            ],
        }

    fit_rows = dataset["fit_rows"]
    evaluation_rows = dataset["evaluation_rows"]
    assert isinstance(fit_rows, list) and isinstance(evaluation_rows, list)
    return DevelopmentDatasetManifest.canonical_sha256({
        "fit_rows": [normalize_row(row) for row in fit_rows],
        "evaluation_rows": [normalize_row(row) for row in evaluation_rows],
    })


def _synchronize_manifest(manifest_path: Path, dataset_path: Path) -> None:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    manifest["fit_row_count"] = len(dataset["fit_rows"])
    manifest["evaluation_row_count"] = len(dataset["evaluation_rows"])
    manifest["content_hash"] = _serialized_dataset_content_hash(dataset)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")


def _write_dataset_v0(root: Path) -> tuple[Path, Path]:
    generation = root / "generations" / "terra-v0-research-test"
    generation.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema_version": "terra-development-dataset.v0",
        "generation_id": "terra-v0-research-test",
        "dataset_id": "terra-development-v0:terra-v0-research-test",
        "dataset_status": "research_only_degraded",
        "formal_oos_allowed": False,
        "production_blend_alpha_bp": 0,
        "formal_rule_only_path_unchanged": True,
        "zero_formal_write": True,
        "feature_registry_hash": "sha256:" + "a" * 64,
        "label_registry_hash": "sha256:" + "b" * 64,
        "content_hash": "",
        "manifest_hash": "sha256:" + "d" * 64,
        "training_as_of": "2025-12-31",
        "evaluation_as_of": "2026-12-31",
        "new_holdout_start": "2026-07-15",
    }
    feature_names = (
        "stock_return_1d_bp", "stock_return_5d_bp", "stock_return_20d_bp", "stock_return_60d_bp",
        "trailing_volatility_20d_bp", "high_low_range_20d_bp", "close_to_ma_5d_bp", "close_to_ma_20d_bp",
        "close_to_ma_60d_bp", "rsi_normalized_bp", "adx_normalized_bp", "macd_normalized_bp",
        "volume_ratio_5d_bp", "volume_ratio_20d_bp", "turnover_amount_minor", "market_return_5d_bp",
        "market_return_20d_bp", "market_return_60d_bp", "stock_minus_market_20d_bp", "industry_relative_return_20d_bp",
    )
    fit_rows = []
    for index in range(120):
        decision_date = date(2025, 1, 1) + timedelta(days=index)
        decision = decision_date.isoformat()
        label_available = (decision_date + timedelta(days=1)).isoformat()
        target = (index % 11 - 5) * 100
        feat_list = [[fname, (index * 10 + i * 5) % 1000] for i, fname in enumerate(feature_names)]
        fit_rows.append({
            "symbol": f"{1000 + index:04d}",
            "decision_date": decision,
            "feature_as_of_date": "2024-12-31",
            "available_date": decision,
            "features": feat_list,
            "labels": [
                {"label_id": "relative_return_20d_bp", "value": target, "horizon_end_date": label_available, "available_date": label_available, "maturity_status": "ready", "quality": "research_only"},
                {"label_id": "downside_20d_flag", "value": int(target <= -500), "horizon_end_date": label_available, "available_date": label_available, "maturity_status": "ready", "quality": "research_only"},
                {"label_id": "maximum_adverse_excursion_20d_bp", "value": target - 200, "horizon_end_date": label_available, "available_date": label_available, "maturity_status": "ready", "quality": "research_only"},
                {"label_id": "cross_sectional_top_quintile_20d_flag", "value": int(target > 200), "horizon_end_date": label_available, "available_date": label_available, "maturity_status": "ready", "quality": "research_only"},
            ],
        })
    dataset = {"fit_rows": fit_rows, "evaluation_rows": []}
    manifest_path = generation / "manifest.json"
    dataset_path = generation / "dataset.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    dataset_path.write_text(json.dumps(dataset), encoding="utf-8")
    _synchronize_manifest(manifest_path, dataset_path)
    return manifest_path, dataset_path


def test_data_inventory_reports_all_20_features_and_4_labels(tmp_path: Path) -> None:
    manifest_p, dataset_p = _write_dataset_v0(tmp_path)
    output_root = tmp_path / "dev_output"

    res = build_development_data_inventory(
        manifest_path=manifest_p,
        dataset_path=dataset_p,
        output_root=output_root,
    )

    assert res.summary["total_fields"] >= 24
    field_ids = {f.field_id for f in res.fields}
    assert "stock_return_1d_bp" in field_ids
    assert "rsi_normalized_bp" in field_ids
    assert "relative_return_20d_bp" in field_ids
    assert "downside_20d_flag" in field_ids

    # MOPS availability gate check
    mops_field = next(f for f in res.fields if f.field_id == "mops.ezsearch.statement_publication")
    assert mops_field.role == "availability_gate"
    assert mops_field.is_numeric_model_feature is False
    assert "availability_timestamp_only_no_numeric_financial_ratios" in mops_field.blockers

    # TWSE microstructure sources check
    micro_fields = [f for f in res.fields if f.family == "microstructure"]
    assert len(micro_fields) == 5
    for mf in micro_fields:
        assert mf.formal_eligible is False

    # Safety flags check
    assert res.report["safety_flags"]["formal_oos_allowed"] is False
    assert res.report["safety_flags"]["production_blend_alpha_bp"] == 0
    assert res.sanitized_projection_path.is_file()


def test_experiment_contract_executes_ablation_and_model_comparison(tmp_path: Path) -> None:
    manifest_p, dataset_p = _write_dataset_v0(tmp_path)
    output_root = tmp_path / "dev_output"
    manifest_data = json.loads(manifest_p.read_text(encoding="utf-8"))

    contract = DevelopmentExperimentContract(
        experiment_id="exp-test-ablation-v1",
        parent_dataset_id=manifest_data["dataset_id"],
        parent_dataset_manifest_hash=manifest_data["manifest_hash"],
        feature_ids=PREDEFINED_FEATURE_PACKS["technical_only"],
        model_families=("linear_logistic", "hist_gradient_boosting"),
    )

    runner = DevelopmentExperimentRunner(now=lambda: datetime(2026, 7, 28, 12, 0, tzinfo=UTC))
    res = runner.run(
        manifest_path=manifest_p,
        dataset_path=dataset_p,
        output_root=output_root,
        contract=contract,
    )

    assert res.experiment_id == "exp-test-ablation-v1"
    assert res.selected_model_family in ("linear_logistic", "hist_gradient_boosting")
    assert "linear_logistic" in res.metrics_by_family
    assert "hist_gradient_boosting" in res.metrics_by_family
    assert res.report["safety_flags"]["formal_oos_allowed"] is False
    assert res.report["safety_flags"]["production_blend_alpha_bp"] == 0
    assert res.report_file_path.is_file()
    assert res.sanitized_projection_path.is_file()


# =========================================================================
# Hostile Safety & Boundary Test Cases (Defects 1 - 8)
# =========================================================================

def test_pipeline_rejects_parent_manifest_hash_mismatch(tmp_path: Path) -> None:
    """Defect 2: Contract parent_dataset_manifest_hash mismatch fails closed."""
    manifest_p, dataset_p = _write_dataset_v0(tmp_path)
    output_root = tmp_path / "dev_output"
    manifest_data = json.loads(manifest_p.read_text(encoding="utf-8"))

    contract = DevelopmentExperimentContract(
        experiment_id="exp-hash-mismatch",
        parent_dataset_id=manifest_data["dataset_id"],
        parent_dataset_manifest_hash="sha256:" + "0" * 64,  # Mismatched hash!
        feature_ids=PREDEFINED_FEATURE_PACKS["price_only"],
    )

    runner = DevelopmentExperimentRunner()
    with pytest.raises(ValueError, match="parent_dataset_manifest_hash mismatch"):
        runner.run(
            manifest_path=manifest_p,
            dataset_path=dataset_p,
            output_root=output_root,
            contract=contract,
        )


def test_pipeline_rejects_future_label_available_date_and_non_ready_labels(tmp_path: Path) -> None:
    """Defect 3: Label available_date > cutoff or maturity_status != ready fails closed."""
    manifest_p, dataset_p = _write_dataset_v0(tmp_path)
    output_root = tmp_path / "dev_output"
    manifest_data = json.loads(manifest_p.read_text(encoding="utf-8"))

    # Corrupt label available_date to future date
    dataset = json.loads(dataset_p.read_text(encoding="utf-8"))
    dataset["fit_rows"][0]["labels"][0]["available_date"] = "2026-06-01"
    dataset_p.write_text(json.dumps(dataset), encoding="utf-8")
    _synchronize_manifest(manifest_p, dataset_p)
    manifest_data = json.loads(manifest_p.read_text(encoding="utf-8"))

    contract = DevelopmentExperimentContract(
        experiment_id="exp-future-label",
        parent_dataset_id=manifest_data["dataset_id"],
        parent_dataset_manifest_hash=manifest_data["manifest_hash"],
        feature_ids=PREDEFINED_FEATURE_PACKS["price_only"],
        training_cutoff_date="2025-12-31",
    )

    runner = DevelopmentExperimentRunner()
    with pytest.raises(ValueError, match="label available_date .* exceeds training_cutoff_date"):
        runner.run(
            manifest_path=manifest_p,
            dataset_path=dataset_p,
            output_root=output_root,
            contract=contract,
        )


def test_pipeline_rejects_feature_timing_violating_t_minus_1(tmp_path: Path) -> None:
    """Defect 3: Feature available_date > decision_date violates T-1 PIT."""
    manifest_p, dataset_p = _write_dataset_v0(tmp_path)
    output_root = tmp_path / "dev_output"

    dataset = json.loads(dataset_p.read_text(encoding="utf-8"))
    dataset["fit_rows"][0]["available_date"] = "2025-01-05"  # Decision date is 2025-01-01
    dataset_p.write_text(json.dumps(dataset), encoding="utf-8")
    _synchronize_manifest(manifest_p, dataset_p)
    manifest_data = json.loads(manifest_p.read_text(encoding="utf-8"))

    contract = DevelopmentExperimentContract(
        experiment_id="exp-t1-violation",
        parent_dataset_id=manifest_data["dataset_id"],
        parent_dataset_manifest_hash=manifest_data["manifest_hash"],
        feature_ids=PREDEFINED_FEATURE_PACKS["price_only"],
    )

    runner = DevelopmentExperimentRunner()
    with pytest.raises(ValueError, match="feature timing timing defect"):
        runner.run(
            manifest_path=manifest_p,
            dataset_path=dataset_p,
            output_root=output_root,
            contract=contract,
        )


def test_pipeline_rejects_candidate_numeric_feature_materialization(tmp_path: Path) -> None:
    """Defect 1: Candidate numeric feature materialization fails closed honestly."""
    manifest_p, dataset_p = _write_dataset_v0(tmp_path)
    output_root = tmp_path / "dev_output"
    manifest_data = json.loads(manifest_p.read_text(encoding="utf-8"))

    contract = DevelopmentExperimentContract(
        experiment_id="exp-candidate-unsupported",
        parent_dataset_id=manifest_data["dataset_id"],
        parent_dataset_manifest_hash=manifest_data["manifest_hash"],
        feature_ids=("broker.branch_flows",),
    )

    runner = DevelopmentExperimentRunner()
    with pytest.raises(ValueError, match="candidate_numeric_feature_materialization_not_implemented"):
        runner.run(
            manifest_path=manifest_p,
            dataset_path=dataset_p,
            output_root=output_root,
            contract=contract,
        )


def test_candidate_artifact_hash_validation(tmp_path: Path) -> None:
    """Defect 7: Candidate artifact expected SHA mismatch fails closed."""
    manifest_p, dataset_p = _write_dataset_v0(tmp_path)
    output_root = tmp_path / "dev_output"

    cand_file = tmp_path / "candidate_artifact.json"
    cand_file.write_text(json.dumps({"source_id": "test_src"}), encoding="utf-8")

    with pytest.raises(ValueError, match="candidate artifact hash mismatch"):
        build_development_data_inventory(
            manifest_path=manifest_p,
            dataset_path=dataset_p,
            output_root=output_root,
            candidate_artifacts=[cand_file],
            candidate_expected_hashes={cand_file.name: "sha256:" + "f" * 64},
        )


def test_sanitized_projection_contains_no_raw_local_filesystem_paths(tmp_path: Path) -> None:
    """Defect 5: Sanitized projection must NOT leak raw local filesystem absolute paths."""
    manifest_p, dataset_p = _write_dataset_v0(tmp_path)
    output_root = tmp_path / "dev_output"
    manifest_data = json.loads(manifest_p.read_text(encoding="utf-8"))

    inv_res = build_development_data_inventory(
        manifest_path=manifest_p,
        dataset_path=dataset_p,
        output_root=output_root,
    )

    proj_str = json.dumps(inv_res.projection)
    # Check no Windows / Unix absolute file paths leak into sanitized projection
    assert r"C:\Projects" not in proj_str
    assert r"tmp_path" not in proj_str
    assert str(manifest_p) not in proj_str
    assert str(dataset_p) not in proj_str

    contract = DevelopmentExperimentContract(
        experiment_id="exp-leak-test",
        parent_dataset_id=manifest_data["dataset_id"],
        parent_dataset_manifest_hash=manifest_data["manifest_hash"],
        feature_ids=PREDEFINED_FEATURE_PACKS["technical_only"],
    )
    exp_res = DevelopmentExperimentRunner().run(
        manifest_path=manifest_p,
        dataset_path=dataset_p,
        output_root=output_root,
        contract=contract,
    )

    exp_proj_str = json.dumps(exp_res.projection)
    assert str(manifest_p) not in exp_proj_str
    assert str(dataset_p) not in exp_proj_str


def test_immutable_report_exclusive_write_prevents_overwrite_collision(tmp_path: Path) -> None:
    """Defect 6: Attempting to overwrite an existing immutable report file fails closed."""
    manifest_p, dataset_p = _write_dataset_v0(tmp_path)
    output_root = tmp_path / "dev_output"
    manifest_data = json.loads(manifest_p.read_text(encoding="utf-8"))

    contract = DevelopmentExperimentContract(
        experiment_id="exp-collision-test",
        parent_dataset_id=manifest_data["dataset_id"],
        parent_dataset_manifest_hash=manifest_data["manifest_hash"],
        feature_ids=PREDEFINED_FEATURE_PACKS["price_only"],
    )

    runner = DevelopmentExperimentRunner()
    runner.run(manifest_path=manifest_p, dataset_path=dataset_p, output_root=output_root, contract=contract)

    # Re-running with same experiment_id must fail due to exclusive write!
    with pytest.raises(ValueError, match="immutable report file already exists"):
        runner.run(manifest_path=manifest_p, dataset_path=dataset_p, output_root=output_root, contract=contract)


def test_model_parameters_validates_family_and_bounded_ranges(tmp_path: Path) -> None:
    """Defect 4: Model parameters schema validation tests."""
    manifest_data = {"dataset_id": "test_id", "manifest_hash": "sha256:" + "a" * 64}

    # Invalid parameter key
    with pytest.raises(ValueError, match="unknown parameter 'invalid_key'"):
        DevelopmentExperimentContract(
            experiment_id="exp-invalid-params",
            parent_dataset_id=manifest_data["dataset_id"],
            parent_dataset_manifest_hash=manifest_data["manifest_hash"],
            feature_ids=PREDEFINED_FEATURE_PACKS["price_only"],
            model_parameters={"linear_logistic": {"invalid_key": 1.0}},
        )

    # Out of bounds range check
    with pytest.raises(ValueError, match="max_iter must be between 5 and 500"):
        DevelopmentExperimentContract(
            experiment_id="exp-invalid-range",
            parent_dataset_id=manifest_data["dataset_id"],
            parent_dataset_manifest_hash=manifest_data["manifest_hash"],
            feature_ids=PREDEFINED_FEATURE_PACKS["price_only"],
            model_parameters={"hist_gradient_boosting": {"max_iter": 9999}},
        )


def test_research_console_source_service_loads_sanitized_inventory_projection(tmp_path: Path) -> None:
    manifest_p, dataset_p = _write_dataset_v0(tmp_path)
    output_root = tmp_path / "dev_output"

    inv_res = build_development_data_inventory(
        manifest_path=manifest_p,
        dataset_path=dataset_p,
        output_root=output_root,
        now=datetime(2026, 7, 28, 12, 0, tzinfo=UTC),
    )

    service = ResearchConsoleSourceService(
        projection_path=inv_res.sanitized_projection_path,
        clock=lambda: datetime(2026, 7, 28, 12, 1, tzinfo=UTC),
    )
    dto = service.inspect()

    assert dto.overall_status in ("observed", "degraded")
    assert dto.boundary.formal_oos_allowed is False
    assert dto.boundary.production_blend_alpha_bp == 0
