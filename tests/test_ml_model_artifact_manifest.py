from __future__ import annotations

import hashlib

import pytest

from ml_module.feature_registry import CORE_LONG_HISTORY_FEATURE_REGISTRY
from ml_module.label_registry import CORE_LONG_HISTORY_LABEL_REGISTRY
from ml_module.model_artifact_manifest import ModelArtifactManifest


def _sha(value: str) -> str:
    return f"sha256:{hashlib.sha256(value.encode('utf-8')).hexdigest()}"


def _manifest(**overrides: object) -> ModelArtifactManifest:
    values: dict[str, object] = {
        "model_id": "core-linear-2024-v1",
        "dataset_id": "core-2015-2024-v1",
        "created_run_id": "historical-shadow-run-v1",
        "created_at": "2026-07-13T12:30:00+00:00",
        "model_family": "linear_regression",
        "feature_registry_hash": CORE_LONG_HISTORY_FEATURE_REGISTRY.registry_hash,
        "label_registry_hash": CORE_LONG_HISTORY_LABEL_REGISTRY.registry_hash,
        "feature_schema": CORE_LONG_HISTORY_FEATURE_REGISTRY.canonical_schema,
        "training_as_of": "2024-12-31",
        "hyperparameters_hash": _sha("linear-params"),
        "library_versions": {"python": "3.11.9", "scikit-learn": "1.5.2"},
        "serialization_format": "joblib",
        "artifact_filename": "core-linear-2024-v1.joblib",
        "artifact_hash": _sha("model-bytes"),
    }
    values.update(overrides)
    return ModelArtifactManifest.create(**values)  # type: ignore[arg-type]


def test_model_manifest_is_deterministic_hashed_and_shadow_only() -> None:
    first = _manifest()
    second = _manifest(library_versions={"scikit-learn": "1.5.2", "python": "3.11.9"})

    assert first == second
    assert first.manifest_hash.startswith("sha256:")
    assert first.frozen is True
    assert first.shadow_only is True
    assert first.production_eligible is False
    assert first.production_action_allowed is False


def test_model_manifest_round_trip_rejects_tampered_record() -> None:
    manifest = _manifest()
    assert ModelArtifactManifest.from_dict(manifest.to_dict()) == manifest

    tampered = manifest.to_dict()
    tampered["artifact_hash"] = _sha("other-model")
    with pytest.raises(ValueError, match="manifest hash mismatch"):
        ModelArtifactManifest.from_dict(tampered)

    unsafe_flags = manifest.to_dict()
    unsafe_flags["shadow_only"] = False
    with pytest.raises(ValueError, match="shadow flags"):
        ModelArtifactManifest.from_dict(unsafe_flags)


def test_model_manifest_library_versions_are_immutable() -> None:
    manifest = _manifest()

    with pytest.raises(TypeError):
        manifest.library_versions["python"] = "3.12.0"  # type: ignore[index]


def test_load_contract_rejects_registry_family_schema_and_library_mismatch() -> None:
    contract = _manifest().to_load_contract()
    contract.validate(
        expected_model_family="linear_regression",
        expected_feature_registry_hash=CORE_LONG_HISTORY_FEATURE_REGISTRY.registry_hash,
        expected_label_registry_hash=CORE_LONG_HISTORY_LABEL_REGISTRY.registry_hash,
        expected_feature_schema=CORE_LONG_HISTORY_FEATURE_REGISTRY.canonical_schema,
        installed_library_versions={"python": "3.11.8", "scikit-learn": "1.5.1"},
    )

    with pytest.raises(ValueError, match="feature registry hash mismatch"):
        contract.validate(
            expected_model_family="linear_regression",
            expected_feature_registry_hash=_sha("wrong-registry"),
            expected_label_registry_hash=CORE_LONG_HISTORY_LABEL_REGISTRY.registry_hash,
            expected_feature_schema=CORE_LONG_HISTORY_FEATURE_REGISTRY.canonical_schema,
            installed_library_versions={"python": "3.11.8", "scikit-learn": "1.5.1"},
        )
    with pytest.raises(ValueError, match="model family mismatch"):
        contract.validate(
            expected_model_family="hist_gradient_boosting",
            expected_feature_registry_hash=CORE_LONG_HISTORY_FEATURE_REGISTRY.registry_hash,
            expected_label_registry_hash=CORE_LONG_HISTORY_LABEL_REGISTRY.registry_hash,
            expected_feature_schema=CORE_LONG_HISTORY_FEATURE_REGISTRY.canonical_schema,
            installed_library_versions={"python": "3.11.8", "scikit-learn": "1.5.1"},
        )
    with pytest.raises(ValueError, match="feature schema mismatch"):
        contract.validate(
            expected_model_family="linear_regression",
            expected_feature_registry_hash=CORE_LONG_HISTORY_FEATURE_REGISTRY.registry_hash,
            expected_label_registry_hash=CORE_LONG_HISTORY_LABEL_REGISTRY.registry_hash,
            expected_feature_schema=tuple(reversed(CORE_LONG_HISTORY_FEATURE_REGISTRY.canonical_schema)),
            installed_library_versions={"python": "3.11.8", "scikit-learn": "1.5.1"},
        )
    with pytest.raises(ValueError, match="library version mismatch"):
        contract.validate(
            expected_model_family="linear_regression",
            expected_feature_registry_hash=CORE_LONG_HISTORY_FEATURE_REGISTRY.registry_hash,
            expected_label_registry_hash=CORE_LONG_HISTORY_LABEL_REGISTRY.registry_hash,
            expected_feature_schema=CORE_LONG_HISTORY_FEATURE_REGISTRY.canonical_schema,
            installed_library_versions={"python": "3.12.0", "scikit-learn": "1.5.1"},
        )

    with pytest.raises(ValueError, match="label registry hash mismatch"):
        contract.validate(
            expected_model_family="linear_regression",
            expected_feature_registry_hash=CORE_LONG_HISTORY_FEATURE_REGISTRY.registry_hash,
            expected_label_registry_hash=_sha("wrong-label-registry"),
            expected_feature_schema=CORE_LONG_HISTORY_FEATURE_REGISTRY.canonical_schema,
            installed_library_versions={"python": "3.11.8", "scikit-learn": "1.5.1"},
        )


def test_model_manifest_rejects_uncontrolled_filename_or_incomplete_hash() -> None:
    with pytest.raises(ValueError, match="artifact_filename"):
        _manifest(artifact_filename="../outside.joblib")
    with pytest.raises(ValueError, match="artifact_hash"):
        _manifest(artifact_hash="sha256:short")


def test_model_manifest_hash_freezes_research_blend_and_production_alpha_zero() -> None:
    baseline = _manifest(
        research_alpha_bp=2500,
        production_alpha_bp=0,
        blend_selection_metric="return_mae_bp",
        blend_selection_label_cutoff="2024-12-31",
        blend_selection_threshold_bp=0,
    )
    changed = _manifest(research_alpha_bp=5000)

    assert baseline.manifest_hash != changed.manifest_hash
    assert baseline.production_alpha_bp == 0
    with pytest.raises(ValueError, match="production_alpha_bp"):
        _manifest(production_alpha_bp=1)
    with pytest.raises(ValueError, match="blend_selection_label_cutoff"):
        _manifest(blend_selection_label_cutoff="2025-01-01")
