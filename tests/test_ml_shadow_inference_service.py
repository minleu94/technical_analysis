from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

import joblib

from ml_module.feature_registry import CORE_LONG_HISTORY_FEATURE_REGISTRY
from ml_module.historical_contracts import HistoricalFeatureRow
from ml_module.historical_feature_builder import HistoricalFeatureBuilder
from ml_module.historical_run_report import HistoricalMLShadowRunReport
from ml_module.model_artifact_loader import (
    ArtifactCompatibilityExpectation,
    SafeShadowModelArtifactLoader,
    ShadowModelArtifactLoadResult,
)
from ml_module.model_artifact_manifest import ModelArtifactManifest
from ml_module.model_prediction_registries import (
    MLShadowPredictionRecord,
    MLShadowPredictionRegistry,
    initialize_shadow_registry,
)
from ml_module.shadow_inference_service import OneDateShadowInferenceService


@dataclass(frozen=True)
class ControlledShadowModel:
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


def _feature_row(**overrides: object) -> HistoricalFeatureRow:
    values: dict[str, object] = {
        "symbol": "2330",
        "decision_date": "2025-01-03",
        "feature_as_of_date": "2025-01-02",
        "available_date": "2025-01-03",
        "values": tuple(
            (spec.feature_id, index * 10)
            for index, spec in enumerate(CORE_LONG_HISTORY_FEATURE_REGISTRY.specs, start=1)
        ),
    }
    values.update(overrides)
    return HistoricalFeatureRow(**values)  # type: ignore[arg-type]


def _run_report(**overrides: object) -> HistoricalMLShadowRunReport:
    values: dict[str, object] = {
        "run_id": "run-1",
        "dataset_id": "dataset-1",
        "model_id": "model-1",
        "training_end_date": "2024-12-31",
        "oos_start_date": "2025-01-02",
        "oos_end_date": "2025-12-31",
        "accepted_rows": 20,
        "excluded_rows": 0,
        "fold_ids": ("fold-1",),
        "metrics_bp": {"mae_bp": 100},
        "artifact_hashes": {"model": _sha(b"model-lineage")},
        "blockers": (),
        "evidence_tier": "historical_locked_oos",
        "result_status": "continue_shadow",
    }
    values.update(overrides)
    return HistoricalMLShadowRunReport.create(**values)  # type: ignore[arg-type]


def _loaded_artifact(root: Path) -> ShadowModelArtifactLoadResult:
    root.mkdir(parents=True)
    artifact_path = root / "model-1.joblib"
    joblib.dump(ControlledShadowModel(), artifact_path)
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
    (root / "manifest.json").write_text(
        json.dumps(manifest.to_dict(), sort_keys=True), encoding="utf-8"
    )
    return SafeShadowModelArtifactLoader(data_root=root.parent / "formal-data").load(
        root,
        expectation=ArtifactCompatibilityExpectation(
            expected_model_family="core_long_history",
            expected_feature_registry_hash=CORE_LONG_HISTORY_FEATURE_REGISTRY.registry_hash,
            expected_label_registry_hash=_sha(b"labels"),
            expected_feature_schema=CORE_LONG_HISTORY_FEATURE_REGISTRY.canonical_schema,
            installed_library_versions={"python": "3.11.8"},
        ),
    )


def _service(tmp_path: Path) -> tuple[OneDateShadowInferenceService, MLShadowPredictionRegistry]:
    db_path = tmp_path / "shadow" / "predictions.sqlite"
    initialize_shadow_registry(db_path, data_root=tmp_path / "formal-data")
    registry = MLShadowPredictionRegistry(db_path, data_root=tmp_path / "formal-data")
    return OneDateShadowInferenceService(HistoricalFeatureBuilder(), registry), registry


def _run(service: OneDateShadowInferenceService, artifact: ShadowModelArtifactLoadResult, **overrides: object):
    builder = HistoricalFeatureBuilder()
    values: dict[str, object] = {
        "feature_row": _feature_row(),
        "artifact": artifact,
        "run_report": _run_report(),
        "source_versions": {"historical_fixture": "v1"},
        "source_versions_hash": _sha(b"sources"),
        "expected_builder_contract_hash": builder.load_contract.contract_hash,
        "expected_builder_schema_hash": builder.load_contract.schema_hash,
    }
    values.update(overrides)
    return service.run_one_date(**values)  # type: ignore[arg-type]


def test_one_date_controlled_inference_is_idempotently_appended(tmp_path: Path) -> None:
    service, registry = _service(tmp_path)
    artifact = _loaded_artifact(tmp_path / "artifact")

    first = _run(service, artifact)
    second = _run(service, artifact)

    assert first == second
    assert first.status == "shadow_available"
    assert first.production_blend_alpha_bp == 0
    assert first.formal_rule_unchanged is True
    assert first.production_action_allowed is False
    assert first.predictions[0].return_prediction_bp == 125
    persisted = registry.list_for_model("model-1")
    assert len(persisted) == 1
    assert persisted[0].ranking_score == 6500
    assert persisted[0].feature_snapshot_hash == first.request.feature_snapshot_hash


def test_builder_contract_or_missing_value_falls_back_without_write(tmp_path: Path) -> None:
    service, registry = _service(tmp_path)
    artifact = _loaded_artifact(tmp_path / "artifact")
    missing_values = list(_feature_row().values)
    missing_values[0] = (missing_values[0][0], None)

    contract_result = _run(service, artifact, expected_builder_contract_hash=_sha(b"wrong"))
    missing_result = _run(service, artifact, feature_row=_feature_row(values=tuple(missing_values)))

    assert contract_result.blockers == ("feature_builder_contract_mismatch",)
    assert missing_result.blockers == ("missing_feature_values",)
    assert contract_result.status == missing_result.status == "shadow_unavailable"
    assert registry.list_for_model("model-1") == ()


def test_artifact_fallback_and_run_identity_mismatch_remain_rule_only(tmp_path: Path) -> None:
    service, registry = _service(tmp_path)
    unavailable = ShadowModelArtifactLoadResult.fallback("manifest_missing")
    wrong_run = _run_report(model_id="other-model")

    artifact_result = _run(service, unavailable)
    run_result = _run(
        service,
        _loaded_artifact(tmp_path / "artifact"),
        run_report=wrong_run,
    )

    assert artifact_result.blockers == ("artifact_unavailable:manifest_missing",)
    assert run_result.blockers == ("historical_run_identity_mismatch",)
    assert registry.list_for_model("model-1") == ()


def test_prediction_registry_conflict_fails_closed_without_overwrite(tmp_path: Path) -> None:
    service, registry = _service(tmp_path)
    artifact = _loaded_artifact(tmp_path / "artifact")
    successful = _run(service, artifact)
    original = registry.list_for_model("model-1")[0]
    conflicting = MLShadowPredictionRecord(
        **{**original.__dict__, "return_prediction_bp": 999}
    )

    db_path = tmp_path / "other" / "predictions.sqlite"
    initialize_shadow_registry(db_path, data_root=tmp_path / "formal-data")
    conflicting_registry = MLShadowPredictionRegistry(db_path, data_root=tmp_path / "formal-data")
    conflicting_registry.append(conflicting)
    conflict_service = OneDateShadowInferenceService(HistoricalFeatureBuilder(), conflicting_registry)
    result = _run(conflict_service, artifact)

    assert successful.status == "shadow_available"
    assert result.status == "shadow_unavailable"
    assert result.blockers == ("prediction_registry_conflict",)
    assert conflicting_registry.list_for_model("model-1") == (conflicting,)
