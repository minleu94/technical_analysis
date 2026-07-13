from pathlib import Path

import pytest

from ml_module.model_artifact_store import (
    ShadowModelArtifactManifest,
    ShadowModelArtifactStore,
)


def _manifest(payload: bytes = b"fixture-model") -> ShadowModelArtifactManifest:
    return ShadowModelArtifactManifest.create(
        model_id="model-1",
        dataset_id="dataset-1",
        feature_registry_hash="sha256:features",
        label_registry_hash="sha256:labels",
        model_family="hist_gradient_boosting",
        training_cutoff="2024-12-31",
        created_run_id="run-1",
        library_versions={"python": "3.11"},
        artifact_bytes=payload,
    )


def test_store_round_trips_hash_verified_shadow_artifact(tmp_path: Path) -> None:
    store = ShadowModelArtifactStore(tmp_path / "shadow-models", data_root=tmp_path / "formal-data")
    manifest = _manifest()

    artifact_path = store.save(manifest, b"fixture-model")

    loaded = store.load(
        "model-1",
        expected_feature_registry_hash="sha256:features",
        expected_model_family="hist_gradient_boosting",
    )
    assert artifact_path.is_file()
    assert loaded.manifest == manifest
    assert loaded.artifact_bytes == b"fixture-model"


def test_store_rejects_data_root_and_non_shadow_manifest(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="DATA_ROOT"):
        ShadowModelArtifactStore(tmp_path / "data" / "models", data_root=tmp_path / "data")

    manifest = _manifest()
    with pytest.raises(ValueError, match="shadow-only"):
        ShadowModelArtifactManifest(**{**manifest.__dict__, "shadow_only": False})


def test_load_fails_closed_for_missing_manifest_hash_and_schema_mismatch(tmp_path: Path) -> None:
    store = ShadowModelArtifactStore(tmp_path / "shadow-models", data_root=tmp_path / "formal-data")
    store.save(_manifest(), b"fixture-model")

    (tmp_path / "shadow-models" / "model-1" / "artifact.bin").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="artifact hash"):
        store.load("model-1")

    (tmp_path / "shadow-models" / "model-1" / "artifact.bin").write_bytes(b"fixture-model")
    with pytest.raises(ValueError, match="feature registry"):
        store.load("model-1", expected_feature_registry_hash="sha256:other")


def test_identical_save_is_idempotent_but_conflicting_content_is_rejected(tmp_path: Path) -> None:
    store = ShadowModelArtifactStore(tmp_path / "shadow-models", data_root=tmp_path / "formal-data")
    manifest = _manifest()
    first = store.save(manifest, b"fixture-model")

    assert store.save(manifest, b"fixture-model") == first
    with pytest.raises(ValueError, match="conflict"):
        store.save(_manifest(b"different"), b"different")
