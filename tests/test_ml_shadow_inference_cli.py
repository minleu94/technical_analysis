from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

import joblib

from ml_module.feature_registry import CORE_LONG_HISTORY_FEATURE_REGISTRY
from ml_module.historical_run_report import HistoricalMLShadowRunReport
from ml_module.model_artifact_manifest import ModelArtifactManifest
from ml_module.model_prediction_registries import MLShadowPredictionRegistry
from scripts.run_ml_shadow_inference import main


@dataclass(frozen=True)
class CLIControlledShadowModel:
    model_id: str = "model-1"
    dataset_id: str = "dataset-1"
    model_family: str = "core_long_history"
    shadow_only: bool = True
    production_eligible: bool = False
    production_action_allowed: bool = False

    def predict_shadow_bp(self, values: tuple[int, ...]) -> tuple[int, int, int, int]:
        assert len(values) == len(CORE_LONG_HISTORY_FEATURE_REGISTRY.specs)
        return (125, 6500, 1800, 300)


def _sha(payload: bytes) -> str:
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def _write_inputs(tmp_path: Path, *, include_artifact: bool) -> dict[str, Path | str]:
    model_root = tmp_path / "model"
    model_root.mkdir()
    if include_artifact:
        artifact_path = model_root / "model-1.joblib"
        joblib.dump(CLIControlledShadowModel(), artifact_path)
        manifest = ModelArtifactManifest.create(
            model_id="model-1",
            dataset_id="dataset-1",
            created_run_id="run-1",
            created_at="2026-07-13T12:00:00+00:00",
            model_family="core_long_history",
            feature_registry_hash=CORE_LONG_HISTORY_FEATURE_REGISTRY.registry_hash,
            label_registry_hash=_sha(b"labels"),
            feature_schema=CORE_LONG_HISTORY_FEATURE_REGISTRY.canonical_schema,
            training_as_of="2024-12-31",
            hyperparameters_hash=_sha(b"params"),
            library_versions={"python": "3.11.9"},
            serialization_format="joblib",
            artifact_filename=artifact_path.name,
            artifact_hash=_sha(artifact_path.read_bytes()),
        )
        (model_root / "manifest.json").write_text(
            json.dumps(manifest.to_dict(), sort_keys=True), encoding="utf-8"
        )
    feature_row = tmp_path / "feature-row.json"
    feature_row.write_text(
        json.dumps(
            {
                "symbol": "2330",
                "decision_date": "2025-01-03",
                "feature_as_of_date": "2025-01-02",
                "available_date": "2025-01-03",
                "values": [
                    [spec.feature_id, index * 10]
                    for index, spec in enumerate(CORE_LONG_HISTORY_FEATURE_REGISTRY.specs, start=1)
                ],
            }
        ),
        encoding="utf-8",
    )
    run_report = HistoricalMLShadowRunReport.create(
        run_id="run-1",
        dataset_id="dataset-1",
        model_id="model-1",
        training_end_date="2024-12-31",
        oos_start_date="2025-01-02",
        oos_end_date="2025-12-31",
        accepted_rows=20,
        excluded_rows=0,
        fold_ids=("fold-1",),
        metrics_bp={"mae_bp": 100},
        artifact_hashes={"model": _sha(b"lineage")},
        blockers=(),
        evidence_tier="historical_locked_oos",
        result_status="continue_shadow",
    )
    run_report_path = tmp_path / "run-report.json"
    run_report_path.write_text(json.dumps(run_report.to_dict()), encoding="utf-8")
    source_versions = tmp_path / "source-versions.json"
    source_versions.write_text(json.dumps({"fixture": "v1"}), encoding="utf-8")
    return {
        "model_root": model_root,
        "feature_row": feature_row,
        "run_report": run_report_path,
        "source_versions": source_versions,
        "source_versions_hash": _sha(b"sources"),
        "label_registry_hash": _sha(b"labels"),
    }


def _args(tmp_path: Path, inputs: dict[str, Path | str]) -> list[str]:
    return [
        "--shadow-root", str(tmp_path / "shadow"),
        "--model-root", str(inputs["model_root"]),
        "--prediction-registry", str(tmp_path / "shadow" / "predictions.sqlite"),
        "--lifecycle-registry", str(tmp_path / "shadow" / "lifecycle.sqlite"),
        "--feature-row", str(inputs["feature_row"]),
        "--run-report", str(inputs["run_report"]),
        "--source-versions", str(inputs["source_versions"]),
        "--source-versions-hash", str(inputs["source_versions_hash"]),
        "--expected-model-family", "core_long_history",
        "--expected-label-registry-hash", str(inputs["label_registry_hash"]),
        "--output-root", str(tmp_path / "shadow" / "output"),
        "--data-root", str(tmp_path / "formal-data"),
    ]


def test_controlled_cli_is_idempotent_and_rollback_stops_later_overlay(tmp_path: Path) -> None:
    inputs = _write_inputs(tmp_path, include_artifact=True)
    args = [*_args(tmp_path, inputs), "--simulate-rollback-reason", "fixture rollback"]

    assert main(args) == 0
    assert main(args) == 0

    registry = MLShadowPredictionRegistry(
        tmp_path / "shadow" / "predictions.sqlite", data_root=tmp_path / "formal-data"
    )
    assert len(registry.list_for_model("model-1")) == 1
    payload = json.loads((tmp_path / "shadow" / "output" / "ml-shadow-operation.json").read_text(encoding="utf-8"))
    assert payload["inference"]["status"] == "shadow_unavailable"
    assert payload["inference"]["blockers"] == ["lifecycle_disabled"]
    assert payload["formal_rule_unchanged"] is True
    assert payload["production_blend_alpha_bp"] == 0
    assert payload["production_scheduler_allowed"] is False
    assert payload["evidence_mode"] == "controlled_contract_path"
    assert payload["validated_artifact_observed"] is True
    assert payload["real_frozen_artifact_observed"] is False


def test_missing_real_artifact_is_reported_as_rule_only_without_fake_prediction(tmp_path: Path) -> None:
    inputs = _write_inputs(tmp_path, include_artifact=False)

    assert main(_args(tmp_path, inputs)) == 0

    payload = json.loads((tmp_path / "shadow" / "output" / "ml-shadow-operation.json").read_text(encoding="utf-8"))
    assert payload["inference"]["status"] == "shadow_unavailable"
    assert payload["inference"]["predictions"] == []
    assert payload["inference"]["blockers"] == ["artifact_unavailable:manifest_missing"]
    assert payload["real_frozen_artifact_observed"] is False


def test_cli_rejects_data_root_descendant_before_creating_output(tmp_path: Path) -> None:
    inputs = _write_inputs(tmp_path, include_artifact=False)
    args = _args(tmp_path, inputs)
    output_index = args.index("--output-root") + 1
    args[output_index] = str(tmp_path / "formal-data" / "output")

    assert main(args) == 2
    assert not (tmp_path / "formal-data" / "output").exists()
